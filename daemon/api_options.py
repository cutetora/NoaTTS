"""HTTP API のオプション解釈を一か所にまとめる (純関数。worker / GPU に依存しない)。

/say /say_wav /say_dialogue /v1/audio/speech が、同じキー名 (voice / speed / caption / cache、
再生系のみ volume) を同じ規則で解釈するための共通部品。不正値は OptionError で返し、
呼び出し側が 400 のエラー文にする。
"""
import math
from pathlib import Path

# リクエストで指定できる話速の範囲。OpenAI TTS API の speed の範囲 (0.25〜4.0) に合わせる。
# 以前は無制限だったので、既存クライアントの値 (/v1 互換の 0.25 など) を変えないよう広めに取る。
# /speed (ボイスカードへ保存する話速) の 0.5〜2.0 とは別。
SPEED_MIN = 0.25
SPEED_MAX = 4.0

_BAD_NAME_CHARS = '/\\:*?"<>|'


class OptionError(ValueError):
    """リクエストのオプションが不正。メッセージはそのまま HTTP 400 の error 文に使う。"""


# ── ボイス名 ──

def _is_voice_dir(d: Path) -> bool:
    # load_voice と同じ規則: config.json、または配布直後の config.default.json があれば声として読める。
    return d.is_dir() and ((d / "config.json").exists() or (d / "config.default.json").exists())


def list_voices(voices_dir) -> list:
    """読み込める声 (ボイスカード) の名前一覧。GET /voices と resolve_voice の両方がこれを使う。"""
    try:
        return sorted(p.name for p in Path(voices_dir).iterdir() if _is_voice_dir(p))
    except OSError:
        return []


def resolve_voice(voices_dir, name):
    """リクエストの voice をディスク上の実名に解決する。空 (None/"") は None (=アクティブ声)。
    形式が不正・存在しない場合は OptionError("unknown voice: …")。
    Windows のフォルダは大文字小文字を区別しないため、実名に揃えてキャッシュの二重化を防ぐ。"""
    name = str(name or "").strip()
    if not name:
        return None
    if name in (".", "..") or any(c in name for c in _BAD_NAME_CHARS):
        raise OptionError(f"unknown voice: {name}")
    names = list_voices(voices_dir)
    if name in names:
        return name
    folded = [n for n in names if n.lower() == name.lower()]
    if len(folded) == 1:
        return folded[0]
    raise OptionError(f"unknown voice: {name}")


# ── 個別の値 ──

def _number(v, field):
    if isinstance(v, bool):
        raise OptionError(f"{field} must be a number")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise OptionError(f"{field} must be a number")
    if math.isnan(x) or math.isinf(x):
        raise OptionError(f"{field} must be a number")
    return x


def parse_speed(v):
    """話速の倍率。None/0以下 は None (=ボイスカードの speed)。それ以外は 0.25〜4.0 に丸める。
    0以下を「指定なし」とするのは、従来の /say_wav の挙動 (Unity 等が 0 を未指定として送る) を保つため。"""
    if v is None:
        return None
    x = _number(v, "speed")
    if x <= 0:
        return None
    return max(SPEED_MIN, min(SPEED_MAX, x))


def parse_volume(v):
    """再生音量。None は None、それ以外は 0.0〜1.0 に丸める。"""
    if v is None:
        return None
    return max(0.0, min(1.0, _number(v, "volume")))


_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off")


def parse_bool(v, field):
    """JSON の bool、0/1、"true"/"false"/"yes"/"no"/"on"/"off" の文字列。
    None (キー無し・null) は None=既定に従う。以前は null が OFF 扱いだったが、
    「指定なし」として既定に従うよう揃えた。それ以外の値は 400。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
    raise OptionError(f"{field} must be true or false")


def parse_caption(v):
    """感情 caption。キーが無い/null は None (=ボイスカードの default_caption に従う)。
    文字列はそのまま使い、"" は「caption なし」(default_caption も使わない) を意味する。"""
    if v is None:
        return None
    return str(v).strip()


# ── まとめて解釈 ──

def parse_common(obj, voices_dir, *, volume=False, cache=True, lenient_voice=False):
    """リクエスト JSON (dict) から voice / speed / caption / cache (と volume) を取り出す。
    volume=True にすると volume も解釈する (再生する /say 系のみ)。
    cache=False は cache を読まない (セグメント単位では指定できないので検証もしない。
    API 全体で、対象外のキーは黙って無視する方針と揃える)。
    lenient_voice=True は、存在しない voice を None (=アクティブ声) に落とす (/v1 の OpenAI 互換用)。
    戻り値は {"voice","speed","caption","cache","volume"}。指定なしの項目は None。"""
    try:
        voice = resolve_voice(voices_dir, obj.get("voice"))
    except OptionError:
        if not lenient_voice:
            raise
        voice = None
    return {
        "voice": voice,
        "speed": parse_speed(obj.get("speed")),
        "caption": parse_caption(obj.get("caption")),
        "cache": parse_bool(obj.get("cache"), "cache") if cache else None,
        "volume": parse_volume(obj.get("volume")) if volume else None,
    }


def parse_dialogue(obj, voices_dir, clean):
    """/say_dialogue の本文を (segments, cache, volume) にする。
    トップレベルの voice/speed/caption は全セグメントの既定値で、セグメント側の指定が優先される。
    clean は本文の整形関数 (clean_text)。整形後に空になったセグメントは捨てる。"""
    segs_raw = obj.get("segments")
    if not isinstance(segs_raw, list) or not segs_raw:
        raise OptionError("segments must be a non-empty list")
    top = parse_common(obj, voices_dir, volume=True)
    segments = []
    for s in segs_raw:
        if not isinstance(s, dict):
            continue
        text = clean(str(s.get("text", "") or "").strip())
        if not text:
            continue
        seg = parse_common(s, voices_dir, cache=False)  # cache はセグメント単位では指定できない
        segments.append({
            "voice": seg["voice"] if seg["voice"] is not None else top["voice"],
            "text": text,
            "speed": seg["speed"] if seg["speed"] is not None else top["speed"],
            "caption": seg["caption"] if seg["caption"] is not None else top["caption"],
        })
    if not segments:
        raise OptionError("nothing to speak after cleanup")
    return segments, top["cache"], top["volume"]
