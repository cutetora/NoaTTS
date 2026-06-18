# VRAMリーク調査メモ（解決済み）

症状: daemon を動かし続けると VRAM 使用量が増えていく。

## 結論（実測で確定）

リーク源は **生成ループではなく、モデル切替 (`switch_model` → `IrodoriEngine.unload`)** だった。

`unload()` は `del self._runtime` の直後に `torch.cuda.empty_cache()` を呼んでいたが、
間に `gc.collect()` が無いため、Python GC が旧ランタイムを回収する前に empty_cache が
走り、まだ参照の生きた CUDA メモリを解放できていなかった。結果、モデルを切り替える
たびに旧モデル分が積み増され、VRAM が増えていた。

`engine/irodori_engine.py` の `unload()` に `gc.collect()` を1行追加して解決。

## 実測値（def1 clone、5090・32GB）

| 経路 | 操作 | allocated Δ | reserved Δ | 備考 |
|---|---|---|---|---|
| 生成ループ | clone 20回 | +0.8MB | +0.0MB | リーク無し（元々問題なし） |
| モデル切替 | unload→reload 8回（修正前） | **+554MB** | +564MB | 1773〜2339MBで乱高下しながら漸増 |
| モデル切替 | 同上（gc.collect 追加後） | **+5MB** | +20MB | 1781.8MBで完全に安定 |

## 当初メモの誤り（記録として残す）

- 「`_synthesize` に `inference_mode`/`no_grad` が無くautograd累積」→ **誤り**。
  irodori_tts ライブラリの `synthesize` が内部で `torch.inference_mode()` で囲っている
  （`inference_runtime.py` L958）。engine 側で囲う必要はない。
- 「生成ごとに empty_cache が無く累積」→ **誤り**。生成ループは実測でリークしない
  （allocated 横ばい）。ライブラリの synthesize 経路は累積しない設計。

教訓: 仮説をコードの見た目だけで立てず、`torch.cuda.memory_allocated()` の
読み上げ前後推移を実測して切り分けること。reserved（アロケータキャッシュ）と
allocated（真の保持量）は別物で、切り分けの鍵は allocated の単調増加の有無。
