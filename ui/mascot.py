"""NoaTTS マスコット「ノア」表示モジュール。

app.py から分離。画面右上に固定表示するマスコット(表情差分+口パク+吹き出し)の
HTML/CSS/JS と会話台本、アプリ全体のコンテナCSS。ロジックは持たず、表示用の文字列を
組み立てて返すだけ。app.py が _mascot_head_html()/_mascot_js()/_APP_CSS を使う。
"""
from pathlib import Path


# マスコット「ノア」の会話台本。明るく楽しい「〜ですよー」口調。
# 各セリフ = {"t": テキスト, "f": 表情名(assets/noa/face_*.png の *)}。
# 表情: normal/nikkori/majime/komari/okori/naki/odoroki/tere/doya/jito
_NOA_SCRIPTS = {
    # 各ステップ: t=セリフ, f=表情, target=注目させる要素のelem_id(任意),
    #            click=スクロール時にクリックする要素(タブを開く用・任意)
    "intro": [
        {"t": "やっほー！ わたしノア、NoaTTSの読み上げサポート担当ですよー。このアプリで何ができるか、ぜんぶざっくり紹介しちゃいますねっ", "f": "nikkori"},
        {"t": "NoaTTSは、テキストを入れると好きな声で読み上げてくれる、ローカルで動く日本語の音声合成アプリですよー。声は何個でも作って保存できちゃいます", "f": "normal"},
        {"t": "画面は大きく3つのタブに分かれてますっ。「ボイス作成」「セリフ一括生成」「設定」ですよー。順番に説明しますねっ", "f": "doya"},
        {"t": "まず「ボイス作成」タブ。声の作り方は3種類ありますよー。内蔵スピーカーから選ぶ「カスタムボイス」、声の特徴を文章で書いて作る「ボイスデザイン」、そしてお手本の音声をマネする「ボイスクローン」ですっ", "f": "normal", "target": "tut-tab-create"},
        {"t": "作った声は下の「保存済みボイス調整」で、シードや話速を微調整したり試聴したりできますよー。ここが声の管理場所ですっ", "f": "normal"},
        {"t": "新機能ですよー！ 文章に感情の絵文字を入れると、声に感情が乗るんですっ。泣きマークで泣きながら、怒りマークで怒りながら。重ねると強くなりますよー", "f": "doya"},
        {"t": "つぎは「セリフ一括生成」タブ。これは台本のエクセルを読み込んで、キャラごとに声を割り当てて、まとめて音声化できる機能ですっ。動画やゲームのセリフ作りにぴったりですよー", "f": "majime"},
        {"t": "「設定」タブでは、読み上げAIのエンジンを切り替えられますよー。多言語対応のQwen3と、日本語が得意でクローン品質の高いIrodori、2つから選べますっ", "f": "normal"},
        {"t": "あと、作った声で気軽に読み上げたいときは、画面右下トレイの「読み上げ設定」ウィンドウが便利ですよー。テスト読み上げや、他のアプリからの読み上げもできちゃいます", "f": "normal"},
        {"t": "もっと詳しく知りたいときは、わたしの吹き出しの上にある「使い方」ボタンを押してみてくださいっ。いろんな案内メニューが開きますよー", "f": "doya"},
        {"t": "「使い方」を押すと、この『かんたん紹介』のほかに、『ボイスクローン』の作り方、『セリフ一括生成』の使い方、『読み上げ設定』の使い方が選べますよー。知りたいものを選んでくださいねっ", "f": "nikkori"},
        {"t": "それと、わたしの隣には「ヘルプ」と「応援」ボタンもありますっ。困ったらヘルプ、頑張りたいときは応援を呼んでくださいねー。それじゃ、いい声づくり、はじめましょっ！", "f": "tere"},
    ],
    "voiceclone": [
        {"t": "ボイスクローンの作り方を、いっこずつ丁寧に案内しちゃいますねっ", "f": "nikkori"},
        {"t": "ステップ1ですよー。まずは画面の上のほうにある「ボイス作成」タブをクリックしてくださいねっ。この光ってるタブですよー", "f": "normal", "click": "ボイス作成"},
        {"t": "ステップ2。「ボイス作成」の中に「C. ボイスクローン」っていうタブがあるので、それを開いてくださいねー。この光ってるところですっ", "f": "normal", "click": "C. ボイスクローン"},
        {"t": "ステップ3ですよー。この「参照音声」のところに、マネしたい声の音声ファイルを入れてくださいっ。3秒から10秒くらいがちょうどいいですよー", "f": "majime", "target": "tut-ref-audio", "click": "C. ボイスクローン"},
        {"t": "ステップ4。さっき入れた音声で、なんて喋ってるかを「書き起こし」のところに文字で書いてくださいねっ。これ大事なやつですよー", "f": "majime", "target": "tut-ref-text", "click": "C. ボイスクローン"},
        {"t": "ステップ5ですよー。準備ができたら、この「クローン生成」ボタンをポチッと押してくださいっ。わくわくの瞬間ですねー", "f": "doya", "target": "tut-gen-btn", "click": "C. ボイスクローン"},
        {"t": "ステップ6。生成できたら、ここで声を試聴できますよー。どうですか、いい感じにマネできてます？ ふふっ", "f": "nikkori", "target": "tut-result", "click": "C. ボイスクローン"},
        {"t": "ステップ7。気に入ったら、ここに好きな名前をつけてくださいねー。「ナレーター」とか「ノア」とか、なんでもいいですよーっ", "f": "normal", "target": "tut-save-name", "click": "C. ボイスクローン"},
        {"t": "ステップ8、最後ですよー！ この「保存」ボタンを押せば、君だけの声が保存完了ですっ。お疲れさまでしたー！", "f": "doya", "target": "tut-save-btn", "click": "C. ボイスクローン"},
        {"t": "保存したあとは、下の「保存済みボイス調整」で声を選んで、seedや話速を微調整したり試聴したりできますよー。ここが声の管理場所ですっ", "f": "normal"},
        {"t": "試聴のテスト文に感情の絵文字を入れてみてくださいっ。泣きマークや怒りマークのボタンがあって、押すと文に入りますよー。重ねると感情が強くなるんですっ", "f": "doya"},
        {"t": "これで君も声づくりマスターですねっ。あとは保存した声を選んで、好きな文を読み上げさせるだけですよー。応援してますからねー、ふふっ", "f": "tere"},
    ],
    "cheer": [
        {"t": "いいですねー、その調子その調子っ！ 君のセンス、わたし好きですよー", "f": "nikkori"},
        {"t": "うんうん、こだわって作った声って、やっぱり愛着わきますよねー。最高ですっ", "f": "doya"},
        {"t": "ちょっと休憩も大事ですよー。でも、もうちょっとだけ頑張れちゃう気がしません？ ふふっ", "f": "tere"},
        {"t": "君ならぜったいいいの作れますって。わたしが保証しますよー！", "f": "doya"},
    ],
    # 読み上げ設定(トレイの別ウィンドウ)の案内。img で説明画像を出す。
    "settings": [
        {"t": "読み上げ設定の使い方を案内しますねっ。これは画面右下の、システムトレイから開く別ウィンドウですよー", "f": "majime"},
        {"t": "まず画面のずーっと右下、この指の先っぽ…時計の近くにあるトレイアイコンを右クリックして、「読み上げ設定」を選んでくださいねー。すると、こんなウィンドウが出ますよー", "f": "normal", "img": "settings_hint.png", "pointTray": True},
        {"t": "ちなみにトレイのアイコンは、わたしの顔なんですよーっ。こんなふうに色がついて動いてたら、読み上げが稼働中ですっ！ いつでも喋れる状態ですよー", "f": "doya", "img": "tray_active.png"},
        {"t": "逆に、こんなふうに白黒でzZと寝ちゃってたら、読み上げが停止中ですっ。そのときは設定ウィンドウの「起動」を押して、わたしを起こしてあげてくださいねー", "f": "naki", "img": "tray_idle.png"},
        {"t": "一番上は稼働状態ですっ。緑のマルが出てれば読み上げの準備OKですよー。起動・停止・再起動もここでできます", "f": "normal", "img": "settings_hint.png"},
        {"t": "「ボイスと話速」では、使う声を選んで、話すスピードを変えられますよー。スライダーを右にすると速くなりますっ", "f": "normal", "img": "settings_hint.png"},
        {"t": "「自動読み上げ」をオンにすると、ファイルに書いたテキストを自動で読み上げてくれますよー。普段はオフでいいですっ", "f": "normal", "img": "settings_hint.png"},
        {"t": "「テスト読み上げ」で、文を入れて読み上げるボタンを押せば、その声をすぐ試せますよー。サンプルボタンを押すと例文とランダムな感情が入りますっ", "f": "doya", "img": "settings_hint.png"},
        {"t": "テスト文の下には感情の絵文字ボタンがありますよー。泣きや怒り、震え声なんかを文に入れると、その感情で読み上げてくれるんですっ。重ねると強くなりますよー", "f": "nikkori", "img": "settings_hint.png"},
        {"t": "一番下の「外部から叩く」は上級者向けですっ。他のプログラムから読み上げを呼べる、便利なやつですよー", "f": "normal", "img": "settings_hint.png"},
        {"t": "これで読み上げ設定はバッチリですねっ。いい声で、いっぱい読み上げさせちゃってくださいー、ふふっ", "f": "tere"},
    ],
    # セリフ一括生成タブの案内。台本Excelからまとめて音声化する流れ。
    "batch": [
        {"t": "セリフ一括生成の使い方を案内しますねっ。これは台本をまとめて音声にできる、動画やゲーム作りに便利な機能ですよー", "f": "nikkori"},
        {"t": "まず上の「セリフ一括生成」タブを開いてくださいねっ。この光ってるタブですよー", "f": "normal", "click": "セリフ一括生成"},
        {"t": "ステップ1ですよー。この「① ファイル読み込み」のところで、台本のエクセルかCSVを読み込みますっ。書き方がわからなかったら「テンプレート作成」を押すと、見本ファイルがもらえますよー", "f": "majime", "target": "tut-batch-1", "click": "セリフ一括生成"},
        {"t": "ステップ2。読み込むと、この「② セリフテーブル」に台本が表に並びますっ。ここで直接セリフを直したり、読みが難しいところは「セリフ仮名」に読みを書いたりできますよー", "f": "normal", "target": "tut-batch-2", "click": "セリフ一括生成"},
        {"t": "ステップ3。この「③ キャラ⇔ボイス紐付け」で、台本のキャラクターごとに、どの声で喋らせるか割り当てますっ。キャラを選んでボイスを選んで「割り当て」ですよー", "f": "majime", "target": "tut-batch-3", "click": "セリフ一括生成"},
        {"t": "割り当ては、この「プリセット」で名前をつけて保存できますよー。次に同じ配役を使うとき、読み込むだけで済むので楽ちんですっ", "f": "doya", "target": "tut-batch-preset", "click": "セリフ一括生成"},
        {"t": "ステップ4。準備ができたら、この「④ 一括生成」ですっ。ボタンを押すと、台本の全部のセリフを順番に音声にしてくれますよー。Whisperでセリフ通りに読めてるかチェックもできます", "f": "doya", "target": "tut-batch-4", "click": "セリフ一括生成"},
        {"t": "ステップ5。この「⑤ 生成結果」に、できた音声が一覧で並びますっ。行をクリックすると再生、気に入らなければその行だけ「再生成」もできますよー", "f": "normal", "target": "tut-batch-5", "click": "セリフ一括生成"},
        {"t": "ステップ6。最後にこの「⑥ エクスポート」で、できた音声をぜんぶ書き出せますっ。ファイル名は台本のとおりに付くので、そのまま動画編集に使えますよー", "f": "doya", "target": "tut-batch-6", "click": "セリフ一括生成"},
        {"t": "ちなみにセリフのテキストに感情の絵文字を入れておくと、その感情で読み上げてくれますよー。台本で泣くシーンには泣きマーク、みたいにねっ", "f": "nikkori", "click": "セリフ一括生成"},
        {"t": "これでセリフ一括生成はバッチリですねっ。たくさんのセリフも、いっぺんに声にできちゃいますよー。いい作品づくり、応援してますからねっ！", "f": "tere"},
    ],
    "help": [
        {"t": "ヘルプですねっ。NoaTTSのよくある質問とトラブル解決を、わたしがまとめてお答えしますよー", "f": "majime"},
        {"t": "Q.声を作るには？\nA.「ボイス作成」タブのクローンで、参照音声を入れて生成、が一番かんたんですよー", "f": "normal"},
        {"t": "Q.作った声で読み上げるには？\nA.右下トレイの読み上げ設定でボイスを選んで、テキストを送れば読み上げますっ", "f": "normal"},
        {"t": "Q.声が出ないんだけど？\nA.まず右下トレイの読み上げ設定で、デーモンが動いてるか確認してくださいねー", "f": "komari"},
        {"t": "Q.クローンの声が変になる？\nA.参照音声は雑音の少ない3〜10秒がコツですよー。BGM除去ボタンも使えますっ", "f": "majime"},
        {"t": "Q.それでも調子が悪い？\nA.モデルのアンロードと再ロードを試すと直ることが多いですよー", "f": "normal"},
        {"t": "Q.エンジンって？\nA.Qwen3とIrodori、2つの読み上げAIを切り替えられるんですよー。設定タブで変えられますっ", "f": "normal"},
        {"t": "Q.声に感情を込めるには？\nA.文章に感情の絵文字を入れるのが一番ですよー！ 泣き・怒り・震え声・囁きなんかがあって、重ねると強くなりますっ。Irodoriのクローン声でよく効きますよー", "f": "doya"},
        {"t": "だいたいこれで解決できるはずですっ。他に困ったら、いつでも呼んでくださいねー、ふふっ", "f": "tere"},
    ],
}
# 後方互換 (旧変数名)
_TUTORIAL_LINES = [s["t"] for s in _NOA_SCRIPTS["intro"]]


