# ポータブル / ワンクリック配布の作り方

**目的**: ユーザーが Python も CUDA も自分で入れずに、**展開して実行するだけ**で動く配布物を作る（VOICEVOX 並みの導入体験を目指す）。

---

## 方式（なぜこの作りか）

| 候補 | 可否 | 理由 |
|---|---|---|
| `python -m venv` をコピー | ❌ | 標準ライブラリ/tkinter が元の Python に依存し、配布先で壊れる |
| 埋め込み版 Python (embeddable) | △ | 軽いが **tkinter なし**（本アプリは tts_api_window でクリップボードに tkinter 使用） |
| **python-build-standalone (relocatable)** | ✅ | **再配置可能 + tkinter 同梱**。`build_portable.bat` はこれを使う |

torch の CUDA ホイールは **CUDA ランタイム(cuDNN/cuBLAS 等)を同梱**しているため、ユーザー側に CUDA Toolkit は不要。**最新の NVIDIA ドライバだけ**あれば動く。

---

## 作り方

```bat
REM 既定 (cu121 = 広い互換性)
build_portable.bat

REM 新しめGPU向けに CUDA を変える
set CUDA_TAG=cu128 & build_portable.bat
```

生成物:
- `dist\NoaTTS-portable\` … 展開済みフォルダ（`NoaTTS起動.bat` で起動）
- `dist\NoaTTS-portable-<cuda>.zip` … 配布用 ZIP

ユーザー手順は **「ZIP を展開 → `NoaTTS起動.bat` をダブルクリック」** だけ（初回のみ TTS モデルを自動ダウンロード）。

---

## CUDA タグの選び方（配布用）

| タグ | 対象 | 備考 |
|---|---|---|
| **cu121** | 広い互換性（既定） | 多くのドライバで動く。配布の基本はこれ |
| cu128 | RTX 50 系など新しめ | 最新ドライバ必須 |

理想は **cu121 と cu128 の 2 種類**を用意し、ユーザーに選ばせる。1 種類だけなら **cu121** が無難。

---

## 配布のハードル（重要）

- ZIP サイズは **おおよそ 3〜6GB**（torch+CUDA が大半）。
- **GitHub Releases は 1 ファイル 2GB 上限** → 大きい ZIP はそのまま置けない。対策:
  - **Hugging Face** のモデルリポ等に ZIP を置き、GitHub Release からリンクする（推奨・無料で大容量）。
  - もしくは ZIP を分割（`7z` のボリューム分割など）。
- モデル（Irodori/DACVAE, 数GB）は **初回起動時に自動DL** される。完全オフライン配布にしたい場合のみ、ビルド時に `HF_HOME` を `dist\NoaTTS-portable\hf_cache` に向けて `download_models.py` を実行し、そのキャッシュを同梱する（その分 ZIP が更に数GB増える）。

---

## さらに「.exe インストーラ」にしたい場合（任意・上級）

`dist\NoaTTS-portable\` を **Inno Setup**（無料）で包むと、ダブルクリックで入る `NoaTTS-Setup.exe` が作れる。最小の `installer.iss` 例:

```ini
[Setup]
AppName=NoaTTS
AppVersion=1.1.0
DefaultDirName={autopf}\NoaTTS
DefaultGroupName=NoaTTS
OutputBaseFilename=NoaTTS-Setup
Compression=lzma2
SolidCompression=yes

[Files]
Source: "dist\NoaTTS-portable\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\NoaTTS"; Filename: "{app}\python\pythonw.exe"; Parameters: "tray.py"; WorkingDir: "{app}"
Name: "{commondesktop}\NoaTTS"; Filename: "{app}\python\pythonw.exe"; Parameters: "tray.py"; WorkingDir: "{app}"
```

---

## 既知の注意点

- **未署名のため SmartScreen 警告**が出る（「詳細情報 → 実行」で回避）。本格配布ではコード署名証明書があると親切（有料）。
- **アンチウイルスの誤検知**（pythonw.exe/同梱 exe）。VirusTotal で確認しておくと安心。
- 配布前に **別の（できればクリーンな）Windows 機**で「展開 → 起動 → 1 文読み上げ」まで必ず実機確認する（ビルドした機械では気づけない依存があるため）。
- ユーザーには **NVIDIA GPU + 最新ドライバ**が必要（GPU 無し/古いドライバでは起動しない）。

---

## まとめ（最短ルート）

1. `set CUDA_TAG=cu121 & build_portable.bat` で ZIP を作る
2. 別Win機で動作確認
3. ZIP を **Hugging Face** に置く（2GB超のため）
4. GitHub Release から ZIP へリンク（＋ README に「DL→展開→起動」を明記）
5. 余裕があれば Inno Setup で `.exe` インストーラ化、cu128 版も用意
