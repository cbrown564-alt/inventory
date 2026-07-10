# Local inference tuning — RTX 4070 Laptop 8 GB

Date: 10 July 2026

## Decision

Keep **`gemma4:26b`** as the quality-oriented local draft model. Run it through
an isolated CUDA-forced Ollama server with one loaded model and one parallel
request. The 26B checkpoint is unusually suitable for this machine because it
is a 25.2B-parameter MoE with only about 3.8B active parameters per token.

Do not spend more full-fixture time on dense models at or above 12B on this
8 GB GPU. The live 12B probe remained heavily split and did not finish one
six-photo batch in eight minutes. Qwen 27B NVFP4 does not provide its native
FP4 speed path on this Ada GPU and the existing Q4 model spills heavily.

The compact, non-thinking Qwen 3.5 9B path is stopped: disabling thinking
dropped the response grammar and returned Markdown rather than evidence-safe
JSON. Do not resume it without a separately designed and validated repair
stage. The next model-swap experiment is **Qwen3-VL 8B Instruct**, followed by
Ministral 3 8B. Both need a one-batch contract test before any larger run.

### Planning boundary

Local inference is a bounded cost-reduction track, not the current v1 gate.
Capture-strategy validation, trustworthy evidence construction and the
native-resolution accuracy bar in docs/00 take precedence. Do not spend a full
fixture on another model until the current step passes its stop condition.

The next two actions are:

1. Run the Gemma 4 26B compact schema on a two-room sample and reject it if
   recall regresses against the canonical local path.
2. Contract-test Qwen3-VL 8B Instruct on one batch; expand only if it remains
   acceptably resident and produces schema-valid evidence-linked output.

Keep `gemma4:26b` as the quality-oriented local draft until a controlled fixture
comparison supports replacement. These experiments must not delay docs/26's
Property A/B capture decision or docs/00 Milestones 1–4.

The repository-controlled repetition-loop guard is shipped: local decoding
uses `repeat_penalty=1.1`, rejects truncated/malformed JSON, and retries once at
temperature 0.3 before quarantining only the failed batch. The remaining
two-room Gemma check is model/data evidence, not missing runtime plumbing.

## Hardware and software observed

| Component | Observed value |
|---|---|
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU, 8,188 MiB, compute capability 8.9 |
| Driver | 581.95 |
| System RAM | 32,213 MB |
| Ollama | 0.30.10 |
| Ollama CUDA library | `cuda_v13` forced for the experiment server |
| Experiment endpoint | `http://127.0.0.1:11435` |
| Sample | InventoryFlex Entrance Hall, six 800×600 photos, one VLM batch |

The sample contains walls, sockets, skirting, flooring, two doors, downlights,
and a control panel. Detection was deliberately disabled so the run measured
the VLM contract rather than YOLO hint quality. Therefore item counts below are
a no-detector stress test, not substitutes for the committed full-fixture
quality scores in `docs/04-backend-comparison.md`.

## Live experiment results

All completed runs used Flash Attention, Q8 KV cache, one parallel request,
temperature 0, and repeat penalty 1.1. `total_s` includes cold loading and
non-token work. `tok/s` is Ollama's generation-only rate.

| Run | Context / output budget | VRAM-resident model | Result | Total | Decode |
|---|---:|---:|---|---:|---:|
| Gemma 4 E4B | 12K / 4K | 3.13 GB | valid JSON, 1 item | 55.4 s | 43.4 tok/s |
| Gemma 4 26B | 24K / 12K | 4.59 GB of 18.11 GB | valid JSON, 1 item | 148.5 s | 21.9 tok/s |
| Gemma 4 26B | 12K / 4K | 4.74 GB of 18.08 GB | valid JSON, 1 item | 156.9 s | 22.9 tok/s |
| Gemma 4 26B, batch 3×2 | 12K / 4K | about 4.74 GB | valid JSON, 2 duplicate wall items | 196.3 s | 19.5 tok/s |
| Qwen 3.5 9B | 12K / 4K | 4.93 GB of 6.38 GB | no JSON after retry | 358.2 s | — |
| Qwen 3.5 9B, thinking off | 12K / 4K | 4.93 GB of 6.38 GB | no JSON after retry | 145.4 s | — |
| Gemma 4 12B | 8K / 4K | 5.89 GB of 8.68 GB | stopped: no result after ~8 min | >480 s | — |
| MiniCPM-V 4.6 Q4_K_M | 8K / 4K | 0.64 GB language model | truncated JSON after retry | 163.9 s | — |

