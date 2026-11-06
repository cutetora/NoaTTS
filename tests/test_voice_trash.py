"""voice/voice_trash.py (ボイスのゴミ箱) の単体テスト。GPU・daemon 不要。
実行: python tests/test_voice_trash.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from voice import voice_trash as vt

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")


def err(fn, *a, **k):
    try:
        fn(*a, **k)
    except vt.TrashError as e:
        return str(e)
    return None


root = Path(tempfile.mkdtemp(prefix="noa_trash_"))
voices = root / "voices"
voices.mkdir()
NOW = datetime(2026, 11, 6, 12, 0, 0)


def mk(name, vtype="clone", last="", default=False, files=("ref_audio.wav", "sample.wav")):
    d = voices / name
    d.mkdir()
    (d / ("config.default.json" if default else "config.json")).write_text(
        json.dumps({"name": name, "voice_type": vtype, "last_used_at": last}), encoding="utf-8")
    for f in files:
        (d / f).write_bytes(b"data-" + name.encode())
    return d


mk("noa", default=True, last="2026-11-06 10:00:00")
mk("man", "design", default=True)
mk("hana", "design", "2026-10-12 08:00:00")
mk("花子_clone", "clone", "")
mk("yukino", "clone", "2026-11-05 09:00:00")
(voices / "notavoice").mkdir()  # 設定ファイルの無いフォルダ

print("== 一覧 ==")
rows = vt.voice_rows(voices, active_names={"YUKINO"})
by = {r["name"]: r for r in rows}
check("読めるボイスだけ (設定なしフォルダを除く)", sorted(by) == ["hana", "man", "noa", "yukino", "花子_clone"], str(sorted(by)))
check("同梱は protected", by["noa"]["protected"] and by["man"]["protected"] and not by["hana"]["protected"])
mk("noa2_copy", default=True)
check("default.json を持つ複製も守る / 同梱名 (大文字小文字違い) も守る",
      vt.is_protected(voices / "noa2_copy") and vt.is_protected(voices / "MAN"))
import shutil as _sh
_sh.rmtree(voices / "noa2_copy")
(voices / "noa" / "config.default.json").rename(voices / "noa" / "x.bak")
check("config.default.json が無くても 名前が noa なら守る", vt.is_protected(voices / "noa"))
(voices / "noa" / "x.bak").rename(voices / "noa" / "config.default.json")
check("読み上げ中は active (大文字小文字を無視)", by["yukino"]["active"] and not by["hana"]["active"])
check("reason: 同梱 / 読み上げ中 / なし", (by["noa"]["reason"], by["yukino"]["reason"], by["hana"]["reason"]) == ("protected", "active", ""))
check("種別と最終使用を読む", by["hana"]["type"] == "design" and by["hana"]["last_used"] == "2026-10-12 08:00:00")
check("最近使った順 (未使用は最後)", rows[0]["name"] == "noa" and rows[-1]["name"] in ("man", "花子_clone"), str([r["name"] for r in rows]))

print("== 削除の拒否 ==")
check("同梱は拒否", "同梱" in (err(vt.move_to_trash, voices, "noa") or ""))
check("読み上げ中は拒否 (照合は大文字小文字を無視)", "読み上げ" in (err(vt.move_to_trash, voices, "yukino", active_names={"YUKINO"}) or ""))
check("削除の対象は完全一致のみ (大文字小文字だけ違う名前は別物として見つからない)", "見つかりません" in (err(vt.move_to_trash, voices, "Hana") or ""))
check("前後の空白は削らずに拒否 (別のフォルダを指さない)", "空白" in (err(vt.move_to_trash, voices, " hana") or "") and "空白" in (err(vt.move_to_trash, voices, "hana ") or ""))
check("存在しない名前は拒否", "見つかりません" in (err(vt.move_to_trash, voices, "nobody") or ""))
check("設定なしフォルダは対象外", "見つかりません" in (err(vt.move_to_trash, voices, "notavoice") or ""))
for bad in ["", "..", "a/b", "a\\b", "x:y", "花子.", "con", "NUL", "../voices/hana"]:
    check(f"不正な名前 {bad!r} は拒否", err(vt.move_to_trash, voices, bad) is not None)
check("拒否した時は何も動かない", (voices / "noa").exists() and (voices / "yukino").exists() and not (root / "voices_trash").exists() or not list((root / "voices_trash").iterdir()))

print("== 削除 ==")
r = vt.move_to_trash(voices, "hana", now=NOW)
check("voices/ から消え、ゴミ箱に移る", not (voices / "hana").exists() and (root / "voices_trash" / r["entry"]).is_dir(), str(r))
check("フォルダ名は 名前__日時", r["entry"] == "hana__20261106-120000", r["entry"])
check("中身 (音声ファイル) が丸ごと残る", (root / "voices_trash" / r["entry"] / "ref_audio.wav").read_bytes() == b"data-hana")
check("削除後は voice_rows にも /voices 相当にも出ない", "hana" not in [x["name"] for x in vt.voice_rows(voices)])
mk("hana", "design")
r2 = vt.move_to_trash(voices, "hana", now=NOW)
check("同じ名前を同じ秒に2回捨てても衝突しない", r2["entry"] != r["entry"] and (root / "voices_trash" / r2["entry"]).is_dir(), r2["entry"])
r3 = vt.move_to_trash(voices, "花子_clone", now=NOW)
check("日本語名も扱える", r3["entry"].startswith("花子_clone__"))

print("== ゴミ箱の一覧 ==")
lst = vt.list_trash(voices, now=NOW)
check("3件が新しい順で並び、残り30日", len(lst) == 3 and all(e["days_left"] == 30 for e in lst), str(lst))
lst2 = vt.list_trash(voices, now=NOW + timedelta(days=28, hours=1))
check("28日後は『あと2日』", all(e["days_left"] == 2 for e in lst2), str(lst2))
(root / "voices_trash" / "random_dir").mkdir()
(root / "voices_trash" / "note.txt").write_text("x")
check("名前を解釈できない項目は一覧に出さない", len(vt.list_trash(voices, now=NOW)) == 3)

print("== 復元 ==")
res = vt.restore(voices, r3["entry"])
check("元の名前で戻る", res == {"restored": "花子_clone", "renamed": False, "warning": ""} and (voices / "花子_clone" / "sample.wav").exists(), str(res))
check("戻したらゴミ箱から消える", not (root / "voices_trash" / r3["entry"]).exists())
mk("hana", "design")   # 同名が既にある状態にする
res = vt.restore(voices, r["entry"])
check("同名が既にあれば『名前_復元』", res == {"restored": "hana_復元", "renamed": True, "warning": ""} and (voices / "hana_復元").is_dir(), str(res))
check("改名したら config の name も合わせる (一覧に同名が2つ並ばない)",
      json.loads((voices / "hana_復元" / "config.json").read_text(encoding="utf-8"))["name"] == "hana_復元")
check("改名しない復元は config を変えない",
      json.loads((voices / "花子_clone" / "config.json").read_text(encoding="utf-8"))["name"] == "花子_clone")
res = vt.restore(voices, r2["entry"])
check("さらに重なれば『名前_復元2』", res["restored"] == "hana_復元2", str(res))
check("存在しない項目は拒否", err(vt.restore, voices, "ghost__20260101-000000") is not None)
for bad in ["../x", "a/b", "hana", "random_dir"]:
    check(f"不正な項目名 {bad!r} は拒否", err(vt.restore, voices, bad) is not None)

print("== 自動の完全削除 ==")
def put(name, when):
    d = root / "voices_trash" / f"{name}__{when.strftime('%Y%m%d-%H%M%S')}"
    d.mkdir(); (d / "config.json").write_text("{}", encoding="utf-8")
put("old1", NOW - timedelta(days=31))
put("old2", NOW - timedelta(days=29, hours=23))
put("fresh", NOW - timedelta(days=1))
n = vt.purge_expired(voices, now=NOW)
names = [e["name"] for e in vt.list_trash(voices, now=NOW)]
check("30日を過ぎたものだけ完全削除 (件数)", n == 1, str(n))
check("29日23時間は残り、1日前も残る", "old2" in names and "fresh" in names and "old1" not in names, str(names))
check("名前を解釈できないフォルダ・ファイルは触らない", (root / "voices_trash" / "random_dir").is_dir() and (root / "voices_trash" / "note.txt").exists())
check("期限ちょうど (30日0秒) は削除対象", vt.purge_expired(voices, now=NOW + timedelta(hours=1)) == 1)
put("old3", NOW - timedelta(days=40))
mk("tmp1")
vt.move_to_trash(voices, "tmp1", now=NOW)
check("削除のたびに期限切れも掃除する", "old3" not in [e["name"] for e in vt.list_trash(voices, now=NOW)])

print("== 移動に失敗した時 ==")
mk("locked")
_real = os.replace
def boom(*a, **k):
    raise PermissionError("in use (test)")
vt.os.replace = boom
try:
    msg = err(vt.move_to_trash, voices, "locked", now=NOW)
finally:
    vt.os.replace = _real
check("使用中の可能性を伝え、元のフォルダは無傷", msg is not None and "使用中" in msg and (voices / "locked" / "ref_audio.wav").exists(), str(msg))

print("== リンクは辿らない ==")
import subprocess
outside = root / "outside"; outside.mkdir(); (outside / "keep.txt").write_text("keep")
link = root / "voices_trash" / "evil__20200101-000000"
subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
if link.exists():
    n_ = vt.purge_expired(voices, now=NOW)
    check("期限切れでもジャンクションは削除対象にしない (リンク先を消さない)", (outside / "keep.txt").exists(), f"purged={n_}")
    check("ジャンクションは復元も拒否", err(vt.restore, voices, "evil__20200101-000000") is not None)
    os.rmdir(link)
else:
    print("  SKIP: ジャンクションを作れない環境")

print("== 移動元がリンクの時 ==")
outside2 = root / "outside2"; outside2.mkdir(); (outside2 / "config.json").write_text("{}")
linkv = voices / "linkvoice"
subprocess.run(["cmd", "/c", "mklink", "/J", str(linkv), str(outside2)], capture_output=True)
if linkv.exists():
    check("リンクのボイスは移動を拒否 (戻せず消えない状態を作らない)", "リンク" in (err(vt.move_to_trash, voices, "linkvoice") or "") and (outside2 / "config.json").exists())
    os.rmdir(linkv)
else:
    print("  SKIP: ジャンクションを作れない環境")

print("== 復元時の name 書き換え失敗 ==")
mk("dupe"); rr = vt.move_to_trash(voices, "dupe", now=NOW)
mk("dupe")
(root / "voices_trash" / rr["entry"] / "config.json").write_text("{ broken json", encoding="utf-8")
res = vt.restore(voices, rr["entry"])
check("name を書き換えられなければ warning を返す (黙って成功にしない)", res["renamed"] and "書き換えられませんでした" in res["warning"], str(res))

print("== アクティブ声の取得 ==")
(root / "_active_voice.txt").write_text("Yukino", encoding="utf-8")
check("daemon が無くても _active_voice.txt から取れる (小文字に揃える)", vt.active_voice_names(root, port=1, timeout=0.2) == {"yukino"})
import socket, threading
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5); hang_port = srv.getsockname()[1]
check("daemon のポートは開いているが /health に答えない時は拒否 (使っていないと誤判定しない)",
      "確認できませんでした" in (err(vt.active_voice_names, root, port=hang_port, timeout=0.5) or ""))
srv.close()
# daemon の /health が busy_voices (一時ロード中の声) を返したら、それも使用中として扱う
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps({"ok": True, "voice": "noa", "busy_voices": ["hana"]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
hs = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=hs.serve_forever, daemon=True).start()
(root / "_active_voice.txt").write_text("yukino", encoding="utf-8")
check("busy_voices (一時ロード中) と active を合わせて返す", vt.active_voice_names(root, port=hs.server_address[1]) == {"noa", "hana", "yukino"})
hs.shutdown()
check("hana が使用中なら削除を拒否", "読み上げ" in (err(vt.move_to_trash, voices, "hana", active_names={"noa", "hana"}) or ""))
(root / "_active_voice.txt").unlink()
check("_active_voice.txt が無いだけなら (daemon 未起動) 続行", vt.active_voice_names(root, port=1, timeout=0.2) == set())
(root / "_active_voice.txt").mkdir()   # 読めない状態 (ファイルでなくフォルダ)
check("_active_voice.txt が読めない時は拒否 (使っていないと誤判定しない)", "確認できませんでした" in (err(vt.active_voice_names, root, port=1, timeout=0.2) or ""))
(root / "_active_voice.txt").rmdir()

print()
print("ALL PASS" if FAIL == 0 else f"{FAIL} FAILED")
sys.exit(1 if FAIL else 0)
