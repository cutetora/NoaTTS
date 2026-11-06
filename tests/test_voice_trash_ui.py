"""読み上げ設定ウィンドウの「ボイスの整理」カードの画面テスト。

tts_api_window.py の HTML を取り出し、スタブの window.api を差してヘッドレス Chrome で動かす
(pywebview は Chromium 系の WebView2 なので描画は同じ)。Chrome / Edge が無い環境ではスキップ。
実行: python tests/test_voice_trash_ui.py [スクリーンショットの保存先.png]
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
browser = next((c for c in CANDIDATES if os.path.exists(c)), None)
if not browser:
    print("SKIP: Chrome / Edge が見つかりません")
    sys.exit(0)

src = (_ROOT / "tts_api_window.py").read_text(encoding="utf-8")
html = re.search(r'HTML = r"""(.*?)"""', src, re.S).group(1).replace("__EMOJI_PALETTE__", "")

# ── スタブの api (本物の Api と同じ戻り値の形) ──
STUB = r"""
<script>
window.__calls = [];
function __fail(m){ if(document.getElementById('probe')) return; const d=document.createElement('pre'); d.id='probe'; d.textContent=JSON.stringify({__error:String(m)}); document.body.appendChild(d); }
window.addEventListener('error', e => __fail(e.message + ' @' + e.lineno));
window.addEventListener('unhandledrejection', e => __fail('reject: ' + (e.reason && e.reason.stack || e.reason)));
const ROWS = [
  {name:'noa', type:'clone', last_used:'2026-11-06 10:00:00', protected:true, active:false, reason:'protected'},
  {name:'yukino', type:'clone', last_used:'2026-11-06 09:00:00', protected:false, active:true, reason:'active'},
  {name:'花子_clone', type:'clone', last_used:'', protected:false, active:false, reason:''},
  {name:'hana', type:'design', last_used:'2026-10-12 08:00:00', protected:false, active:false, reason:''},
  {name:'<img src=x onerror=window.__xss=1>', type:'custom', last_used:'', protected:false, active:false, reason:''},
];
let TRASH = [
  {entry:'gket5__20261020-000000', name:'gket5', deleted_at:'2026-10-20', days_left:13},
  {entry:'vket2__20261009-000000', name:'vket2', deleted_at:'2026-10-09', days_left:2},
];
window.api = {
  status: async()=>({running:true, voice:'yukino', speed:1, auto:false, speaking:false, model:null}),
  voices: async()=>({ok:true, voices:['noa','yukino','hana'], active:'yukino'}),
  models: async()=>({ok:true, models:[]}),
  vram: async()=>({ok:false}),
  copy: async()=>({ok:true}),
  manage_list: async()=>({ok:true, rows:ROWS.slice(), trash:TRASH.slice(), active_unknown:false, retention_days:30}),
  trash_voice: async(n)=>{ window.__calls.push(['trash_voice', n]);
    if (n==='yukino') return {ok:false, error:'「yukino」は現在、読み上げに使っています。'};
    const i = ROWS.findIndex(r=>r.name===n); if (i>=0) { const r = ROWS.splice(i,1)[0];
      TRASH.unshift({entry:n+'__20261106-120000', name:n, deleted_at:'2026-11-06', days_left:30}); }
    return {ok:true, name:n, entry:n+'__20261106-120000', retention_days:30}; },
  trash_restore: async(e)=>{ window.__calls.push(['trash_restore', e]);
    const i = TRASH.findIndex(t=>t.entry===e); const t = TRASH.splice(i,1)[0];
    ROWS.push({name:t.name, type:'design', last_used:'', protected:false, active:false, reason:''});
    return {ok:true, restored:t.name, renamed:false}; },
  trash_open: async()=>{ window.__calls.push(['trash_open']); return {ok:true}; },
};
window.pywebview = {api: window.api};   // 本物は pywebview が注入する。ページ側の init() がこれを拾う
</script>
"""

# ── 操作と検証 (ページ内で実行し、結果を JSON で返す) ──
PROBE = r"""
<script>
const sleep = ms => new Promise(r => setTimeout(r, ms));
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
window.addEventListener('load', async () => {
  const out = {};
  await sleep(400);
  out.initiallyClosed = !$('#mg').open;
  out.headerCount = $('#mgcnt').textContent;
  out.warnShown = $('#mgwarn').style.display !== 'none' && $('#mgwarn').textContent;
  $('#mg').open = true; await sleep(300);
  out.arrow = $('#mgarrow').textContent;
  const rows = $$('#mgVlist .mgrow');
  out.rowCount = rows.length;
  const byName = {}; rows.forEach(r => { byName[r.querySelector('.n').textContent] = r; });
  out.noaLockedDisabled = byName['noa'].querySelector('button').disabled && /同梱/.test(byName['noa'].textContent);
  out.activeDisabled = byName['yukino'].querySelector('button').disabled && /読み上げ中/.test(byName['yukino'].textContent);
  out.normalEnabled = !byName['hana'].querySelector('button').disabled;
  out.noXss = !window.__xss && !!byName['<img src=x onerror=window.__xss=1>'];
  // 絞り込み
  $('#mgq').value = 'han'; $('#mgq').dispatchEvent(new Event('input')); await sleep(50);
  out.filter = $$('#mgVlist .mgrow .n').map(e => e.textContent);
  $('#mgq').value = ''; $('#mgq').dispatchEvent(new Event('input')); await sleep(50);
  // 削除: モーダルの既定はキャンセル、Esc で閉じて何も呼ばれない
  byName['hana'] = $$('#mgVlist .mgrow').find(r => r.querySelector('.n').textContent === 'hana');
  byName['hana'].querySelector('button').click(); await sleep(100);
  out.modalOpen = !!$('#modal');
  out.defaultFocus = document.activeElement && document.activeElement.textContent;
  out.modalText = $('#modal') && $('#modal').textContent;
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); await sleep(50);
  out.escClosed = !$('#modal');
  out.callsAfterEsc = window.__calls.length;
  // 削除を確定
  byName['hana'].querySelector('button').click(); await sleep(100);
  Array.from($('#modal').querySelectorAll('button')).find(b => b.textContent === 'ゴミ箱へ移動').click(); await sleep(400);
  out.trashCalled = JSON.stringify(window.__calls.filter(c => c[0] === 'trash_voice'));
  out.afterCount = $('#mgcnt').textContent;
  out.note = $('#mgmsg').textContent;
  // ゴミ箱タブと復元
  mgTab('t'); await sleep(50);
  out.trashRows = $$('#mgTlist .mgrow').map(r => r.querySelector('.n').textContent);
  out.soonChipRed = !!$('#mgTlist .chip.red');
  const gk = $$('#mgTlist .mgrow').find(r => r.querySelector('.n').textContent === 'gket5');
  gk.querySelector('button').click(); await sleep(400);
  out.restoreCalled = JSON.stringify(window.__calls.filter(c => c[0] === 'trash_restore'));
  out.restoreNote = $('#mgmsg').textContent;
  $$('#paneT button').find(b => b.textContent.includes('ゴミ箱フォルダ')).click(); await sleep(50);
  out.openCalled = window.__calls.some(c => c[0] === 'trash_open');
  // 拒否 (直前に状況が変わった想定): daemon 側が拒否 → エラーのモーダル
  mgTab('v'); await sleep(50);
  await mgDoTrash('yukino'); await sleep(100);
  out.refuseModal = $('#modal') && $('#modal').textContent;
  closeModal();
  const d = document.createElement('pre'); d.id = 'probe'; d.textContent = JSON.stringify(out); document.body.appendChild(d);
});
</script>
"""

tmp = Path(tempfile.mkdtemp(prefix="noa_ui_"))
page = tmp / "probe.html"
page.write_text(html.replace("<body>", "<body>" + STUB, 1).replace("</body>", PROBE + "</body>"), encoding="utf-8")


def run(args):
    return subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                           *args], capture_output=True, timeout=120)


res = run(["--window-size=720,2200", "--virtual-time-budget=6000", "--dump-dom", page.as_uri()])
m = re.search(r'<pre id="probe">(.*?)</pre>', res.stdout.decode("utf-8", "replace"), re.S)
if not m:
    print("FAIL: 画面の確認が最後まで動きませんでした")
    print(res.stdout.decode("utf-8", "replace")[-600:])
    sys.exit(1)
import html as _html
o = json.loads(_html.unescape(m.group(1)))
if "__error" in o:
    print("FAIL: ページ内でエラー:", o["__error"])
    sys.exit(1)

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")


check("初期は閉じている (折りたたみ)", o["initiallyClosed"] is True)
check("閉じていても見出しに件数が出る", o["headerCount"] == "ボイス 5 ／ ゴミ箱 2", o["headerCount"])
check("期限間近の警告が見出しに出る", "あと2日以内" in (o["warnShown"] or ""), str(o["warnShown"]))
check("開くと矢印が ▾", o["arrow"] == "▾")
check("一覧にボイスが並ぶ", o["rowCount"] == 5, str(o["rowCount"]))
check("同梱は 🗑 が押せず理由が出る", o["noaLockedDisabled"] is True)
check("読み上げ中は 🗑 が押せず理由が出る", o["activeDisabled"] is True)
check("通常のボイスは 🗑 が押せる", o["normalEnabled"] is True)
check("名前に HTML を含んでも実行されない (textContent 描画)", o["noXss"] is True)
check("名前で絞り込める", o["filter"] == ["hana"], str(o["filter"]))
check("削除でモーダルが開き、既定フォーカスは「キャンセル」", o["modalOpen"] and o["defaultFocus"] == "キャンセル", str(o["defaultFocus"]))
check("モーダルに保管日数と完全削除の案内がある", "30日" in (o["modalText"] or "") and "ゴミ箱" in (o["modalText"] or ""))
check("Esc で閉じ、何も削除されない", o["escClosed"] and o["callsAfterEsc"] == 0)
check("確定すると trash_voice が名前つきで呼ばれる", o["trashCalled"] == '[["trash_voice","hana"]]', o["trashCalled"])
check("削除後に件数が更新され、案内が出る", o["afterCount"] == "ボイス 4 ／ ゴミ箱 3" and "ゴミ箱へ移動しました" in o["note"], f'{o["afterCount"]} / {o["note"]}')
check("ゴミ箱タブに一覧が出る (新しい順)", o["trashRows"] == ["hana", "gket5", "vket2"], str(o["trashRows"]))
check("残り2日は赤いチップ", o["soonChipRed"] is True)
check("元に戻すで trash_restore が項目名つきで呼ばれる", o["restoreCalled"] == '[["trash_restore","gket5__20261020-000000"]]', o["restoreCalled"])
check("戻した案内が出る", "元に戻しました" in o["restoreNote"], o["restoreNote"])
check("ゴミ箱フォルダを開く", o["openCalled"] is True)
check("拒否された時はエラーのモーダルが出る", "読み上げに使っています" in (o["refuseModal"] or ""), str(o["refuseModal"]))

# スクリーンショット (引数があれば)。開いた状態で撮る
if len(sys.argv) > 1:
    shot_page = tmp / "shot.html"
    shot_page.write_text(html.replace("<body>", "<body>" + STUB, 1).replace(
        "</body>", "<script>addEventListener('load',()=>{setTimeout(()=>{document.getElementById('mg').open=true;},300)})</script></body>"),
        encoding="utf-8")
    run(["--window-size=720,1500", "--force-device-scale-factor=1", "--virtual-time-budget=4000",
         f"--screenshot={sys.argv[1]}", shot_page.as_uri()])
    print("screenshot:", sys.argv[1])

print()
print("ALL PASS" if FAIL == 0 else f"{FAIL} FAILED")
sys.exit(1 if FAIL else 0)