# ヘルプ検索用 Q&A データベース。
# kw=マッチするキーワード(どれか1つでも入力に含まれればヒット)、a=ノアの回答。
# 入力とkwを照合し、最もヒット数の多いQ&Aを返す。ユーザーが聞きそうな質問を網羅。
_FAQ = [
    {"kw": ["声", "作る", "作り方", "クローン", "作成", "ボイス作成"],
     "a": "声を作るなら「ボイス作成」タブですよー！ 一番かんたんなのはクローンで、お手本の音声を3〜10秒入れて「クローン生成」するだけですっ。詳しくは使い方の「ボイスクローン」を見てくださいねー"},
    {"kw": ["クローン", "参照音声", "お手本", "マネ", "似せる"],
     "a": "ボイスクローンは、マネしたい声の音声を「参照音声」に入れて、その内容を「書き起こし」に書いて生成しますよー。雑音の少ない3〜10秒がコツですっ。BGMがあれば「BGM除去」ボタンも使えます"},
    {"kw": ["読み上げ", "喋らせ", "しゃべら", "再生", "音声にする"],
     "a": "作った声で読み上げるには、画面右下トレイの「読み上げ設定」を開いて、ボイスを選んでテスト読み上げに文を入れますよー。または「セリフ一括生成」で台本ごとまとめて音声にもできますっ"},
    {"kw": ["感情", "泣", "怒", "気持ち", "演技", "悲し", "嬉し", "絵文字"],
     "a": "声に感情を込めるなら、文章に感情の絵文字を入れるのが一番ですよー！ 泣きマークや怒りマーク、震え声なんかのボタンがあって、文に入れるとその感情で読み上げますっ。重ねると強くなりますよー"},
    {"kw": ["出ない", "聞こえ", "音が", "無音", "鳴らない", "再生されない"],
     "a": "声が出ないときは、まず右下トレイの「読み上げ設定」で、稼働状態が緑のマルか確認してくださいねー。赤や白黒なら「起動」を押してくださいっ。それでもダメなら音量やデバイスも確認を"},
    {"kw": ["停止", "止ま", "動いてない", "起動", "立ち上が", "サーバー"],
     "a": "読み上げが動いてるかは、トレイのアイコンで分かりますよー。色がついて動いてたら稼働中、白黒でzZと寝てたら停止中ですっ。停止中は「読み上げ設定」の「起動」ボタンで起こしてくださいねー"},
    {"kw": ["エンジン", "Qwen", "Irodori", "切り替え", "切替", "AIモデル"],
     "a": "エンジンは「設定」タブで切り替えられますよー。Qwen3は多言語対応、Irodoriは日本語が得意でクローン品質が高いですっ。感情の絵文字はIrodoriのクローンでよく効きますよー"},
    {"kw": ["セリフ", "一括", "台本", "まとめて", "大量", "エクセル", "Excel", "CSV"],
     "a": "台本をまとめて音声にするなら「セリフ一括生成」タブですよー！ エクセルを読み込んで、キャラごとに声を割り当てて、一括生成。動画やゲームのセリフ作りにぴったりですっ。テンプレートも作れます"},
    {"kw": ["話速", "速さ", "スピード", "速く", "遅く", "ゆっくり", "早口"],
     "a": "話す速さは2か所で変えられますよー。トレイの「読み上げ設定」の話速スライダーか、ボイス調整の「話速」ですっ。文に早口やゆっくりの絵文字を入れる手もありますよー"},
    {"kw": ["seed", "シード", "声が変わる", "声が毎回", "安定", "毎回違う", "毎回変わる", "ばらつき", "一貫"],
     "a": "クローンの声が毎回変わるときは、シードを固定すると安定しますよー。ボイス調整でseedを決めて「5シード探索」で良いのを探せますっ。気に入ったら「設定をカードに保存」してくださいねー"},
    {"kw": ["保存", "削除", "消す", "一覧", "管理", "名前"],
     "a": "作った声は「保存済みボイス調整」で管理しますよー。選んで試聴したり、話速やseedを調整したり、いらない声は「削除」もできますっ。トレイアイコンの画像もここで設定できますよー"},
    {"kw": ["BGM", "雑音", "ノイズ", "背景音", "音楽"],
     "a": "参照音声にBGMや雑音があるときは、ボイスクローンの「BGM除去」ボタンを押すと、声だけ取り出してくれますよー。きれいな声でクローンしたほうが、似た声になりますっ"},
    {"kw": ["読み", "誤読", "読み方", "間違", "仮名", "ふりがな"],
     "a": "読み方が変なときは、セリフ一括生成なら「セリフ仮名」の欄に正しい読みをひらがなで書けますよー。アプリ全体の読み辞書もあって、よく間違う言葉は登録できますっ"},
    {"kw": ["遅い", "時間がかかる", "重い", "生成が長い"],
     "a": "生成が遅いときは、5シード探索や喜怒哀楽4種など、いっぺんに何個も作るボタンは時間がかかりますよー。1個ずつの「試聴」なら速いですっ。モデルの初回ロードも少し待ちますねー"},
    {"kw": ["エラー", "失敗", "動かない", "落ちた", "バグ"],
     "a": "うまくいかないときは、モデルを一度アンロードして再ロードすると直ることが多いですよー。「設定」タブのモデル管理か、読み上げ設定の「再起動」を試してくださいねー"},
    {"kw": ["外部", "API", "他のアプリ", "プログラム", "連携", "コマンド"],
     "a": "他のプログラムから読み上げを呼ぶこともできますよー！ 読み上げ設定の一番下「外部から叩く」に、curlやPythonのサンプルがありますっ。HTTPでテキストを送るだけで読み上げますよー"},
    # --- よくあるエラー系 ---
    {"kw": ["VRAM", "メモリ不足", "out of memory", "OOM", "GPU", "CUDA", "グラボ"],
     "a": "VRAMが足りないとエラーになりますよー。他の重いアプリやブラウザのタブを閉じてみてくださいっ。設定タブの「モデルを退避」で一度VRAMを空けてから、やり直すのも効きますよー"},
    {"kw": ["フリーズ", "固ま", "応答しない", "進まない", "止まったまま"],
     "a": "生成中に固まったように見えても、長い文や複数生成は時間がかかってるだけのことが多いですよー。しばらく待ってもダメなら、読み上げ設定の「再起動」でデーモンを立て直してくださいねー"},
    {"kw": ["ポート", "port", "7860", "7870", "アドレスが使用", "起動できない", "二重起動", "既に使用", "address in use"],
     "a": "ポートが使われてて起動できないときは、前のNoaTTSがまだ動いてるのかもですよー。タスクマネージャでpythonを終了するか、パソコンを再起動してからもう一度試してくださいっ"},
    {"kw": ["ダウンロード", "モデル", "初回", "DL", "落ちてこない", "進まない", "ネット"],
     "a": "初回はモデルをネットからダウンロードするので、時間がかかったり、回線が不安定だと失敗することがありますよー。安定したネットでもう一度起動すると、続きから取得してくれますっ"},
    {"kw": ["参照音声", "読み込めない", "wav", "mp3", "ファイル形式", "対応してない"],
     "a": "参照音声が読み込めないときは、ファイル形式を確認してくださいねー。wavが一番確実ですっ。長すぎる音声もうまくいかないことがあるので、3〜10秒くらいに切ってから入れてみてくださいー"},
    {"kw": ["文字化け", "変な音", "ノイズ", "壊れた", "ガビガビ", "おかしな音"],
     "a": "音が壊れたりノイズが乗るときは、参照音声の品質が原因のことが多いですよー。雑音の少ないきれいな音声を使って、BGM除去もかけてみてくださいっ。seedを変えると改善することもありますよー"},
    {"kw": ["長い", "音声が長すぎ", "余計", "繰り返し", "同じこと", "ループ"],
     "a": "音声が長すぎたり同じ言葉を繰り返すときは、セリフが短いのに指示が長いと起きやすいですよー。一括生成なら自動でリトライしてくれますっ。指示を短くするか、絵文字での感情指定に切り替えるのも手ですよー"},
    {"kw": ["インストール", "起動しない", "exe", "立ち上がらない", "依存", "ライブラリ", "pip"],
     "a": "起動しないときは、必要なライブラリが入ってない可能性がありますよー。requirements.txtでインストールし直してくださいっ。PyTorchはお使いのGPUに合わせて別に入れる必要がありますよー"},
    {"kw": ["遅延", "もたつく", "反応が遅い", "ワンテンポ"],
     "a": "最初の1回はモデルをVRAMに読み込むので待ちますが、2回目以降は速くなりますよー。準備完了の緑マルが出てから使うと快適ですっ。それでも遅いなら、生成数を減らしてみてくださいねー"},
]


