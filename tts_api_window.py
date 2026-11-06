"""NoaTTS 読み上げ設定ウィンドウ (pywebview)

トレイ右クリック「読み上げ設定」からサブプロセスとして起動される。
読み上げソフト(noa_tts_daemon.py)の設定を一ヶ所で操作する独立ウィンドウ:
  - 使用ボイスの選択 + 話速(speed)調整
  - 自動読み上げ ON/OFF トグル (tts_auto.flag)
  - daemon の 起動 / 停止 / 再起動 と 稼働状態表示
  - テスト読み上げ + 外部APIの使い方

daemon 停止中でもウィンドウは開く。daemonの起動/停止は Python 側 (Api クラス) が
subprocess で行い、ボイス/話速/トグル/テストは daemon の HTTP(:7870) を叩く。
"""
import os
import sys
import json
import socket
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

import webview

from voice import voice_trash as _vt

ROOT = Path(__file__).parent
PYTHON_EXE = sys.executable
DAEMON_SCRIPT = ROOT / "noa_tts_daemon.py"
DAEMON_PID_PATH = ROOT / ".tts_daemon_pid"

API_HOST = "127.0.0.1"
API_PORT = 7870
API_BASE = f"http://{API_HOST}:{API_PORT}"
VOICES_DIR = ROOT / "voices"


def port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect((API_HOST, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def _http(path: str, method: str = "GET", body: str = None,
          ctype: str = "text/plain; charset=utf-8", timeout: float = 8) -> dict:
    """daemon の HTTP を叩いて JSON dict を返す。失敗時は {'ok': False, ...}。
    モデル切替など時間のかかる呼び出しは timeout を延ばす。"""
    try:
        data = body.encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            API_BASE + path, data=data,
            headers={"Content-Type": ctype}, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e), "_offline": True}


