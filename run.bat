@echo off
cd /d "%~dp0"
REM venv があればそれを使う。無ければ py -3.11 / python にフォールバック。
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" app.py
) else (
  py -3.11 -c "" 2>nul && (py -3.11 app.py) || (python app.py)
)
pause
