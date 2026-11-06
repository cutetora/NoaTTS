# 落とし穴メモ（後から直すと作り直しになる箇所）

## ボイスの削除とゴミ箱（`voice/voice_trash.py`）

- **フォルダ名の形式 `名前__YYYYmmdd-HHMMSS` は固定。** 30日の起算はこの日時で数える（mtime は復元やコピーで変わる）。
  形式を変えると、古い項目は「解釈できないので触らない」扱いになり、自動では消えなくなる（安全側だが残り続ける）。
- **ゴミ箱は `voices/` の外（`voices_trash/`）。** 中に置くと `GET /voices`・各 UI の一覧・`list_voices` に出てしまう。
  プロジェクトの中なので、フォルダの入れ直しや `git clean -fdx` で消える（README に明記）。`.gitignore` に入れてある。
- **ボイス一覧とカードの読み書きはフォルダ名ではなく `config.json` の `name` を使う**（`VoiceManager.list_voices` / `save_voice`）。
  復元で「名前_復元」に改名する時は、`config.json`（と `config.default.json`）の `name` も書き換える。
  そうしないと一覧に同名が2つ並び、どちらも元のカードを開く。
- **「読み上げ中」の判定は、判定できなければ拒否にする。** daemon のポートが開いているのに `/health` が読めない時
  （合成中で応答が遅い等）に「使っていない」と扱うと、使用中のボイスを消してしまう。`_active_voice.txt` との和集合で見る。
  `/say_wav`・`/v1`・掛け合い（`voice` 指定）が一時ロードして使っている別ボイスは `voice_name` を変えないので、
  `/health` の `voice` には出ない。そのため worker が使用中の声を `busy_voices` として `/health` に出し、整理側はそれも拒否の対象にする。
  `_active_voice.txt` は「ファイルが無い」時だけ無視し、読めない理由が別なら拒否する。
- **削除の対象はフォルダ名の完全一致で探す。** 名前の前後の空白は削らず拒否する（`strip` すると `" 花子"` が `"花子"` を指す）。
  大文字小文字の無視は、読み上げ中の照合と、復元時の同名チェックだけに使う。移動元がリンクのものは入れない（戻せず消えもしなくなるため）。
- **同梱判定は「名前が noa/man」または「`config.default.json` を持つ」の和集合。** 後者はフォルダごと複製したものも消せなくなる（消せない側に倒している）。
- **削除は daemon の HTTP を使わず、設定ウィンドウ（pywebview の Python 側）が直接ファイルを動かす。**
  daemon の HTTP は `Access-Control-Allow-Origin: *` なので、削除用のエンドポイントを足すと外部ページから叩かれる。
  js_api の引数は名前/項目名の文字列だけ。`voice_trash` 側で形式・親ディレクトリ・リンクを検証する。
- **シンボリックリンク／ジャンクションは辿らない。** 完全削除（`rmtree`）と復元で、リンク先の外のフォルダに及ばせない。
- **移動は `os.replace`。** 同じドライブ内の移動なので一瞬だが、Windows ではファイルを開いている間は失敗する（`PermissionError`）。
  失敗したら「使用中の可能性」を返して何も動かさない。これに頼って「使用中」の判定を省かない（Irodori の `.pt` は開きっぱなしにならない）。
- **Voice Studio（Gradio）は別プロセス。** 設定ウィンドウで消しても、Gradio のドロップダウンは再読み込みするまで古い一覧が残る。
  古い一覧のまま操作しても、`load_voice` が失敗するだけで復活はしない（`save_voice_action` は意図的に新規作成する関数）。
- **トレイ起動時の掃除は握りつぶす（失敗しても起動を止めない）。** 掃除はほかに、削除時と整理カードを開いた時にも走る。

## 読み上げ API のオプション（`daemon/api_options.py`）

- `volume` は「以降の読み上げにも続く」仕様（`voice`/`speed`/`caption`/`cache` は「その回だけ」）。README に明記済み。
- `caption` は 省略/`null`=ボイス既定、`""`=感情なし。`cache` の `null` は「指定なし」。クライアントの意味が変わるので、変更時は README の「変わる点」に書く。
- 音声キャッシュのキー（`TTSWorker._cache_path`）は変えない。変えると既存のキャッシュがすべて使われないまま残る。

## インストーラーの更新（`installer.iss` / `installer/stop_app.ps1`）

- **更新で上書きされる＝配布物に入っているファイル。** `ignoreversion` で全部上書きする。利用者が書き換えるファイルを配布物に入れない
  （ボイスの `config.json`、`conf/settings.json`、`gap.txt` 等は実行時に作られるので安全）。配布物に入っていて利用者が追記する
  `conf/reading_dict.json` だけは `onlyifdoesntexist` にしてある（代償: 将来の版で既定の辞書が増えても既存の利用者には届かない）。
- **更新前にアプリを止める。** Inno 標準の「使用中のアプリを閉じる」はウィンドウの無い `pythonw` を閉じられず、無人実行
  （`/VERYSILENT`）では中断してロールバックする。`PrepareToInstall` で `stop_app.ps1` を呼ぶ。止める対象はインストール先配下の
  プロセスだけで、別の場所（開発フォルダなど）の daemon には `/quit` を送らない。
- **`requirements.txt` が変わった更新では、`installer/update_deps.py` が `pip install -r` を走らせる。** `site-packages	orch` がある環境だけ。
  torch が無い環境で入れると CPU 版の torch が入って動かなくなる。さらに torch / torchaudio / torchvision は「今入っている版」に
  固定して（`-c`）実行するので、要求が食い違うと置き換わらずに pip が失敗して止まる（CUDA 版は守られる）。
  最後に入れ終えた `requirements.txt` のハッシュを `python\.req_sha256` に持ち、成功したときだけ書き換える（失敗した更新は、
  インストーラーを再実行すると再試行される）。印が無い環境は、上書き前の `requirements.txt` のハッシュを印にする。
  失敗しても `/VERYSILENT` の終了コードは 0 のまま（ログと、画面付きの場合のメッセージで知らせる）。
  `NoaTTS.exe`（PyInstaller 製）は依存の変化を見ないので、ZIP を上書き展開して更新する人には効かない。
- **`stop_app.ps1` はプロセスツリーごと止めない。** インストール先配下の実行ファイルだけを `Stop-Process` する（アプリが開いた
  ブラウザなど、利用者のプログラムを巻き込まないため）。インストール先が浅い場所（`D:\` など）や、`python\python.exe` と
  `NoaTTS.exe` が無いフォルダのときは何も止めない。
- ローカルで `build_portable.bat` を回すと、手元の `voices\` が丸ごと配布物に入る（CI は Git 管理分の `noa` / `man` だけ）。
  その配布物でインストーラーを作ると、開発用のボイスや `config.json` が入る。リリースは CI のビルドで行う。
- アンインストールは `python\` 配下（初回セットアップで入った torch 等）を消さない。Inno は自分が入れたファイルしか消さないため。
- `.iss` は日本語を含むので UTF-8 の BOM が要る（無いと文字化けする）。
