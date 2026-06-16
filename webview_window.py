"""NoaTTS の専用ウインドウを開く (pywebview)
tray.py からサブプロセスとして起動される。
URL は引数で受け取る。フラグ:
  --on-top    : 最前面表示で開く
  --maximized : 最大化して開く (画面いっぱい・タイトルバーは残る)
(初回ウェルカム起動で両方使う)
"""
import sys
from pathlib import Path
import webview


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    url = args[0] if args else "http://127.0.0.1:7860"
    on_top = "--on-top" in flags
    maximized = "--maximized" in flags
    title = "NoaTTS"
    base_kwargs = dict(
        title=title, url=url, width=1280, height=860,
        resizable=True, confirm_close=False,
    )
    # on_top は create_window 引数で。maximized は引数だけだと効かない環境が
    # あるため、start(func=) で表示直後に window.maximize() を確実に呼ぶ。
    try:
        win = webview.create_window(**base_kwargs, on_top=on_top)
    except TypeError:
        win = webview.create_window(**base_kwargs)

    def _after_start():
        if maximized:
            try:
                win.maximize()
            except Exception:
                pass

    _icon = Path(__file__).parent / "assets" / "noa.ico"
    try:
        webview.start(func=_after_start, icon=str(_icon))  # pywebview 5+ は icon 対応
    except TypeError:
        webview.start(_after_start)  # 古い pywebview (icon 非対応)


if __name__ == "__main__":
    main()
