"""ボイス作成ドメインのロジック (UI非依存)。

app.py から分離。サンプル生成(custom/design/clone)・BGM除去・ボイスカード保存/
削除/試聴・トレイアイコン設定。UI(ui_voice_create.py / app.py)から呼ばれる。
エンジン/設定/進捗は engine_control の共有層を使う。
"""
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import gradio as gr
import numpy as np
import soundfile as sf

from voice.voice_manager import VoiceConfig
from engine.audio_utils import trim_silence, trim_interior_pauses, adjust_speed
from engine.engine_control import (
    cfg, vm, monitor, get_engine, mark_generating, _wait_for_preload,
)


def refresh_voice_list():
    return gr.update(choices=vm.get_voice_choices())


def test_saved_voice(voice_name, test_text, test_instruct):
    """Generate audio using a saved voice card for preview."""
    if not voice_name:
        return None, "ボイスを選択してください"
    if not test_text or not test_text.strip():
        return None, "テキストを入力してください"
    try:
        vc = vm.load_voice(voice_name)
        vm.touch_voice(voice_name)
        eng = get_engine()
        monitor.start(f"ボイステスト: {voice_name}")

        instruct = test_instruct.strip() if test_instruct else ""

        t0 = time.time()
        if vc.voice_type == "custom":
            # Combine attribute + user instruct
            full_instruct = type(eng).build_instruct(vc.attribute, "", instruct, cfg.instruct_template) if vc.attribute else instruct
            results = eng.generate_custom_voice(
                text=test_text, language=vc.language,
                speaker=vc.speaker, instruct=full_instruct,
            )
            wav, sr = results[0]
        elif vc.voice_type == "design":
            full_instruct = vc.voice_description
            if vc.attribute:
                full_instruct += f"。{vc.attribute}"
            if instruct:
                full_instruct += f"。{instruct}"
            results = eng.generate_voice_design(
                text=test_text, language=vc.language,
                instruct=full_instruct, num_samples=1, seed=vc.seed,
            )
            (wav, sr), _ = results[0]
        elif vc.voice_type == "clone":
            # Irodori は ref_text を使わないので、参照音声さえあれば再生成できる。
            _need_reftext = (cfg.tts_engine_type != "irodori")
            if not vc.ref_audio_path or (_need_reftext and not vc.ref_text):
                monitor.finish("クローンボイスはref_audioとref_textが必要です")
                return None, "クローンボイスの参照データが不足しています"
            results = eng.generate_voice_clone(
                text=test_text, language=vc.language,
                ref_audio=vc.ref_audio_path, ref_text=vc.ref_text,
                seed=vc.seed,  # daemon/バッチと同じ seed で試聴する (-1 ならランダム)
            )
            wav, sr = results[0]
        else:
            return None, f"不明なボイスタイプ: {vc.voice_type}"

        elapsed = time.time() - t0
        audio_len = len(wav) / sr
        msg = f"生成完了 ({elapsed:.1f}s / 音声{audio_len:.1f}s) [{vc.voice_type}]"
        if vc.seed >= 0:
            msg += f" seed={vc.seed}"
        monitor.finish(msg)
        return (sr, wav), msg
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return None, f"エラー: {e}"


# ════════════════════════════════════════════
# Tab 1: Voice Creation
# ════════════════════════════════════════════

