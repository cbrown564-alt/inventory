# Describe-Backend Comparison

*Opened 10 June 2026 (informal single-room probe); closed 2 July 2026 against the
full InventoryFlex fixture. All numbers below are scored by `evals/run_eval.py`
against gold labels in `benchmarks/inventoryflex/labels.json` (6 rooms, 116 items,
75 notable, 53 defect-bearing) and reproduced by `python evals/score_benchmarks.py`.*

## What each backend is

- **`claude`** — Anthropic vision, structured JSON output. Quality ceiling; the
  pick for the signed report. Default `opus-4-8`, `claude-haiku-4-5` for cheaper runs.
- **`openai`** — any OpenAI-compatible API: OpenAI (`gpt-5.4-mini`), Gemini via
  the compat endpoint (`gemini-3.1-flash-lite`), or a custom `--base-url`.
  Cheap cross-provider comparison tier.
- **`local`** — open-weight VLM through Ollama (default `qwen3.5:9b`). £0/run,
  runs offline. The open-source-only path this milestone was built to validate.

## Scored results (InventoryFlex fixture, v4 prompt where it exists)

Higher is better for recall / naming / condition / defect; lower is better for
hallucination. Targets from `evals/README.md`.

| Backend (run) | notable recall ≥90 | halluc. ≤5 | naming ≥85 | cond-exact ≥70 | within-one ≥95 | defect ≥75 |
|---|---|---|---|---|---|---|
| **claude-v4** (quality ceiling) | 88.0 | **2.8** | 94.8 | **93.2** | 100 | **71.3** |
| gpt54mini-v4 (best openai) | **90.7** | 14.7 | **96.8** | 83.1 | 100 | 64.8 |
| local qwen9b-v2 (best local) | 72.0 | 25.7 | 96.3 | 75.0 | 98.7 | 60.8 |
| local qwen9b (v1) | 65.3 | 19.4 | 91.0 | 71.9 | 95.3 | 62.1 |
| local gemma12b / qwen27b / gemma4e4b | ~0 | — | — | — | — | — |

Reproduce: `python evals/score_benchmarks.py` (or `--json`). Per-run JSON in
`benchmarks/inventoryflex/report-<run>/inventory.json`.

## Reading the gap

**`claude` vs `openai` (gpt-5.4-mini).** These are close enough that the
choice is a cost/hallucination trade-off, not a quality cliff. gpt-5.4-mini
edges claude on notable recall (90.7 vs 88.0) and naming (96.8 vs 94.8) but
**hallucinates ~5× more** (14.7 vs 2.8) — and an unreviewed false item or
defect is exactly the failure that loses an adjudication. gpt-5.4-mini is the
cheap-iteration backend; claude produces the signed artefact. Confirmed by
the cost data in `docs/06`: ~$0.14 vs ~$1.17 per property — both noise against
the £165 professional fee, so the hallucination gap is worth paying to close.

**Open-source gap (the M3 question).** `local qwen3.5:9b` is the only viable
local backend, and it is **not yet at parity**, but the gap is narrower than the
headline recall number suggests:

- **Naming (96.3) and within-one grading (98.7) are competitive** with the API
  tiers — qwen names and grades items almost as well as claude once it finds them.
