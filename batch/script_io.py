"""台本ファイル(CSV/Excel)の読込・保存と、生成結果のエクスポート。"""
import os
import time
from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd
import soundfile as sf

from engine.engine_control import cfg
from . import state
from .state import SCRIPT_COLUMNS, RESULT_COLUMNS, generated_audio


def create_template():
    """台本テンプレートを生成し、そのまま読み込んでセリフテーブルへ反映する。

    同梱の sample_script.csv (記入例・区切り行つき8カラム) をテンプレ元に使い、
    一時CSVへコピーしてから load_script_file に通す。これにより
    テーブル表示・キャラ抽出・上書き保存用パス(state._loaded_file_path)が
    通常の読み込みと同じ経路で揃う。戻り値は load_script_file と同形。
    返り値: (df, status, char_dropdown_update, download_file_update)
    """
    import tempfile
    from config import BASE_DIR

    sample = BASE_DIR / "sample_script.csv"
    if sample.exists():
        df = pd.read_csv(sample, encoding="utf-8-sig")
    else:
        # フォールバック: 同梱サンプルが無い場合の最小テンプレ (8カラム)
        df = pd.DataFrame(columns=SCRIPT_COLUMNS)
        df.loc[0] = ["1", "クールで低い声の青年、無愛想で言葉少な", "001_taro_ohayo",
                     "おはようございます", "", "", "少し照れながら", ""]
        df.loc[1] = ["2", "明るく元気なお姉さん、ハキハキした話し方", "002_hanako_tenki",
                     "今日は良い天気ですね", "", "", "穏やかに微笑みながら", "★"]

    path = os.path.join(tempfile.gettempdir(), "script_template.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")

    class _F:  # load_script_file は .name を参照する
        name = path
    out_df, status, char_update = load_script_file(_F())
    status = "テンプレートを作成しました。編集後「上書き保存」で同じファイルに保存できます。 / " + status
    return out_df, status, char_update, gr.update(value=path, visible=True)


def load_script_file(file):
    if file is None:
        return None, "ファイルを選択してください", gr.update(choices=[])
    try:
        path = file.name if hasattr(file, 'name') else file
        state._loaded_file_path = path
        if path.endswith((".xlsx", ".xls")):
            # 全シートを読み込んで連結
            sheets = pd.read_excel(path, sheet_name=None)
            df = pd.concat(sheets.values(), ignore_index=True) if sheets else pd.DataFrame()
        else:
            df = pd.read_csv(path, encoding="utf-8-sig")

        # Normalize column names
        col_map = {}
        for col in df.columns:
            c = str(col).strip()
            if c in ("ID", "No", "no", "id"):
                col_map[col] = "ID"
            elif "キャラ" in c or "性格" in c or "属性" in c:
                col_map[col] = "キャラ(性格)"
            elif "ファイル" in c or "file" in c.lower():
                col_map[col] = "ファイル名"
            elif "仮名" in c or "読み" in c or "ひらがな" in c:
                col_map[col] = "セリフ仮名"
            elif "感情" in c:
                col_map[col] = "感情"
            elif "システムプロンプト" in c or "指示" in c or "プロンプト" in c:
                col_map[col] = "Qwen3TTSシステムプロンプト"
            elif "セリフ" in c or "台詞" in c:
                col_map[col] = "セリフ"
            elif "おすすめ" in c or "推奨" in c or "recommend" in c.lower():
                col_map[col] = "おすすめ"
        df = df.rename(columns=col_map)

        # Ensure all columns exist
        for c in SCRIPT_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        df = df[SCRIPT_COLUMNS]
        # セクション区切り行を除外: ID が "■" 始まり (例: "■ デフォルト")
        df = df[~df["ID"].astype(str).str.strip().str.startswith("■")]
        # ファイル名が完全に空の行も除外（見出し/空行）
        df = df[df["ファイル名"].astype(str).str.strip() != ""]
        df = df.reset_index(drop=True)
        # Forward fill: Excelの結合セル対応（キャラ・IDなど上のセルと同じ値で埋める）
        for col in ["ID", "キャラ(性格)"]:
            if col in df.columns:
                df[col] = df[col].replace("", np.nan).ffill()
        df = df.fillna("")

        # Check output/ for existing WAV files
        out_path = Path(cfg.output_dir)
        existing_count = 0
        missing_count = 0
        for i in range(len(df)):
            fname = str(df.iloc[i]["ファイル名"]).strip()
            if not fname:
                continue
            fname_clean = "".join(c for c in fname if c.isalnum() or c in "_-.").strip().rstrip(".")
            if (out_path / f"{fname_clean}.wav").exists():
                existing_count += 1
            else:
                missing_count += 1

        # Extract unique キャラ(性格) values for voice mapping
        chars = sorted(df["キャラ(性格)"].unique().tolist())
        chars = [c for c in chars if c]

        star_count = int((df["おすすめ"].astype(str).str.strip() == "★").sum())
        status_parts = [f"{len(df)} 行読み込み完了 (キャラ: {len(chars)}種)"]
        if star_count:
            status_parts.append(f"★: {star_count}件")
        if existing_count:
            status_parts.append(f"生成済WAV: {existing_count}件")
        if missing_count:
            status_parts.append(f"未生成: {missing_count}件")
        return df, " / ".join(status_parts), gr.update(choices=chars)
    except Exception as e:
        return None, f"読み込みエラー: {e}", gr.update(choices=[])


