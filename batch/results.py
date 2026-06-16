"""生成結果の行操作 (再生/再生成/チェック) と NGレポート/NG Excel。"""
import os
import time
from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd

from engine.engine_control import cfg, vm, monitor, get_engine
from engine.text_utils import normalize_tts_text
from engine.audio_utils import trim_silence, trim_interior_pauses, adjust_speed
from .state import (
    SCRIPT_COLUMNS, RESULT_COLUMNS, generated_audio, voice_check_cache,
    speech_check_cache, generation_context,
)
from .checks import run_voice_check, build_result_table


def on_result_row_select(evt: gr.SelectData):
    """When user clicks a row in the result table, play its audio."""
    row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
    if row_idx in generated_audio:
        wav, sr = generated_audio[row_idx]
        # Use cache instead of re-computing
        label, f0 = voice_check_cache.get(row_idx, ("", 0.0))
        speech_status, transcribed, _detail = speech_check_cache.get(row_idx, ("", "", ""))
        info = f"行 {row_idx} | {label} ({f0:.0f}Hz) | {len(wav)/sr:.1f}秒 | {speech_status}"
        if transcribed:
            info += f" [{transcribed}]"
        return (sr, wav), info, row_idx
    return None, f"行 {row_idx} は音声未生成です", row_idx


