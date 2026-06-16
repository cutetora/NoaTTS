"""声質チェック(F0)・セリフ照合(Whisper)と結果テーブルの構築。"""
import pandas as pd

from engine.audio_utils import check_voice_gender, check_speech_content
from .state import (
    RESULT_COLUMNS, generated_audio, voice_check_cache, speech_check_cache,
)


def run_voice_check(row_idx: int, expected_text: str = "", system_prompt: str = ""):
    """Run voice quality + speech content check for a single row and cache results."""
    if row_idx in generated_audio:
        wav, sr = generated_audio[row_idx]
        gender_result = check_voice_gender(wav, sr)
        voice_check_cache[row_idx] = gender_result

        if expected_text:
            status, transcribed, base_detail = check_speech_content(wav, sr, expected_text)

            # Enrich NG detail with concrete data for Claude Code analysis
            if "✅" not in status:
                audio_sec = len(wav) / sr
                text_len = len(expected_text)
                prompt_len = len(system_prompt) if system_prompt else 0
                ratio = prompt_len / max(text_len, 1)

                parts = [base_detail] if base_detail else []
                parts.append(f"[データ] セリフ{text_len}文字 / プロンプト{prompt_len}文字 (比率{ratio:.1f}倍) / 音声{audio_sec:.1f}秒")
                if system_prompt:
                    parts.append(f"[使用プロンプト] {system_prompt}")
                if ratio > 3:
                    parts.append("[分析] プロンプトがセリフの3倍以上→TTSが混乱しやすい。プロンプトを短縮すべき")
                if text_len <= 5 and prompt_len > 15:
                    parts.append("[分析] 短いセリフに長い指示→繰り返しが発生しやすい。指示は5文字以内に")
                if transcribed and expected_text in transcribed and len(transcribed) > len(expected_text) * 1.5:
                    parts.append("[分析] セリフ自体は含まれるが余計な音声あり→プロンプトの言葉が読み上げられた可能性")
                detail = "\n".join(parts)
            else:
                detail = base_detail

            speech_check_cache[row_idx] = (status, transcribed, detail)
        return gender_result
    return ("", 0.0)


def build_result_table(df: pd.DataFrame, check_rows: list[int] | None = None, max_sec: float = 0.0) -> pd.DataFrame:
    """Build the generation result table.

    Args:
        check_rows: If specified, only run voice check on these rows (use cache for others).
                    If None, check all generated rows.
        max_sec:    If >0, rows with audio longer than this get a warning mark in 状態.
    """
    rows = []
    for i in range(len(df)):
        fname = str(df.iloc[i]["ファイル名"]).strip()
        serif = str(df.iloc[i]["セリフ"])
        prompt = str(df.iloc[i]["Qwen3TTSシステムプロンプト"]).strip()
        if i in generated_audio:
            wav, sr = generated_audio[i]
            audio_sec = len(wav) / sr
            # Only run check if needed
            if check_rows is None or i in check_rows:
                run_voice_check(i, expected_text=serif, system_prompt=prompt)
            label, f0 = voice_check_cache.get(i, ("未チェック", 0.0))
            voice_check = f"{label} ({f0:.0f}Hz)" if f0 > 0 else label
            speech_status, transcribed, _detail = speech_check_cache.get(i, ("", "", ""))
            if max_sec > 0 and audio_sec > max_sec:
                dur_info = f"🔴 {audio_sec:.1f}s"
                status = f"⚠️ {audio_sec:.1f}s/{max_sec:.1f}s 超過"
            else:
                dur_info = f"{audio_sec:.1f}s"
                status = "✅ 生成済"
        elif not fname:
            voice_check = ""
            speech_status = ""
            transcribed = ""
            dur_info = ""
            status = "⏭️ スキップ"
        else:
            voice_check = ""
            speech_status = ""
            transcribed = ""
            dur_info = ""
            status = "⬜ 未生成"
        rows.append([i, fname, serif, prompt, dur_info, voice_check, speech_status, transcribed, status])
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)
