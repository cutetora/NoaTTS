"""TTS入力テキストの正規化と読み仮名辞書。

app.py から分離。（）モノローグ除去・波ダッシュ正規化・装飾記号→読点・
reading_dict.json による読み置換を行う。daemon の clean_text(絵文字/MD除去)とは
役割が別物（こちらは台本→TTS入力の整形）なので統合しない。
"""
import json
import re

from config import CONF_DIR

# ── Reading dictionary ──
_reading_dict: dict[str, str] | None = None


def _load_reading_dict() -> dict[str, str]:
    """Load kanji reading dictionary (cached)."""
    global _reading_dict
    if _reading_dict is None:
        dict_path = CONF_DIR / "reading_dict.json"
        if dict_path.exists():
            data = json.loads(dict_path.read_text(encoding="utf-8"))
            _reading_dict = data.get("辞書", {})
        else:
            _reading_dict = {}
    return _reading_dict


def reload_reading_dict():
    """Force reload the reading dictionary."""
    global _reading_dict
    _reading_dict = None
    return _load_reading_dict()


def normalize_tts_text(text: str) -> str:
    """Normalize text for TTS input: remove monologue, fix characters, apply reading dict."""
    # Remove （）monologue
    text = re.sub(r'[（(][^）)]*[）)]', '', text).strip()
    # Wave dash variants → long vowel mark
    text = text.replace('～', 'ー').replace('〜', 'ー').replace('~', 'ー')
    # ……→…
    text = text.replace('……', '…')
    # 装飾記号を読点に変換 (TTSが誤読する記号を読みの区切りに利用)
    for sym in ['♥', '♡', '❤', '★', '☆', '♪', '♫', '♬']:
        text = text.replace(sym, '、')
    # 連続読点を1つに圧縮
    text = re.sub(r'、{2,}', '、', text)
    text = re.sub(r'、\s*$', '', text)
    # Apply reading dictionary (longer keys first to avoid partial replacement)
    rd = _load_reading_dict()
    for key in sorted(rd.keys(), key=len, reverse=True):
        text = text.replace(key, rd[key])
    return text
