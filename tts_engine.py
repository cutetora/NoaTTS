import torch
import numpy as np
from pathlib import Path

# TensorFloat32 for Ampere+ GPUs (including Blackwell)
torch.set_float32_matmul_precision("high")


class TTSEngine:
    """Qwen3-TTS wrapper with lazy model loading and inference optimizations."""

    MODEL_MAP = {
        "custom": {
            "1.7B": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            "0.6B": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        },
        "design": {
            "1.7B": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        },
        "clone": {
            "1.7B": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "0.6B": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        },
    }

    SPEAKERS = [
        "Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric",
        "Ryan", "Aiden", "Ono_Anna", "Sohee",
    ]

    LANGUAGES = [
        "Japanese", "Chinese", "English", "Korean",
        "German", "French", "Russian", "Portuguese", "Spanish", "Italian",
    ]

    def __init__(self, model_size: str = "1.7B", device: str = "cuda:0"):
        self.model_size = model_size
        self.device = device
        self._models: dict = {}
        self._optimized: set = set()  # track which models have been optimized

    @property
    def loaded_models(self) -> list[str]:
        return list(self._models.keys())

    def _load_model(self, voice_type: str, on_progress=None):
        if voice_type in self._models:
            return self._models[voice_type]

        def _report(msg):
            if on_progress:
                on_progress(msg)

        size = self.model_size
        if voice_type == "design":
            size = "1.7B"

        model_id = self.MODEL_MAP[voice_type].get(size)
        if not model_id:
            raise ValueError(f"Model not available: type={voice_type}, size={size}")

        _report("[1/5] qwen_tts ライブラリ読み込み中...")
        from qwen_tts import Qwen3TTSModel

        # sdpa is fastest on Blackwell (RTX 5090, SM12.0)
        attn_impl = "sdpa"
        _report(f"[2/5] モデル読み込み中 ({model_id}, {attn_impl})...")

        model = Qwen3TTSModel.from_pretrained(
            model_id,
            device_map=self.device,
            dtype=torch.bfloat16,
            attn_implementation=attn_impl,
        )
        _report("[3/5] GPU にモデル転送完了")

        # Apply inference optimizations (fast_codebook + torch.compile)
        # Skip for clone model - torch.compile conflicts with multiple models
        if voice_type == "clone":
            _report("[4/5] クローンモデルは最適化スキップ (安定性優先)")
        else:
            _report("[4/5] 推論最適化を適用中 (torch.compile + fast_codebook)...")
            try:
                model.enable_streaming_optimizations(
                    decode_window_frames=300,   # larger window for non-streaming
                    use_compile=True,
                    use_cuda_graphs=False,      # variable sizes, not needed
                    compile_mode="max-autotune",
                    use_fast_codebook=True,
                    compile_codebook_predictor=True,
                    compile_talker=True,
                )
                self._optimized.add(voice_type)
            except Exception as e:
                # Fall back to unoptimized if something fails
                _report(f"[4/5] 最適化スキップ: {e}")

        _report("[5/5] モデル準備完了")
        self._models[voice_type] = model
        return model

    def unload(self, voice_type: str | None = None):
        if voice_type:
            m = self._models.pop(voice_type, None)
            if m:
                del m
            self._optimized.discard(voice_type)
        else:
            self._models.clear()
            self._optimized.clear()
        torch.cuda.empty_cache()

    # ── Generation methods ──

    # Default repetition penalty to reduce TTS hallucination/looping
    DEFAULT_REPETITION_PENALTY = 1.3

    def generate_custom_voice(
        self,
        text: str,
        language: str = "Japanese",
        speaker: str = "Ono_Anna",
        instruct: str = "",
        num_samples: int = 1,
    ) -> list[tuple[np.ndarray, int]]:
        model = self._load_model("custom")
        results = []
        for _ in range(num_samples):
            wavs, sr = model.generate_custom_voice(
                text=text, language=language,
                speaker=speaker, instruct=instruct,
                repetition_penalty=self.DEFAULT_REPETITION_PENALTY,
            )
            results.append((wavs[0], sr))
        return results

    def generate_voice_design(
        self,
        text: str,
        language: str = "Japanese",
        instruct: str = "",
        num_samples: int = 1,
        seed: int = -1,
    ) -> list[tuple[tuple[np.ndarray, int], int]]:
        """Returns list of ((wav, sr), seed_used) tuples."""
        import random
        model = self._load_model("design")
        results = []
        for _ in range(num_samples):
            # Seed management: -1 = random, else fixed
            if seed >= 0:
                s = seed
            else:
                s = random.randint(0, 2**31 - 1)
            torch.manual_seed(s)
            torch.cuda.manual_seed_all(s)

            wavs, sr = model.generate_voice_design(
                text=text, language=language, instruct=instruct,
                repetition_penalty=self.DEFAULT_REPETITION_PENALTY,
            )
            results.append(((wavs[0], sr), s))
        return results

    def extract_clone_prompt(
        self,
        ref_audio: str,
        ref_text: str,
    ):
        """Extract voice_clone_prompt from ref_audio (one-time, then cache)."""
        model = self._load_model("clone")
        prompt = model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        return prompt

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
        # clone_caption は Irodori の VoiceDesign クローン専用。Qwen3 は非対応のため
        # インターフェース互換のために受け取るだけで無視する。
        model = self._load_model("clone")

        # Seed
        if seed >= 0:
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)

        # Build kwargs - aggressive stability for cloning
        kwargs = {"repetition_penalty": self.DEFAULT_REPETITION_PENALTY}
        if temperature > 0:
            kwargs["temperature"] = temperature
            # When temperature is low, also constrain top_p/top_k for stability
            kwargs["top_p"] = 0.7
            kwargs["top_k"] = 30

        if voice_clone_prompt is not None:
            wavs, sr = model.generate_voice_clone(
                text=text, language=language,
                voice_clone_prompt=voice_clone_prompt,
                **kwargs,
            )
        else:
            wavs, sr = model.generate_voice_clone(
                text=text, language=language,
                ref_audio=ref_audio, ref_text=ref_text,
                **kwargs,
            )
        return [(wavs[0], sr)]

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
        # clone_caption は Irodori VoiceDesign クローン専用。Qwen3 は無視。
        if voice_type == "custom":
            results = self.generate_custom_voice(
                text=text, language=language, speaker=speaker, instruct=instruct
            )
            return results[0]
        elif voice_type == "design":
            full_instruct = voice_description
            if instruct:
                full_instruct = f"{voice_description}。{instruct}"
            results = self.generate_voice_design(
                text=text, language=language, instruct=full_instruct, seed=seed
            )
            return results[0][0]  # ((wav, sr), seed) -> (wav, sr)
        elif voice_type == "clone":
            results = self.generate_voice_clone(
                text=text, language=language,
                ref_audio=ref_audio, ref_text=ref_text,
                voice_clone_prompt=voice_clone_prompt,
                temperature=clone_temperature,
                seed=seed,
            )
            return results[0]
        else:
            raise ValueError(f"Unknown voice type: {voice_type}")

    # ── Instruct builder ──

    @staticmethod
    def build_instruct(
        attribute: str,
        emotion: str,
        instruction: str,
        template: str,
    ) -> str:
        """Build instruct string with priority: attribute > emotion > instruction."""
        parts = []
        if attribute:
            parts.append(
                f"【最重要】あなたは{attribute}な性格です。"
                f"この性格を最も強く反映してください。"
            )
        if emotion:
            parts.append(f"感情は「{emotion}」。")
        if instruction:
            parts.append(instruction)
        return "".join(parts)
