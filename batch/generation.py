"""一括生成の本体 (オーケストレーター + 機能別ヘルパー)。"""
import os
import time
import traceback
from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd
import soundfile as sf

from engine_control import cfg, vm, monitor, get_engine, mark_generating
from text_utils import normalize_tts_text
from audio_utils import (
    trim_silence, trim_interior_pauses, adjust_speed, check_audio_duration,
)
from . import state
from .state import (
    SCRIPT_COLUMNS, RESULT_COLUMNS, generated_audio, voice_check_cache,
    speech_check_cache, generation_context,
)
from .checks import run_voice_check, build_result_table


def assign_voice_to_char(char_name, voice_name, mapping_state):
    mapping = mapping_state or {}
    if char_name and voice_name:
        mapping[char_name] = voice_name
    display = "\n".join([f"  {k} → {v}" for k, v in mapping.items()])
    return mapping, f"現在の割り当て:\n{display}" if display else "割り当てなし"


def stop_batch():
    state.batch_stop_requested = True
    return "停止リクエスト送信... 現在の行の生成完了後に停止します"


# ── run_batch_generation の機能別ヘルパー ──

def _normalize_script_df(df_data) -> pd.DataFrame:
    """Gradio経由で崩れた列順/欠損列/結合セルを補正し、生成対象行だけに絞る。"""
    df = pd.DataFrame(df_data, columns=SCRIPT_COLUMNS) if not isinstance(df_data, pd.DataFrame) else df_data.copy()
    # Gradio経由で列順/列名が崩れることがあるので SCRIPT_COLUMNS を強制的に揃える
    for c in SCRIPT_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[SCRIPT_COLUMNS]
    # ファイル名が空の行は読み込み時にも除外しているが、編集後にも残り得るのでここでも除外
    df = df[df["ファイル名"].astype(str).str.strip() != ""].reset_index(drop=True)
    # Re-apply forward fill (Gradio may lose it when passing data)
    for col in ["ID", "キャラ(性格)"]:
        df[col] = df[col].replace("", np.nan).ffill().fillna("")
    return df


def _retry_instruct_for(attempt: int, instruct: str, emotion: str, row_no: int) -> str:
    """リトライ段階に応じて instruct を段階的に短縮する (2回目=感情のみ / 3回目=空)。"""
    if attempt == 2:
        retry_instruct = emotion if emotion else ""
        monitor.log_step(f"行{row_no} リトライ2: instruct→感情のみ [{retry_instruct}]")
        return retry_instruct
    if attempt == 3:
        monitor.log_step(f"行{row_no} リトライ3: instruct→空")
        return ""
    return instruct


def _load_clone_settings(vc, clone_stable: bool, warn_once: bool):
    """クローン安定化用の promptキャッシュ(.pt/.pkl両対応)と temperature を解決する。"""
    clone_prompt = None
    clone_temp = -1.0
    if clone_stable and vc.voice_type == "clone":
        clone_temp = vc.clone_temperature if vc.clone_temperature > 0 else 0.3
        if vc.clone_prompt_path and os.path.exists(vc.clone_prompt_path):
            if vc.clone_prompt_path.endswith(".pt"):
                # Irodori の latentキャッシュ: パス文字列のまま engine に渡す
                # (engine 側で ref_latent として読む。pickle.load すると壊れる)
                clone_prompt = vc.clone_prompt_path
            else:
                # Qwen3 等の pickle キャッシュ
                import pickle
                with open(vc.clone_prompt_path, "rb") as f:
                    clone_prompt = pickle.load(f)
        else:
            if warn_once:
                monitor.log_step(f"⚠️ {vc.name}: promptキャッシュなし。クローンボイス調整タブで「Promptを抽出してキャッシュ」を実行してください")
        # Force fixed seed for clone stability (use 42 if not set)
        if vc.seed < 0:
            if warn_once:
                monitor.log_step(f"⚠️ {vc.name}: seedが-1。安定のためseed=42を一時使用")
    return clone_prompt, clone_temp


def _resolve_seed(vc, clone_stable: bool, attempt: int) -> int:
    """生成シードを決める (クローン安定化は42固定 / リトライ時はランダム化)。"""
    use_seed = vc.seed
    if clone_stable and vc.voice_type == "clone" and use_seed < 0:
        use_seed = 42  # default fallback for stability
    if attempt > 1:
        use_seed = -1  # randomize on retry
    return use_seed


