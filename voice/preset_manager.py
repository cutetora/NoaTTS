"""キャラ⇔ボイス割り当てプリセットの保存・読込。

app.py から分離。presets/<名前>.json に {"mapping": {キャラ名: ボイス名}} を永続化する。
presets_dir は呼び出しのたびに settings.json から解決する（プリセット操作は稀な
UIクリックなのでコストは無視できる。app.py の cfg インスタンスと二重管理にしない）。
"""
import json
from pathlib import Path

from config import AppConfig


def _presets_dir() -> Path:
    return Path(AppConfig.load().presets_dir)


def save_preset(name, mapping_state):
    if not name:
        return "プリセット名を入力してください"
    try:
        preset_dir = _presets_dir()
        preset_dir.mkdir(parents=True, exist_ok=True)
        data = {"mapping": mapping_state or {}}
        (preset_dir / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return f"プリセット '{name}' を保存しました"
    except Exception as e:
        return f"エラー: {e}"


def load_preset(name):
    try:
        path = _presets_dir() / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = data.get("mapping", {})
        display = "\n".join([f"  {k} → {v}" for k, v in mapping.items()])
        return mapping, f"プリセット '{name}' を読み込みました\n{display}"
    except Exception as e:
        return {}, f"読み込みエラー: {e}"


def list_presets():
    preset_dir = _presets_dir()
    if not preset_dir.exists():
        return []
    return [p.stem for p in sorted(preset_dir.glob("*.json"))]
