@echo off
REM ============================================================
REM  NoaTTS 初回セットアップ (薄い配布物用)
REM  必要なライブラリ(torch/CUDA 等・約4GB)を一度だけ DL・導入する。
REM  CUDA は GPU に合わせて自動選択。NoaTTS起動.bat から自動で呼ばれる。
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PPY=python\python.exe"

echo.
echo === NoaTTS 初回セットアップ ===
echo  必要なライブラリ(約4GB)をダウンロードします。初回のみ・数分かかります。
echo.

"%PPY%" -m pip install --upgrade pip

REM GPU の CUDA を自動検出して合う torch を選ぶ (検出不可は cu121 にフォールバック)
set "CUDA_TAG=cu121"
for /f "delims=" %%i in ('"%PPY%" detect_cuda.py 2^>nul') do set "CUDA_TAG=%%i"
if "%CUDA_TAG%"=="" set "CUDA_TAG=cu121"
if /I "%CUDA_TAG%"=="none" set "CUDA_TAG=cu121"
echo [torch] CUDA=%CUDA_TAG% を導入中...
"%PPY%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/%CUDA_TAG%
if errorlevel 1 ( echo !!! torch の導入に失敗(ネット/ドライバを確認^)。 & pause & exit /b 1 )

echo [deps] 依存ライブラリを導入中...
"%PPY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo !!! 依存の導入に失敗。 & pause & exit /b 1 )

echo.
echo === セットアップ完了。NoaTTS を起動します ===
endlocal
exit /b 0
