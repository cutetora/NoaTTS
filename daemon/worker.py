"""TTSWorker: モデルVRAM常駐・ボイスカード・文分割生成→連続再生。"""
import os
import time
import queue
import hashlib
import datetime
import threading
from pathlib import Path

from daemon import tuning
from .runtime import (
    BASE_DIR, VOICES_DIR, OUTPUT_DIR, CACHE_DIR, CACHE_FLAG_PATH,
    TMP_SAY_DIR, write_active_voice,
)
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
        # 音声キャッシュ(WAV使い回し)。既定OFF。cache.flag が存在すればON。
        # この回だけの上書きは _cache_override (None=既定に従う)。
        self.cache_enabled = CACHE_FLAG_PATH.exists()
        self._cache_override = None
        self._load()

    def set_cache(self, enabled) -> bool:
        """音声キャッシュの既定ON/OFFを設定。cache.flag で永続化。"""
        on = bool(enabled)
        self.cache_enabled = on
        try:
            if on:
                CACHE_FLAG_PATH.write_text("1", encoding="utf-8")
            elif CACHE_FLAG_PATH.exists():
                CACHE_FLAG_PATH.unlink()
        except Exception:
            pass
        return on

    def clear_cache(self) -> int:
        """キャッシュ済みWAVを全削除。削除した件数を返す。"""
        n = 0
        try:
            if CACHE_DIR.is_dir():
                for f in CACHE_DIR.glob("*.wav"):
                    try:
                        f.unlink(); n += 1
                    except Exception:
                        pass
        except Exception:
            pass
        return n

    def _cache_on(self) -> bool:
        """この読み上げでキャッシュを使うか。_cache_override 優先、無ければ既定。"""
        if self._cache_override is not None:
            return bool(self._cache_override)
        return bool(self.cache_enabled)

    def _cache_path(self, text, vc, caption, pause_cap, speed):
        """文+声+感情+速度+ポーズ上限 から一意なキャッシュファイルパスを作る。
        どれか1つでも変われば別ファイルになる(別音声として扱う)。"""
        voice_id = getattr(vc, "name", None) or getattr(vc, "voice_type", "") or self.voice_name
        seed = getattr(vc, "seed", "")
        key = "\x1f".join([
            str(voice_id), str(text), str(caption or ""),
            f"{float(speed or 1.0):.4f}", f"{float(pause_cap or 0.0):.4f}",
            str(seed),
        ])
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{h}.wav"

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
        if repo_id == self._model_repo:
            return True
        # 進行中の読み上げを止めてから切替 (待ち時間短縮)
        self.cancel()
        with self._model_lock:
            try:
                # VoiceDesign も通常ランタイムとして読み上げ本体に使える
                # (検証済: caption 無しでも合成可)。読み上げ本体として恒久ロードし、
                # vd_checkpoint も合わせて caption 付き読み上げと整合させる。
                self._eng.unload()
                self._eng.checkpoint = repo_id
                self._eng._runtime = None
                self._eng._load_runtime()
                self._model_repo = repo_id
                if is_vd:
                    # caption 付き読み上げ時の vd ランタイムも同じモデルに揃える
                    self._eng.vd_checkpoint = repo_id
                    self._eng._vd_runtime = None
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
        # 読み上げ本体は irodori_checkpoint に保存し、再起動後も選択を保持する。
        # VoiceDesign を本体にした場合は vd_checkpoint も揃えておく。
        try:
            from config import AppConfig
            cfg = AppConfig.load()
            cfg.irodori_checkpoint = repo_id
            if is_vd:
                cfg.irodori_vd_checkpoint = repo_id
            cfg.save()
        except Exception:
            pass
        print(f"[daemon] モデル切替 → {repo_id}", flush=True)
        return True

    def _load_voice_card(self, voice_name: str):
        """ボイスカードと clone_prompt を読み込む。エンジンは再利用 (切替で再呼出可)。"""
        import pickle
        from voice.voice_manager import VoiceManager

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

    def _gen_core(self, text, vc, clone_prompt, caption, pause_cap, speed):
        """1文を合成して後処理した波形 (wav, sr) を返す中核。
        /say と /say_wav の双方から呼ぶ。self の可変状態は読まない(引数で受ける)ので、
        渡す引数さえスレッドローカルなら並行安全。エンジン呼び出しは _model_lock で排他。"""
        from engine.audio_utils import trim_silence, trim_interior_pauses, adjust_speed
        clone_temp = vc.clone_temperature if vc.clone_temperature > 0 else -1.0
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
                voice_clone_prompt=clone_prompt,
                clone_temperature=clone_temp,
                clone_caption=caption,
            )
        wav = trim_silence(wav, sr)
        if pause_cap and pause_cap > 0:
            wav = trim_interior_pauses(wav, sr, pause_cap)
        if speed and float(speed) != 1.0:
            wav = adjust_speed(wav, sr, float(speed))
        return wav, sr

    def _generate_one(self, text: str, vc=None, clone_prompt=None, caption=None):
        """1文を合成(+キャッシュ)する。
        vc/clone_prompt が None ならアクティブ声(self._vc)を使う。
        複数キャラ読み上げでは呼び出し側が一時ロードした vc を渡す。
        caption が None なら _caption_override → ボイス既定 の順でフォールバック。"""
        if vc is None:
            vc = self._vc
            clone_prompt = self._clone_prompt
        # 感情caption (Irodoriクローン): 引数指定 > HTTP /say の一時指定 > ボイス既定。
        # clone_promptは通常モデルのlatentキャッシュなので、caption使用時はエンジン側で
        # ref_wav へフォールバックされる。
        if caption is None:
            caption = getattr(self, "_caption_override", None)
        if caption is None:
            caption = getattr(vc, "default_caption", "") or ""
        # 音声内の「、」「。」等のポーズ上限。0なら無加工。
        # _pause_override が設定されていれば config より優先(HTTP /pause で可変)。
        pause_cap = self._pause_override if self._pause_override is not None \
            else float(getattr(vc, "max_pause_sec", 0.0) or 0.0)
        speed = getattr(vc, "speed", 1.0)

        # ── 音声キャッシュ(使い回し) ──
        # ON時: 同じ文+声+感情+速度+ポーズのWAVが cache/ にあれば合成せず読み込む。
        if self._cache_on():
            import soundfile as sf
            cpath = self._cache_path(text, vc, caption, pause_cap, speed)
            if cpath.exists():
                try:
                    wav, sr = sf.read(str(cpath), dtype="float32")
                    print(f"[daemon] cache hit: {cpath.name}", flush=True)
                    return wav, sr
                except Exception as e:
                    print(f"[daemon] cache読み込み失敗(再生成): {e}", flush=True)
            wav, sr = self._gen_core(text, vc, clone_prompt, caption, pause_cap, speed)
            try:
                CACHE_DIR.mkdir(exist_ok=True)
                sf.write(str(cpath), wav, sr)
                print(f"[daemon] cache保存: {cpath.name}", flush=True)
            except Exception as e:
                print(f"[daemon] cache保存失敗: {e}", flush=True)
            return wav, sr

        return self._gen_core(text, vc, clone_prompt, caption, pause_cap, speed)

    def _load_vc_only(self, voice_name: str):
        """指定ボイスの (vc, clone_prompt) を self を汚さず読み込んで返す。
        /say_wav の voice 引数用 (アクティブ声を切り替えない)。同checkpoint前提。"""
        import pickle
        from voice.voice_manager import VoiceManager

        vm = VoiceManager(VOICES_DIR)
        vc = vm.load_voice(voice_name)
        clone_prompt = None
        if vc.clone_prompt_path and os.path.exists(vc.clone_prompt_path):
            if vc.clone_prompt_path.endswith(".pt"):
                clone_prompt = vc.clone_prompt_path  # Irodori latent: パス文字列のまま
            else:
                with open(vc.clone_prompt_path, "rb") as f:
                    clone_prompt = pickle.load(f)
        return vc, clone_prompt

    def synthesize_wav(self, text: str, voice=None, speed=None):
        """text を鳴らさずに合成し、結合した1本の波形 (wav, sr=ネイティブ) を返す。
        /say_wav 用。再生せず・output/ に依存せず・アクティブ声を切り替えない。
        voice: None/アクティブ声と同じなら現在の声、別IDなら一時ロードして使用(同checkpoint前提)。
        speed: 倍率(省略時はボイスカードの speed)。
        並行安全: self の override 類(caption/pause/volume)を一切触らない。"""
        import numpy as np

        if voice and voice != self.voice_name:
            vc, clone_prompt = self._load_vc_only(voice)
        else:
            vc, clone_prompt = self._vc, self._clone_prompt

        caption = getattr(vc, "default_caption", "") or ""
        pause_cap = float(getattr(vc, "max_pause_sec", 0.0) or 0.0)
        if speed is not None and float(speed) > 0:
            spd = float(speed)
        else:
            spd = float(getattr(vc, "speed", 1.0) or 1.0)

        sentences = _split_sentences(text)
        gap = float(getattr(tuning, "_gap_sec", 0.15) or 0.0)

        parts = []
        sr = None
        for sent in sentences:
            wav, sr = self._gen_core(sent, vc, clone_prompt, caption, pause_cap, spd)
            parts.append(np.asarray(wav, dtype=np.float32))

        if not parts or sr is None:
            raise RuntimeError("no audio generated")

        if gap > 0 and len(parts) > 1:
            sil = np.zeros(int(gap * sr), dtype=np.float32)
            merged = parts[0]
            for p in parts[1:]:
                merged = np.concatenate([merged, sil, p])
        else:
            merged = parts[0] if len(parts) == 1 else np.concatenate(parts)
        # 末尾余韻: 語尾が trim_silence で切れるのを防ぐ無音を足す。
        tail = float(getattr(tuning, "_tail_pad_sec", 0.0) or 0.0)
        if tail > 0:
            merged = np.concatenate([merged, np.zeros(int(tail * sr), dtype=np.float32)])
        return merged, sr

    def speak(self, text: str, caption=None, cache=None):
        """テキストを文分割して順次生成・再生。キャンセル可能。
        caption: この読み上げに限り使う感情caption (None=ボイス既定 default_caption)。
        cache:   この読み上げに限るキャッシュON/OFF上書き (None=既定 cache_enabled に従う)。"""
        import soundfile as sf

        self._caption_override = caption
        self._cache_override = cache
        self._cancel.clear()
        sentences = _split_sentences(text)
        print(f"[daemon] {len(sentences)} 文", flush=True)

        # 読み上げの使い捨てWAVは tmp_say/ へ(一括生成の output/ とは分離)。
        # daemon起動時に掃除されるので増え続けない。
        TMP_SAY_DIR.mkdir(exist_ok=True)
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
                    p = TMP_SAY_DIR / f"noa_tts_{ts}_p{i+1:02d}.wav"
                    sf.write(str(p), wav, sr)
                    gen_q.put(p)
                    # 1文ぶんの合成が完了 → GPU作業バッファを即破棄する。これをしないと
                    # PyTorch が各文のキャッシュを抱えたまま reserved が文をまたいで
                    # せり上がり、長文ほど高止まりする(実測 982→2786MB)。1文ごとに捨てれば
                    # reserved は ~1.5GB で平らに保てる。次文は再確保するが合成は再生より
                    # ずっと速い(RTF<<1)のでストリーミングは途切れない。
                    try:
                        import torch as _torch
                        if _torch.cuda.is_available():
                            _torch.cuda.empty_cache()
                    except Exception:
                        pass
                    print(f"[daemon] 生成 {i+1}/{len(sentences)}", flush=True)
                except Exception as e:
                    print(f"[daemon] 生成失敗: {e}", flush=True)
            gen_q.put(None)

        self._run_play_loop(producer, gen_q)

    def speak_dialogue(self, segments, cache=None):
        """複数キャラの掛け合いを声を切り替えながら連続再生する。
        segments: [{"voice": "<声ID|None>", "text": "...", "caption": "<任意>"}, ...]
                  voice 省略/None はアクティブ声。別IDは一時ロード(同checkpoint前提)。
        cache:    キャッシュON/OFF上書き (None=既定に従う)。各セグメントの
                  文+声+感情+速度でキャッシュされる。
        声切替は1セグメントごと。大量キャラでなければ都度ロードのコストは軽い。"""
        import soundfile as sf

        self._cache_override = cache
        self._cancel.clear()

        # セグメントを正規化(空textは捨てる)。
        segs = []
        for s in (segments or []):
            if not isinstance(s, dict):
                continue
            txt = str(s.get("text", "") or "").strip()
            if not txt:
                continue
            segs.append({
                "voice": (str(s.get("voice", "") or "").strip() or None),
                "text": txt,
                "caption": (str(s.get("caption", "") or "").strip() or None),
            })
        if not segs:
            print("[daemon] dialogue: 有効なセグメントなし", flush=True)
            return
        print(f"[daemon] dialogue {len(segs)} セグメント", flush=True)

        TMP_SAY_DIR.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # 声カードのロードはコストがあるので同一声は使い回す(セグメント間キャッシュ)。
        vc_cache = {}

        def resolve_vc(voice):
            if not voice or voice == self.voice_name:
                return self._vc, self._clone_prompt
            if voice not in vc_cache:
                vc_cache[voice] = self._load_vc_only(voice)
            return vc_cache[voice]

        gen_q: queue.Queue = queue.Queue()

        def producer():
            idx = 0
            for s in segs:
                if self._cancel.is_set():
                    gen_q.put(None)
                    return
                try:
                    vc, clone_prompt = resolve_vc(s["voice"])
                except Exception as e:
                    print(f"[daemon] dialogue 声ロード失敗 ({s['voice']}): {e}", flush=True)
                    continue
                # セグメント本文をさらに文分割して順次合成(間が空きすぎないように)。
                for sent in _split_sentences(s["text"]):
                    if self._cancel.is_set():
                        gen_q.put(None)
                        return
                    try:
                        wav, sr = self._generate_one(
                            sent, vc=vc, clone_prompt=clone_prompt, caption=s["caption"])
                        if self.volume < 1.0:
                            wav = wav * float(self.volume)
                        idx += 1
                        p = TMP_SAY_DIR / f"noa_tts_{ts}_d{idx:03d}.wav"
                        sf.write(str(p), wav, sr)
                        gen_q.put(p)
                        try:
                            import torch as _torch
                            if _torch.cuda.is_available():
                                _torch.cuda.empty_cache()
                        except Exception:
                            pass
                        print(f"[daemon] dialogue 生成 {idx} ({s['voice'] or self.voice_name})", flush=True)
                    except Exception as e:
                        print(f"[daemon] dialogue 生成失敗: {e}", flush=True)
            gen_q.put(None)

        self._run_play_loop(producer, gen_q)

    def _run_play_loop(self, producer, gen_q):
        """producer が gen_q に積む WAV パスを、連続ストリームで途切れなく再生する。
        speak() / speak_dialogue() 共通の再生ループ。None で終端。"""
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
            # 末尾余韻: 最後の文の語尾が trim_silence で切り詰められているため、
            # close 前に無音を流して「最後まで鳴り切ってから」閉じる(語尾欠け防止)。
            if not first and not self._cancel.is_set() and tuning._tail_pad_sec > 0:
                player.feed_silence(tuning._tail_pad_sec)
        finally:
            player.close()
            self._player = None

        t.join()

        # 感情caption で一時ロードされた VoiceDesign 第二モデル(~2GB)を解放する。
        # これをしないと caption を一度使っただけで VD が居座り続け、アイドルでも
        # 本体(int4 ~1.3GB)+VD で ~3.5GB のままになる。emoji 駆動の感情運用では
        # VD を常駐させる必要がないので、読み上げ後に落として VRAM を返す。
        try:
            self._eng.release_vd()
        except Exception:
            pass

        # 読み上げ完了 → アイドル。合成で積もった作業バッファ(CUDAアロケータの
        # reserved 高水位 / Triton ワークスペース)を返す。合成中ではなくアイドル時に
        # 呼ぶので体感速度に影響しない。次の合成は僅かに再確保コストがかかるが、
        # reserved が際限なく肥大して /vram の noa がモデル本体(~1.2GB)より大きく
        # 見える問題を抑える。
        try:
            import gc
            import torch
            if torch.cuda.is_available():
                gc.collect()
                torch.cuda.empty_cache()
        except Exception:
            pass

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
