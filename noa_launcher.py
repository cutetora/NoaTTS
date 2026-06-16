"""NoaTTS 起動ランチャー (exe化用)。

重い依存 (torch等) は一切 import せず、pythonw.exe で tray.py を起動するだけ。
これを PyInstaller でアイコン付き・コンソール無しの軽量 .exe にする。

exe にすることで、タスクバー/ショートカットに noa.ico が反映される
(bat だと黒窓のアイコンになってしまう問題の解決)。
"""
import os
import sys
import subprocess
from pathlib import Path


def _base_dir() -> Path:
    # PyInstaller でexe化されると __file__ が使えないので sys.executable 基準。
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def main():
    base = _base_dir()
    tray = base / "tray.py"

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # 黒窓を出さない

    # tray.py を起動する Python を探す。setup.bat が作る venv を最優先で使い、
    # 無ければ Windows の py ランチャーで 3.11、さらに無ければ PATH の pythonw / python。
    venv_pyw = base / "venv" / "Scripts" / "pythonw.exe"
    candidates = []
    if venv_pyw.exists():
        candidates.append([str(venv_pyw), str(tray)])
    candidates += [["pyw", "-3.11", str(tray)],
                   ["pythonw", str(tray)],
                   ["python", str(tray)]]
    for cmd in candidates:
        try:
            subprocess.Popen(cmd, cwd=str(base), creationflags=creationflags)
            return
        except FileNotFoundError:
            continue


if __name__ == "__main__":
    main()
