"""
NoaTTSデーモン — モデルをVRAMに常駐させ、named pipe経由でテキストを受け取り即時読み上げ。

起動:
  python noa_tts_daemon.py [--voice def1]

停止:
  pipe に "##QUIT##" を送る、または Ctrl-C

pipe名: \\\\.\\pipe\\noa_tts
プロトコル: UTF-8テキストを送るだけ。応答なし (fire-and-forget)。
複数リクエストが来た場合: 現在の再生を中断して新しいテキストを優先する。

読み上げ経路は3本:
  1. named pipe (\\\\.\\pipe\\noa_tts)  — Windowsローカル、トグル無視で必ず読む
  2. ファイル監視 (_tts_say.txt)         — 自動読み上げ用、tts_auto.flag ON時のみ
  3. HTTP API (http://127.0.0.1:7870/)   — 別開発・ブラウザ用、トグル無視で必ず読む
     POST /say  GET /health  POST /stop  GET / (操作パネル画面)
"""
from daemon.main import main

if __name__ == "__main__":
    main()
