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

ROOT = Path(__file__).parent
PYTHON_EXE = sys.executable
DAEMON_SCRIPT = ROOT / "noa_tts_daemon.py"
DAEMON_PID_PATH = ROOT / ".tts_daemon_pid"

API_HOST = "127.0.0.1"
API_PORT = 7870
API_BASE = f"http://{API_HOST}:{API_PORT}"


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
        """VRAM使用状況 (全体/NoaTTS/空き、MB) を daemon から取得。"""
        if not port_open(API_PORT):
            return {"ok": False}
        return _http("/vram")

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
  .vram-other{height:100%;background:#5a4a78;transition:width .4s;}
  .vram-legend{display:flex;gap:14px;margin-top:8px;font-size:12px;color:var(--muted);}
  .vram-legend b{color:var(--ink);font-weight:600;}
  .vram-sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle;}
  .vram-noa-c{background:#d8557a;} .vram-other-c{background:#5a4a78;} .vram-free-c{background:#2e2640;border:1px solid var(--line);}
  .b-on{background:var(--ok);color:#0c1f14;} .b-off{background:#4a4356;}
  .speedval{min-width:46px;text-align:right;font-variant-numeric:tabular-nums;color:var(--accent);font-weight:600;}
  .msg{margin-top:10px;font-size:12.5px;color:var(--muted);min-height:16px;}
  pre{background:#141019;border:1px solid var(--line);border-radius:8px;
    padding:11px 13px;overflow-x:auto;font-size:12.5px;color:#d7cce6;margin:8px 0;
    font-family:"Cascadia Code","Consolas",monospace;}
  .copy{float:right;font-size:11px;padding:2px 8px;background:#332a42;border-radius:5px;
    cursor:pointer;color:var(--muted);} .copy:hover{color:var(--ink);}
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
    <div class="msg" id="dmsg"></div>
  </div>

  <div class="card">
    <h2>VRAM 使用状況</h2>
    <div id="vramGauge" class="vram-gauge"><div id="vramNoa" class="vram-noa"></div><div id="vramOther" class="vram-other"></div></div>
    <div class="vram-legend">
      <span><i class="vram-sw vram-noa-c"></i>NoaTTS <b id="vramNoaTxt">-</b></span>
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
      <pre><span class="copy" onclick="cp(this)">copy</span>curl -X POST http://127.0.0.1:7870/say -d "ビルドが完了いたしました"</pre>
      <pre><span class="copy" onclick="cp(this)">copy</span>Invoke-RestMethod http://127.0.0.1:7870/say -Method Post -Body "テストが通りました"</pre>
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
    if (s.model) { const ms=document.getElementById('model'); if(ms) ms.value=s.model; }
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
  }
  updateVram(s.running);
}

function gb(mb){ return (mb/1024).toFixed(1)+'GB'; }
async function updateVram(running){
  const noaEl=document.getElementById('vramNoa'), otherEl=document.getElementById('vramOther');
  const msg=document.getElementById('vramMsg');
  if(!running){ noaEl.style.width='0%'; otherEl.style.width='0%';
    document.getElementById('vramNoaTxt').textContent='-';
    document.getElementById('vramOtherTxt').textContent='-';
    document.getElementById('vramFreeTxt').textContent='-';
    msg.textContent='(読み上げ停止中)'; return; }
  const v=await api.vram();
  if(!v||!v.ok||!v.total){ msg.textContent='VRAM情報を取得できません'; return; }
  const noa=v.noa||0, other=Math.max(0,(v.used||0)-noa), total=v.total;
  noaEl.style.width=(noa/total*100).toFixed(1)+'%';
  otherEl.style.width=(other/total*100).toFixed(1)+'%';
  document.getElementById('vramNoaTxt').textContent=gb(noa);
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
  const txt=el.parentNode.textContent.replace(/^copy/,'').trim();
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
  await loadVoices(); await loadModels(); await refresh(); setInterval(refresh, 4000);
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