def _resolve_clone_caption(vc, emotion: str) -> str:
    """クローン(Irodori)の感情caption を組み立てる。
    ボイスカードの既定感情(default_caption) を基底に、台本の「感情」列を重ねる。
    custom/design では使われない (エンジン側が clone 型のみ caption を反映)。"""
    base = (getattr(vc, "default_caption", "") or "").strip()
    emo = (emotion or "").strip()
    if base and emo:
        return f"{base}。{emo}"
    return base or emo


def _generate_row_audio(eng, vc, text, retry_instruct, use_seed, clone_prompt,
                        clone_temp, clone_caption=""):
    """1行ぶんを生成し、後処理 (無音除去→文中ポーズ短縮→話速調整) まで行う。"""
    wav, sr = eng.generate_for_script_row(
        voice_type=vc.voice_type,
        text=text,
        language=vc.language,
        instruct=retry_instruct,
        speaker=vc.speaker,
        ref_audio=vc.ref_audio_path,
        ref_text=vc.ref_text,
        voice_description=vc.voice_description,
        seed=use_seed,
        voice_clone_prompt=clone_prompt,
        clone_temperature=clone_temp,
        clone_caption=clone_caption,
    )
    wav = trim_silence(wav, sr)
    if getattr(vc, "max_pause_sec", 0.0) > 0:
        wav = trim_interior_pauses(wav, sr, float(vc.max_pause_sec))
    if getattr(vc, "speed", 1.0) != 1.0:
        wav = adjust_speed(wav, sr, float(vc.speed))
    return wav, sr


def _build_status_message(df, total, skipped, stopped, errors, max_sec) -> str:
    """生成結果のステータス文 (停止/スキップ/秒数超過/エラーのサマリー) を組み立てる。"""
    msg = f"{len(generated_audio)}/{total} 行の音声を生成しました"
    if stopped:
        msg += " (手動停止)"
    if skipped:
        msg += f" ({skipped}行スキップ)"
    # 超過行サマリー
    if max_sec and float(max_sec) > 0:
        over = []
        for i, (w, s) in generated_audio.items():
            sec = len(w) / s
            if sec > float(max_sec):
                fn = str(df.iloc[i]["ファイル名"]).strip() if i < len(df) else f"行{i}"
                over.append((i, fn, sec))
        if over:
            head = f"\n\n⚠️ 最大{float(max_sec):.1f}s 超過 {len(over)}件:"
            lines = [f"  行{i} [{fn}] {sec:.1f}s" for i, fn, sec in over[:20]]
            if len(over) > 20:
                lines.append(f"  ... 他{len(over)-20}件")
            msg += head + "\n" + "\n".join(lines)
    if errors:
        msg += "\n\nエラー:\n" + "\n".join(errors[:10])
    return msg


