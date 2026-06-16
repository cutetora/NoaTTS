"""B. ボイスデザイン タブ (声の説明文から生成→キャラカード保存)。"""
import gradio as gr

from engine.tts_engine import TTSEngine
from voice.voice_creation import gen_voice_design, save_voice_action


def build_design_tab():
    # ── B. VoiceDesign ──
    with gr.Tab("B. ボイスデザイン [Qwen3推奨]"):
        vd_audios = gr.State([])
        vd_seeds = gr.State([])
        with gr.Row():
            # 左カラム: 入力・操作・保存
            with gr.Column(scale=1):
                with gr.Row():
                    vd_lang = gr.Dropdown(
                        choices=TTSEngine.LANGUAGES, value="Japanese", label="言語"
                    )
                    vd_num = gr.Slider(1, 5, value=3, step=1, label="生成数")
                vd_desc = gr.Textbox(
                    label="声の説明 (声の特徴を記述)",
                    placeholder="高めの声で可愛い感じの少女、元気でハキハキした話し方",
                    lines=2,
                )
                vd_text = gr.Textbox(label="テスト文", value="こんにちは、テスト音声です。")
                vd_btn = gr.Button("サンプル生成", variant="primary")
                vd_status = gr.Textbox(label="ステータス", interactive=False, lines=4)

                # ── Save as character card ──
                gr.Markdown("#### キャラカードとして保存")
                with gr.Row():
                    vd_save_idx = gr.Slider(1, 5, value=1, step=1, label="保存サンプル番号")
                    vd_save_name = gr.Textbox(label="キャラ名", placeholder="花子")
                vd_save_attr = gr.Textbox(
                    label="キャラ属性 (一括生成で最優先される人物像)",
                    placeholder="明るく元気なお姉さん、ハキハキした話し方",
                    lines=2,
                )
                vd_save_btn = gr.Button("キャラカード保存", variant="primary")
                vd_save_status = gr.Textbox(label="保存結果", interactive=False)

            # 右カラム: 生成結果(サンプル試聴)
            with gr.Column(scale=1):
                vd_audio1 = gr.Audio(label="サンプル 1")
                vd_audio2 = gr.Audio(label="サンプル 2")
                vd_audio3 = gr.Audio(label="サンプル 3")
                vd_audio4 = gr.Audio(label="サンプル 4", visible=False)
                vd_audio5 = gr.Audio(label="サンプル 5", visible=False)
        vd_all_audios = [vd_audio1, vd_audio2, vd_audio3, vd_audio4, vd_audio5]

        def _gen_design(lang, desc, text, num):
            audios, seeds, msg = gen_voice_design(lang, desc, text, num)
            updates = []
            for i in range(5):
                if i < len(audios):
                    updates.append(gr.update(value=audios[i], visible=True))
                else:
                    updates.append(gr.update(value=None, visible=i < 3))
            return [audios, seeds, msg] + updates

        vd_btn.click(
            _gen_design,
            inputs=[vd_lang, vd_desc, vd_text, vd_num],
            outputs=[vd_audios, vd_seeds, vd_status] + vd_all_audios,
        )

        def _save_design(idx, name, audios, seeds, lang, desc, attr):
            i = int(idx) - 1
            if not audios or i >= len(audios):
                return "サンプルを先に生成してください", gr.update()
            seed = seeds[i] if seeds and i < len(seeds) else -1
            return save_voice_action(
                name, "design", lang, "", desc, "", "",
                audios[i], seed=seed, attribute=attr,
            )

        vd_save_btn.click(
            _save_design,
            inputs=[vd_save_idx, vd_save_name, vd_audios, vd_seeds,
                    vd_lang, vd_desc, vd_save_attr],
            outputs=[vd_save_status, gr.State()],
        )
