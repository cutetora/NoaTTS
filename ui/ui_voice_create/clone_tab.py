"""C. ボイスクローン タブ (参照音声+書き起こし、BGM除去付き)。

vc_ref_text を返す (エンジン切替時に設定タブが表示/ラベルを書き換えるため)。"""
import gradio as gr

from engine.tts_engine import TTSEngine
from engine.engine_control import cfg
from engine.audio_utils import trim_interior_pauses, adjust_speed
from voice.voice_creation import gen_voice_clone, remove_bgm, save_voice_action


def build_clone_tab():
    # ── C. VoiceClone ──
    with gr.Tab("C. ボイスクローン [両エンジン対応]", elem_id="tut-tab-clone"):
        vc_audios = gr.State([])
        with gr.Row():
            # 左カラム: 入力・操作・保存
            with gr.Column(scale=1):
                vc_lang = gr.Dropdown(
                    choices=TTSEngine.LANGUAGES, value="Japanese", label="言語"
                )
                vc_ref_audio = gr.Audio(label="参照音声 (3〜10秒)", type="filepath", elem_id="tut-ref-audio")
                vc_bgm_btn = gr.Button("BGM除去 (Demucs)")
                # Irodoriは ref_text を内部で使わない(参照音声のみでクローン)。
                # エンジンに応じてラベル/必須表示を出し分け、Irodoriでは非表示にする。
                _irodori = (cfg.tts_engine_type == "irodori")
                vc_ref_text = gr.Textbox(
                    label="参照音声の書き起こし (必須)" if not _irodori else "参照音声の書き起こし (Irodoriでは不要)",
                    placeholder="参照音声で話されている内容をテキストで入力",
                    elem_id="tut-ref-text",
                    visible=not _irodori,
                )
                vc_text = gr.Textbox(label="テスト文", value="こんにちは、テスト音声です。")
                with gr.Row():
                    vc_speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="試聴用 話速", info="1.0=等倍")
                    vc_max_pause = gr.Slider(0.0, 1.0, value=0.0, step=0.05, label="ポーズ上限秒", info="0=無効")
                vc_btn = gr.Button("クローン生成", variant="primary", elem_id="tut-gen-btn")
                vc_status = gr.Textbox(label="ステータス", interactive=False)
                with gr.Row():
                    vc_save_name = gr.Textbox(label="ボイス名", placeholder="ナレーター", elem_id="tut-save-name")
                vc_save_btn = gr.Button("保存", elem_id="tut-save-btn")
                vc_save_status = gr.Textbox(label="保存結果", interactive=False)

            # 右カラム: 生成結果(BGM除去結果・クローン結果)
            with gr.Column(scale=1):
                vc_bgm_status = gr.Textbox(label="BGM除去ステータス", interactive=False, visible=False)
                vc_bgm_audio = gr.Audio(label="BGM除去済み音声 (試聴・DL可)", visible=False)
                vc_result_audio = gr.Audio(label="クローン結果", elem_id="tut-result")

        def _remove_bgm(audio_path):
            vocals_path, msg = remove_bgm(audio_path)
            if vocals_path:
                return (
                    gr.update(value=msg, visible=True),
                    gr.update(value=vocals_path, visible=True),
                    vocals_path,  # auto-set as ref audio
                )
            return (
                gr.update(value=msg, visible=True),
                gr.update(visible=False),
                audio_path,  # keep original
            )

        vc_bgm_btn.click(
            _remove_bgm,
            inputs=[vc_ref_audio],
            outputs=[vc_bgm_status, vc_bgm_audio, vc_ref_audio],
        )

        def _gen_clone(ref_path, ref_txt, lang, text, speed, max_pause):
            results, msg = gen_voice_clone(ref_path, ref_txt, lang, text)
            if results:
                sr, wav = results[0]
                if float(max_pause) > 0:
                    wav = trim_interior_pauses(wav, sr, float(max_pause))
                if float(speed) != 1.0:
                    wav = adjust_speed(wav, sr, float(speed))
                results = [(sr, wav)]
                msg = f"{msg} | speed={float(speed)}x, max_pause={float(max_pause)}s"
            audio_out = results[0] if results else None
            return results, msg, audio_out

        vc_btn.click(
            _gen_clone,
            inputs=[vc_ref_audio, vc_ref_text, vc_lang, vc_text, vc_speed, vc_max_pause],
            outputs=[vc_audios, vc_status, vc_result_audio],
        )

        def _save_clone(name, audios, ref_path, ref_txt, lang, speed, max_pause):
            if not audios:
                return "先にクローンを生成してください", gr.update()
            return save_voice_action(
                name, "clone", lang, "", "", ref_path, ref_txt, audios[0],
                speed=float(speed), max_pause_sec=float(max_pause),
            )

        vc_save_btn.click(
            _save_clone,
            inputs=[vc_save_name, vc_audios, vc_ref_audio, vc_ref_text, vc_lang, vc_speed, vc_max_pause],
            outputs=[vc_save_status, gr.State()],
        )
    return vc_ref_text
