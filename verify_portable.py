"""ポータブル版が「自己完結」しているか検証する。

build_portable.bat の最後に、バンドル同梱の python で実行される。
同梱 python・torch が**バンドル内**から読み込まれているか(=システムの Python を
使っていないか)と、CUDA が使えるかを判定する。クリーンな別マシンが無くても、
これが両方 OK なら配布先でも動く見込みが高い。
"""
import os
import sys


def _under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) \
            == os.path.abspath(root)
    except Exception:
        return False


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))  # = バンドルのルート
    print("=== ポータブル自己完結チェック ===")
    print("バンドル :", root)
    print("python   :", sys.executable)
    print("prefix   :", sys.prefix)

    py_ok = _under(sys.executable, root) and _under(sys.prefix, root)

    torch_ok = False
    cuda = False
    try:
        import torch
        print("torch    :", torch.__file__)
        torch_ok = _under(torch.__file__, root)
        cuda = bool(torch.cuda.is_available())
        print("CUDA     :", cuda)
    except Exception as e:
        print("torch import 失敗:", e)

    print()
    if py_ok and torch_ok:
        note = "（CUDA も利用可）" if cuda else "（※CUDA 不可: ドライバ未対応 / Sandbox 等）"
        print("[OK] Python と torch はバンドル内で完結 → 配布先でも動作する見込み " + note)
        return 0
    print("[NG] システム側の Python / torch を参照している可能性があります（移植性に問題）。")
    print(f"     py_ok={py_ok}  torch_ok={torch_ok}")
    print("     ※このスクリプトは必ずバンドル同梱の python で実行してください:")
    print("       dist\\NoaTTS-portable\\python\\python.exe verify_portable.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
