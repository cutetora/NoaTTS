"""セリフ一括生成ドメイン (batch パッケージ)。

旧 batch.py を機能別に分割したもの。公開APIは従来どおりここから import する
(`from batch import run_batch_generation` 等は無変更で動く)。
  state.py      … 共有状態 (キャッシュ/列定義/停止フラグ)
  checks.py     … 声質/セリフ照合と結果テーブル
  script_io.py  … 台本の読込/保存/エクスポート
  generation.py … 一括生成本体 (run_batch_generation)
  results.py    … 行操作 (再生成/チェック) と NGレポート
"""
from .state import (
    SCRIPT_COLUMNS, RESULT_COLUMNS, generated_audio, voice_check_cache,
    speech_check_cache, generation_context,
)
from .checks import run_voice_check, build_result_table
from .script_io import create_template, load_script_file, save_script_table, save_result_table, export_all
from .generation import assign_voice_to_char, stop_batch, run_batch_generation
from .results import (
    on_result_row_select, generate_ng_report, export_ng_excel,
    regenerate_row, check_row,
)
