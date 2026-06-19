"""保存済みボイス調整のロジック (UI非依存・全関数が引数渡し)。

試聴/シード探索/喜怒哀楽/設定保存のハンドラ群。UI部品を一切掴んでいないため
単体で呼び出してテストできる。clone_prompt の読込は _load_clone_prompt に一本化。"""
import os
import time

from pathlib import Path

import gradio as gr

from engine.engine_control import cfg, vm, monitor, get_engine
from engine.audio_utils import trim_silence, trim_interior_pauses, adjust_speed
from voice.voice_creation import test_saved_voice


def _load_clone_prompt(vc_cfg):
    """clone_prompt キャッシュを読み込む (.pt=Irodori latent はパスのまま / .pkl=Qwen3 は pickle)。
    無ければ None。試聴系の全ハンドラがこれを使う (単一実装)。"""
    if vc_cfg.clone_prompt_path and os.path.exists(vc_cfg.clone_prompt_path):
        if vc_cfg.clone_prompt_path.endswith(".pt"):
            return vc_cfg.clone_prompt_path
        import pickle
        with open(vc_cfg.clone_prompt_path, "rb") as f:
            return pickle.load(f)
    return None


def _tune_refresh():
    # 旧「保存済みボイス一覧」を統合したため全ボイス対象 (クローン限定フィルタ廃止)
    return gr.update(choices=vm.get_voice_choices())


def _tune_load(name):
    if not name:
        return 0.5, -1, 1.0, 0.0, "ボイスを選択してください", ""
    vc_cfg = vm.load_voice(name)
    temp = vc_cfg.clone_temperature if vc_cfg.clone_temperature > 0 else 0.5
    speed = getattr(vc_cfg, "speed", 1.0) or 1.0
    max_pause = getattr(vc_cfg, "max_pause_sec", 0.0) or 0.0
    default_caption = getattr(vc_cfg, "default_caption", "") or ""
    if vc_cfg.voice_type != "clone":
        prompt_status = f"— ({vc_cfg.voice_type}ボイス。prompt/temperatureはクローン専用)"
    elif vc_cfg.clone_prompt_path and os.path.exists(vc_cfg.clone_prompt_path):
        prompt_status = "✅ キャッシュ済み"
    else:
        prompt_status = "❌ 未キャッシュ"
    return temp, vc_cfg.seed, float(speed), float(max_pause), prompt_status, default_caption


def _tune_extract_prompt(name):
    if not name:
        return "ボイスを選択してください"
    try:
        vc_cfg = vm.load_voice(name)
        if not vc_cfg.ref_audio_path or not os.path.exists(vc_cfg.ref_audio_path):
            return "ref_audioが見つかりません"
        eng = get_engine()
        monitor.start(f"Prompt抽出: {name}")
        prompt = eng.extract_clone_prompt(
            ref_audio=vc_cfg.ref_audio_path,
            ref_text=vc_cfg.ref_text,
        )
        # Save prompt
        import pickle
        voice_dir = Path(cfg.voices_dir) / name
        voice_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = voice_dir / "clone_prompt.pkl"
        with open(str(prompt_path), "wb") as f:
            pickle.dump(prompt, f)
        vc_cfg.clone_prompt_path = str(prompt_path)
        vm.save_voice(vc_cfg)
        monitor.finish("Prompt抽出完了")
        return "✅ キャッシュ済み"
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return f"エラー: {e}"


def _tune_test(name, temp, seed, speed, max_pause, test_text, emotion_caption=""):
    if not name:
        return None, "ボイスを選択してください"
    try:
        vc_cfg = vm.load_voice(name)
        if vc_cfg.voice_type != "clone":
            # custom/design はカード設定+指示/感情で生成 (旧ボイス一覧のテスト生成と同経路)
            return test_saved_voice(name, test_text, emotion_caption)
        vm.touch_voice(name)
        eng = get_engine()
        # Load cached prompt if available
        clone_prompt = _load_clone_prompt(vc_cfg)
        caption = (emotion_caption or "").strip()
        t0 = time.time()
        results = eng.generate_voice_clone(
            text=test_text, language=vc_cfg.language,
            ref_audio=vc_cfg.ref_audio_path, ref_text=vc_cfg.ref_text,
            voice_clone_prompt=clone_prompt,
            temperature=float(temp),
            seed=int(seed),
            clone_caption=caption,
        )
        wav, sr = results[0]
        if float(max_pause) > 0:
            wav = trim_interior_pauses(wav, sr, float(max_pause))
        if float(speed) != 1.0:
            wav = adjust_speed(wav, sr, float(speed))
        elapsed = time.time() - t0
        prompt_info = "✅キャッシュ済prompt使用" if clone_prompt else "❌promptは毎回ref_audioから抽出"
        # caption使用時は VoiceDesignモデルに切替わり、キャッシュ済promptは使われない
        cap_line = f"\n  🎭 感情caption: 「{caption}」(VoiceDesignモデル)" if caption else ""
        info = (
            f"生成完了 ({elapsed:.1f}s) | 音声長 {len(wav)/sr:.1f}s\n"
            f"  temperature: {temp}\n"
            f"  top_p: 0.7, top_k: 30 (自動)\n"
            f"  seed: {int(seed)}\n"
            f"  speed: {float(speed)}x\n"
            f"  repetition_penalty: 1.3 (自動)\n"
            f"  {prompt_info}"
            f"{cap_line}"
        )
        return (sr, wav), info
    except Exception as e:
        return None, f"エラー: {e}"


