# Describe-Backend Comparison — First Real Footage

*10 June 2026. Status: informal single-room comparison; a labelled fixture and
`evals/run_eval.py` are needed before any of this is treated as conclusive.*

## Setup

- **Footage**: `examples/videos/IMG_5278.mov` — hand-held iPhone walkthrough of
  one living/dining room. HEVC, portrait 1080×1920, 30 fps, 14.3 s.
- **Keyframes**: 19 frames via the best-frame-per-window extractor (see commit
  `11f8c38` — the old absolute sharpness gate left a 4.5 s coverage hole on
  this exact video; windowed selection closed it, max gap 1.2 s).
- **Pipeline**: `build --backend openai --no-detect` (no YOLOE hints), one
  whole-room call per backend, identical system prompt and JSON schema.
- **Test hardware context**: RTX 4070 Laptop (8 GB VRAM), 31.5 GB RAM —
  relevant to the still-pending local-model run, not the API ones.

## Results (same 19 frames, same prompt)

| Backend / model | Items | Structural items | Grading | Defects found | Approx cost |
|---|---|---|---|---|---|
| `openai` gpt-4.1-mini | 17 | walls, flooring | flat — all "good" | 0 | ~1.5¢ |
| `openai` gemini-3.1-flash-lite | 10 | walls, flooring, ceiling | differentiated (exc/good/fair) | 1, localized — **verified false**: the "surface scratch" on the TV unit is a "2021 new" sticker | ~0.4¢ |
| `openai` gpt-5.4-mini | 28 | ceiling, walls, skirting, flooring | differentiated | 1, localized (wall-decal sections detached) | ~4¢ |
| `local` qwen3.5:9b | — | *pending: GPU shared with another workload* | | | £0 |
| `claude` (any) | — | *not yet run on this footage* | | | — |

## Observations

**gpt-5.4-mini is the standout of the cheap tier.** Best recall (robot vacuum,
TV remote, dining chairs ×4, skirting boards), proper structural coverage as
separately graded items, grade differentiation, a real localized defect, and
clerk-register language ("white emulsioned finish", "fair decorative order").
At ~4¢/room (≈30–50p per property) it is the provisional best-value default.

**Recall and grading discipline are separate skills.** gpt-4.1-mini found 70%
more items than gemini-3.1-flash-lite but graded everything "good" with zero
defects — an inventory that can't support a deduction claim. Gemini found
fewer items but behaved like a clerk. A model must do both; so far only
gpt-5.4-mini does.

**Failure modes to score in evals, not just recall:**

- *Hedge items*: gpt-5.4-mini emitted "Cylindrical floor object" and "Portable
  lamp or light source reflection" despite the omit-rather-than-guess rule.
  These should count against it as hallucination-adjacent.
- *Hallucinated defects are real, not hypothetical*: gemini's sole defect
  claim — a "surface scratch to top right corner" of the TV unit — turned out
  to be a "2021 new" sticker. One human glance at the evidence photo dismissed
  it; an unreviewed report would have carried a false damage claim into a
  dispute where the landlord bears the burden of proof. This is the strongest
  argument yet for a review experience that puts each claim next to its
  evidence crop (see 05-review-experience.md).
- *Dedup misses across names*: "Children's bicycle" + "Bicycle" survived the
  string-key merge as two items. Fuzzy/embedding matching is the fix and is
  needed for M3 `compare` anyway.

## Cost reference (June 2026, per 1M tokens in/out)

| Model | Price | Note |
|---|---|---|
| gemini-3.1-flash-lite | $0.25 / $1.50 | cheapest credible VLM |
| gpt-4.1-mini | $0.40 / $1.60 | flat grading as observed |
| gpt-5.4-mini | $0.75 / $4.50 | provisional pick |
| claude-haiku-4-5 | $1.00 / $5.00 | untested on this footage |
| qwen3.5:9b via Ollama | £0 | pending local run |

A 19-frame room ≈ 25K input + 3–4K output tokens; one property ≈ 8–10× that.

## Next steps

1. Label this room as the first eval fixture (`evals/README.md` format).
   The TV-unit "scratch" is verified false (sticker) — record it as a
   negative label so the eval penalises any backend that reports it.
2. Run `evals/run_eval.py` across all backends → recall / hallucination /
   naming / condition-agreement table; pick the default backend on numbers.
3. Run `local` qwen3.5:9b when the GPU is free (and optionally
  `gemma-4-12b:q4` as the local rival).
4. Add a claude run (haiku + opus) as the quality ceiling reference.
5. Consider a fuzzy-name merge pass to close the bicycle-style dedup gap.
