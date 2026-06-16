"""受信テキストの整形 (絵文字/マークダウン/コードブロック除去)。

感情制御用の絵文字 (😭😠🥺 等。emotion_emoji.EMOTION_EMOJI) は Irodori-TTS が
スタイル制御に使うため、除去せず残す。それ以外の装飾絵文字のみ除去する。
"""
import re

try:
    from emotion_emoji import EMOTION_EMOJI
    _EMOTION_TOKENS = [e[0] for e in EMOTION_EMOJI]
except Exception:
    _EMOTION_TOKENS = []


def _apply_reading_dict(text: str) -> str:
    """reading_dict.json の読み置換を適用 (NoaTTS→ノアティーティーエス 等)。
    text_utils の辞書ローダを再利用。辞書が無ければ素通り。長いキー優先。"""
    try:
        from text_utils import _load_reading_dict
        rd = _load_reading_dict()
    except Exception:
        return text
    for key in sorted(rd.keys(), key=len, reverse=True):
        if key.startswith("_"):  # _補足 等のメモ行はスキップ
            continue
        text = text.replace(key, rd[key])
    return text

# ─── テキスト整形 ───
# 受け取ったテキストを、TTSが読める素テキストに整形する汎用処理。
# コードブロック・インラインコード・マークダウンリンク・絵文字・装飾記号を
# 除去し、余分な空白を詰める。

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F0FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"
    "♡♥❤❣"
    "\U0001F90D-\U0001F90F"
    "]+",
    flags=re.UNICODE,
)


def clean_text(raw: str) -> str:
    raw = re.sub(r"```[\s\S]*?```", "", raw)
    raw = re.sub(r"`[^`\n]+`", "", raw)
    raw = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw)

    lines = raw.splitlines()
    out_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 罫線だけの行 (---, ===, *** 等) は読まない
        if re.fullmatch(r"[-=*]{3,}", stripped):
            continue
        out_lines.append(line)

    text = "\n".join(out_lines)
    text = text.replace("…", "\x00ELLIPSIS\x00")
    # 感情絵文字を一旦プレースホルダに退避してから装飾絵文字を除去し、後で復元する
    # (😮‍💨 や 🌬️ のような複数コードポイント絵文字も丸ごと保護できる)。
    protected = []
    for i, tok in enumerate(_EMOTION_TOKENS):
        if tok in text:
            ph = f"\x00EMO{i}\x00"
            text = text.replace(tok, ph)
            protected.append((ph, tok))
    text = _EMOJI_PATTERN.sub("", text)
    for ph, tok in protected:
        text = text.replace(ph, tok)
    text = re.sub(r"\*\*", "", text)  # 太字記号 ** を除去 (中身は残す)
    text = re.sub(r"(?<!\S)\*|\*(?!\S)", "", text)  # 箇条書き/強調の単独 * を除去
    text = text.replace("\x00ELLIPSIS\x00", "…")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    # 読み仮名辞書を適用 (NoaTTS→ノアティーティーエス 等の誤読防止)
    text = _apply_reading_dict(text)
    return text.strip()