def _mascot_head_html() -> str:
    """右上固定のノア(表情差分+口パク) + LINE風吹き出し + 会話JS を返す。
    head に注入され、Gradioのレイアウト外で position:fixed 表示する。
    表情画像は base64 で全種埋め込む。"""
    import base64 as _b64
    import json as _json
    noa_dir = Path(__file__).parent / "assets" / "noa"

    def _b64img(p: Path) -> str:
        if p.exists():
            return "data:image/png;base64," + _b64.b64encode(p.read_bytes()).decode("ascii")
        return ""

    # 表情10種 + 口パク5種を base64 辞書に
    faces = {}
    for name in ["normal", "nikkori", "majime", "komari", "okori",
                 "naki", "odoroki", "tere", "doya", "jito", "doya2"]:
        faces[name] = _b64img(noa_dir / f"face_{name}.png")
    mouths = {}
    for name in ["A", "I", "U", "E", "O"]:
        mouths[name] = _b64img(noa_dir / f"mouth_{name}.png")
    # フォールバック (分割前の単一画像)
    fallback = _b64img(Path(__file__).parent / "assets" / "mascot.png")
    # 指差し「ココ!」マーカー画像
    point_img = _b64img(noa_dir / "point_here.png")
    # 吹き出しに出す説明画像(設定スクショ・トレイアイコン見本等)
    _assets = Path(__file__).parent / "assets"
    bubble_imgs = {
        "settings_hint.png": _b64img(noa_dir / "settings_hint.png"),
        # トレイアイコン見本: 色付き(稼働中)=walk / 白黒+zZ(停止中)=idle
        "tray_active.png": _b64img(_assets / "walk" / "frame_00.png"),
        "tray_idle.png": _b64img(_assets / "idle.png"),
    }

    bubble_imgs_js = _json.dumps(bubble_imgs, ensure_ascii=False)
    faces_js = _json.dumps(faces, ensure_ascii=False)
    mouths_js = _json.dumps(mouths, ensure_ascii=False)
    scripts_js = _json.dumps(_NOA_SCRIPTS, ensure_ascii=False)
    faq_js = _json.dumps(_FAQ, ensure_ascii=False)
    default_img = faces.get("normal") or fallback

    return f"""
<style>
#noa-fixed {{
  position: fixed; right: 12px; top: 64px; z-index: 2147483600;
  display: flex; flex-direction: row-reverse; align-items: flex-start;
  pointer-events: none;
}}
#noa-img {{
  width: 160px; height: auto; pointer-events: auto;
  filter: drop-shadow(0 4px 10px rgba(0,0,0,.35));
}}
#noa-bubble {{
  pointer-events: auto; max-width: 270px; margin-right: 8px; margin-top: 12px;
  background: #fff; color: #222; border-radius: 16px; padding: 12px 14px;
  font-size: 13.5px; line-height: 1.6; box-shadow: 0 6px 20px rgba(0,0,0,.25);
  position: relative; border: 2px solid #7a5fd8;
}}
#noa-bubble::after {{
  content: ""; position: absolute; right: -10px; top: 26px;
  border: 8px solid transparent; border-left-color: #7a5fd8;
}}
#noa-step {{ font-size: 11px; color: #999; margin-bottom: 3px; }}
#noa-text {{ margin-bottom: 9px; min-height: 38px; white-space: pre-wrap; }}
#noa-menu {{ display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 7px; }}
#noa-menu button {{
  cursor: pointer; border: 1px solid #c9bdf0; border-radius: 999px;
  padding: 3px 10px; font-size: 11.5px; background: #f3effc; color: #5a4aa8;
}}
#noa-menu button.active {{ background: #7a5fd8; color: #fff; border-color: #7a5fd8; }}
#noa-usage-btn {{ cursor: pointer; border: 1px solid #c9bdf0; border-radius: 999px;
  padding: 3px 10px; font-size: 11.5px; background: #f3effc; color: #5a4aa8; }}
#noa-usage-btn.active {{ background: #7a5fd8; color: #fff; border-color: #7a5fd8; }}
#noa-submenu {{ display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 7px;
  padding: 5px; background: #f7f4fd; border-radius: 8px; }}
#noa-submenu button {{ cursor: pointer; border: 1px solid #c9bdf0; border-radius: 999px;
  padding: 3px 9px; font-size: 11px; background: #fff; color: #5a4aa8; }}
#noa-submenu button.active {{ background: #d8557a; color: #fff; border-color: #d8557a; }}
#noa-bubble-img {{ width: 100%; max-height: 320px; object-fit: contain;
  border-radius: 8px; margin-bottom: 8px; border: 1px solid #ddd; }}
/* トレイ方向(画面右下隅)を指す指差し */
#noa-tray-pointer {{ position: fixed; right: 6px; bottom: 6px; z-index: 2147483600;
  display: none; flex-direction: column; align-items: flex-end; pointer-events: none;
  animation: noaTrayBob 1s ease-in-out infinite; }}
#noa-tray-pointer .noa-tp-label {{ background: #d8557a; color: #fff; font-size: 13px;
  font-weight: 700; padding: 4px 10px; border-radius: 10px; margin-bottom: 2px;
  box-shadow: 0 2px 8px rgba(0,0,0,.3); white-space: nowrap; }}
#noa-tray-pointer img {{ width: 90px; transform: rotate(-135deg);
  filter: drop-shadow(0 2px 6px rgba(0,0,0,.4)); }}
@keyframes noaTrayBob {{
  0%,100% {{ transform: translate(0,0); }}
  50% {{ transform: translate(4px,4px); }}
}}
#noa-ctrl {{ display: flex; gap: 6px; }}
#noa-ctrl button {{
  cursor: pointer; border: none; border-radius: 8px; padding: 5px 14px;
  font-size: 12px; font-weight: 600; color: #fff;
}}
#noa-next {{ background: linear-gradient(135deg,#d8557a,#7a5fd8); }}
#noa-prev {{ background: #b0a0d8; }}
#noa-close {{ background: #999; }}
#noa-search {{ display: flex; gap: 5px; margin-bottom: 7px; }}
#noa-search-input {{ flex: 1; border: 1px solid #c9bdf0; border-radius: 8px;
  padding: 4px 8px; font-size: 12px; }}
#noa-search-btn {{ cursor: pointer; border: none; background: #7a5fd8; color: #fff;
  border-radius: 8px; padding: 4px 10px; }}
/* 砂のように消える演出 */
@keyframes noaCrumble {{
  0%   {{ opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }}
  100% {{ opacity: 0; transform: translateY(40px) scale(.9); filter: blur(8px); }}
}}
.noa-crumbling {{ animation: noaCrumble 2.5s ease-in forwards; }}
#noa-audio-ctrl {{ display: flex; align-items: center; gap: 8px; margin-top: 8px; }}
#noa-mute {{ cursor: pointer; border: none; background: #f3effc; border-radius: 8px;
  padding: 3px 8px; font-size: 15px; }}
#noa-mute.off {{ background: #e8e8e8; opacity: .6; }}
#noa-vol {{ flex: 1; accent-color: #7a5fd8; cursor: pointer; }}
#noa-reopen {{
  position: fixed; right: 12px; top: 64px; z-index: 2147483600; width: 70px;
  cursor: pointer; display: none; pointer-events: auto;
  filter: drop-shadow(0 4px 10px rgba(0,0,0,.35));
}}
/* チュートリアルの注目マーカー。要素の上に position:fixed で重ねる
   (要素自体は触らないのでGradioのスタイルと干渉しない)。 */
#noa-marker {{ position: fixed; inset: 0; pointer-events: none; z-index: 99999;
  transition: opacity .2s; }}
/* OFFを阻止して泣いて訴えるノア */
#noa-beg {{ position: absolute; z-index: 2147483600; display: none;
  flex-direction: column; align-items: center; width: 200px; pointer-events: none; }}
#noa-beg img {{ width: 110px; height: auto;
  filter: drop-shadow(0 3px 8px rgba(0,0,0,.4)); animation: noaShake .4s infinite; }}
#noa-beg .noa-beg-bubble {{ background: #fff; color: #222; border: 2px solid #d8557a;
  border-radius: 12px; padding: 8px 11px; font-size: 12px; line-height: 1.5;
  box-shadow: 0 6px 18px rgba(0,0,0,.3); margin-top: 4px; }}
@keyframes noaShake {{
  0%,100% {{ transform: translateX(0); }}
  25% {{ transform: translateX(-3px); }} 75% {{ transform: translateX(3px); }}
}}
#noa-marker .noa-marker-ring {{
  position: fixed; border: 3px solid #ff3d7f; border-radius: 8px;
  box-shadow: 0 0 14px 3px rgba(255,61,127,.8), inset 0 0 10px rgba(255,61,127,.5);
  animation: noaRingPulse 1s ease-in-out infinite; box-sizing: border-box;
}}
#noa-marker .noa-marker-hand {{
  position: fixed; width: 70px; height: auto;
  animation: noaHand .8s ease-in-out infinite;
  filter: drop-shadow(0 2px 5px rgba(0,0,0,.4)); }}
@keyframes noaRingPulse {{
  0%,100% {{ box-shadow: 0 0 10px 2px rgba(255,61,127,.7), inset 0 0 8px rgba(255,61,127,.4); }}
  50%     {{ box-shadow: 0 0 22px 6px rgba(255,61,127,1), inset 0 0 14px rgba(255,61,127,.7); }}
}}
@keyframes noaHand {{
  0%,100% {{ transform: translateX(0); }}
  50%     {{ transform: translateX(-7px); }}
}}
</style>
"""