def gen_custom_voice(speaker, language, instruct, test_text, num_samples, progress=gr.Progress()):
    try:
        eng = get_engine()
        monitor.start(f"カスタムボイス生成 ({speaker})")
        if "custom" not in eng.loaded_models:
            monitor.update(0, "CustomVoice モデル読み込み中...")
            _wait_for_preload()
        n = int(num_samples)
        results = []
        t_total = time.time()
        for i in range(n):
            monitor.update(i / n, f"サンプル {i+1}/{n} 生成中...")
            progress(i / n, desc=f"音声生成中 {i+1}/{n}...")
            t0 = time.time()
            res = eng.generate_custom_voice(
                text=test_text, language=language,
                speaker=speaker, instruct=instruct,
                num_samples=1,
            )
            gen_time = time.time() - t0
            results.append((res[0], gen_time))
            audio_sec = len(res[0][0]) / res[0][1]
            monitor.log_step(f"サンプル{i+1} 完了 ({gen_time:.1f}s → {audio_sec:.1f}s音声)")
        elapsed = time.time() - t_total
        outputs = [(sr, wav) for (wav, sr), _ in results]
        times = " / ".join([f"{t:.1f}s" for _, t in results])
        audio_lens = " / ".join([f"{len(wav)/sr:.1f}s" for (wav, sr), _ in results])
        msg = f"{n}サンプル生成完了 (合計 {elapsed:.1f}s)\n生成時間: {times}\n音声長: {audio_lens}"
        monitor.finish(msg.split("\n")[0])
        return outputs, msg
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return [], f"エラー: {e}"


def gen_voice_design(language, voice_desc, test_text, num_samples, progress=gr.Progress()):
    """Returns (audios_list, seeds_list, status_msg)."""
    try:
        eng = get_engine()
        monitor.start("ボイスデザイン生成")
        if "design" not in eng.loaded_models:
            monitor.update(0, "VoiceDesign モデル読み込み中...")
        n = int(num_samples)
        audio_results = []  # (sr, wav)
        seed_results = []   # seed per sample
        gen_times = []
        t_total = time.time()
        for i in range(n):
            monitor.update(i / n, f"サンプル {i+1}/{n} 生成中...")
            progress(i / n, desc=f"音声生成中 {i+1}/{n}...")
            t0 = time.time()
            res = eng.generate_voice_design(
                text=test_text, language=language,
                instruct=voice_desc, num_samples=1, seed=-1,
            )
            gen_time = time.time() - t0
            (wav, sr), seed_used = res[0]
            audio_results.append((sr, wav))
            seed_results.append(seed_used)
            gen_times.append(gen_time)
            monitor.log_step(f"サンプル{i+1} 完了 ({gen_time:.1f}s, seed={seed_used})")
        elapsed = time.time() - t_total
        times = " / ".join([f"{t:.1f}s" for t in gen_times])
        audio_lens = " / ".join([f"{len(a[1])/a[0]:.1f}s" for a in audio_results])
        seeds_str = " / ".join([str(s) for s in seed_results])
        msg = (
            f"{n}サンプル生成完了 (合計 {elapsed:.1f}s)\n"
            f"生成時間: {times}\n音声長: {audio_lens}\n"
            f"Seed: {seeds_str}"
        )
        monitor.finish(msg.split("\n")[0])
        return audio_results, seed_results, msg
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return [], [], f"エラー: {e}"


def gen_voice_clone(ref_audio_path, ref_text, language, test_text, progress=gr.Progress()):
    try:
        if not ref_audio_path:
            return [], "参照音声をアップロードしてください"
        # Irodori は参照音声のみでクローンでき ref_text を内部で使わない。
        # そのため Irodori 選択時は書き起こしを必須にしない (UIでも非表示)。
        if cfg.tts_engine_type != "irodori" and (not ref_text or not ref_text.strip()):
            return [], "参照音声の書き起こしテキストを入力してください（必須）"
        eng = get_engine()
        monitor.start("ボイスクローン生成")
        if "clone" not in eng.loaded_models:
            monitor.update(0, "VoiceClone モデル読み込み中...")
        monitor.update(0.3, "クローン音声生成中...")
        progress(0.3, desc="クローン音声生成中...")
        t0 = time.time()
        results = eng.generate_voice_clone(
            text=test_text, language=language,
            ref_audio=ref_audio_path, ref_text=(ref_text or "").strip(),
        )
        elapsed = time.time() - t0
        wav, sr = results[0]
        audio_len = len(wav) / sr
        msg = f"クローン生成完了 (生成 {elapsed:.1f}s / 音声長 {audio_len:.1f}s)"
        monitor.finish(msg)
        return [(sr, wav)], msg
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return [], f"エラー: {e}"


