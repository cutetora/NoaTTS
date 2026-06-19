# NoaTTS 追加API仕様 — `POST /say_wav`（合成WAV返却）

## 背景
既存 `POST /say` はサーバーPCのスピーカーで再生し、応答は `{"ok":true,"chars":N}`。WAVは返さない。
みるくADV（Unity）は「クライアントがWAVバイト列を受け取り自前で再生」する設計のため、
**再生ではなくWAVを返すAPI** `/say_wav` を新規追加した。`/say` は一切変更していない（役割分離）。

## エンドポイント
`POST /say_wav`

### リクエスト
- ヘッダ: `Content-Type: application/json; charset=utf-8`
- ボディ(JSON):

```json
{
  "text": "読み上げ本文（必須・UTF-8・改行/記号/絵文字混在可）",
  "voice": "noa",   // 任意。GET /voices のIDのいずれか。省略時は active 声
  "speed": 1.0       // 任意。話速倍率。省略時はボイスカードの speed
}
```

- `text` は内部で `clean_text`（絵文字・マークダウン・コードブロック除去）を通してから合成する。
- `voice` 指定時もアクティブ声（`/say` が使う声）は切り替えない。指定声を一時ロードして合成する。
  - 前提: 指定声は現在ロード中のモデル（checkpoint）と同一であること（クローン声同士はOK）。
- `speed` は WSOLA ベースの話速調整で適用する。

### レスポンス（成功）
- ステータス: `200`
- ヘッダ: `Content-Type: audio/wav`
- ボディ: WAVバイト列そのもの。先頭が `RIFF...WAVE`。
- フォーマット厳守: **PCM 16bit / モノラル / 24000Hz**
  （fmt チャンク: `AudioFormat=1, NumChannels=1, SampleRate=24000, BitsPerSample=16`）
  - エンジンのネイティブ出力は 48000Hz mono float。`/say_wav` 内で 24000Hz / 16bit PCM に変換して返す。

### レスポンス（失敗）
- `400`: text 欠落/空/不正JSON、clean後に空、または存在しない voice 指定
- `500`: 合成失敗、または生成結果が空
- ボディ(JSON): `{"ok": false, "error": "理由"}`
- **禁止事項を遵守**: 失敗時に「200 + 0バイトWAV」や「200 + 空ボディ」を返さない
  （Unity `WavUtility.ToAudioClip` が `Length must be larger than 0` で落ちるため）。
  WAVヘッダ(44byte)以下のサイズは `500 empty audio` 扱い。

## 動作要件（実装で満たしている点）
- **同期返却**: レスポンスを返す時点で合成完了し、全WAVがボディに入っている（202+ポーリングではない）。
- **PCで鳴らさない**: `/say_wav` は再生せずバイト返却のみ（`StreamPlayer` を使わない）。
- **ファイルに依存しない**: メモリ上で生成して返す（`output/` 共有ファイルを参照しない）。
- **並行安全**: `ThreadingHTTPServer` でリクエストごとにスレッド処理。合成中核 `_gen_core` は
  エンジン呼び出しを `_model_lock` で排他し、`self` の可変状態（caption/pause/volume の override）を
  一切読み書きしない。波形の組み立ては各スレッドのローカル変数 → 各レスポンスは自分の text の WAV を返す。
- **長文**: 内部で文分割しても、文間 gap（`gap.txt` 設定値）を挟んで結合した **1本のWAV** として返す（1リクエスト=1WAV）。
- **タイムアウト**: 合成は最大60秒許容（クライアントも60秒待つ想定）。

## 受け入れテスト

```bash
# 成功: RIFFで始まるWAVが返る / 24kHz mono 16bit
curl -s -X POST http://127.0.0.1:7870/say_wav \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary '{"text":"てすと","voice":"noa"}' \
  -o out.wav -w "ctype=%{content_type} bytes=%{size_download}\n"
# 期待: ctype=audio/wav, bytes>0, out.wav 先頭が "RIFF"
#       fmt: PCM(1) / 1ch / 24000Hz / 16bit

# 失敗: text空 → 400 + JSON、WAVは返らない
curl -s -X POST http://127.0.0.1:7870/say_wav \
  -H "Content-Type: application/json" --data-binary '{"text":""}' \
  -w " http=%{http_code}\n"
# 期待: http=400, ボディ {"ok":false,"error":...}
```

## 既存への影響
- `GET /voices` / `GET /health` / `POST /say` / `POST /stop` は変更なし。
- `/say_wav` の `voice` 引数は `/voices` のIDを受け付ける。

## 実装箇所（NoaTTS側）
- `engine/audio_utils.py` : `to_wav_bytes(audio, sr, target_sr=24000)` を追加（48k→24k/mono/16bit PCM の RIFF バイト列化）。
- `daemon/worker.py` : `_gen_core()`（合成中核を抽出・`/say` と共用）、`_load_vc_only()`（声を切り替えず一時ロード）、`synthesize_wav()`（鳴らさず1本WAVを返す）を追加。
- `daemon/servers.py` : `do_POST` に `/say_wav` 分岐を追加。

> **反映には daemon の再起動が必要**（実行中プロセスは旧コードを保持しているため）。

## クライアント側（みるくADV / main.py）
```
TTS_URL = "http://127.0.0.1:7870/say_wav"
payload = {"text": text, "voice": "noa"}   # 旧: {model,input,voice,response_format}
# レスポンスのバイト列をそのまま AudioClip 化（24kHz/mono/16bit）
```
