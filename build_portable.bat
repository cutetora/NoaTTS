@echo off
REM ============================================================
REM  NoaTTS ポータブル版ビルダー
REM  再配置可能(relocatable)な Python を取り込み、torch+deps を入れ、
REM  アプリ一式と共に dist\NoaTTS-portable\ へまとめて ZIP 化する。
REM  生成物は「展開して NoaTTS起動.bat を実行」で動く(Python/CUDA 導入不要)。
REM  ※ユーザー側は最新の NVIDIA ドライバだけ必要(CUDA ランタイムは torch 同梱)。
REM
REM  使い方:   build_portable.bat                 (既定 cu121=広い互換性)
REM            set CUDA_TAG=cu128 ^& build_portable.bat   (新しめGPU向け)
REM
REM  注意: 通常の "python -m venv" のコピーはポータブルにならない
REM        (標準ライブラリ/tkinter が元の Python に依存するため)。
REM        ここでは python-build-standalone の relocatable ビルドを使う。
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

if "%CUDA_TAG%"=="" set "CUDA_TAG=cu121"
set "DIST=dist\NoaTTS-portable"
set "PYDIR=%DIST%\python"

REM --- relocatable Python (tkinter 同梱) ---
REM  最新版URLは https://github.com/astral-sh/python-build-standalone/releases から
REM  cpython-3.11.x+YYYYMMDD-x86_64-pc-windows-msvc-install_only.tar.gz を選んで更新する。
set "PBS_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20250115/cpython-3.11.11+20250115-x86_64-pc-windows-msvc-install_only.tar.gz"

echo === NoaTTS ポータブルビルド (CUDA=%CUDA_TAG%) ===
echo.

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

REM 1) relocatable Python を取得・展開
echo [python] relocatable Python を取得中...
curl -L "%PBS_URL%" -o "%TEMP%\noatts_pbs.tar.gz"
if errorlevel 1 ( echo !!! Python の取得に失敗。PBS_URL を最新に更新してください。& pause & exit /b 1 )
tar -xzf "%TEMP%\noatts_pbs.tar.gz" -C "%DIST%"
if errorlevel 1 ( echo !!! 展開に失敗(tar が必要: Windows 10 以降は標準)。& pause & exit /b 1 )
set "PPY=%PYDIR%\python.exe"
if not exist "%PPY%" ( echo !!! 展開先が想定と異なります: %PPY% ^(install_only 版か確認^) & pause & exit /b 1 )

REM 2) torch + 依存を同梱 Python に導入
echo [pip] アップグレード...
"%PPY%" -m pip install --upgrade pip
echo [torch] %CUDA_TAG% を導入中... (数GB)
"%PPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 ( echo !!! torch 導入に失敗。& pause & exit /b 1 )
echo [deps] requirements.txt を導入中...
"%PPY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo !!! 依存導入に失敗。& pause & exit /b 1 )

REM 3) アプリ本体をコピー (実行時生成物 output/tmp_say は除外)
echo [copy] アプリ一式をコピー...
for %%d in (assets batch conf daemon engine presets ui voice voices) do (
  if exist "%%d" xcopy /e /i /q /y "%%d" "%DIST%\%%d" >nul
)
for %%f in (app.py config.py detect_cuda.py download_models.py llm_provider.py noa_launcher.py noa_tts_daemon.py tray.py tts_api_window.py webview_window.py verify_portable.py README.md CHANGELOG.md) do (
  if exist "%%f" copy /y "%%f" "%DIST%\" >nul
)

REM 3.5) 自己完結チェック(同梱 Python で実行: システムPythonに頼ってないか確認)
echo.
echo [verify] ポータブル自己完結チェック...
"%PYDIR%\python.exe" "%DIST%\verify_portable.py"
if errorlevel 1 echo [verify] !!! 自己完結していない可能性があります(上記NG)。配布前に要確認。
echo.

REM 4) 同梱 Python を使う起動 bat を生成
set "LAUNCH=%DIST%\NoaTTS起動.bat"
> "%LAUNCH%" echo @echo off
>>"%LAUNCH%" echo cd /d "%%~dp0"
>>"%LAUNCH%" echo REM 同梱 Python で起動(初回はモデルを自動DL/数GB)
>>"%LAUNCH%" echo start "" "python\pythonw.exe" tray.py --welcome

REM 5) ZIP 化
echo [zip] 圧縮中...
powershell -NoProfile -Command "Compress-Archive -Path '%DIST%\*' -DestinationPath 'dist\NoaTTS-portable-%CUDA_TAG%.zip' -Force"

echo.
echo === 完成 ===
echo   フォルダ : %DIST%
echo   ZIP     : dist\NoaTTS-portable-%CUDA_TAG%.zip
echo   配布後、ユーザーは展開して「NoaTTS起動.bat」を実行するだけ。
echo   (初回起動時に TTS モデルを自動ダウンロードします)
echo.
pause
