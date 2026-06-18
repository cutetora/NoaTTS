# NoaTTS VRAM リーク調査計画

## 状況整理（現時点で確定していること）

- **クローン合成ループは無リーク**。in-process で `generate_voice_clone` を x20 回したとき `memory_allocated` Δ +0.8MB / `memory_reserved` Δ +0.0MB（フラット）。
- **モデル切替経路にリークがあったが修正済み**。unload→reload x8 で `allocated` Δ +554MB（1773–2339MB を振動）。原因は `IrodoriEngine.unload()` が `del self._runtime` → `torch.cuda.empty_cache()` を **`gc.collect()` を挟まずに**実行していたこと。修正として `gc.collect()` を `empty_cache()` の前に追加（`engine/irodori_engine.py:114-126`）。修正後は switch x8 で `allocated` Δ +5MB / `reserved` Δ +20MB（1781.8MB で安定）。
- **ライブラリ側は既に健全**。`irodori_tts` の `synthesize()` は `torch.inference_mode()` でラップ済み（`inference_runtime.py:958`）。`empty_cache()` は `unload()` 内のみ（`inference_runtime.py:1237-1246`）で per-utterance には呼ばない。
- **重要な但し書き**：実測したのは上記 **2 経路だけ**。クローン合成と同種モデル切替以外（VoiceDesign 第二ランタイム常駐、`/say_wav` 一時ボイス、ストリーミング producer/consumer、長時間ソークの断片化、UI 別プロセスの二重常駐など）は**まだ一度も計測していない**。以下はそれらを潰すための計画。

ユーザー報告は「動作を続けるとVRAMがどんどん大きくなる」。**最有力は「リーク」ではなく『キャプション使用時に第二ランタイム `_vd_runtime` が一度ロードされ、モデル切替まで解放されない（設計通りの常駐増 +1.2〜1.8GB）』が「上がって戻らない」と知覚されているケース**である可能性が高い。これを最初に切り分ける。

---

## コード読みで先に除外できる仮説（ソークを浪費しない）

| 除外対象 | 根拠 | 状態 |
|---|---|---|
| ライブラリ global `_RUNTIME_CACHE_VALUE` / `get_cached_runtime` | NoaTTS は `InferenceRuntime.from_key()` を直接呼ぶ（`engine/irodori_engine.py:65,98`）。`get_cached_runtime()` を一度も呼ばずモジュールキャッシュは常に None | **死コード** |
| LoRA アダプタ蓄積（`inference_runtime.py:489`） | `SamplingRequest.lora_adapter` が NoaTTS の全 `*.py` で未設定。`_lora_adapter_names` は `{}` のまま | **死コード** |
| torch.compile / inductor キャッシュ増加（Irodori 経路） | `RuntimeKey.compile_model` 既定 False（`inference_runtime.py:189`）、NoaTTS は未設定。Qwen3 のみ compile を使うが実運用エンジンではない | **休眠（Qwen3 時のみ）** |
| RoPE `_freqs_cis_cache`（`model.py:653-661` 他） | grow-only だがトークナイザ上限（~256, `inference_runtime.py:542-552`）で頭打ち。数MBで自己収束 | **境界あり・軽微** |

これらは**長時間ソークのベースラインに畳み込むだけ**にし、専用実験は組まない（設定が Qwen3 に切り替わった場合のみ E7 で確認）。

---

## 仮説ランキング表（症状を説明する確からしさ × 検証の容易さ で降順）

