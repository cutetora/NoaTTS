"""デザイン→クローンカード保存 (voice_creation.save_design_as_clone) の単体テスト。

GPU/モデル不要: 一時フォルダの VoiceManager に差し替え、prompt 抽出はしない。
実行: python tests/test_design_to_clone.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import numpy as np

from voice.voice_manager import VoiceManager
import voice.voice_creation as vcm

SR = 24000
FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    if cond:
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")


def tone(sec, pad=0.5):
    """前後に無音(pad秒)を持つ sec 秒の音声。"""
    t = np.arange(int(SR * sec)) / SR
    body = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    silence = np.zeros(int(SR * pad), dtype=np.float32)
    return SR, np.concatenate([silence, body, silence])


tmp = tempfile.mkdtemp(prefix="noa_d2c_")
vcm.vm = VoiceManager(tmp)
vcm.cfg.voices_dir = tmp


def save(name, audio=None, overwrite=False, seed=12345, ref_text="こんにちは"):
    return vcm.save_design_as_clone(
        name, audio if audio is not None else tone(5.0), seed, ref_text,
        "Japanese", "高めの声", "明るい", overwrite=overwrite, extract_prompt=False)


print("== 基本保存 ==")
msg, ok = save("花子_clone")
check("保存成功", ok, msg)
d = Path(tmp) / "花子_clone"
conf = json.loads((d / "config.json").read_text(encoding="utf-8"))
check("type=clone", conf["voice_type"] == "clone")
check("seed 引き継ぎ", conf["seed"] == 12345)
check("ref_text=テスト文", conf["ref_text"] == "こんにちは")
check("voice_description 引き継ぎ", conf["voice_description"] == "高めの声")
check("ref_audio.wav と sample.wav がある",
      (d / "ref_audio.wav").exists() and (d / "sample.wav").exists())
import soundfile as sf
ref_len = len(sf.read(str(d / "ref_audio.wav"))[0]) / SR
smp_len = len(sf.read(str(d / "sample.wav"))[0]) / SR
check("ref は無音トリム済み (≈5秒)、sample は元のまま (≈6秒)",
      4.8 < ref_len < 5.2 and 5.8 < smp_len < 6.2, f"ref={ref_len} sample={smp_len}")
check("config.json にパスはファイル名のみ", conf["ref_audio_path"] == "ref_audio.wav", conf["ref_audio_path"])
check("5秒は警告なし", "⚠️" not in msg)

print("== 上書き ==")
(d / "stale.txt").write_text("old", encoding="utf-8")
msg, ok = save("花子_clone")
check("同名は許可なしで拒否", not ok and "上書き" in msg, msg)
check("拒否時は既存を触らない", (d / "stale.txt").exists())
msg, ok = save("花子_clone", overwrite=True, seed=7)
check("許可ありで上書き成功", ok, msg)
check("フォルダがクリーンになる (旧ファイル消滅)", not (d / "stale.txt").exists())
check("新しい seed が入る", json.loads((d / "config.json").read_text(encoding="utf-8"))["seed"] == 7)

print("== 上書き中に保存が失敗したら旧カードを戻す ==")
before = (d / "config.json").read_text(encoding="utf-8")
(d / "keep.txt").write_text("keep", encoding="utf-8")
_orig_save = vcm.vm.save_voice
def _boom(*a, **k):
    raise OSError("disk full (test)")
vcm.vm.save_voice = _boom
msg, ok = save("花子_clone", overwrite=True, seed=999)
vcm.vm.save_voice = _orig_save
check("失敗は saved=False", not ok, msg)
check("旧 config.json がそのまま残る", (d / "config.json").read_text(encoding="utf-8") == before)
check("旧フォルダの他ファイルも残る", (d / "keep.txt").exists())
check("退避フォルダの残骸が無い",
      not [p for p in Path(tmp).parent.iterdir() if p.name.startswith(".voice_bak_") and p.parent == Path(tmp).parent
           and (p / "old").exists()])

print("== 大文字小文字だけ違う名前 ==")
save("Hanako")
msg, ok = save("hanako")
check("大文字小文字違いも同名として拒否し、既存の実名と種別を表示", not ok and "Hanako" in msg and "clone" in msg, msg)
msg, ok = save("hanako", overwrite=True)
check("許可すれば上書きできる", ok, msg)

print("== 長さ警告 ==")
msg, ok = save("short", audio=tone(1.0))
check("1秒は保存されるが警告", ok and "⚠️" in msg, msg)
msg, ok = save("long", audio=tone(12.0))
check("12秒は保存されるが警告", ok and "⚠️" in msg, msg)

print("== 入力検証 ==")
for bad in ["", "  ", "..", "a/b", "a\\b", "x:y", "花子.", "花子 .", "con", "NUL", "com1.txt", "lpt9"]:
    msg, ok = save(bad)
    check(f"不正名 {bad!r} は拒否", not ok, msg)
check("voices_dir の外は作られない", not (Path(tmp).parent / "b").exists())
msg, ok = vcm.save_design_as_clone("ng", None, 1, "x", "Japanese", extract_prompt=False)
check("サンプル無しは拒否", not ok, msg)
msg, ok = save("ng2", ref_text="  ")
check("テスト文が空なら拒否", not ok, msg)
msg, ok = save("noseed", seed=-1)
check("seed=-1 もそのまま -1", ok and json.loads((Path(tmp) / "noseed" / "config.json").read_text(encoding="utf-8"))["seed"] == -1)

print("== clone_prompt キャッシュ (エンジン差し替え) ==")
class _Eng:
    def __init__(self, ret):
        self.ret = ret
    def extract_clone_prompt(self, ref_audio, ref_text):
        return self.ret

save("cache1")
c1 = Path(tmp) / "cache1"
(c1 / "clone_prompt.pt").write_bytes(b"x")
_orig_get = vcm.get_engine
vcm.get_engine = lambda: _Eng(str(c1 / "clone_prompt.pt"))
st = vcm.extract_prompt_cache("cache1")
conf = json.loads((c1 / "config.json").read_text(encoding="utf-8"))
check("Irodori(.pt): 成功扱い", st.startswith("✅"), st)
check("Irodori(.pt): カードに .pt をファイル名のみで記録", conf["clone_prompt_path"] == "clone_prompt.pt", conf["clone_prompt_path"])
check("Irodori(.pt): pkl を作らない", not (c1 / "clone_prompt.pkl").exists())
check("Irodori(.pt): load_voice が実パスに解決", vcm.vm.load_voice("cache1").clone_prompt_path == str(c1 / "clone_prompt.pt"))

save("cache2")
c2 = Path(tmp) / "cache2"
vcm.get_engine = lambda: _Eng(str(c2 / "ref_audio.wav"))  # Irodori の失敗フォールバック (参照音声パス)
st = vcm.extract_prompt_cache("cache2")
check("Irodori(フォールバック): 警告を返し何も記録しない",
      st.startswith("⚠️") and json.loads((c2 / "config.json").read_text(encoding="utf-8"))["clone_prompt_path"] == ""
      and not (c2 / "clone_prompt.pkl").exists(), st)

save("cache3")
c3 = Path(tmp) / "cache3"
vcm.get_engine = lambda: _Eng({"dummy": "qwen prompt"})  # Qwen3 は pickle 化できるオブジェクト
st = vcm.extract_prompt_cache("cache3")
check("Qwen3: pkl を作りカードに記録", st.startswith("✅") and (c3 / "clone_prompt.pkl").exists()
      and json.loads((c3 / "config.json").read_text(encoding="utf-8"))["clone_prompt_path"] == "clone_prompt.pkl", st)
vcm.get_engine = _orig_get

print("== 古い記録の掃除 / 退避失敗 / 音声キャッシュキー ==")
save("cache4")
c4 = Path(tmp) / "cache4"
v4 = vcm.vm.load_voice("cache4"); v4.clone_prompt_path = str(c4 / "clone_prompt.pkl")
(c4 / "clone_prompt.pkl").write_bytes(b"old"); vcm.vm.save_voice(v4)
vcm.get_engine = lambda: _Eng(str(c4 / "ref_audio.wav"))  # フォールバック(.pt以外の文字列)
vcm.extract_prompt_cache("cache4")
check("キャッシュ無しの時は古い clone_prompt_path を空にする",
      json.loads((c4 / "config.json").read_text(encoding="utf-8"))["clone_prompt_path"] == "")
vcm.get_engine = _orig_get

_orig_mk = vcm.tempfile.mkdtemp
def _mk_fail(*a, **k):
    raise PermissionError("no write (test)")
vcm.tempfile.mkdtemp = _mk_fail
before4 = (c4 / "config.json").read_text(encoding="utf-8")
msg, ok = save("cache4", overwrite=True)
vcm.tempfile.mkdtemp = _orig_mk
check("退避先を作れなければ例外にせず拒否し、旧カードは無傷",
      (not ok) and "退避" in msg and (c4 / "config.json").read_text(encoding="utf-8") == before4, msg)

from daemon.worker import TTSWorker
class _VC:  # _cache_path が読む属性だけ持つ最小のカード
    def __init__(self, vt, ref):
        self.name = "same"; self.voice_type = vt; self.seed = 5; self.ref_audio_path = ref
w = object.__new__(TTSWorker)
k_design = w._cache_path("こんにちは", _VC("design", ""), "", 0, 1.0)
k_clone = w._cache_path("こんにちは", _VC("clone", str(d / "ref_audio.wav")), "", 0, 1.0)
check("同名・同seed でも 種別/参照音声が違えばキャッシュキーが変わる", k_design != k_clone)
check("同じ入力ならキーは安定", k_clone == w._cache_path("こんにちは", _VC("clone", str(d / "ref_audio.wav")), "", 0, 1.0))

print()
print("ALL PASS" if FAIL == 0 else f"{FAIL} FAILED")
sys.exit(1 if FAIL else 0)
