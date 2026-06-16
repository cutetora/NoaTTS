"""連続ストリーム再生 (StreamPlayer) と winsound フォールバック。"""
import os
from pathlib import Path

class StreamPlayer:
    """sounddevice の OutputStream を開きっぱなしにして波形を流し込む連続再生器。
    winsound のように文ごとにデバイスを開き直さないので継ぎ目(プチノイズ)が出ない。
    生成済みWAVを次々 feed() で書き込み、文間は無音サンプルで埋める。
    abort() で即停止(キャンセル用)。"""

    def __init__(self):
        self._sd = None
        self._stream = None
        self._sr = None
        self._aborted = False

    def _ensure(self, sr: int):
        import sounddevice as sd
        self._sd = sd
        if self._stream is not None and self._sr == sr:
            return
        # サンプルレートが変わった/未開なら開き直す
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
        self._stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32")
        self._stream.start()
        self._sr = sr

    def feed_wav(self, path):
        """WAVファイルを読んでストリームに書き込む。
        小さいチャンクに分けて書き込み、各チャンク前に中断をチェックするので
        abort() がほぼ即座に効く(長い文の途中でもすぐ止まる)。"""
        import soundfile as sf
        import numpy as np
        if self._aborted:
            return
        data, sr = sf.read(str(path), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)  # ステレオ→モノ
        self._ensure(sr)
        # 約50msごとのチャンクに分割して書き込む(中断の応答性を上げる)
        chunk = max(256, int(sr * 0.05))
        for i in range(0, len(data), chunk):
            if self._aborted:
                return
            self._stream.write(data[i:i + chunk])

    def feed_silence(self, sec: float):
        """無音サンプルを書き込む(文間ギャップ用、継ぎ目なし)。"""
        import numpy as np
        if self._aborted or sec <= 0 or self._stream is None or self._sr is None:
            return
        n = int(sec * self._sr)
        if n > 0:
            self._stream.write(np.zeros(n, dtype="float32"))

    def abort(self):
        """再生を即停止(バッファ破棄)。"""
        self._aborted = True
        if self._stream is not None:
            try:
                self._stream.abort()
            except Exception:
                pass

    def close(self):
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
        self._stream = None


# 旧 winsound 版(フォールバック用に残す。通常は StreamPlayer を使う)
def _play_silence(sec: float, sr: int = 48000):
    if sec <= 0:
        return
    import tempfile
    import soundfile as sf
    import numpy as np
    import winsound
    silence = np.zeros(int(sec * sr), dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        sf.write(tmp_path, silence, sr)
        winsound.PlaySound(tmp_path, winsound.SND_FILENAME)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _play_wav(path: Path):
    import winsound
    winsound.PlaySound(str(path), winsound.SND_FILENAME)