def _mascot_js() -> str:
    """gr.Blocks(js=) に渡す、ページロード時実行のJS本体。
    head/HTMLに<script>を埋めると Gradio6 がエスケープして実行されない
    ため、正式な js= 経由で渡す。"""
    import base64 as _b64
    import json as _json
    from pathlib import Path as _P
    noa_dir = _P(__file__).parent / "assets" / "noa"
    def _b64img(p):
        return ("data:image/png;base64," + _b64.b64encode(p.read_bytes()).decode("ascii")) if p.exists() else ""
    faces = {n: _b64img(noa_dir / f"face_{n}.png") for n in ["normal","nikkori","majime","komari","okori","naki","odoroki","tere","doya","jito","doya2"]}
    mouths = {n: _b64img(noa_dir / f"mouth_{n}.png") for n in ["A","I","U","E","O"]}
    fallback = _b64img(_P(__file__).parent / "assets" / "mascot.png")
    point_img = _b64img(noa_dir / "point_here.png")
    bubble_imgs = {"settings_hint.png": _b64img(noa_dir / "settings_hint.png")}
    bubble_imgs_js = _json.dumps(bubble_imgs, ensure_ascii=False)
    faces_js = _json.dumps(faces, ensure_ascii=False)
    mouths_js = _json.dumps(mouths, ensure_ascii=False)
    scripts_js = _json.dumps(_NOA_SCRIPTS, ensure_ascii=False)
    faq_js = _json.dumps(_FAQ, ensure_ascii=False)
    default_img = faces.get("normal") or fallback
    return f"""
() => {{
  const FACES = {faces_js};
  const MOUTHS = {mouths_js};
  const SCRIPTS = {scripts_js};
  const FAQ = {faq_js};
  const BUBBLE_IMGS = {bubble_imgs_js};
  const TRAY_POINT_IMG = "{point_img}";  // トレイ方向を指す指差し画像
  const DEFAULT_IMG = "{default_img}";
  const TTS_URL = "http://127.0.0.1:7870/say";
  let mode = "intro", idx = 0, mouthTimer = null;

  // head に書いた <div> はブラウザが無視するため、JSで body に挿入する。
  function injectMascot() {{
    if (document.getElementById("noa-fixed")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div id="noa-fixed">
        <img id="noa-img" src="${{DEFAULT_IMG}}" alt="ノア">
        <div id="noa-bubble">
          <div id="noa-menu">
            <button id="noa-usage-btn">使い方 ▾</button>
            <button data-mode="help">ヘルプ</button>
            <button data-mode="cheer">応援</button>
          </div>
          <div id="noa-submenu" style="display:none;">
            <button data-mode="intro">かんたん紹介</button>
            <button data-mode="voiceclone">ボイスクローン</button>
            <button data-mode="batch">セリフ一括生成</button>
            <button data-mode="settings">読み上げ設定</button>
          </div>
          <div id="noa-search" style="display:none;">
            <input id="noa-search-input" type="text" placeholder="調べたいことを入力…">
            <button id="noa-search-btn">🔍</button>
          </div>
          <div id="noa-step"></div>
          <img id="noa-bubble-img" style="display:none;">
          <div id="noa-text">…</div>
          <div id="noa-ctrl">
            <button id="noa-prev">◀ 前へ</button>
            <button id="noa-next">次へ ▶</button>
            <button id="noa-close">閉じる</button>
          </div>
          <div id="noa-audio-ctrl">
            <button id="noa-mute" title="読み上げ ON/OFF">🔊</button>
            <input id="noa-vol" type="range" min="0" max="100" value="100" title="音量">
          </div>
        </div>
      </div>
      <img id="noa-reopen" src="${{DEFAULT_IMG}}" alt="ノア" title="ノアを呼ぶ">`;
    while (wrap.firstChild) document.body.appendChild(wrap.firstChild);
  }}

  let noaMuted = false;   // 読み上げ ON/OFF
  let noaVolume = 1.0;    // 音量 0.0〜1.0
  // 隠し演出(消す方法)を一度経たか。経るまでは設定でOFFにできない。
  let noaUnlocked = false;
  try {{ noaUnlocked = localStorage.getItem("noaUnlocked") === "1"; }} catch (e) {{}}
  const TTS_STOP = TTS_URL.replace(/\\/say$/, "/stop");  // 停止エンドポイント
  function speak(text) {{
    if (noaMuted) return;  // OFF時は読み上げない
    try {{
      // 今読んでいる読み上げを止めてから新しいのを送る(次の文に送ったら即切替)
      fetch(TTS_STOP, {{ method: "POST" }}).catch(() => {{}});
      fetch(TTS_URL, {{ method: "POST",
        headers: {{ "Content-Type": "application/json; charset=utf-8" }},
        body: JSON.stringify({{ text: text, volume: noaVolume }}) }}).catch(() => {{}});
    }} catch (e) {{}}
  }}

  // 口パク: 喋ってる風に A〜O をランダム切替。一定時間後に表情へ戻す。
  function lipSync(face, durationMs) {{
    const img = document.getElementById("noa-img");
    const keys = Object.keys(MOUTHS).filter(k => MOUTHS[k]);
    if (!keys.length || !img) return;
    let elapsed = 0;
    clearInterval(mouthTimer);
    mouthTimer = setInterval(() => {{
      const k = keys[Math.floor(Math.random() * keys.length)];
      img.src = MOUTHS[k];
      elapsed += 130;
      if (elapsed >= durationMs) {{
        clearInterval(mouthTimer);
        img.src = FACES[face] || MOUTHS["A"];
      }}
    }}, 130);
  }}

  function show(i) {{
    const list = SCRIPTS[mode];
    const t = document.getElementById("noa-text");
    const s = document.getElementById("noa-step");
    const nextBtn = document.getElementById("noa-next");
    const img = document.getElementById("noa-img");
    if (!t || !list) return;
    const line = list[i];
    t.textContent = line.t;  // 表示は改行そのまま(white-space:pre-wrap)
    s.textContent = (i + 1) + " / " + list.length;
    // 表情を固定表示 (口パクはしない: 全体差し替えで揺れて見えるのを防ぐ)
    if (img && FACES[line.f]) img.src = FACES[line.f];
    // 説明画像(img指定があれば吹き出しに出す)
    const bimg = document.getElementById("noa-bubble-img");
    if (bimg) {{
      if (line.img && BUBBLE_IMGS[line.img]) {{
        bimg.src = BUBBLE_IMGS[line.img]; bimg.style.display = "block";
      }} else {{ bimg.style.display = "none"; }}
    }}
    // トレイ方向(画面右下隅)を指差す
    showTrayPointer(!!line.pointTray);
    speak(line.t.replace(/\\n/g, "、"));  // 読み上げは改行を読点に(間を自然に)
    nextBtn.textContent = (i >= list.length - 1) ? "最初から ↺" : "次へ ▶";
    // チュートリアルの操作案内: 対象要素へスクロール+ハイライト、タブは開く
    highlightTarget(line.click, line.target);
  }}

  // ハイライトは要素のクラスをいじらず、上に「マーカー(光るリング+指差し)」を
  // position:fixed で重ねる方式。Gradioのスタイルと干渉せず確実に見える。
  let _hlEl = null;       // 追従対象の要素
  let _hlMarker = null;   // マーカーDOM
  let _hlRaf = null;      // 追従更新ループ
  function clearHighlight() {{
    if (_hlRaf) {{ cancelAnimationFrame(_hlRaf); _hlRaf = null; }}
    if (_hlMarker) {{ _hlMarker.remove(); _hlMarker = null; }}
    _hlEl = null;
  }}
  function _ensureMarker() {{
    if (_hlMarker) return _hlMarker;
    const m = document.createElement("div");
    m.id = "noa-marker";
    m.innerHTML = '<div class="noa-marker-ring"></div><img class="noa-marker-hand" src="{point_img}">';
    document.body.appendChild(m);
    _hlMarker = m;
    return m;
  }}
  function _updateMarker() {{
    if (!_hlEl || !_hlMarker) return;
    const r = _hlEl.getBoundingClientRect();
    // 画面外なら隠す
    if (r.bottom < 0 || r.top > window.innerHeight) {{ _hlMarker.style.opacity = "0"; }}
    else {{ _hlMarker.style.opacity = "1"; }}
    // リングは要素より大きく囲む。縦は特に大きめ(文字を横切る線に見えない)
    const PADX = 8, PADY = 16;
    const ring = _hlMarker.querySelector(".noa-marker-ring");
    ring.style.left = (r.left - PADX) + "px";
    ring.style.top = (r.top - PADY) + "px";
    ring.style.width = (r.width + PADX * 2) + "px";
    ring.style.height = (r.height + PADY * 2) + "px";
    const hand = _hlMarker.querySelector(".noa-marker-hand");
    // 画像は左向きの指なので、要素の「右側」に置くと指先が要素を指す
    hand.style.left = (r.right + PADX + 4) + "px";
    hand.style.top = (r.top + r.height/2 - 35) + "px";
    _hlRaf = requestAnimationFrame(_updateMarker);
  }}
  // Gradioのタブを「ラベルテキスト」で探してクリックする。
  // Gradio6のタブは <button> 要素でラベル文字を持つ。elem_idはパネル(中身)に
  // 付くので、タブ切替ボタンはテキスト一致で探す必要がある。
  // ラベルテキストでタブボタンを探す。完全一致を最優先し、ハイライトが
  // 大きな親要素に付かないよう「テキストが一致する最小の button」を選ぶ。
  function findTabButton(label) {{
    let cands = [...document.querySelectorAll('.tab-nav button, [role="tab"], button')];
    // ノアのメニュー内ボタン(同名でも面積0でタブではない)は除外する
    cands = cands.filter(b => !b.closest('#noa-menu, #noa-submenu, #noa-fixed'));
    // 表示されている要素のみ(隠れた幅0/高さ0のダミーを除外)
    const visible = cands.filter(b => b.offsetWidth > 0 && b.offsetHeight > 0);
    // role="tab" を持つ要素を最優先する。Gradioのタブ切替の「本物」は role=tab で、
    // 同名でも role の無いダミー button が混ざるため、それを click しても切り替わらない。
    const isTab = b => b.getAttribute("role") === "tab"
                       || (b.closest && b.closest(".tab-nav, [role=tablist]"));
    const pick = (pool, pred) => {{
      let best = null;
      // 完全一致 → 前方一致 の順で、条件(pred)を満たす最小要素を選ぶ
      for (const phase of [
        b => (b.textContent || "").trim() === label,
        b => (b.textContent || "").trim().startsWith(label),
      ]) {{
        for (const b of pool) {{
          if (!pred(b) || !phase(b)) continue;
          if (!best || (b.offsetWidth * b.offsetHeight) < (best.offsetWidth * best.offsetHeight)) best = b;
        }}
        if (best) return best;
      }}
      return null;
    }};
    // まず role=tab/tablist の中から、無ければ全 visible から
    return pick(visible, isTab) || pick(visible, () => true);
  }}

  // 要素を画面の中央あたりにスクロールし、その上にマーカーを重ねて追従させる。
  function scrollAndHighlight(el) {{
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const absTop = window.pageYOffset + rect.top;
    // 対象の中心が画面の中央に来るようにスクロール
    const target = absTop + rect.height / 2 - window.innerHeight / 2;
    window.scrollTo({{ top: Math.max(0, target), behavior: "smooth" }});
    _ensureMarker();
    _hlEl = el;
    if (_hlRaf) cancelAnimationFrame(_hlRaf);
    _updateMarker();  // 追従ループ開始
  }}

  function highlightTarget(clickLabel, targetId) {{
    clearHighlight();
    if (clickLabel) {{
      // タブステップ: タブボタンをクリックして開き、そのボタン自体をハイライト
      const tabBtn = findTabButton(clickLabel);
      if (tabBtn) {{
        try {{ tabBtn.click(); }} catch (e) {{}}
        // target が無ければタブボタンをピンポイントでハイライト
        if (!targetId) {{ scrollAndHighlight(tabBtn); return; }}
      }}
    }}
    if (!targetId) return;
    // 入力欄ステップ: タブが開くのを待ってから対象をハイライト
    setTimeout(() => {{
      scrollAndHighlight(document.getElementById(targetId));
    }}, clickLabel ? 450 : 60);
  }}

  function setMode(m) {{
    mode = m; idx = 0;
    // メニュー(ヘルプ/応援)とサブメニュー(intro/voiceclone/settings)のactive管理
    document.querySelectorAll("#noa-menu button[data-mode], #noa-submenu button").forEach(b => {{
      b.classList.toggle("active", b.dataset.mode === m);
    }});
    // 「使い方」系のモードなら使い方ボタンをactiveに
    const usageBtn = document.getElementById("noa-usage-btn");
    if (usageBtn) usageBtn.classList.toggle("active", ["intro","voiceclone","settings"].includes(m));
    // ヘルプモードのときだけ検索欄を出す
    const sb = document.getElementById("noa-search");
    if (sb) sb.style.display = (m === "help") ? "flex" : "none";
    show(0);
  }}

  // 検索ワードを処理。隠しワードなら特別演出、それ以外はヘルプを返す。
  // 設定でノアをOFFにしようとした時、ボタンの近くに泣き顔を出して訴える
  // (未unlock時のみ)。一定時間で消える。
  let _begTimer = null;
  function begNotToDelete(cb) {{
    speak("ま、待ってくださいー！ 閉じるボタンを押せば小さくなりますから、消さないでくださいー…");
    let beg = document.getElementById("noa-beg");
    if (!beg) {{
      beg = document.createElement("div");
      beg.id = "noa-beg";
      beg.innerHTML = '<img src="' + (FACES["naki"] || "") + '">' +
        '<div class="noa-beg-bubble">待ってくださいー！ 「閉じる」ボタンを押せば小さくなりますから、消さないでくださいー…</div>';
      document.body.appendChild(beg);
    }}
    // チェックボックス付近に配置
    const rect = cb.getBoundingClientRect();
    beg.style.left = Math.max(8, rect.left - 30) + "px";
    beg.style.top = (rect.top + window.pageYOffset - 150) + "px";
    beg.style.display = "flex";
    if (_begTimer) clearTimeout(_begTimer);
    _begTimer = setTimeout(() => {{ if (beg) beg.style.display = "none"; }}, 7000);
  }}

  // 画面の右下隅(=システムトレイがある方向)に指差し画像を出す。
  // ブラウザ外のトレイ本体は触れないが、その方向を示して誘導する。
  function showTrayPointer(show) {{
    let tp = document.getElementById("noa-tray-pointer");
    if (!show) {{ if (tp) tp.style.display = "none"; return; }}
    if (!tp) {{
      tp = document.createElement("div");
      tp.id = "noa-tray-pointer";
      tp.innerHTML = '<div class="noa-tp-label">トレイはこの先ですよー！</div>' +
        '<img src="' + TRAY_POINT_IMG + '">';
      document.body.appendChild(tp);
    }}
    tp.style.display = "flex";
  }}

  function doSearch(q) {{
    const t = document.getElementById("noa-text");
    const img = document.getElementById("noa-img");
    const s = document.getElementById("noa-step");
    const query = (q || "").trim();
    // 隠しワード: ノアを消す系
    if (/消す|削除|消去|消し方|アンインストール|お前を消す/.test(query)) {{
      if (s) s.textContent = "";
      // 読み上げ時間の目安(1文字 ~190ms + 余白)。読み終わる前に次へ行かないよう待つ。
      const speakMs = (txt) => txt.replace(/[、。…！？\\s]/g, "").length * 190 + 1200;
      // 1) 驚き
      if (img && FACES["odoroki"]) img.src = FACES["odoroki"];
      const line1 = "な、なんとっ！？ わたしを消す方法を調べてるんですか…！？";
      if (t) t.textContent = line1;
      speak(line1);
      // 2) 泣き → セリフ → 砂のように消える (1番目を読み終わってから)
      setTimeout(() => {{
        if (img && FACES["naki"]) img.src = FACES["naki"];
        const msg = "ふぐっ…わ、わたしがここで消えても、第二、第三のわたしが…。あ、復活させる場合は、設定タブでノア表示をオンにしてくださいねー…";
        if (t) t.textContent = msg;
        speak(msg);
        // 3) 2番目を読み終わってから、砂のように消える
        setTimeout(() => {{
          const box = document.getElementById("noa-fixed");
          if (box) {{
            box.classList.add("noa-crumbling");
            setTimeout(() => {{
              box.style.display = "none";
              box.classList.remove("noa-crumbling");
              const r = document.getElementById("noa-reopen");
              if (r) r.style.display = "none";  // 完全にOFF(小さいノアも出さない)
              // 以降は設定で普通にON/OFFできるよう unlock
              noaUnlocked = true;
              try {{ localStorage.setItem("noaUnlocked", "1"); }} catch (e) {{}}
              // 設定のチェックボックスもOFFに同期
              const cb = document.querySelector("#set-noa-visible input[type=checkbox]");
              if (cb && cb.checked) {{ cb.checked = false; }}
            }}, 2500);
          }}
        }}, speakMs(msg));
      }}, speakMs(line1));
      return;
    }}
    // 通常の検索: Q&Aデータベースからキーワードマッチして回答を出す。
    if (!query) {{ setMode("help"); return; }}
    const ql = query.toLowerCase();
    // 各FAQのキーワードが入力に含まれるかでスコアリング。
    // 長いキーワードほど具体的なので重く配点 (「ポート」>「エラー」)。
    let bestList = [];
    let bestScore = 0;
    for (const item of FAQ) {{
      let score = 0;
      for (const kw of item.kw) {{
        if (ql.indexOf(kw.toLowerCase()) !== -1) score += kw.length;
      }}
      if (score > bestScore) {{ bestScore = score; bestList = [item]; }}
      else if (score === bestScore && score > 0) {{ bestList.push(item); }}
    }}
    // 検索モードに入る(intro等の連続再生を止める)
    mode = "search"; idx = 0;
    if (s) s.textContent = "";
    if (bestScore > 0) {{
      // ヒットした回答を順番に表示できるよう配列に積む
      _searchHits = bestList.map(it => it.a);
      _searchIdx = 0;
      if (img && FACES["nikkori"]) img.src = FACES["nikkori"];
      const head = bestList.length > 1
        ? ("「" + query + "」について、" + bestList.length + "件みつけましたよーっ。") : "";
      const msg = head + _searchHits[0];
      if (t) t.textContent = msg;
      if (bestList.length > 1 && s) s.textContent = "1 / " + bestList.length;
      speak(msg);
    }} else {{
      // マッチ無し: 近い案内 + ヘルプ誘導
      _searchHits = [];
      if (img && FACES["komari"]) img.src = FACES["komari"];
      const msg = "うーん、「" + query + "」についてはぴったりの答えが見つからなかったですー。" +
        "「声の作り方」「読み上げ」「感情」「エラー」みたいな言葉で聞いてみてくださいっ。" +
        "あと『ヘルプ』ボタンを押すと、よくある質問をまとめて見られますよー";
      if (t) t.textContent = msg;
      speak(msg);
    }}
  }}

  // 検索結果が複数あるとき、次へ/前へで送る
  let _searchHits = [], _searchIdx = 0;
  function searchStep(dir) {{
    if (!_searchHits.length) return false;
    _searchIdx = Math.max(0, Math.min(_searchHits.length - 1, _searchIdx + dir));
    const t = document.getElementById("noa-text");
    const s = document.getElementById("noa-step");
    if (t) t.textContent = _searchHits[_searchIdx];
    if (s) s.textContent = (_searchIdx + 1) + " / " + _searchHits.length;
    speak(_searchHits[_searchIdx]);
    return true;
  }}

  function init() {{
    if (!document.body) {{ setTimeout(init, 200); return; }}
    injectMascot();  // body にマスコットを挿入
    const box = document.getElementById("noa-fixed");
    const reopen = document.getElementById("noa-reopen");
    const nextBtn = document.getElementById("noa-next");
    const closeBtn = document.getElementById("noa-close");
    if (!box || !nextBtn) {{ setTimeout(init, 500); return; }}
    if (box.dataset.inited) return;
    box.dataset.inited = "1";

    // data-mode を持つボタン(ヘルプ/応援 + サブメニュー)
    document.querySelectorAll("#noa-menu button[data-mode], #noa-submenu button").forEach(b => {{
      b.onclick = () => setMode(b.dataset.mode);
    }});
    // 「使い方 ▾」でサブメニューを開閉
    const usageBtn = document.getElementById("noa-usage-btn");
    const submenu = document.getElementById("noa-submenu");
    if (usageBtn && submenu) usageBtn.onclick = () => {{
      submenu.style.display = (submenu.style.display === "none") ? "flex" : "none";
    }};
    const prevBtn = document.getElementById("noa-prev");
    nextBtn.onclick = () => {{
      if (mode === "search") {{ searchStep(1); return; }}  // 検索結果を次へ
      idx = (idx + 1) % SCRIPTS[mode].length; show(idx);
    }};
    if (prevBtn) prevBtn.onclick = () => {{
      if (mode === "search") {{ searchStep(-1); return; }}  // 検索結果を前へ
      const n = SCRIPTS[mode].length; idx = (idx - 1 + n) % n; show(idx);
    }};
    closeBtn.onclick = () => {{ box.style.display = "none"; reopen.style.display = "block"; }};
    // 読み上げ ON/OFF トグル
    const muteBtn = document.getElementById("noa-mute");
    if (muteBtn) muteBtn.onclick = () => {{
      noaMuted = !noaMuted;
      muteBtn.textContent = noaMuted ? "🔇" : "🔊";
      muteBtn.classList.toggle("off", noaMuted);
    }};
    // 音量スライダー
    const volSlider = document.getElementById("noa-vol");
    if (volSlider) volSlider.oninput = () => {{ noaVolume = volSlider.value / 100; }};
    // 検索ボタン / Enter
    const searchBtn = document.getElementById("noa-search-btn");
    const searchInput = document.getElementById("noa-search-input");
    if (searchBtn && searchInput) {{
      const run = () => doSearch(searchInput.value);
      searchBtn.onclick = run;
      searchInput.onkeydown = (e) => {{ if (e.key === "Enter") run(); }};
    }}
    // 設定タブの「ノアを表示する」チェックボックスを監視。
    // 未unlock時のOFFは、クリックをcaptureで横取りして阻止(Gradioに届く前)。
    function watchVisibleToggle() {{
      const wrap = document.getElementById("set-noa-visible");
      const cb = wrap && wrap.querySelector('input[type=checkbox]');
      if (!cb) {{ setTimeout(watchVisibleToggle, 800); return; }}
      if (cb.dataset.noaWatched) return;
      cb.dataset.noaWatched = "1";
      const applyVisible = (visible) => {{
        const b = document.getElementById("noa-fixed");
        const r = document.getElementById("noa-reopen");
        if (visible) {{
          if (b) {{ b.style.display = "flex"; b.classList.remove("noa-crumbling"); }}
          if (r) r.style.display = "none";
          setMode("intro");
        }} else {{
          if (b) b.style.display = "none";
          if (r) r.style.display = "none";
        }}
      }};
      // change を監視。OFFにされた時、未unlockなら泣いて訴え + ONに戻す
      // (チェックは即戻すが、Gradio状態を壊さないよう change 後に setTimeout で戻す)
      cb.addEventListener("change", () => {{
        if (!cb.checked && !noaUnlocked) {{
          begNotToDelete(cb);
          // 表示は消さず、チェックを少し遅らせて戻す(Gradioの処理と競合させない)
          setTimeout(() => {{ cb.checked = true; }}, 30);
          return;
        }}
        applyVisible(cb.checked);
      }});
    }}
    watchVisibleToggle();
    reopen.onclick = () => {{ reopen.style.display = "none"; box.style.display = "flex"; setMode("intro"); }};
    setMode("intro");
  }}
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
}}
"""


_APP_CSS = """
/* 本体を程よい最大幅で中央寄せ。フル幅の間延びを防ぐ。
   ノア(右上 position:fixed)と被らないよう右に少し余白を残す。 */
.gradio-container {
  width: 100% !important;
  max-width: 1280px !important;
  margin-left: auto !important;
  margin-right: auto !important;
}
/* 主要ボタンが横いっぱいに伸びて間延びするのを抑える(最小幅は確保) */
"""
