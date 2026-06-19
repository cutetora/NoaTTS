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

## 作り方（2モード）

| モード | 配布サイズ | 中身 | 初回起動 |
|---|---|---|---|
| **THIN（既定・推奨）** | **~200MB** | Python + アプリのみ | torch(CUDA自動検出)+モデルをDL |
| FULL | ~4-5GB | torch/CUDA も同梱 | モデルのみDL |

```bat
REM THIN(薄い配布物・推奨) — torch は初回起動時に自動DL
build_portable.bat

REM FULL(全部同梱) — オフラインで即動く
set FULL=1 & build_portable.bat

REM FULL時に CUDA を指定したい場合
set CUDA_TAG=cu128 & set FULL=1 & build_portable.bat
```

生成物: `dist\NoaTTS-portable\`（展開済み）と `dist\NoaTTS-portable-<MODE>.zip`（配布用）。

ユーザー手順は **「ZIP 展開 → `NoaTTS起動.bat` ダブルクリック」** だけ。THIN は初回起動時に
必要なライブラリ(torch 等)を **GPU に合わせて自動DL/導入**し、続けて TTS モデルを取得する。

---

## CUDA タグの選び方（配布用）

| タグ | 対象 | 備考 |
|---|---|---|
| **cu121** | 広い互換性（既定） | 多くのドライバで動く。配布の基本はこれ |
| cu128 | RTX 50 系など新しめ | 最新ドライバ必須 |

理想は **cu121 と cu128 の 2 種類**を用意し、ユーザーに選ばせる。1 種類だけなら **cu121** が無難。

---

## 配布のハードル

- **THIN(~200MB)なら GitHub Releases にそのまま置ける**（1ファイル2GB上限内）。外部ホスト不要＝これが推奨。
- **FULL(~4-5GB)** は GitHub Releases の **2GB/ファイル上限**を超えるので、**Hugging Face** に置いて Release からリンクするか、ZIP を分割（`7z` のボリューム分割）する。
- THIN/FULL とも **モデル(Irodori/DACVAE, 数GB)は初回起動時に自動DL**。完全オフライン配布にしたい場合のみ FULL + モデル同梱（ビルド時に `HF_HOME` を bundle 内へ向けて `download_models.py` を実行し、そのキャッシュを同梱）。

> なぜ torch を初回DLにできるのか: torch+CUDA(~4GB)は **PyTorch の CDN から pip で取得**できるため、
> 配布物に同梱しなくても初回起動時に入れられる（モデルと同じ「初回DL」方式）。THIN はこれを使って薄くしている。

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