def remove_bgm(audio_path, progress=gr.Progress()):
    """Remove BGM from audio using Demucs, return vocals-only wav."""
    if not audio_path:
        return None, "音声ファイルを選択してください"
    try:
        import subprocess, tempfile, shutil
        monitor.start("BGM除去 (Demucs)")
        monitor.update(0.1, "Demucs 実行中...")

        out_dir = tempfile.mkdtemp(prefix="demucs_")
        script_path = os.path.join(out_dir, "run_demucs.py")
        vocals_out = os.path.join(out_dir, "vocals.wav").replace("\\", "/")
        audio_in = audio_path.replace("\\", "/")
        with open(script_path, "w", encoding="utf-8") as sf_script:
            sf_script.write(f"""
import soundfile as sf
import numpy as np
import torch
from demucs.pretrained import get_model
from demucs.apply import apply_model

# Load audio with soundfile (avoids torchaudio/torchcodec issues)
data, sr = sf.read("{audio_in}", dtype="float32")
if data.ndim == 1:
    data = np.stack([data, data])  # mono to stereo
else:
    data = data.T  # (samples, channels) -> (channels, samples)
wav = torch.from_numpy(data).float()

# Run Demucs
model = get_model("htdemucs")
model.to("cuda")
ref = wav.mean(0)
wav_norm = (wav - ref.mean()) / ref.std()
sources = apply_model(model, wav_norm[None].to("cuda"), device="cuda")[0]
sources = sources * ref.std() + ref.mean()

# Extract vocals and save
vocals = sources[model.sources.index("vocals")].cpu().numpy()
sf.write("{vocals_out}", vocals.T, sr)
print("OK")
""")
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            monitor.finish(f"Demucs エラー")
            return None, f"Demucs エラー: {result.stderr[-300:]}"

        # Find vocals output
        from pathlib import Path
        vocals_files = [Path(out_dir) / "vocals.wav"]
        if not vocals_files[0].exists():
            vocals_files = list(Path(out_dir).rglob("vocals.wav"))
        if not vocals_files:
            monitor.finish("ボーカルファイルが見つかりません")
            return None, "ボーカルファイルが見つかりません"

        # Copy to persistent location
        dest = str(Path(cfg.output_dir) / "bgm_removed_vocals.wav")
        Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(vocals_files[0]), dest)
        shutil.rmtree(out_dir, ignore_errors=True)

        monitor.finish("BGM除去完了")
        return dest, f"BGM除去完了 → {dest}"
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return None, f"エラー: {e}"


def _save_voice_icon(name: str, icon_image) -> str:
    """ボイスのトレイアイコン画像を voices/<名>/icon.png に保存。
    トレイ表示向けに正方形(透過維持)で保存する。icon_image は PIL.Image か
    パス文字列 (Gradio Image)。空なら何もしない。戻り値: 状況メッセージ(空可)。"""
    if icon_image is None:
        return ""
    try:
        from PIL import Image
        img = icon_image if isinstance(icon_image, Image.Image) else Image.open(icon_image)
        img = img.convert("RGBA")
        # 正方形にクロップ (中央)
        w, h = img.size
        s = min(w, h)
        left, top = (w - s) // 2, (h - s) // 2
        img = img.crop((left, top, left + s, top + s))
        # トレイ用に程よいサイズへ
        if s > 256:
            img = img.resize((256, 256), Image.LANCZOS)
        voice_dir = Path(cfg.voices_dir) / name
        voice_dir.mkdir(parents=True, exist_ok=True)
        img.save(str(voice_dir / "icon.png"))
        return " / アイコン保存"
    except Exception as e:
        return f" / アイコン保存失敗: {e}"


