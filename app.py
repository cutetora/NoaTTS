"""
Qwen3-TTS Voice Studio
- Tab1: Voice Creation (CustomVoice / VoiceDesign / VoiceClone)
- Tab2: Script Batch Generation
- Tab3: Settings
"""

import os
import re
import sys
import json
import time
import threading
import traceback
from pathlib import Path

import gradio as gr
import numpy as np
import pandas as pd
import soundfile as sf

from config import AppConfig, BASE_DIR
from voice_manager import VoiceManager, VoiceConfig
from tts_engine import TTSEngine
from audio_utils import process_audio, voicevox_notify, check_voice_gender, check_speech_content, trim_silence, check_audio_duration, adjust_speed, trim_interior_pauses
from mascot import _mascot_head_html, _mascot_js, _APP_CSS
from text_utils import normalize_tts_text
from preset_manager import save_preset, load_preset, list_presets
import models_catalog as mcat

import engine_control as ec
from engine_control import (
    cfg, vm, monitor, get_engine, mark_generating, start_preload,
    unload_engine_action, _wait_for_preload,
)

from batch import (
    SCRIPT_COLUMNS, RESULT_COLUMNS, load_script_file, assign_voice_to_char, stop_batch,
    run_batch_generation, on_result_row_select, generate_ng_report,
    export_ng_excel, regenerate_row, check_row, save_script_table,
    save_result_table, export_all,
)

from ui_voice_create import (
    build_custom_tab, build_design_tab, build_clone_tab, build_tuning_panel,
)

# ════════════════════════════════════════════
# Tab 2: Script Batch Generation
# ════════════════════════════════════════════

# ════════════════════════════════════════════
# Tab 3: Settings
# ════════════════════════════════════════════

def save_settings(engine_type, model_size, language, instruct_tmpl):
    prev_engine_type = cfg.tts_engine_type
    cfg.tts_engine_type = engine_type
    cfg.tts_model_size = model_size
    cfg.default_language = language
    if instruct_tmpl.strip():
        cfg.instruct_template = instruct_tmpl
    cfg.save()
    # Reset engine if type or size changed
    needs_reload = (
        prev_engine_type != engine_type
        or (ec.engine and hasattr(ec.engine, "model_size") and ec.engine.model_size != model_size)
    )
    if ec.engine and needs_reload:
        ec.engine.unload()
        ec.engine = None
        return f"設定を保存しました (エンジン再ロードが必要 → 次回生成時に自動)"
    return "設定を保存しました"


# ── モデル管理 (設定タブ「モデル管理」セクションのバックエンド) ──

def _model_choices(engine_type, include_hf):
    """Dropdown 用の (ラベル, repo_id) リストを返す。"""
    entries = mcat.list_for_ui(engine_type, include_hf=include_hf)
    return [(f"{e.label}  [{e.repo_id}]", e.repo_id) for e in entries]


def refresh_model_catalog(engine_type, include_hf):
    """一覧(Dataframe)と選択肢(Dropdown)を更新する。更新確認(ネット)はしない。"""
    entries = mcat.list_for_ui(engine_type, include_hf=include_hf)
    rows = mcat.to_table_rows(entries, with_update=False)
    choices = [(f"{e.label}  [{e.repo_id}]", e.repo_id) for e in entries]
    note = "" if not include_hf else "  (β=HuggingFace最新・動作未確認)"
    return (
        gr.update(value=rows),
        gr.update(choices=choices, value=(choices[0][1] if choices else None)),
        f"一覧を更新しました{note}",
    )


def check_model_updates(engine_type, include_hf):
    """各モデルの更新状態(HFのlastModified比較)を確認して Dataframe を更新する。
    ネットアクセスを伴うため時間がかかる。"""
    entries = mcat.list_for_ui(engine_type, include_hf=include_hf)
    rows = mcat.to_table_rows(entries, with_update=True)
    return gr.update(value=rows), "更新状態を確認しました"