Interpretation:

- Gemma 4 E4B is the throughput winner but is not complete enough for an
  inventory schedule. It can be considered for captions, room summaries, or a
  cheap first-pass candidate generator only.
- Gemma 4 26B retains the best demonstrated production quality: 97.4% naming
  and 91.7% exact condition grading on the full fixture. Context 12K versus 24K
  did not change this small sample, but the full schema and retry behaviour
  still justify 24K until a compact prompt is evaluated.
- Reducing Gemma batching from six to three increased total time by 32% and
  produced a duplicate rather than better coverage. Keep batch size six.
- Qwen hidden thinking is a major cost. Disabling it cut failed-run time by
  roughly 59%, but Ollama did not return schema-valid JSON. A two-pass design
  or explicit JSON repair is required before that speed can be used.
- MiniCPM-V's small language model fits easily, but its 1.1 GB vision projector
  and weak schema adherence make it a specialised visual pre-pass candidate,
  not a drop-in report generator.

## Recommended Ollama server

Run a dedicated server rather than relying on the tray application's inherited
state. `OLLAMA_MAX_LOADED_MODELS=1` is important: during the experiments Ollama
kept Gemma 12B resident while MiniCPM loaded because both happened to fit,
reducing reproducibility.

```powershell
$env:OLLAMA_HOST = "127.0.0.1:11435"
$env:OLLAMA_LLM_LIBRARY = "cuda_v13"
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE = "q8_0"
$env:OLLAMA_CONTEXT_LENGTH = "24576"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_KEEP_ALIVE = "5m"
ollama serve
```

Production local-draft settings:

```powershell
$env:OLLAMA_HOST = "http://127.0.0.1:11435"
$env:HI_NUM_CTX = "24576"
$env:HI_NUM_PREDICT = "12288"
$env:HI_BATCH_SIZE = "6"
$env:HI_REPEAT_PENALTY = "1.1"
$env:HI_TEMPERATURE = "0"
$env:HI_TIMEOUT = "1200"
Remove-Item Env:HI_THINK -ErrorAction SilentlyContinue
```

Q8 KV cache is the first choice because Ollama documents it as roughly half
the F16 memory with usually negligible quality loss. Q4 KV should be treated
as an experiment, not a default: the additional memory saving is useful only
if it moves meaningful layers onto the GPU without degrading long structured
output. Always verify `/api/ps` after a model loads.

## Lower-level opportunities

### 1. Compact the application contract

This is the highest-value software change. Qwen spends thousands of generated
tokens reasoning before JSON, while the current item schema requests many
fields that can be filled deterministically later. Test a two-stage path:

1. VLM returns only `name`, `condition`, `defects`, and `photo_ids`.
2. Python supplies IDs, defaults, value bands, review fields, and full schema.

For Qwen, test `think: false` with the compact schema and a deterministic JSON
repair/validation pass. The live experiment proves the speed gain exists but
also proves the current one-pass schema is incompatible.

**Implemented 10 July (awaiting the two-room quality check):** set
`HI_COMPACT_SCHEMA=true` to have the local backend request only `name`,
`condition`, `defects`, and `photo_ids`. The canonical output contract remains
unchanged: Python deterministically supplies category (`other`), description,
cleanliness, quantity, value band, and confidence defaults. Compact mode is
opt-in; use it with `HI_THINK=false` for the Qwen experiment and record the
setting in the run name. It does not yet perform JSON repair — grammar-valid
compact output is required before a repair policy is introduced.

**Probe result, 10 July:** the six-photo Entrance Hall compact-contract probe
of `qwen3.5:9b` with `think: false`, 12K context, 4K output budget, Flash
Attention and Q8 KV cache **stopped normally but returned a Markdown table,
not JSON**. It emitted no hidden-thinking field, used 2,324 prompt tokens in
25.478 s and 543 generated tokens in 37.706 s (14.4 generated tok/s); the
80.364 s total includes a 17.011 s cold load. This confirms the known Ollama
behaviour: disabling Qwen thinking prevents the response `format` grammar from
being applied. Do not promote compact/no-think Qwen to a full run. A future
two-pass experiment needs an explicitly scoped text-to-JSON repair call and
its own quality gate; parsing the Markdown table heuristically would not be
evidence-safe.

