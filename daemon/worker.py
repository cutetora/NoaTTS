"""TTSWorker: モデルVRAM常駐・ボイスカード・文分割生成→連続再生。"""
import os
import time
import queue
import datetime
import threading
from pathlib import Path

from daemon import tuning
from .runtime import BASE_DIR, VOICES_DIR, OUTPUT_DIR, write_active_voice
from .tuning import _split_sentences
from .player import StreamPlayer

class TTSWorker:
    """モデルをVRAMに保持したまま、キューからテキストを受け取り再生するワーカー。"""

    def __init__(self, voice_name: str):
        self.voice_name = voice_name
        self._cancel = threading.Event()
        self._eng = None
        self._vc = None
        self._clone_prompt = None
        self._model_repo = None  # 現在の使用モデル(checkpoint repo_id)
        # モデル切替と読み上げ生成の排他。切替中(GPU再ロード)は生成を待たせる。
        self._model_lock = threading.Lock()
        self._player = None  # 現在のStreamPlayer(cancelで停止する)
        self.volume = 1.0    # 再生音量 (0.0〜1.0)。HTTP /say の volume で可変。
        # 感情caption の一時上書き。None=ボイスカードの default_caption に従う。
        # HTTP /say の caption で1回だけ指定でき、その読み上げ後に None へ戻す。
        self._caption_override = None
        # 音声内ポーズ上限の上書き(秒)。None=configのmax_pause_secに従う。
        # pause.txt があれば復元。/pause エンドポイントで可変。
        self._pause_override = None
        try:
            pf = BASE_DIR / "pause.txt"
            if pf.exists():
                self._pause_override = max(0.0, min(2.0, float(pf.read_text(encoding="utf-8").strip())))
        except Exception:
            pass
        self._load()

    def set_pause(self, sec) -> float:
        """音声内ポーズ上限(秒)を設定。0で無加工。pause.txt に永続化。"""
        v = max(0.0, min(2.0, float(sec)))
        self._pause_override = v
        try:
            (BASE_DIR / "pause.txt").write_text(str(v), encoding="utf-8")
        except Exception:
            pass
        return v

    @property
    def pause(self) -> float:
        if self._pause_override is not None:
            return self._pause_override
        return float(getattr(self._vc, "max_pause_sec", 0.0) or 0.0)

    def _load(self):
        from engine.irodori_engine import IrodoriEngine
        from config import AppConfig

        # settings.json の使用モデル指定を反映 (空なら既定)
        cfg = AppConfig.load()
        self._model_repo = cfg.irodori_checkpoint or IrodoriEngine.DEFAULT_CHECKPOINT

        print(f"[daemon] モデルロード中... ({self._model_repo})", flush=True)
        self._eng = IrodoriEngine(
            device="cuda:0",
            checkpoint=(cfg.irodori_checkpoint or None),
            vd_checkpoint=(cfg.irodori_vd_checkpoint or None),
        )
        # _load_runtime を呼んでGPUに乗せる (最初の1回のみ)
        self._eng._load_runtime()

        self._load_voice_card(self.voice_name)
        write_active_voice(self.voice_name)
        print(f"[daemon] 準備完了 — ボイス: {self._vc.name}, seed={self._vc.seed}", flush=True)

    def switch_model(self, repo_id: str) -> bool:
        """読み上げモデル(checkpoint)を動的に切り替える。GPU再ロードを伴う(数十秒)。
        成功で True。settings.json にも保存する。"""
        if not repo_id:
            return False
        is_vd = "VoiceDesign" in repo_id
        # 既に同じモデルなら何もしない
        if not is_vd and repo_id == self._model_repo:
            return True
        # 進行中の読み上げを止めてから切替 (待ち時間短縮)
        self.cancel()
        with self._model_lock:
            try:
                if is_vd:
                    # VoiceDesign は遅延ロード。差し替えて次回使用時にロードさせる。
                    self._eng.vd_checkpoint = repo_id
                    if getattr(self._eng, "_vd_runtime", None) is not None:
                        self._eng._vd_runtime = None
                else:
                    self._eng.unload()
                    self._eng.checkpoint = repo_id
                    self._eng._runtime = None
                    self._eng._load_runtime()
                    self._model_repo = repo_id
            except Exception as e:
                print(f"[daemon] モデル切替失敗 ({repo_id}): {e}", flush=True)
                # 失敗時は既定モデルで復旧を試みる (無モデル状態を避ける)
                try:
                    from engine.irodori_engine import IrodoriEngine
                    self._eng.checkpoint = IrodoriEngine.DEFAULT_CHECKPOINT
                    self._eng._runtime = None
                    self._eng._load_runtime()
                    self._model_repo = IrodoriEngine.DEFAULT_CHECKPOINT
                except Exception:
                    pass
                return False
        # settings.json に保存 (load してから1フィールドだけ更新し他フィールドを温存)
        try:
            from config import AppConfig
            cfg = AppConfig.load()
            if is_vd:
                cfg.irodori_vd_checkpoint = repo_id
            else:
                cfg.irodori_checkpoint = repo_id
            cfg.save()
        except Exception:
            pass
        print(f"[daemon] モデル切替 → {repo_id}", flush=True)
        return True

    def _load_voice_card(self, voice_name: str):
        """ボイスカードと clone_prompt を読み込む。エンジンは再利用 (切替で再呼出可)。"""
        import pickle
        from voice_manager import VoiceManager

        vm = VoiceManager(VOICES_DIR)
        vc = vm.load_voice(voice_name)
        clone_prompt = None
        if vc.clone_prompt_path and os.path.exists(vc.clone_prompt_path):
            if vc.clone_prompt_path.endswith(".pt"):
                # Irodori の latentキャッシュ: パス文字列のまま engine に渡す
                # (engine 側で ref_latent として torch.load される)
                clone_prompt = vc.clone_prompt_path
                print(f"[daemon] latentキャッシュ使用 ({voice_name})", flush=True)
            else:
                # Qwen3 等の pickle キャッシュ
                with open(vc.clone_prompt_path, "rb") as f:
                    clone_prompt = pickle.load(f)
                print(f"[daemon] clone_prompt キャッシュ使用 ({voice_name})", flush=True)
        self._vc = vc
        self._clone_prompt = clone_prompt
        self.voice_name = voice_name

    def switch_voice(self, voice_name: str) -> bool:
        """読み上げボイスを切り替える。成功で True。"""
        if voice_name == self.voice_name:
            return True
        try:
            self._load_voice_card(voice_name)
        except Exception as e:
            print(f"[daemon] ボイス切替失敗 ({voice_name}): {e}", flush=True)
            return False
        write_active_voice(voice_name)
        print(f"[daemon] ボイス切替 → {voice_name}, seed={self._vc.seed}", flush=True)
        return True

    @property
    def speed(self) -> float:
        return float(getattr(self._vc, "speed", 1.0) or 1.0)

    def set_speed(self, speed: float) -> bool:
        """現在ボイスの話速を変更し、config.json に永続化する。"""
        import json as _json
        try:
            speed = max(0.5, min(2.0, float(speed)))
        except (TypeError, ValueError):
            return False
        self._vc.speed = speed
        # config.json を書き戻す (speed のみ更新)
        cfg_path = Path(VOICES_DIR) / self.voice_name / "config.json"
        try:
            data = _json.loads(cfg_path.read_text(encoding="utf-8"))
            data["speed"] = speed
            cfg_path.write_text(_json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except Exception as e:
            print(f"[daemon] 話速保存失敗: {e}", flush=True)
            return False
        print(f"[daemon] 話速変更 → {speed} ({self.voice_name})", flush=True)
        return True

    def _generate_one(self, text: str):
        from engine.audio_utils import trim_silence, trim_interior_pauses, adjust_speed
        vc = self._vc
        clone_temp = vc.clone_temperature if vc.clone_temperature > 0 else -1.0
        # 感情caption (Irodoriクローン): HTTP /say で一時指定があれば優先、
        # 無ければボイスカードの既定感情(default_caption)。clone_promptは
        # 通常モデルのlatentキャッシュなので、caption使用時はエンジン側で
        # ref_wav へフォールバックされる。
        caption = getattr(self, "_caption_override", None)
        if caption is None:
            caption = getattr(vc, "default_caption", "") or ""
        # モデル切替(GPU再ロード)中は完了まで待つ。切替と生成の排他。
        with self._model_lock:
            wav, sr = self._eng.generate_for_script_row(
                voice_type=vc.voice_type,
                text=text,
                language=vc.language,
                instruct="",
                speaker=vc.speaker,
                ref_audio=vc.ref_audio_path,
                ref_text=vc.ref_text,
                voice_description=vc.voice_description,
                seed=vc.seed,
                voice_clone_prompt=self._clone_prompt,
                clone_temperature=clone_temp,
                clone_caption=caption,
            )
        wav = trim_silence(wav, sr)
        # 音声内の「、」「。」等のポーズ上限。0なら無加工。
        # _pause_override が設定されていれば config より優先(HTTP /pause で可変)。
        pause_cap = self._pause_override if self._pause_override is not None \
            else float(getattr(vc, "max_pause_sec", 0.0) or 0.0)
        if pause_cap > 0:
            wav = trim_interior_pauses(wav, sr, pause_cap)
        if getattr(vc, "speed", 1.0) != 1.0:
            wav = adjust_speed(wav, sr, float(vc.speed))
        return wav, sr

    def speak(self, text: str, caption=None):
        """テキストを文分割して順次生成・再生。キャンセル可能。
        caption: この読み上げに限り使う感情caption (None=ボイス既定 default_caption)。"""
        import soundfile as sf

        self._caption_override = caption
        self._cancel.clear()
        sentences = _split_sentences(text)
        print(f"[daemon] {len(sentences)} 文", flush=True)

        OUTPUT_DIR.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        gen_q: queue.Queue = queue.Queue()

        def producer():
            for i, sent in enumerate(sentences):
                if self._cancel.is_set():
                    gen_q.put(None)
                    return
                try:
                    wav, sr = self._generate_one(sent)
                    # 音量適用 (1.0未満なら波形を減衰)
                    if self.volume < 1.0:
                        wav = wav * float(self.volume)
                    p = OUTPUT_DIR / f"noa_tts_{ts}_p{i+1:02d}.wav"
                    sf.write(str(p), wav, sr)
                    gen_q.put(p)
                    print(f"[daemon] 生成 {i+1}/{len(sentences)}", flush=True)
                except Exception as e:
                    print(f"[daemon] 生成失敗: {e}", flush=True)
            gen_q.put(None)

        t = threading.Thread(target=producer, daemon=True)
        t.start()

        # 連続ストリーム再生: デバイスを開きっぱなしで波形を流し込む(継ぎ目なし)。
        player = StreamPlayer()
        self._player = player
        first = True
        try:
            while True:
                if self._cancel.is_set():
                    break
                try:
                    p = gen_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if p is None:
                    break
                if self._cancel.is_set():
                    break
                if not first and tuning._gap_sec > 0:
                    player.feed_silence(tuning._gap_sec)  # 文間ギャップも同一ストリームで(継ぎ目なし)
                first = False
                player.feed_wav(p)  # 生成済みWAVを流し込む(再生終わりまでブロック)
        finally:
            player.close()
            self._player = None

        t.join()

    def cancel(self):
        self._cancel.set()
        # 連続ストリーム再生を即停止(バッファ破棄)
        pl = getattr(self, "_player", None)
        if pl is not None:
            try:
                pl.abort()
            except Exception:
                pass
        # winsound フォールバック経路も一応止める
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
