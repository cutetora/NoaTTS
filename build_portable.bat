@echo off
REM ============================================================
REM  NoaTTS ポータブル版ビルダー
REM  再配置可能(relocatable)な Python を取り込み、アプリ一式と共に
REM  dist\NoaTTS-portable\ へまとめて ZIP 化する。
REM
REM  2モード:
REM   - THIN(既定): torch/CUDA は同梱せず「初回起動時にDL」。配布物が薄い(~200MB)
REM                 = GitHub Release にそのまま置ける。初回起動で CUDA 自動検出+導入。
REM   - FULL      : torch/CUDA も同梱(~4-5GB)。オフラインで即動くが配布物が大きい。
REM
REM  使い方:   build_portable.bat                       (THIN・薄い配布物/推奨)
REM            set FULL=1 ^& build_portable.bat          (FULL・全部同梱)
REM            set CUDA_TAG=cu128 ^& set FULL=1 ^& build_portable.bat  (FULL時のCUDA指定)
REM
REM  注意: 通常の "python -m venv" コピーは非ポータブル(stdlib/tkinter が元Python依存)。
REM        python-build-standalone の relocatable ビルドを使う。
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

if "%CUDA_TAG%"=="" set "CUDA_TAG=cu121"
set "DIST=dist\NoaTTS-portable"
set "PYDIR=%DIST%\python"
set "MODE=THIN"
if "%FULL%"=="1" set "MODE=FULL"

REM relocatable Python (tkinter 同梱)。最新版URLは
REM https://github.com/astral-sh/python-build-standalone/releases から更新可。
set "PBS_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20250115/cpython-3.11.11+20250115-x86_64-pc-windows-msvc-install_only.tar.gz"

echo === NoaTTS ポータブルビルド (MODE=%MODE% / CUDA=%CUDA_TAG%) ===
echo.

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

REM 1) relocatable Python を取得・展開
echo [python] relocatable Python を取得中...
curl -L "%PBS_URL%" -o "%TEMP%\noatts_pbs.tar.gz"
if errorlevel 1 ( echo !!! Python の取得に失敗。PBS_URL を最新に更新してください。 & pause & exit /b 1 )
tar -xzf "%TEMP%\noatts_pbs.tar.gz" -C "%DIST%"
if errorlevel 1 ( echo !!! 展開に失敗(tar が必要: Windows 10 以降は標準^)。 & pause & exit /b 1 )
set "PPY=%PYDIR%\python.exe"
if not exist "%PPY%" ( echo !!! 展開先が想定と異なります: %PPY% & pause & exit /b 1 )
"%PPY%" -m pip install --upgrade pip

REM 2) FULL のみ torch + 依存を同梱 (THIN は初回起動時にDL)
if not "%MODE%"=="FULL" goto :skip_deps
echo [torch] %CUDA_TAG% を導入中... (数GB)
"%PPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 ( echo !!! torch 導入に失敗。 & pause & exit /b 1 )
echo [deps] requirements.txt を導入中...
"%PPY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo !!! 依存導入に失敗。 & pause & exit /b 1 )
:skip_deps

REM 3) アプリ本体をコピー (THIN は requirements.txt / first_run_setup.bat も必須)
echo [copy] アプリ一式をコピー...
for %%d in (assets batch conf daemon engine presets ui voice voices) do (
  if exist "%%d" xcopy /e /i /q /y "%%d" "%DIST%\%%d" >nul
)
for %%f in (app.py config.py detect_cuda.py download_models.py llm_provider.py noa_launcher.py noa_tts_daemon.py tray.py tts_api_window.py webview_window.py verify_portable.py first_run_setup.bat requirements.txt README.md CHANGELOG.md) do (
  if exist "%%f" copy /y "%%f" "%DIST%\" >nul
)

REM 3.5) FULL のみ 自己完結チェック (THIN は torch 未導入のためスキップ)
if not "%MODE%"=="FULL" goto :skip_verify
echo.
echo [verify] ポータブル自己完結チェック...
"%PPY%" "%DIST%\verify_portable.py"
if errorlevel 1 echo [verify] !!! 自己完結していない可能性(上記NG)。配布前に要確認。
echo.
:skip_verify

REM 4) 起動 bat を生成 (torch 未導入なら first_run_setup を呼ぶ。失敗時は起動しない)
set "LAUNCH=%DIST%\NoaTTS-Start.bat"
> "%LAUNCH%" echo @echo off
>>"%LAUNCH%" echo cd /d "%%~dp0"
>>"%LAUNCH%" echo "python\python.exe" -c "import torch" ^>nul 2^>^&1
>>"%LAUNCH%" echo if errorlevel 1 (
>>"%LAUNCH%" echo   call first_run_setup.bat
>>"%LAUNCH%" echo   if errorlevel 1 exit /b 1
>>"%LAUNCH%" echo ^)
>>"%LAUNCH%" echo start "" "python\pythonw.exe" tray.py --welcome

REM 5) ZIP 化
echo [zip] 圧縮中...
powershell -NoProfile -Command "Compress-Archive -Path '%DIST%\*' -DestinationPath 'dist\NoaTTS-portable-%MODE%.zip' -Force"

echo.
echo === 完成 (%MODE%) ===
echo   フォルダ : %DIST%
echo   ZIP     : dist\NoaTTS-portable-%MODE%.zip
if "%MODE%"=="THIN" echo   薄い配布物(~200MB)。初回起動時に torch(CUDA自動検出)+モデルをDLします。
if "%MODE%"=="FULL" echo   torch 同梱(~4-5GB)。初回起動時はモデルのみDL。
echo   ユーザーは展開して「NoaTTS-Start.bat」を実行するだけ。
echo.
pause
