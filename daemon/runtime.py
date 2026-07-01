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
# 音声キャッシュ(WAV使い回し)。同じ文+声+感情+速度なら合成をスキップして再生する。
# 既定はOFF。/cache エンドポイント or cache.flag で切替。
CACHE_DIR = BASE_DIR / "cache"
CACHE_FLAG_PATH = BASE_DIR / "tts_cache.flag"  # 存在=ON / 無し=OFF (既定OFF)
# 読み上げの使い捨て一時WAV置き場。一括生成の output/ とは分離する。
# daemon起動時に中身を掃除して増え続けるのを防ぐ。
TMP_SAY_DIR = BASE_DIR / "tmp_say"


def cleanup_tmp_say():
    """tmp_say/ の古い一時WAVを全削除する。daemon起動時に呼ぶ。"""
    try:
        if TMP_SAY_DIR.is_dir():
            for f in TMP_SAY_DIR.glob("*.wav"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass
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


def dispatch_speak(worker, cleaned: str, caption=None, cache=None):
    """前の読み上げをキャンセルして新しいテキストの読み上げを開始する。
    pipe・ファイル監視・HTTP の全経路から呼ばれる共通入口。
    caption: HTTP /say で指定された一時感情 (None=ボイス既定)。
    cache:   HTTP /say で指定された一時キャッシュON/OFF (None=既定に従う)。"""
    global _current_speak_thread
    with _speak_lock:
        worker.cancel()
        prev = _current_speak_thread
        if prev is not None and prev.is_alive():
            prev.join(timeout=2.0)
        t = threading.Thread(target=worker.speak, args=(cleaned, caption, cache), daemon=True)
        _current_speak_thread = t
        t.start()


def dispatch_dialogue(worker, segments, cache=None):
    """複数キャラの掛け合いを声を切り替えながら連続再生する (HTTP /say_dialogue 用)。
    前の読み上げをキャンセルして新規開始する点は dispatch_speak と同じ。
    segments: [{"voice","text","caption?"}, ...]"""
    global _current_speak_thread
    with _speak_lock:
        worker.cancel()
        prev = _current_speak_thread
        if prev is not None and prev.is_alive():
            prev.join(timeout=2.0)
        t = threading.Thread(target=worker.speak_dialogue, args=(segments, cache), daemon=True)
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