| 順位 | 疑わしい発生源 | トリガ | 深刻度 | これを決める単一実験 |
|---|---|---|---|---|
| 1 | **VoiceDesign 第二ランタイム `_vd_runtime` の常駐**。`_load_vd_runtime()`（`irodori_engine.py:79-108`）が初回キャプション使用で第二 `InferenceRuntime` 全体を遅延ロードし、`unload()`（=モデル切替）まで解放しない。design ボイスは `generate_for_script_row` で常に非空キャプションを組む（`irodori_engine.py:310-315`）ため**design ボイス使用＝常に VD 常駐** | `/say caption=...`、または design ボイスでの読み上げ | high | **E1**：caption あり1回→なし10回→あり10回→switch_model。`allocated` の段差が一度きりで、caption off でも戻らず、switch で初めて解放されるかを確認 |
| 2 | **UI が別プロセスで第二エンジンを常駐**。`app.py`(:7860) が `ec.engine` に独自 `IrodoriEngine`（+独自 `_vd_runtime`）を保持（`engine_control.py:137-150`）。手動 unload まで解放されない。daemon の torch view からは**見えない**（別プロセス）が nvidia-smi 全体には出る | daemon と UI を同時起動、UI で emotion/5-seed ループ | high（UI 起動時のみ） | **E6**：daemon のみ→UI 起動→UI で生成→UI unload→UI kill を **nvidia-smi 全体 と daemon `/memstats` 両方**で測る |
| 3 | **per-utterance codec 再エンコード断片化**。`_load_reference_latent`（`inference_runtime.py:735-740`）が `.pt` 不在時に毎発話 `codec.encode_waveform(...).cpu()`。caption は ref_wav フォールバックを強制（`irodori_engine.py:266-270`）。可変長で caching allocator が断片化（`reserved` が `allocated` フラットのまま増える） | caption 連発、または `.pt` 無しボイスでの連続合成 | 断片化=high / 真リーク=medium | **E4**：`.pt` 無し（or caption）で可変長テキスト200回。`allocated`（真リーク）vs `reserved`+`num_alloc_retries`（断片化）の乖離を見る |
| 4 | **speak/cancel churn でのスレッド/クロージャ滞留**。`dispatch_speak` は旧 producer を `join(timeout=2.0)` 後に放棄（`runtime.py:78-81`）。放棄スレッドのフレームが wav/gen_q/Path を保持（`worker.py:390-406`）。音声は CPU numpy なので主に host-RAM だが VRAM 断片化も確認 | 長文 /say → 約300ms後 /stop を高速反復 | medium（VRAM）/ medium（host） | **E5**：speak→cancel を50〜100周。`threading.active_count()`・`tracemalloc`・`tmp_say/` ファイル数・`allocated` を測る |
| 5 | **長時間ソークの allocator 断片化**。可変長 latent/encode で `reserved` だけ単調増、`allocated` フラット。1〜4 を除外した後に残る緩やかな増加の正体 | 数千発話の混合通常使用 | medium | **E8**：8h 混合ソーク。idle quiescent 点での `allocated` 傾き（真リーク）vs `reserved`/`retries` 傾き（断片化）を分離 |
| 6 | **`/say_wav` 回転ボイスの一時 latent churn**。`_load_vc_only`（`worker.py:313-328`）が毎回ボイスカード+`torch.load(map_location='cpu')`→`.to(device)`（`inference_runtime.py:714`）。distinct ボイス数に比例して残るか | `/say_wav voice=` を毎回違うボイスで連発 | medium | **E4 Variant B/C** に統合（同一テキスト×回転ボイス vs 単一ボイス対照） |
| 7 | **switch_model の VD-as-main 分岐と失敗復旧**。VoiceDesign repo を本体モデルに選ぶ分岐、bogus repo→DEFAULT 復旧で部分ロードが残らないか | `/model` で VD repo 選択、bogus repo 投入 | medium | **E1b**（switch 計測）に統合：成功/失敗どちらも単一モデルプラトーに戻るか |
| 8 | **Qwen3 `_models` 辞書 + compile キャッシュ**（`tts_engine.py:39`）。custom/design/clone を最大3つ同時保持、明示 unload まで残る。実運用 Irodori では無関係 | settings で qwen3 選択時のみ | low（gated） | **E7**：qwen3 選択可能時のみ。3モデル共存は設計どおり、per-generation フラット性のみがリーク判定 |

---

## 計測の大原則（全実験共通）

- **真リーク判定は `torch.cuda.memory_allocated()` のみ**。固定された **quiescent point**（経路完了後・推論非実行中・`gc.collect()`+`torch.cuda.synchronize()` 後）で N 回の同一反復にわたり差分を取る。
- `memory_reserved()` / `memory_stats()` / nvidia-smi は **分類用**であって判定ではない。`reserved` が増えて `allocated` フラット = 断片化（リークではない）。
- **nvidia-smi / `reserved` だけでリークと判断しない**（これは反証済みメモが犯した誤り）。
- **Windows WDDM では nvidia-smi の per-process が取れない**ことがある。daemon の torch view は自プロセスのスライスのみを見る＝**別プロセスの UI には構造的に盲目**。UI が起動中なら daemon view だけで「無リーク」と結論しない。

---

## 計測装置（追加すべき最小限のインストルメンテーション）

すべて**デバッグフラグ/env で gate** し、既定では本番に載せない（設計のみ、コミットしない）。

