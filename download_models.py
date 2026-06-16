"""TTSモデルを事前ダウンロードする (setup.bat から呼ばれる)。

GPU ロードはせず、HuggingFace から重みファイルをローカルキャッシュへ落とすだけ。
これを setup 時に実行しておくと、アプリ初回起動時の「モデルDL待ち」が無くなる。

既定エンジン (settings.json の tts_engine_type) のモデルを対象にする。
  - irodori: Aratako/Irodori-TTS-500M-v3 (読み上げ本体)
  - qwen3  : Qwen/Qwen3-TTS-12Hz-<size>-Base / -CustomVoice

ボイスデザイン(600M)や別エンジンのモデルは「使う時に自動DL」されるため、
ここでは落とさない (容量と時間の節約)。
"""
import sys


def _dl_irodori():
    from engine.irodori_engine import IrodoriEngine
    repo = IrodoriEngine.DEFAULT_CHECKPOINT
    print(f"[download] Irodori 読み上げモデル: {repo}", flush=True)

    # 最も確実な方法: runtime を実際に CPU でロードしてみる。
    # これで本体 (model.safetensors) / codec (Semantic-DACVAE) / tokenizer など
    # 起動に必要な依存ファイルがすべてキャッシュへ落ちる。推論はしない。
    try:
        from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey
        from huggingface_hub import hf_hub_download
        print("[download] runtime を CPU でロードして依存ファイルを取得します...", flush=True)
        checkpoint = hf_hub_download(repo_id=repo, filename="model.safetensors")
        InferenceRuntime.from_key(
            RuntimeKey(
                checkpoint=checkpoint,
                model_device="cpu",
                codec_device="cpu",
                model_precision="fp32",
                codec_precision="fp32",
            )
        )
        print("[download] Irodori 依存ファイル一式の取得完了", flush=True)
        return
    except Exception as e:
        print(f"[download] CPUロードでの取得に失敗: {e}", flush=True)
        print("[download] フォールバック: 本体と codec を個別に取得します...", flush=True)

    # フォールバック: 本体 + codec を個別にDL (tokenizer 等は初回起動時に補完)
    from huggingface_hub import hf_hub_download
    hf_hub_download(repo_id=repo, filename="model.safetensors")
    try:
        hf_hub_download(repo_id="Aratako/Semantic-DACVAE-Japanese-32dim",
                        filename="weights.pth")
    except Exception as e:
        print(f"[download] codec の個別取得に失敗 (初回起動時に再取得): {e}", flush=True)
    print("[download] Irodori モデル(本体)の取得完了", flush=True)


def _dl_qwen3():
    from engine.tts_engine import TTSEngine
    from huggingface_hub import snapshot_download
    eng = TTSEngine()  # GPUロードはしない (from_pretrained を呼ばない)
    size = eng.model_size
    # 通常使う custom / clone の2モデルを取得
    repos = [
        eng.MODEL_MAP["custom"].get(size),
        eng.MODEL_MAP["clone"].get(size),
    ]
    for repo in repos:
        if not repo:
            continue
        print(f"[download] Qwen3 モデル: {repo}", flush=True)
        snapshot_download(repo_id=repo)
    print("[download] Qwen3 モデルの取得完了", flush=True)


def main():
    from config import AppConfig
    cfg = AppConfig.load()
    engine_type = getattr(cfg, "tts_engine_type", "irodori")
    print(f"=== モデル事前ダウンロード (engine={engine_type}) ===", flush=True)
    try:
        if engine_type == "qwen3":
            _dl_qwen3()
        else:
            _dl_irodori()
    except Exception as e:
        print(f"[download] 失敗: {e}", flush=True)
        print("  ※ ネットワーク接続を確認してください。アプリ初回起動時に再取得を試みます。", flush=True)
        return 1
    print("=== ダウンロード完了 ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