def save_voice_action(name, voice_type, language, speaker, voice_desc,
                      ref_audio_path, ref_text, sample_audio,
                      seed=-1, attribute="", speed=1.0, max_pause_sec=0.0,
                      icon_image=None):
    if not name:
        return "ボイス名を入力してください", gr.update()
    try:
        vc = VoiceConfig(
            name=name,
            voice_type=voice_type,
            language=language,
            attribute=attribute or "",
            speaker=speaker or "",
            voice_description=voice_desc or "",
            seed=int(seed) if seed and int(seed) >= 0 else -1,
            ref_text=ref_text or "",
            speed=float(speed) if speed else 1.0,
            max_pause_sec=float(max_pause_sec) if max_pause_sec else 0.0,
        )
        sample_wav = None
        sample_sr = 24000
        ref_data = None
        ref_sr_val = 24000

        if sample_audio is not None:
            sample_sr, sample_wav = sample_audio
            if isinstance(sample_wav, np.ndarray) and sample_wav.dtype == np.int16:
                sample_wav = sample_wav.astype(np.float32) / 32768.0

        if ref_audio_path and os.path.exists(ref_audio_path):
            ref_data, ref_sr_val = sf.read(ref_audio_path)
            vc.ref_audio_path = ref_audio_path

        vm.save_voice(vc, sample_audio=sample_wav, sample_sr=sample_sr,
                       ref_audio_data=ref_data, ref_sr=ref_sr_val)
        icon_msg = _save_voice_icon(name, icon_image)
        return f"'{name}' を保存しました{icon_msg}", gr.update(choices=vm.get_voice_choices())
    except Exception as e:
        return f"保存エラー: {e}", gr.update()


def extract_prompt_cache(name):
    """クローンカードの参照音声から clone_prompt を抽出して voices/<名>/clone_prompt.pkl に
    キャッシュし、カードに記録する。戻り値はステータス文字列 (失敗時は「エラー: …」)。"""
    if not name:
        return "ボイスを選択してください"
    try:
        vc_cfg = vm.load_voice(name)
        if not vc_cfg.ref_audio_path or not os.path.exists(vc_cfg.ref_audio_path):
            return "ref_audioが見つかりません"
        eng = get_engine()
        monitor.start(f"Prompt抽出: {name}")
        prompt = eng.extract_clone_prompt(
            ref_audio=vc_cfg.ref_audio_path,
            ref_text=vc_cfg.ref_text,
        )
        voice_dir = Path(cfg.voices_dir) / name
        voice_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(prompt, str):
            # Irodori: 戻り値は latent キャッシュ(.pt)のパス。失敗時は参照音声パスにフォールバックする。
            # パス文字列を pkl に包むと絶対パスが残り、フォルダ移動で参照が切れて
            # エラーにならず別の声で喋るため、.pt は直接カードに記録し、それ以外は何も記録しない。
            if prompt.endswith(".pt") and os.path.exists(prompt):
                vc_cfg.clone_prompt_path = prompt
                vm.save_voice(vc_cfg)
                monitor.finish("Prompt抽出完了")
                return "✅ キャッシュ済み"
            # 以前の記録 (古い pkl / .pt) を残すと「参照音声をそのまま使う」表示と食い違う
            vc_cfg.clone_prompt_path = ""
            vm.save_voice(vc_cfg)
            monitor.finish("キャッシュ生成なし")
            return "⚠️ キャッシュを作れませんでした（参照音声をそのまま使います）"
        import pickle
        prompt_path = voice_dir / "clone_prompt.pkl"
        with open(str(prompt_path), "wb") as f:
            pickle.dump(prompt, f)
        vc_cfg.clone_prompt_path = str(prompt_path)
        vm.save_voice(vc_cfg)
        monitor.finish("Prompt抽出完了")
        return "✅ キャッシュ済み"
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return f"エラー: {e}"


