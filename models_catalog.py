"""TTSモデルのカタログ・状態照会・ダウンロード (モデル管理UIのバックエンド)。

UI (app.py の設定タブ) から呼ばれる。HuggingFace 依存のロジックはここに集約し、
失敗時は必ずフォールバック (固定リストのみ表示) して UI に例外を漏らさない。

モデルの出どころは2系統:
  - VERIFIED  : 動作確認済み (推奨)。コードに固定で定義。
  - HF 動的   : HuggingFace を検索して取得。「動作未確認・β」として区別。
"""
from dataclasses import dataclass


@dataclass
class ModelEntry:
    repo_id: str
    label: str          # 表示名
    engine: str         # "irodori" | "qwen3"
    role: str           # "main" | "voicedesign" | "custom" | "clone"
    verified: bool      # True=動作確認済み(推奨) / False=β(動作未確認)


# ── 動作確認済みモデル (推奨) ─────────────────────────────
# 真実の源は各エンジンのクラス定数。二重管理を避けるためそこから組み立てる。
def _verified_entries() -> list[ModelEntry]:
    entries: list[ModelEntry] = []
    try:
        from irodori_engine import IrodoriEngine
        entries.append(ModelEntry(
            IrodoriEngine.DEFAULT_CHECKPOINT,
            "Irodori 500M v3 (読み上げ本体)", "irodori", "main", True))
        entries.append(ModelEntry(
            IrodoriEngine.VOICEDESIGN_CHECKPOINT,
            "Irodori 600M v3 VoiceDesign", "irodori", "voicedesign", True))
    except Exception:
        pass
    try:
        from tts_engine import TTSEngine
        seen = set()
        for role, sizes in TTSEngine.MODEL_MAP.items():
            for size, repo in sizes.items():
                if repo in seen:
                    continue
                seen.add(repo)
                entries.append(ModelEntry(
                    repo, f"Qwen3 {size} ({role})", "qwen3", role, True))
    except Exception:
        pass
    return entries


def verified_for(engine_type: str) -> list[ModelEntry]:
    """指定エンジンの動作確認済みモデル一覧。"""
    return [e for e in _verified_entries() if e.engine == engine_type]


# ── HuggingFace 動的取得 (β・動作未確認) ──────────────────
# エンジンごとの検索条件 (author, search)。
_HF_SEARCH = {
    "irodori": ("Aratako", "Irodori-TTS"),
    "qwen3": ("Qwen", "Qwen3-TTS"),
}


def fetch_hf_candidates(engine_type: str, limit: int = 20) -> list[ModelEntry]:
    """HF を検索して候補を返す。動作確認済みと重複するものは除外。
    ネット不通/API失敗時は空リストを返す (UI は固定リストのみ表示)。"""
    cond = _HF_SEARCH.get(engine_type)
    if not cond:
        return []
    author, search = cond
    try:
        from huggingface_hub import list_models
        verified_ids = {e.repo_id for e in verified_for(engine_type)}
        out: list[ModelEntry] = []
        for m in list_models(author=author, search=search, limit=limit):
            if m.id in verified_ids:
                continue
            out.append(ModelEntry(m.id, m.id, engine_type, "main", False))
        return out
    except Exception:
        return []


# ── ローカル状態 / 更新判定 ────────────────────────────────
def _local_last_modified(repo_id: str):
    """ローカルキャッシュにある場合、その最終更新時刻(aware datetime)を返す。
    scan_cache_dir は float(UNIX秒)を返すので datetime(UTC)に統一する
    (remote の model_info.lastModified が aware datetime のため比較可能にする)。
    無ければ None。"""
    try:
        from datetime import datetime, timezone
        from huggingface_hub import scan_cache_dir
        for r in scan_cache_dir().repos:
            if r.repo_id == repo_id:
                revs = list(r.revisions)
                if revs:
                    ts = max(rev.last_modified for rev in revs)
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        pass
    return None


def is_downloaded(repo_id: str) -> bool:
    return _local_last_modified(repo_id) is not None


def _remote_last_modified(repo_id: str):
    try:
        from huggingface_hub import model_info
        return model_info(repo_id).lastModified
    except Exception:
        return None


def update_state(repo_id: str) -> str:
    """更新状態を文字列で返す: 未DL / 最新 / 更新あり / 確認不可。
    ネットアクセスを伴う (model_info)。"""
    local = _local_last_modified(repo_id)
    if local is None:
        return "未DL"
    remote = _remote_last_modified(repo_id)
    if remote is None:
        return "最新?(確認不可)"
    try:
        return "更新あり" if remote > local else "最新"
    except TypeError:
        return "最新?(確認不可)"


# ── ダウンロード ──────────────────────────────────────────
def download_model(repo_id: str):
    """指定モデルを取得する。snapshot_download でリポジトリ一式を落とす。
    成功でローカルパス、失敗で例外。UI 側で try/except すること。"""
    from huggingface_hub import snapshot_download
    return snapshot_download(repo_id=repo_id)


# ── UI 表示用のまとめ ─────────────────────────────────────
def list_for_ui(engine_type: str, include_hf: bool = False) -> list[ModelEntry]:
    """UI 表示用のモデル一覧。verified を先に、HF候補(β)を後ろに。"""
    entries = list(verified_for(engine_type))
    if include_hf:
        entries += fetch_hf_candidates(engine_type)
    return entries


def to_table_rows(entries: list[ModelEntry], with_update: bool = False) -> list[list]:
    """gr.Dataframe 用の行データに変換。
    列: モデル / 種別 / 状態 / 更新。with_update=False なら更新列は '-'."""
    rows = []
    for e in entries:
        kind = "推奨" if e.verified else "β(未確認)"
        dl = "DL済み" if is_downloaded(e.repo_id) else "未DL"
        upd = update_state(e.repo_id) if with_update else "-"
        rows.append([e.label, kind, dl, upd])
    return rows
