"""nvidia-smi から GPU が対応する CUDA バージョンを検出し、推奨する PyTorch の
CUDA インデックスタグ (cu128 / cu124 / cu121 / cu118 / none) を 1行で出力する。

setup.bat が `TORCH_INDEX` を自動選択するために使う。GPU/ドライバが無ければ `none`。
依存は標準ライブラリのみ (torch 導入前でも動く)。

検出ロジック: nvidia-smi が表示する「CUDA Version: X.Y」(=ドライバが対応する最大 CUDA)
を読み、それ以下で最も新しい PyTorch ホイールのタグを選ぶ。
"""
import re
import subprocess


def detect() -> str:
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True,
                             timeout=10).stdout
    except Exception:
        return "none"
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    if not m:
        return "none"
    v = int(m.group(1)) * 100 + int(m.group(2))  # 12.8 -> 1208
    if v >= 1208:
        return "cu128"
    if v >= 1204:
        return "cu124"
    if v >= 1201:
        return "cu121"
    if v >= 1108:
        return "cu118"
    return "none"


if __name__ == "__main__":
    print(detect())
