"""TTSエンジンのライフサイクル管理と全タブ共通の進捗モニター。

app.py から分離。アプリ全体で共有する状態の置き場:
  - cfg / vm          … 設定とボイスマネージャ (再代入されない。from-import可)
  - engine            … ロード済みエンジン (実行時に再代入される。必ず
                        `import engine_control as ec; ec.engine` で参照すること)
  - preload_status 等 … プリロード進捗 (同上。ec.preload_status で参照)
  - monitor           … ActivityMonitor (再代入されない。from-import可)
batch.py / app.py の両方がここに依存する (循環importを避けるための共有層)。
"""
import time
import threading
from pathlib import Path

from config import AppConfig
from voice.voice_manager import VoiceManager
from engine.tts_engine import TTSEngine

# ── Globals ──
cfg = AppConfig.load()
vm = VoiceManager(cfg.voices_dir)
engine: TTSEngine | None = None
preload_status: str = "未ロード"

# トレイアプリ向け状態フラグ
is_generating: bool = False  # 生成中=True (トレイアイコンが走る)
engine_loaded_at: float = 0.0  # 最後にエンジンが使われた時刻 (アンロード判定用)


_STATE_FILE = Path(__file__).parent / "assets" / "_state.txt"


def mark_generating(state: bool):
    """生成中フラグの更新 (トレイアプリ・自動アンロード判定用)."""
    global is_generating, engine_loaded_at
    is_generating = state
    if state:
        import time as _t
        engine_loaded_at = _t.time()
    # トレイアプリ向けに状態を書き出し
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text("run" if state else "walk", encoding="utf-8")
    except Exception:
        pass


def unload_engine_action():
    """エンジンを退避してVRAMを解放."""
    global engine
    if engine is None:
        return "既にアンロード済み"
    try:
        engine.unload()
    except Exception:
        pass
    engine = None
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass
    return "✅ モデルを退避しました (VRAM解放)"


# ── Activity Monitor ──
class ActivityMonitor:
    """Global progress tracker visible across all tabs."""

    def __init__(self):
        self.task: str = ""
        self.progress: float = 0.0
        self.detail: str = ""
        self.start_time: float = 0.0
        self.is_active: bool = False
        self.log: list[str] = []

    def start(self, task: str):
        self.task = task
        self.progress = 0.0
        self.detail = ""
        self.start_time = time.time()
        self.is_active = True
        self._add_log(f"開始: {task}")

    def update(self, progress: float, detail: str = ""):
        self.progress = progress
        if detail:
            self.detail = detail

    def log_step(self, msg: str):
        self._add_log(msg)
        self.detail = msg

    def finish(self, msg: str = ""):
        elapsed = time.time() - self.start_time
        finish_msg = msg or f"{self.task} 完了"
        self._add_log(f"{finish_msg} ({elapsed:.1f}s)")
        self.is_active = False
        self.progress = 1.0
        self.detail = finish_msg

    def _add_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")
        if len(self.log) > 15:
            self.log = self.log[-15:]

    def render(self) -> str:
        lines = []
        if self.is_active:
            elapsed = time.time() - self.start_time
            bar_len = 20
            filled = int(bar_len * self.progress)
            bar = "█" * filled + "░" * (bar_len - filled)
            pct = int(self.progress * 100)
            lines.append(f"● {self.task}")
            lines.append(f"  {bar} {pct}%  ({elapsed:.0f}秒経過)")
            if self.detail:
                lines.append(f"  → {self.detail}")
        else:
            lines.append("待機中")

        if self.log:
            lines.append("")
            lines.append("─── ログ ───")
            for entry in self.log[-8:]:
                lines.append(entry)
        return "\n".join(lines)


monitor = ActivityMonitor()


def get_engine():
    """Return engine based on config.tts_engine_type (qwen3 or irodori)."""
    global engine
    if engine is None:
        if cfg.tts_engine_type == "irodori":
            from engine.irodori_engine import IrodoriEngine
            engine = IrodoriEngine(
                device=cfg.tts_device,
                checkpoint=(cfg.irodori_checkpoint or None),
                vd_checkpoint=(cfg.irodori_vd_checkpoint or None),
            )
        else:
            engine = TTSEngine(model_size=cfg.tts_model_size, device=cfg.tts_device)
    return engine


def _engine_type_changed() -> bool:
    """Check if loaded engine matches current config."""
    if engine is None:
        return False
    cls_name = type(engine).__name__
    if cfg.tts_engine_type == "irodori" and cls_name != "IrodoriEngine":
        return True
    if cfg.tts_engine_type == "qwen3" and cls_name != "TTSEngine":
        return True
    return False


preload_start_time: float = 0.0
preload_done: bool = False


def _preload_worker():
    """Background thread: load model, apply optimizations, warmup torch.compile."""
    global preload_status, preload_start_time, preload_done
    try:
        preload_start_time = time.time()
        preload_status = "⏳ [0/5] エンジン初期化中..."
        eng = get_engine()

        def on_progress(msg):
            global preload_status
            elapsed = time.time() - preload_start_time
            preload_status = f"⏳ {msg} ({elapsed:.0f}秒経過)"

        t0 = time.time()
        # Branch by engine type
        if cfg.tts_engine_type == "irodori":
            # Irodori: just load runtime, no warmup needed
            eng._load_model("irodori", on_progress=on_progress)
            load_time = time.time() - t0
            total = time.time() - preload_start_time
            preload_status = f"✅ 準備完了 (Irodori-TTS v3 ロード {load_time:.1f}s)"
        else:
            # Qwen3-TTS: load + warmup torch.compile
            eng._load_model("custom", on_progress=on_progress)
            load_time = time.time() - t0

            warmup_texts = [
                "Warmup one two three.",
                "Hello, this is a longer warmup test sentence for compilation.",
                "こんにちは、ウォームアップテストです。",
                "おはようございます、今日はとても良い天気ですね。お散歩に行きましょう。",
            ]
            t1 = time.time()
            for i, txt in enumerate(warmup_texts):
                elapsed = time.time() - preload_start_time
                preload_status = f"⏳ ウォームアップ中 {i+1}/{len(warmup_texts)} (torch.compile コンパイル中, {elapsed:.0f}秒経過)"
                eng.generate_custom_voice(
                    text=txt, language="English", speaker="Ryan", instruct="", num_samples=1
                )
            warmup_time = time.time() - t1

            total = time.time() - preload_start_time
            preload_status = (
                f"✅ 準備完了 (ロード {load_time:.1f}s + "
                f"最適化ウォームアップ {warmup_time:.1f}s = 合計 {total:.0f}s)"
            )
        preload_done = True
    except Exception as e:
        preload_status = f"❌ プリロードエラー: {e}"
        preload_done = True


def start_preload():
    """Start preloading in a background thread."""
    t = threading.Thread(target=_preload_worker, daemon=True)
    t.start()


def _wait_for_preload():
    """Block until background preload finishes (if running)."""
    while not preload_done and preload_start_time > 0:
        time.sleep(0.5)
