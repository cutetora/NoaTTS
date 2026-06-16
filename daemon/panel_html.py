"""HTTP操作パネル (GET /) のHTML。表示専用の文字列のみ。"""

CONTROL_PANEL_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NoaTTS 読み上げAPI — コントロールパネル</title>
<style>
  :root {
    --bg:#1a1620; --panel:#241d2e; --line:#3a3048; --ink:#ece6f2;
    --muted:#a99cb8; --accent:#d8557a; --accent2:#7a5fd8; --ok:#5fd89a;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font-family:"Yu Gothic UI","Segoe UI",sans-serif; line-height:1.7; }
  .wrap { max-width:860px; margin:0 auto; padding:28px 20px 60px; }
  h1 { font-size:22px; margin:0 0 4px; }
  h1 .sub { font-size:13px; color:var(--muted); font-weight:normal; margin-left:8px; }
  h2 { font-size:15px; margin:28px 0 10px; color:var(--accent);
    border-bottom:1px solid var(--line); padding-bottom:6px; }
  .card { background:var(--panel); border:1px solid var(--line);
    border-radius:12px; padding:18px; margin-top:14px; }
  .status { display:flex; align-items:center; gap:10px; font-size:14px; }
  .dot { width:11px; height:11px; border-radius:50%; background:#777; }
  .dot.on { background:var(--ok); box-shadow:0 0 8px var(--ok); }
  .dot.off { background:var(--accent); }
  textarea { width:100%; min-height:84px; resize:vertical; background:#181320;
    color:var(--ink); border:1px solid var(--line); border-radius:8px;
    padding:10px 12px; font-size:15px; font-family:inherit; }
  .row { display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }
  button { cursor:pointer; border:none; border-radius:8px; padding:10px 18px;
    font-size:14px; font-weight:600; color:#fff; transition:filter .15s; }
  button:hover { filter:brightness(1.12); }
  button:active { filter:brightness(.92); }
  .btn-say { background:linear-gradient(135deg,var(--accent),var(--accent2)); }
  .btn-stop { background:#4a4356; }
  .btn-test { background:#3a3048; }
  .msg { margin-top:10px; font-size:13px; min-height:18px; color:var(--muted); }
  code, pre { font-family:"Cascadia Code","Consolas",monospace; }
  pre { background:#141019; border:1px solid var(--line); border-radius:8px;
    padding:12px 14px; overflow-x:auto; font-size:13px; color:#d7cce6; margin:8px 0; }
  code.inline { background:#141019; padding:2px 6px; border-radius:4px;
    font-size:13px; color:var(--accent); }
  .copy { float:right; font-size:11px; padding:3px 9px; background:#332a42;
    border-radius:5px; cursor:pointer; color:var(--muted); }
  .copy:hover { color:var(--ink); }
  table { width:100%; border-collapse:collapse; font-size:13px; margin-top:6px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line);
    vertical-align:top; }
  th { color:var(--muted); font-weight:600; white-space:nowrap; }
  td code { color:var(--accent); }
  .muted { color:var(--muted); font-size:12.5px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>NoaTTS 読み上げAPI<span class="sub">コントロールパネル</span></h1>
  <div class="muted">別の開発・スクリプト・ブラウザから文を投げると、選択中のボイスで読み上げます。</div>

  <div class="card">
    <div class="status">
      <span class="dot" id="dot"></span>
      <span id="statustext">状態を確認中…</span>
    </div>
  </div>

  <h2>テスト送信</h2>
  <div class="card">
    <textarea id="text" placeholder="読み上げさせたい文を入力…（例: ビルドが完了しました）"></textarea>
    <div class="row">
      <button class="btn-say" onclick="say()">読み上げる</button>
      <button class="btn-stop" onclick="stop()">中断</button>
      <button class="btn-test" onclick="testPhrase()">サンプル文を入れる</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>

  <h2>使い方 — 別の開発から叩く</h2>
  <div class="card">
    <p class="muted">開発タスクの末尾（ビルド成功・テスト完了・デプロイ完了など）に一行足すだけ。</p>

    <p><b>curl (bash / Git Bash):</b></p>
    <pre><span class="copy" onclick="cp(this)">copy</span>curl -X POST http://127.0.0.1:__PORT__/say -d "ビルドが完了しました"</pre>

    <p><b>PowerShell:</b></p>
    <pre><span class="copy" onclick="cp(this)">copy</span>Invoke-RestMethod -Uri http://127.0.0.1:__PORT__/say -Method Post -Body "テストが全て通りました"</pre>

    <p><b>JSON で送る場合:</b></p>
    <pre><span class="copy" onclick="cp(this)">copy</span>curl -X POST http://127.0.0.1:__PORT__/say -H "Content-Type: application/json" -d "{\\"text\\": \\"デプロイが完了しました\\"}"</pre>

    <p><b>Python から:</b></p>
    <pre><span class="copy" onclick="cp(this)">copy</span>import urllib.request
urllib.request.urlopen("http://127.0.0.1:__PORT__/say",
    data="処理が完了しました".encode("utf-8"))</pre>
  </div>

  <h2>エンドポイント一覧</h2>
  <div class="card">
    <table>
      <tr><th>メソッド</th><th>パス</th><th>説明</th></tr>
      <tr><td><code>POST</code></td><td><code>/say</code></td><td>本文(プレーン or JSON <code>{"text"}</code>)を読み上げ。トグルOFFでも必ず読む</td></tr>
      <tr><td><code>POST</code></td><td><code>/stop</code></td><td>現在の読み上げを中断</td></tr>
      <tr><td><code>GET</code></td><td><code>/health</code></td><td>生存確認。JSON <code>{"ok":true,...}</code> を返す</td></tr>
      <tr><td><code>GET</code></td><td><code>/</code></td><td>この操作パネル画面</td></tr>
    </table>
    <p class="muted" style="margin-top:12px;">※ 絵文字・マークダウン記号(<code>**</code> 等)・コードブロックは送っても自動除去されます。</p>
  </div>
</div>

<script>
const PORT = __PORT__;
const base = "http://127.0.0.1:" + PORT;

async function refresh() {
  const dot = document.getElementById("dot");
  const st = document.getElementById("statustext");
  try {
    const r = await fetch(base + "/health");
    const j = await r.json();
    dot.className = "dot on";
    st.textContent = "稼働中 — ボイス: " + (j.voice || "?") + " / ポート " + PORT
      + (j.speaking ? " (読み上げ中)" : "");
  } catch (e) {
    dot.className = "dot off";
    st.textContent = "daemon に接続できません (停止中?)";
  }
}

async function say() {
  const t = document.getElementById("text").value.trim();
  const msg = document.getElementById("msg");
  if (!t) { msg.textContent = "文を入力してくださいませ。"; return; }
  msg.textContent = "送信中…";
  try {
    const r = await fetch(base + "/say", { method:"POST",
      headers:{"Content-Type":"text/plain; charset=utf-8"}, body:t });
    const j = await r.json();
    msg.textContent = j.ok ? ("読み上げ開始 (" + j.chars + "字)") : ("エラー: " + (j.error||""));
  } catch (e) { msg.textContent = "送信失敗: " + e; }
  refresh();
}

async function stop() {
  const msg = document.getElementById("msg");
  try { await fetch(base + "/stop", { method:"POST" }); msg.textContent = "中断しました。"; }
  catch (e) { msg.textContent = "中断失敗: " + e; }
  refresh();
}

function testPhrase() {
  document.getElementById("text").value = "これはテスト送信です。音声が聞こえていますか？";
}

function cp(el) {
  const pre = el.parentNode;
  const txt = pre.textContent.replace(/^copy/, "");
  navigator.clipboard.writeText(txt.trim());
  el.textContent = "copied"; setTimeout(()=>el.textContent="copy", 1200);
}

refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""
