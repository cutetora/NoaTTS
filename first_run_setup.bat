@echo off
REM ============================================================
REM  NoaTTS first-run setup (for THIN portable build)
REM  Downloads heavy libraries (torch/CUDA, ~4GB) one time only.
REM  CUDA build is auto-selected to match your GPU.
REM  Called automatically by the launcher when torch is missing.
REM  Lives in scripts\ ; cd to the app root (parent) so python\ resolves.
REM
REM  NOTE: no multi-line ( ) blocks on purpose. Parenthesized if-blocks
REM  with blank echos were misparsed by cmd ("." was unexpected). We use
REM  single-line `if errorlevel 1 goto :fail` instead, which is robust.
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
REM if launched from scripts\, step up to the app root (where python\ is).
if not exist "python\python.exe" if exist "..\python\python.exe" cd ..
set "PPY=python\python.exe"

echo.
echo === NoaTTS first-run setup ===
echo  Downloading required libraries (~4GB). First run only, takes a few minutes.
echo.

REM --- 0) sanity: bundled python must exist ---
if not exist "%PPY%" goto :no_python

"%PPY%" -m pip install --upgrade pip

REM --- 1) detect GPU / CUDA (falls back to cu121, warns if no GPU) ---
set "CUDA_TAG=cu121"
for /f "delims=" %%i in ('"%PPY%" detect_cuda.py 2^>nul') do set "CUDA_TAG=%%i"
if "%CUDA_TAG%"=="" set "CUDA_TAG=cu121"
if /I "%CUDA_TAG%"=="none" goto :no_gpu
goto :install_torch

:no_gpu
echo.
echo [WARN] No NVIDIA GPU / driver detected by nvidia-smi.
echo        NoaTTS needs an NVIDIA GPU with an up-to-date driver.
echo        Continuing with a default CUDA build, but it may not run.
echo        Install the latest NVIDIA driver and re-run this if it fails.
echo.
set "CUDA_TAG=cu121"

:install_torch
REM --- 2) install torch (CUDA-matched) ---
echo [1/3] Installing torch (CUDA=%CUDA_TAG%) ...
"%PPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 goto :torch_fail

REM --- 3) install the rest of the dependencies ---
echo [2/3] Installing remaining dependencies ...
"%PPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :deps_fail

REM --- 4) pre-download the default TTS model (Irodori-TTS-500M) ---
REM     Done now so the FIRST launch is instant. Non-fatal: if it fails,
REM     the app re-fetches the model on first launch.
echo [3/3] Downloading the TTS model (Irodori-TTS-500M, a few GB) ...
"%PPY%" download_models.py
if errorlevel 1 echo [WARN] Model pre-download did not finish (will retry on first launch).

echo.
echo === Setup complete. Launching NoaTTS... ===
endlocal
exit /b 0

:no_python
echo [ERROR] Bundled Python not found: %PPY%
echo         The folder looks broken. Re-extract the ZIP and try again.
goto :fail

:torch_fail
echo.
echo [ERROR] Failed to install torch.
echo   Likely causes:
echo     - No internet connection / proxy blocking the download
echo     - download.pytorch.org is unreachable
echo   Fix your connection, then run NoaTTS again (setup re-runs automatically).
goto :fail

:deps_fail
echo.
echo [ERROR] Failed to install dependencies.
echo   Likely causes:
echo     - 'git' is not installed (some engines are pulled from GitHub)
echo       install Git for Windows: https://git-scm.com/download/win
echo     - Internet connection dropped mid-download
echo   Fix the above, then run NoaTTS again.
goto :fail

:fail
echo.
echo Setup did not finish. NoaTTS will not start yet.
echo Re-run NoaTTS after fixing the issue above.
echo.
pause
endlocal
exit /b 1
