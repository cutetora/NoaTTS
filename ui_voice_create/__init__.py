"""ボイス作成タブ (Tab1) の UI ビルダー群 (パッケージ)。

旧 ui_voice_create.py を1ブロック=1ファイルに分割。公開APIは従来どおり
(`from ui_voice_create import build_custom_tab` 等は無変更で動く)。
  custom_tab.py / design_tab.py / clone_tab.py … A/B/C サブタブ
  tuning_panel.py + tuning_logic.py … 保存済みボイス調整 (一覧機能も統合)
"""
from .custom_tab import build_custom_tab
from .design_tab import build_design_tab
from .clone_tab import build_clone_tab
from .tuning_panel import build_tuning_panel