class Api:
    """pywebview の JS から呼ばれる Python 側 API (daemon の起動/停止を担う)。"""

    def status(self):
        """稼働状態 + 現在設定をまとめて返す。"""
        if not port_open(API_PORT):
            return {"running": False}
        h = _http("/health")
        if not h.get("ok"):
            return {"running": False}
        return {"running": True, "voice": h.get("voice"),
                "speed": h.get("speed", 1.0), "auto": h.get("auto", False),
                "speaking": h.get("speaking", False), "model": h.get("model")}

    def voices(self):
        if not port_open(API_PORT):
            # daemon停止中でも voices/ を直接走査して一覧は出す
            try:
                names = sorted([p.name for p in (ROOT / "voices").iterdir() if p.is_dir()])
                return {"ok": True, "voices": names, "active": None}
            except Exception:
                return {"ok": False, "voices": []}
        return _http("/voices")

    def vram(self):
        """VRAM使用状況 (全体/読み上げ/Voice Studio/空き、MB)。
        daemon から 全体/noa を取得し、Voice Studio(app.py) の分は state ファイルから読む。"""
        if not port_open(API_PORT):
            return {"ok": False}
        info = _http("/vram")
        # Voice Studio(app.py) のVRAM: app.py が 3秒ごとに書き出すファイル。
        # 10秒以上更新が無ければ Voice Studio 未起動とみなして 0。
        try:
            f = ROOT / "assets" / "_studio_vram.txt"
            if f.exists() and (time.time() - f.stat().st_mtime) < 10:
                info["studio"] = int(f.read_text(encoding="utf-8").strip() or "0")
            else:
                info["studio"] = 0
        except Exception:
            info["studio"] = 0
        return info

    def models(self):
        """irodori の使用可能モデル一覧 (DL状態付き)。daemon 不要。"""
        try:
            import engine.models_catalog as mcat
            entries = mcat.list_for_ui("irodori", include_hf=False)
            return {"ok": True, "models": [
                {"repo_id": e.repo_id, "label": e.label, "role": e.role,
                 "downloaded": mcat.is_downloaded(e.repo_id)} for e in entries]}
        except Exception as e:
            return {"ok": False, "error": str(e), "models": []}

    def set_model(self, repo_id):
        """daemon の使用モデルを切り替える。GPU再ロードで数十秒かかるため
        タイムアウトを長く取る。"""
        if not port_open(API_PORT):
            return {"ok": False, "error": "daemon 未起動"}
        return _http("/model", "POST", str(repo_id),
                     ctype="text/plain; charset=utf-8", timeout=180)

    def set_lightweight(self, enabled):
        """軽量モード(int4 軽量モデル ~1.5GB)の ON/OFF。settings.json に永続化し、
        稼働中の daemon の使用モデルも即切り替える。OFF で通常 bf16 (500M v3) に戻す。"""
        try:
            from config import AppConfig
            from engine.irodori_engine import IrodoriEngine
            # int4 は専用ランタイムが必須。未導入で ON にすると読み込みで落ちるため弾く。
            if enabled:
                import importlib.util
                if importlib.util.find_spec("irodori_tts_lite") is None:
                    return {"ok": False, "lightweight": False,
                            "error": "軽量モードには int4 ランタイムが必要です。"
                                     "未導入のため ON にできません。"
                                     "`python\\python.exe -m pip install -r requirements-lite.txt` で導入してください。"}
            c = AppConfig.load()
            repo = IrodoriEngine.LIGHT_CHECKPOINT if enabled else IrodoriEngine.DEFAULT_CHECKPOINT
            c.lightweight_mode = bool(enabled)
            c.irodori_checkpoint = repo
            c.save()
        except Exception as e:
            return {"ok": False, "error": f"設定保存失敗: {e}"}
        if port_open(API_PORT):
            r = _http("/model", "POST", repo, ctype="text/plain; charset=utf-8", timeout=180)
            r["lightweight"] = bool(enabled)
            r["model"] = repo
            return r
        return {"ok": True, "lightweight": bool(enabled), "model": repo,
                "note": "daemon停止中: 次回起動時に反映"}

    def start_daemon(self):
        """daemon 未起動なら起動し、HTTPが立つまで待つ。
        停止直後はポートが閉じきるまで待ってから起動する (残存ポートでの
        二重起動・即死を防ぐ)。返り値に status を含めて JS が確実に再描画できる。"""
        # 1. 既に健全に稼働中なら何もしない
        if port_open(API_PORT) and _http("/health").get("ok"):
            return {"ok": True, "already": True, "status": self.status()}
        # 2. ポートが残存していれば閉じきるまで待つ (最大6秒)
        t0 = time.time()
        while port_open(API_PORT) and time.time() - t0 < 6:
            time.sleep(0.3)
        # 3. 起動
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        subprocess.Popen(
            [PYTHON_EXE, str(DAEMON_SCRIPT)], cwd=str(ROOT),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 4. HTTP が立ち、/health が ok を返すまで待つ
        t0 = time.time()
        while time.time() - t0 < 90:
            if port_open(API_PORT) and _http("/health").get("ok"):
                return {"ok": True, "started": True, "status": self.status()}
            time.sleep(0.5)
        return {"ok": False, "error": "起動がタイムアウトしました(モデルロードに時間)",
                "status": self.status()}

    def stop_daemon(self):
        """daemon を停止 (HTTP /quit → 駄目ならPID kill)。
        ポートが完全に閉じるまで待ってから返す (停止直後の再起動を確実にする)。"""
        if not port_open(API_PORT):
            return {"ok": True, "already_stopped": True, "status": self.status()}
        _http("/quit", "POST", "")
        # /quit 後、ポートが閉じるまで待つ
        t0 = time.time()
        while time.time() - t0 < 6:
            if not port_open(API_PORT):
                return {"ok": True, "stopped": True, "status": self.status()}
            time.sleep(0.3)
        # フォールバック: PID kill
        try:
            pid = int(DAEMON_PID_PATH.read_text(encoding="utf-8").strip())
            os.kill(pid, 15)
        except Exception:
            pass
        # kill 後もポートが閉じるまで待つ
        t0 = time.time()
        while port_open(API_PORT) and time.time() - t0 < 6:
            time.sleep(0.3)
        ok = not port_open(API_PORT)
        return {"ok": ok, "stopped": ok,
                "error": None if ok else "停止できませんでした",
                "status": self.status()}

    def restart_daemon(self):
        self.stop_daemon()
        time.sleep(1.0)
        return self.start_daemon()

    def set_voice(self, name):
        return _http("/voice", "POST", str(name))

    def set_speed(self, speed):
        return _http("/speed", "POST", str(speed))

    def toggle_auto(self):
        return _http("/toggle", "POST", "")

    def say(self, text, caption=""):
        # 感情caption (Irodoriクローン) があれば JSON で送る。
        # daemon は JSON 時のみ "caption" を読む (未指定はボイス既定感情)。
        cap = (caption or "").strip()
        if cap:
            body = json.dumps({"text": str(text), "caption": cap}, ensure_ascii=False)
            return _http("/say", "POST", body, ctype="application/json; charset=utf-8")
        return _http("/say", "POST", str(text))

    def stop_speaking(self):
        return _http("/stop", "POST", "")

    # ── ボイスの整理 (削除はゴミ箱へ移動 → 30日後に自動で完全削除) ──
    # 削除は daemon の HTTP を使わず、この窓のプロセスが直接ファイルを動かす
    # (daemon の HTTP は CORS が * で、ほかのページから叩かれうるため)。
    # JS から渡るのは名前/項目名の文字列だけ。検証は voice_trash 側で行う。

    def manage_list(self):
        """整理カードの表示用: ボイス一覧 (同梱/読み上げ中の印つき) とゴミ箱の中身。"""
        try:
            _vt.purge_expired(VOICES_DIR)
            try:
                active, unknown = _vt.active_voice_names(ROOT, API_PORT), False
            except _vt.TrashError:
                active, unknown = set(), True  # 表示だけは出し、削除の時にもう一度確認して拒否する
            return {"ok": True, "rows": _vt.voice_rows(VOICES_DIR, active),
                    "trash": _vt.list_trash(VOICES_DIR), "active_unknown": unknown,
                    "retention_days": _vt.RETENTION_DAYS}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def trash_voice(self, name):
        try:
            active = _vt.active_voice_names(ROOT, API_PORT)
            r = _vt.move_to_trash(VOICES_DIR, str(name), active)
            return {"ok": True, **r, "retention_days": _vt.RETENTION_DAYS}
        except _vt.TrashError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"削除できませんでした ({e})"}

    def trash_restore(self, entry):
        try:
            return {"ok": True, **_vt.restore(VOICES_DIR, str(entry))}
        except _vt.TrashError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"元に戻せませんでした ({e})"}

    def trash_open(self):
        """ゴミ箱フォルダをエクスプローラーで開く (開くのは固定のパスだけ)。"""
        try:
            d = _vt.trash_dir_for(VOICES_DIR)
            d.mkdir(exist_ok=True)
            os.startfile(str(d))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def copy(self, text):
        """クリップボードへコピー。pywebview は data:/file: 描画のため
        navigator.clipboard が使えない。Python(tkinter)側で確実に書き込む。"""
        try:
            import tkinter
            r = tkinter.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(str(text))
            r.update()  # クリップボードへ焼き付ける
            r.destroy()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


