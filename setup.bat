@echo off
REM ============================================================
REM  NoaTTS setup: winget installs Python/git -^> venv -^> deps
REM  Target: Windows + NVIDIA GPU (CUDA 12.8 series)
REM  For a different CUDA version, edit TORCH_INDEX below.
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

set "PY_VER=3.11"
set "VENV_DIR=venv"
REM PyTorch for CUDA 12.8. Other CUDA: https://pytorch.org/get-started/locally/
set "TORCH_INDEX=https://download.pytorch.org/whl/cu128"

echo.
echo === NoaTTS setup ===
echo.

REM --- 1. git check / install ----------------------------------
where git >nul 2>&1
if not errorlevel 1 goto :git_ok
echo [git] not found. Trying to install via winget ...
where winget >nul 2>&1
if not errorlevel 1 goto :git_winget
echo.
echo !!! Neither winget nor git is available.
echo     Please install Git for Windows manually, then run setup.bat again:
echo     https://git-scm.com/download/win
pause
exit /b 1
:git_winget
winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
echo [git] installed. Close this window and run setup.bat again so PATH refreshes.
pause
exit /b 0
:git_ok
echo [git] OK

REM --- 2. Python 3.11 check / install --------------------------
py -%PY_VER% -c "" >nul 2>&1
if not errorlevel 1 goto :py_ok
echo [Python %PY_VER%] not found. Trying to install via winget ...
where winget >nul 2>&1
if not errorlevel 1 goto :py_winget
echo.
echo !!! winget is not available. Please install Python %PY_VER% manually:
echo     https://www.python.org/downloads/release/python-3119/
pause
exit /b 1
:py_winget
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
echo [Python %PY_VER%] installed. Close this window and run setup.bat again so PATH refreshes.
pause
exit /b 0
:py_ok
echo [Python %PY_VER%] OK

REM --- 3. venv create ------------------------------------------
if exist "%VENV_DIR%\Scripts\python.exe" goto :venv_exists
echo [venv] Creating %VENV_DIR% ...
py -%PY_VER% -m venv "%VENV_DIR%"
if not errorlevel 1 goto :venv_ok
echo !!! Failed to create the venv.
pause
exit /b 1
:venv_exists
echo [venv] Using existing %VENV_DIR%
:venv_ok

set "VPY=%VENV_DIR%\Scripts\python.exe"

REM --- 4. pip upgrade ------------------------------------------
echo [pip] Upgrading ...
"%VPY%" -m pip install --upgrade pip

REM --- 5. PyTorch (CUDA) ---------------------------------------
echo.
echo [PyTorch] Installing CUDA build of torch / torchaudio
echo           index: %TORCH_INDEX%
echo           For a different CUDA version, edit TORCH_INDEX in setup.bat
"%VPY%" -m pip install torch torchaudio --index-url %TORCH_INDEX%
if not errorlevel 1 goto :torch_ok
echo !!! Failed to install PyTorch. Check your CUDA version / network.
pause
exit /b 1
:torch_ok

REM --- 6. requirements -----------------------------------------
echo.
echo [deps] Installing requirements.txt ...
"%VPY%" -m pip install -r requirements.txt
if not errorlevel 1 goto :deps_ok
echo !!! Failed to install dependencies.
pause
exit /b 1
:deps_ok

REM --- 7. TTS model pre-download -------------------------------
echo.
echo [model] Pre-downloading the TTS model (several GB / a few minutes) ...
"%VPY%" download_models.py
if not errorlevel 1 goto :model_ok
echo.
echo [model] Download failed (network, etc.)
echo         Setup itself is complete. The model will be fetched on first launch.
echo.
:model_ok

echo.
echo === SETUP COMPLETE ===
echo.
echo Setup finished successfully. Starting NoaTTS ...
echo   (Voice Studio opens in your browser and the noa daemon starts)
echo   You can start later from NoaTTS.exe or run_tray.bat too.
echo.
REM Launch tray directly with venv pythonw (avoid run_tray.bat exit propagation)
if exist "%VENV_DIR%\Scripts\pythonw.exe" goto :start_venv
start "" pythonw tray.py --welcome
goto :done
:start_venv
start "" "%VENV_DIR%\Scripts\pythonw.exe" tray.py --welcome

:done
echo.
echo You can close this window.
pause
