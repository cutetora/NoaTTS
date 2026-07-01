"""デーモン起動 (引数解析・シグナル・スレッド起動)。"""
import os
import sys
import signal
import argparse
import threading

from daemon import tuning
from .runtime import BASE_DIR, DEFAULT_VOICE, DAEMON_PID_PATH, _stop_event, cleanup_tmp_say
from .tuning import _load_gap, _load_firstcut, _load_nosplit, _load_tailpad
from .worker import TTSWorker
from .servers import pipe_server, file_watcher, http_server

# ─── エントリポイント ───

def main():
    parser = argparse.ArgumentParser(description="NoaTTSデーモン")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    args = parser.parse_args()

    # PID記録
    DAEMON_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

    def _on_signal(sig, frame):
        print("[daemon] シグナル受信、終了します", flush=True)
        _stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    sys.path.insert(0, str(BASE_DIR))
    os.chdir(str(BASE_DIR))

    _load_gap()  # gap.txt があれば文間無音を復元
    _load_firstcut()  # firstcut.txt があれば1文目早切り設定を復元
    _load_nosplit()  # nosplit.txt があれば分割しない閾値を復元
    _load_tailpad()  # tailpad.txt があれば末尾余韻を復元
    print(f"[daemon] gap:{tuning._gap_sec}秒 firstcut:{tuning._first_cut}字 nosplit:{tuning._nosplit}字 tailpad:{tuning._tail_pad_sec}秒", flush=True)

    # 読み上げの使い捨て一時WAV(tmp_say/)を掃除。増え続けるのを防ぐ。
    cleanup_tmp_say()
    print("[daemon] tmp_say/ を掃除しました", flush=True)

    worker = TTSWorker(args.voice)

    # ファイル監視を別スレッドで起動 (transcript非依存の読み上げ経路)
    fw = threading.Thread(target=file_watcher, args=(worker,), daemon=True)
    fw.start()

    # HTTP サーバーを別スレッドで起動 (別開発・ブラウザからの読み上げ経路)
    hs = threading.Thread(target=http_server, args=(worker,), daemon=True)
    hs.start()

    # pipe サーバーはメインスレッドで起動 (named pipe は Windows 専用)。
    # Mac/Linux では pipe を使わず、HTTP API / ファイル監視の経路だけで待受する
    # (メインスレッドは停止イベントまでブロックして daemon を生かす)。
    import os as _os
    if _os.name == "nt":
        pipe_server(worker)
    else:
        print("[daemon] named pipe は Windows のみ — HTTP/ファイル監視で待受します", flush=True)
        try:
            _stop_event.wait()
        except KeyboardInterrupt:
            pass

    try:
        DAEMON_PID_PATH.unlink()
    except Exception:
        pass
    print("[daemon] 終了", flush=True)


if __name__ == "__main__":
    main()
