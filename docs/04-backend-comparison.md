# Describe-Backend Comparison

Which vision model should describe a property inventory? This document records
scored runs on the **InventoryFlex fixture** — 6 rooms, 192 photos (800×600 from
a professional sample report), 116 gold items (75 notable, 53 defect-bearing).
All numbers come from `evals/run_eval.py` against
`evals/fixtures/inventoryflex/labels.json`; reproduce with
`python evals/score_benchmarks.py`. YOLOE detection setup, mode comparison, and
impact on describe scores: **`docs/13-yoloe-detection.md`**.

## Summary

**For a signed report, use `claude` (opus-4-8, v4 prompt).** It has the lowest
hallucination rate (2.8%) and the most reliable condition grading (93.2% exact).
An unreviewed false item or defect is the failure mode that loses an
adjudication — hallucination is the metric that matters most for the final artefact.

**For cheap prompt iteration, use `openai` gpt-5.4-mini (v4 prompt).** It edges
claude on notable recall (90.7 vs 88.0) and naming (96.8 vs 94.8) at ~8× lower
cost (~$0.14 vs ~$1.17 per property; see `docs/06`), but hallucinates ~5× more
(14.7%). Good for sweeps; not for an unreviewed report.

**`gemini-3.5-flash` is the segmentation default** (docs/11) and was evaluated on
describe in July 2026. It clears the hallucination ceiling (5.0%) and the
condition-exact floor (72.0%), but sits ~21 pts below claude on condition-exact
and ~5 pts below on notable recall — so it **does not pass the describe decision
gate** (docs/12) and claude stays the quality default for signed output.

**For a £0 local draft, use `local` gemma4:26b** (MoE via Ollama). It is the
first open-weight model that completes a full fixture run and produces
clerk-quality naming (97.4) and grading (91.7 exact / 100 within-one) — the best
of any backend on those two metrics. Recall (72.0 notable) and hallucination
(23.8) still need the review loop (`docs/05`). Dense local models on an 8 GB GPU
either spill to CPU and time out (qwen3.5:9b) or are too weak to fill the schema;
MoE sidesteps that on hardware with enough system RAM.

## Backends

| Backend | Role | Default model |
|---|---|---|
| **`claude`** | Quality ceiling; signed report | `claude-opus-4-8` (`claude-haiku-4-5` for budget) |
| **`openai`** | Any OpenAI-compatible API — OpenAI, Gemini compat endpoint, custom `--base-url` | `gpt-4.1-mini`; benchmark uses `gpt-5.4-mini` |
| **`local`** | Open-weight VLM through Ollama; £0/run, offline | `qwen3.5:9b` (lighter fallback); **`gemma4:26b`** recommended |

## Results

Higher is better for recall / naming / condition / defect; lower is better for
hallucination. Targets from `evals/README.md`.

| Backend (run) | notable recall ≥90 | halluc. ≤5 | naming ≥85 | cond-exact ≥70 | within-one ≥95 | defect ≥75 |
|---|---|---|---|---|---|---|
| **claude-v4** ★ signed report | 88.0 | **2.8** | 94.8 | **93.2** | 100 | **71.3** |
| gpt54mini-v4 (best OpenAI tier) | **90.7** | 14.7 | **96.8** | 83.1 | 100 | 64.8 |
| gemini-3.5-flash (describe eval) | 82.7 | 5.0 | 93.8 | 72.0 | 100 | 64.6 |
| **gemma4:26b** (best local) | 72.0 | 23.8 | **97.4** | **91.7** | 100 | 57.7 |
| qwen9b-v2 (light local fallback) | 72.0 | 25.7 | 96.3 | 75.0 | 98.7 | 60.8 |

★ Quality default for describe. Per-run JSON:
`benchmarks/inventoryflex/report-<run>/inventory.json`.

### Underperforming or non-competitive runs

These were tried and logged; they are **not** recommended backends.

| Run | What happened |
|---|---|
| **local gemma-3-12b / qwen3.5:27b / gemma-3-4e4b** | 0–1 items per property under this harness — structured-JSON contract and Ollama thinking-model handling; evidence in `report-local-*` dirs |
| **local qwen2.5vl:3b / gemma3:4b** | Fit in 8 GB VRAM but too weak: repetition loops, 1-item rooms, or schema rebellion under pressure |
| **local gemma4:12b** (dense) | Multimodal but spills worse than qwen9b; single-room probe did not finish in time |
| **local qwen3.6:35b** (MoE) | Probed; thinking model too slow under spillover (~3–4 hr estimate for full fixture) |
| **gpt54mini v1** (pre-v4 prompt) | 41% condition-exact — found items but graded undifferentiated; motivated the v4 prompt |
| **claude v1** (pre-v4 prompt) | 86.6 notable recall, 9.2% hallucination — superseded by claude-v4 |

