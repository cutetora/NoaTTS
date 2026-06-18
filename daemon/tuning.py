"""読み上げ調整値 (gap/nosplit/firstcut) の永続化と文分割。

⚠ _gap_sec/_nosplit/_first_cut は実行時に再代入されるため、他モジュールからは
`from daemon import tuning` → `tuning._gap_sec` で読むこと (setterはfrom-import可)。
"""
import re

from .runtime import BASE_DIR

# ─── 音声生成・再生ワーカー ───

# 分割しない閾値: テキスト全体がこの文字数以下なら一切分割せず丸ごと1回で生成する。
# 文分割すると文ごとに別生成→繋ぎ目に間ができてテンポが悪い。短いセリフは
# 丸ごと渡せばモデルが「、。」を自然な抑揚で一息に読み、間が空かない。
# /nosplit エンドポイントで可変、nosplit.txt に永続化。
NOSPLIT_FILE = BASE_DIR / "nosplit.txt"
_nosplit = 0  # 0=常に句点(。！？)で分割し1文ずつ合成(VRAMピークを1文分に抑える/日本語の自然な単位)。
# >0 にすると その文字数以下は分割せず丸ごと読む(間が空かずテンポ優先だが、長文1チャンクで
# VRAMピークが跳ねる。例: 140字丸ごと=ピーク約4.4GB / 句点分割=約2.4GB)。

# 1文目早切り: 最初のチャンクだけ読点で早めに切り、喋り出しを速くする。
# _nosplit を超える長文のときだけ有効(短文は分割しないので無関係)。
FIRSTCUT_FILE = BASE_DIR / "firstcut.txt"
_first_cut = 30  # デフォルト30字


def _load_nosplit():
    global _nosplit
    try:
        if NOSPLIT_FILE.exists():
            _nosplit = max(0, min(2000, int(float(NOSPLIT_FILE.read_text(encoding="utf-8").strip()))))
    except Exception:
        pass


def _set_nosplit(n) -> int:
    global _nosplit
    _nosplit = max(0, min(2000, int(float(n))))
    try:
        NOSPLIT_FILE.write_text(str(_nosplit), encoding="utf-8")
    except Exception:
        pass
    return _nosplit


def _load_firstcut():
    global _first_cut
    try:
        if FIRSTCUT_FILE.exists():
            _first_cut = max(0, min(200, int(float(FIRSTCUT_FILE.read_text(encoding="utf-8").strip()))))
    except Exception:
        pass


def _set_firstcut(n) -> int:
    global _first_cut
    _first_cut = max(0, min(200, int(float(n))))
    try:
        FIRSTCUT_FILE.write_text(str(_first_cut), encoding="utf-8")
    except Exception:
        pass
    return _first_cut


def _split_sentences(text: str) -> list:
    # 短いセリフは分割せず丸ごと1チャンク(句読点で間が空かない・テンポ最優先)。
    if _nosplit > 0 and len(text.strip()) <= _nosplit:
        return [text.strip()]
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?\n])", text) if s.strip()]
    merged = []
    for s in sentences:
        if merged and len(s) <= 8:
            merged[-1] += s
        else:
            merged.append(s)
    # 長文のときだけ1文目早切り(喋り出しを速くする)。短文はここに来ない。
    if _first_cut > 0 and merged and len(merged[0]) > _first_cut:
        head = merged[0]
        cut = -1
        for idx in range(_first_cut, len(head)):
            if head[idx] in "、，":
                cut = idx + 1
                break
        if cut > 0 and (len(head) - cut) >= 4:
            merged = [head[:cut].strip(), head[cut:].strip()] + merged[1:]
    return merged


# ─── 文間ギャップ(無音)の調整 ───
# 文と文の間に挟む無音の秒数。小さいほど連続的に、大きいほど区切って読む。
# /gap エンドポイントで実行中に変更でき、gap.txt に永続化される(再起動不要)。
GAP_FILE = BASE_DIR / "gap.txt"
_gap_sec = 0.15  # デフォルト


def _load_gap():
    global _gap_sec
    try:
        if GAP_FILE.exists():
            v = float(GAP_FILE.read_text(encoding="utf-8").strip())
            _gap_sec = max(0.0, min(2.0, v))
    except Exception:
        pass


def _set_gap(sec: float) -> float:
    global _gap_sec
    _gap_sec = max(0.0, min(2.0, float(sec)))
    try:
        GAP_FILE.write_text(str(_gap_sec), encoding="utf-8")
    except Exception:
        pass
    return _gap_sec
