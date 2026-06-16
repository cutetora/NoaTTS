"""セリフ一括生成ドメインの共有状態。

生成キャッシュ(dict)はin-placeで更新されるため from-import 可。
⚠ batch_stop_requested と _loaded_file_path は再代入されるため、
他モジュールからは必ず `from batch import state` → `state.xxx` で読み書きすること。
"""
import numpy as np

# Script generation state
generated_audio: dict[int, tuple[np.ndarray, int]] = {}  # row_idx -> (audio, sr)
voice_check_cache: dict[int, tuple[str, float]] = {}  # row_idx -> (label, f0)
speech_check_cache: dict[int, tuple[str, str, str]] = {}  # row_idx -> (status, transcription, detail_reason)
# Full generation context for NG analysis
generation_context: dict[int, dict] = {}  # row_idx -> {all TTS input data}
batch_stop_requested: bool = False

SCRIPT_COLUMNS = [
    "ID", "キャラ(性格)", "ファイル名",
    "セリフ", "セリフ仮名", "感情", "Qwen3TTSシステムプロンプト", "おすすめ",
]


RESULT_COLUMNS = [
    "行", "ファイル名", "セリフ", "Qwen3TTSシステムプロンプト", "音声長", "声質チェック", "セリフチェック", "書き起こし", "状態",
]




# Track the loaded file path for overwrite save
_loaded_file_path: str = ""
