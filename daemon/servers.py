"""3つの受信サーバー: named pipe / ファイル監視 / HTTP API。"""
import os
from pathlib import Path

from daemon import runtime, tuning
from .runtime import (
    PIPE_NAME, SAY_FILE, FLAG_PATH, VOICES_DIR, HTTP_HOST, HTTP_PORT,
    DAEMON_PID_PATH, CACHE_DIR, _stop_event, dispatch_speak, dispatch_dialogue, stop_speaking,
)
from .textproc import clean_text
from .tuning import _set_gap, _set_nosplit, _set_firstcut, _set_tailpad
from .panel_html import CONTROL_PANEL_HTML
from .worker import TTSWorker

# ─── Named pipe サーバー ───

def pipe_server(worker: TTSWorker):
    import win32pipe
    import win32file
    import pywintypes

    print(f"[daemon] pipe待受: {PIPE_NAME}", flush=True)

    while not _stop_event.is_set():
        try:
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_INBOUND,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1, 65536, 65536, 0, None,
            )
        except Exception as e:
            print(f"[daemon] pipe作成失敗: {e}", flush=True)
            break

        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            data = b""
            while True:
                try:
                    _, chunk = win32file.ReadFile(pipe, 65536)
                    data += chunk
                except pywintypes.error as e:
                    # ERROR_BROKEN_PIPE (109) = クライアントが切断
                    break
        except Exception as e:
            print(f"[daemon] pipe接続エラー: {e}", flush=True)
            continue
        finally:
            try:
                win32file.CloseHandle(pipe)
            except Exception:
                pass

        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            continue

        if text == "##QUIT##":
            print("[daemon] 終了シグナル受信", flush=True)
            _stop_event.set()
            break

        cleaned = clean_text(text)
        if not cleaned:
            continue

        print(f"[daemon] テキスト受信 ({len(cleaned)}字)", flush=True)

        # 前の読み上げをキャンセルして新しいものを開始
        dispatch_speak(worker, cleaned)


# ─── ファイル監視サーバー ───

def file_watcher(worker):
    """_tts_say.txt の変更を監視し、書き換わったら読み上げる。
    transcript非依存・1ターン遅れ無し。トグル(tts_auto.flag)OFFなら無視。"""
    import time as _time

    last_mtime = None
    # 起動時の既存ファイルは読まない (古い内容の誤読防止)
    if SAY_FILE.exists():
        try:
            last_mtime = SAY_FILE.stat().st_mtime
        except OSError:
            pass

    print(f"[daemon] ファイル監視開始: {SAY_FILE.name}", flush=True)

    while not _stop_event.is_set():
        _time.sleep(0.4)
        try:
            if not SAY_FILE.exists():
                continue
            mt = SAY_FILE.stat().st_mtime
            if mt == last_mtime:
                continue
            last_mtime = mt
            # トグルOFFなら読み上げない
            if not FLAG_PATH.exists():
                continue
            text = SAY_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not text:
            continue

        cleaned = clean_text(text)
        if not cleaned:
            continue
        print(f"[daemon] ファイルから受信 ({len(cleaned)}字)", flush=True)

        # 前の読み上げをキャンセルして新規開始
        dispatch_speak(worker, cleaned)


# ─── HTTP サーバー ───
# 別の開発・スクリプト・ブラウザから「文を投げれば読む」入口。
#   POST /say     text=... または JSON {"text": "..."} を読み上げ (トグル無視で必ず読む)
#   POST /stop    読み上げを中断
#   GET  /health  生存確認 (JSON)
#   GET  /vram    VRAM使用状況 (全体/NoaTTS/空き、MB)
#   GET  /        操作パネル画面 (使い方・curl例・テスト送信・状態)


def _vram_info() -> dict:
    """VRAM使用状況を返す (MB)。
    total/used/free は nvidia-smi (GPU全体)、noa はこの daemon プロセスが
    CUDA に確保した量 (torch)。Windows WDDM では nvidia-smi のプロセス別が
    取れないため、自プロセス分は torch.cuda.memory_reserved を使う。"""
    import subprocess
    info = {"ok": True, "total": 0, "used": 0, "free": 0, "noa": 0}
    # Windows では nvidia-smi 呼び出しのたびに一瞬コンソール窓が開くのを防ぐ
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=creationflags)
        nums = [int(x.strip()) for x in r.stdout.strip().splitlines()[0].split(",")]
        info["total"], info["used"], info["free"] = nums[0], nums[1], nums[2]
    except Exception as e:
        info["ok"] = False
        info["error"] = f"nvidia-smi: {e}"
    try:
        import torch
        if torch.cuda.is_available():
            # reserved = PyTorchがキャッシュ含め確保した量 (実使用に近い)
            info["noa"] = round(torch.cuda.memory_reserved() / (1024 * 1024))
    except Exception:
        pass
    return info


