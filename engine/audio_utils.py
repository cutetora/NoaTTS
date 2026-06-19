import io
import numpy as np
import librosa
import soundfile as sf
import requests
import tempfile
import os


def to_wav_bytes(audio: np.ndarray, sr: int, target_sr: int = 24000) -> bytes:
    """float波形を「24kHz / モノラル / 16bit リニアPCM」の WAV バイト列(RIFF...WAVE)にして返す。
    /say_wav 等、クライアント側で再生するためにバイト列を返す用途。
    fmt: AudioFormat=1(PCM), NumChannels=1, SampleRate=target_sr, BitsPerSample=16。"""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:                      # ステレオ等 → モノ化
        audio = audio.mean(axis=1)
    if sr != target_sr:                     # ネイティブ48k等 → 24kへリサンプル
        audio = librosa.resample(audio, orig_sr=sr, target_sr=target_sr)
    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    sf.write(buf, pcm16, target_sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# フォーマット → Content-Type
_AUDIO_CTYPES = {
    "wav": "audio/wav", "pcm": "audio/pcm", "mp3": "audio/mpeg",
    "flac": "audio/flac", "ogg": "audio/ogg", "opus": "audio/opus",
    "aac": "audio/aac",
}


def _ffmpeg_encode(audio_mono_f32: np.ndarray, sr: int, fmt: str):
    """ffmpeg で指定フォーマットにエンコード (subprocess)。未インストール/失敗で None。
    soundfile が直接出せない形式 (opus/aac 等) のフォールバック用。"""
    import shutil
    import subprocess
    if shutil.which("ffmpeg") is None:
        return None
    pcm16 = (np.clip(audio_mono_f32, -1.0, 1.0) * 32767.0).astype(np.int16)
    wbuf = io.BytesIO()
    sf.write(wbuf, pcm16, sr, format="WAV", subtype="PCM_16")
    ff_fmt = {"mp3": "mp3", "opus": "opus", "aac": "adts", "ogg": "ogg",
              "flac": "flac", "wav": "wav"}.get(fmt, fmt)
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "wav", "-i", "pipe:0", "-f", ff_fmt, "pipe:1"],
            input=wbuf.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
        return p.stdout if (p.returncode == 0 and p.stdout) else None
    except Exception:
        return None


