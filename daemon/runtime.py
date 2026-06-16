"""デーモン共有ランタイム: パス定数・PID・読み上げの排他ディスパッチ。

⚠ _current_speak_thread は再代入されるため、他モジュールからは
`from daemon import runtime` → `runtime._current_speak_thread` で参照すること。
"""
import sys
import os
import re
import argparse
import threading
import queue
import datetime
import signal
from pathlib import Path

# パッケージ化で1階層下がったため、リポジトリルートは parent.parent
# (旧 noa_tts_daemon.py 単一ファイル時代は Path(__file__).parent だった)
BASE_DIR = Path(__file__).resolve().parent.parent
VOICES_DIR = str(BASE_DIR / "voices")
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_VOICE = "noa"
PIPE_NAME = r"\\.\pipe\noa_tts"
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 7870
DAEMON_PID_PATH = BASE_DIR / ".tts_daemon_pid"
# ファイル監視方式: 外部がこのファイルにテキストを書き、daemonが
# 変更を検知して読み上げる。
SAY_FILE = BASE_DIR / "_tts_say.txt"
FLAG_PATH = BASE_DIR / "tts_auto.flag"
# 現在アクティブなボイス名を書き出す (tray がアイコン切替に使う)
ACTIVE_VOICE_FILE = BASE_DIR / "_active_voice.txt"


def write_active_voice(name: str):
    try:
        ACTIVE_VOICE_FILE.write_text(name, encoding="utf-8")
    except Exception:
        pass

# 読み上げキュー: 新しいテキストが来たら古いものを捨てて即差し替え
_play_queue: queue.Queue = queue.Queue()
_stop_event = threading.Event()

# 現在読み上げ中のスレッド (pipe/file/http すべて共通でこれを差し替える)
_speak_lock = threading.Lock()
_current_speak_thread = None


def dispatch_speak(worker, cleaned: str, caption=None):
    """前の読み上げをキャンセルして新しいテキストの読み上げを開始する。
    pipe・ファイル監視・HTTP の全経路から呼ばれる共通入口。
    caption: HTTP /say で指定された一時感情 (None=ボイス既定)。"""
    global _current_speak_thread
    with _speak_lock:
        worker.cancel()
        prev = _current_speak_thread
        if prev is not None and prev.is_alive():
            prev.join(timeout=2.0)
        t = threading.Thread(target=worker.speak, args=(cleaned, caption), daemon=True)
        _current_speak_thread = t
        t.start()


def stop_speaking(worker):
    """読み上げを中断する (HTTP /stop 用)。"""
    global _current_speak_thread
    with _speak_lock:
        worker.cancel()
        prev = _current_speak_thread
        if prev is not None and prev.is_alive():
            prev.join(timeout=2.0)
        _current_speak_thread = None
