"""
End-to-end test: 10 rows batch generation → speech check → NG export → verify
Run with Python 3.11 (CUDA environment)
"""
import sys
import os
# tests/ から1つ上 (プロジェクトルート) を import パス兼 CWD にする
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import time
import numpy as np
import pandas as pd

print("=" * 60)
print("E2E TEST: 10 rows batch generation + speech check")
print("=" * 60)

# ── Step 1: Load config and modules ──
print("\n[Step 1] Loading modules...")
from config import AppConfig
from voice_manager import VoiceManager
from engine.tts_engine import TTSEngine
from engine.audio_utils import check_voice_gender, check_speech_content
import re

cfg = AppConfig.load()
vm = VoiceManager(cfg.voices_dir)

# Check available voices
voices = vm.get_voice_names()
print(f"  Available voices: {voices}")
if not voices:
    print("  ERROR: No voices available. Please create a voice first.")
    sys.exit(1)

# ── Step 2: Load test Excel ──
print("\n[Step 2] Loading test Excel...")
SCRIPT_COLUMNS = ["ID", "キャラ(性格)", "ファイル名", "セリフ", "セリフ仮名", "感情", "Qwen3TTSシステムプロンプト"]

df = pd.read_excel("test_10rows.xlsx")
col_map = {}
for col in df.columns:
    c = col.strip()
    if c in ("ID",): col_map[col] = "ID"
    elif "キャラ" in c or "性格" in c: col_map[col] = "キャラ(性格)"
    elif "ファイル" in c: col_map[col] = "ファイル名"
    elif "仮名" in c: col_map[col] = "セリフ仮名"
    elif "感情" in c: col_map[col] = "感情"
    elif "システムプロンプト" in c or "指示" in c: col_map[col] = "Qwen3TTSシステムプロンプト"
    elif "セリフ" in c: col_map[col] = "セリフ"
df = df.rename(columns=col_map)
for c in SCRIPT_COLUMNS:
    if c not in df.columns: df[c] = ""
df = df[SCRIPT_COLUMNS]
# ffill
for col_name in ["ID", "キャラ(性格)"]:
    df[col_name] = df[col_name].replace("", np.nan).ffill()
df = df.fillna("")

print(f"  Loaded {len(df)} rows")
for i in range(len(df)):
    fname = str(df.iloc[i]["ファイル名"]).strip()
    chara = str(df.iloc[i]["キャラ(性格)"]).strip()
    serif = str(df.iloc[i]["セリフ"]).strip()
    print(f"  行{i}: ファイル=[{fname}] キャラ=[{chara}] セリフ=[{serif[:20]}]")

# ── Step 3: Setup voice mapping ──
print("\n[Step 3] Setting up voice mapping...")
# Use first available voice for デフォルト
voice_name = voices[0]
mapping = {"デフォルト": voice_name}
print(f"  Mapping: デフォルト → {voice_name}")
vc = vm.load_voice(voice_name)
print(f"  Voice type: {vc.voice_type}, seed: {vc.seed}")

# ── Step 4: Load TTS engine ──
print("\n[Step 4] Loading TTS engine...")
engine = TTSEngine(model_size=cfg.tts_model_size, device=cfg.tts_device)

def on_progress(msg):
    print(f"  {msg}")

engine._load_model(vc.voice_type, on_progress=on_progress)
print("  Engine ready")

# ── Step 5: Batch generation (simulate run_batch_generation logic) ──
print("\n[Step 5] Batch generation...")
generated_audio = {}
voice_check_cache = {}
speech_check_cache = {}
errors = []
skipped = 0
total = len(df)
max_retries = 3

for i in range(total):
    row = df.iloc[i]
    fname = str(row["ファイル名"]).strip()
    if not fname:
        skipped += 1
        print(f"  行{i}: SKIP (no filename)")
        continue

    char_name = str(row["キャラ(性格)"]).strip()
    voice_name_mapped = mapping.get(char_name, "")
    if not voice_name_mapped:
        if char_name:
            errors.append(f"行{i}: '{char_name}' にボイス未割り当て")
        else:
            skipped += 1
        print(f"  行{i}: SKIP (no voice for [{char_name}])")
        continue

    text = str(row["セリフ仮名"]).strip() or str(row["セリフ"])
    text = re.sub(r'[（(][^）)]*[）)]', '', text).strip()
    if not text:
        skipped += 1
        print(f"  行{i}: SKIP (empty text after monologue removal)")
        continue

    attribute = vc.attribute or char_name
    emotion = str(row["感情"]).strip()
    instruction = str(row["Qwen3TTSシステムプロンプト"]).strip()
    instruct = TTSEngine.build_instruct(attribute, emotion, instruction, cfg.instruct_template)

    serif_orig = re.sub(r'[（(][^）)]*[）)]', '', str(row["セリフ"])).strip()

    for attempt in range(1, max_retries + 1):
        try:
            t0 = time.time()
            wav, sr = engine.generate_for_script_row(
                voice_type=vc.voice_type, text=text, language=vc.language,
                instruct=instruct, speaker=vc.speaker,
                ref_audio=vc.ref_audio_path, ref_text=vc.ref_text,
                voice_description=vc.voice_description,
                seed=vc.seed if attempt == 1 else -1,
            )
            generated_audio[i] = (wav, sr)
            gen_time = time.time() - t0

            # Voice check
            g_label, g_f0 = check_voice_gender(wav, sr)
            voice_check_cache[i] = (g_label, g_f0)

            # Speech check
            s_status, transcribed, detail = check_speech_content(wav, sr, serif_orig)
            speech_check_cache[i] = (s_status, transcribed, detail)

            if "✅" in s_status or attempt == max_retries:
                retry_info = f" (試行{attempt}回)" if attempt > 1 else ""
                print(f"  行{i}: [{fname}] {gen_time:.1f}s | {g_label} {g_f0:.0f}Hz | {s_status} [{transcribed[:30]}]{retry_info}")
                if detail and "✅" not in s_status:
                    print(f"         NG理由: {detail[:80]}")
                break
            else:
                print(f"  行{i}: {s_status} → retry {attempt}/{max_retries}")
        except Exception as e:
            errors.append(f"行{i}: {e}")
            print(f"  行{i}: ERROR - {e}")
            break