_RANDOM_SENTENCES = [
    "おはようございます、今日もいい天気ですね。",
    "えっ、本当に？ それはすごいね！",
    "ちょっと待ってください、今行きますから。",
    "うーん、どうしようかな…迷っちゃうな。",
    "やったー！ ついに完成したよ！",
    "ごめんなさい、少し遅れちゃいました。",
    "ねえねえ、聞いて聞いて！ すっごい話があるの！",
    "お疲れ様です。今日は大変でしたね。",
    "あのさ、ちょっと相談があるんだけど…",
    "わあ、きれい！ こんな景色初めて見た！",
    "もう、しょうがないなぁ。仕方ないか。",
    "ありがとう、すごく嬉しい！",
    "はい、了解しました。すぐに取り掛かります。",
    "えへへ、ちょっと照れちゃうな。",
    "さて、そろそろ始めましょうか。",
]


def _tune_random_test(name, temp, seed, speed, max_pause, emotion_caption=""):
    if not name:
        return None, None, None, "ボイスを選択してください"
    try:
        import random
        texts = random.sample(_RANDOM_SENTENCES, 3)
        vc_cfg = vm.load_voice(name)
        vm.touch_voice(name)
        eng = get_engine()
        clone_prompt = _load_clone_prompt(vc_cfg)

        caption = (emotion_caption or "").strip()
        audios = []
        for txt in texts:
            results = eng.generate_voice_clone(
                text=txt, language=vc_cfg.language,
                ref_audio=vc_cfg.ref_audio_path, ref_text=vc_cfg.ref_text,
                voice_clone_prompt=clone_prompt,
                temperature=float(temp),
                seed=int(seed),
                clone_caption=caption,
            )
            wav, sr = results[0]
            wav = trim_silence(wav, sr)
            if float(max_pause) > 0:
                wav = trim_interior_pauses(wav, sr, float(max_pause))
            if float(speed) != 1.0:
                wav = adjust_speed(wav, sr, float(speed))
            audios.append((sr, wav))

        prompt_info = "prompt=cached" if clone_prompt else "prompt=live"
        status = f"3文生成完了 temp={temp} seed={int(seed)} {prompt_info}\n"
        status += "\n".join([f"  {i+1}. {t}" for i, t in enumerate(texts)])
        return (
            gr.update(value=audios[0], visible=True),
            gr.update(value=audios[1], visible=True),
            gr.update(value=audios[2], visible=True),
            status,
        )
    except Exception as e:
        return None, None, None, f"エラー: {e}"