def download_selected_model(repo_id):
    if not repo_id:
        return "モデルを選択してください"
    try:
        mcat.download_model(repo_id)
        return f"ダウンロード完了: {repo_id}"
    except Exception as e:
        return f"ダウンロード失敗: {repo_id} ({e})"


def use_selected_model(engine_type, repo_id):
    """選んだモデルを「使用モデル」に設定して永続化し、エンジンを再ロード待ちにする。
    irodori のみ checkpoint 指定に対応 (qwen3 はサイズ切替で対応のため非対応)。"""
    if not repo_id:
        return "モデルを選択してください"
    if engine_type != "irodori":
        return "使用モデルの指定は現在 Irodori のみ対応です (Qwen3 はモデルサイズで切替)"
    # VoiceDesign 系か本体かで保存先を分ける
    if "VoiceDesign" in repo_id:
        cfg.irodori_vd_checkpoint = repo_id
    else:
        cfg.irodori_checkpoint = repo_id
    cfg.save()
    if ec.engine is not None:
        ec.unload_engine_action()
        ec.engine = None
    # 稼働中の読み上げ daemon にも動的に反映 (停止中なら settings.json のみ→次回起動で反映)
    daemon_note = ""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:7870/model", method="POST",
            data=repo_id.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"})
        urllib.request.urlopen(req, timeout=180)
        daemon_note = " / 読み上げソフトにも反映しました"
    except Exception:
        daemon_note = " (読み上げソフトは次回起動時に反映)"
    return f"使用モデルを設定しました: {repo_id} (次回生成時に再ロード){daemon_note}"


# ════════════════════════════════════════════
# UI
# ════════════════════════════════════════════

def _engine_label() -> str:
    """Pretty engine name for UI display."""
    if cfg.tts_engine_type == "irodori":
        return "🎨 Irodori-TTS v3 (日本語特化・クローン高品質・instruct無効)"
    return f"🤖 Qwen3-TTS {cfg.tts_model_size} (多言語・instruct指示対応)"


