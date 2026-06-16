import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "settings.json"


@dataclass
class AppConfig:
    # TTS
    tts_engine_type: str = "qwen3"  # "qwen3" or "irodori"
    tts_model_size: str = "1.7B"
    tts_device: str = "cuda:0"
    default_language: str = "Japanese"

    # 使用モデル指定 (空文字 = 各エンジンの既定モデルを使う)
    # モデル管理UI でユーザーが選んだ HF repo_id をここに永続化する。
    irodori_checkpoint: str = ""        # 例 "Aratako/Irodori-TTS-500M-v3"
    irodori_vd_checkpoint: str = ""     # VoiceDesign 用

    # LLM
    llm_provider: str = "claude"  # "claude" or "ollama"
    claude_model: str = "haiku"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:27b"

    # Instruct template (属性 > 感情 > 指示)
    instruct_template: str = (
        "【最重要】あなたは{attribute}な性格です。"
        "この性格を最も強く反映してください。"
        "感情は「{emotion}」。{instruction}"
    )

    # Paths
    voices_dir: str = str(BASE_DIR / "voices")
    output_dir: str = str(BASE_DIR / "output")
    presets_dir: str = str(BASE_DIR / "presets")

    # save 時に書き出さないフィールド (環境依存の絶対パス。BASE_DIR 基準で
    # 毎回再計算されるため保存不要。保存すると他環境で壊れる/配布で邪魔になる)
    _NO_SAVE = ("voices_dir", "output_dir", "presets_dir")

    def save(self):
        data = {k: v for k, v in asdict(self).items() if k not in self._NO_SAVE}
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> "AppConfig":
        # settings.json が無ければ settings.default.json からコピーして作る。
        # (配布物は settings.default.json のみ。ユーザーの設定変更で書き換わる
        #  settings.json は git 管理外にしてある)
        if not CONFIG_PATH.exists():
            default_path = BASE_DIR / "settings.default.json"
            if default_path.exists():
                try:
                    CONFIG_PATH.write_text(
                        default_path.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**valid)
        return cls()
