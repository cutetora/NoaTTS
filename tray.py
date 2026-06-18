"""NoaTTS タスクトレイ常駐ランチャー

機能:
  - Gradioサーバを背後で起動
  - タスクトレイにアニメーションアイコン表示
    - walk: 通常
    - run : TTS生成中
    - idle: モデル退避中 (静止)
  - 左クリック: 専用ウインドウを開く (pywebview)
  - 右クリック: メニュー
"""
import os
import sys
import time
import socket
import subprocess
import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
STATE_FILE = ASSETS / "_state.txt"
PYTHON_EXE = sys.executable
WEBVIEW_SCRIPT = ROOT / "webview_window.py"

URL = "http://127.0.0.1:7860"
PORT = 7860
TTS_API_URL = "http://127.0.0.1:7870"
TTS_API_PORT = 7870
DAEMON_SCRIPT = ROOT / "noa_tts_daemon.py"
TTS_API_WINDOW_SCRIPT = ROOT / "tts_api_window.py"
FRAME_MS_WALK = 250
FRAME_MS_RUN = 90
FRAME_MS_LOVE = 90


VOICES_DIR = ROOT / "voices"
ACTIVE_VOICE_FILE = ROOT / "_active_voice.txt"


def load_frames(folder: Path):
    paths = sorted(folder.glob("frame_*.png"))
    return [Image.open(p) for p in paths]


# ── デフォルトのアイコン素材 ──
frames_walk = load_frames(ASSETS / "walk")
frames_run = load_frames(ASSETS / "run")
frame_idle = Image.open(ASSETS / "idle.png")

DEFAULT_ICONSET = {
    "walk": frames_walk,
    "run": frames_run,
    "idle": [frame_idle],
}

# ボイス名 -> アイコンセット のキャッシュ ({} = 未解決, None = デフォルト使用)
_iconset_cache: dict = {}


def _resolve_voice_iconset(voice_name: str) -> dict:
    """トレイアイコンは全ボイス共通でデフォルト(この子)に統一する。

    以前は voices/<名>/ の個別アイコンを優先していた(案B)が、アプリ共通の
    マスコットに統一したいので、常にデフォルトを返す。
    (個別アイコン対応を復活させたい場合はこの早期 return を外す)
    """
    return DEFAULT_ICONSET

    # --- 以下、個別アイコン対応 (現在は無効) ---
    if not voice_name:
        return DEFAULT_ICONSET
    if voice_name in _iconset_cache:
        return _iconset_cache[voice_name]

    vdir = VOICES_DIR / voice_name
    iconset = dict(DEFAULT_ICONSET)  # まずデフォルトで埋める
    found_any = False

    if vdir.is_dir():
        # 1枚絵 icon.png (全状態の基本フォールバック)
        icon_png = vdir / "icon.png"
        static_img = None
        if icon_png.exists():
            try:
                static_img = Image.open(icon_png)
                found_any = True
            except Exception:
                static_img = None

        for st in ("walk", "run", "love", "idle"):
            st_dir = vdir / st
            frames = load_frames(st_dir) if st_dir.is_dir() else []
            if frames:
                iconset[st] = frames
                found_any = True
            elif static_img is not None:
                iconset[st] = [static_img]
            # else: デフォルトのまま

    result = iconset if found_any else DEFAULT_ICONSET
    _iconset_cache[voice_name] = result
    return result


def get_active_voice() -> str:
    try:
        return ACTIVE_VOICE_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


# ── 状態 ──
state = {
    "love_mode": False,   # 媚モード手動トグル
    "idle_mode": False,   # モデル退避中
    "gradio_proc": None,  # subprocess
    "running": True,
}


def port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def launch_gradio():
    """Gradio サーバをサブプロセスで起動 (コンソール非表示)"""
    if port_open(PORT):
        return None  # 既起動
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        [PYTHON_EXE, str(ROOT / "app.py")],
        cwd=str(ROOT),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def wait_gradio(timeout_sec: float = 120):
    """Gradio起動を待機"""
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        if port_open(PORT):
            return True
        time.sleep(0.5)
    return False


def open_window(icon=None, item=None):
    """専用ウインドウを開く (pywebview をサブプロセスで起動)"""
    if not port_open(PORT):
        # Gradio起動中、待つ
        threading.Thread(target=_open_when_ready, daemon=True).start()
        return
    _spawn_window()


def _open_when_ready():
    if wait_gradio():
        _spawn_window()


def _spawn_window(extra_flags=None):
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    cmd = [PYTHON_EXE, str(WEBVIEW_SCRIPT), URL]
    if extra_flags:
        cmd += list(extra_flags)
    subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        creationflags=creationflags,
    )


def open_in_browser(icon=None, item=None):
    """既定ブラウザで Gradio 画面を開く。未起動なら起動を待ってから開く。"""
    if port_open(PORT):
        webbrowser.open(URL)
        return

    def _wait_then_open():
        if wait_gradio():
            webbrowser.open(URL)
    threading.Thread(target=_wait_then_open, daemon=True).start()


