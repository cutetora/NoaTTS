"""ボイス作成ドメインのロジック (UI非依存)。

app.py から分離。サンプル生成(custom/design/clone)・BGM除去・ボイスカード保存/
削除/試聴・トレイアイコン設定。UI(ui_voice_create.py / app.py)から呼ばれる。
エンジン/設定/進捗は engine_control の共有層を使う。
"""
import os
import sys
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