1. **MEMPROBE 再利用ハーネス**（新規 `tmp_say/memprobe.py`、全オフライン実験が import）
   - `snap()` → `dict(alloc, reserved, active_bytes.all.peak, reserved_bytes.all.peak, num_alloc_retries, segment.all.current)`。読む前に必ず `gc.collect()` + `torch.cuda.synchronize()`。
   - `run_path(fn, n, warmup=3)`：warmup → `reset_peak_memory_stats()` → `base=snap()` → n 回 `fn()`+`snap()` を **quiescent point** で記録 → per-iter テーブルと `(last.alloc-base.alloc)`, `(last.reserved-base.reserved)` を返す。
   - **自己検証**：既知フラットなクローン経路 n=10 で `allocated` Δ < 2MB を再現できなければハーネス側のバグ。他実験を信用する前に直す。

2. **`GET /memstats` エンドポイント**（`daemon/servers.py`、既存 `/vram` の隣）
   - daemon **自プロセス**の MEMPROBE タプル＋プロセス健全性カウンタ：`vd_loaded (worker._eng._vd_runtime is not None)`, `model_repo`, `threading.active_count()`, `len(gc.get_objects())`, `tmp_say/*.wav` 数。
   - `?gc=1` で opt-in の `gc.collect()`（既定 off、hot path を止めないため）。実 daemon を再起動せず実トラフィック下で観測できる。

3. **`/vram` の文書化注記**（挙動変更なし）：現 `/vram` の `noa` フィールドは `memory_reserved`（allocator キャッシュの高水位）であって `allocated` ではない。**単独でリーク証拠にしない**。リーク狩りは `/memstats` の `alloc` を見る。

4. **`torch.cuda.memory._record_memory_history(max_entries=100000)`**（E8 ソークの限定窓のみ）→ 終了時 `_dump_snapshot('snap.pickle')`。生き残ったブロックを割当 Python スタック（call site）に帰属。**オーバーヘッド大、本番常時は不可、診断窓のみ**。

5. **nvidia-smi per-PID**（E6 のみ）：`nvidia-smi --query-compute-apps=pid,used_memory --format=csv`。取れない WDDM では全体総量＋`python.exe` PID 数にフォールバック。daemon `/memstats` の `alloc` と毎ステップ対比。

6. **オフライン外部ドライバ**（新規 `tmp_say/` 配下、未コミット）：`requests`+`concurrent.futures` で `/say`,`/say_wav`,`/model`,`/voice`,`/cache` のループを発火し `/memstats` を CSV にポーリング。計測を daemon プロセス外に置き、観測自体が daemon メモリを乱さないようにする。

7. **テストフィクスチャ**：clone(`.pt`あり)/clone(ref_wavのみ)/design(voice_description あり) を混ぜた使い捨てボイスカード ~30 枚＋可変長 `.pt` latent を生成するスクリプト（E1/E4 Variant B 用）。

---

## 順序付き実験ランブック（安いものから・重いソークは最後）

### E0 — MEMPROBE ハーネス構築 + 自己検証（最初に作る／medium）
- **目的**：以降全実験の判定基盤を作り、既知フラット経路で再現させる。
- **手順**：上記インストルメンテーション 1 を実装 → クローン経路 n=10 を `run_path` で回す。
- **測る**：per-iter `alloc/reserved/retries/segments`。
- **リーク信号**：既知フラット経路で `allocated` がドリフトしたら**ハーネスのバグ**。
- **合格基準**：クローン経路 `allocated` Δ < 2MB、warmup 後は単調非増加。

### E0b — `/memstats` エンドポイント実装（medium）
- **目的**：実 daemon を再起動せずライブ観測。
- **合格基準**：8h 通常使用ソークで、idle 時 `alloc` が post-warmup ベースライン +20MB 以内に戻る／`threads` が idle ベースラインに戻る／`tmp_say_files` が有界。

### E1 — VoiceDesign 第二ランタイム常駐の切り分け（最優先・quick）
- **目的**：仮説1。VD が「上がって戻らない」常駐増（設計通り）かリークかを決める。
- **手順**（各境界で snap、daemon のみ・UI off）：
  - P0：`caption=''` 通常 /say x3 → ベースライン。
  - P1：`caption='喜'` x1（`use_vd=True` 強制ロード）。
  - P2：`caption=''` x10（通常ランタイムに戻る）。
  - P3：`caption='怒'` x10（VD 再利用）。`id(engine._vd_runtime)` が不変なシングルトンか確認。
  - P4：`switch_model` で unload 強制。`engine._vd_runtime is None` を確認。
