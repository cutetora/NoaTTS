@echo off
REM ============================================================
REM  NoaTTS first-run setup (for THIN portable build)
REM  Downloads heavy libraries (torch/CUDA, ~4GB) one time only.
REM  CUDA build is auto-selected to match your GPU.
REM  Called automatically by NoaTTS-Start.bat when torch is missing.
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PPY=python\python.exe"

echo.
echo === NoaTTS first-run setup ===
echo  Downloading required libraries (~4GB). First run only, takes a few minutes.
echo.

REM --- 0) sanity: bundled python must exist ---
if not exist "%PPY%" (
  echo [ERROR] Bundled Python not found: %PPY%
  echo         The folder looks broken. Re-extract the ZIP and try again.
  goto :fail
)

"%PPY%" -m pip install --upgrade pip

REM --- 1) detect GPU / CUDA (falls back to cu121, warns if no GPU) ---
set "CUDA_TAG=cu121"
for /f "delims=" %%i in ('"%PPY%" detect_cuda.py 2^>nul') do set "CUDA_TAG=%%i"
if "%CUDA_TAG%"=="" set "CUDA_TAG=cu121"
if /I "%CUDA_TAG%"=="none" (
  echo.
  echo [WARN] No NVIDIA GPU / driver detected by nvidia-smi.
  echo        NoaTTS needs an NVIDIA GPU with an up-to-date driver.
  echo        Continuing with a default CUDA build, but it may not run.
  echo        Install the latest NVIDIA driver and re-run this if it fails.
  echo.
  set "CUDA_TAG=cu121"
)

REM --- 2) install torch (CUDA-matched) ---
echo [1/2] Installing torch (CUDA=%CUDA_TAG%) ...
"%PPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to install torch.
  echo   Likely causes:
  echo     - No internet connection / proxy blocking the download
  echo     - download.pytorch.org is unreachable
  echo   Fix your connection, then just run NoaTTS-Start.bat again
  echo   (this setup re-runs automatically until it succeeds).
  goto :fail
)

REM --- 3) install the rest of the dependencies ---
echo [2/2] Installing remaining dependencies ...
"%PPY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to install dependencies.
  echo   Likely causes:
  echo     - 'git' is not installed (some engines are pulled from GitHub)
  echo       -^> install Git for Windows: https://git-scm.com/download/win
  echo     - Internet connection dropped mid-download
  echo   Fix the above, then run NoaTTS-Start.bat again.
  goto :fail
)

echo.
echo === Setup complete. Launching NoaTTS... ===
endlocal
exit /b 0

:fail
echo.
echo Setup did not finish. NoaTTS will not start yet.
echo Re-run NoaTTS-Start.bat after fixing the issue above.
echo.
pause
endlocal
exit /b 1
