"""NoaTTS 読み上げデーモン (パッケージ)。

旧 noa_tts_daemon.py 単一ファイルを機能別に分割。起動は従来どおり
`python noa_tts_daemon.py` (薄い起動口がこのパッケージの main を呼ぶ)。
  runtime.py  … 定数/PID/読み上げ排他ディスパッチ
  textproc.py … clean_text
  tuning.py   … gap/nosplit/firstcut + 文分割
  player.py   … StreamPlayer (連続再生)
  worker.py   … TTSWorker (モデル常駐・生成)
  servers.py  … pipe/ファイル監視/HTTP
  panel_html.py … 操作パネルHTML
  main.py     … 起動
"""
