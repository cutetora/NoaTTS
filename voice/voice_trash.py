"""ボイスカードのゴミ箱 (削除 → 30日保管 → 自動で完全削除)。

GUI・daemon に依存しない純関数。Voice Studio (Gradio) と 読み上げ設定ウィンドウ (pywebview) の
削除が、どちらもこれを使う。voices/<名前>/ は voices_trash/<名前>__<日時>/ へ「移動」するだけで、
30日以内なら元に戻せる。
"""
import json
import os
import re
import shutil
import socket
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

RETENTION_DAYS = 30
TRASH_DIRNAME = "voices_trash"

_STAMP_FMT = "%Y%m%d-%H%M%S"
# 30日の起算にはフォルダ名の日時を使う (mtime はコピーや復元で変わるため)
_ENTRY_RE = re.compile(r"^(?P<name>.+)__(?P<stamp>\d{8}-\d{6})$")
_RESERVED_RE = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)
_BAD_CHARS = '\\/:*?"<>|'


class TrashError(Exception):
    """削除・復元できない理由。メッセージはそのままユーザーに見せる。"""


def trash_dir_for(voices_dir) -> Path:
    """ゴミ箱の場所。voices/ の外 (プロジェクト直下) なので、ボイス一覧や /voices には出ない。"""
    return Path(voices_dir).resolve().parent / TRASH_DIRNAME


# ── 検証・判定 ──

def check_name(name) -> str:
    """ボイス名の形式を検証する。フォルダを動かす操作なので、voices/ の外を指す名前や、
    Windows が別のフォルダに解決する名前は弾く。"""
    # strip しない: 前後の空白を削ると、別のフォルダ (" 花子" → "花子") を指してしまう
    name = str(name or "")
    if not name or name in (".", "..") or any(c in name for c in _BAD_CHARS):
        raise TrashError("ボイス名が不正です")
    if name != name.strip():
        raise TrashError("ボイス名の前後に空白があるため扱えません")
    if _RESERVED_RE.match(name):
        raise TrashError(f"'{name}' は Windows の予約名のため扱えません")
    # Win32 は末尾の '.' や空白を無視する ("花子." が "花子" を指す)
    if name.endswith((".", " ")):
        raise TrashError("ボイス名の末尾に「.」や空白は使えません")
    return name


# 配布物に入っている同梱ボイス。config.default.json の有無とは別に、名前でも守る
# (default.json の置き忘れ・削除で、同梱ボイスが消せてしまうのを防ぐ)。
BUNDLED_VOICES = frozenset({"noa", "man"})


def is_protected(voice_dir) -> bool:
    """同梱ボイスは消せない: 名前が同梱のものか、配布物の config.default.json を持つもの。
    後者はユーザーがフォルダごと複製したものも該当するが、消せない側に倒す。"""
    d = Path(voice_dir)
    return d.name.lower() in BUNDLED_VOICES or (d / "config.default.json").exists()


def _is_voice_dir(d: Path) -> bool:
    return d.is_dir() and ((d / "config.json").exists() or (d / "config.default.json").exists())


def _find_dir(voices_dir, name, exact=False):
    """voices_dir 直下から name のフォルダを返す (無ければ None)。
    exact=False は大文字小文字を無視 (同名の衝突チェック用)。exact=True は完全一致のみ
    (削除の対象を決める時。大文字小文字だけ違う別フォルダを動かさないため)。"""
    try:
        for p in Path(voices_dir).iterdir():
            if p.is_dir() and (p.name == name if exact else p.name.lower() == name.lower()):
                return p
    except OSError:
        pass
    return None


