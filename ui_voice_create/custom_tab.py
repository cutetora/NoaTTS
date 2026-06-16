"""A. カスタムボイス タブ (Qwen3専用: 内蔵スピーカーで生成→保存)。"""
import gradio as gr

from engine.tts_engine import TTSEngine
from voice_creation import gen_custom_voice, save_voice_action


def build_custom_tab():
    # ── A. CustomVoice ──
    with gr.Tab("A. カスタムボイス [Qwen3専用]"):
        cv_audios = gr.State([])
        with gr.Row():
            # 左カラム: 入力・操作・保存
            with gr.Column(scale=1):
                with gr.Row():
                    cv_speaker = gr.Dropdown(
                        choices=TTSEngine.SPEAKERS, value="Ono_Anna", label="スピーカー"
                    )
                    cv_lang = gr.Dropdown(
                        choices=TTSEngine.LANGUAGES, value="Japanese", label="言語"
                    )
                cv_num = gr.Slider(1, 5, value=3, step=1, label="生成数")
                cv_instruct = gr.Textbox(label="指示 (感情・話し方)", placeholder="クールに落ち着いて")
                cv_text = gr.Textbox(label="テスト文", value="こんにちは、テスト音声です。")
                cv_btn = gr.Button("サンプル生成", variant="primary")
                cv_status = gr.Textbox(label="ステータス", interactive=False)
                # Save
                with gr.Row():
                    cv_save_idx = gr.Slider(1, 5, value=1, step=1, label="保存サンプル番号")
                    cv_save_name = gr.Textbox(label="ボイス名", placeholder="太郎_通常")
                cv_save_btn = gr.Button("保存")
                cv_save_status = gr.Textbox(label="保存結果", interactive=False)

            # 右カラム: 生成結果(サンプル試聴)
            with gr.Column(scale=1):
                cv_audio1 = gr.Audio(label="サンプル 1", visible=True)
                cv_audio2 = gr.Audio(label="サンプル 2", visible=True)
                cv_audio3 = gr.Audio(label="サンプル 3", visible=True)
                cv_audio4 = gr.Audio(label="サンプル 4", visible=False)
                cv_audio5 = gr.Audio(label="サンプル 5", visible=False)
        cv_all_audios = [cv_audio1, cv_audio2, cv_audio3, cv_audio4, cv_audio5]

        def _gen_custom(speaker, lang, instruct, text, num):
            results, msg = gen_custom_voice(speaker, lang, instruct, text, num)
            updates = []
            for i in range(5):
                if i < len(results):
                    updates.append(gr.update(value=results[i], visible=True))
                else:
                    updates.append(gr.update(value=None, visible=i < 3))
            return [results, msg] + updates

        cv_btn.click(
            _gen_custom,
            inputs=[cv_speaker, cv_lang, cv_instruct, cv_text, cv_num],
            outputs=[cv_audios, cv_status] + cv_all_audios,
        )

        def _save_custom(idx, name, audios, speaker, lang):
            i = int(idx) - 1
            if not audios or i >= len(audios):
                return "サンプルを先に生成してください", gr.update()
            return save_voice_action(name, "custom", lang, speaker, "", "", "", audios[i])

        cv_save_btn.click(
            _save_custom,
            inputs=[cv_save_idx, cv_save_name, cv_audios, cv_speaker, cv_lang],
            outputs=[cv_save_status, gr.State()],  # placeholder for voice list refresh
        )