def save_script_table(df_data):
    """Overwrite the original Excel/CSV file with edited table data."""
    if df_data is None or len(df_data) == 0:
        return "データがありません"
    if not state._loaded_file_path:
        return "元ファイルが不明です（ファイルを読み込み直してください）"
    try:
        df = pd.DataFrame(df_data, columns=SCRIPT_COLUMNS) if not isinstance(df_data, pd.DataFrame) else df_data
        path = state._loaded_file_path
        if path.endswith((".xlsx", ".xls")):
            df.to_excel(path, index=False)
        else:
            df.to_csv(path, index=False, encoding="utf-8-sig")
        return f"保存しました → {path}"
    except Exception as e:
        return f"保存エラー: {e}"


def save_result_table(result_data, output_dir):
    """Save generation result table as a separate Excel file."""
    if result_data is None or len(result_data) == 0:
        return "生成結果がありません"
    try:
        df = pd.DataFrame(result_data, columns=RESULT_COLUMNS) if not isinstance(result_data, pd.DataFrame) else result_data
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        fpath = out_path / "generation_result.xlsx"
        df.to_excel(str(fpath), index=False)
        return f"生成結果を保存しました → {fpath}"
    except Exception as e:
        return f"保存エラー: {e}"


def export_all(df_data, output_dir, progress=gr.Progress()):
    if not generated_audio:
        return "生成済み音声がありません"
    try:
        df = pd.DataFrame(df_data, columns=SCRIPT_COLUMNS) if not isinstance(df_data, pd.DataFrame) else df_data
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        exported = 0
        for idx, (wav, sr) in generated_audio.items():
            row = df.iloc[idx]
            fname = str(row["ファイル名"]).strip()
            if not fname:
                row_id = str(row["ID"]).strip() or str(idx + 1)
                char_name = str(row["キャラ(性格)"]).strip() or "unknown"
                text_head = str(row["セリフ"])[:10].replace(" ", "_")
                fname = f"{row_id}_{char_name}_{text_head}"
            # Sanitize
            fname = "".join(c for c in fname if c.isalnum() or c in "_-.").strip().rstrip(".")
            if not fname:
                fname = f"row_{idx}"
            fpath = out_path / f"{fname}.wav"
            sf.write(str(fpath), wav, sr)
            exported += 1
            progress(exported / len(generated_audio), desc=f"エクスポート中 {exported}/{len(generated_audio)}")


        return f"{exported} ファイルをエクスポートしました → {out_path}"
    except Exception as e:
        return f"エクスポートエラー: {e}"