def to_audio_bytes(audio: np.ndarray, sr: int, fmt: str = "wav",
                   target_sr: int = 24000):
    """波形を指定フォーマットのバイト列にして (bytes, content_type) を返す。
    対応: wav / pcm / flac / ogg / mp3 (soundfile)、opus / aac 等は ffmpeg。
    その形式を出せない環境では wav にフォールバックする。"""
    fmt = (fmt or "wav").lower().strip()
    a = np.asarray(audio, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != target_sr:
        a = librosa.resample(a, orig_sr=sr, target_sr=target_sr)
    a = np.clip(a, -1.0, 1.0)
    ctype = _AUDIO_CTYPES.get(fmt, "application/octet-stream")

    if fmt == "pcm":  # raw PCM 16bit LE mono
        return (a * 32767.0).astype("<i2").tobytes(), "audio/pcm"

    # soundfile が直接書ける形式
    sf_fmt = {"wav": "WAV", "flac": "FLAC", "ogg": "OGG", "mp3": "MP3",
              "opus": "OGG"}.get(fmt)
    try:
        avail = sf.available_formats()
    except Exception:
        avail = {}
    if sf_fmt and sf_fmt in avail:
        try:
            buf = io.BytesIO()
            if fmt == "wav":
                sf.write(buf, (a * 32767.0).astype(np.int16), target_sr,
                         format="WAV", subtype="PCM_16")
            elif fmt == "opus":
                sf.write(buf, a, target_sr, format="OGG", subtype="OPUS")
            else:
                sf.write(buf, a, target_sr, format=sf_fmt)
            return buf.getvalue(), ctype
        except Exception:
            pass

    data = _ffmpeg_encode(a, target_sr, fmt)  # opus/aac 等のフォールバック
    if data:
        return data, ctype

    buf = io.BytesIO()  # 最終フォールバック: wav
    sf.write(buf, (a * 32767.0).astype(np.int16), target_sr,
             format="WAV", subtype="PCM_16")
    return buf.getvalue(), "audio/wav"


def adjust_speed(audio: np.ndarray, sr: int, speed: float = 1.0) -> np.ndarray:
    """話速調整。WSOLA(audiotsm)を優先使用してエコー/位相歪みを回避。"""
    if abs(speed - 1.0) < 0.01:
        return audio
    audio_f = audio.astype(np.float32)
    # WSOLA (audiotsm) — 音声向け。エコーなし
    try:
        from audiotsm import wsola
        from audiotsm.io.array import ArrayReader, ArrayWriter
        # audiotsm は (channels, samples) 形式を期待
        if audio_f.ndim == 1:
            arr_in = audio_f.reshape(1, -1)
        else:
            arr_in = audio_f.T if audio_f.shape[0] > audio_f.shape[1] else audio_f
        reader = ArrayReader(arr_in)
        writer = ArrayWriter(channels=arr_in.shape[0])
        tsm = wsola(channels=arr_in.shape[0], speed=float(speed))
        tsm.run(reader, writer)
        out = writer.data
        return out[0] if out.shape[0] == 1 else out.T
    except ImportError:
        # フォールバック: librosa の phase vocoder (エコー出やすい)
        return librosa.effects.time_stretch(audio_f, rate=speed)


def adjust_pitch(audio: np.ndarray, sr: int, semitones: float = 0.0) -> np.ndarray:
    if abs(semitones) < 0.01:
        return audio
    return librosa.effects.pitch_shift(
        audio.astype(np.float32), sr=sr, n_steps=semitones
    )


def process_audio(
    audio: np.ndarray, sr: int, speed: float = 1.0, pitch: float = 0.0
) -> np.ndarray:
    audio = adjust_speed(audio, sr, speed)
    audio = adjust_pitch(audio, sr, pitch)
    return audio


def trim_silence(audio: np.ndarray, sr: int, top_db: int = 25) -> np.ndarray:
    """Trim silence from start and end of audio."""
    trimmed, _ = librosa.effects.trim(audio.astype(np.float32), top_db=top_db)
    return trimmed


def trim_interior_pauses(
    audio: np.ndarray, sr: int, max_pause_sec: float = 0.3, top_db: int = 30
) -> np.ndarray:
    """文中の長いポーズを max_pause_sec 以下に切り詰める。
    無効化 (max_pause_sec<=0) のときは元音声をそのまま返す。
    つなぎ目に5msのクロスフェードを入れてプチノイズを防ぐ。"""
    if max_pause_sec <= 0:
        return audio
    audio_f = audio.astype(np.float32)
    intervals = librosa.effects.split(audio_f, top_db=top_db)
    if len(intervals) <= 1:
        return audio_f
    max_pause_samples = int(max_pause_sec * sr)
    xfade = max(1, int(0.005 * sr))  # 5ms
    out_parts = [audio_f[intervals[0][0]:intervals[0][1]]]
    for i in range(1, len(intervals)):
        prev_end = intervals[i - 1][1]
        cur_start = intervals[i][0]
        gap = cur_start - prev_end
        if gap > max_pause_samples:
            # 切り詰めた無音を挿入
            silence = np.zeros(max_pause_samples, dtype=np.float32)
        else:
            silence = audio_f[prev_end:cur_start]
        seg = audio_f[cur_start:intervals[i][1]]
        # クロスフェード: 直前パートの末尾を fade-out しつつ silence を続ける
        if len(out_parts[-1]) >= xfade and len(silence) >= xfade:
            fade = np.linspace(1.0, 0.0, xfade, dtype=np.float32)
            out_parts[-1][-xfade:] = out_parts[-1][-xfade:] * fade
        out_parts.append(silence)
        # silence -> seg もフェードイン
        if len(seg) >= xfade:
            fade = np.linspace(0.0, 1.0, xfade, dtype=np.float32)
            seg = seg.copy()
            seg[:xfade] = seg[:xfade] * fade
        out_parts.append(seg)
    return np.concatenate(out_parts)


def check_audio_duration(audio: np.ndarray, sr: int, text: str) -> tuple[str, float, float]:
    """
    Check if audio duration is reasonable for the text length.
    Japanese speech: roughly 5-8 chars/sec.

    Returns:
        (status, actual_sec, expected_max_sec)
    """
    actual_sec = len(audio) / sr
    # Estimate: ~0.2 sec per character + 0.5 sec margin
    text_len = len(text)
    expected_max = text_len * 0.25 + 1.0  # generous upper bound
    expected_max = max(expected_max, 1.5)  # minimum 1.5 sec

    if actual_sec > expected_max * 2.5:
        return "❌ 長すぎ", actual_sec, expected_max
    elif actual_sec > expected_max * 1.8:
        return "⚠️ やや長い", actual_sec, expected_max
    else:
        return "✅ OK", actual_sec, expected_max


def check_voice_gender(audio: np.ndarray, sr: int) -> tuple[str, float]:
    """
    Estimate voice gender from fundamental frequency (F0).
    Returns (label, median_f0_hz).

    Female voice: typically 165-300 Hz
    Male voice: typically 85-165 Hz
    """
    f0, voiced_flag, _ = librosa.pyin(
        audio.astype(np.float32),
        fmin=librosa.note_to_hz('C2'),   # ~65 Hz
        fmax=librosa.note_to_hz('C6'),   # ~1047 Hz
        sr=sr,
    )
    # Filter to voiced frames only
    voiced_f0 = f0[voiced_flag] if voiced_flag is not None else f0[~np.isnan(f0)]
    voiced_f0 = voiced_f0[~np.isnan(voiced_f0)]

    if len(voiced_f0) == 0:
        return "判定不可", 0.0

    median_f0 = float(np.median(voiced_f0))

    # Threshold: 165 Hz is roughly the boundary
    if median_f0 >= 165:
        return "✅ 女性", median_f0
    elif median_f0 >= 140:
        return "⚠️ 低め", median_f0
    else:
        return "❌ 男性?", median_f0


# ── Whisper-based speech verification ──

_whisper_model = None


def _get_whisper():
    """Lazy-load Whisper model (tiny for speed)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    return _whisper_model


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: remove punctuation, whitespace, normalize symbols."""
    import re
    t = text.strip()
    # Normalize common variations
    t = t.replace("～", "〜").replace("ー", "ー")
    # Remove punctuation and whitespace
    t = re.sub(r'[、。！？!?,.\s　「」『』（）()\[\]…・〜~♪♡★☆\-ー]', '', t)
    # Normalize to hiragana for comparison (katakana -> hiragana)
    result = []
    for ch in t:
        cp = ord(ch)
        if 0x30A1 <= cp <= 0x30F6:  # katakana -> hiragana
            result.append(chr(cp - 0x60))
        else:
            result.append(ch)
    return ''.join(result)


def check_speech_content(
    audio: np.ndarray,
    sr: int,
    expected_text: str,
) -> tuple[str, str, str]:
    """
    Transcribe audio with Whisper and compare with expected text.

    Returns:
        (status_label, transcribed_text, detail_reason)
    """
    try:
        model = _get_whisper()

        # Write to temp WAV for Whisper
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        sf.write(tmp.name, audio.astype(np.float32), sr)
        tmp.close()

        segments, info = model.transcribe(tmp.name, language="ja", beam_size=3)
        transcribed = "".join(seg.text for seg in segments).strip()
        os.unlink(tmp.name)

        audio_duration = len(audio) / sr

        if not transcribed:
            return "⚠️ 無音?", "", f"音声{audio_duration:.1f}秒だがWhisperが何も検出できず"

        # Normalize both texts
        norm_expected = _normalize_text(expected_text)
        norm_transcribed = _normalize_text(transcribed)

        if not norm_expected:
            return "✅ OK", transcribed, ""

        # Check: repetition (transcribed contains expected text 2+ times)
        if norm_expected and len(norm_expected) >= 2:
            count = 0
            pos = 0
            while True:
                idx = norm_transcribed.find(norm_expected, pos)
                if idx == -1:
                    break
                count += 1
                pos = idx + 1
            if count >= 2:
                return "⚠️ 繰り返し", transcribed, (
                    f"セリフが{count}回繰り返されている。"
                    f"期待:「{expected_text}」→ 実際:「{transcribed}」。"
                    f"原因: システムプロンプトが長すぎるか、短いセリフに対して指示が複雑すぎる可能性"
                )

        # Check: length ratio (transcribed much longer than expected)
        len_ratio = len(norm_transcribed) / max(len(norm_expected), 1)
        if len_ratio > 2.0:
            return "⚠️ 長すぎ", transcribed, (
                f"書き起こしがセリフの{len_ratio:.1f}倍長い。"
                f"期待:「{expected_text}」({len(norm_expected)}文字) → 実際:「{transcribed}」({len(norm_transcribed)}文字)。"
                f"原因: TTSがシステムプロンプトの一部を読み上げたか、余計な音声を生成した可能性"
            )

        # Check: similarity (simple character overlap)
        if norm_expected and norm_transcribed:
            common = sum(1 for c in norm_expected if c in norm_transcribed)
            similarity = common / max(len(norm_expected), 1)
            if similarity < 0.3:
                return "❌ 大幅ズレ", transcribed, (
                    f"セリフとの一致率{similarity:.0%}。"
                    f"期待:「{expected_text}」→ 実際:「{transcribed}」。"
                    f"原因: TTSが全く別の内容を生成。セリフ仮名の誤りかモデルのハルシネーション"
                )
            elif similarity < 0.5:
                return "⚠️ 内容ズレ", transcribed, (
                    f"セリフとの一致率{similarity:.0%}。"
                    f"期待:「{expected_text}」→ 実際:「{transcribed}」。"
                    f"原因: 部分的に正しいが一部が欠落または変化している"
                )

        return "✅ OK", transcribed, ""

    except Exception as e:
        return f"チェック失敗: {e}", "", str(e)


def voicevox_notify(text: str = "全ての処理が完了しました", speaker: int = 1):
    """VOICEVOX で音声通知を再生する"""
    try:
        base = "http://localhost:50021"
        q = requests.post(
            f"{base}/audio_query", params={"text": text, "speaker": speaker}, timeout=10
        )
        q.raise_for_status()
        syn = requests.post(
            f"{base}/synthesis", params={"speaker": speaker}, json=q.json(), timeout=30
        )
        syn.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(syn.content)
        tmp.close()

        # Windows
        import winsound
        winsound.PlaySound(tmp.name, winsound.SND_FILENAME)
        os.unlink(tmp.name)
    except Exception as e:
        print(f"[VOICEVOX notification failed] {e}")