**Gemma compact probe, 10 July:** `gemma4:26b` with the compact schema at 12K
context and a 4K output budget returned schema-valid JSON (`done_reason: stop`)
with 253 visible output tokens at 22.3 generated tok/s. It was not faster in
wall-clock time: 218.765 s total, including 44.848 s cold loading and 6,747
characters of hidden thinking. This validates the compact response contract but
is not evidence of a throughput improvement. The initial probe omitted the
application's canonical `P###` labels, so its numeric photo references cannot
be used to judge attribution; `benchmarks/probe_local.py` now mirrors the
application's ordered photo-ID prompt for the next run.

### 2. Keep detector hints; reduce redundant vision work

The no-detector sample missed obvious non-wall items. Production comparisons
should reuse cached YOLO detections so every model sees identical hints.
Choose six diverse frames rather than six adjacent near-duplicates. This can
improve both recall and speed without changing the VLM.

### 3. Test Flash Attention both ways for Qwen vision

Flash Attention normally reduces context memory, but llama.cpp reported a
Qwen 3.5 vision-projector regression in which unsupported F32 Flash Attention
operations moved image encoding to CPU. Before standardising Qwen settings,
run the same one-image request with Flash Attention on and off and compare
`prompt_eval_duration`, not just decode speed. Gemma should retain Flash
Attention unless its own A/B measurement says otherwise.

### 4. Consider llama.cpp for placement control

Ollama chooses layer placement automatically. A standalone recent CUDA
`llama-server` exposes `--n-gpu-layers`, CPU affinity/priority, mmap controls,
and MoE CPU placement. For Gemma 4 26B, a sweep that keeps attention/KV on GPU
while deliberately placing experts in system RAM may outperform automatic
placement. This is a second-phase experiment because multimodal projector and
JSON-schema compatibility must first match Ollama.

### 5. Control laptop conditions

Benchmark on AC power, a performance thermal profile, and a stable cool start.
Record GPU temperature, power, clocks, model digest, context, KV type, Flash
Attention, loaded-model count, and `/api/ps` `size_vram`. Laptop power or
thermal throttling can otherwise swamp a 5–10% inference optimisation.

## Model test ladder

| Priority | Model/path | Purpose | Stop condition |
|---:|---|---|---|
| 1 | Gemma 4 26B, compact schema | JSON contract passed on one batch; performance inconclusive | No recall loss on two-room sample |
| 2 | Qwen 3.5 9B, no-think + compact schema + repair | **Stopped:** grammar dropped and returned Markdown | Requires a separately validated second-pass repair design |
| 3 | Qwen3-VL 8B Instruct | Mature 8B vision baseline near the VRAM boundary | Spill remains severe or schema fails twice |
| 4 | Ministral 3 8B | Edge-oriented alternative | Worse recall/JSON than Qwen3-VL |
| 5 | MiniCPM-V 4.6 | Caption/visual candidate pre-pass only | Do not test as full schedule again without a smaller schema |
| 6 | Gemma 4 E4B | Fast summary/candidate path | Do not promote without full-fixture recall evidence |

Exclude dense Gemma 12B+, Qwen 27B, and Qwen 3.6 27B from routine testing on
this machine. Revisit them only after a materially smaller quantisation or a
GPU upgrade.

## Sources

- [Ollama context length and CPU-offload guidance](https://docs.ollama.com/context-length)
- [Ollama Flash Attention and KV-cache configuration](https://docs.ollama.com/faq)
- [Ollama Gemma 4 model architecture and benchmarks](https://registry.ollama.com/library/gemma4)
- [Ollama MiniCPM-V 4.6 model card](https://ollama.com/library/minicpm-v4.6)
- [Qwen3-VL 8B Instruct model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
- [llama.cpp CUDA and hybrid CPU/GPU support](https://github.com/ggml-org/llama.cpp)
- [Qwen 3.5 vision-projector Flash Attention regression](https://github.com/ggml-org/llama.cpp/issues/21272)