def active_voice_names(root, port=7870, timeout=1.5) -> set:
    """いま読み上げに使われているボイス名 (小文字)。daemon の /health と _active_voice.txt の両方を見る。
    daemon のポートが開いているのに /health を読めない (合成中で応答が遅い等) 時は、
    「使っていない」と誤判定して消さないよう TrashError にする。daemon 停止中はファイルだけで判定する。"""
    names = set()
    daemon_up = False
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        daemon_up = True
    except OSError:
        pass
    if daemon_up:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
                h = json.loads(r.read().decode("utf-8"))
            if h.get("voice"):
                names.add(str(h["voice"]).strip().lower())
            # /say_wav・/v1・掛け合いが、アクティブ声とは別に一時ロードして使っている声
            for b in (h.get("busy_voices") or []):
                names.add(str(b).strip().lower())
        except Exception:
            raise TrashError("読み上げ中のボイスを確認できませんでした。"
                             "daemon が応答していません。少し待ってから、もう一度お試しください")
    try:
        v = (Path(root) / "_active_voice.txt").read_text(encoding="utf-8").strip()
        if v:
            names.add(v.lower())
    except FileNotFoundError:
        pass  # まだ一度も daemon を起動していない
    except Exception as e:
        # 読めない理由が分からないまま「使っていない」と扱わない
        raise TrashError(f"読み上げ中のボイスを確認できませんでした ({e})")
    return names


# ── 一覧 ──

def voice_rows(voices_dir, active_names=()) -> list:
    """整理画面に出すボイスの一覧。使えない理由 (同梱/読み上げ中) も付ける。最近使った順。"""
    active = {str(n).lower() for n in active_names}
    rows = []
    try:
        dirs = sorted(Path(voices_dir).iterdir())
    except OSError:
        return []
    for d in dirs:
        if not _is_voice_dir(d):
            continue
        vtype, last = "", ""
        for fname in ("config.json", "config.default.json"):
            try:
                data = json.loads((d / fname).read_text(encoding="utf-8"))
                vtype = data.get("voice_type", "") or ""
                last = data.get("last_used_at", "") or ""
                break
            except Exception:
                continue
        protected = is_protected(d)
        is_active = d.name.lower() in active
        reason = "protected" if protected else ("active" if is_active else "")
        rows.append({"name": d.name, "type": vtype, "last_used": last,
                     "protected": protected, "active": is_active, "reason": reason})
    rows.sort(key=lambda r: (r["last_used"] or "0"), reverse=True)
    return rows


def _is_link(p: Path) -> bool:
    """シンボリックリンクまたは Windows のジャンクション (rmtree や移動で外のフォルダに及ばせない)。"""
    try:
        if p.is_symlink():
            return True
        attrs = getattr(p.lstat(), "st_file_attributes", 0)
        return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def _parse_entry(name):
    m = _ENTRY_RE.match(name)
    if not m:
        return None
    try:
        return m.group("name"), datetime.strptime(m.group("stamp"), _STAMP_FMT)
    except ValueError:
        return None


def list_trash(voices_dir, now=None) -> list:
    """ゴミ箱の中身。新しく捨てた順。days_left は完全削除までの日数 (0 は次の掃除で削除)。"""
    now = now or datetime.now()
    tdir = trash_dir_for(voices_dir)
    out = []
    try:
        entries = list(tdir.iterdir())
    except OSError:
        return []
    for p in entries:
        parsed = _parse_entry(p.name) if p.is_dir() else None
        if not parsed:
            continue
        name, deleted = parsed
        age_days = (now - deleted).total_seconds() / 86400
        out.append({"entry": p.name, "name": name,
                    "deleted_at": deleted.strftime("%Y-%m-%d"),
                    "days_left": max(0, RETENTION_DAYS - int(age_days)),
                    "_deleted": deleted})
    out.sort(key=lambda e: e["_deleted"], reverse=True)
    for e in out:
        del e["_deleted"]
    return out


# ── 削除・復元・掃除 ──