# デザインのサンプルをクローン参照音声に使う時の推奨長 (UI の「参照音声 3〜10秒」と同じ)
DESIGN_CLONE_REF_MIN_SEC = 3.0
DESIGN_CLONE_REF_MAX_SEC = 10.0


def _checked_voice_dir(name):
    """ボイス名を検証して (名前, voices/<名> の絶対パス) を返す。
    上書き時に rmtree するため、区切り文字や '..' で voices_dir の外を指す名前は ValueError。"""
    name = (name or "").strip()
    if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError("カード名が空か、使えない文字(\\ / : * ? \" < > |)を含んでいます")
    # Windows の予約デバイス名 (CON, NUL, COM1 …) は拡張子付きでも実ファイルにならない
    if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", name, re.IGNORECASE):
        raise ValueError(f"'{name}' は Windows の予約名のため使えません")
    base = Path(cfg.voices_dir).resolve()
    d = (base / name).resolve()
    # Win32 は末尾の '.' や空白を無視するため "花子." が実際には "花子" フォルダを指し、
    # 上書き時に別カードを消しかねない (存在しない名前だと resolve では検出できない)。
    if name.endswith((".", " ")):
        raise ValueError("カード名の末尾に「.」や空白は使えません")
    # 大文字小文字だけは Windows が実在フォルダの表記に直して返すので、無視して比較する
    if d.parent != base or d.name.lower() != name.lower():
        raise ValueError("カード名が不正です")
    return name, d


def _voice_type_of(voice_dir):
    """既存カードの voice_type を表示用に読む (読めなければ「種別不明」)。"""
    import json
    try:
        data = json.loads((Path(voice_dir) / "config.json").read_text(encoding="utf-8"))
        return data.get("voice_type") or "種別不明"
    except Exception:
        return "種別不明"


def _find_existing_voice_dir(base, name):
    """voices_dir 直下から name と大文字小文字を無視して一致するフォルダを返す (無ければ None)。"""
    try:
        for p in Path(base).iterdir():
            if p.is_dir() and p.name.lower() == name.lower():
                return p
    except OSError:
        pass
    return None