def build_ui():
    with gr.Blocks(title="NoaTTS", css=_APP_CSS) as app:
        # マスコットのCSS+HTMLは gr.HTML、JSは末尾の app.load(js=) で実行する。
        gr.HTML(_mascot_head_html())
        gr.Markdown(f"# NoaTTS — Voice Studio")
        engine_banner = gr.Markdown(f"### 現在のエンジン: **{_engine_label()}**")

        # ── Persistent monitor panel (always visible) ──
        with gr.Row():
            with gr.Column(scale=1):
                model_status = gr.Textbox(
                    label="モデル状態", value=ec.preload_status, interactive=False,
                    lines=1, max_lines=2,
                )
            with gr.Column(scale=2):
                activity_display = gr.Textbox(
                    label="進捗モニター", value="待機中", interactive=False,
                    lines=6, max_lines=12,
                )

        # Auto-refresh timer (always active, 1s interval is lightweight)
        monitor_timer = gr.Timer(value=1, active=True)

        def _poll_all():
            return ec.preload_status, monitor.render(), f"### 現在のエンジン: **{_engine_label()}**"

        monitor_timer.tick(
            _poll_all,
            outputs=[model_status, activity_display, engine_banner],
        )

        # ──────────────────────────────────
        # Tab 1: Voice Creation
        # ──────────────────────────────────
        with gr.Tab("ボイス作成", elem_id="tut-tab-create"):
            with gr.Tabs():
                build_custom_tab()
                build_design_tab()
                vc_ref_text = build_clone_tab()
                tune_temp, tune_extract_btn = build_tuning_panel()

        # ──────────────────────────────────
        # Tab 2: Script Batch Generation
        # ──────────────────────────────────
        with gr.Tab("セリフ一括生成"):
            # State
            script_df = gr.State(None)
            char_voice_map = gr.State({})

            # ① File load
            gr.Markdown("### ① ファイル読み込み\n*元のExcelまたはNG修正後のExcelを読み込めます*", elem_id="tut-batch-1")
            with gr.Row():
                script_file = gr.File(label="CSV / Excel ファイル", file_types=[".csv", ".xlsx", ".xls"])
                script_load_btn = gr.Button("読み込み", variant="primary")
                template_btn = gr.Button("テンプレート作成")
            template_file = gr.File(label="ダウンロード", visible=False)
            script_load_status = gr.Textbox(label="ステータス", interactive=False)

            def create_template():
                import tempfile
                tpl = pd.DataFrame(columns=SCRIPT_COLUMNS)
                tpl.loc[0] = ["1", "クールで低い声の青年、無愛想で言葉少な", "001_taro_ohayo", "おはようございます", "", "喜", "少し照れながら", "★"]
                tpl.loc[1] = ["2", "明るく元気なお姉さん、ハキハキした話し方", "002_hanako_tenki", "今日はいい天気ですね", "", "", "穏やかに微笑みながら", ""]
                path = os.path.join(tempfile.gettempdir(), "script_template.csv")
                tpl.to_csv(path, index=False, encoding="utf-8-sig")
                return gr.update(value=path, visible=True)

            template_btn.click(create_template, outputs=[template_file])

            # ② Table display
            gr.Markdown("### ② セリフテーブル", elem_id="tut-batch-2")
            gr.Markdown("*セリフ仮名は読みが曖昧な箇所のみ手動入力（空欄ならセリフをそのまま使用）*")
            script_table = gr.Dataframe(
                headers=SCRIPT_COLUMNS,
                label="セリフデータ",
                interactive=True,
                wrap=True,
            )

            # Character list for mapping
            char_dd = gr.Dropdown(choices=[], label="キャラ選択", interactive=True)

            script_load_btn.click(
                load_script_file,
                inputs=[script_file],
                outputs=[script_df, script_load_status, char_dd],
            ).then(
                lambda df: df if df is not None else gr.update(),
                inputs=[script_df],
                outputs=[script_table],
            )

            # Update script_df when table is edited
            script_table.change(
                lambda df: df,
                inputs=[script_table],
                outputs=[script_df],
            )

            # ③ Character-Voice mapping
            gr.Markdown("### ③ キャラ⇔ボイス紐付け", elem_id="tut-batch-3")
            with gr.Row():
                map_voice_dd = gr.Dropdown(choices=vm.get_voice_choices(), label="ボイス", interactive=True)
                map_assign_btn = gr.Button("割り当て")
            map_display = gr.Textbox(label="現在の割り当て", interactive=False, lines=5)

            map_assign_btn.click(
                assign_voice_to_char,
                inputs=[char_dd, map_voice_dd, char_voice_map],
                outputs=[char_voice_map, map_display],
            )

            # Refresh voice dropdown
            map_refresh_btn = gr.Button("ボイス一覧更新")
            map_refresh_btn.click(
                lambda: gr.update(choices=vm.get_voice_choices()),
                outputs=[map_voice_dd],
            )

            # Preset
            gr.Markdown("### プリセット", elem_id="tut-batch-preset")
            with gr.Row():
                preset_name_input = gr.Textbox(label="プリセット名", placeholder="プロジェクトA")
                preset_save_btn = gr.Button("保存")
                preset_dd = gr.Dropdown(choices=list_presets(), label="プリセット読込")
                preset_load_btn = gr.Button("読込")
            preset_status = gr.Textbox(label="プリセット状態", interactive=False)

            preset_save_btn.click(
                save_preset, inputs=[preset_name_input, char_voice_map],
                outputs=[preset_status],
            ).then(lambda: gr.update(choices=list_presets()), outputs=[preset_dd])

            preset_load_btn.click(
                load_preset, inputs=[preset_dd],
                outputs=[char_voice_map, preset_status],
            ).then(
                lambda m: "\n".join([f"  {k} → {v}" for k, v in m.items()]) if m else "",
                inputs=[char_voice_map], outputs=[map_display],
            )

            # セリフテーブル保存
            with gr.Row():
                script_save_btn = gr.Button("セリフテーブルを元ファイルに上書き保存")
            script_save_status = gr.Textbox(label="保存結果", interactive=False)

            script_save_btn.click(
                save_script_table,
                inputs=[script_df],
                outputs=[script_save_status],
            )

            # ④ Batch generation
            gr.Markdown("### ④ 一括生成", elem_id="tut-batch-4")

            # クローン安定化チェック表示
            with gr.Row():
                check_stable_btn = gr.Button("🔍 ボイスカードの安定化設定を確認", variant="secondary")
                unload_btn = gr.Button("💤 モデルを退避 (VRAM解放)", variant="secondary")
            stable_check_text = gr.Textbox(label="安定化設定", interactive=False, lines=12, visible=False)
            unload_status = gr.Textbox(label="モデル退避結果", interactive=False, visible=False)

            def _unload_with_status():
                msg = unload_engine_action()
                return gr.update(value=msg, visible=True)

            unload_btn.click(_unload_with_status, outputs=[unload_status])

            def _check_stable_settings(mapping_state):
                if not mapping_state:
                    return gr.update(value="キャラ⇔ボイスの割り当てを設定してください", visible=True)
                lines = ["キャラ → ボイス | 設定状態", "=" * 60]
                for char_name, voice_name in mapping_state.items():
                    try:
                        vc_cfg = vm.load_voice(voice_name)
                        # 共通フィールド
                        speed = getattr(vc_cfg, "speed", 1.0) or 1.0
                        max_pause = getattr(vc_cfg, "max_pause_sec", 0.0) or 0.0
                        attr = (vc_cfg.attribute or "").strip()
                        speed_str = f"{float(speed):.2f}x" + (" (調整中)" if abs(float(speed) - 1.0) > 0.01 else "")
                        pause_str = (f"{float(max_pause):.2f}s" if float(max_pause) > 0 else "無効")
                        attr_str = attr if attr else "(未設定)"

                        if vc_cfg.voice_type != "clone":
                            lines.append(f"  {char_name} → {voice_name} [{vc_cfg.voice_type}]")
                            lines.append(f"    話速={speed_str}  最大ポーズ={pause_str}  attribute={attr_str}")
                            continue

                        # クローン固有
                        temp = vc_cfg.clone_temperature if vc_cfg.clone_temperature > 0 else 0.3
                        seed_str = str(vc_cfg.seed) if vc_cfg.seed >= 0 else "未設定(自動で42使用)"
                        has_prompt = vc_cfg.clone_prompt_path and os.path.exists(vc_cfg.clone_prompt_path)
                        prompt_str = "✅キャッシュ済" if has_prompt else "❌未キャッシュ(要抽出)"

                        warnings = []
                        if not has_prompt:
                            warnings.append("⚠️Prompt未キャッシュ")
                        if vc_cfg.seed < 0:
                            warnings.append("⚠️seed未設定")
                        warning_str = " ".join(warnings) if warnings else "✅安定"

                        lines.append(f"  {char_name} → {voice_name} [clone] {warning_str}")
                        lines.append(f"    temp={temp}  seed={seed_str}  prompt={prompt_str}")
                        lines.append(f"    話速={speed_str}  最大ポーズ={pause_str}  attribute={attr_str}")
                    except Exception as e:
                        lines.append(f"  {char_name} → {voice_name}: エラー {e}")
                return gr.update(value="\n".join(lines), visible=True)

            check_stable_btn.click(
                _check_stable_settings,
                inputs=[char_voice_map],
                outputs=[stable_check_text],
            )

            with gr.Row():
                batch_btn = gr.Button("一括生成", variant="primary", size="lg")
                batch_stop_btn = gr.Button("停止", variant="stop")
            with gr.Row():
                batch_skip_existing = gr.Checkbox(label="未生成のみ (既存WAVスキップ)", value=True)
                batch_clone_stable = gr.Checkbox(label="クローン安定化 (temp/seed/prompt固定) [Qwen3のみ]", value=True)
                batch_check_opt = gr.Checkbox(label="セリフチェック (Whisper照合)", value=False)
                batch_only_star = gr.Checkbox(label="★ のみ生成 (おすすめ列が★の行のみ)", value=False)
            with gr.Row():
                batch_max_sec = gr.Number(label="1行最大秒数", info="0=無効 / 例:5.0=超過行に⚠️警告", value=0.0, precision=1)
            batch_status = gr.Textbox(label="生成ステータス", interactive=False, lines=5)

            # ⑤ 生成結果テーブル
            gr.Markdown("### ⑤ 生成結果 (行をクリックで再生)", elem_id="tut-batch-5")
            result_table = gr.Dataframe(
                headers=RESULT_COLUMNS,
                label="生成結果",
                interactive=True,
                wrap=True,
            )
            selected_row_idx = gr.State(-1)

            with gr.Row():
                result_audio = gr.Audio(label="プレビュー", interactive=False)
            with gr.Row():
                result_info = gr.Textbox(label="選択中の行", interactive=False)
                result_regen_btn = gr.Button("🔄 この行を再生成", variant="secondary")
                result_check_btn = gr.Button("🔍 この行をチェック", variant="secondary")
                ng_report_btn = gr.Button("📋 NGレポート", variant="secondary")
            ng_report_text = gr.Textbox(label="NGレポート", interactive=False, lines=10, visible=False)

            # 一括生成 → ステータス + 結果テーブル表示
            batch_btn.click(
                run_batch_generation,
                inputs=[script_df, char_voice_map, batch_skip_existing, batch_clone_stable, batch_check_opt, batch_only_star, batch_max_sec],
                outputs=[batch_status, result_table],
            )
            batch_stop_btn.click(
                stop_batch,
                outputs=[batch_status],
            )

            # 結果テーブル行クリック → 再生
            result_table.select(
                on_result_row_select,
                outputs=[result_audio, result_info, selected_row_idx],
            )

            # 再生成ボタン (生成のみ。チェックは別ボタンで)
            result_regen_btn.click(
                regenerate_row,
                inputs=[selected_row_idx, script_df, char_voice_map, result_table],
                outputs=[result_audio, result_info, result_table],
            )

            # チェックボタン (声質+セリフ照合)
            result_check_btn.click(
                check_row,
                inputs=[selected_row_idx, script_df, result_table],
                outputs=[result_audio, result_info, result_table],
            )

            # NGレポート
            def _show_ng_report():
                report = generate_ng_report()
                return gr.update(value=report, visible=True)

            ng_report_btn.click(
                _show_ng_report,
                outputs=[ng_report_text],
            )

            # ⑥ Export
            gr.Markdown("### ⑥ エクスポート", elem_id="tut-batch-6")
            with gr.Row():
                export_dir = gr.Textbox(label="出力先", value=cfg.output_dir)
            with gr.Row():
                export_btn = gr.Button("音声を一括エクスポート (WAV)", variant="primary")
                result_save_btn = gr.Button("生成結果テーブルを保存 (Excel)")
            with gr.Row():
                ng_export_btn = gr.Button("NG行をExcel出力", variant="stop")
            export_status = gr.Textbox(label="エクスポートステータス", interactive=False, lines=5)
            ng_export_file = gr.File(label="修正済みExcel (このまま①で読み込み可)", visible=False)

            export_btn.click(
                export_all, inputs=[script_df, export_dir],
                outputs=[export_status],
            )
            result_save_btn.click(
                save_result_table, inputs=[result_table, export_dir],
                outputs=[export_status],
            )

            def _export_ng(df_data, out_dir):
                msg, fpath = export_ng_excel(df_data, out_dir)
                if fpath:
                    return msg, gr.update(value=fpath, visible=True)
                return msg, gr.update(visible=False)

            ng_export_btn.click(
                _export_ng,
                inputs=[script_df, export_dir],
                outputs=[export_status, ng_export_file],
            )

        # ──────────────────────────────────
        # Tab 4: Settings
        # ──────────────────────────────────
        with gr.Tab("設定"):  # Tab 3
            gr.Markdown("### マスコット (ノア)")
            set_noa_visible = gr.Checkbox(
                value=True, label="ノアを表示する", interactive=True,
                info="右上のマスコット(ノア)の表示/非表示。消えてしまったノアもここで復活します。",
                elem_id="set-noa-visible",
            )

            gr.Markdown("### TTS設定")
            set_engine_type = gr.Dropdown(
                ["qwen3", "irodori"],
                value=cfg.tts_engine_type,
                label="TTSエンジン (qwen3=Qwen3-TTS / irodori=Irodori-TTS v3)",
            )
            gr.Markdown(
                "*qwen3: 多言語対応、instruct指示が効く / "
                "irodori: 日本語特化、クローン品質高い、instruct指示なし*"
            )
            # モデルサイズは Qwen3 専用。Irodori は 500M 固定で model_size を無視する。
            set_model_size = gr.Dropdown(
                ["1.7B", "0.6B"], value=cfg.tts_model_size,
                label="Qwen3 モデルサイズ" if cfg.tts_engine_type != "irodori" else "Qwen3 モデルサイズ (Irodoriでは無効)",
                interactive=(cfg.tts_engine_type != "irodori"),
            )
            set_language = gr.Dropdown(TTSEngine.LANGUAGES, value=cfg.default_language, label="デフォルト言語")

            gr.Markdown("### モデル管理")
            gr.Markdown(
                "*現在のエンジンで使えるモデルの一覧・ダウンロード・使用切替。"
                "「HF最新も表示」を押すと HuggingFace の新しい版(β・動作未確認)も一覧に出ます。*"
            )
            _init_entries = mcat.list_for_ui(cfg.tts_engine_type, include_hf=False)
            _init_rows = mcat.to_table_rows(_init_entries, with_update=False)
            _init_choices = [(f"{e.label}  [{e.repo_id}]", e.repo_id) for e in _init_entries]
            model_table = gr.Dataframe(
                headers=["モデル", "種別", "状態", "更新"],
                value=_init_rows,
                interactive=False,
                label="利用可能なモデル",
                wrap=True,
            )
            with gr.Row():
                show_hf_chk = gr.Checkbox(value=False, label="HF最新も表示 (β・動作未確認)")
                refresh_cat_btn = gr.Button("一覧を更新")
                check_upd_btn = gr.Button("更新を確認 (HF照会)")
            model_select = gr.Dropdown(
                choices=_init_choices,
                value=(_init_choices[0][1] if _init_choices else None),
                label="操作するモデル",
            )
            with gr.Row():
                dl_model_btn = gr.Button("⬇️ ダウンロード", variant="primary")
                use_model_btn = gr.Button("✅ このモデルを使用", variant="primary")
            model_mgr_status = gr.Textbox(label="モデル管理ログ", interactive=False)

            refresh_cat_btn.click(
                refresh_model_catalog,
                inputs=[set_engine_type, show_hf_chk],
                outputs=[model_table, model_select, model_mgr_status],
            )
            show_hf_chk.change(
                refresh_model_catalog,
                inputs=[set_engine_type, show_hf_chk],
                outputs=[model_table, model_select, model_mgr_status],
            )
            check_upd_btn.click(
                check_model_updates,
                inputs=[set_engine_type, show_hf_chk],
                outputs=[model_table, model_mgr_status],
            )
            dl_model_btn.click(
                download_selected_model,
                inputs=[model_select],
                outputs=[model_mgr_status],
            )
            use_model_btn.click(
                use_selected_model,
                inputs=[set_engine_type, model_select],
                outputs=[model_mgr_status],
            )
            # エンジンを切り替えたらモデル一覧も追従させる
            set_engine_type.change(
                refresh_model_catalog,
                inputs=[set_engine_type, show_hf_chk],
                outputs=[model_table, model_select, model_mgr_status],
            )

            gr.Markdown("### Instruct テンプレート")
            set_instruct = gr.Textbox(value=cfg.instruct_template, label="テンプレート", lines=3)

            set_save_btn = gr.Button("設定を保存", variant="primary")
            set_status = gr.Textbox(label="保存結果", interactive=False)

            def _refresh_engine_dependent(engine_type):
                """エンジン切替後、エンジン依存UIをまとめて更新する。
                能力マトリクス(sync-engine-capabilities スキル参照)に従い、
                Irodoriで無効/不要な項目を非表示/無効化する。"""
                is_iro = (engine_type == "irodori")
                ref_text_u = gr.update(
                    label="参照音声の書き起こし (Irodoriでは不要)" if is_iro else "参照音声の書き起こし (必須)",
                    visible=not is_iro,
                )
                # Temperature: Irodoriは内部で無視するので無効化＋注記
                temp_u = gr.update(
                    interactive=not is_iro,
                    info="Irodoriでは無効 (Qwen3クローン専用)" if is_iro else "0.3推奨。低=安定/高=表現豊か",
                )
                # Prompt抽出ボタン: Qwen3クローン専用なのでIrodoriで非表示
                extract_u = gr.update(visible=not is_iro)
                # モデルサイズ: Irodoriは500M固定なので無効化＋注記
                size_u = gr.update(
                    interactive=not is_iro,
                    label="Qwen3 モデルサイズ (Irodoriでは無効)" if is_iro else "Qwen3 モデルサイズ",
                )
                # 言語: Irodoriは日本語専用なので無効化＋注記
                lang_u = gr.update(
                    interactive=not is_iro,
                    label="デフォルト言語 (Irodoriは日本語専用)" if is_iro else "デフォルト言語",
                )
                # Instructテンプレート: Irodoriは instruct指示なし(感情はクローンのcaptionで指定)
                instruct_u = gr.update(
                    interactive=not is_iro,
                    label="テンプレート (Irodoriでは無効・instruct指示なし)" if is_iro else "テンプレート",
                    info="Irodoriは指示文を解釈しません。感情はクローン調整の「指示/感情」欄(caption)で指定します" if is_iro else None,
                )
                return ref_text_u, temp_u, extract_u, size_u, lang_u, instruct_u

            # エンジン依存UIの更新先 (この順序は _refresh_engine_dependent の返り値と一致)
            _engine_dep_outputs = [
                vc_ref_text, tune_temp, tune_extract_btn,
                set_model_size, set_language, set_instruct,
            ]
            # エンジンを選んだ瞬間に反映 (保存を待たずに無効化/注記が変わる)
            set_engine_type.change(
                _refresh_engine_dependent,
                inputs=[set_engine_type],
                outputs=_engine_dep_outputs,
            )
            set_save_btn.click(
                save_settings,
                inputs=[set_engine_type, set_model_size, set_language, set_instruct],
                outputs=[set_status],
            ).then(
                _refresh_engine_dependent,
                inputs=[set_engine_type],
                outputs=_engine_dep_outputs,
            )

            gr.Markdown("### VRAM")
            with gr.Row():
                unload_btn = gr.Button("全モデルをアンロード (VRAM解放)")
            unload_btn.click(
                lambda: (get_engine().unload() if ec.engine else None) or "モデルをアンロードしました",
                outputs=[set_status],
            )

        # マスコット(ノア)注入JSを load イベントで確実に発火させる。
        # Blocks(js=) は Gradio6.2 で発火しないことがあるため app.load(js=) を使う。
        app.load(None, None, None, js=_mascot_js())

    return app


if __name__ == "__main__":
    # Start model preloading in background
    start_preload()
    app = build_ui()
    _favicon = Path(__file__).parent / "assets" / "noa_icon.png"
    # queue() を有効化: 5シード探索/喜怒哀楽4種など数十秒かかる生成でも
    # リクエストがタイムアウトせず順次処理される (特に VoiceDesign caption 生成は重い)。
    app.queue(default_concurrency_limit=1)
    app.launch(server_name="127.0.0.1", server_port=7860,
               favicon_path=str(_favicon) if _favicon.exists() else None)