- **測る**：各 P 境界の `allocated`/`reserved`、`_vd_runtime` の `id()`。
- **リーク信号**：P2 や P3 で per-call `allocated` 増（caption 経路の真リーク）、または P4 で VD 段差が解放されない（stale 参照）。
- **合格基準**：P1=単一段差、P2/P3 各 `allocated` Δ < 5MB、P4 で P1 段差の **≥95%** 解放かつ `_vd_runtime is None`。**P1 の恒久プラトーは設計どおり＝リークではない**。ユーザー知覚の「増加」の最有力としてフラグし、idle 時に `_vd_runtime` を解放するか常駐コストを許容するかを判断する。

### E1b — switch_model 多数サイクル + VD-as-main + 失敗復旧（medium）
- **目的**：仮説7。`gc.collect()` 修正が 20 サイクル超でも保つか、VD repo を本体に選ぶ分岐と失敗復旧で部分ロードが残らないか。
- **手順**：
  - (A) 500M-v3 ⇄ 600M-VoiceDesign を交互に 20 回（=10 往復）、各切替の間に 1 回 /say を挟む。round-robin で 3 repo も試し「同一キー短絡」を破る。
  - (B) bogus repo_id を投入し DEFAULT へ復旧、部分ロードが残らないか。
- **測る**：各切替の quiescent `allocated`/`reserved`、`segment.all.current`、`num_alloc_retries`。
- **リーク信号**：`allocated` が 20 切替で +30MB 超（旧バグ +554MB/8 の再来）、`reserved` 単調増（断片化）、失敗 switch で `allocated` 高止まり、is_vd 分岐で同一 repo を二重ロード。
- **合格基準**：`allocated` Δ < 30MB で固定プラトー振動、`reserved` 安定、`retries` がサイクル毎に増えない。失敗 switch も単一モデルプラトーに戻る。

### E6 — UI 別プロセス二重常駐（medium、daemon-isolated 実験の前に「UI が起動していないこと」を必ず確認）
- **目的**：仮説2。「VRAM 総量が増える」が単に daemon+UI 共存である可能性を測る。**in-process probe が完全に盲目な唯一のケース**。
- **手順**（各ステップで nvidia-smi 全体 と daemon `/memstats` の両方）：
  - S0：何も起動せず → nvidia-smi ベースライン。
  - S1：daemon 起動 → nvidia-smi ~+X、daemon `alloc` ~X。
  - S2：UI(:7860) 起動＋1回生成 → nvidia-smi ~2X、daemon `alloc` **不変**（= 第二プロセス証明）。
  - S3：UI で engine qwen3⇄irodori 5回＋各生成。
  - S4：UI で emotion-4-set / 5-seed-explore を 5〜10回（UI 側 `gr.State` 蓄積：`design_tab.py:11-12`, `tuning_logic.py:188-236`）。
  - S5：UI unload ボタン → nvidia-smi が ~X に戻るか。S6：UI kill → daemon-only に戻るか。
- **測る**：nvidia-smi 全体、per-PID（取れれば）、daemon の `/memstats alloc`、UI プロセス RSS。
- **リーク信号**：UI 停止後に nvidia-smi 総量が戻らない／S3 で engine 切替が置換でなく蓄積／S4 ループが単調増。
- **合格基準**：daemon の `alloc` は UI 活動に関わらず全工程フラット（=daemon は無罪）。S5 で UI VRAM が S1 近くに戻る。S3 は置換、S4 は出力消費後にベースライン復帰。**両プロセス共存で 2X なら設定の問題でありリークではない**——報告でそう明記。

### E4 — per-utterance codec 再エンコード断片化 + /say_wav 回転ボイス（medium）
- **目的**：仮説3+6。caption/`.pt`無し経路の `encode_waveform` churn が真リークか断片化か、回転ボイスが distinct ボイス数に比例して残るか。
- **手順**：
  - Variant A（断片化）：`.pt` 無し（or caption 付き）clone ボイスで、可変長テキスト（10/60/200字を巡回）を同一 ref_wav で 200 回。開始時に `reset_peak_memory_stats()` 1回。**固定長テキストの対照ループも実行**。
  - Variant B（回転ボイス）：30 distinct ボイス（`.pt`あり/なし混在、一部 large `.pt`）を巡回し固定短文で 300 回。**単一ボイス×300 回の対照**と比較。
  - Variant C（並行）：`concurrent.futures` 8 worker で `/say_wav` 50〜1000 件。バースト drain 後・スレッド idle 後に snap。