def http_server(worker):
    """別開発・ブラウザ向けの HTTP 入口。標準ライブラリのみ。"""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    panel_html = CONTROL_PANEL_HTML.replace("__PORT__", str(HTTP_PORT))

    def is_speaking():
        t = runtime._current_speak_thread
        return bool(t is not None and t.is_alive())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # アクセスログ抑制

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_OPTIONS(self):
            self._send(204, b"")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/" or path == "/index.html":
                self._send(200, panel_html.encode("utf-8"),
                           "text/html; charset=utf-8")
            elif path == "/health":
                self._json(200, {"ok": True, "voice": worker.voice_name,
                                 "speaking": is_speaking(), "port": HTTP_PORT,
                                 "speed": worker.speed, "gap": tuning._gap_sec,
                                 "pause": worker.pause, "firstcut": tuning._first_cut,
                                 "nosplit": tuning._nosplit, "tailpad": tuning._tail_pad_sec,
                                 "auto": FLAG_PATH.exists(),
                                 "model": getattr(worker, "_model_repo", None)})
            elif path == "/autostatus":
                self._json(200, {"ok": True, "auto": FLAG_PATH.exists()})
            elif path == "/voices":
                names = []
                try:
                    vdir = Path(VOICES_DIR)
                    names = sorted([p.name for p in vdir.iterdir() if p.is_dir()])
                except Exception:
                    pass
                self._json(200, {"ok": True, "voices": names,
                                 "active": worker.voice_name})
            elif path == "/vram":
                self._json(200, _vram_info())
            elif path == "/model":
                self._json(200, {"ok": True,
                                 "model": getattr(worker, "_model_repo", None)})
            elif path == "/cache":
                # 音声キャッシュ(WAV使い回し)の現在状態と保存件数。
                n = 0
                try:
                    if CACHE_DIR.is_dir():
                        n = sum(1 for _ in CACHE_DIR.glob("*.wav"))
                except Exception:
                    pass
                self._json(200, {"ok": True,
                                 "enabled": worker.cache_enabled,
                                 "files": n})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""

            if path == "/stop":
                stop_speaking(worker)
                self._json(200, {"ok": True, "stopped": True})
                return

            if path == "/cache":
                # 音声キャッシュ(WAV使い回し)の既定ON/OFF・クリア。
                #   {"enabled": true/false}  既定のON/OFFを設定(cache.flagに永続化)
                #   {"action": "clear"}      キャッシュ済みWAVを全削除
                body = raw.decode("utf-8", errors="replace").strip()
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(obj, dict):
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                resp = {"ok": True}
                if str(obj.get("action", "")).lower() == "clear":
                    resp["cleared"] = worker.clear_cache()
                if "enabled" in obj:
                    resp["enabled"] = worker.set_cache(obj.get("enabled"))
                else:
                    resp["enabled"] = worker.cache_enabled
                self._json(200, resp)
                return

            if path == "/voice":
                body = raw.decode("utf-8", errors="replace").strip()
                name = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        name = str(json.loads(body or "{}").get("name", "")).strip()
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                if not name:
                    self._json(400, {"ok": False, "error": "empty voice name"})
                    return
                ok = worker.switch_voice(name)
                self._json(200 if ok else 404,
                           {"ok": ok, "voice": worker.voice_name,
                            "error": None if ok else "voice not found"})
                return

            if path == "/model":
                body = raw.decode("utf-8", errors="replace").strip()
                repo_id = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        repo_id = str(json.loads(body or "{}").get("repo_id", "")).strip()
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                if not repo_id:
                    self._json(400, {"ok": False, "error": "empty repo_id"})
                    return
                # GPU再ロードで数十秒かかる (クライアントは長めのタイムアウトで待つ)
                ok = worker.switch_model(repo_id)
                self._json(200 if ok else 500,
                           {"ok": ok, "model": getattr(worker, "_model_repo", None),
                            "error": None if ok else "model switch failed"})
                return

            if path == "/speed":
                body = raw.decode("utf-8", errors="replace").strip()
                val = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        val = json.loads(body or "{}").get("speed", "")
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                ok = worker.set_speed(val)
                self._json(200 if ok else 400,
                           {"ok": ok, "speed": worker.speed,
                            "error": None if ok else "invalid speed"})
                return

            if path == "/gap":
                # 文間無音(秒)を変更。再起動不要・gap.txtに永続化。
                body = raw.decode("utf-8", errors="replace").strip()
                val = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        val = json.loads(body or "{}").get("gap", "")
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                try:
                    newgap = _set_gap(float(val))
                    self._json(200, {"ok": True, "gap": newgap})
                except (TypeError, ValueError):
                    self._json(400, {"ok": False, "error": "invalid gap"})
                return

            if path == "/tailpad":
                # 末尾余韻(秒)を変更。語尾欠け防止。再起動不要・tailpad.txt永続化。
                body = raw.decode("utf-8", errors="replace").strip()
                val = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        val = json.loads(body or "{}").get("tailpad", "")
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                try:
                    newpad = _set_tailpad(float(val))
                    self._json(200, {"ok": True, "tailpad": newpad})
                except (TypeError, ValueError):
                    self._json(400, {"ok": False, "error": "invalid tailpad"})
                return

            if path == "/nosplit":
                # この文字数以下は分割しない(テンポ優先)。再起動不要・nosplit.txt永続化。
                body = raw.decode("utf-8", errors="replace").strip()
                val = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        val = json.loads(body or "{}").get("nosplit", "")
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                try:
                    newn = _set_nosplit(val)
                    self._json(200, {"ok": True, "nosplit": newn})
                except (TypeError, ValueError):
                    self._json(400, {"ok": False, "error": "invalid nosplit"})
                return

            if path == "/firstcut":
                # 1文目早切りの目標文字数。0で無効。再起動不要・firstcut.txt永続化。
                body = raw.decode("utf-8", errors="replace").strip()
                val = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        val = json.loads(body or "{}").get("firstcut", "")
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                try:
                    newc = _set_firstcut(val)
                    self._json(200, {"ok": True, "firstcut": newc})
                except (TypeError, ValueError):
                    self._json(400, {"ok": False, "error": "invalid firstcut"})
                return

            if path == "/pause":
                # 音声内ポーズ上限(秒)を変更。0で無加工。再起動不要・pause.txt永続化。
                body = raw.decode("utf-8", errors="replace").strip()
                val = body
                ctype = (self.headers.get("Content-Type") or "").lower()
                if "application/json" in ctype:
                    try:
                        val = json.loads(body or "{}").get("pause", "")
                    except Exception:
                        self._json(400, {"ok": False, "error": "invalid json"})
                        return
                try:
                    newp = worker.set_pause(float(val))
                    self._json(200, {"ok": True, "pause": newp})
                except (TypeError, ValueError):
                    self._json(400, {"ok": False, "error": "invalid pause"})
                return

            if path == "/toggle":
                # 自動読み上げ (tts_auto.flag) の作成/削除をトグル
                if FLAG_PATH.exists():
                    try:
                        FLAG_PATH.unlink()
                    except Exception:
                        pass
                    auto = False
                else:
                    try:
                        FLAG_PATH.write_text("on", encoding="utf-8")
                    except Exception:
                        pass
                    auto = FLAG_PATH.exists()
                print(f"[daemon] 自動読み上げ → {'ON' if auto else 'OFF'}", flush=True)
                self._json(200, {"ok": True, "auto": auto})
                return

            if path == "/quit":
                self._json(200, {"ok": True, "quitting": True})
                print("[daemon] HTTP /quit 受信、終了します", flush=True)
                _stop_event.set()
                # main の pipe_server は ConnectNamedPipe でブロッキング待機して
                # おり _stop_event では即抜けない。確実に死ぬよう、応答返却後に
                # プロセスごと自死する (別スレッドで少し遅らせて wfile flush を待つ)。
                import threading as _th
                import time as _t

                def _suicide():
                    _t.sleep(0.3)
                    try:
                        DAEMON_PID_PATH.unlink()
                    except Exception:
                        pass
                    os._exit(0)

                _th.Thread(target=_suicide, daemon=True).start()
                return

            if path == "/v1/audio/speech":
                # OpenAI Text-to-Speech API 互換エンドポイント。既存の OpenAI-TTS
                # クライアント(SDK/curl)から差し替えで使えるようにする。
                # body: {"input": "...", "voice": "<ボイスカード名>", "speed": 1.0,
                #        "response_format": "wav"|"pcm"} (model は無視)。
                # response_format で出力形式を指定 (wav/pcm/mp3/flac/ogg/opus/aac)。
                # 環境にエンコーダが無い形式は wav にフォールバックする。
                from engine.audio_utils import to_audio_bytes
                body = raw.decode("utf-8", errors="replace").strip()
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    self._json(400, {"error": {"message": "invalid json"}})
                    return
                if not isinstance(obj, dict):
                    self._json(400, {"error": {"message": "invalid json"}})
                    return
                text = str(obj.get("input", "") or "").strip()
                voice = str(obj.get("voice", "") or "").strip() or None
                speed = obj.get("speed", None)
                fmt = str(obj.get("response_format", "") or "wav").lower()
                if not text:
                    self._json(400, {"error": {"message": "input is required"}})
                    return
                cleaned = clean_text(text)
                if not cleaned:
                    self._json(400, {"error": {"message": "nothing to speak after cleanup"}})
                    return
                # OpenAI の voice 名(alloy等)は NoaTTS には無いので、ボイスカードが
                # 存在すればそれを使い、無ければアクティブボイスにフォールバック。
                if voice and not (Path(VOICES_DIR) / voice / "config.json").exists():
                    voice = None
                try:
                    wav, sr = worker.synthesize_wav(cleaned, voice=voice, speed=speed)
                except Exception as e:
                    self._json(500, {"error": {"message": f"synthesis failed: {e}"}})
                    return
                try:
                    data, ctype = to_audio_bytes(wav, sr, fmt=fmt, target_sr=24000)
                except Exception as e:
                    self._json(500, {"error": {"message": f"encode failed: {e}"}})
                    return
                if not data:
                    self._json(500, {"error": {"message": "empty audio"}})
                    return
                self._send(200, data, ctype=ctype)
                print(f"[daemon] /v1/audio/speech 返却 ({len(cleaned)}字 / fmt={fmt})", flush=True)
                return

            if path == "/say_wav":
                # 合成WAVを返す(鳴らさない)。Unity等クライアント再生用。
                # /say とは役割分離: 再生せず、24kHz/mono/16bit PCM のバイト列を同期返却。
                # output/ 共有ファイルに依存せずメモリ生成 → 並行リクエストでも取り違えない。
                from engine.audio_utils import to_wav_bytes
                body = raw.decode("utf-8", errors="replace").strip()
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(obj, dict):
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                text = str(obj.get("text", "") or "").strip()
                voice = str(obj.get("voice", "") or "").strip() or None
                speed = obj.get("speed", None)
                if not text:
                    self._json(400, {"ok": False, "error": "empty text"})
                    return
                cleaned = clean_text(text)
                if not cleaned:
                    self._json(400, {"ok": False, "error": "nothing to speak after cleanup"})
                    return
                # voice 指定があり実在しなければ 400 (GET /voices のIDのいずれか)
                if voice and not (Path(VOICES_DIR) / voice / "config.json").exists():
                    self._json(400, {"ok": False, "error": f"unknown voice: {voice}"})
                    return
                try:
                    wav, sr = worker.synthesize_wav(cleaned, voice=voice, speed=speed)
                    data = to_wav_bytes(wav, sr, target_sr=24000)
                except Exception as e:
                    self._json(500, {"ok": False, "error": f"synthesis failed: {e}"})
                    return
                # 失敗時に「200+0バイト」を返さない (Unity WavUtility が落ちるため)
                if not data or len(data) <= 44:
                    self._json(500, {"ok": False, "error": "empty audio"})
                    return
                print(f"[daemon] /say_wav 返却 ({len(cleaned)}字 / {len(data)}B)", flush=True)
                self._send(200, data, ctype="audio/wav")
                return

            if path == "/say_dialogue":
                # 複数キャラの掛け合いを声を切り替えながら連続再生する。
                #   {"segments": [{"voice":"sara","text":"...","caption":"<任意>"}, ...],
                #    "cache": true/false(任意)}
                # voice 省略/null はアクティブ声。実在しない voice は400。
                body = raw.decode("utf-8", errors="replace").strip()
                try:
                    obj = json.loads(body) if body else {}
                except Exception:
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(obj, dict):
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
                raw_segs = obj.get("segments")
                if not isinstance(raw_segs, list) or not raw_segs:
                    self._json(400, {"ok": False, "error": "segments must be a non-empty list"})
                    return
                cache = bool(obj["cache"]) if "cache" in obj else None
                segments = []
                for s in raw_segs:
                    if not isinstance(s, dict):
                        continue
                    txt = clean_text(str(s.get("text", "") or "").strip())
                    if not txt:
                        continue
                    voice = str(s.get("voice", "") or "").strip() or None
                    if voice and not (Path(VOICES_DIR) / voice / "config.json").exists():
                        self._json(400, {"ok": False, "error": f"unknown voice: {voice}"})
                        return
                    segments.append({
                        "voice": voice,
                        "text": txt,
                        "caption": str(s.get("caption", "") or "").strip() or None,
                    })
                if not segments:
                    self._json(400, {"ok": False, "error": "nothing to speak after cleanup"})
                    return
                print(f"[daemon] /say_dialogue 受信 ({len(segments)}セグメント)", flush=True)
                dispatch_dialogue(worker, segments, cache=cache)
                self._json(200, {"ok": True, "segments": len(segments)})
                return

            if path != "/say":
                self._json(404, {"ok": False, "error": "not found"})
                return

            body = raw.decode("utf-8", errors="replace").strip()
            text = body
            caption = None  # None=ボイスカードの default_caption に従う
            cache = None    # None=既定のキャッシュON/OFFに従う / True/Falseでこの回だけ上書き
            voice = None    # None=アクティブ声 / 声IDでこの読み上げだけ別キャラ
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype:
                try:
                    obj = json.loads(body) if body else {}
                    text = str(obj.get("text", "")).strip()
                    # 音量 (0.0〜1.0)。指定があれば worker に反映。
                    if "volume" in obj:
                        try:
                            worker.volume = max(0.0, min(1.0, float(obj["volume"])))
                        except (TypeError, ValueError):
                            pass
                    # 感情caption (Irodoriクローン): この読み上げに限り上書き。
                    if "caption" in obj:
                        caption = str(obj.get("caption") or "").strip()
                    # 音声キャッシュ(使い回し): この読み上げに限りON/OFF上書き。
                    if "cache" in obj:
                        cache = bool(obj.get("cache"))
                    # 声指定: この読み上げだけ別キャラの声で読む(アクティブ声は変えない)。
                    if "voice" in obj:
                        voice = str(obj.get("voice") or "").strip() or None
                except Exception:
                    self._json(400, {"ok": False, "error": "invalid json"})
                    return
            # form-encoded (text=...) も拾う
            elif body.startswith("text=") and "\n" not in body:
                from urllib.parse import parse_qs
                text = (parse_qs(body).get("text", [""])[0]).strip()

            if not text:
                self._json(400, {"ok": False, "error": "empty text"})
                return

            cleaned = clean_text(text)
            if not cleaned:
                self._json(400, {"ok": False, "error": "nothing to speak after cleanup"})
                return

            # voice指定があり実在すれば、その声で読む(1セグメントの掛け合いとして処理)。
            if voice and not (Path(VOICES_DIR) / voice / "config.json").exists():
                self._json(400, {"ok": False, "error": f"unknown voice: {voice}"})
                return

            print(f"[daemon] HTTP受信 ({len(cleaned)}字{', voice='+voice if voice else ''})", flush=True)
            if voice:
                dispatch_dialogue(
                    worker,
                    [{"voice": voice, "text": cleaned, "caption": caption}],
                    cache=cache,
                )
            else:
                dispatch_speak(worker, cleaned, caption=caption, cache=cache)
            self._json(200, {"ok": True, "chars": len(cleaned)})

    try:
        httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    except OSError as e:
        print(f"[daemon] HTTPサーバー起動失敗 (port {HTTP_PORT}): {e}", flush=True)
        return
    print(f"[daemon] HTTP待受: http://{HTTP_HOST}:{HTTP_PORT}/", flush=True)

    while not _stop_event.is_set():
        httpd.timeout = 0.5
        httpd.handle_request()
    httpd.server_close()