def _tune_random5_seeds(name, temp, test_text, speed, max_pause, emotion_caption=""):
    """Generate 5 versions with random seeds - to find the best seed."""
    if not name:
        return [None]*5 + [-1]*5 + [gr.update(visible=False)]*5 + ["ボイスを選択してください"]
    try:
        import random
        seeds = [random.randint(1, 2**31 - 1) for _ in range(5)]
        vc_cfg = vm.load_voice(name)
        vm.touch_voice(name)
        eng = get_engine()
        clone_prompt = _load_clone_prompt(vc_cfg)

        caption = (emotion_caption or "").strip()
        audios = []
        monitor.start(f"5シード生成: {name}")
        for idx, s in enumerate(seeds):
            monitor.update(idx / 5, f"seed {idx+1}/5: {s}")
            results = eng.generate_voice_clone(
                text=test_text, language=vc_cfg.language,
                ref_audio=vc_cfg.ref_audio_path, ref_text=vc_cfg.ref_text,
                voice_clone_prompt=clone_prompt,
                temperature=float(temp),
                seed=s,
                clone_caption=caption,
            )
            wav, sr = results[0]
            wav = trim_silence(wav, sr)
            if float(max_pause) > 0:
                wav = trim_interior_pauses(wav, sr, float(max_pause))
            if float(speed) != 1.0:
                wav = adjust_speed(wav, sr, float(speed))
            audios.append((sr, wav))
        monitor.finish("5シード生成完了")

        prompt_info = "✅cached" if clone_prompt else "❌live"
        status = f"5つのseedで生成完了 (temp={temp}, prompt={prompt_info})\n"
        for i, s in enumerate(seeds):
            status += f"  試聴結果 {i+1}: seed={s}\n"
        # Audios + seed states + adopt buttons + status
        audio_updates = [
            gr.update(value=audios[i], visible=True, label=f"試聴結果 {i+1} (seed={seeds[i]})")
            for i in range(5)
        ]
        adopt_updates = [gr.update(visible=True) for _ in range(5)]
        return audio_updates + seeds + adopt_updates + [status]
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return [None]*5 + [-1]*5 + [gr.update(visible=False)]*5 + [f"エラー: {e}"]


# シード固定でランダム3文試聴 (一貫性確認用)
def _tune_seed_random3(name, temp, seed, speed, max_pause, emotion_caption=""):
    if not name:
        return [None]*5 + [gr.update(visible=False)]*5 + ["ボイスを選択してください"]
    if int(seed) < 0:
        return [None]*5 + [gr.update(visible=False)]*5 + ["seed値を固定してください (採用ボタン or 手動入力)"]
    try:
        import random
        texts = random.sample(_RANDOM_SENTENCES, 3)
        vc_cfg = vm.load_voice(name)
        vm.touch_voice(name)
        eng = get_engine()
        clone_prompt = _load_clone_prompt(vc_cfg)

        caption = (emotion_caption or "").strip()
        audios = []
        monitor.start(f"シード固定3文生成: {name} seed={int(seed)}")
        for idx, txt in enumerate(texts):
            monitor.update(idx / 3, f"{idx+1}/3: {txt[:15]}")
            results = eng.generate_voice_clone(
                text=txt, language=vc_cfg.language,
                ref_audio=vc_cfg.ref_audio_path, ref_text=vc_cfg.ref_text,
                voice_clone_prompt=clone_prompt,
                temperature=float(temp),
                seed=int(seed),
                clone_caption=caption,
            )
            wav, sr = results[0]
            wav = trim_silence(wav, sr)
            if float(max_pause) > 0:
                wav = trim_interior_pauses(wav, sr, float(max_pause))
            if float(speed) != 1.0:
                wav = adjust_speed(wav, sr, float(speed))
            audios.append((sr, wav))
        monitor.finish("3文生成完了")

        prompt_info = "✅cached" if clone_prompt else "❌live"
        status = f"seed={int(seed)} 固定で3文生成完了 (temp={temp}, prompt={prompt_info})\n"
        for i, t in enumerate(texts):
            status += f"  {i+1}. {t}\n"
        audio_updates = [
            gr.update(value=audios[i], visible=True, label=f"試聴結果 {i+1}: {texts[i][:20]}")
            for i in range(3)
        ] + [gr.update(value=None, visible=False) for _ in range(2)]
        adopt_updates = [gr.update(visible=False) for _ in range(5)]
        return audio_updates + adopt_updates + [status]
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return [None]*5 + [gr.update(visible=False)]*5 + [f"エラー: {e}"]


# 感情4種セット (各 (caption感情名, テストセリフ))。喜怒哀楽 と もう1系統。
_EMOTION_SAMPLES = [
    ("喜", "やった〜! ついに完成したよ! めっちゃ嬉しい!"),
    ("怒", "もう! 何回言わせるの? いい加減にしてよ!"),
    ("哀", "ごめん…ちょっと一人にしてくれる? 今は無理…"),
    ("楽", "ふふっ、楽しいね。こうして話してるだけで安心するな。"),
]
# 別系統の4種 (照れ・驚き・眠気・クール)。喜怒哀楽より細やかなニュアンス。
_EMOTION_SAMPLES2 = [
    ("照れ", "えっ、そ、そんなこと言われたら…照れちゃうじゃん…"),
    ("驚き", "ええっ!? 嘘でしょ!? 信じられない、本当に!?"),
    ("眠気", "ふぁ…あ…もう眠くて…まぶたが…重い…おやすみ…"),
    ("クール", "ふん。別に。どうでもいいわ、そんなこと。"),
]