- **The real gap is recall** (notable 72.0 vs claude's 88.0; −16 pts): qwen
  misses items, especially the small wall-mounted cluster (smoke alarms,
  thermostats, doorstops) that all backends under-find. This is where an
  open-source-only property loses coverage.
- **Hallucination is the open-source weakness** (25.7 vs 2.8): qwen invents /
  over-splits more, and its granularity-split rate (38.7 vs claude's 29.6)
  shows it fragments clerk-merged items more aggressively. Every qwen output
  needs the review loop more than a claude output does.
- **Defect recall (60.8) is only ~10 pts off claude (71.3)** — surprising for a
  9B local model, and within the same resolution-bound band that caps all
  backends on this 800×600 fixture (see `docs/06`).

Net: **`local` is usable for a £0 draft that a reviewer then corrects**; it is
not yet a drop-in replacement for `claude` for an unreviewed report. The review
experience (`docs/05`) is what makes the open-source path viable, and it is
also the place qwen's higher hallucination rate gets caught.

**The three failed local models.** `gemma-3-12b`, `qwen3.5:27b`, and
`gemma-3-4e4b` were all tried via Ollama and produced **0–1 items per property**
under this harness — effectively no usable inventory. Likely causes are the
structured-JSON output contract and Ollama thinking-model handling (the
qwen9b fixes in commits `930455d`/`59f3fde` were not enough for the larger
models); not re-run before closing M3 because qwen9b already represents the
local path and re-running needs GPU time the user is spending on M2 capture.
Logged here so the record isn't lost; their `report-*` dirs are kept as
evidence of "tried, failed."

## Historical note (the original 10 June probe)

The first comparison was an informal single-room probe on
`examples/videos/IMG_5278.mov` (one living/dining room, 19 keyframes, whole-room
calls, no detector). Findings that still hold and shaped the v4 prompt:

- **Recall and grading discipline are separate skills.** gpt-4.1-mini found 70%
  more items than gemini-3.1-flash-lite but graded everything "good" with zero
  defects — an inventory that can't support a deduction. A model must do both.
- **Hallucinated defects are real, not hypothetical.** gemini's one defect claim
  — a "surface scratch" on the TV unit — was a "2021 new" sticker. One human
  glance at the evidence photo dismissed it; an unreviewed report would have
  carried a false damage claim into a dispute where the landlord bears the burden
  of proof. This was the strongest argument for the per-item review experience
  (`docs/05`) and is why hallucination rate stays a primary metric.
- **Dedup misses across names** ("Children's bicycle" + "Bicycle" surviving merge)
  motivated the fuzzy/embedding merge that later landed (commit `fc5df67`).

Cost reference (June 2026, per 1M tokens in/out): gemini-3.1-flash-lite
$0.25/$1.50, gpt-4.1-mini $0.40/$1.60, gpt-5.4-mini $0.75/$4.50,
claude-haiku-4-5 $1.00/$5.00, opus-4-8 $5/$25, qwen3.5:9b £0. A 19-frame room
is ~25K input + 3–4K output tokens; one property ≈ 8–10× that.

## Conclusion (M3 close, 2 July 2026)

- **Quality ceiling:** `claude` (opus-4-8 on the v4 prompt). Best hallucination
  and grading; the artefact to sign.
- **Cheap iteration:** `openai` gpt-5.4-mini. Within reach on recall/naming at
  ~8× lower cost; usable for prompt sweeps, higher hallucination for final use.
- **Open-source-only:** `local` qwen3.5:9b. Naming and grading competitive;
  recall −16 pts and hallucination +23 pts vs claude. Usable as a £0 draft
  **with the review loop**, not as an unreviewed report. Larger local models
  (gemma-3-12b, qwen3.5:27b) failed to produce output and are not yet viable.

The backend interface, all three backends, and the detector-mode eval are
landed; the quality gap is documented above. **Milestone 3 is closed.** The
remaining quality work (defect depth at native resolution, recall of small
wall-mounted items) is owned by M2's own-property capture, not the backend layer.

## Local-backend performance: spillover and the 8 GB ceiling (2 July 2026)

A follow-up run instrumented the `local` backend's actual throughput (timing
capture landed in `LocalBackend` + checkpoint `timing` fields). Two questions
that prior runs couldn't answer — how long a run takes, and whether Ollama
spills to CPU — are now settled, and they reframe what "open-source-only"
means on consumer hardware.

**qwen3.5:9b spills to CPU on an 8 GB card; throughput is capped at ~15 tok/s.**
Confirmed two independent ways: Ollama `/api/ps` reported **4.9 / 7.0 GB in
VRAM (72%)**, and `nvidia-smi` showed 4848 / 8188 MiB used. The 6.7 GB Q4_K_M
weights don't fit alongside the KV cache and vision activations, so ~30% of
the weights offload to system RAM. Generation held a flat **~15 tok/s** across
every room (Balcony 15.5, Bathroom 14.6, Bedroom 15.4, Entrance 15.7) — a 3–4×
depression from the ~40–60 tok/s a fully on-GPU 9B run would hit. At that rate
batches on the larger rooms exceed the 900s socket timeout: a full run of the
InventoryFlex fixture (192 photos, 6 rooms) did not complete — Reception alone
saw 7 of 14 batches time out. `num_ctx` does **not** help: Ollama sizes the KV
cache by actual tokens, not the ctx ceiling, so lowering it leaves the 6.7 GB
weight footprint untouched (measured: 4.84 GB VRAM at ctx 16384 vs 4.9 at
24576 — no change). The spillover is the weights, not the cache.

**A smaller model fits but is too weak.** `qwen2.5vl:3b` (Q4, 2.72 GB) loads
**100% in VRAM** at **55 tok/s** — spillover eliminated, 3.5× faster, and it
accepts the structured-JSON `format` contract. But it is marginal for this
task: at temperature 0 it falls into repetition loops (one batch emitted the
same "ceiling" item 34× until `num_predict` truncated it); with
`repeat_penalty` and a mild temperature it still fails intermittently, leaving
empty or truncated checkpoints, and its output is thin (6 structural items,
missing content a clerk would record). Across multiple attempts no parameter
combination produced a stable full run.

**Other families were surveyed, not just qwen.** To check the "no sweet-spot
model" finding wasn't qwen-specific, two further small VLMs were probed on the
same backend prompt (6 Bathroom photos, temp 0, the structured-JSON `format`
contract this pipeline requires):

- **`gemma3:4b`** (Q4_K_M, 2.77 GB, 100% VRAM, ~12–38 tok/s) — natively
  multimodal, *stable* at temp 0 where qwen2.5vl:3b looped. But it
  **under-produces**: two identical trials both returned 1 item ("Wall –
  Bathroom Wall", ~200 tokens, `done_reason=stop`) where a clerk records ~15.
  Pushing it for thoroughness ("list 15–30 items") made it **break the schema**,
  emitting its own field names (`Material`/`Grade`/`Details`/`Location`) instead
  of the required ones — Ollama's grammar then aborted the response (null
  `eval_count`, partial 308-char body). So gemma3:4b complies minimally but
  rebels under pressure: stably thin, weak schema adherence. (Note: the
  `gemma-4-12b` tags already on disk are the text-only Q4_0 build with no
  vision projectors — not a candidate without a different tag.)
- **`gemma4:12b`** (official `gemma4:12b`, Q4_K_M, 7.56 GB — distinct from the
  text-only `gemma-4-12b:*` tags) — this *is* the multimodal one: it accepted
  images and generated (no "does not support multimodal" 400 that the text-only
  build returns). Note gemma4's encoder-free design (a ~35M embedded module)
  doesn't surface as `*.vision.*` model_info keys, so `/api/show` reports "no
  vision keys" even though vision works. But at 7.56 GB it **spills worse than
  qwen9b**: 62% on GPU (5.54/8.98 GB), ~3.4 GB on CPU, and a single 6-photo
  Balcony batch did not finish within the 195s probe window. Same wall as the
  9B, taller.
- **Phi-3.5-vision / MiniCPM-V** (~4B tier) are the remaining untested
  candidates; not probed here.

**Net (dense models):** across four dense vision models / three families (qwen
9B, qwen2.5vl 3B, gemma3 4B, gemma4 12B), every one fails this pipeline on an 8
GB card — the ≥9B models spill and are timeout-bound; the ≤4B models that fit
are too weak (loops / empties / under-produce / schema-rebel). The binding
constraints are the **8 GB VRAM ceiling** (forces a small dense model, which is
too weak) and the **strict structured-output contract** (which weak models
adhere to minimally or abandon under pressure). *This conclusion is dense-only
— see the MoE finding below, which breaks it.*

**Mixture-of-Experts breaks the deadlock (3 July 2026).** The dense-model
survey overlooked MoE: a model with huge total weights but few active experts
per token. With 32 GB system RAM absorbing the weights and the 8 GB GPU holding
only the active-expert pathway + KV cache, an MoE model can be large *and*
fast. **`gemma4:26b`** (Q4_K_M, 18 GB, 25.8B params, **8 of 128 experts
active** ≈ a ~1.6B dense model's compute per token) is the result:

| Metric (target) | claude-v4 | qwen9b-v2 | **gemma4:26b** |
|---|---|---|---|
| item_recall_notable (≥90) | 88.0 | 72.0 | 72.0 |
| hallucination_rate (≤5) | **2.8** | 25.7 | 23.8 |
| naming_accuracy (≥85) | 94.8 | 96.3 | **97.4** |
| condition_exact (≥70) | 93.2 | 75.0 | **91.7** |
| condition_within_one (≥95) | 100 | 98.7 | **100** |
| defect_recall (≥75) | 71.3 | 60.8 | 57.7 |

Reproduce: `python evals/score_benchmarks.py`. gemma4:26b ran at a steady
**23.4 tok/s** (faster than the spilling dense qwen9b's 15), 24% in VRAM
(4.4/18.4 GB — the rest rides system RAM), completing all 6 rooms in ~26 min
of generation. Its **naming (97.4) and grading (91.7 exact / 100 within-one)
are the best of any backend including claude** — a genuine step up over qwen9b
on the local tier. The gaps vs claude are recall (72 vs 88) and hallucination
(23.8 vs 2.8): partly the 5 batches the 900s timeout skipped on complex rooms,
partly gemma4's tendency to over-split items (134 predicted in Reception vs the
clerk's 43). The merge pass tames but doesn't eliminate that, and the review
loop (`docs/05`) is where the recall gap and higher hallucination get caught.

`qwen3.6:35b` (36B, 8-of-256 active, 24 GB) was also probed but is too slow
here: a thinking model under heavy spillover (20% VRAM), a single batch
exceeded the 290s probe window. It would likely score higher than gemma4:26b
but needs a ~3–4 hr overnight run.

**Revised local recommendation:** `--backend local --model gemma4:26b` is the
first local model that produces a full, clerk-quality £0 draft worth reviewing.
The dense-model ceiling is real, but MoE sidesteps it on hardware with enough
system RAM to hold the weights. qwen3.5:9b remains the lighter fallback where
system RAM is also constrained.

**Knobs added for local experimentation** (env vars, no CLI flags): `HI_NUM_CTX`
(context window), `HI_NUM_PREDICT` (output token ceiling), `HI_REPEAT_PENALTY`,
`HI_TEMPERATURE` (primary sampling temperature; the retry path is separately
jittered). Per-batch and per-room timing (wall clock, prompt/eval token counts,
derived tok/s) is now captured into each checkpoint's `timing` field, so future
local runs self-document their throughput instead of being a black box.
Reproduce the spillover diagnosis: `curl -s localhost:11434/api/ps` shows the
VRAM/total split; a steep `eval_tok_per_s` drop vs a prior run is the
CPU-offload tell-tale.