def move_to_trash(voices_dir, name, active_names=(), now=None) -> dict:
    """ボイスをゴミ箱へ移動する。同梱・読み上げ中・存在しない・形式不正は TrashError。"""
    name = check_name(name)
    src = _find_dir(voices_dir, name, exact=True)
    if src is None or not _is_voice_dir(src):
        raise TrashError(f"「{name}」が見つかりません")
    if _is_link(src):
        # 復元・完全削除はリンクを扱わないので、入れると戻せず消えもしない状態になる
        raise TrashError(f"「{src.name}」はリンク (ジャンクション) のため扱えません")
    if is_protected(src):
        raise TrashError(f"「{src.name}」は同梱ボイスのため削除できません")
    if src.name.lower() in {str(n).lower() for n in active_names}:
        raise TrashError(f"「{src.name}」は現在、読み上げに使っています。"
                         f"別のボイスに切り替えてから、もう一度削除してください")
    now = now or datetime.now()
    tdir = trash_dir_for(voices_dir)
    tdir.mkdir(exist_ok=True)
    # 同じ名前を同じ秒に2回捨てても衝突しないよう、日時を1秒ずつずらす
    stamp_dt = now
    for _ in range(60):
        dst = tdir / f"{src.name}__{stamp_dt.strftime(_STAMP_FMT)}"
        if not dst.exists():
            break
        stamp_dt = stamp_dt + timedelta(seconds=1)
    else:
        raise TrashError("ゴミ箱に移せませんでした (名前が重なっています)")
    try:
        os.replace(src, dst)
    except OSError as e:
        raise TrashError(f"「{src.name}」を移動できませんでした。"
                         f"ファイルを使用中の可能性があります ({e})")
    purge_expired(voices_dir, now=now)
    return {"name": src.name, "entry": dst.name}


def restore(voices_dir, entry, now=None) -> dict:
    """ゴミ箱のボイスを voices/ へ戻す。同名があれば「名前_復元」「名前_復元2」…で戻す。"""
    entry = str(entry or "")
    if any(c in entry for c in _BAD_CHARS) or entry in (".", ".."):
        raise TrashError("ゴミ箱の項目名が不正です")
    parsed = _parse_entry(entry)
    tdir = trash_dir_for(voices_dir)
    src = tdir / entry
    if not parsed or not src.is_dir() or _is_link(src) or src.resolve().parent != tdir.resolve():
        raise TrashError("ゴミ箱に見つかりません (すでに完全削除された可能性があります)")
    name = parsed[0]
    target = name
    n = 1
    while _find_dir(voices_dir, target) is not None:
        target = f"{name}_復元" if n == 1 else f"{name}_復元{n}"
        n += 1
        if n > 99:
            raise TrashError("戻す名前が決まりませんでした")
    try:
        os.replace(src, Path(voices_dir) / target)
    except OSError as e:
        raise TrashError(f"元に戻せませんでした ({e})")
    warning = ""
    if target != name:
        # ボイス一覧とカードの読み書きは、フォルダ名ではなく config の name を使う。
        # 合わせないと、一覧に元と同じ名前が2つ並び、どちらも元のカードを開いてしまう。
        for fname in ("config.json", "config.default.json"):
            cfg = Path(voices_dir) / target / fname
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                data["name"] = target
                cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"[voice_trash] 復元後の name 書き換えに失敗 ({fname}): {e}", flush=True)
                warning = (f"「{target}」に戻しましたが、{fname} の名前を書き換えられませんでした。"
                           f"ボイス一覧に元の名前が出る場合は、そのファイルの name を「{target}」に直してください")
    return {"restored": target, "renamed": target != name, "warning": warning}


def purge_expired(voices_dir, now=None, days=RETENTION_DAYS) -> int:
    """保管期限 (days 日) を過ぎたものを完全に削除する。名前を解釈できないものは触らない。
    戻り値は削除した件数。"""
    now = now or datetime.now()
    tdir = trash_dir_for(voices_dir)
    n = 0
    try:
        entries = list(tdir.iterdir())
    except OSError:
        return 0
    for p in entries:
        parsed = _parse_entry(p.name) if (p.is_dir() and not _is_link(p)) else None
        if not parsed:
            continue
        if (now - parsed[1]).total_seconds() >= days * 86400:
            try:
                shutil.rmtree(p)
                n += 1
            except OSError as e:
                print(f"[voice_trash] 完全削除に失敗 ({p.name}): {e}", flush=True)
    return n