- **測る**：20 反復毎に `allocated`/`reserved`、`memory_stats['num_alloc_retries']`、`reserved_bytes.all.current`、`segment.all.current`。
- **リーク信号**：`allocated` が毎反復フラットに戻るが `reserved` 単調増＋`retries` 増＝断片化。`allocated` も単調増＝encode 経路の真リーク。Variant B で distinct ボイス数に比例して `alloc` 増＝per-voice latent 滞留。Variant C でバースト drain 後に `alloc` がベースライン非復帰＝per-thread バッファ滞留。
- **合格基準**：可変長/固定長どちらも `reserved` が最初の ~40 反復でプラトー、以降 ±10MB フラット、`retries`==0。Variant B は回転と単一が同一フラットプラトーへ収束、`alloc` がコール間でベースライン +5MB 以内。Variant C は drain 後に `alloc` 復帰（`reserved` はバーストのピークで高止まりしてよいが、**2 回目の同一バーストでさらに上がらない**こと）。

### E5 — speak/cancel churn：孤児スレッド・滞留・tmp_say（heavy）
- **目的**：仮説4。最もありそうな「実使用での遅いリーク」を、単発 clone/switch probe が一度も叩いていない経路で潰す。
- **手順**：`/memstats` をポーリングしつつ、長い複数文 /say → 約300ms後 /stop を 50〜100 周（時々超長文で feed_wav 書込中に cancel）。ループ前・中・終了5秒後（idle）に読む。
- **測る**：`threading.active_count()`（孤児 producer）、`len(gc.get_objects())`（クロージャ/Path/ndarray 滞留）、`tracemalloc` top（numpy wav は **host RAM**）、`tmp_say/*.wav` 数、`open_files()`、`allocated`/`reserved`。
- **リーク信号**：ループ後にスレッド数が idle ベースラインに戻らない／`py_objs` がサイクル毎に増える／`tmp_say` ファイルが無制限増／滞留オブジェクトが CUDA テンソルを保持していれば `alloc` 増。
- **合格基準**：ループ＋5秒 idle 後、スレッド数==idle ベースライン、`py_objs` がベースライン±小定数、`tmp_say` 有界、`alloc` 復帰。**host-RAM のみの滞留（ndarray）は VRAM とは別カテゴリの低優先所見として別個にラベル**。

### E3 — RoPE `_freqs_cis_cache` の grow-only 確認（medium、E8 前に一度）
- **目的**：境界ありの grow-only キャッシュが「seq_len が伸び続けるセッション」で増加に見えることを確認し、**繰り返し同一長でフラット**＝バグでないことを示す。
- **手順**（同一ランタイム、間でリロードしない）：
  - Path A：固定 ~20 字を 20 回（warmup 後フラットのはず）。
  - Path B：16,32,64,128,200,250 字と厳密増、VD ランタイムは caption 長も厳密増、最後に最長を 5 回反復。各段で `reset_peak_memory_stats()`→`max_memory_allocated` を読む。
  - Path C（解放確認）：`switch_model` で unload 後再測。
- **リーク信号**：各より大きい長さで増（設計どおり）かつ**既に見た長さの反復でも増え続ける**（=真バグ）。
- **合格基準**：Path A フラット、Path B は新最大長でのみ段差・既知長反復で完全フラット、総増分は 256 トークン上限で数 MB（GB ではない）。**反復同一長で増え続けたらエスカレート**。

### E7 — Qwen3 `_models` 辞書 + compile キャッシュ（gated・heavy／qwen3 選択可能時のみ）
- **目的**：仮説8。settings が qwen3 になり得る環境のみ。
- **手順**：custom→design→clone を順に生成（3モデルロード）→各 20 回再利用→`cfg.tts_model_size` 変更し `get_engine()` 再呼出（unload なし）→`unload()`。
- **リーク信号**：20回再利用ループで per-generation 増（dynamic shape の compile 再構築）、model_size 変更で旧モデルを解放せず 4 つ目を積む、`reserved` が compile 断片化で増。
- **合格基準**：型内 20 回ループはフラット。3モデル共存は設計どおり（容量上限であってリークではない）。`unload()` でベースライン復帰。**判定はあくまで per-generation フラット性**。