HTML = r"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NoaTTS 読み上げ設定</title>
<style>
  :root{--bg:#1a1620;--panel:#241d2e;--line:#3a3048;--ink:#ece6f2;
    --muted:#a99cb8;--accent:#d8557a;--accent2:#7a5fd8;--ok:#5fd89a;--off:#8a7f99;}
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:"Yu Gothic UI","Segoe UI",sans-serif;line-height:1.7;}
  .wrap{max-width:680px;margin:0 auto;padding:22px 20px 50px;}
  h1{font-size:20px;margin:0 0 14px;}
  h2{font-size:14px;margin:0 0 10px;color:var(--accent);}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:16px 18px;margin-top:14px;}
  .status{display:flex;align-items:center;gap:10px;font-size:14px;}
  .dot{width:11px;height:11px;border-radius:50%;background:var(--off);}
  .dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok);}
  .dot.off{background:var(--accent);}
  label{font-size:13px;color:var(--muted);display:block;margin-bottom:5px;}
  select,textarea,input[type=text]{width:100%;background:#181320;color:var(--ink);
    border:1px solid var(--line);border-radius:8px;padding:9px 11px;
    font-size:14px;font-family:inherit;}
  input[type=text]::placeholder,textarea::placeholder{color:var(--muted);}
  textarea{min-height:70px;resize:vertical;}
  input[type=range]{width:100%;accent-color:var(--accent);}
  .row{display:flex;gap:10px;align-items:center;margin-top:12px;flex-wrap:wrap;}
  .row.sb{justify-content:space-between;}
  button{cursor:pointer;border:none;border-radius:8px;padding:9px 16px;
    font-size:13px;font-weight:600;color:#fff;transition:filter .15s;}
  button:hover{filter:brightness(1.12);} button:active{filter:brightness(.9);}
  button:disabled{opacity:.4;cursor:not-allowed;}
  .b-pri{background:linear-gradient(135deg,var(--accent),var(--accent2));}
  .b-sub{background:#3a3048;} .b-stop{background:#4a4356;}
  .emoji-row{display:flex;flex-wrap:wrap;gap:6px;}
  .emoji-row button{background:#2e2640;padding:6px 10px;font-size:12px;}
  .vram-gauge{display:flex;width:100%;height:22px;border-radius:7px;overflow:hidden;
    background:#2e2640;border:1px solid var(--line);}
  .vram-noa{height:100%;background:linear-gradient(90deg,#d8557a,#e0769a);transition:width .4s;}
  .vram-studio{height:100%;background:linear-gradient(90deg,#5fb0d8,#7ac6e0);transition:width .4s;}
  .vram-other{height:100%;background:#5a4a78;transition:width .4s;}
  .vram-legend{display:flex;gap:14px;margin-top:8px;font-size:12px;color:var(--muted);}
  .vram-legend b{color:var(--ink);font-weight:600;}
  .vram-sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle;}
  .vram-noa-c{background:#d8557a;} .vram-studio-c{background:#5fb0d8;} .vram-other-c{background:#5a4a78;} .vram-free-c{background:#2e2640;border:1px solid var(--line);}
  .b-on{background:var(--ok);color:#0c1f14;} .b-off{background:#4a4356;}
  .speedval{min-width:46px;text-align:right;font-variant-numeric:tabular-nums;color:var(--accent);font-weight:600;}
  .msg{margin-top:10px;font-size:12.5px;color:var(--muted);min-height:16px;}
  pre{background:#141019;border:1px solid var(--line);border-radius:8px;
    padding:11px 13px;overflow-x:auto;font-size:12.5px;color:#d7cce6;margin:8px 0;
    font-family:"Cascadia Code","Consolas",monospace;}
  /* コードブロックは「見出し行(言語名+copyボタン) + pre」の2段。copy を pre の中に float で
     置くと、長い行の文字がボタンに重なってクリックが pre に吸われていた。 */
  .code{margin:10px 0;}
  .code-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;
    font-size:12px;color:var(--muted);}
  .code pre{margin:0;}
  .copy{background:#3a3048;color:var(--ink);border-radius:8px;padding:6px 16px;min-width:76px;
    font-size:12.5px;font-weight:600;cursor:pointer;} .copy:hover{filter:brightness(1.2);}
  /* ── ボイスの整理 (折りたたみ) ── */
  .mgsum{display:flex;align-items:center;gap:10px;cursor:pointer;list-style:none;}
  .mgsum::-webkit-details-marker{display:none;}
  .mgsum h2{margin:0;} .mgsum .arrow{color:var(--muted);font-size:13px;width:14px;}
  .mgsum .cnt{font-size:12.5px;color:var(--muted);} .mgsum .sp{flex:1;}
  .warnchip{font-size:11.5px;padding:2px 9px;border-radius:10px;background:rgba(192,57,43,.25);color:#ff9a8d;}
  .seg{display:flex;gap:6px;margin:12px 0;}
  .seg button{padding:7px 14px;background:#2e2640;color:var(--muted);}
  .seg button.on{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;}
  .mglist{border:1px solid var(--line);border-radius:10px;overflow:hidden;max-height:290px;overflow-y:auto;}
  .mgrow{display:flex;align-items:center;gap:10px;padding:8px 12px;border-bottom:1px solid var(--line);
    background:#201a29;font-size:14px;}
  .mgrow:last-child{border-bottom:none;}
  .mgrow .n{flex:1;min-width:0;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .mgrow .t,.mgrow .d{font-size:12px;color:var(--muted);white-space:nowrap;}
  .mgrow.lock{background:#1d1824;} .mgrow.lock .n{color:#7f748f;}
  .mgrow.act{background:#1f2a26;}
  .chip{font-size:11.5px;padding:2px 9px;border-radius:10px;background:#3a3048;color:var(--muted);white-space:nowrap;}
  .chip.ok{background:rgba(95,216,154,.16);color:var(--ok);} .chip.red{background:rgba(192,57,43,.25);color:#ff9a8d;}
  .mgbtn{padding:6px 10px;background:#3a3048;}
  .mgbtn:disabled{opacity:.35;cursor:not-allowed;}
  .over{position:fixed;inset:0;background:rgba(8,6,12,.66);display:flex;align-items:center;justify-content:center;z-index:50;}
  .modal{width:min(440px,calc(100vw - 32px));background:var(--panel);border:1px solid #54476b;border-radius:12px;
    padding:20px 22px;box-shadow:0 10px 30px rgba(0,0,0,.6);}
  .modal h3{margin:0 0 8px;font-size:16px;} .modal p{margin:0;font-size:14px;color:#d7cce6;line-height:1.7;}
  .modal p small{color:var(--muted);font-size:12.5px;}
  .modal .acts{display:flex;justify-content:flex-end;gap:10px;margin-top:18px;}
  .b-danger{background:#c0392b;}
  .modal button:focus-visible{outline:2px solid #fff;outline-offset:2px;}
  details{margin-top:6px;} summary{cursor:pointer;color:var(--muted);font-size:13px;}
</style></head>
<body><div class="wrap">
  <h1>NoaTTS 読み上げ設定</h1>

  <div class="card">
    <div class="status">
      <span class="dot" id="dot"></span>
      <span id="stext">確認中…</span>
    </div>
    <div class="row">
      <button class="b-pri" id="btnStart" onclick="startD()">起動</button>
      <button class="b-stop" id="btnStop" onclick="stopD()">停止</button>
      <button class="b-sub" id="btnRestart" onclick="restartD()">再起動</button>
    </div>
    <div class="row" style="margin-top:8px;">
      <label style="display:flex;align-items:center;gap:8px;margin:0;cursor:pointer;font-size:13px;color:var(--ink);">
        <input type="checkbox" id="lwChk" style="width:auto;accent-color:var(--accent);" onchange="setLightweight()">
        ⚡ 軽量モード (int4・約1.5GB / VRAM節約)
      </label>
    </div>
    <div class="msg" id="dmsg"></div>
  </div>

  <div class="card">
    <h2>VRAM 使用状況</h2>
    <div id="vramGauge" class="vram-gauge"><div id="vramNoa" class="vram-noa"></div><div id="vramStudio" class="vram-studio"></div><div id="vramOther" class="vram-other"></div></div>
    <div class="vram-legend">
      <span><i class="vram-sw vram-noa-c"></i>読み上げ <b id="vramNoaTxt">-</b></span>
      <span><i class="vram-sw vram-studio-c"></i>Voice Studio <b id="vramStudioTxt">-</b></span>
      <span><i class="vram-sw vram-other-c"></i>その他 <b id="vramOtherTxt">-</b></span>
      <span><i class="vram-sw vram-free-c"></i>空き <b id="vramFreeTxt">-</b></span>
    </div>
    <div class="msg" id="vramMsg"></div>
  </div>

  <div class="card">
    <h2>使用モデル</h2>
    <label>読み上げモデル (Irodori)</label>
    <select id="model" onchange="setModel()"></select>
    <div class="msg" id="mmsg"></div>
  </div>

  <div class="card">
    <h2>ボイス と 話速</h2>
    <label>使用ボイス</label>
    <select id="voice" onchange="setVoice()"></select>
    <div class="row sb" style="margin-top:14px;">
      <label style="margin:0;">話速 (speed)</label>
      <span class="speedval" id="speedval">1.00</span>
    </div>
    <input type="range" id="speed" min="0.5" max="2.0" step="0.05" value="1.0"
      oninput="document.getElementById('speedval').textContent=(+this.value).toFixed(2)"
      onchange="setSpeed()">
    <div class="msg" id="vmsg"></div>
  </div>

  <div class="card" id="mgcard">
    <details id="mg" ontoggle="mgToggle()">
      <summary class="mgsum"><span class="arrow" id="mgarrow">▸</span><h2>ボイスの整理</h2>
        <span class="cnt" id="mgcnt"></span><span class="sp"></span><span class="warnchip" id="mgwarn" style="display:none"></span></summary>
      <div class="seg">
        <button id="tabV" class="on" onclick="mgTab('v')">ボイス <span id="nV"></span></button>
        <button id="tabT" onclick="mgTab('t')">🗑 ゴミ箱 <span id="nT"></span></button>
      </div>
      <div id="paneV">
        <input type="text" id="mgq" placeholder="🔍 名前で絞り込み" oninput="mgRender()" style="margin-bottom:10px;">
        <div class="mglist" id="mgVlist"></div>
      </div>
      <div id="paneT" style="display:none;">
        <div class="mglist" id="mgTlist"></div>
        <div class="row sb"><button class="b-sub" onclick="mgOpenTrash()">📂 ゴミ箱フォルダを開く</button>
          <span style="font-size:12px;color:var(--muted);">30日を過ぎたものは、起動時と削除時に自動で完全削除</span></div>
        <div class="msg">ℹ️ 同名のボイスが既にある時は「<b>名前_復元</b>」の名前で戻します。</div>
      </div>
      <div class="msg" id="mgmsg"></div>
      <div class="msg">ℹ️ 削除したボイスは <b>voices_trash</b> フォルダに <b>30日間</b>保管され、その後は自動で完全に削除されます。
        30日以内なら「ゴミ箱」から元に戻せます。（プロジェクトフォルダの入れ直しや <code>git clean</code> でも消えます）</div>
    </details>
  </div>

  <div class="card">
    <h2>自動読み上げ</h2>
    <div class="row sb">
      <span style="font-size:13px;color:var(--muted);">_tts_say.txt に書かれたテキストを自動で読み上げる (tts_auto.flag)</span>
      <button id="btnAuto" class="b-off" onclick="toggleAuto()">OFF</button>
    </div>
  </div>

  <div class="card">
    <h2>テスト読み上げ</h2>
    <textarea id="text" placeholder="読み上げさせたい文を入力…"></textarea>
    <div style="font-size:12px;color:var(--muted);margin:8px 0 4px;">感情絵文字を挿入 (文中に入れると声に乗る・重ねると強調):</div>
    <div class="emoji-row">__EMOJI_PALETTE__</div>
    <input id="emotion" type="text" placeholder="指示 / 感情 (任意・補助)  例: 高めの声で / 落ち着いた低い声で (感情は絵文字が強く効きます)" style="margin-top:8px;">
    <div class="row">
      <button class="b-pri" onclick="say()">読み上げる</button>
      <button class="b-stop" onclick="stopSpeak()">中断</button>
      <button class="b-sub" onclick="sample()">サンプル</button>
    </div>
    <div class="msg" id="tmsg"></div>
  </div>

  <div class="card">
    <h2>外部から叩く (API)</h2>
    <details><summary>使い方を表示</summary>
      <p style="font-size:12.5px;color:var(--muted);">開発タスクの末尾に一行足すだけで完了通知を読み上げます。</p>
      <div class="code"><div class="code-h"><span>curl</span><button class="copy" onclick="cp(this)">copy</button></div><pre>curl -X POST http://127.0.0.1:7870/say -d "ビルドが完了いたしました"</pre></div>
      <div class="code"><div class="code-h"><span>PowerShell</span><button class="copy" onclick="cp(this)">copy</button></div><pre>Invoke-RestMethod http://127.0.0.1:7870/say -Method Post -Body "テストが通りました"</pre></div>
    </details>
  </div>
</div>

<script>
// api は pywebview 準備完了後に代入する (最上部で window.pywebview.api を
// 参照すると、まだ undefined でTypeErrorになり初期化全体が止まる)
let api = null;

async function refresh() {
  if (!api) return;
  const dot=document.getElementById('dot'), st=document.getElementById('stext');
  const s = await api.status();
  const ctrls = ['voice','speed','model'];
  if (s.running) {
    dot.className='dot on';
    st.textContent='稼働中 — ボイス: '+(s.voice||'?')+' / 話速 '+(+s.speed).toFixed(2)
      +(s.speaking?' (読み上げ中)':'');
    document.getElementById('btnStart').disabled=true;
    document.getElementById('btnStop').disabled=false;
    document.getElementById('speed').value=s.speed;
    document.getElementById('speedval').textContent=(+s.speed).toFixed(2);
    if (s.model) { const ms=document.getElementById('model');
      if(ms){ if(![...ms.options].some(o=>o.value===s.model)){ const o=document.createElement('option');
        o.value=s.model; o.textContent=s.model.split('/').pop(); ms.appendChild(o); } ms.value=s.model; } }
    { const lw=document.getElementById('lwChk');
      if(lw){ lw.checked = !!(s.model && s.model.indexOf('int4')>=0); lw.disabled=false; } }
    setAutoBtn(s.auto);
    ctrls.forEach(id=>document.getElementById(id).disabled=false);
    document.getElementById('btnAuto').disabled=false;
  } else {
    dot.className='dot off';
    st.textContent='停止中 — 「起動」で読み上げソフトを立ち上げます';
    document.getElementById('btnStart').disabled=false;
    document.getElementById('btnStop').disabled=true;
    ctrls.forEach(id=>document.getElementById(id).disabled=true);
    document.getElementById('btnAuto').disabled=true;
    { const lw=document.getElementById('lwChk'); if(lw) lw.disabled=true; }
  }
  updateVram(s.running);
}

function gb(mb){ return (mb/1024).toFixed(1)+'GB'; }
async function updateVram(running){
  const noaEl=document.getElementById('vramNoa'), studioEl=document.getElementById('vramStudio'), otherEl=document.getElementById('vramOther');
  const msg=document.getElementById('vramMsg');
  const stTxt=document.getElementById('vramStudioTxt');
  if(!running){ noaEl.style.width='0%'; if(studioEl)studioEl.style.width='0%'; otherEl.style.width='0%';
    document.getElementById('vramNoaTxt').textContent='-';
    if(stTxt)stTxt.textContent='-';
    document.getElementById('vramOtherTxt').textContent='-';
    document.getElementById('vramFreeTxt').textContent='-';
    msg.textContent='(読み上げ停止中)'; return; }
  const v=await api.vram();
  if(!v||!v.ok||!v.total){ msg.textContent='VRAM情報を取得できません'; return; }
  const noa=v.noa||0, studio=v.studio||0, total=v.total;
  const other=Math.max(0,(v.used||0)-noa-studio);
  noaEl.style.width=(noa/total*100).toFixed(1)+'%';
  if(studioEl)studioEl.style.width=(studio/total*100).toFixed(1)+'%';
  otherEl.style.width=(other/total*100).toFixed(1)+'%';
  document.getElementById('vramNoaTxt').textContent=gb(noa);
  if(stTxt)stTxt.textContent=(studio>0?gb(studio):'未起動');
  document.getElementById('vramOtherTxt').textContent=gb(other);
  document.getElementById('vramFreeTxt').textContent=gb(v.free||0);
  msg.textContent='全体 '+gb(v.used)+' / '+gb(total)+' 使用中 ('+(v.used/total*100).toFixed(0)+'%)';
}

async function loadVoices() {
  const r = await api.voices();
  const sel = document.getElementById('voice');
  sel.innerHTML='';
  (r.voices||[]).forEach(n=>{
    const o=document.createElement('option'); o.value=n; o.textContent=n;
    if (n===r.active) o.selected=true; sel.appendChild(o);
  });
}

// ───────── ボイスの整理 ─────────
let mg = {rows: [], trash: [], unknown: false, days: 30, tab: 'v'};
const TYPE_LABEL = {clone: '🎙 クローン', design: '🎨 デザイン', custom: '🔧 カスタム'};

function mkel(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
// 自作モーダル (OS 標準の confirm は白く、窓の配色と合わないため)。buttons: [{label, cls, fn}]
// focusIdx のボタンが既定 (Enter で押される)。Esc・外側クリックは何もせず閉じる (=キャンセル)。
function mgModal(title, bodyLines, buttons, focusIdx) {
  closeModal();
  const over = mkel('div', 'over'); over.id = 'modal';
  const box = mkel('div', 'modal');
  box.appendChild(mkel('h3', '', title));
  const p = mkel('p');
  bodyLines.forEach((ln, i) => {
    if (i) p.appendChild(document.createElement('br'));
    const parts = Array.isArray(ln) ? ln : [ln];
    parts.forEach(x => { if (typeof x === 'string') p.appendChild(document.createTextNode(x)); else p.appendChild(x); });
  });
  box.appendChild(p);
  const acts = mkel('div', 'acts'); const bs = [];
  buttons.forEach(b => {
    const btn = mkel('button', b.cls || 'b-sub', b.label);
    btn.onclick = () => { closeModal(); if (b.fn) b.fn(); };
    acts.appendChild(btn); bs.push(btn);
  });
  box.appendChild(acts); over.appendChild(box);
  over.addEventListener('mousedown', ev => { if (ev.target === over) closeModal(); });
  over._onkey = ev => { if (ev.key === 'Escape') { ev.preventDefault(); closeModal(); } };
  document.addEventListener('keydown', over._onkey);
  document.body.appendChild(over);
  (bs[focusIdx] || bs[bs.length - 1]).focus();
}
function closeModal() {
  const o = document.getElementById('modal');
  if (!o) return;
  document.removeEventListener('keydown', o._onkey);
  o.remove();
}
function mgNote(t) { document.getElementById('mgmsg').textContent = t || ''; }
function mgToggle() {
  const open = document.getElementById('mg').open;
  document.getElementById('mgarrow').textContent = open ? '▾' : '▸';
  if (open) loadManage();
}
function mgTab(t) {
  mg.tab = t;
  document.getElementById('tabV').className = t === 'v' ? 'on' : '';
  document.getElementById('tabT').className = t === 't' ? 'on' : '';
  document.getElementById('paneV').style.display = t === 'v' ? '' : 'none';
  document.getElementById('paneT').style.display = t === 't' ? '' : 'none';
}
async function loadManage() {
  if (!api) return;
  let r; try { r = await api.manage_list(); } catch (e) { r = {ok: false, error: String(e)}; }
  if (!r || !r.ok) { mgNote('一覧を読み込めませんでした: ' + ((r && r.error) || '')); return; }
  mg.rows = r.rows || []; mg.trash = r.trash || []; mg.unknown = !!r.active_unknown; mg.days = r.retention_days || 30;
  document.getElementById('nV').textContent = mg.rows.length;
  document.getElementById('nT').textContent = mg.trash.length;
  document.getElementById('mgcnt').textContent = 'ボイス ' + mg.rows.length + ' ／ ゴミ箱 ' + mg.trash.length;
  const soon = mg.trash.filter(t => t.days_left <= 2).length;
  const w = document.getElementById('mgwarn');
  w.style.display = soon ? '' : 'none';
  w.textContent = '⚠ あと2日以内に完全削除: ' + soon + '件';
  mgRender();
}
function mgRender() {
  const q = (document.getElementById('mgq').value || '').trim().toLowerCase();
  const vl = document.getElementById('mgVlist'); vl.innerHTML = '';
  const rows = mg.rows.filter(r => !q || r.name.toLowerCase().includes(q));
  if (!rows.length) vl.appendChild(mkel('div', 'mgrow', q ? '一致するボイスがありません' : 'ボイスがありません'));
  rows.forEach(r => {
    const row = mkel('div', 'mgrow' + (r.protected ? ' lock' : r.active ? ' act' : ''));
    row.appendChild(mkel('div', 'n', r.name));
    row.appendChild(mkel('div', 't', TYPE_LABEL[r.type] || r.type || ''));
    row.appendChild(mkel('div', 'd', r.last_used ? r.last_used.slice(0, 10) : '未使用'));
    if (r.protected) row.appendChild(mkel('span', 'chip', '🔒 同梱'));
    else if (r.active) row.appendChild(mkel('span', 'chip ok', '▶ 読み上げ中'));
    const b = mkel('button', 'mgbtn', '🗑');
    b.title = r.protected ? '同梱ボイスは削除できません' : r.active ? '読み上げ中のボイスは削除できません' : 'ゴミ箱へ移動';
    b.disabled = !!r.reason;
    b.onclick = () => mgAskTrash(r.name);
    row.appendChild(b);
    vl.appendChild(row);
  });
  if (mg.unknown) mgNote('⚠ 読み上げ中のボイスを確認できませんでした (daemon が応答していません)。削除は確認できるまで拒否されます。');
  const tl = document.getElementById('mgTlist'); tl.innerHTML = '';
  if (!mg.trash.length) tl.appendChild(mkel('div', 'mgrow', 'ゴミ箱は空です'));
  mg.trash.forEach(t => {
    const row = mkel('div', 'mgrow');
    row.appendChild(mkel('div', 'n', t.name));
    row.appendChild(mkel('div', 'd', '削除 ' + t.deleted_at));
    row.appendChild(mkel('span', 'chip' + (t.days_left <= 2 ? ' red' : ''), 'あと ' + t.days_left + '日'));
    const b = mkel('button', 'mgbtn', '↩ 元に戻す');
    b.onclick = () => mgRestore(t.entry, t.name);
    row.appendChild(b);
    tl.appendChild(row);
  });
}
function mgAskTrash(name) {
  mgModal('ボイスをゴミ箱へ移動',
    [['「', mkel('b', '', name), '」をゴミ箱へ移動しますか？'],
     [mkel('small', '', mg.days + '日間は「ボイスの整理 → ゴミ箱」から元に戻せます。' + mg.days + '日後に自動で完全に削除されます。')]],
    [{label: 'ゴミ箱へ移動', cls: 'b-danger', fn: () => mgDoTrash(name)},
     {label: 'キャンセル', cls: 'b-pri'}], 1);
}
async function mgDoTrash(name) {
  let r; try { r = await api.trash_voice(name); } catch (e) { r = {ok: false, error: String(e)}; }
  if (r && r.ok) { mgNote('「' + r.name + '」をゴミ箱へ移動しました。' + mg.days + '日後に自動で完全削除されます。'); }
  else mgModal('削除できません', [(r && r.error) || '不明なエラー'], [{label: 'OK', cls: 'b-pri'}], 0);
  await loadManage(); loadVoices();
}
async function mgRestore(entry, name) {
  let r; try { r = await api.trash_restore(entry); } catch (e) { r = {ok: false, error: String(e)}; }
  if (r && r.ok) mgNote((r.renamed ? '「' + name + '」は同名のボイスがあったため「' + r.restored + '」の名前で戻しました。'
                                   : '「' + r.restored + '」を元に戻しました。') + (r.warning ? ' ⚠ ' + r.warning : ''));
  else mgModal('元に戻せません', [(r && r.error) || '不明なエラー'], [{label: 'OK', cls: 'b-pri'}], 0);
  await loadManage(); loadVoices();
}
async function mgOpenTrash() { try { await api.trash_open(); } catch (e) {} }

async function loadModels() {
  const r = await api.models();
  const sel = document.getElementById('model');
  if (!sel) return;
  sel.innerHTML='';
  (r.models||[]).forEach(m=>{
    const o=document.createElement('option');
    o.value=m.repo_id;
    o.textContent=m.label + (m.downloaded?'':' (未DL)');
    sel.appendChild(o);
  });
}

async function setModel(){
  const id=document.getElementById('model').value;
  const m=document.getElementById('mmsg');
  if(!id) return;
  m.textContent='モデル切替中…(GPU再ロードで数十秒)';
  document.getElementById('model').disabled=true;
  const r=await api.set_model(id);
  document.getElementById('model').disabled=false;
  m.textContent=r.ok?('モデル → '+id):('切替失敗: '+(r.error||''));
  refresh();
}

async function setLightweight(){
  const on=document.getElementById('lwChk').checked;
  const m=document.getElementById('mmsg');
  m.textContent='⚡ 軽量モード切替中…(GPU再ロードで数十秒)';
  document.getElementById('lwChk').disabled=true;
  const r=await api.set_lightweight(on);
  m.textContent=r.ok?('⚡ 軽量モード '+(on?'ON (int4・約1.5GB)':'OFF (通常bf16)')):('切替失敗: '+(r.error||''));
  await loadModels(); await refresh();
}

function setAutoBtn(on){
  const b=document.getElementById('btnAuto');
  b.textContent=on?'ON':'OFF'; b.className=on?'b-on':'b-off';
}

async function startD(){
  document.getElementById('dmsg').textContent='起動中…(モデルロードに数十秒)';
  const r=await api.start_daemon();
  document.getElementById('dmsg').textContent=r.ok?'起動しました':('起動失敗: '+(r.error||''));
  await loadVoices(); await refresh();
}
async function stopD(){
  document.getElementById('dmsg').textContent='停止中…';
  const r=await api.stop_daemon();
  document.getElementById('dmsg').textContent=r.ok?'停止しました':('停止失敗: '+(r.error||''));
  await refresh();
}
async function restartD(){
  document.getElementById('dmsg').textContent='再起動中…';
  const r=await api.restart_daemon();
  document.getElementById('dmsg').textContent=r.ok?'再起動しました':('失敗: '+(r.error||''));
  await loadVoices(); await refresh();
}
async function setVoice(){
  const n=document.getElementById('voice').value;
  const r=await api.set_voice(n);
  document.getElementById('vmsg').textContent=r.ok?('ボイス → '+n):('切替失敗: '+(r.error||''));
  refresh();
}
async function setSpeed(){
  const v=document.getElementById('speed').value;
  const r=await api.set_speed(v);
  document.getElementById('vmsg').textContent=r.ok?('話速 → '+(+r.speed).toFixed(2)):('失敗: '+(r.error||''));
}
async function toggleAuto(){
  const r=await api.toggle_auto();
  if (r.ok) setAutoBtn(r.auto);
}
async function say(){
  const t=document.getElementById('text').value.trim();
  const e=document.getElementById('emotion').value.trim();
  const m=document.getElementById('tmsg');
  if(!t){m.textContent='文を入力してくださいませ。';return;}
  m.textContent='送信中…';
  const r=await api.say(t, e);
  m.textContent=r.ok?('読み上げ開始 ('+r.chars+'字'+(e?' / 感情: '+e:'')+')'):('エラー: '+(r.error||''));
}
const EMOTION_SAMPLES=[
  '楽しそうに弾んだ明るい声で',
  '悲しげで震える声、今にも泣き出しそう',
  '怒って語気を強め、苛立った声で',
  '穏やかでやさしい、落ち着いた声で',
  '元気いっぱい、ハキハキした声で',
  '恥ずかしそうに、もじもじした声で',
  'びっくりして、慌てた声で',
  '眠そうで、ぼんやりした声で',
  'クールに淡々と、冷静な声で',
  'やさしく囁くような、甘い声で',
  '自信たっぷり、堂々とした声で',
  '不安げで、おどおどした声で',
];
function sample(){
  document.getElementById('text').value='これはテスト送信です。音声が聞こえていますか？';
  const e=EMOTION_SAMPLES[Math.floor(Math.random()*EMOTION_SAMPLES.length)];
  document.getElementById('emotion').value=e;
}
function insertEmoji(emo){
  // テスト文の末尾(またはカーソル位置)に感情絵文字を挿入。重ねると強調。
  const t=document.getElementById('text');
  const s=t.selectionStart, e=t.selectionEnd;
  if(typeof s==='number'){ t.value=t.value.slice(0,s)+emo+t.value.slice(e); t.selectionStart=t.selectionEnd=s+emo.length; }
  else { t.value+=emo; }
  t.focus();
}
async function stopSpeak(){ await api.stop_speaking();
  document.getElementById('tmsg').textContent='中断しました。'; }

async function cp(el){
  // ボタンの文言 (copy/copied) に頼らず、対応する pre から直接読む
  // (copied 表示中に押し直すと "ied…" が混ざっていた)
  const txt=el.closest('.code').querySelector('pre').textContent.trim();
  let ok=false;
  try { const r=await api.copy(txt); ok=r && r.ok; } catch(e){}
  if(!ok){ // フォールバック (セキュアコンテキストなら効く)
    try { await navigator.clipboard.writeText(txt); ok=true; } catch(e){}
  }
  el.textContent=ok?'copied':'失敗'; setTimeout(()=>el.textContent='copy',1200);
}

async function init(){
  api = window.pywebview.api;
  document.getElementById('stext').textContent='読み込み中…';
  await loadVoices(); await loadModels(); await refresh(); setInterval(refresh, 4000); loadManage();
}

// pywebviewready が発火すれば即 init。取りこぼし対策として、
// window.pywebview が現れるまでポーリングする保険も併走させる。
window.addEventListener('pywebviewready', init);
(function waitReady(n){
  if (api) return;                       // 既に init 済み
  if (window.pywebview && window.pywebview.api) { init(); return; }
  if (n > 100) {                         // 約10秒待っても駄目
    document.getElementById('stext').textContent='APIに接続できません(pywebview未準備)';
    return;
  }
  setTimeout(()=>waitReady(n+1), 100);
})(0);
</script>
</body></html>
"""


def _render_html() -> str:
    """HTML の __EMOJI_PALETTE__ を感情絵文字ボタン群に置換して返す。"""
    try:
        from engine.emotion_emoji import EMOTION_EMOJI
    except Exception:
        EMOTION_EMOJI = []
    btns = "".join(
        f'<button class="b-sub" title="{desc}" onclick="insertEmoji(\'{emo}\')">{emo} {label}</button>'
        for emo, label, desc in EMOTION_EMOJI
    )
    return HTML.replace("__EMOJI_PALETTE__", btns)


def main():
    api = Api()
    webview.create_window(
        title="NoaTTS — 読み上げ設定",
        html=_render_html(),
        js_api=api,
        width=720, height=900, resizable=True, confirm_close=False,
    )
    _icon = ROOT / "assets" / "noa.ico"
    try:
        webview.start(icon=str(_icon))  # pywebview 5+ は icon 引数対応
    except TypeError:
        webview.start()  # 古い pywebview は icon 非対応


if __name__ == "__main__":
    main()
