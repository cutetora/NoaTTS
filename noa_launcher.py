"""NoaTTS 起動ランチャー (exe化用)。

重い依存 (torch等) は一切 import せず、pythonw.exe で tray.py を起動するだけ。
これを PyInstaller でアイコン付き・コンソール無しの軽量 .exe にする。

exe にすることで、タスクバー/ショートカットに noa.ico が反映される
(bat だと黒窓のアイコンになってしまう問題の解決)。

THIN ポータブル配布 (build_portable.bat) では、隣に同梱された python\ を使う。
torch が未導入なら first_run_setup.bat を先に走らせてから tray.py を起動する
(= NoaTTS-Start.bat と同じ初回DLの面倒を exe 単独でも見る)。
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


def _bundled_python(base: Path):
    """THIN 配布で同梱された python\ を返す (無ければ None)。"""
    p = base / "python"
    pyw = p / "pythonw.exe"
    py = p / "python.exe"
    if pyw.exists() and py.exists():
        return pyw, py
    return None


def _deps_ready(py_exe: Path) -> bool:
    """依存が揃っているか。torch だけでなく pystray も見る——torch は入った
    のに requirements が途中で止まった『中途半端』状態を初回セットアップで
    やり直させるため (pystray が無いと tray.py が即落ちする)。"""
    try:
        r = subprocess.run([str(py_exe), "-c", "import torch, pystray"],
                           cwd=str(py_exe.parent.parent),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _run_first_setup(base: Path) -> bool:
    """first_run_setup.bat を (コンソール表示で) 実行。成功で True。
    入口を分かりやすくするため bat は scripts\ に置く。旧構成(直下)も一応見る。"""
    setup = base / "scripts" / "first_run_setup.bat"
    if not setup.exists():
        setup = base / "first_run_setup.bat"  # 後方互換
    if not setup.exists():
        return True  # THIN でなければ初回DLは不要 (開発環境など)
    try:
        # 進捗が見えるよう、ここはコンソールを出して実行する。
        # bat 側は親(アプリルート)へ cd するので cwd は base のままでよい。
        r = subprocess.run(["cmd", "/c", str(setup)], cwd=str(base))
        return r.returncode == 0
    except Exception:
        return False


def main():
    base = _base_dir()
    tray = base / "tray.py"

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # 黒窓を出さない

    # --- THIN 配布: 同梱 python\ があればそれを使う ---
    bundled = _bundled_python(base)
    if bundled is not None:
        pyw, py = bundled
        # 依存が未導入/中途半端なら初回セットアップ (失敗したら起動しない)。
        if not _deps_ready(py):
            if not _run_first_setup(base):
                return
        subprocess.Popen([str(pyw), str(tray)], cwd=str(base),
                         creationflags=creationflags)
        return

    # --- 開発環境など: venv / py ランチャー / PATH の python を順に試す ---
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
