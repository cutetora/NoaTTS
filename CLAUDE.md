# NoaTTS — 開発・操作ガイド

ローカルで動く日本語TTS（音声合成）アプリ。モデルをVRAMに常駐させ、テキストを投げると即座に読み上げる。ユーザー向けの概要・セットアップは [README.md](README.md) を参照。このファイルは、コードを触る／アプリを操作する際の補足メモ。

## 構成

- **[noa_tts_daemon.py](noa_tts_daemon.py)** — 中核。モデルをVRAM常駐させ、3経路で受け取ったテキストを読み上げる。
- **[tts_engine.py](tts_engine.py) / [irodori_engine.py](irodori_engine.py)** — TTSエンジン（Qwen3-TTS / Irodori-TTS）。`settings.json` の `tts_engine_type` で切替。
- **[voice_manager.py](voice_manager.py)** — ボイスカード（`voices/<名前>/config.json`）の読み書き。
- **[app.py](app.py)** — Gradio の Voice Studio（ボイス作成・編集 UI、:7860）。
- **[tray.py](tray.py)** — タスクトレイ常駐ランチャー。daemon・UI をまとめて管理。

## 読み上げの3経路

daemon は次の3つの入口を持つ。いずれも受信テキストを `clean_text`（絵文字・マークダウン・コードブロックを除去）で整形してから読み上げる。

1. **HTTP API** (`http://127.0.0.1:7870/`) — `POST /say` 等。トグルに関係なく常に読む。
2. **ファイル監視** (`_tts_say.txt`) — `tts_auto.flag` が存在する間だけ、ファイルが書き換わると読む。
3. **named pipe** (`\\.\pipe\noa_tts`) — Windowsローカル。トグルに関係なく常に読む。

## 起動・停止

- 起動: `python noa_tts_daemon.py [--voice <名前>]`（既定ボイスは `def1`）。
- 停止/再起動: `.tts_daemon_pid` のPIDへ SIGTERM、または `POST /quit`。
- トレイ常駐でまとめて起動: `run_tray.bat`。

## 自動読み上げ（ファイル監視）の使い方

外部スクリプトから「テキストをファイルに書くだけ」で読み上げさせたいとき:

1. `tts_auto.flag` を作成（中身は任意、例: `on`）。
2. `_tts_say.txt` に読み上げたいテキストを書き込む。daemon が変更を検知して読む。
3. 止めるときは `tts_auto.flag` を削除。

フラグが無い間、ファイル監視経路は無視される（HTTP / pipe は影響を受けない）。

## 環境メモ

- Python 3.11 を想定（GUI・daemon の依存はこの環境に入れてある）。
- `output/` に生成WAVが溜まる。`gap.txt` / `nosplit.txt` / `firstcut.txt` / `pause.txt` は daemon の調整値の永続化ファイル（HTTP経由で変更すると書き換わる）。
