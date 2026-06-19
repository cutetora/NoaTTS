# NoaTTS

ローカルで動く日本語TTS（音声合成）アプリ。モデルをVRAMに常駐させて、テキストを投げると即座に読み上げる。声は「ボイスカード」として保存・切替でき、ボイスクローンにも対応する。

- **2つのTTSエンジン**を切替可能 — [Qwen3-TTS](https://huggingface.co/Qwen) / [Irodori-TTS](https://huggingface.co/Aratako)
- **VRAM常駐デーモン** — 初回ロード後は待ち時間なしで読み上げ（待機 約1.3GB）
- **⚡軽量モード** — int4軽量モデルでVRAMを節約（読み上げ中も 約1.5GB）。画像生成やゲームなど重いアプリと同居しやすい
- **3つの入力経路** — HTTP API / ファイル監視 / Windows named pipe
- **感情絵文字スタイル制御**（Irodori） — 文中に 😭😠🥺 などを入れると、声を保ったまま感情が乗る
- **セリフ一括生成** — 台本（CSV/Excel）を読み込み、キャラごとにボイスを割り当ててまとめて音声化
- **タスクトレイ常駐** + Web UI（Gradio）でボイス作成・編集（マスコット「ノア」が使い方を案内）

---

## 動作環境

> Windows 専用（named pipe を使用）。GPU は NVIDIA + CUDA が前提です（CPU のみでの動作は実用的ではありません）。

**最小スペック**（⚡軽量モードで読み上げするだけ）
→ Windows 10/11 (64bit) ／ NVIDIA GPU **VRAM 4GB**（実使用 約2.0GB）／ RAM 8GB ／ SSD 空き 10GB ／ Python 3.11 + CUDA対応 PyTorch

**推奨スペック**（声作成・両エンジン・VoiceDesign も快適）
→ Windows 11 ／ NVIDIA RTX 系 **VRAM 8GB〜**（Qwen3 1.7B も使うなら 12GB〜）／ RAM 16GB〜 ／ SSD 空き 20GB〜

詳細は下表と、その下の VRAM 注記を参照してください。

| 項目 | 最小 | 推奨 |
|---|---|---|
| OS | Windows 10 / 11 (64bit) | Windows 11 (64bit) |
| GPU | NVIDIA（CUDA対応）／VRAM 4GB〜（⚡軽量モード時） | NVIDIA RTX 系／VRAM 8GB〜（Qwen3・VoiceDesign も使うなら 12GB〜） |
| 主に使えるエンジン | Irodori 500M 中心 | Qwen3 1.7B・VoiceDesign も快適に切替 |
| メモリ (RAM) | 8GB | 16GB〜 |
| ストレージ | SSD 空き 10GB〜 | SSD 空き 20GB〜 |
| Python | 3.11 | 3.11 |
| PyTorch | CUDA 対応版 | CUDA 12.x 対応版（動作確認: torch 2.11.0+cu128 / CUDA 12.8） |

> ⚠️ **VRAM 実測値（v1.1.0）** — 何を使うかで大きく変わります（数値は CUDAコンテキスト込みの実使用）。
>
> - **読み上げアプリ（常駐デーモン）のみ ＋ ⚡軽量モード**: **約2.0GB**（モデル本体 約1.5GB ＋ CUDAコンテキスト 約0.5GB）。これが最小構成で、テキストを送って読み上げるだけならこれだけ。**4GB クラスの GPU でも快適**です。
> - **読み上げアプリのみ ＋ 通常モデル（Irodori 500M bf16）**: 約3GB。
> - **Voice Studio（声の作成・編集）も使う場合**: 上記に加えてもう一つモデルが載るので **+2GB ほど**（声作成は重い処理。使い終わると自動で退避します）。VoiceDesign 600M を使う場合は約3GB。
> - **Qwen3-TTS 1.7B（別エンジン・大型）**: 6〜8GB 程度。
>
> → **読み上げ用途だけなら、軽量モードで実質2GB前後**。声作成も使う／両エンジンを切り替える／VoiceDesign も使うなら 8〜12GB あると安心です。

- ストレージは PyTorch（数GB）＋モデルの内訳です。**Irodori 500M ≈ 2GB／Qwen3-TTS 1.7B ≈ 4GB**（使うモデルだけ落とせば節約できます）。
- CUDA バージョンは GPU 世代に依存します（例: RTX 50 系 = cu128、それ以前 = cu121 など）。`setup.bat` の `TORCH_INDEX` で環境に合わせてください。

---

## 入手

どちらかの方法でプロジェクト一式を手に入れます。

- **ZIP（git が無くてもOK・おすすめ）**: [**最新版をダウンロード**](https://github.com/cutetora/NoaTTS/releases/latest) → ページ下の **Assets** にある `Source code (zip)` を落として、好きな場所に展開する。バージョン管理された安定版です。
  - （最新の開発版がほしい場合は、緑の「Code」→「Download ZIP」で main の最新を取得することもできます）
- **git clone（git がある人）**:
  ```bash
  git clone https://github.com/cutetora/NoaTTS.git
  ```

> どちらでも構いません。git が入っていなくても、後述の `setup.bat` が（winget があれば）git を自動で入れるので、最初は ZIP 取得で問題ありません。

---

## セットアップ

> ⚠️ これは「ワンクリックで全部入る」アプリではありません。**Python 3.11 と CUDA 対応 PyTorch を自分で入れる前提**の構成です（PyTorch は環境の CUDA バージョンに依存するため自動化していません）。同梱の `NoaTTS.exe` も Python 環境を呼び出す軽量ランチャーで、依存が無い環境では動きません。

### かんたん: `setup.bat`（CUDA 12.8 / winget 環境向け）

**`setup.bat` をダブルクリック** すると、以下を自動でやります:

1. `git` / `Python 3.11` を winget で導入（無い場合）
2. `venv`（仮想環境）を作成
3. CUDA 12.8 版 PyTorch を導入
4. `requirements.txt` の依存を導入
5. **TTSモデルを事前ダウンロード**（数GB・数分。ここで落とすので初回起動が速い）

> ⚠️ 自動なのは **winget が使えて、GPU が CUDA 12.8 系** の環境だけです。CUDA バージョンが違う場合は `setup.bat` 内の `TORCH_INDEX` を自分の環境に合わせて書き換えてください（`https://download.pytorch.org/whl/cu121` など）。winget が無い環境では、git / Python を手動で入れてから実行します。

終わったら `run_tray.bat`（または `NoaTTS.exe`）で起動します。`venv` があれば各 bat / exe は自動でそれを使います。モデルは setup 時に取得済みなので、起動後すぐ使えます。

### 手動セットアップ

Python 3.11 を推奨。**先に PyTorch を入れてから** 依存をインストールします。

1. **Python 3.11** を導入（`py -3.11` で呼べる状態にする）。
2. **CUDA 対応の PyTorch** を導入（環境の CUDA バージョンに合わせる）。
   <https://pytorch.org/get-started/locally/> から `torch` と `torchaudio` を入れる
   （動作確認: torch 2.11.0+cu128 / CUDA 12.8）。
3. 残りの依存をインストール（TTS エンジンを GitHub から取得するため **git が必要**）。

```bash
pip install -r requirements.txt
```

4. （任意）モデルを事前ダウンロードしておくと初回起動が速くなります。省略した場合は初回起動時に自動取得されます。

```bash
python download_models.py
```

---

## 起動方法

目的に応じて4通り。普段使いは **`NoaTTS.exe` をダブルクリック** が一番ラク。

| やりたいこと | 起動方法 | 説明 |
|---|---|---|
| 普段使い（おすすめ） | **`NoaTTS.exe` をダブルクリック** | アイコン付きで黒窓を出さずにトレイ常駐を起動するランチャー（中身は `run_tray.bat` と同じくトレイ起動） |
| トレイ常駐（bat 版） | `run_tray.bat` | トレイアイコン + Web UI + デーモン管理をまとめて |
| 読み上げだけ使う | `python noa_tts_daemon.py` | デーモン単体。HTTP API(:7870)・ファイル監視・pipe が立つ |
| ボイス作成 Web UI 単体 | `run.bat` | Gradio の Voice Studio(:7860) |

トレイ常駐後の操作:

- **トレイアイコンをダブルクリック** → Voice Studio（Web UI）を開く
- **トレイアイコンを右クリック** → 読み上げ設定・ボイス選択・モデル退避などのメニュー

デーモンのボイスは `--voice <名前>` で指定（既定は `noa`）。同梱ボイスは `noa` のみで、
ほかのボイスは Web UI から自分で作成します。

```bash
python noa_tts_daemon.py --voice noa
```

> `NoaTTS.exe` は `noa_launcher.py` を PyInstaller でビルドしたものです。自分で作り直す場合:
> ```bash
> py -3.11 -m PyInstaller --onefile --noconsole --icon assets/noa.ico --name NoaTTS noa_launcher.py
> ```

---

## HTTP API

デーモン起動中、`http://127.0.0.1:7870/` をブラウザで開くとコントロールパネルが出ます。

| メソッド | パス | 説明 |
|---|---|---|
| `POST` | `/say` | 本文（プレーン or JSON）を読み上げ。トグルOFFでも必ず読む |
| `POST` | `/stop` | 読み上げを中断 |
| `POST` | `/voice` | ボイス切替（`{"name": "..."}`） |
| `POST` | `/speed` | 話速変更（`{"speed": 1.0}`） |
| `POST` | `/gap` | 文間の無音（秒）。`gap.txt` に永続化 |
| `POST` | `/nosplit` | この文字数以下は文分割しない。`nosplit.txt` に永続化 |
| `POST` | `/firstcut` | 1文目の早切り目標文字数（0で無効）。`firstcut.txt` に永続化 |
| `POST` | `/pause` | 音声内ポーズ上限（秒、0で無加工）。`pause.txt` に永続化 |
| `POST` | `/quit` | デーモンを終了 |
| `GET`  | `/health` | 稼働状態（ボイス・話速・各調整値・モデル等のJSON） |
| `GET`  | `/voices` | ボイス一覧 |

`/say` の JSON では `text` のほか、`volume`（0.0〜1.0）と `caption`（その読み上げに限り感情を上書き、Irodoriクローン用）を指定できます。

例:

```bash
# プレーンテキスト
curl -X POST http://127.0.0.1:7870/say -d "テストです。聞こえていますか？"

# JSON（音量・感情つき）
curl -X POST http://127.0.0.1:7870/say -H "Content-Type: application/json" \
  -d "{\"text\": \"おかえりなさい\", \"volume\": 0.8}"
```

絵文字・マークダウン記号・コードブロックは送信時に自動除去されます（感情絵文字は残ります）。

### 自動読み上げ（ファイル監視）

`tts_auto.flag` ファイルが存在する間、`_tts_say.txt` の内容が書き換わると自動で読み上げます。
外部スクリプトから「テキストをファイルに書くだけ」で読み上げさせたい場合に使います。フラグが無ければ無視されます（HTTP / pipe はフラグに関係なく常に読み上げ）。

---

## 感情絵文字（Irodori）

Irodori エンジンでは、読み上げテキストに感情絵文字を埋め込むと、**声（参照音声）はそのままに感情だけ**が乗ります。同じ絵文字を重ねると効果が強まります（実測: 😭1個で音声長 +30%、😭×3で +130%）。通常の装飾絵文字は除去されますが、これらの感情絵文字は残して解釈されます。

| 絵文字 | 効果 | 絵文字 | 効果 |
|---|---|---|---|
| 😭 | 泣き | 🤭 | 含み笑い |
| 😱 | 悲鳴 | 😮‍💨 | 溜息・吐息 |
| 😠 | 怒り | 👂 | 囁き |
| 😰 | 動揺 | 🌬️ | 息切れ |
| 🥺 | 震え声 | ⏩ / 🐢 | 早口 / ゆっくり |

Web UI の絵文字パレットからも挿入できます。

---

## セリフ一括生成

台本（CSV / Excel）を読み込み、登場キャラごとにボイスを割り当てて、まとめて音声ファイルを生成できます（動画・ゲームのセリフ作りなどに）。キャラ⇔ボイスの割り当ては **プリセット**として `presets/<名前>.json` に保存・呼び出しできます。Web UI の「セリフ一括生成」タブから操作します。

サンプル台本（記入例つき）: [sample_script.xlsx](sample_script.xlsx)（Excel・推奨） / [sample_script.csv](sample_script.csv)（CSV）。どちらも Google スプレッドシートでも開けます。「テンプレート作成」ボタンを押すと、このサンプルがその場でセリフテーブルに読み込まれ、編集してそのまま「上書き保存」できます（ダウンロードも可）。

台本の列（順不同・見出し名で自動認識）:

| 列 | 必須 | 説明 |
|---|---|---|
| `ID` | ○ | 通し番号。`■` で始めると区切り見出し行になり生成対象から外れる |
| `キャラ(性格)` | ○ | 声の性格を文章で。**同じ文字列**のキャラには同じボイスが割り当たる |
| `ファイル名` | ○ | 出力WAV名。半角英数と `_ - .` 推奨（全角・記号は除去される） |
| `セリフ` | ○ | 読み上げる本文 |
| `セリフ仮名` | | 読みが不安な語だけ仮名で上書き（任意） |
| `感情` | | 喜 / 怒 / 哀 / 楽 など（任意） |
| `Qwen3TTSシステムプロンプト` | | 話し方・口調の指示（任意） |
| `おすすめ` | | `★` を入れると採用候補マーク。読み込み時に件数集計される |

---

## ボイスカード

`voices/<名前>/` にボイスごとの `config.json`（話者・seed・参照音声・話速など）と参照音声を置きます。Web UI（`run.bat`）から作成・編集できます。

> ⚠️ **同梱ボイスについて**: このリポジトリに同梱されるボイスは `noa`（自作）のみです。あなたがクローン作成した（参照音声に第三者の録音を使った）ボイスを追加して再配布する場合は、各自で権利関係を確認してください。

---

## フォルダ構成（開発者向け）

コードは機能ごとにパッケージへ分類しています。エントリポイントと設定パス基準（`config.py`）はルート直下のままです。

```
engine/   TTS合成コア（tts_engine, irodori_engine, engine_control, audio_utils, models_catalog, emotion_emoji, text_utils）
voice/    ボイス管理（voice_manager, voice_creation, preset_manager）
ui/       Voice Studio のUI部品（mascot, ui_voice_create/）
daemon/   読み上げデーモン
batch/    セリフ一括生成
conf/     設定・読み辞書（settings.json※ / settings.default.json / reading_dict.json）
tests/    テスト
assets/ docs/ voices/ presets/   素材・データ
```

ルート直下の `.py` はエントリポイント（`app.py` / `tray.py` / `noa_tts_daemon.py` / `noa_launcher.py` / `tts_api_window.py` / `webview_window.py` / `download_models.py`）と、全体が参照する基盤（`config.py`）です。`bat`・`NoaTTS.exe` はこれらをファイル名で起動するため、移動していません。

> ※ `conf/settings.json` は初回起動時に `conf/settings.default.json` からコピー生成され、以後ユーザー設定で書き換わるため git 管理外です。

---

## 更新履歴

変更点は [CHANGELOG.md](CHANGELOG.md) を参照してください。最新版は **v1.1.0**（⚡軽量モード・VRAM大幅削減）。

---

## ライセンス

本アプリのコードは [MIT License](LICENSE) で配布します。
ただし、使用する TTS モデル（[Qwen3-TTS](https://github.com/dffdeeq/Qwen3-TTS-streaming) / [Irodori-TTS](https://github.com/Aratako/Irodori-TTS)）および同梱ボイスのライセンスは、各提供元の条項に従います。
