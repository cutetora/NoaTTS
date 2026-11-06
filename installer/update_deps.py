"""更新インストールで requirements.txt が変わったときに、依存ライブラリを入れる。

installer.iss の [Code] から、同梱の python\python.exe で呼ばれる: python -I update_deps.py <インストール先>

- torch / torchaudio / torchvision は、今入っている版に固定する (constraints)。requirements.txt や git 依存の
  先が別の版の torch を要求しても、PyPI の CPU 版に置き換わらず、pip が失敗して止まる (CUDA 版は守られる)。
- 成功したときだけ、python\.req_sha256 に requirements.txt のハッシュを書く。失敗したら書かないので、
  インストーラーを再実行すると再試行される。
終了コード: pip の終了コード (0 = 成功)
"""
import hashlib
import importlib.metadata as md
import os
import subprocess
import sys
import tempfile

TORCH_FAMILY = ("torch", "torchaudio", "torchvision")


def main() -> int:
    app = sys.argv[1]
    req = os.path.join(app, "requirements.txt")
    stamp = os.path.join(app, "python", ".req_sha256")

    pins = []
    for name in TORCH_FAMILY:
        try:
            pins.append(f"{name}=={md.version(name)}")
        except md.PackageNotFoundError:
            pass

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(pins) + "\n")
        constraints = f.name
    try:
        print(f"[update_deps] constraints: {pins}", flush=True)
        rc = subprocess.run([sys.executable, "-m", "pip", "install", "-r", req, "-c", constraints], cwd=app).returncode
    finally:
        try:
            os.remove(constraints)
        except OSError:
            pass

    if rc == 0:
        with open(req, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        with open(stamp, "w", encoding="ascii") as f:
            f.write(digest)
    return rc


if __name__ == "__main__":
    sys.exit(main())
