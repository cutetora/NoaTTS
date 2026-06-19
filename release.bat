@echo off
REM ============================================================
REM  NoaTTS release helper
REM  Builds ZIP (+ optional installer exe), then asks you to verify
REM  on your real GPU machine. After you confirm, it creates the
REM  GitHub Release and uploads the artifacts (notes from CHANGELOG).
REM
REM  Usage:
REM    release.bat v1.2.0                 (ZIP only)
REM    set INNO=1 ^& release.bat v1.2.0    (ZIP + NoaTTS-Setup.exe)
REM
REM  Requires: gh CLI (logged in), and for INNO=1, Inno Setup 6.
REM ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "TAG=%~1"
if "%TAG%"=="" (
  echo Usage: release.bat ^<tag^>   e.g.  release.bat v1.2.0
  echo        set INNO=1 ^& release.bat v1.2.0   (also build installer exe)
  exit /b 1
)

set "ZIP=dist\NoaTTS-portable-THIN.zip"
set "EXE=Output\NoaTTS-Setup.exe"

echo ============================================================
echo  Release %TAG%  (INNO=%INNO%)
echo ============================================================

REM 1) build fresh artifacts
echo [1/4] building artifacts (build_portable.bat)...
call build_portable.bat
if errorlevel 1 ( echo !!! build failed. & exit /b 1 )
if not exist "%ZIP%" ( echo !!! ZIP not produced: %ZIP% & exit /b 1 )

REM 2) show what we are about to ship + ask the human to verify
echo.
echo [2/4] artifacts ready:
for %%F in ("%ZIP%") do echo    ZIP : %%~fF  (%%~zF bytes^)
if "%INNO%"=="1" if exist "%EXE%" ( for %%F in ("%EXE%") do echo    EXE : %%~fF  (%%~zF bytes^) )
echo.
echo  >>> NOW: test on your real GPU machine before publishing. <<<
echo      Extract the ZIP somewhere clean, run NoaTTS-Start.bat,
echo      let first-run download finish, and confirm it SPEAKS.
echo.
set /p OK="Publish release %TAG% to GitHub now? (y/N): "
if /I not "%OK%"=="y" ( echo Aborted. Artifacts are kept; nothing published. & exit /b 0 )

REM 3) tag (create if missing) and push it
echo [3/4] tagging %TAG%...
git rev-parse "%TAG%" >nul 2>&1
if errorlevel 1 (
  git tag "%TAG%"
  git push origin "%TAG%"
) else (
  echo    tag %TAG% already exists; reusing it.
)

REM 4) create the GitHub Release and upload artifacts
echo [4/4] creating GitHub Release and uploading artifacts...
set "ASSETS=%ZIP%"
if "%INNO%"=="1" if exist "%EXE%" set "ASSETS=%ZIP% %EXE%"
gh release view "%TAG%" >nul 2>&1
if errorlevel 1 (
  gh release create "%TAG%" %ASSETS% --title "NoaTTS %TAG%" --notes-file CHANGELOG.md
) else (
  echo    release %TAG% exists; uploading/overwriting assets...
  gh release upload "%TAG%" %ASSETS% --clobber
)
if errorlevel 1 ( echo !!! gh release failed. & exit /b 1 )

echo.
echo === Released %TAG% ===
gh release view "%TAG%" --web
exit /b 0
