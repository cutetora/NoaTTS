@echo off
REM ============================================================
REM  NoaTTS portable builder
REM  Bundles a relocatable Python together with the app and
REM  zips everything into dist\NoaTTS-portable\.
REM
REM  Two modes:
REM   - THIN (default): torch/CUDA NOT bundled; downloaded on first
REM                     launch. Small (~200MB) = fits GitHub Releases.
REM                     First launch auto-detects CUDA and installs.
REM   - FULL          : torch/CUDA bundled (~4-5GB). Works offline,
REM                     but the distributable is large.
REM
REM  Usage:   build_portable.bat                        (THIN / recommended)
REM           set FULL=1 ^& build_portable.bat           (FULL / bundle all)
REM           set CUDA_TAG=cu128 ^& set FULL=1 ^& build_portable.bat  (FULL CUDA pin)
REM
REM  Note: a plain "python -m venv" copy is NOT portable (stdlib/tkinter
REM        depend on the base Python). We use python-build-standalone.
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

if "%CUDA_TAG%"=="" set "CUDA_TAG=cu121"
set "DIST=dist\NoaTTS-portable"
set "PYDIR=%DIST%\python"
set "MODE=THIN"
if "%FULL%"=="1" set "MODE=FULL"

REM relocatable Python (tkinter included). Update this URL from
REM https://github.com/astral-sh/python-build-standalone/releases
set "PBS_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20250115/cpython-3.11.11+20250115-x86_64-pc-windows-msvc-install_only.tar.gz"

echo === NoaTTS portable build (MODE=%MODE% / CUDA=%CUDA_TAG%) ===
echo.

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

REM 1) fetch and extract relocatable Python
echo [python] downloading relocatable Python...
curl -L "%PBS_URL%" -o "%TEMP%\noatts_pbs.tar.gz"
if errorlevel 1 ( echo !!! Failed to download Python. Update PBS_URL to the latest release. & pause & exit /b 1 )
tar -xzf "%TEMP%\noatts_pbs.tar.gz" -C "%DIST%"
if errorlevel 1 ( echo !!! Extract failed (tar required: built into Windows 10+^). & pause & exit /b 1 )
set "PPY=%PYDIR%\python.exe"
if not exist "%PPY%" ( echo !!! Unexpected layout: %PPY% not found & pause & exit /b 1 )
"%PPY%" -m pip install --upgrade pip

REM 2) FULL only: bundle torch + deps (THIN downloads them on first launch)
if not "%MODE%"=="FULL" goto :skip_deps
echo [torch] installing %CUDA_TAG% ... (several GB)
"%PPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 ( echo !!! torch install failed. & pause & exit /b 1 )
echo [deps] installing requirements.txt ...
"%PPY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo !!! dependency install failed. & pause & exit /b 1 )
:skip_deps

REM 3) copy the app (THIN also needs requirements.txt / first_run_setup.bat)
echo [copy] copying app files...
for %%d in (assets batch conf daemon engine presets ui voice voices) do (
  if exist "%%d" xcopy /e /i /q /y "%%d" "%DIST%\%%d" >nul
)
for %%f in (app.py config.py detect_cuda.py download_models.py llm_provider.py noa_launcher.py noa_tts_daemon.py tray.py tts_api_window.py webview_window.py verify_portable.py first_run_setup.bat requirements.txt requirements-lite.txt README.md CHANGELOG.md NoaTTS.exe) do (
  if exist "%%f" copy /y "%%f" "%DIST%\" >nul
)

REM 3.5) FULL only: self-containment check (THIN skips it; torch not installed yet)
if not "%MODE%"=="FULL" goto :skip_verify
echo.
echo [verify] portable self-containment check...
"%PPY%" "%DIST%\verify_portable.py"
if errorlevel 1 echo [verify] !!! may not be self-contained (see NG above). Check before shipping.
echo.
:skip_verify

REM 4) generate launcher (runs first_run_setup if torch missing; aborts on setup failure)
set "LAUNCH=%DIST%\NoaTTS-Start.bat"
> "%LAUNCH%" echo @echo off
>>"%LAUNCH%" echo cd /d "%%~dp0"
>>"%LAUNCH%" echo "python\python.exe" -c "import torch" ^>nul 2^>^&1
>>"%LAUNCH%" echo if errorlevel 1 (
>>"%LAUNCH%" echo   call first_run_setup.bat
>>"%LAUNCH%" echo   if errorlevel 1 exit /b 1
>>"%LAUNCH%" echo ^)
>>"%LAUNCH%" echo start "" "python\pythonw.exe" tray.py --welcome

REM 5) zip it
echo [zip] compressing...
powershell -NoProfile -Command "Compress-Archive -Path '%DIST%\*' -DestinationPath 'dist\NoaTTS-portable-%MODE%.zip' -Force"

REM 6) optional: build NoaTTS-Setup.exe via Inno Setup (set INNO=1 to enable)
REM    Requires Inno Setup (ISCC.exe) installed: https://jrsoftware.org/isdl.php
if not "%INNO%"=="1" goto :skip_inno
echo [inno] building installer (NoaTTS-Setup.exe)...
set "ISCC="
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
  if exist "%%~p" set "ISCC=%%~p"
)
if not defined ISCC ( where ISCC >nul 2>&1 && set "ISCC=ISCC" )
if not defined ISCC (
  echo [inno] ISCC.exe not found. Install Inno Setup 6, then re-run with INNO=1.
) else (
  "%ISCC%" installer.iss
  if errorlevel 1 ( echo [inno] !!! installer build failed. ) else ( echo [inno] -^> Output\NoaTTS-Setup.exe )
)
:skip_inno

echo.
echo === Done (%MODE%) ===
echo   Folder : %DIST%
echo   ZIP    : dist\NoaTTS-portable-%MODE%.zip
if "%INNO%"=="1" echo   Installer: Output\NoaTTS-Setup.exe (if Inno Setup was found)
if "%MODE%"=="THIN" echo   THIN (~200MB). On first launch it downloads torch (auto-CUDA) + models.
if "%MODE%"=="FULL" echo   FULL (~4-5GB, torch bundled). First launch downloads models only.
echo   Users just extract and run NoaTTS-Start.bat (or run the installer exe).
echo.
pause
