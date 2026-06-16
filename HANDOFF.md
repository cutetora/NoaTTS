# 引き継ぎメモ（2026-06-16）

セッションが長くなり停止が頻発したため引き継ぎ。次の担当はこれを読んで続行すること。

## 現在の git 状態

- ブランチ: **`refactor/folder-structure`**（main 未マージ）
- 作業ツリー: クリーン
- **origin より 3コミット先行（未push）** → 最初に `git push origin refactor/folder-structure` で退避推奨
- main は無傷。問題が起きたら `git checkout main` で即戻れる

### このブランチのコミット（新→古）
```
8d5ccc4 fix: VoiceDesign を読み上げ本体に選んでも選択が保持されるように
e803c06 Revert "fix: 読み上げ設定の使用モデルから VoiceDesign を除外"
b25fd86 fix: 読み上げ設定の使用モデルから VoiceDesign を除外（←誤り。e803c06でrevert済）
f2ed084 docs: README にフォルダ構成とテンプレ作成の挙動を追記
f47da25 fix: engine/ 移動で状態ファイルが engine/assets を指していた不具合
7809e03 fix: マスコットのミュートで再生中の読み上げも停止する
86511c2 feat: テンプレート作成でセリフテーブルまで反映、上書き保存と連動
3d1a8a7 fix: 台本テンプレートを正式8カラムに修正、xlsxテンプレ追加
b9780bf refactor: 設定・読み辞書を conf/ へ集約、未使用 tts_dict.toml を削除
4f42680 refactor: UI層を ui/ パッケージへ集約
72842f4 refactor: ボイス管理層を voice/ パッケージへ集約
58b5352 refactor: TTSコア層を engine/ パッケージへ集約
ca68162 refactor: テストを tests/ へ集約
```

## このセッションで完了したこと

1. **フォルダ整理（リファクタ）** — ルートの .py を 23→9個に削減。`engine/ voice/ ui/ conf/ tests/` にパッケージ化。
   - エントリポイント（app.py / tray.py / noa_tts_daemon.py / noa_launcher.py / tts_api_window.py / webview_window.py / download_models.py）と `config.py` はルート据え置き（bat/exe/PyInstaller がファイル名で起動・パス基準のため）。
   - **src/ 移動は却下**（`Path(__file__).parent` で assets/voices/output/conf を解決する箇所が散在し壊れるため）。
2. **設定を conf/ へ集約** — settings.json / settings.default.json / reading_dict.json。フォルダ名は `config.py` との import 衝突回避で **`conf`**（`config/` は不可）。未使用 tts_dict.toml 削除。
3. **テンプレート作成バグ修正** — 「テンプレート作成」が②セリフテーブルに反映＋元ファイルパスをセットし上書き保存も効くように（`batch/script_io.py` の `create_template`）。
4. **マスコットのミュート修正** — 🔇で再生中の音声も `/stop` で止める。音量リアルタイム変更は daemon構造上不可で「次の発話から」が仕様。
5. **engine/assets バグ修正** — engine_control.py の `_STATE_FILE` を `BASE_DIR` 基準に（engine/移動で engine/assets を指していた）。
6. **「使用モデルを変えても戻る」修正（VoiceDesign）** — `daemon/worker.py` の `switch_model`。VoiceDesign も読み上げ本体として恒久ロード・`_model_repo` 更新・`irodori_checkpoint` 保存。**実機検証済**（VD切替→health反映→caption無しsay成功→main復帰）。
   - 注意: 当初「VoiceDesignをselectから除外」する誤修正(b25fd86)をしたが、ユーザー指摘で revert(e803c06)。VoiceDesignは読み上げに使える（caption無しでも合成可能、実機確認済）。

## 未完了タスク B（次にやること）

ユーザー依頼（原文）:
> ボイスカードでクローンとボイスデザインで設計したやつをわかるようにして、ボイスデザインにはそれに追加して指示の声で同じ声で違う感情って感じでできる？

分解:
1. **ボイスカードで種別（クローン製/ボイスデザイン製）を見分けられるよう表示する**
2. **ボイスデザインのカードに「同じ声で違う感情」を指定**（caption で感情を足し、声は同じまま感情だけ変える）

### 調査済みの土台（重要）
`voice/voice_manager.py` の `VoiceConfig` に**必要なフィールドは既にある**:
- `voice_type: str  # "custom", "design", "clone"` ← 種別はデータ上既に存在。UIで表示できているか要確認。
- `default_caption: str = ""  # Irodori VoiceDesignクローンの既定感情/スタイル(caption)` ← 感情指定の土台も既にある。「空なら無し。デーモン読み上げ・バッチ生成でこの声の基底トーンとして使う」とコメントあり。

### 次にやる調査（タスクBの設計前）
- `ui/ui_voice_create/tuning_panel.py` と `tuning_logic.py` で、保存済みボイスの一覧/調整UIに `voice_type` や `default_caption` を表示・編集する口があるか確認。
- `engine/emotion_emoji.py`（EMOTION_EMOJI）が caption とどう関係するか。VoiceDesign の caption に感情絵文字 or 自由文を入れる設計か。
- engine の `_synthesize(caption=...)`: 既に確認済 → `use_vd=bool(caption)` で caption ありなら VoiceDesign ランタイム使用（`engine/irodori_engine.py:157`）。
- **設計をユーザーに提示してから実装すること**（このセッションは先走って確認過多になった反省）。

## 環境メモ（ハマりポイント）

- **Bash ツールの `python` は Python310（irodori_tts 無し）**。daemon やTTS関連は **Python311**（`C:\Users\ct\AppData\Local\Programs\Python\Python311\python.exe`）。エンジン検証は必ず Python311 フルパスで。
- daemon (:7870) / Voice Studio Gradio (:7860)。daemon はトレイ(tray.py)から起動。**tray を kill すると daemon も子として巻き添えで落ちる**。
- `run_tray.bat` は venv 前提だが **venv は存在しない**。実際は Python311 直起動。起動例:
  `Start-Process Python311\pythonw.exe -ArgumentList "tray.py" -WorkingDirectory "I:\AI_Claud\NoaTTS_clean"`
- TTS通知（CLAUDE.md ルール）: 作業完了ごとに `POST http://127.0.0.1:7870/say` に JSON `{"text":"..."}` を PowerShell でUTF-8送信。daemon停止中は鳴らないが無視して進めてよい。
- ペルソナ: `personas/_active.md`（現在「メカニスト系ボクっ娘」口調＝ボク/君/〜だよー）。

## 推奨する次の一手

1. `git push origin refactor/folder-structure`（退避）
2. タスクB の調査（上記）→ 設計をユーザーに提示 → 実装
3. 全体が固まったら実起動確認 → main へマージ
