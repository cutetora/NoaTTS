"""Integration test for all major features."""
import sys, os, time
# tests/ から1つ上 (プロジェクトルート) を import パスに通す
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import torch
torch.set_float32_matmul_precision("high")

import numpy as np
import soundfile as sf
from pathlib import Path

PASS = 0
FAIL = 0
OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS: {name}")
    except Exception as e:
        FAIL += 1
        print(f"  FAIL: {name} -> {e}")

# ── 1. Config ──
print("\n=== Config ===")
def t_config():
    from config import AppConfig
    cfg = AppConfig.load()
    assert cfg.tts_model_size in ("1.7B", "0.6B")
test("Config load", t_config)

# ── 2. Voice Manager ──
print("\n=== VoiceManager ===")
def t_vm():
    from voice.voice_manager import VoiceManager, VoiceConfig
    vm = VoiceManager(str(OUT / "_test_voices"))
    vc = VoiceConfig(name="test_voice", voice_type="design", language="Japanese",
                     attribute="テスト属性", voice_description="テスト説明", seed=42)
    dummy_audio = np.zeros(24000, dtype=np.float32)
    vm.save_voice(vc, sample_audio=dummy_audio, sample_sr=24000)
    loaded = vm.load_voice("test_voice")
    assert loaded.seed == 42
    assert loaded.attribute == "テスト属性"
    assert "test_voice" in vm.get_voice_names()
    vm.delete_voice("test_voice")
    assert "test_voice" not in vm.get_voice_names()
test("Save/Load/Delete with seed+attribute", t_vm)

# ── 3. LLM Provider ──
print("\n=== LLM Provider ===")
def t_llm():
    from config import AppConfig
    from llm_provider import create_provider, generate_hiragana, generate_motion
    cfg = AppConfig.load()
    provider = create_provider(cfg)
    h = generate_hiragana(provider, "今日は天気です")
    assert len(h) > 0
    m = generate_motion(provider, "おはよう", "喜")
    assert len(m) > 0
test("Claude CLI hiragana + motion", t_llm)

# ── 4. TTS Engine - CustomVoice ──
print("\n=== TTS Engine ===")
from engine.tts_engine import TTSEngine
engine = TTSEngine(model_size="1.7B", device="cuda:0")

def t_custom():
    results = engine.generate_custom_voice(
        text="テスト音声です", language="Japanese",
        speaker="Ono_Anna", instruct="明るく", num_samples=1,
    )
    wav, sr = results[0]
    assert len(wav) > 0 and sr > 0
    sf.write(str(OUT / "_test_custom.wav"), wav, sr)
test("CustomVoice generation", t_custom)

# ── 5. TTS Engine - VoiceDesign with seed ──
def t_design_seed():
    res1 = engine.generate_voice_design(
        text="テスト", language="Japanese",
        instruct="可愛い女の子の声", num_samples=1, seed=12345,
    )
    (wav1, sr1), seed1 = res1[0]
    assert seed1 == 12345
    assert len(wav1) > 0
    sf.write(str(OUT / "_test_design.wav"), wav1, sr1)
test("VoiceDesign with seed", t_design_seed)

# ── 6. TTS Engine - VoiceClone ──
def t_clone():
    # Create a ref audio from custom voice
    ref_results = engine.generate_custom_voice(
        text="This is a reference audio for cloning.",
        language="English", speaker="Ryan", instruct="",
    )
    ref_wav, ref_sr = ref_results[0]
    ref_path = str(OUT / "_test_ref.wav")
    sf.write(ref_path, ref_wav, ref_sr)

    results = engine.generate_voice_clone(
        text="クローンテストです", language="Japanese",
        ref_audio=ref_path, ref_text="This is a reference audio for cloning.",
    )
    wav, sr = results[0]
    assert len(wav) > 0
    sf.write(str(OUT / "_test_clone.wav"), wav, sr)
test("VoiceClone with ref_text", t_clone)

# ── 7. BGM Removal (Demucs) ──
print("\n=== Demucs BGM Removal ===")
def t_demucs():
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    # Create test audio (sine + noise = fake bgm + voice)
    sr_d = 24000
    t_arr = np.linspace(0, 2, sr_d * 2)
    voice = np.sin(2 * np.pi * 300 * t_arr) * 0.5
    bgm = np.sin(2 * np.pi * 1000 * t_arr) * 0.3
    mixed = (voice + bgm).astype(np.float32)
    stereo = np.stack([mixed, mixed])
    wav_t = torch.from_numpy(stereo).float()

    model = get_model("htdemucs")
    model.to("cuda")
    ref = wav_t.mean(0)
    wav_norm = (wav_t - ref.mean()) / ref.std()
    sources = apply_model(model, wav_norm[None].to("cuda"), device="cuda")[0]
    sources = sources * ref.std() + ref.mean()
    vocals = sources[model.sources.index("vocals")].cpu().numpy()
    sf.write(str(OUT / "_test_demucs_vocals.wav"), vocals.T, sr_d)
    assert Path(OUT / "_test_demucs_vocals.wav").exists()
test("Demucs BGM removal", t_demucs)

# ── 8. Instruct Builder ──
print("\n=== Instruct Builder ===")
def t_instruct():
    instruct = TTSEngine.build_instruct("クールな青年", "喜", "照れながら", "")
    assert "クールな青年" in instruct
    assert "喜" in instruct
    assert "照れながら" in instruct
test("Build instruct with priority", t_instruct)

# ── Cleanup ──
import shutil
for f in OUT.glob("_test_*"):
    if f.is_dir():
        shutil.rmtree(f, ignore_errors=True)
    else:
        f.unlink(missing_ok=True)

# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
