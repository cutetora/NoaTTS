"""
Irodori-TTS engine wrapper (TTSEngine互換インターフェース).
v3 (Aratako/Irodori-TTS-500M-v3) を使用。

Qwen3-TTSとの主な違い:
- CustomVoice (既存スピーカー) なし
- 主にボイスクローンに使用

ボイスデザイン (caption で声を指定):
- 専用モデル Aratako/Irodori-TTS-600M-v3-VoiceDesign が必要。
- 通常モデルとは別に遅延ロードする (使う時だけDL/VRAM常駐)。
- SamplingRequest.caption に声の説明文を渡すと、その声で生成される。
"""

import os
import numpy as np
import torch


# ── int4 (lite) ランタイム組込み ─────────────────────────────
# kizuna-intelligence/Irodori-TTS-*-int4 を、標準の InferenceRuntime.from_key 経由で
# 読めるようにする。irodori_tts_lite.patch() が from_key にフックを差し込み、4bit重みを
# 直接読める。checkpoint 名に "int4" を含む時だけ発動し、通常モデルには触れない。冪等。
_LITE_PATCHED = False


def _is_int4_checkpoint(ckpt: "str | None") -> bool:
    return "int4" in (ckpt or "").lower()


def _ensure_lite_patched():
    """int4 チェックポイントを読む前に一度だけ呼ぶ。lite ランタイムのパッチと、
    版ズレ吸収シム (int4 ckpt の新しい ModelConfig キーを落とす) を仕込む。"""
    global _LITE_PATCHED
    if _LITE_PATCHED:
        return
    import irodori_tts_lite
    # int4 重みは Triton カーネルが fp16 ネイティブ。force_fp16 で全体を fp16 化する
    # (from_key には precision="bf16" を渡すが、ここで fp16 に矯正される)。
    irodori_tts_lite.configure(use_fused=True, force_fp16=True)
    irodori_tts_lite.patch()
    # int4 ckpt の config_json は現行 irodori_tts より新しいキー (duration_uncertainty
    # 系 / max_text_len 等) を含むことがある。ModelConfig が未知キーで落ちるのを防ぐため、
    # 受け付けないキーを除去して構築する (通常 ckpt では落とすキーが無く無害)。
    import dataclasses
    import irodori_tts.config as _cfgmod
    _orig = _cfgmod.ModelConfig
    _fields = {f.name for f in dataclasses.fields(_orig)}

    def _model_config_shim(**kwargs):
        return _orig(**{k: v for k, v in kwargs.items() if k in _fields})

    _cfgmod.ModelConfig = _model_config_shim
    _LITE_PATCHED = True