def generate_ng_report():
    """Generate a report of all NG rows with detailed reasons."""
    if not speech_check_cache:
        return "チェック結果がありません。先に一括生成を実行してください。"

    ng_rows = []
    for idx, (status, transcribed, detail) in speech_check_cache.items():
        if "✅" not in status:
            ng_rows.append((idx, status, transcribed, detail))

    if not ng_rows:
        return "全行OKです。NG行はありません。"

    lines = [f"NG行レポート ({len(ng_rows)}件)", "=" * 50]
    for idx, status, transcribed, detail in ng_rows:
        ctx = generation_context.get(idx, {})
        lines.append(f"\n行{idx}: {status}")
        lines.append(f"  セリフ: {ctx.get('セリフ原文', '')}")
        lines.append(f"  TTS入力テキスト: {ctx.get('TTS入力テキスト', '')}")
        lines.append(f"  build_instruct全文(初回): {ctx.get('build_instruct結果', '')}")
        if ctx.get("最終使用instruct", "") != ctx.get("build_instruct結果", ""):
            lines.append(f"  最終使用instruct: {ctx.get('最終使用instruct', '')}")
        lines.append(f"  ユーザー指示: {ctx.get('ユーザー指示', '')}")
        lines.append(f"  キャラ属性: {ctx.get('キャラ属性', '')}")
        lines.append(f"  感情: {ctx.get('感情', '')}")
        lines.append(f"  seed: {ctx.get('seed', '')}")
        lines.append(f"  リトライ回数: {ctx.get('リトライ回数', '')}")
        lines.append(f"  書き起こし: {transcribed}")
        if detail:
            lines.append(f"  詳細: {detail}")

    # Save to file
    try:
        log_dir = Path(cfg.output_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        report_path = log_dir / "ng_report.txt"
        with open(str(report_path), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        lines.append(f"\n保存先: {report_path}")
    except Exception:
        pass

    return "\n".join(lines)


def export_ng_excel(df_data, output_dir):
    """Export NG rows as an Excel file with full generation context for Claude Code review."""
    if not speech_check_cache:
        return "チェック結果がありません", None

    df = pd.DataFrame(df_data, columns=SCRIPT_COLUMNS) if not isinstance(df_data, pd.DataFrame) else df_data
    for col in ["ID", "キャラ(性格)"]:
        if col in df.columns:
            df[col] = df[col].replace("", np.nan).ffill().fillna("")

    ng_rows = []
    for idx, (status, transcribed, detail) in speech_check_cache.items():
        if "✅" not in status and idx < len(df):
            row = df.iloc[idx]
            ctx = generation_context.get(idx, {})
            ng_rows.append({
                "ID": str(row["ID"]),
                "キャラ(性格)": str(row["キャラ(性格)"]),
                "ファイル名": str(row["ファイル名"]),
                "セリフ": str(row["セリフ"]),
                "セリフ仮名": str(row["セリフ仮名"]),
                "感情": str(row["感情"]),
                "Qwen3TTSシステムプロンプト": str(row["Qwen3TTSシステムプロンプト"]),
                "TTS入力テキスト": ctx.get("TTS入力テキスト", ""),
                "build_instruct全文": ctx.get("build_instruct結果", ""),
                "キャラ属性": ctx.get("キャラ属性", ""),
                "voice_type": ctx.get("voice_type", ""),
                "seed": str(ctx.get("seed", "")),
                "リトライ回数": str(ctx.get("リトライ回数", "")),
                "NG理由": status,
                "書き起こし": transcribed,
                "詳細": detail,
            })

    if not ng_rows:
        return "NG行はありません", None

    ng_df = pd.DataFrame(ng_rows)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    fpath = out_path / "ng_rows.xlsx"
    ng_df.to_excel(str(fpath), index=False)

    return f"NG {len(ng_rows)}行をエクスポート → {fpath}", str(fpath)


def regenerate_row(selected_row, df_data, mapping_state, current_result_table=None):
    """Regenerate audio for the selected row. Preserves edits in result table."""
    idx = int(selected_row) if selected_row is not None else -1
    if idx < 0:
        return None, "行を選択してください", gr.update()
    if df_data is None:
        return None, "データがありません", gr.update()
    try:
        df = pd.DataFrame(df_data, columns=SCRIPT_COLUMNS) if not isinstance(df_data, pd.DataFrame) else df_data
        if idx >= len(df):
            return None, "行が範囲外です", gr.update()

        row = df.iloc[idx]

        # Check if result table has edits for this row (use edited values if available)
        result_serif = ""
        result_prompt = ""
        if current_result_table is not None and len(current_result_table) > 0:
            res_df = pd.DataFrame(current_result_table, columns=RESULT_COLUMNS) if not isinstance(current_result_table, pd.DataFrame) else current_result_table
            for ri in range(len(res_df)):
                try:
                    if int(res_df.iloc[ri]["行"]) == idx:
                        result_serif = str(res_df.iloc[ri]["セリフ"]).strip()
                        result_prompt = str(res_df.iloc[ri]["Qwen3TTSシステムプロンプト"]).strip()
                        break
                except (ValueError, TypeError):
                    continue

        char_name = str(row["キャラ(性格)"]).strip()
        voice_name = (mapping_state or {}).get(char_name, "")
        if not voice_name:
            return None, f"'{char_name}' にボイスが割り当てられていません", gr.update()

        vc = vm.load_voice(voice_name)
        vm.touch_voice(voice_name)
        # Use result table values if edited, otherwise fall back to script table
        serif_text = result_serif or str(row["セリフ仮名"]).strip() or str(row["セリフ"])
        text = normalize_tts_text(serif_text)
        attribute = vc.attribute or char_name
        prompt_text = result_prompt or str(row["Qwen3TTSシステムプロンプト"]).strip()
        eng = get_engine()
        instruct = type(eng).build_instruct(
            attribute, str(row["感情"]).strip(),
            prompt_text, cfg.instruct_template,
        )
        t0 = time.time()
        wav, sr = eng.generate_for_script_row(
            voice_type=vc.voice_type, text=text, language=vc.language,
            instruct=instruct, speaker=vc.speaker,
            ref_audio=vc.ref_audio_path, ref_text=vc.ref_text,
            voice_description=vc.voice_description, seed=vc.seed,
        )
        if getattr(vc, "max_pause_sec", 0.0) > 0:
            wav = trim_interior_pauses(wav, sr, float(vc.max_pause_sec))
        if getattr(vc, "speed", 1.0) != 1.0:
            wav = adjust_speed(wav, sr, float(vc.speed))
        generated_audio[idx] = (wav, sr)
        gen_time = time.time() - t0
        # チェックは別ボタンで行うため、ここではキャッシュをクリアして状態のみ更新
        voice_check_cache.pop(idx, None)
        speech_check_cache.pop(idx, None)
        info = f"行 {idx} 再生成完了 ({gen_time:.1f}s)"

        # Update only the regenerated row in the current result table (preserve user edits)
        if current_result_table is not None and len(current_result_table) > 0:
            res_df = pd.DataFrame(current_result_table, columns=RESULT_COLUMNS) if not isinstance(current_result_table, pd.DataFrame) else current_result_table.copy()
            for ri in range(len(res_df)):
                try:
                    if int(res_df.iloc[ri]["行"]) == idx:
                        res_df.iat[ri, RESULT_COLUMNS.index("声質チェック")] = ""
                        res_df.iat[ri, RESULT_COLUMNS.index("セリフチェック")] = ""
                        res_df.iat[ri, RESULT_COLUMNS.index("書き起こし")] = ""
                        res_df.iat[ri, RESULT_COLUMNS.index("状態")] = "✅ 再生成済 (未チェック)"
                        break
                except (ValueError, TypeError):
                    continue
        else:
            # Fallback: rebuild table
            res_df = build_result_table(df, check_rows=[])
        return (sr, wav), info, res_df
    except Exception as e:
        return None, f"再生成エラー: {e}", gr.update()


def check_row(selected_row, df_data, current_result_table=None):
    """Run voice + speech check on the regenerated audio of the selected row."""
    idx = int(selected_row) if selected_row is not None else -1
    if idx < 0:
        return None, "行を選択してください", gr.update()
    if idx not in generated_audio:
        return None, f"行 {idx} の音声がありません (先に再生成してください)", gr.update()
    try:
        df = pd.DataFrame(df_data, columns=SCRIPT_COLUMNS) if not isinstance(df_data, pd.DataFrame) else df_data
        if idx >= len(df):
            return None, "行が範囲外です", gr.update()
        row = df.iloc[idx]

        # 結果テーブルの編集値を優先 (再生成と同じロジック)
        result_serif = ""
        result_prompt = ""
        if current_result_table is not None and len(current_result_table) > 0:
            res_df_in = pd.DataFrame(current_result_table, columns=RESULT_COLUMNS) if not isinstance(current_result_table, pd.DataFrame) else current_result_table
            for ri in range(len(res_df_in)):
                try:
                    if int(res_df_in.iloc[ri]["行"]) == idx:
                        result_serif = str(res_df_in.iloc[ri]["セリフ"]).strip()
                        result_prompt = str(res_df_in.iloc[ri]["Qwen3TTSシステムプロンプト"]).strip()
                        break
                except (ValueError, TypeError):
                    continue

        serif_text = result_serif or str(row["セリフ仮名"]).strip() or str(row["セリフ"])
        serif_orig = normalize_tts_text(serif_text)
        prompt_used = result_prompt or str(row["Qwen3TTSシステムプロンプト"]).strip()
        label, f0 = run_voice_check(idx, expected_text=serif_orig, system_prompt=prompt_used)
        speech_status, transcribed, _detail = speech_check_cache.get(idx, ("", "", ""))
        voice_check = f"{label} ({f0:.0f}Hz)" if f0 > 0 else label
        info = f"行 {idx} チェック完了 | {label} ({f0:.0f}Hz) | {speech_status} [{transcribed}]"

        wav, sr = generated_audio[idx]
        if current_result_table is not None and len(current_result_table) > 0:
            res_df = pd.DataFrame(current_result_table, columns=RESULT_COLUMNS) if not isinstance(current_result_table, pd.DataFrame) else current_result_table.copy()
            for ri in range(len(res_df)):
                try:
                    if int(res_df.iloc[ri]["行"]) == idx:
                        res_df.iat[ri, RESULT_COLUMNS.index("声質チェック")] = voice_check
                        res_df.iat[ri, RESULT_COLUMNS.index("セリフチェック")] = speech_status
                        res_df.iat[ri, RESULT_COLUMNS.index("書き起こし")] = transcribed
                        res_df.iat[ri, RESULT_COLUMNS.index("状態")] = "✅ チェック済"
                        break
                except (ValueError, TypeError):
                    continue
        else:
            res_df = build_result_table(df, check_rows=[idx])
        return (sr, wav), info, res_df
    except Exception as e:
        return None, f"チェックエラー: {e}", gr.update()
