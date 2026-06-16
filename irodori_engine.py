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


class IrodoriEngine:
    """Irodori-TTS wrapper with TTSEngine-compatible interface."""

    DEFAULT_CHECKPOINT = "Aratako/Irodori-TTS-500M-v3"
    # ボイスデザイン (caption駆動) 専用チェックポイント。通常モデルとは別物。
    VOICEDESIGN_CHECKPOINT = "Aratako/Irodori-TTS-600M-v3-VoiceDesign"

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

        _report(f"[3/4] モデルをGPUにロード中...")
        self._runtime = InferenceRuntime.from_key(
            RuntimeKey(
                checkpoint=checkpoint_path,
                model_device=self.device,
                codec_device=self.device,
                # bf16: 5090で1.5〜2倍高速。irodori_ttsが公式サポート(CUDA時bf16可)。
                # codecはfp32のまま(音質安定優先)。問題あればfp32へ戻す。
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

    def unload(self, voice_type: str | None = None):
        if self._runtime is not None:
            del self._runtime
            self._runtime = None
        if self._vd_runtime is not None:
            del self._vd_runtime
            self._vd_runtime = None
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
        runtime = self._load_vd_runtime() if use_vd else self._load_runtime()
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
        wav, sr = self._synthesize(
            text=text, ref_wav=ref_wav, ref_latent=ref_latent, seed=seed, caption=caption)
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
            # voice_description (キャラ属性) を caption として使う
            caption = voice_description or instruct
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