def open_tts_settings(icon=None, item=None):
    """読み上げソフトの設定ウィンドウを開く (pywebviewネイティブウィンドウ)。
    ボイス選択・話速・自動読み上げトグル・daemon起動停止・テストを一括操作。
    daemonの起動/停止は tts_api_window.py 側 (Apiクラス) が面倒を見る。"""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        [PYTHON_EXE, str(TTS_API_WINDOW_SCRIPT)],
        cwd=str(ROOT),
        creationflags=creationflags,
    )
    state["tts_window_proc"] = proc  # アプリ終了時に一緒に閉じるためハンドルを保持


def open_tts_api_browser(icon=None, item=None):
    """フォールバック: ブラウザで読み上げAPI画面を開く。"""
    webbrowser.open(TTS_API_URL)


def list_voices() -> list:
    """voices/ フォルダからボイス名一覧を取得 (daemon不要・直接走査)。"""
    try:
        return sorted([p.name for p in (ROOT / "voices").iterdir() if p.is_dir()])
    except Exception:
        return []


def switch_voice(name: str):
    """daemon にボイス切替を依頼。daemon未起動でも _active_voice.txt は更新し、
    アイコンだけは即切替える (次回 daemon 起動時に効く)。"""
    # アイコン即時反映のためファイルを先に更新
    try:
        ACTIVE_VOICE_FILE.write_text(name, encoding="utf-8")
    except Exception:
        pass
    # daemon が起きていれば実際のボイスも切替
    if port_open(TTS_API_PORT):
        try:
            import urllib.request
            req = urllib.request.Request(
                TTS_API_URL + "/voice", data=name.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass


def make_voice_handler(name: str):
    return lambda icon=None, item=None: switch_voice(name)


def build_voice_submenu():
    """voices/ を走査してボイス選択サブメニューを動的生成。
    現在アクティブなボイスにはチェックを付ける。"""
    items = []
    voices = list_voices()
    if not voices:
        return pystray.Menu(
            pystray.MenuItem("(ボイスがありません)", lambda i, _: None, enabled=False))
    for name in voices:
        items.append(pystray.MenuItem(
            name,
            make_voice_handler(name),
            checked=lambda item, n=name: get_active_voice() == n,
            radio=True,
        ))
    return pystray.Menu(*items)


def toggle_love_mode(icon=None, item=None):
    state["love_mode"] = not state["love_mode"]


def toggle_idle(icon=None, item=None):
    """モデル退避を切替 (再ロードはアプリ側で自動)"""
    import urllib.request
    state["idle_mode"] = not state["idle_mode"]
    if state["idle_mode"]:
        # Gradio API経由でアンロードを呼ぶ手段がないため、
        # state file 経由でアプリへの指示を残す (簡易実装)
        try:
            (ASSETS / "_unload_request.txt").write_text("1", encoding="utf-8")
        except Exception:
            pass


def open_output_folder(icon=None, item=None):
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    os.startfile(str(out))  # type: ignore[attr-defined]


def _stop_daemon():
    """読み上げ daemon(:7870) を停止する。HTTP /quit → 駄目なら PID kill。
    アプリ終了時に呼び、サーバも一緒に止めて全部クリアにする。"""
    if not port_open(TTS_API_PORT):
        return
    try:
        import urllib.request
        req = urllib.request.Request(TTS_API_URL + "/quit", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass
    # ポートが閉じるまで少し待つ
    t0 = time.time()
    while port_open(TTS_API_PORT) and time.time() - t0 < 5:
        time.sleep(0.3)
    # まだ生きていれば PID ファイルから kill
    if port_open(TTS_API_PORT):
        try:
            import os
            pid = int((ROOT / ".tts_daemon_pid").read_text(encoding="utf-8").strip())
            os.kill(pid, 15)
        except Exception:
            pass


def quit_app(icon=None, item=None):
    state["running"] = False
    # 読み上げ daemon(:7870) も停止して全部クリアにする
    _stop_daemon()
    # Gradioサブプロセス終了
    proc = state.get("gradio_proc")
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
    # 読み上げ設定ウィンドウ(tts_api_window)も開いていれば閉じる
    win = state.get("tts_window_proc")
    if win is not None:
        try:
            win.terminate()
        except Exception:
            pass
    if icon is not None:
        icon.stop()


# TTSデーモン(:7870)の生存チェックのキャッシュ (毎フレーム叩くと重い)
_daemon_check = {"alive": False, "ts": 0.0}
_DAEMON_CHECK_INTERVAL = 2.0  # 秒


def _daemon_alive() -> bool:
    """TTSデーモン(:7870)が稼働中か。2秒キャッシュ。"""
    now = time.time()
    if now - _daemon_check["ts"] >= _DAEMON_CHECK_INTERVAL:
        _daemon_check["alive"] = port_open(TTS_API_PORT)
        _daemon_check["ts"] = now
    return _daemon_check["alive"]


def get_current_state() -> str:
    """現在のトレイ表示モードを返す。

    最優先: TTSデーモンが停止していれば idle (停止中=グレー+zZ)。
    サーバーが落ちていることを一目で分かるようにするため、これを先頭で判定する。
    """
    if not _daemon_alive():
        return "idle"
    if state["love_mode"]:
        return "love"
    if state["idle_mode"]:
        return "idle"
    try:
        s = STATE_FILE.read_text(encoding="utf-8").strip()
        if s in ("run", "walk", "love", "idle"):
            return s
    except Exception:
        pass
    return "walk"


_FRAME_MS = {"walk": FRAME_MS_WALK, "run": FRAME_MS_RUN, "love": FRAME_MS_LOVE}


def animate(icon: pystray.Icon):
    """フレームを差し替え続ける。アクティブボイスのアイコンセットを使う (案B)。"""
    idx = {"walk": 0, "run": 0, "love": 0, "idle": 0}
    last_voice = None
    while state["running"]:
        voice = get_active_voice()
        if voice != last_voice:
            # ボイスが変わったらインデックスをリセット (フレーム数が違うため)
            idx = {"walk": 0, "run": 0, "love": 0, "idle": 0}
            last_voice = voice
        iconset = _resolve_voice_iconset(voice)

        mode = get_current_state()
        frames = iconset.get(mode) or DEFAULT_ICONSET.get(mode) or [frame_idle]
        icon.icon = frames[idx[mode] % len(frames)]
        idx[mode] += 1

        if mode == "idle" or len(frames) <= 1:
            time.sleep(0.5)
        else:
            time.sleep(_FRAME_MS.get(mode, FRAME_MS_WALK) / 1000)


def build_menu():
    return pystray.Menu(
        pystray.MenuItem("NoaTTS", lambda i, _: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("⚙️ 読み上げ設定", open_tts_settings),
        pystray.MenuItem("🌐 Voice Studio を開く", open_in_browser, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🎤 ボイス選択", build_voice_submenu()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda item: "▶️ モデル再ロード" if state["idle_mode"] else "💤 モデル退避",
            toggle_idle,
        ),
        pystray.MenuItem("📁 出力フォルダを開く", open_output_folder),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ アプリを閉じる", quit_app),
    )


def _start_daemon_if_needed():
    """読み上げ daemon (noa) が未起動なら起動する。
    noa_tts_daemon.py は引数なしだと既定ボイス noa で立つ。"""
    if port_open(TTS_API_PORT):
        return  # 既に起動済み
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        subprocess.Popen(
            [PYTHON_EXE, str(DAEMON_SCRIPT)], cwd=str(ROOT),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _open_browser_maximized():
    """既定ブラウザで Voice Studio を開き、その窓を最大化+前面化する
    (ベストエフォート。Windows のみ・pywin32 がある場合)。
    ブラウザのタブ/ウィンドウタイトルに含まれる "NoaTTS" (Gradio の title) で
    対象窓を特定する。失敗しても普通にタブが開いた状態にはなる。"""
    try:
        webbrowser.open(URL)
    except Exception:
        return
    if os.name != "nt":
        return

    def _bring_front():
        try:
            import win32gui
            import win32con
        except Exception:
            return  # pywin32 が無ければ何もしない (ベストエフォート)
        # ブラウザがタブを開いてタイトルへ反映されるまで少し待つ
        for _ in range(20):  # 最大 ~10 秒
            time.sleep(0.5)
            target = []

            def _enum(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if title and "NoaTTS" in title:
                    target.append(hwnd)

            try:
                win32gui.EnumWindows(_enum, None)
            except Exception:
                return
            if target:
                hwnd = target[0]
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                return

    threading.Thread(target=_bring_front, daemon=True).start()


def main():
    # --welcome: setup 直後の初回起動。Voice Studio をブラウザで開き、
    # 読み上げ daemon(noa) も自動起動して「叩くだけで使える」状態にする。
    # 通常起動(引数なし)では静かにトレイ常駐するだけ。
    welcome = "--welcome" in sys.argv

    # 初期状態ファイル
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text("walk", encoding="utf-8")
    except Exception:
        pass

    # Gradio起動
    state["gradio_proc"] = launch_gradio()
    # 読み上げ daemon(noa) も起動する(「閉じる=全停止」と対称に、開く=全起動)。
    # 既に起動済みなら何もしない(冪等)。バックグラウンドでモデルをロードする。
    _start_daemon_if_needed()

    # トレイアイコン
    icon = pystray.Icon(
        "qwentts",
        frames_walk[0],
        title="NoaTTS — 起動中…",
        menu=build_menu(),
    )

    # アニメスレッド
    threading.Thread(target=animate, args=(icon,), daemon=True).start()

    # Gradio起動完了したらタイトル更新。--welcome 時は専用ウインドウ表示+daemon起動も。
    def update_title():
        if wait_gradio():
            try:
                icon.title = "NoaTTS — 稼働中"
            except Exception:
                pass
            if welcome:
                # 読み上げ daemon(noa) を先に立て、Voice Studio を
                # 既定ブラウザで開いて最大化+前面化する (アドレスバーを見せるため
                # pywebview 窓ではなくブラウザを使う)
                _start_daemon_if_needed()
                try:
                    _open_browser_maximized()
                except Exception:
                    pass
    threading.Thread(target=update_title, daemon=True).start()

    icon.run()


if __name__ == "__main__":
    main()
