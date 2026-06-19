"""保存済みボイス調整パネルの UI 部品と配線。

ロジックは tuning_logic.py (UI非依存)。(tune_temp, tune_extract_btn) を返す
(エンジン切替時に設定タブが無効化/非表示を切り替えるため)。"""
import gradio as gr

from engine.engine_control import cfg, vm
from engine.emotion_emoji import EMOTION_EMOJI
from voice.voice_creation import (
    preview_voice, get_voice_icon_path, set_voice_icon_action, delete_voice_action,
)
from .tuning_logic import (
    _tune_refresh, _tune_load, _tune_extract_prompt, _tune_test,
    _tune_random_test, _tune_random5_seeds, _tune_seed_random3,
    _tune_emotion4_test, _tune_emotion4b_test, _tune_save,
)


def build_tuning_panel():
    # ── Saved Voice Tuning (旧「保存済みボイス一覧」を統合) ──
    gr.Markdown("---\n#### 保存済みボイス調整")
    gr.Markdown("*保存済みのボイスを選んで、seed・話速・temperature・promptキャッシュを調整・試聴します*")
    tune_seed_states = [gr.State(-1) for _ in range(5)]
    tune_audio_components = []
    tune_adopt_btns = []
    with gr.Row():
        # 左カラム: 調整操作・試聴ボタン・保存
        with gr.Column(scale=1):
            with gr.Row():
                tune_voice_dd = gr.Dropdown(
                    choices=vm.get_voice_choices(),
                    label="調整するボイス", interactive=True,
                )
                tune_refresh_btn = gr.Button("更新")
            # Temperature と Prompt抽出は Qwen3クローン専用。
            # Irodori は temperature を内部で無視し、prompt は latent(.pt) 方式。
            _is_iro = (cfg.tts_engine_type == "irodori")
            with gr.Row():
                tune_temp = gr.Slider(
                    0.1, 1.0, value=0.3, step=0.05, label="Temperature",
                    info="0.3推奨。低=安定/高=表現豊か" if not _is_iro else "Irodoriでは無効 (Qwen3クローン専用)",
                    interactive=not _is_iro,
                )
                tune_seed = gr.Number(label="Seed", info="-1=ランダム/固定値推奨", value=42, precision=0)
            with gr.Row():
                tune_speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="話速", info="1.0=等倍。上げると速い")
                tune_max_pause = gr.Slider(0.0, 1.0, value=0.0, step=0.05, label="ポーズ上限秒", info="0=無効。間を短縮")
            tune_prompt_status = gr.Textbox(label="Promptキャッシュ状態", interactive=False)
            tune_extract_btn = gr.Button(
                "Promptを抽出してキャッシュ", variant="secondary", visible=not _is_iro,
            )
            tune_test_text = gr.Textbox(label="テスト文", value="こんにちは、テスト音声です。")
            # 絵文字パレット: テスト文に感情絵文字を挿入する (Irodoriクローンで強く効く)。
            # 同じ絵文字を重ねるほど効果が強まる。caption方式より明確に感情が乗る。
            gr.Markdown("感情絵文字を挿入 (文中に入れると声に乗る・重ねると強調):")
            _emoji_btns = []
            with gr.Row():
                for _emo, _label, _desc in EMOTION_EMOJI:
                    _b = gr.Button(f"{_emo} {_label}", variant="secondary", size="sm")
                    _emoji_btns.append((_b, _emo))
            # 指示/感情(caption方式): 試聴に使うと同時に「設定をカードに保存」で
            # 既定感情(default_caption)として保存され、daemon読み上げ・バッチ生成に
            # 恒久反映される (design/clone)。「同じ声のまま感情だけ変える」の指定欄。
            tune_emotion = gr.Textbox(
                label="既定感情 / 指示 (保存対象)",
                placeholder="例: 落ち着いた低い声で / 嬉しそうに  (空なら感情指定なし)",
                info="保存すると この声の既定感情になり、読み上げ本体に反映されます (design/clone)。感情演技は上の絵文字の方が強く効きます",
            )
            with gr.Row():
                tune_test_btn = gr.Button("試聴", variant="primary")
                tune_random_btn = gr.Button("ランダム3文で試聴", variant="secondary")
            with gr.Row():
                tune_random5_btn = gr.Button("5シード探索", variant="secondary")
                tune_seed_random3_btn = gr.Button("シード固定で3文", variant="secondary")
            with gr.Row():
                tune_emotion4_btn = gr.Button("喜怒哀楽4種で試聴", variant="secondary")
                tune_emotion4b_btn = gr.Button("照れ驚き眠気クール4種で試聴", variant="secondary")
            tune_save_btn = gr.Button("設定をカードに保存", variant="primary")
            tune_status = gr.Textbox(label="調整結果", interactive=False, lines=8)

        # 右カラム: 保存時サンプル + 試聴結果5個（各々に「このシードを採用」ボタン付き）
        with gr.Column(scale=1):
            tune_preview = gr.Audio(label="保存時サンプル", interactive=False)
            for i in range(5):
                tune_audio = gr.Audio(label=f"試聴結果 {i+1}", interactive=False, visible=(i == 0))
                tune_adopt_btn = gr.Button(f"⭐ このシードを採用", variant="secondary", visible=False, size="sm")
                tune_audio_components.append(tune_audio)
                tune_adopt_btns.append(tune_adopt_btn)

    # アクセス用エイリアス
    tune_audio = tune_audio_components[0]
    tune_audio2 = tune_audio_components[1]
    tune_audio3 = tune_audio_components[2]
    tune_audio4 = tune_audio_components[3]
    tune_audio5 = tune_audio_components[4]


    # 絵文字ボタン: クリックでテスト文の末尾に絵文字を追加 (重ねると強調)
    for _btn, _emo in _emoji_btns:
        _btn.click(
            lambda cur, e=_emo: (cur or "") + e,
            inputs=[tune_test_text],
            outputs=[tune_test_text],
        )

    tune_refresh_btn.click(_tune_refresh, outputs=[tune_voice_dd])


    tune_voice_dd.change(
        _tune_load,
        inputs=[tune_voice_dd],
        outputs=[tune_temp, tune_seed, tune_speed, tune_max_pause, tune_prompt_status, tune_emotion],
    )
    # ボイス選択で保存時サンプルと現在アイコンも連動 (旧ボイス一覧から統合)
    tune_voice_dd.change(preview_voice, inputs=[tune_voice_dd], outputs=[tune_preview])


    tune_extract_btn.click(
        _tune_extract_prompt,
        inputs=[tune_voice_dd],
        outputs=[tune_prompt_status],
    )


    tune_test_btn.click(
        _tune_test,
        inputs=[tune_voice_dd, tune_temp, tune_seed, tune_speed, tune_max_pause, tune_test_text, tune_emotion],
        outputs=[tune_audio, tune_status],
    )


    tune_random_btn.click(
        _tune_random_test,
        inputs=[tune_voice_dd, tune_temp, tune_seed, tune_speed, tune_max_pause, tune_emotion],
        outputs=[tune_audio, tune_audio2, tune_audio3, tune_status],
    )


    tune_random5_btn.click(
        _tune_random5_seeds,
        inputs=[tune_voice_dd, tune_temp, tune_test_text, tune_speed, tune_max_pause, tune_emotion],
        outputs=tune_audio_components + tune_seed_states + tune_adopt_btns + [tune_status],
    )

    # 「このシードを採用」ボタンの処理
    for i in range(5):
        tune_adopt_btns[i].click(
            lambda s: (s, f"seed={s} を採用しました"),
            inputs=[tune_seed_states[i]],
            outputs=[tune_seed, tune_status],
        )


    tune_seed_random3_btn.click(
        _tune_seed_random3,
        inputs=[tune_voice_dd, tune_temp, tune_seed, tune_speed, tune_max_pause, tune_emotion],
        outputs=tune_audio_components + tune_adopt_btns + [tune_status],
    )


    tune_emotion4_btn.click(
        _tune_emotion4_test,
        inputs=[tune_voice_dd, tune_temp, tune_seed, tune_speed, tune_max_pause, tune_emotion],
        outputs=tune_audio_components + tune_adopt_btns + [tune_status],
    )
    tune_emotion4b_btn.click(
        _tune_emotion4b_test,
        inputs=[tune_voice_dd, tune_temp, tune_seed, tune_speed, tune_max_pause, tune_emotion],
        outputs=tune_audio_components + tune_adopt_btns + [tune_status],
    )


    tune_save_btn.click(
        _tune_save,
        inputs=[tune_voice_dd, tune_temp, tune_seed, tune_speed, tune_max_pause, tune_emotion],
        outputs=[tune_status],
    )

    # ── トレイアイコン設定 (旧ボイス一覧から統合・一番下) ──
    gr.Markdown("#### 🎤 トレイアイコン設定")
    gr.Markdown("*選択中のボイスに、タスクトレイ表示用の画像を設定します（中央正方形で保存）。設定すると、そのボイス選択時にトレイのアイコンがこの絵に変わります。*")
    with gr.Row():
        tune_icon_upload = gr.Image(label="アイコン画像", type="filepath", height=160)
        tune_icon_current = gr.Image(label="現在のアイコン", interactive=False, height=160)
    tune_icon_set_btn = gr.Button("このボイスのトレイアイコンに設定", variant="primary")
    tune_icon_status = gr.Textbox(label="アイコン設定結果", interactive=False)
    with gr.Row():
        tune_del_btn = gr.Button("このボイスを削除", variant="stop")
    tune_del_status = gr.Textbox(label="削除結果", interactive=False)

    # ボイス選択で現在アイコンも連動
    tune_voice_dd.change(get_voice_icon_path, inputs=[tune_voice_dd], outputs=[tune_icon_current])
    tune_icon_set_btn.click(
        set_voice_icon_action,
        inputs=[tune_voice_dd, tune_icon_upload],
        outputs=[tune_icon_status],
    ).then(get_voice_icon_path, inputs=[tune_voice_dd], outputs=[tune_icon_current])
    tune_del_btn.click(
        delete_voice_action, inputs=[tune_voice_dd],
        outputs=[tune_del_status, tune_voice_dd],
    )
    return tune_temp, tune_extract_btn