# ── Step 6: Results summary ──
print(f"\n[Step 6] Results")
print(f"  Generated: {len(generated_audio)}/{total}")
print(f"  Skipped: {skipped}")
print(f"  Errors: {len(errors)}")

ok_count = sum(1 for s, _, _ in speech_check_cache.values() if "✅" in s)
ng_count = sum(1 for s, _, _ in speech_check_cache.values() if "✅" not in s)
print(f"  Speech check: OK={ok_count}, NG={ng_count}")

if errors:
    print(f"  Error details: {errors}")

# ── Step 7: Export WAV ──
print(f"\n[Step 7] Exporting WAV files...")
import soundfile as sf
from pathlib import Path

out_path = Path(cfg.output_dir) / "test_e2e"
out_path.mkdir(parents=True, exist_ok=True)
for idx, (wav, sr) in generated_audio.items():
    fname = str(df.iloc[idx]["ファイル名"]).strip()
    fname = "".join(c for c in fname if c.isalnum() or c in "_-.").strip().rstrip(".")
    sf.write(str(out_path / f"{fname}.wav"), wav, sr)
print(f"  Exported to {out_path}")

# ── Step 8: Export NG Excel ──
print(f"\n[Step 8] NG Excel export...")
ng_rows = []
for idx, (status, transcribed, detail) in speech_check_cache.items():
    if "✅" not in status and idx < len(df):
        row = df.iloc[idx]
        ng_rows.append({
            "ID": str(row["ID"]),
            "キャラ(性格)": str(row["キャラ(性格)"]),
            "ファイル名": str(row["ファイル名"]),
            "セリフ": str(row["セリフ"]),
            "セリフ仮名": str(row["セリフ仮名"]),
            "感情": str(row["感情"]),
            "Qwen3TTSシステムプロンプト": str(row["Qwen3TTSシステムプロンプト"]),
            "NG理由": status,
            "書き起こし": transcribed,
            "詳細": detail,
        })

if ng_rows:
    ng_df = pd.DataFrame(ng_rows)
    ng_path = out_path / "ng_rows.xlsx"
    ng_df.to_excel(str(ng_path), index=False)
    print(f"  NG {len(ng_rows)} rows exported → {ng_path}")
else:
    print(f"  No NG rows! All OK.")

# ── Step 9: Verify セリフチェック tab logic ──
print(f"\n[Step 9] Verifying セリフチェック tab logic (re-check from WAV files)...")
recheck_ok = 0
recheck_ng = 0
for idx, (wav, sr) in generated_audio.items():
    serif = str(df.iloc[idx]["セリフ"])
    serif_clean = re.sub(r'[（(][^）)]*[）)]', '', serif).strip()
    if not serif_clean:
        continue
    s_status, transcribed, detail = check_speech_content(wav, sr, serif_clean)
    if "✅" in s_status:
        recheck_ok += 1
    else:
        recheck_ng += 1
        print(f"  Re-check NG: 行{idx} [{serif_clean}] → [{transcribed}] {s_status}")

print(f"  Re-check results: OK={recheck_ok}, NG={recheck_ng}")

# ── Step 10: Test specific edge cases ──
print(f"\n[Step 10] Edge case verification:")
# Row 3: has （心の声） - should be stripped
row3_text = str(df.iloc[3]["セリフ"])
row3_clean = re.sub(r'[（(][^）)]*[）)]', '', row3_text).strip()
print(f"  Row 3 monologue: [{row3_text}] → [{row3_clean}]")
assert "心の声" not in row3_clean, "FAIL: monologue not removed!"
print(f"  ✅ Monologue removal OK")

# Row 8: empty セリフ - should be skipped
row8_text = str(df.iloc[8]["セリフ"]).strip()
print(f"  Row 8 empty: [{row8_text}] → skipped={8 not in generated_audio}")
assert 8 not in generated_audio, "FAIL: empty text row should be skipped!"
print(f"  ✅ Empty text skip OK")

# ffill check
for i in range(len(df)):
    chara = str(df.iloc[i]["キャラ(性格)"]).strip()
    assert chara != "" and chara != "nan", f"FAIL: row {i} has empty キャラ after ffill!"
print(f"  ✅ ffill OK (all rows have キャラ)")

# Filename sanitization
test_fname = "test.file-name_01"
sanitized = "".join(c for c in test_fname if c.isalnum() or c in "_-.").strip().rstrip(".")
assert sanitized == "test.file-name_01", f"FAIL: got [{sanitized}]"
print(f"  ✅ Filename sanitization OK (dots preserved)")

print(f"\n{'='*60}")
print(f"E2E TEST COMPLETE")
print(f"  Generated: {len(generated_audio)}/{total} rows")
print(f"  Speech OK: {ok_count}, NG: {ng_count}")
print(f"  All edge cases passed")
print(f"{'='*60}")