def save_design_as_clone(name, sample_audio, seed, ref_text, language,
                         voice_desc="", attribute="", overwrite=False,
                         extract_prompt=True):
    """ボイスデザインで選んだサンプルを、クローンカードとして保存する。

    サンプル音声 = 参照音声(ref_audio.wav)、生成時のテスト文 = ref_text、デザインの seed =
    カードの seed。クローンの seed は声質ではなくサンプリングの揺れを固定するだけで、
    声質は参照音声が担う点に注意 (seed を引き継いでも同じ声になる保証は seed ではなく参照音声)。
    同名フォルダがある時は overwrite=True の場合だけ、フォルダごと削除して作り直す。
    Returns (status_msg, saved)。"""
    try:
        name, voice_dir = _checked_voice_dir(name)
    except ValueError as e:
        return f"保存できません: {e}", False
    if sample_audio is None:
        return "サンプルを先に生成してください", False
    if not (ref_text or "").strip():
        return "テスト文(参照音声の書き起こし)が空です。サンプルを生成し直してください", False

    sr, wav = sample_audio
    wav = np.asarray(wav)
    if wav.dtype == np.int16:
        wav = wav.astype(np.float32) / 32768.0
    # 先頭・末尾の無音は参照音声としてノイズになるので落とす (sample.wav は元のまま残す)
    ref_wav = trim_silence(wav, sr)
    dur = len(ref_wav) / sr
    warn = ""
    if not (DESIGN_CLONE_REF_MIN_SEC <= dur <= DESIGN_CLONE_REF_MAX_SEC):
        warn = (f"\n⚠️ 参照音声が {dur:.1f}秒です (推奨 {DESIGN_CLONE_REF_MIN_SEC:.0f}〜"
                f"{DESIGN_CLONE_REF_MAX_SEC:.0f}秒)。テスト文の長さを調整して生成し直すと安定します")

    existing = _find_existing_voice_dir(voice_dir.parent, name)
    backup_root = None
    if existing is not None:
        if not overwrite:
            return (f"'{existing.name}' ({_voice_type_of(existing)}) は既に存在します。"
                    f"上書きするなら「上書きを許可」にチェックして、もう一度押してください"), False
        # 先に消さず、まず退避する。保存に失敗した時に旧カードも新カードも無くなるのを防ぐ。
        # 退避先は voices_dir の外 (残骸がボイス一覧に出ないように) で、rename できる同一ドライブ。
        try:
            backup_root = Path(tempfile.mkdtemp(prefix=".voice_bak_", dir=voice_dir.parent.parent))
            os.replace(existing, backup_root / "old")
        except OSError as e:
            if backup_root is not None:
                shutil.rmtree(backup_root, ignore_errors=True)
            return f"既存フォルダを退避できませんでした (使用中?): {e}", False

    seed = int(seed) if seed is not None and int(seed) >= 0 else -1
    vc = VoiceConfig(
        name=name, voice_type="clone", language=language or "Japanese",
        attribute=attribute or "", voice_description=voice_desc or "",
        seed=seed, ref_text=ref_text.strip(),
    )
    try:
        vm.save_voice(vc, sample_audio=wav, sample_sr=sr,
                      ref_audio_data=ref_wav, ref_sr=sr)
    except Exception as e:
        if backup_root is not None:
            shutil.rmtree(voice_dir, ignore_errors=True)  # 書きかけを消して旧カードを戻す
            try:
                os.replace(backup_root / "old", existing)
                shutil.rmtree(backup_root, ignore_errors=True)
                return f"保存エラー: {e}\n(元のカードに戻しました)", False
            except OSError as e2:
                return f"保存エラー: {e}\n⚠️ 元のカードを戻せませんでした。退避先: {backup_root / 'old'} ({e2})", False
        return f"保存エラー: {e}", False
    if backup_root is not None:
        shutil.rmtree(backup_root, ignore_errors=True)

    msg = f"'{name}' をクローンカードとして保存しました (seed={seed}, 参照音声 {dur:.1f}秒)"
    if backup_root is not None:
        # daemon はボイスの読み込みを起動時と切替時にしか行わない
        msg += "\n(上書きしました。読み上げ中のボイスなら、別のボイスへ切り替えてから選び直すと反映されます)"
    if extract_prompt:
        # 失敗してもカード自体は保存済み。キャッシュ無しは調整タブから後で抽出できる
        status = extract_prompt_cache(name)
        msg += f"\nprompt: {status}"
    return msg + warn, True


def delete_voice_action(name):
    if not name:
        return "ボイスを選択してください", gr.update()
    vm.delete_voice(name)
    return f"'{name}' を削除しました", gr.update(choices=vm.get_voice_choices())


def preview_voice(name):
    p = vm.get_sample_path(name)
    if p and os.path.exists(p):
        return p
    return None


def set_voice_icon_action(name, icon_image):
    """選択中のボイスにトレイアイコン画像を設定 (voices/<名>/icon.png)。"""
    if not name:
        return "ボイスを選択してください"
    if icon_image is None:
        return "画像を選択してください"
    msg = _save_voice_icon(name, icon_image)
    if "失敗" in msg:
        return f"'{name}' {msg.strip(' /')}"
    return f"'{name}' のトレイアイコンを設定しました (voices/{name}/icon.png)"


def get_voice_icon_path(name):
    """選択中ボイスの既存アイコンパス (プレビュー用)。無ければ None。"""
    if not name:
        return None
    p = Path(cfg.voices_dir) / name / "icon.png"
    return str(p) if p.exists() else None


