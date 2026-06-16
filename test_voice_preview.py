"""Test: save voice then test-generate from saved voice card."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

import torch
torch.set_float32_matmul_precision("high")

import numpy as np
import soundfile as sf

from config import AppConfig
from voice_manager import VoiceManager, VoiceConfig
from tts_engine import TTSEngine
from app import test_saved_voice, save_voice_action, gen_custom_voice, gen_voice_design, vm, get_engine

PASS = 0
FAIL = 0

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS: {name}")
    except Exception as e:
        FAIL += 1
        print(f"  FAIL: {name} -> {e}")
        import traceback; traceback.print_exc()


# ── Step 1: Save a CustomVoice card ──
print("\n=== Step 1: Save CustomVoice card ===")
def t_save_custom():
    # Generate a sample first
    outputs, msg = gen_custom_voice("Ono_Anna", "Japanese", "明るく", "テストです", 1)
    assert len(outputs) > 0, f"Generation failed: {msg}"
    result_msg, _ = save_voice_action(
        "test_preview_custom", "custom", "Japanese",
        "Ono_Anna", "", "", "", outputs[0],
        seed=-1, attribute="元気な女の子",
    )
    assert "保存しました" in result_msg, f"Save failed: {result_msg}"
test("Save CustomVoice card", t_save_custom)


# ── Step 2: Save a VoiceDesign card with seed ──
print("\n=== Step 2: Save VoiceDesign card ===")
def t_save_design():
    audios, seeds, msg = gen_voice_design("Japanese", "低い声の落ち着いた男性", "テストです", 1)
    assert len(audios) > 0, f"Generation failed: {msg}"
    assert len(seeds) > 0, f"No seeds: {msg}"
    result_msg, _ = save_voice_action(
        "test_preview_design", "design", "Japanese",
        "", "低い声の落ち着いた男性", "", "",
        audios[0], seed=seeds[0], attribute="クールな青年",
    )
    assert "保存しました" in result_msg, f"Save failed: {result_msg}"
test("Save VoiceDesign card with seed", t_save_design)


# ── Step 3: Test generate from saved CustomVoice ──
print("\n=== Step 3: Test generate from CustomVoice card ===")
def t_test_custom():
    audio, msg = test_saved_voice(
        "test_preview_custom",
        "おはようございます、元気ですか？",
        "嬉しそうに",
    )
    assert audio is not None, f"Generation failed: {msg}"
    sr, wav = audio
    assert len(wav) > 0, "Empty audio"
    rms = (wav ** 2).mean() ** 0.5
    assert rms > 0.001, f"Audio is silent: RMS={rms}"
    print(f"    audio={len(wav)/sr:.1f}s, RMS={rms:.4f}")
test("Test generate from CustomVoice", t_test_custom)


# ── Step 4: Test generate from saved VoiceDesign ──
print("\n=== Step 4: Test generate from VoiceDesign card ===")
def t_test_design():
    audio, msg = test_saved_voice(
        "test_preview_design",
        "ああ、そうだな。面倒くさいけど行くか。",
        "ため息混じりに",
    )
    assert audio is not None, f"Generation failed: {msg}"
    sr, wav = audio
    assert len(wav) > 0, "Empty audio"
    rms = (wav ** 2).mean() ** 0.5
    assert rms > 0.001, f"Audio is silent: RMS={rms}"
    assert "seed=" in msg, f"Seed not in message: {msg}"
    print(f"    audio={len(wav)/sr:.1f}s, RMS={rms:.4f}, msg={msg}")
test("Test generate from VoiceDesign", t_test_design)


# ── Step 5: Test with empty text (should fail gracefully) ──
print("\n=== Step 5: Validation tests ===")
def t_validation():
    audio, msg = test_saved_voice("test_preview_custom", "", "")
    assert audio is None, "Should have failed with empty text"
    assert "テキスト" in msg, f"Wrong error: {msg}"

    audio, msg = test_saved_voice("", "テスト", "")
    assert audio is None, "Should have failed with no voice"
    assert "選択" in msg, f"Wrong error: {msg}"
test("Validation (empty text / no voice)", t_validation)


# ── Cleanup ──
vm.delete_voice("test_preview_custom")
vm.delete_voice("test_preview_design")

# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
