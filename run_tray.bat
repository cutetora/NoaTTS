@echo off
cd /d "%~dp0"
REM venv があればそれを使う。無ければ py -3.11 / pythonw にフォールバック。
REM 引数 (%*) はそのまま tray.py へ渡す (例: --welcome で初回ウェルカム起動)。
if exist "venv\Scripts\pythonw.exe" (
  start "" "venv\Scripts\pythonw.exe" tray.py %*
) else (
  py -3.11 -c "" 2>nul && (start "" pyw -3.11 tray.py %*) || (start "" pythonw tray.py %*)
)
REM call 元(setup.bat 等)を巻き込まないよう exit /b を使う。
exit /b
