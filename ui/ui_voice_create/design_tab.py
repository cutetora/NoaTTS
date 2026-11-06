"""B. ボイスデザイン タブ (声の説明文から生成→キャラカード保存)。"""
import gradio as gr

from engine.tts_engine import TTSEngine
from voice.voice_creation import gen_voice_design, save_voice_action, save_design_as_clone


def build_design_tab():
    # ── B. VoiceDesign ──
    with gr.Tab("B. ボイスデザイン [Qwen3推奨]"):
        vd_audios = gr.State([])
        vd_seeds = gr.State([])
        # 生成時のテスト文/言語/声の説明。生成後に入力欄を編集しても、クローン保存の
        # ref_text が実際に喋らせた文と食い違わないよう、生成時点の値を持っておく。
        vd_gen_meta = gr.State({})
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
                # 保存対象サンプルのseedを明示 (VoiceDesignは声=seed依存のため再現に必須)
                vd_save_seed_info = gr.Markdown("*（サンプル未生成）*")
                vd_save_attr = gr.Textbox(
                    label="キャラ属性 (一括生成で最優先される人物像)",
                    placeholder="明るく元気なお姉さん、ハキハキした話し方",
                    lines=2,
                )
                vd_save_btn = gr.Button("キャラカード保存", variant="primary")
                vd_save_status = gr.Textbox(label="保存結果", interactive=False)

                # ── Save as clone card (デザインの声を参照音声として固定) ──
                gr.Markdown(
                    "#### クローンカードとして保存（この声を固定）\n"
                    "上で選んだサンプルを**参照音声**、テスト文を**書き起こし**、"
                    "seed をそのままクローンカードに引き継ぎます。"
                    "声質は参照音声で決まり、クローンの seed は抑揚の揺れを固定します。"
                    "参照音声は 3〜10 秒が目安です。"
                )
                vd_clone_name = gr.Textbox(
                    label="クローンカード名", placeholder="空なら「キャラ名_clone」")
                vd_clone_overwrite = gr.Checkbox(
                    label="同名カードがあれば上書きを許可（フォルダを削除して作り直す）",
                    value=False)
                vd_clone_btn = gr.Button("クローンカードとして保存", variant="secondary")
                vd_clone_status = gr.Textbox(
                    label="クローン保存結果", interactive=False, lines=3)

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
                    updates.append(gr.update(value=audios[i], visible=True,
                                             label=f"サンプル {i+1} (seed={seeds[i]})"))
                else:
                    updates.append(gr.update(value=None, visible=i < 3,
                                             label=f"サンプル {i+1}"))
            seed_info = (f"**保存サンプル 1 → seed={seeds[0]}** （このseedがカードに保存され再現に使われます）"
                         if seeds else "*（サンプル未生成）*")
            meta = {"text": text, "lang": lang, "desc": desc} if audios else {}
            return [audios, seeds, msg, seed_info, meta] + updates

        vd_btn.click(
            _gen_design,
            inputs=[vd_lang, vd_desc, vd_text, vd_num],
            outputs=[vd_audios, vd_seeds, vd_status, vd_save_seed_info, vd_gen_meta]
                    + vd_all_audios,
        )

        def _show_save_seed(idx, seeds):
            """保存サンプル番号を変えたら、そのサンプルのseedを表示する。"""
            i = int(idx) - 1
            if seeds and 0 <= i < len(seeds):
                return f"**保存サンプル {int(idx)} → seed={seeds[i]}** （このseedがカードに保存され再現に使われます）"
            return "*（そのサンプルは未生成）*"

        vd_save_idx.change(
            _show_save_seed,
            inputs=[vd_save_idx, vd_seeds],
            outputs=[vd_save_seed_info],
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

        def _save_design_clone(idx, clone_name, overwrite, audios, seeds, meta,
                               char_name, attr):
            i = int(idx) - 1
            if not audios or i >= len(audios):
                return "サンプルを先に生成してください", gr.update(value=False)
            name = (clone_name or "").strip()
            if not name and (char_name or "").strip():
                name = f"{char_name.strip()}_clone"
            seed = seeds[i] if seeds and i < len(seeds) else -1
            meta = meta or {}
            msg, _saved = save_design_as_clone(
                name, audios[i], seed,
                ref_text=meta.get("text", ""), language=meta.get("lang", "Japanese"),
                voice_desc=meta.get("desc", ""), attribute=attr,
                overwrite=bool(overwrite),
            )
            # 上書き許可は1回きり (次の保存で誤って消さないよう毎回戻す)
            return msg, gr.update(value=False)

        vd_clone_btn.click(
            _save_design_clone,
            inputs=[vd_save_idx, vd_clone_name, vd_clone_overwrite, vd_audios,
                    vd_seeds, vd_gen_meta, vd_save_name, vd_save_attr],
            outputs=[vd_clone_status, vd_clone_overwrite],
        )