class IrodoriEngine:
    """Irodori-TTS wrapper with TTSEngine-compatible interface."""

    DEFAULT_CHECKPOINT = "Aratako/Irodori-TTS-500M-v3"
    # ボイスデザイン (caption駆動) 専用チェックポイント。通常モデルとは別物。
    VOICEDESIGN_CHECKPOINT = "Aratako/Irodori-TTS-600M-v3-VoiceDesign"
    # 軽量モード用 int4 量子化チェックポイント (約1.5GB)。_is_int4_checkpoint で
    # 検知され、from_key 前に lite ランタイムが自動で仕込まれる。
    LIGHT_CHECKPOINT = "kizuna-intelligence/Irodori-TTS-500M-v3-int4"

    # For UI compatibility (Qwen3-TTS uses these)
    SPEAKERS = []  # Irodori has no built-in speakers
    LANGUAGES = ["Japanese"]  # Irodori is Japanese-only

    def __init__(self, model_size: str = "500M-v3", device: str = "cuda:0",
                 checkpoint: str | None = None, vd_checkpoint: str | None = None):
        self.model_size = model_size
        self.device = device
        # 使用モデル。指定が無ければクラス定数の既定を使う (設定UIから上書き可)。
        self.checkpoint = checkpoint or self.DEFAULT_CHECKPOINT
        self.vd_checkpoint = vd_checkpoint or self.VOICEDESIGN_CHECKPOINT
        self._runtime = None
        self._vd_runtime = None  # VoiceDesign専用ランタイム (遅延ロード)
        self._optimized: set = set()

    @property
    def loaded_models(self) -> list[str]:
        return ["irodori"] if self._runtime is not None else []

    def _load_runtime(self, on_progress=None):
        if self._runtime is not None:
            return self._runtime

        def _report(msg):
            if on_progress:
                on_progress(msg)

        _report("[1/4] irodori_tts ライブラリ読み込み中...")
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        from huggingface_hub import hf_hub_download

        _report(f"[2/4] HuggingFace から checkpoint DL/取得中 ({self.checkpoint})...")
        checkpoint_path = hf_hub_download(
            repo_id=self.checkpoint,
            filename="model.safetensors",
        )

        # int4 (lite) チェックポイントなら、from_key の前に lite ランタイムを仕込む。
        if _is_int4_checkpoint(self.checkpoint):
            _ensure_lite_patched()

        _report(f"[3/4] モデルをGPUにロード中...")
        self._runtime = InferenceRuntime.from_key(
            RuntimeKey(
                checkpoint=checkpoint_path,
                model_device=self.device,
                codec_device=self.device,
                # bf16: 5090で1.5〜2倍高速。irodori_ttsが公式サポート(CUDA時bf16可)。
                # codecはfp32のまま(音質安定優先)。問題あればfp32へ戻す。
                # int4 (lite) の場合は _ensure_lite_patched の force_fp16 で fp16 に矯正される。
                model_precision="bf16",
                codec_precision="fp32",
            )
        )
        _report("[4/4] モデル準備完了")
        return self._runtime

    def _load_vd_runtime(self, on_progress=None):
        """ボイスデザイン専用ランタイムを遅延ロードする (caption対応モデル)。
        通常ランタイムとは別物。初回呼び出し時にDL/GPUロードする。"""
        if self._vd_runtime is not None:
            return self._vd_runtime

        def _report(msg):
            if on_progress:
                on_progress(msg)

        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        from huggingface_hub import hf_hub_download

        _report(f"[VD 1/3] VoiceDesignモデルDL/取得中 ({self.vd_checkpoint})...")
        checkpoint_path = hf_hub_download(
            repo_id=self.vd_checkpoint,
            filename="model.safetensors",
        )
        _report("[VD 2/3] VoiceDesignモデルをGPUにロード中...")
        self._vd_runtime = InferenceRuntime.from_key(
            RuntimeKey(
                checkpoint=checkpoint_path,
                model_device=self.device,
                codec_device=self.device,
                model_precision="bf16",
                codec_precision="fp32",
            )
        )
        _report("[VD 3/3] VoiceDesign準備完了")
        return self._vd_runtime

    def _load_model(self, voice_type: str, on_progress=None):
        """Compatibility shim for Qwen3-TTS API."""
        return self._load_runtime(on_progress=on_progress)

    def release_vd(self):
        """VoiceDesign 第二ランタイムだけを解放する (本体ランタイムは残す)。
        caption(感情指定)使用時に VD(~2GB)がロードされ常駐するが、emoji 駆動の感情運用
        では読み上げ後に落として VRAM を返す。次の caption 使用時に再ロードされる。
        VD が未ロードなら何もしない。"""
        if self._vd_runtime is None:
            return
        del self._vd_runtime
        self._vd_runtime = None
        import gc
        gc.collect()
        torch.cuda.empty_cache()

    def unload(self, voice_type: str | None = None):
        if self._runtime is not None:
            del self._runtime
            self._runtime = None
        if self._vd_runtime is not None:
            del self._vd_runtime
            self._vd_runtime = None
        # del しただけでは Python GC が旧ランタイムを回収する前に empty_cache が
        # 走り、まだ参照の生きた CUDA メモリを解放できない。gc.collect() で先に
        # 回収してから空にすることで、モデル切替を繰り返した際の reserved 漸増を抑える。
        import gc
        gc.collect()
        torch.cuda.empty_cache()

    # ── Generation methods ──

    def encode_reference_latent(self, ref_wav: str, save_path: str) -> str:
        """参照音声を一度だけ codec で latent にエンコードして .pt 保存する。
        以降の生成で ref_latent としてこれを渡せば、毎回のWAV読込+エンコードを
        省略でき高速化する (2文目以降が速くなる)。save_path を返す。"""
        import torch as _torch
        from irodori_tts.inference_runtime import _load_audio
        rt = self._load_runtime()
        wav, sr = _load_audio(ref_wav)
        latent = rt.codec.encode_waveform(
            wav.unsqueeze(0), sample_rate=int(sr),
            normalize_db=-16.0, ensure_max=True,
        ).cpu()
        _torch.save(latent, save_path)
        return save_path

    def _synthesize(
        self,
        text: str,
        ref_wav: str | None = None,
        no_ref: bool = False,
        seed: int | None = None,
        num_steps: int = 40,
        caption: str | None = None,
        ref_latent: str | None = None,
    ) -> tuple[np.ndarray, int]:
        """Core synthesis method.

        caption を渡すとボイスデザイン (声をテキストで指定) になり、
        VoiceDesign専用ランタイムで生成する。caption が無ければ通常ランタイム。
        ref_latent (.pt パス) を渡すと、毎回の参照音声エンコードを省略して高速化。"""
        from irodori_tts.inference_runtime import SamplingRequest

        use_vd = bool(caption and caption.strip())
        if use_vd:
            # 本体ランタイムが既に caption 対応 (VoiceDesign 等) なら、それを再利用して
            # 第二ランタイムの二重ロードを避ける (VD を読み上げ本体にした時の VRAM 節約:
            # 通常500M+VD600M の二重常駐 ~5.7GB → VD単体 ~2GB)。本体が通常モデルの時だけ
            # 専用 VoiceDesign ランタイムを別途ロードする。
            main = self._runtime
            if main is not None and getattr(
                    getattr(main, "model_cfg", None), "use_caption_condition", False):
                runtime = main
            else:
                runtime = self._load_vd_runtime()
        else:
            runtime = self._load_runtime()
        req_kwargs = {
            "text": text,
            "no_ref": no_ref,
            "num_steps": num_steps,
        }
        if use_vd:
            req_kwargs["caption"] = caption.strip()
        # ref_latent (エンコード済み) があれば優先、無ければ ref_wav
        if ref_latent:
            req_kwargs["ref_latent"] = ref_latent
        elif ref_wav:
            req_kwargs["ref_wav"] = ref_wav
        if seed is not None and seed >= 0:
            req_kwargs["seed"] = seed

        req = SamplingRequest(**req_kwargs)
        result = runtime.synthesize(req, log_fn=None)

        # Extract audio
        if hasattr(result, "audio"):
            audio = result.audio
        elif hasattr(result, "audios"):
            audio = result.audios[0] if isinstance(result.audios, (list, tuple)) else result.audios
        else:
            raise RuntimeError("Irodori result has no audio attribute")

        # Convert tensor to numpy if needed
        if hasattr(audio, "cpu"):
            audio = audio.cpu().numpy()
        if audio.ndim > 1:
            audio = audio.squeeze()

        sr = getattr(result, "sample_rate", 24000)
        return audio.astype(np.float32), sr

    def generate_custom_voice(
        self,
        text: str,
        language: str = "Japanese",
        speaker: str = "",
        instruct: str = "",
        num_samples: int = 1,
    ) -> list[tuple[np.ndarray, int]]:
        """Irodori has no custom voice mode → fall back to no_ref."""
        results = []
        for _ in range(num_samples):
            wav, sr = self._synthesize(text=text, no_ref=True)
            results.append((wav, sr))
        return results

    def generate_voice_design(
        self,
        text: str,
        language: str = "Japanese",
        instruct: str = "",
        num_samples: int = 1,
        seed: int = -1,
    ) -> list[tuple[tuple[np.ndarray, int], int]]:
        """声の説明 (instruct=caption) から声を生成する。
        Returns list of ((wav, sr), seed_used) tuples."""
        import random
        caption = instruct  # UIの「声の説明」が caption になる
        results = []
        for _ in range(num_samples):
            s = seed if seed >= 0 else random.randint(0, 2**31 - 1)
            torch.manual_seed(s)
            wav, sr = self._synthesize(text=text, no_ref=True, seed=s, caption=caption)
            results.append(((wav, sr), s))
        return results

    def extract_clone_prompt(self, ref_audio: str, ref_text: str):
        """参照音声を latent にエンコードしてキャッシュ(.pt)を作り、そのパスを返す。
        以降のクローン生成でこれを ref_latent として使うと毎回のエンコードを省ける。
        エンコード失敗時は ref_audio パスをそのまま返す(従来動作にフォールバック)。"""
        try:
            cache_path = os.path.join(os.path.dirname(ref_audio), "clone_prompt.pt")
            return self.encode_reference_latent(ref_audio, cache_path)
        except Exception as e:
            print(f"[irodori] latentキャッシュ生成失敗、ref_audioにフォールバック: {e}")
            return ref_audio

    def generate_voice_clone(
        self,
        text: str,
        language: str = "Japanese",
        ref_audio: str = "",
        ref_text: str = "",
        voice_clone_prompt=None,
        temperature: float = -1.0,
        seed: int = -1,
        clone_caption: str = "",
    ) -> list[tuple[np.ndarray, int]]:
        # voice_clone_prompt: Irodoriでは latentキャッシュ(.pt) か ref_audioパス(str)。
        # .pt (エンコード済みlatent) なら ref_latent として渡し、毎回のエンコードを省略。
        # clone_caption: 感情/スタイルの自由文。指定すると VoiceDesignモデルに切替わり
        #   「参照音声=声 + caption=感情」で生成する (v3 VoiceDesign の style-controlled cloning)。
        ref_latent = None
        ref_wav = ref_audio
        caption = (clone_caption or "").strip() or None
        # clone の感情caption は VoiceDesign(別モデル ~2GB)をロードしてしまう。本体が
        # caption非対応(通常/int4 クローン)の場合、感情は emoji 駆動で出す方針なので、
        # caption を無視して VD を一切ロードしない(VRAM節約: caption使用後の ~3.5GB 常駐を防ぐ)。
        # 本体が caption対応(VoiceDesign を読み上げ本体にした場合)なら _synthesize 側で
        # 本体を再利用するため、ここでは caption をそのまま活かす。
        if caption is not None:
            _main = self._runtime
            _main_caption_ok = _main is not None and getattr(
                getattr(_main, "model_cfg", None), "use_caption_condition", False)
            if not _main_caption_ok:
                caption = None
        if isinstance(voice_clone_prompt, str) and voice_clone_prompt:
            if voice_clone_prompt.endswith(".pt") and os.path.exists(voice_clone_prompt):
                # latentキャッシュは通常モデルでエンコードされている。caption使用時は
                # VoiceDesignモデルに切替わるため整合せず、ref_wav から取り直す。
                if caption:
                    ref_wav = ref_audio
                else:
                    ref_latent = voice_clone_prompt  # 高速パス (latentキャッシュ)
            else:
                ref_wav = voice_clone_prompt
        # 参照音声(ref_wav/ref_latent)が無ければ no_ref で生成する。
        # デザイン/カスタム声を caption 付きで呼んだ場合などに「Specify either
        # ref_wav/ref_latent, or set no_ref=True」で落ちるのを防ぐ。
        ref_wav_ok = bool(ref_wav) and (not isinstance(ref_wav, str) or os.path.exists(ref_wav))
        no_ref = not (ref_latent or ref_wav_ok)
        wav, sr = self._synthesize(
            text=text, ref_wav=(ref_wav if ref_wav_ok else None),
            ref_latent=ref_latent, seed=seed, caption=caption, no_ref=no_ref)
        return [(wav, sr)]

    # ── Batch generation for script ──

    def generate_for_script_row(
        self,
        voice_type: str,
        text: str,
        language: str,
        instruct: str = "",
        speaker: str = "",
        ref_audio: str = "",
        ref_text: str = "",
        voice_description: str = "",
        seed: int = -1,
        voice_clone_prompt=None,
        clone_temperature: float = -1.0,
        clone_caption: str = "",
    ) -> tuple[np.ndarray, int]:
        """Generate audio for a single script row based on voice type."""
        if voice_type == "custom":
            # Irodori has no custom voice → use no_ref mode
            results = self.generate_custom_voice(text=text)
            return results[0]
        elif voice_type == "design":
            # voice_description (声の説明=声そのもの) を caption の基底に使う。
            # clone_caption (= カードの既定感情/HTTP一時指定) があれば後ろに重ね、
            # 「同じ声(voice_description)のまま感情だけ変える」を実現する。
            # seed 固定と併せて声を保つが、説明文が伸びる分 声質が多少揺れうる。
            base = voice_description or instruct
            cap = (clone_caption or "").strip()
            caption = f"{base}。{cap}" if (base and cap) else (base or cap)
            results = self.generate_voice_design(
                text=text, instruct=caption, seed=seed)
            return results[0][0]
        elif voice_type == "clone":
            results = self.generate_voice_clone(
                text=text, ref_audio=ref_audio, ref_text=ref_text,
                voice_clone_prompt=voice_clone_prompt, seed=seed,
                clone_caption=clone_caption,
            )
            return results[0]
        else:
            raise ValueError(f"Unknown voice type: {voice_type}")

    @staticmethod
    def build_instruct(
        attribute: str,
        emotion: str,
        instruction: str,
        template: str,
    ) -> str:
        """ボイスデザインの caption 文字列を組み立てる。
        属性・感情・指示を読点でつないだ声の説明文を返す。"""
        parts = [p.strip() for p in (attribute, emotion, instruction) if p and p.strip()]
        return "、".join(parts)
