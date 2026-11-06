"""daemon/api_options.py (HTTP API オプション解釈) の単体テスト。GPU・daemon 不要。
実行: python tests/test_api_options.py
"""
import os
import sys
import tempfile
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from daemon import api_options as ao

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ao.OptionError as e:
        return str(e)
    return None


tmp = Path(tempfile.mkdtemp(prefix="noa_api_opt_"))
(tmp / "Noa").mkdir()
(tmp / "Noa" / "config.json").write_text("{}", encoding="utf-8")
(tmp / "fresh").mkdir()  # 配布直後: config.default.json のみ
(tmp / "fresh" / "config.default.json").write_text("{}", encoding="utf-8")
(tmp / "notavoice").mkdir()  # 設定ファイルの無いフォルダ

print("== ボイス名 ==")
check("list_voices は読める声だけ (設定なしフォルダを除く)", ao.list_voices(tmp) == ["Noa", "fresh"], str(ao.list_voices(tmp)))
check("config.default.json のみのカードも実在扱い", ao.resolve_voice(tmp, "fresh") == "fresh")
check("空/None は None (アクティブ声)", ao.resolve_voice(tmp, "") is None and ao.resolve_voice(tmp, None) is None)
check("大文字小文字違いはディスク上の実名に揃う", ao.resolve_voice(tmp, "noa") == "Noa")
check("存在しない声は unknown voice", raises(ao.resolve_voice, tmp, "nobody") == "unknown voice: nobody")
check("設定なしフォルダは unknown voice", raises(ao.resolve_voice, tmp, "notavoice") is not None)
for bad in ["..", ".", "../Noa", "a/b", "a\\b", "C:x"]:
    check(f"不正な名前 {bad!r} は拒否", raises(ao.resolve_voice, tmp, bad) is not None)

print("== speed ==")
check("None は None", ao.parse_speed(None) is None)
check("1.2 はそのまま", ao.parse_speed(1.2) == 1.2)
check("文字列の数値も受ける", ao.parse_speed("1.5") == 1.5)
check("0 と負数は None (カードの speed を使う)", ao.parse_speed(0) is None and ao.parse_speed(-1) is None)
check("OpenAI の範囲 (0.25〜4.0) はそのまま通る", ao.parse_speed(0.25) == 0.25 and ao.parse_speed(4.0) == 4.0 and ao.parse_speed(3) == 3.0)
check("下限 0.25 に丸める", ao.parse_speed(0.1) == 0.25)
check("上限 4.0 に丸める", ao.parse_speed(100) == 4.0)
for bad in ["abc", True, [], {}, float("nan"), float("inf")]:
    check(f"不正な speed {bad!r} は拒否", raises(ao.parse_speed, bad) == "speed must be a number")

print("== volume / cache / caption ==")
check("volume は 0〜1 に丸める", ao.parse_volume(5) == 1.0 and ao.parse_volume(-1) == 0.0 and ao.parse_volume(0.4) == 0.4)
check("不正な volume は拒否", raises(ao.parse_volume, "loud") == "volume must be a number")
check("cache の bool / 0,1 / 文字列", ao.parse_bool(True, "cache") is True and ao.parse_bool(0, "cache") is False
      and ao.parse_bool("true", "cache") is True and ao.parse_bool("0", "cache") is False
      and ao.parse_bool("Yes", "cache") is True and ao.parse_bool("off", "cache") is False)
check("cache null/無しは None (=既定に従う。以前の null=OFF から変更)", ao.parse_bool(None, "cache") is None)
check("不正な cache は拒否", raises(ao.parse_bool, "maybe", "cache") == "cache must be true or false"
      and raises(ao.parse_bool, 2, "cache") is not None)
check("caption: キー無し/null は None (default に従う)", ao.parse_caption(None) is None)
check('caption: "" は「なし」を意味する (None と区別)', ao.parse_caption("") == "" and ao.parse_caption("  ") == "")
check("caption は strip", ao.parse_caption("  嬉しい ") == "嬉しい")

print("== parse_common ==")
r = ao.parse_common({"voice": "noa", "speed": 2, "caption": "", "cache": False, "volume": 0.5}, tmp, volume=True)
check("全項目を解釈", r == {"voice": "Noa", "speed": 2.0, "caption": "", "cache": False, "volume": 0.5}, str(r))
r = ao.parse_common({"voice": "nobody", "volume": 0.5}, tmp, lenient_voice=True)
check("lenient_voice: 存在しない声は None に落とす。volume は対象外なら None", r["voice"] is None and r["volume"] is None, str(r))
check("lenient でなければ unknown voice", raises(ao.parse_common, {"voice": "nobody"}, tmp) == "unknown voice: nobody")
check("指定なしはすべて None", ao.parse_common({}, tmp) == {"voice": None, "speed": None, "caption": None, "cache": None, "volume": None})
check("不正な cache は parse_common でも拒否", raises(ao.parse_common, {"cache": "x"}, tmp) is not None)

print("== parse_dialogue ==")
clean = lambda t: t.replace("😀", "").strip()
segs, cache, vol = ao.parse_dialogue(
    {"voice": "fresh", "speed": 1.1, "caption": "穏やかに", "cache": True, "volume": 0.7,
     "segments": [
         {"text": "こんにちは"},                                  # 既定値を継承
         {"voice": "noa", "text": "やあ", "speed": 1.5, "caption": ""},  # 上書き + 空 caption は「なし」
         {"text": "😀"},                                         # 整形後に空 → 捨てる
         "not a dict",
     ]}, tmp, clean)
check("既定値の継承とセグメント側の優先", segs == [
    {"voice": "fresh", "text": "こんにちは", "speed": 1.1, "caption": "穏やかに"},
    {"voice": "Noa", "text": "やあ", "speed": 1.5, "caption": ""},
], str(segs))
check("cache / volume はトップレベルから", cache is True and vol == 0.7)
check("segments が無い/空は拒否", raises(ao.parse_dialogue, {}, tmp, clean) == "segments must be a non-empty list"
      and raises(ao.parse_dialogue, {"segments": []}, tmp, clean) == "segments must be a non-empty list")
check("全セグメントが空になったら拒否", raises(ao.parse_dialogue, {"segments": [{"text": "😀"}]}, tmp, clean) == "nothing to speak after cleanup")
segs2, _, _ = ao.parse_dialogue({"segments": [{"text": "a", "cache": "x", "volume": "y"}]}, tmp, clean)
check("セグメント単位の cache/volume は対象外: 検証も反映もしない (エラーにならず無視)", len(segs2) == 1 and "cache" not in segs2[0])
check("セグメントの存在しない声は拒否", raises(ao.parse_dialogue, {"segments": [{"voice": "nobody", "text": "a"}]}, tmp, clean) == "unknown voice: nobody")

print()
print("ALL PASS" if FAIL == 0 else f"{FAIL} FAILED")
sys.exit(1 if FAIL else 0)
