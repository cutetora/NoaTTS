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

ユーザー手順は **「ZIP 展開 → `NoaTTS-Start.bat` ダブルクリック」** だけ。THIN は初回起動時に
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

## 「.exe インストーラ」にする（Windows 向けおまけ）

リポジトリ同梱の **[installer.iss](../installer.iss)** を **Inno Setup**（無料）でコンパイルすると、
ダブルクリックで入る `Output\NoaTTS-Setup.exe` が作れる。`dist\NoaTTS-portable\`（= `build_portable.bat`
の生成物）を丸ごと包む構成なので、**先に `build_portable.bat` を実行**してから作る。

**作り方A（自動・推奨）**: Inno Setup 6 を入れて `INNO=1` を付けるだけ。
```bat
set INNO=1 & build_portable.bat
```
→ ビルド完了後、`ISCC.exe` を自動で見つけて `Output\NoaTTS-Setup.exe` まで生成する。

**作り方B（手動）**: `installer.iss` を Inno Setup Compiler で開いて Compile。

### 設計の要点（なぜこの構成か）
- **インストール先は `{localappdata}\NoaTTS`**（管理者権限不要）。`Program Files` を避けるのは、
  **初回起動の `first_run_setup.bat` が `python\` 配下へ torch/依存を書き込む**ため
  （Program Files は読み取り専用で pip install が失敗する）。
- **THIN を維持**: インストーラを使っても初回起動で torch(自動CUDA)+モデルを DL する。
  `first_run_setup.bat` / `NoaTTS-Start.bat` は**消さない**（将来 Mac/Linux 版の土台にもなる）。
- ショートカットは `NoaTTS-Start.bat` を指す（アイコンは `assets\noa.ico`）。

> ⚠️ Inno Setup は **Windows 専用**。Mac/Linux はこの .exe ではなく、THIN 土台の
> ランチャー（`.bat`→`.sh`/`.command` 置換）や `pip` 配布で対応する想定。

---

## 既知の注意点

- **未署名のため SmartScreen 警告**が出る（「詳細情報 → 実行」で回避）。本格配布ではコード署名証明書があると親切（有料）。
- **アンチウイルスの誤検知**（pythonw.exe/同梱 exe）。VirusTotal で確認しておくと安心。
- 配布前に **別の（できればクリーンな）Windows 機**で「展開 → 起動 → 1 文読み上げ」まで必ず実機確認する（ビルドした機械では気づけない依存があるため）。
- ユーザーには **NVIDIA GPU + 最新ドライバ**が必要（GPU 無し/古いドライバでは起動しない）。

---

## まとめ（最短ルート・THIN推奨）

1. `build_portable.bat`（THIN既定）で **~200MB の ZIP** を作る
2. 別Win機で「展開 → `NoaTTS-Start.bat` → 初回DL → 1文読み上げ」まで動作確認
3. ZIP を **GitHub Release にそのまま添付**（200MB なので 2GB 上限内・外部ホスト不要）
4. README に「DL → 展開 → `NoaTTS-Start.bat` 実行（初回のみ自動DL）」を明記
5. 余裕があれば Inno Setup で `.exe` 化。完全オフライン版が要るなら `set FULL=1` で FULL ビルド（~4-5GB・配布は HF 経由）