def _tune_emotion_set(name, temp, seed, speed, max_pause, emotion_caption, samples, set_label):
    """感情セット(samples)を順に caption として生成・試聴する汎用ハンドラ。
    喜怒哀楽4種・別系統4種で共有。最大5枠 (4種+空き1) に対応。"""
    if not name:
        return [None]*5 + [gr.update(visible=False)]*5 + ["ボイスを選択してください"]
    try:
        vc_cfg = vm.load_voice(name)
        vm.touch_voice(name)
        eng = get_engine()
        clone_prompt = _load_clone_prompt(vc_cfg)

        audios = []
        extra_cap = (emotion_caption or "").strip()
        n = len(samples)
        monitor.start(f"{set_label}生成: {name} seed={int(seed)}")
        for idx, (emo, txt) in enumerate(samples):
            monitor.update(idx / max(n, 1), f"{idx+1}/{n}: {emo}")
            # 感情名を caption に。ユーザー指定があれば重ねる(声質指定など)
            cap = f"{emo}。{extra_cap}" if extra_cap else emo
            if vc_cfg.voice_type == "clone":
                results = eng.generate_voice_clone(
                    text=txt, language=vc_cfg.language,
                    ref_audio=vc_cfg.ref_audio_path, ref_text=vc_cfg.ref_text,
                    voice_clone_prompt=clone_prompt,
                    temperature=float(temp),
                    seed=int(seed),
                    clone_caption=cap,
                )
                wav, sr = results[0]
            else:
                # design/custom は参照音声が無いので、声の説明(voice_description)+
                # 感情caption で no_ref 合成する (generate_for_script_row が voice_type で振分け)。
                wav, sr = eng.generate_for_script_row(
                    voice_type=vc_cfg.voice_type,
                    text=txt, language=vc_cfg.language,
                    speaker=getattr(vc_cfg, "speaker", ""),
                    voice_description=getattr(vc_cfg, "voice_description", ""),
                    seed=int(seed),
                    clone_caption=cap,
                )
            wav = trim_silence(wav, sr)
            if float(max_pause) > 0:
                wav = trim_interior_pauses(wav, sr, float(max_pause))
            if float(speed) != 1.0:
                wav = adjust_speed(wav, sr, float(speed))
            audios.append((sr, wav))
        monitor.finish(f"{set_label}生成完了")

        prompt_info = "✅cached" if clone_prompt else "❌live"
        status = f"{set_label}生成完了 (temp={temp}, seed={int(seed)}, prompt={prompt_info})\n"
        for emo, txt in samples:
            status += f"  [{emo}] {txt}\n"
        audio_updates = [
            gr.update(value=audios[i], visible=True,
                      label=f"[{samples[i][0]}] {samples[i][1][:25]}")
            for i in range(n)
        ] + [gr.update(value=None, visible=False) for _ in range(5 - n)]
        adopt_updates = [gr.update(visible=False) for _ in range(5)]
        return audio_updates + adopt_updates + [status]
    except Exception as e:
        monitor.finish(f"エラー: {e}")
        return [None]*5 + [gr.update(visible=False)]*5 + [f"エラー: {e}"]


def _tune_emotion4_test(name, temp, seed, speed, max_pause, emotion_caption=""):
    return _tune_emotion_set(name, temp, seed, speed, max_pause, emotion_caption,
                             _EMOTION_SAMPLES, "喜怒哀楽4種")


def _tune_emotion4b_test(name, temp, seed, speed, max_pause, emotion_caption=""):
    return _tune_emotion_set(name, temp, seed, speed, max_pause, emotion_caption,
                             _EMOTION_SAMPLES2, "照れ驚き眠気クール4種")


def _tune_save(name, temp, seed, speed, max_pause, default_caption=""):
    if not name:
        return "ボイスを選択してください"
    try:
        vc_cfg = vm.load_voice(name)
        vc_cfg.clone_temperature = float(temp)
        vc_cfg.seed = int(seed)
        vc_cfg.speed = float(speed)
        vc_cfg.max_pause_sec = float(max_pause)
        # 既定感情 (この声をこの感情で恒久的に読ませる)。design/clone で読み上げに反映。
        vc_cfg.default_caption = (default_caption or "").strip()
        vm.save_voice(vc_cfg)
        cap_msg = f", 既定感情「{vc_cfg.default_caption}」" if vc_cfg.default_caption else ""
        return f"'{name}' の設定を保存しました (temp={temp}, seed={int(seed)}, speed={float(speed)}x, max_pause={float(max_pause)}s{cap_msg})"
    except Exception as e:
        return f"保存エラー: {e}"