### E8 — 8h 混合ワークロード・ソーク（最後・heavy）
- **目的**：仮説5＋未発見。実 daemon を 8h、ランダム混合で駆動し、真リークと断片化ドリフトを分離。ユーザーの「続けると増える」を実条件で再現。
- **手順**：~70% 通常 /say（可変長・時々超長文）、~15% caption /say（VD 行使）、~10% `/say_wav voice=` ランダム、~5% 高速 /stop、~30 分毎に /model 切替。`/memstats` を 60s 毎に CSV。限定窓で `_record_memory_history` を有効化し snapshot を pickle ダンプ。**無操作 idle 対照（daemon 起動・リクエスト 0・同 duration）でベースラインドリフトを差し引く**。
- **測る**：idle quiescent 点での `alloc` の長期傾き（真リーク）、`reserved` 傾き（断片化/キャッシュ）、`num_alloc_retries`/`num_ooms`、`threads`/`py_objs`/`tmp_say_files`。snapshot で増加ブロックを call site に帰属。
- **リーク信号**：idle で `alloc` 傾き > 0（真リーク）。`alloc` フラットだが `reserved`+`retries` 増（断片化）。`py_objs`/`threads` 増（CUDA とは独立の Python 側リーク）。
- **合格基準**：8h 全体で idle-quiescent `alloc` の傾き ~0（フラットバンド）、`num_ooms`==0。`reserved`/`retries` だけドリフトなら断片化と分類。`alloc` ドリフトなら snapshot がリーク call site を名指し。

---

## 決定木 / 停止基準

```
[E1] caption off に戻しても allocated が下がらない？
 ├─ はい、かつ switch_model で解放される → 設計どおりの VD 常駐（リークではない）。
 │     対応：idle 時 _vd_runtime 解放を実装するか、+1.2〜1.8GB 常駐を許容と文書化。
 └─ caption 反復(P3)で per-call 増、または switch でも解放されない → 真リーク → 修正クラス: Python参照/stale参照

[E6] UI を kill すると nvidia-smi 総量が S1 に戻る？ daemon /memstats alloc は全工程フラット？
 ├─ daemon alloc フラット & UI kill で総量復帰 → 「増加」は daemon+UI 共存（設定）。daemon は無罪。
 └─ UI unload 後も総量が戻らない → UI 側リーク → 修正クラス: 二重常駐/UI unload 不完全

[E4/E8] allocated と reserved のどちらが増える？
 ├─ allocated 単調増（quiescent 点で） → 真リーク → snapshot で call site 特定 → 修正クラス: Python参照 or ライブラリキャッシュ
 ├─ reserved だけ増・allocated フラット・retries↑ → 断片化（リークではない）
 │     → 修正クラス: allocator-cache。PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True で再測し平坦化を確認。OOM 切迫しないなら過剰対応しない
 └─ 両方フラット → その経路は無罪

[E5] ループ後にスレッド数/py_objs が idle ベースラインに戻る？
 ├─ はい → producer/cancel は無罪
 └─ スレッド or 滞留 host 配列が線形増 → 修正クラス: Python参照/孤児スレッド（host-RAM、VRAM とは別所見）

[E3] 既知長の反復で allocated が増え続ける？
 ├─ いいえ（新最大長でのみ段差） → RoPE は境界あり・無罪
 └─ はい → 真リーク → エスカレート
```

**「完全に直った」と言える条件**：E1 が VD を設計どおりと確定 ∧ E1b で switch が +30MB 未満プラトー ∧ E4 で `allocated` フラット（`reserved` ドリフトは断片化として別分類）∧ E5 でスレッド/py_objs がベースライン復帰 ∧ E8 の 8h で idle-quiescent `allocated` 傾き ~0・`num_ooms`==0。

**「まだリークしている、エスカレート」**：上記いずれかで `allocated` が quiescent 点で単調増 → `memory._record_memory_history` の snapshot で割当スタックを特定し、その call site に帰属する修正（Python 参照解放／ライブラリキャッシュの明示クリア）を行う。

---

## カテゴリ混同を避ける注意（報告時に分離すること）

- **disk**（`cache/`, `tmp_say/`）は VRAM ではない。`cache/` は distinct キー数で有界だが無制限化しうる——VRAM 症状と混同しない。
- **host-RAM**（producer クロージャの numpy wav、`gr.State` DataFrame、tray の handle）は RSS/tracemalloc で見える別カテゴリ。E5 を torch.cuda.* だけで見ると host リークを誤って無罪化する。
- **fragmentation**（`reserved` 増・`allocated` フラット）はリークではなく、32GB 5090 では `num_ooms`/`num_alloc_retries` が立つまで無害。`expandable_segments` で検証し、benign なら過剰修正しない。