def _write_generation_log(df, total, msg) -> str:
    """output/generation_log.txt に実行ログと行別詳細を書き、msgにログパスを追記して返す。"""
    try:
        log_dir = Path(cfg.output_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "generation_log.txt"
        with open(str(log_path), "w", encoding="utf-8") as f:
            f.write(f"生成日時: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"結果: {msg.split(chr(10))[0]}\n")
            f.write(f"{'='*60}\n")
            for entry in monitor.log:
                f.write(f"{entry}\n")
            f.write(f"{'='*60}\n")
            # Write per-row details
            for i in range(total):
                row = df.iloc[i]
                fname = str(row["ファイル名"]).strip()
                if not fname:
                    continue
                serif = str(row["セリフ"])
                gl, gf = voice_check_cache.get(i, ("", 0.0))
                ss, tr, detail = speech_check_cache.get(i, ("", "", ""))
                status = "生成済" if i in generated_audio else "未生成"
                f.write(f"行{i+1} [{fname}] {status}\n")
                f.write(f"  セリフ: {serif}\n")
                f.write(f"  声質: {gl} ({gf:.0f}Hz)\n")
                f.write(f"  セリフチェック: {ss}\n")
                if tr:
                    f.write(f"  書き起こし: {tr}\n")
                if detail:
                    f.write(f"  NG理由: {detail}\n")
                f.write(f"\n")
        msg += f"\n\nログ: {log_path}"
    except Exception:
        pass
    return msg


def _autosave_wavs(df, msg) -> str:
    """生成済み音声を output/ に自動保存し、結果を msg に追記して返す。"""
    try:
        out_path = Path(cfg.output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        saved = 0
        for idx, (wav, sr) in generated_audio.items():
            row = df.iloc[idx]
            fname = str(row["ファイル名"]).strip()
            if not fname:
                continue
            fname = "".join(c for c in fname if c.isalnum() or c in "_-.").strip().rstrip(".")
            if not fname:
                fname = f"row_{idx}"
            sf.write(str(out_path / f"{fname}.wav"), wav, sr)
            saved += 1
        msg += f"\n{saved}ファイルを自動保存 → {out_path}"
    except Exception as e:
        msg += f"\n自動保存エラー: {e}"
    return msg


def run_batch_generation(df_data, mapping_state, skip_existing=True, clone_stable=True, do_speech_check=False, only_star=False, max_sec=0.0, progress=gr.Progress()):
    generated_audio.clear()
    voice_check_cache.clear()
    speech_check_cache.clear()
    generation_context.clear()
    state.batch_stop_requested = False
    mark_generating(True)  # トレイアイコン走る
    if hasattr(run_batch_generation, "_touched"):
        run_batch_generation._touched.clear()

    if df_data is None or len(df_data) == 0:
        return "データがありません", pd.DataFrame(columns=RESULT_COLUMNS)
    if not mapping_state:
        return "キャラ⇔ボイスの割り当てを設定してください", pd.DataFrame(columns=RESULT_COLUMNS)

    try:
        df = _normalize_script_df(df_data)
        eng = get_engine()
        total = len(df)
        errors = []
        monitor.start(f"セリフ一括生成 ({total}行)")

        skipped = 0
        stopped = False
        for i in range(total):
            if state.batch_stop_requested:
                stopped = True
                break

            row = df.iloc[i]

            # ★フィルタ: only_star=True のとき おすすめ="★" の行のみ生成
            if only_star and "おすすめ" in df.columns:
                if str(row.get("おすすめ", "")).strip() != "★":
                    skipped += 1
                    continue

            # ファイル名が空欄 → 生成不要、スキップ
            fname = str(row["ファイル名"]).strip()
            if not fname:
                skipped += 1
                continue

            # Skip if WAV already exists
            if skip_existing:
                fname_clean = "".join(c for c in fname if c.isalnum() or c in "_-.").strip().rstrip(".")
                if (Path(cfg.output_dir) / f"{fname_clean}.wav").exists():
                    skipped += 1
                    continue

            char_name = str(row["キャラ(性格)"]).strip()
            voice_name = mapping_state.get(char_name, "") if char_name else ""
            if not voice_name:
                # キャラ空欄 or 未割り当て → スキップ（エラーにしない）
                if char_name:
                    errors.append(f"行{i+1}: '{char_name}' にボイスが割り当てられていません")
                else:
                    skipped += 1
                continue

            try:
                vc = vm.load_voice(voice_name)
            except Exception:
                errors.append(f"行{i+1}: ボイス '{voice_name}' が見つかりません")
                continue

            # Touch voice once per voice in this batch
            if not hasattr(run_batch_generation, "_touched"):
                run_batch_generation._touched = set()
            if voice_name not in run_batch_generation._touched:
                vm.touch_voice(voice_name)
                run_batch_generation._touched.add(voice_name)

            # Build text: use セリフ仮名 if available, else セリフ
            text = str(row["セリフ仮名"]).strip() or str(row["セリフ"])
            # Remove （）モノローグ and ()モノローグ
            text = normalize_tts_text(text)
            if not text:
                skipped += 1
                continue

            # Use attribute from: character card > CSV column
            attribute = vc.attribute or char_name
            emotion = str(row["感情"]).strip()
            instruction = str(row["Qwen3TTSシステムプロンプト"]).strip()

            # Build instruct (attribute > emotion > instruction)
            # エンジンごとに書式が違う(Qwen3=指示文/Irodori=カンマ区切りcaption)ため
            # ロード中エンジンのクラスの build_instruct を使う
            instruct = type(eng).build_instruct(attribute, emotion, instruction, cfg.instruct_template)

            # Save full generation context for NG analysis
            serif_orig = normalize_tts_text(str(row["セリフ"]))
            generation_context[i] = {
                "セリフ原文": str(row["セリフ"]),
                "TTS入力テキスト": text,
                "キャラ属性": attribute,
                "感情": emotion,
                "ユーザー指示": instruction,
                "build_instruct結果": instruct,
                "voice_type": vc.voice_type,
                "seed": vc.seed,
                "voice_description": vc.voice_description,
            }

            monitor.update(i / total, f"行{i+1}/{total}: {char_name}「{text[:15]}...」")
            progress(i / total, desc=f"生成中 {i+1}/{total}: {text[:20]}...")

            max_retries = 3 if do_speech_check else 1
            try:
                for attempt in range(1, max_retries + 1):
                    # リトライ段階に応じた instruct 短縮 → クローン設定/シード解決 → 生成+後処理
                    retry_instruct = _retry_instruct_for(attempt, instruct, emotion, i + 1)
                    clone_prompt, clone_temp = _load_clone_settings(vc, clone_stable, warn_once=(i == 0))
                    use_seed = _resolve_seed(vc, clone_stable, attempt)

                    # Irodoriクローンは「感情」列+ボイス既定感情を caption として乗せる
                    # (Qwen3 では engine 側で無視され、従来どおり retry_instruct が効く)
                    row_caption = _resolve_clone_caption(vc, emotion)
                    t0 = time.time()
                    wav, sr = _generate_row_audio(
                        eng, vc, text, retry_instruct, use_seed, clone_prompt, clone_temp,
                        clone_caption=row_caption)
                    generated_audio[i] = (wav, sr)
                    gen_time = time.time() - t0
                    audio_sec = len(wav) / sr

                    if do_speech_check:
                        # Full check: duration + voice + speech content
                        dur_status, actual_sec, expected_max = check_audio_duration(wav, sr, text)
                        if "❌" in dur_status and attempt < max_retries:
                            speech_check_cache[i] = (f"⚠️ 音声長すぎ({actual_sec:.1f}s/想定{expected_max:.1f}s)", "",
                                f"トリミング後も音声が想定の{actual_sec/expected_max:.1f}倍長い")
                            monitor.log_step(f"行{i+1} 音声{actual_sec:.1f}s(想定{expected_max:.1f}s)→再生成")
                            continue

                        label, f0 = run_voice_check(i, expected_text=serif_orig, system_prompt=retry_instruct)
                        speech_status, transcribed, _detail = speech_check_cache.get(i, ("", "", ""))

                        if "✅" in speech_status or attempt == max_retries:
                            generation_context[i]["リトライ回数"] = attempt
                            generation_context[i]["最終結果"] = speech_status
                            generation_context[i]["最終使用instruct"] = retry_instruct
                            if attempt > 1:
                                monitor.log_step(f"行{i+1} {char_name}「{text[:10]}」({gen_time:.1f}s) {speech_status} (試行{attempt}回目)")
                            else:
                                monitor.log_step(f"行{i+1} {char_name}「{text[:10]}」({gen_time:.1f}s) {label} {f0:.0f}Hz {speech_status}")
                            break
                        else:
                            monitor.log_step(f"行{i+1} {speech_status}→再生成 (試行{attempt}/{max_retries})")
                    else:
                        # Fast mode: generation + trim only, no Whisper check
                        monitor.log_step(f"行{i+1} {char_name}「{text[:10]}」({gen_time:.1f}s / {audio_sec:.1f}s)")
                        break
            except Exception as e:
                errors.append(f"行{i+1}: 生成エラー - {e}")
                monitor.log_step(f"行{i+1} エラー: {e}")

        # Build result table using cached voice checks (no re-check)
        result_df = build_result_table(df, check_rows=[], max_sec=float(max_sec or 0.0))

        msg = _build_status_message(df, total, skipped, stopped, errors, max_sec)
        monitor.finish(f"{len(generated_audio)}/{total} 行の音声を生成完了")
        msg = _write_generation_log(df, total, msg)   # output/generation_log.txt
        msg = _autosave_wavs(df, msg)                 # output/*.wav 自動保存

        mark_generating(False)  # トレイアイコン歩きに戻る
        return msg, result_df
    except Exception as e:
        mark_generating(False)
        monitor.finish(f"一括生成エラー")
        return f"一括生成エラー: {e}\n{traceback.format_exc()}", pd.DataFrame(columns=RESULT_COLUMNS)
