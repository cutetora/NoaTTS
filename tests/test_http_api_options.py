"""HTTP API (/say /say_wav /say_dialogue /v1/audio/speech /voice /voices) のオプション結合テスト。

GPU・実 daemon 不要: ダミーの worker と一時の voices フォルダで http_server を別ポートに立てる
(実 daemon の :7870 とは衝突しない)。あわせて TTSWorker の「その回だけの上書きが次へ漏れない」
「キャッシュの並行安全」を、合成部分 (_gen_core) だけ差し替えた本物の worker で確認する。
実行: python tests/test_http_api_options.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import numpy as np

from daemon import servers, runtime, worker as worker_mod

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")


# ── 一時の voices フォルダ ──
tmp = Path(tempfile.mkdtemp(prefix="noa_http_"))
voices = tmp / "voices"
for name, cfgfile in [("noa", "config.json"), ("Sara", "config.json"), ("fresh", "config.default.json")]:
    (voices / name).mkdir(parents=True)
    (voices / name / cfgfile).write_text("{}", encoding="utf-8")
(voices / "notavoice").mkdir()
servers.VOICES_DIR = str(voices)


class FakeWorker:
    """HTTP 層が呼ぶ worker の最小の代役。受け取った引数を記録する。"""
    def __init__(self):
        self.voice_name = "noa"
        self.volume = 1.0
        self.cache_enabled = False
        self.calls = []

    def cancel(self):
        pass

    def speak(self, text, caption=None, cache=None, speed=None):
        self.calls.append(("speak", text, caption, cache, speed))

    def speak_dialogue(self, segments, cache=None):
        self.calls.append(("dialogue", segments, cache))

    def synthesize_wav(self, text, voice=None, speed=None, caption=None, cache=None):
        self.calls.append(("wav", text, voice, speed, caption, cache))
        return np.full(2400, 0.1, dtype=np.float32), 24000

    def switch_voice(self, name):
        self.calls.append(("switch", name))
        self.voice_name = name
        return True


fw = FakeWorker()
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
servers.HTTP_PORT = port
runtime._stop_event.clear()
threading.Thread(target=servers.http_server, args=(fw,), daemon=True).start()
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)


def call(path, body=None, ctype="application/json", raw=False):
    """(status, 本文) を返す。body が dict なら JSON で送る。"""
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else str(body).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 method="POST" if data is not None else "GET",
                                 headers={"Content-Type": ctype} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            b = r.read()
            return r.status, (b if raw else json.loads(b.decode("utf-8")))
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (b if raw else json.loads(b.decode("utf-8")))


def last_say():
    """/say 系が起動したスレッドの完了を待って、最後の呼び出しを返す。"""
    t = runtime._current_speak_thread
    if t is not None:
        t.join(timeout=3)
    return fw.calls[-1] if fw.calls else None


print("== GET /voices ==")
st, r = call("/voices")
check("読める声だけ返す (config.default.json のみも含み、設定なしフォルダは除く)",
      st == 200 and r["voices"] == ["Sara", "fresh", "noa"], str(r))

print("== /say ==")
fw.calls.clear()
st, r = call("/say", "こんにちは", ctype="text/plain")
check("プレーンテキストはオプションなし", st == 200 and last_say() == ("speak", "こんにちは", None, None, None), str(fw.calls))
st, r = call("/say", {"text": "やあ", "speed": 1.5, "caption": "", "cache": False})
check('speed / caption="" / cache を worker に渡す', last_say() == ("speak", "やあ", "", False, 1.5), str(fw.calls[-1]))
st, r = call("/say", {"text": "やあ", "speed": 100})
check("speed は範囲 (4.0) に丸める", last_say()[4] == 4.0)
st, r = call("/say", {"text": "やあ", "voice": "sara", "speed": 1.2, "caption": "嬉しい"})
check("voice 指定は掛け合い経路 (実名に正規化。speed/caption も届く)",
      last_say() == ("dialogue", [{"voice": "Sara", "text": "やあ", "caption": "嬉しい", "speed": 1.2}], None), str(fw.calls[-1]))
st, r = call("/say", {"text": "やあ", "voice": "fresh"})
check("config.default.json のみのカードも voice 指定できる", st == 200, str(r))
for label, body in [("存在しない voice", {"text": "a", "voice": "nobody"}),
                    ("不正な speed", {"text": "a", "speed": "fast"}),
                    ("不正な cache", {"text": "a", "cache": "maybe"}),
                    ("不正な volume", {"text": "a", "volume": "loud"}),
                    ("パス区切りの voice", {"text": "a", "voice": "../noa"})]:
    st, r = call("/say", body)
    check(f"{label} は 400", st == 400 and r["ok"] is False, f"{st} {r}")
st, r = call("/say", [1, 2])
check("JSON が dict でなければ 400 invalid json", st == 400 and r["error"] == "invalid json")
st, r = call("/say", {"text": "  "})
check("空テキストは 400", st == 400)
fw.volume = 1.0
call("/say", {"text": "a", "volume": 0.3})
last_say()
check("volume は以降の読み上げにも続く (仕様)", fw.volume == 0.3)
call("/say", {"text": "b"})
last_say()
check("volume 指定なしの次の /say でも保たれる", fw.volume == 0.3)
fw.volume = 1.0
call("/say", {"text": "a", "volume": "loud"})
check("不正な volume では worker.volume を変えない", fw.volume == 1.0)

print("== /say_wav ==")
fw.calls.clear()
st, data = call("/say_wav", {"text": "こんにちは", "voice": "NOA", "speed": 0.8, "caption": "静かに", "cache": True}, raw=True)
check("WAV を返す", st == 200 and data[:4] == b"RIFF")
check("voice/speed/caption/cache を synthesize_wav へ", fw.calls[-1] == ("wav", "こんにちは", "noa", 0.8, "静かに", True), str(fw.calls[-1]))
st, r = call("/say_wav", {"text": "a", "voice": "nobody"})
check("存在しない voice は 400 (ok:false 形式)", st == 400 and r == {"ok": False, "error": "unknown voice: nobody"}, str(r))
st, r = call("/say_wav", {"text": "a", "speed": "abc"})
check("不正な speed は 500 でなく 400", st == 400, str(r))
fw.calls.clear()
call("/say_wav", {"text": "a", "speed": 0}, raw=True)
check("speed 0 は「指定なし」(従来どおり)", fw.calls[-1][3] is None)

print("== /v1/audio/speech ==")
fw.calls.clear()
st, data = call("/v1/audio/speech", {"input": "こんにちは", "voice": "alloy", "speed": 3, "caption": "元気に", "cache": False}, raw=True)
check("OpenAI の voice 名 (alloy) はアクティブ声にフォールバック。speed 3.0 は通る",
      st == 200 and fw.calls[-1] == ("wav", "こんにちは", None, 3.0, "元気に", False), str(fw.calls[-1]))
st, r = call("/v1/audio/speech", {"input": "a", "speed": "fast"})
check("不正な speed は OpenAI 形式のエラー", st == 400 and "error" in r and "message" in r["error"], str(r))
st, data = call("/v1/audio/speech", {"input": "a", "voice": "Sara"}, raw=True)
check("実在する voice は使う", fw.calls[-1][2] == "Sara")

print("== /say_dialogue ==")
fw.calls.clear()
st, r = call("/say_dialogue", {"voice": "fresh", "speed": 1.1, "caption": "穏やかに", "cache": True, "volume": 0.6,
                                "segments": [{"text": "はじめまして"},
                                             {"voice": "sara", "text": "よろしく", "speed": 1.4, "caption": ""}]})
last_say()
check("既定値の継承とセグメント側の優先", fw.calls[-1] == ("dialogue", [
    {"voice": "fresh", "text": "はじめまして", "speed": 1.1, "caption": "穏やかに"},
    {"voice": "Sara", "text": "よろしく", "speed": 1.4, "caption": ""}], True), str(fw.calls[-1]))
check("volume は worker へ", fw.volume == 0.6)
fw.volume = 1.0
for label, body in [("segments なし", {}), ("存在しない voice", {"segments": [{"voice": "nobody", "text": "a"}]}),
                    ("不正な speed", {"speed": "x", "segments": [{"text": "a"}]})]:
    st, r = call("/say_dialogue", body)
    check(f"{label} は 400", st == 400 and r["ok"] is False, f"{st} {r}")

print("== /voice ==")
fw.calls.clear()
st, r = call("/voice", "SARA", ctype="text/plain")
check("実名に正規化して switch_voice へ", st == 200 and fw.calls[-1] == ("switch", "Sara"), f"{st} {r} {fw.calls}")
st, r = call("/voice", "nobody", ctype="text/plain")
check("存在しない声は 404", st == 404 and r["error"] == "voice not found")
st, r = call("/voice", "../noa", ctype="text/plain")
check("パス区切りは 404", st == 404)

runtime._stop_event.set()

# ── 本物の TTSWorker (合成だけ差し替え) ──
print("== TTSWorker: その回だけの上書きが漏れない / キャッシュ ==")


class VC:
    name = "noa"; voice_type = "design"; seed = 1; ref_audio_path = ""
    default_caption = "既定の感情"; speed = 1.0; max_pause_sec = 0.0


w = object.__new__(worker_mod.TTSWorker)
w.voice_name = "noa"; w._vc = VC(); w._clone_prompt = None
w._pause_override = None; w.cache_enabled = False; w.volume = 1.0
gen_calls = []


def fake_core(text, vc, clone_prompt, caption, pause_cap, speed):
    gen_calls.append((text, caption, speed))
    return np.full(100, 0.2, dtype=np.float32), 24000


w._gen_core = fake_core
w._generate_one("a", caption="")
w._generate_one("a")
w._generate_one("a", caption="嬉しい", speed=1.5)
check('caption: ""=なし / None=ボイス既定 / 文字列=その感情', [g[1] for g in gen_calls] == ["", "既定の感情", "嬉しい"], str(gen_calls))
check("speed: None=ボイスの speed / 数値=その倍率", [g[2] for g in gen_calls] == [1.0, 1.0, 1.5], str(gen_calls))
check("前の指定が self に残らない (override 属性を持たない)",
      not hasattr(w, "_caption_override") and not hasattr(w, "_cache_override"))

worker_mod.CACHE_DIR = tmp / "cache"
gen_calls.clear()
w.cache_enabled = False
w._generate_one("キャッシュ")
w._generate_one("キャッシュ", cache=True)
n_after_first = len(gen_calls)
w._generate_one("キャッシュ", cache=True)
check("cache=True はこの呼び出しだけ有効: 2回目は再利用 (合成は増えない)", len(gen_calls) == n_after_first == 2, str(gen_calls))
check("cache 指定なしは既定 (OFF) に従う", (w._generate_one("キャッシュ"), len(gen_calls))[1] == 3)
check("一時ファイルが残らない", not list((tmp / "cache").glob("*.tmp")) and len(list((tmp / "cache").glob("*.wav"))) == 1)

# 並行で同じ文を要求しても、書きかけの WAV を読まない
gen_calls.clear()
errs = []


def hammer():
    try:
        for _ in range(20):
            wav, sr = w._generate_one("並行", cache=True)
            assert sr == 24000 and len(wav) == 100
    except Exception as e:
        errs.append(repr(e))


ths = [threading.Thread(target=hammer) for _ in range(6)]
[t.start() for t in ths]; [t.join() for t in ths]
check("同じキーを並行に要求しても壊れない", not errs, str(errs[:2]))

check("並行テスト後も .tmp が残らない", not list((tmp / "cache").glob("*.tmp")))

# 保存に失敗しても、.tmp が残らず、合成結果は返る
_real_replace = worker_mod.os.replace
def _fail_replace(*a, **k):
    raise PermissionError("locked (test)")
worker_mod.os.replace = _fail_replace
try:
    wav_f, sr_f = w._generate_one("置換失敗", cache=True)
finally:
    worker_mod.os.replace = _real_replace
check("os.replace が失敗しても音声は返り、.tmp は残らない", len(wav_f) == 100 and not list((tmp / "cache").glob("*.tmp")))

# 一時ロードした声の使用中の印 (ボイスの整理が削除を拒否するため /health に出す)
w._busy_lock = threading.Lock(); w._busy = {}
seen = []
w._load_vc_only = lambda name: (w._vc, None)
_core = w._gen_core
w._gen_core = lambda *a, **k: (seen.append(w.busy_voices()), _core(*a, **k))[1]
w.synthesize_wav("使用中テスト", voice="Other", cache=False)
check("別の声を一時ロードしている間は busy_voices に載り、終わると外れる", seen and all(s == ["other"] for s in seen) and w.busy_voices() == [], f"{seen} / {w.busy_voices()}")
seen.clear(); w.synthesize_wav("アクティブ声", voice="noa", cache=False)
check("アクティブ声 (大文字小文字違いも) は busy に載せない", all(s == [] for s in seen))
w._gen_core = _core

wav, sr = w.synthesize_wav("こんにちは。ありがとう。", caption="", speed=2.0, cache=False)
check("synthesize_wav も caption/speed を引数で受ける", len(wav) > 0 and gen_calls[-1][1] == "" and gen_calls[-1][2] == 2.0, str(gen_calls[-2:]))

print()
print("ALL PASS" if FAIL == 0 else f"{FAIL} FAILED")
sys.exit(1 if FAIL else 0)