Early prompt versions (`gpt54mini-v2`…`v3`) are kept in `report-gpt54mini-*` for
history; v4 is the OpenAI tier to compare against.

## Recommendations

| Use case | Backend | Notes |
|---|---|---|
| Signed report | `claude` opus-4-8, v4 prompt | Lowest hallucination; best condition grading |
| Prompt / cost iteration | `openai` gpt-5.4-mini, v4 prompt | Higher recall; accept higher hallucination |
| Video segmentation | `gemini-3.5-flash` | Already default (`docs/11`); describe eval did not displace claude |
| £0 local draft + review | `local` gemma4:26b | Best local naming/grading; needs `docs/05` review loop |
| Constrained RAM | `local` qwen3.5:9b | Lighter weights; worse recall/hallucination; may not finish large rooms on 8 GB GPU |

## Reading the gaps

**API tier: recall vs trust.** gpt-5.4-mini and claude are close on finding and
naming items. The split is hallucination and grading discipline — gpt finds more
but invents more; claude grades conditions more reliably. Cost is noise against
the £165 professional fee; the hallucination gap is not.

**gemini-3.5-flash describe.** Competitive on naming and within-one grading, at
the hallucination ceiling but not near claude's 2.8%. The blocker is condition-exact
(72.0 vs 93.2): enough to pass the ≥70 floor, not enough for the docs/12 gate
("within a few points of claude-v4"). Reproduce:

```bash
homeinventory build benchmarks/inventoryflex/capture \
  -o benchmarks/inventoryflex/report-gemini35flash \
  --backend openai --model gemini-3.5-flash
python evals/run_eval.py benchmarks/inventoryflex/report-gemini35flash/inventory.json \
  evals/fixtures/inventoryflex/labels.json
```

**Local tier: find vs grade.** All competitive local runs share ~72% notable recall
— they miss the same small wall-mounted cluster (smoke alarms, thermostats,
doorstops) that API backends also under-find. Where gemma4:26b wins is *given an
item, name and grade it like a clerk*. Hallucination (~24%) and over-splitting
(134 predicted items in Reception vs the clerk's 43) mean every local output
needs review; qwen9b-v2 is similar quality at lower RAM cost but no grading
advantage over gemma4.

**Defect recall across all backends.** No run hits the ≥75% defect target on this
800×600 fixture — resolution-bound band documented in `docs/06`. Treat defect
recall as a shared ceiling until native-resolution capture lands (M2).

## Local hardware notes

Consumer **8 GB VRAM** is the binding constraint for dense open-weight VLMs.
qwen3.5:9b (6.7 GB Q4) spills ~30% of weights to system RAM → ~15 tok/s and
900s batch timeouts on large rooms. Smaller dense models (≤4B) fit fully on GPU
but cannot sustain the structured-JSON inventory contract.

**MoE breaks the deadlock** when system RAM can hold the full weights: gemma4:26b
(18 GB Q4, 8-of-128 experts active) runs at ~23 tok/s with 24% in VRAM, completing
all 6 rooms in ~26 min. Requires ~32 GB system RAM for the weight footprint.

Local tuning env vars (no CLI flags): `HI_NUM_CTX`, `HI_NUM_PREDICT`,
`HI_REPEAT_PENALTY`, `HI_TEMPERATURE`. Per-batch timing is captured in checkpoint
`timing` fields. Spillover diagnosis: `curl -s localhost:11434/api/ps` (VRAM/total
split); a steep `eval_tok_per_s` drop vs a prior run indicates CPU offload.

## Historical probe (June 2026)

Before the full fixture, an informal single-room probe on
`examples/videos/IMG_5278.mov` (19 keyframes, no detector) established three
design constraints that still hold:

1. **Recall and grading are separate skills** — a model that finds everything but
   grades it all "good" with zero defects is useless for deductions.
2. **Hallucinated defects are real** — gemini-3.1-flash-lite's "scratch" on a TV
   unit was a "2021 new" sticker; motivated per-item review (`docs/05`) and
   hallucination as a primary metric.
3. **Dedup across names** ("Children's bicycle" + "Bicycle") motivated the fuzzy
   merge pass (commit `fc5df67`).

Cost reference (June 2026, per 1M tokens in/out): gemini-3.1-flash-lite
$0.25/$1.50, gpt-5.4-mini $0.75/$4.50, claude-haiku-4-5 $1.00/$5.00,
opus-4-8 $5/$25, local £0.

## Milestone status

M3 (backend layer) is **closed**. The interface, all three backends, and the
detector-mode eval are landed. Remaining quality work — defect depth at native
resolution, recall of small wall-mounted items — is owned by M2 capture, not the
backend choice.
