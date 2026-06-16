import json
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict, field


@dataclass
class VoiceConfig:
    """Character voice card - stores all info needed to reproduce a voice."""
    name: str
    voice_type: str  # "custom", "design", "clone"
    language: str = "Japanese"
    # Character attribute (used as top-priority instruct in batch generation)
    attribute: str = ""
    # CustomVoice
    speaker: str = ""
    # VoiceDesign
    voice_description: str = ""
    seed: int = -1  # -1 = random, else fixed seed for voice consistency
    # VoiceClone
    ref_audio_path: str = ""
    ref_text: str = ""
    clone_temperature: float = -1.0  # -1 = default, 0.1-1.0 = fixed
    clone_prompt_path: str = ""  # cached voice_clone_prompt file
    # Irodori VoiceDesign クローンの既定感情/スタイル (caption)。
    # 空なら無し。デーモン読み上げ・バッチ生成でこの声の基底トーンとして使う。
    default_caption: str = ""
    # 話速 (生成後のtime_stretch倍率: 1.0=等倍, 1.2=20%速く, 0.9=10%遅く)
    speed: float = 1.0
    # 文中の最大ポーズ秒数 (0.0=無効, 例:0.3=これより長い無音を0.3秒に切り詰め)
    max_pause_sec: float = 0.0
    # Sample
    sample_audio_path: str = ""
    # Usage tracking
    last_used_at: str = ""  # "YYYY-MM-DD HH:MM:SS"


class VoiceManager:
    def __init__(self, voices_dir: str):
        self.voices_dir = Path(voices_dir)
        self.voices_dir.mkdir(parents=True, exist_ok=True)

    def save_voice(
        self,
        config: VoiceConfig,
        sample_audio=None,
        sample_sr: int = 24000,
        ref_audio_data=None,
        ref_sr: int = 24000,
    ):
        import soundfile as sf

        voice_dir = self.voices_dir / config.name
        voice_dir.mkdir(parents=True, exist_ok=True)

        if sample_audio is not None:
            p = voice_dir / "sample.wav"
            sf.write(str(p), sample_audio, sample_sr)
            config.sample_audio_path = str(p)

        if ref_audio_data is not None:
            p = voice_dir / "ref_audio.wav"
            sf.write(str(p), ref_audio_data, ref_sr)
            config.ref_audio_path = str(p)

        # config.json にはパスを「ファイル名のみ」で保存する (絶対パスを残さない)。
        # load_voice 側がフォルダ基準で解決し直すので、配布しても他環境で壊れない。
        data = asdict(config)
        for attr in ("ref_audio_path", "clone_prompt_path", "sample_audio_path"):
            if data.get(attr):
                data[attr] = Path(data[attr]).name
        (voice_dir / "config.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_voice(self, name: str) -> VoiceConfig:
        voice_dir = self.voices_dir / name
        config_path = voice_dir / "config.json"
        # config.json が無ければ config.default.json からコピーして作る。
        # (配布物は config.default.json + 音声ファイルのみ。読み上げ等で
        #  last_used_at が書き換わる config.json は git 管理外)
        if not config_path.exists():
            default_path = voice_dir / "config.default.json"
            if default_path.exists():
                config_path.write_text(
                    default_path.read_text(encoding="utf-8"), encoding="utf-8")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        vc = VoiceConfig(**{k: v for k, v in data.items() if k in VoiceConfig.__dataclass_fields__})
        # config.json に保存された絶対パスは別環境では壊れるため、ロード時に
        # 実フォルダ基準で解決し直す (ファイル名だけ採用してvoices_dirに付け替え)。
        for attr, default_name in (
            ("ref_audio_path", "ref_audio.wav"),
            ("clone_prompt_path", "clone_prompt.pkl"),
            ("sample_audio_path", "sample.wav"),
        ):
            stored = getattr(vc, attr, "")
            fname = Path(stored).name if stored else default_name
            resolved = voice_dir / fname
            setattr(vc, attr, str(resolved) if resolved.exists() else "")
        return vc

    def list_voices(self) -> list[VoiceConfig]:
        voices = []
        for d in sorted(self.voices_dir.iterdir()):
            # config.json か、配布初期状態の config.default.json があれば対象。
            if d.is_dir() and ((d / "config.json").exists()
                               or (d / "config.default.json").exists()):
                try:
                    voices.append(self.load_voice(d.name))
                except Exception:
                    pass
        return voices

    def delete_voice(self, name: str):
        d = self.voices_dir / name
        if d.exists():
            shutil.rmtree(d)

    def get_voice_names(self) -> list[str]:
        return [v.name for v in self.list_voices()]

    def get_voice_choices(self, voice_type_filter: str | None = None) -> list[tuple[str, str]]:
        """
        Return [(display_label, name), ...] sorted by last_used_at desc.
        display_label includes the timestamp if available.
        """
        voices = self.list_voices()
        if voice_type_filter:
            voices = [v for v in voices if v.voice_type == voice_type_filter]
        # Sort by last_used_at desc (recent first), empty timestamps last
        voices.sort(key=lambda v: v.last_used_at or "0", reverse=True)
        result = []
        for v in voices:
            if v.last_used_at:
                label = f"{v.name}  ({v.last_used_at})"
            else:
                label = f"{v.name}  (未使用)"
            result.append((label, v.name))
        return result

    def touch_voice(self, name: str):
        """Update last_used_at timestamp for the voice."""
        import time
        try:
            vc = self.load_voice(name)
            vc.last_used_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save_voice(vc)
        except Exception:
            pass

    def get_sample_path(self, name: str) -> str | None:
        p = self.voices_dir / name / "sample.wav"
        return str(p) if p.exists() else None
