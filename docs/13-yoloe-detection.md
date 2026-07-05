# YOLOE Detection

*Evaluated July 2026 on the InventoryFlex fixture (192 photos, 6 rooms). Detector
scores from `evals/eval_detect.py`; full-pipeline impact measured with
`gemini-3.5-flash` describe (docs/04).*

## Summary

**YOLOE is the open-source, local, £0 detection layer.** It runs before the
describe backend and does three jobs: per-photo object labels, cropped thumbnails
(`work/crops/`), and a **checklist hint** appended to the VLM prompt (“detector
saw: sofa, door, … — trust the images over the detector”).

**Install CLIP or detection silently skips.** Ultralytics YOLOE text-prompt mode
needs the Ultralytics CLIP fork (`git+https://github.com/ultralytics/CLIP.git`).
Without it the pipeline logs `YOLOE unavailable` and continues in whole-image
mode — no crops, no hints. This is what happened on the first
`report-gemini35flash` run in docs/04.

**Default mode: `text` (household vocabulary).** On the fixture, text mode finds
**58.7% of notable gold items** with manageable label noise. **`prompt_free`**
(LVIS/Objects365, ~1,200 classes) reaches **76.0% recall** but emits labels
like “hospital room”, “razor blade”, and “Eiffel tower”, misses inventory terms
(smoke alarm, towel rail), and fails the per-room coverage checklist **twice as
often**. Keep `text` for `build` and `check`; use `prompt_free` only for
offline-only drafts where breadth beats vocabulary fit.

**Detection hints help the VLM a little, not a lot.** Re-running
`gemini-3.5-flash` with YOLOE enabled (315 crops, text mode) vs the whole-image
baseline: **+1.3 pp notable recall**, **+5.6 pp condition-exact**, but **+1.5 pp
hallucination** and **−5.3 pp defect recall** — within run-to-run noise for a
single model. YOLOE is worth having for crops, capture-time `check`, and modest
describe uplift; it does not close the gap to claude-v4 on its own.

## Role in the pipeline

```
photos → YOLOE (local) → labels + crops + prompt hints → VLM describe → merge → report
```

| Concern | Owner |
|---|---|
| *What* is in the room | YOLOE (labels + crops) |
| *Condition*, defects, clerk wording | VLM describe backend |
| £0 report with no API | `--backend offline` (detector labels only) |

YOLOE cannot grade condition or write “scuff 10 cm left of handle” — that is why
detector and describer stay separate (docs/01).

## Installation

Requires the `[detect]` extra plus CLIP (not pulled automatically by ultralytics):

```bash
uv pip install -e ".[detect]"
uv pip install "git+https://github.com/ultralytics/CLIP.git"
```

First run downloads `yoloe-11s-seg.pt` (~28 MB) and MobileCLIP weights (~572 MB).
Weights land in the working directory or Ultralytics cache.

Verify:

```bash
python -c "import clip; from ultralytics import YOLOE; YOLOE('yoloe-11s-seg.pt')"
```

On Apple Silicon, pass `--device mps` to `build`, `check`, and `eval_detect`.

## Two detection modes

| Mode | Weights | Vocabulary | Use |
|---|---|---|---|
| **`text`** (default) | `yoloe-11s-seg.pt` | `HOUSEHOLD_VOCAB` (~48 inventory terms in `detect.py`) | `build`, `check`, benchmark default |
| **`prompt_free`** | `yoloe-11s-seg-pf.pt` | LVIS + Objects365 (~1,200 classes) | `--detect-mode prompt_free`, offline drafts |

CLI flags: `--detect-mode text|prompt_free`, `--detect-model`, `--det-conf` (default
0.25), `--device`, `--no-detect` (skip entirely).

## Detector eval (InventoryFlex)

Scored by `evals/eval_detect.py` — *detector only*, no VLM spend. Metrics:

| Metric | Meaning |
|---|---|
| **gold recall (notable)** | % of hand-labelled notable items matched by at least one detection label in the room |
| **unmatched label rate** | % of unique detection labels that match no gold item (noise) |
| **coverage gap rate** | % of per-room checklist terms (`coverage.py`) absent from detections |

Run (July 2026, `--device mps`; CPU baseline in committed
`detect-comparison.json` is within 0.3 pp):

```bash
python evals/eval_detect.py benchmarks/inventoryflex/capture \
  evals/fixtures/inventoryflex/labels.json \
  -o evals/fixtures/inventoryflex/detect-comparison-mps.json --device mps
```

### Mode comparison

| Mode | notable recall | unmatched labels ↓ | coverage gaps ↓ | dets/photo |
|---|---|---|---|---|
| **text** ★ default | **58.7%** | **65.8%** | **37.5%** | 1.86 |
| prompt_free | 76.0% | 71.4% | 66.7% | 5.67 |

★ Recommended for production `build` / `check`.

**Why text wins despite lower recall.** Prompt-free finds more gold items (+17 pp)
but the labels are unusable as inventory vocabulary: “home interior” in five
rooms, “evening sky”, “plywood”, “missile”. It also misses checklist-specific
terms the household vocab includes (`smoke alarm`, `towel rail`) while hitting
near-synonyms the fuzzy matcher rejects (`faucet` vs gold “mixer tap”). Coverage
gaps jump from 37.5% to 66.7% — the capture-time `check` command would flag
false alarms constantly.

**Text-mode blind spots (per room, notable recall):**

| Room | notable recall | notes |
|---|---|---|
| Bathroom | 66.7% | best fit — fixtures match vocab |
| Reception & Open Plan Kitchen | 66.7% | many labels, still misses small items |
| Bedroom | 61.5% | |
| Entrance Hall | 50.0% | |
| Walk In Wardrobe | 42.9% | |
| Balcony | **0.0%** | outdoor deck; vocab has no “railing” / “balustrade” |

Common **false unmatched** labels in text mode: `tap`, `television`, `mirror`,
`chair` — the detector sees them but gold uses clerk phrasing (“wall-mounted TV”,
“basin mixer tap”) below the 0.6 fuzzy threshold.

## Impact on describe (`gemini-3.5-flash`)

Compared whole-image (CLIP missing, no hints) vs YOLOE text + hints on the same
fixture and model:

```bash
# whole-image (no CLIP / --no-detect equivalent)
homeinventory build benchmarks/inventoryflex/capture \
  -o benchmarks/inventoryflex/report-gemini35flash \
  --backend openai --model gemini-3.5-flash

# with YOLOE text mode
homeinventory build benchmarks/inventoryflex/capture \
  -o benchmarks/inventoryflex/report-gemini35flash-detect \
  --backend openai --model gemini-3.5-flash --device mps
```

| Metric | whole-image | + YOLOE hints | Δ |
|---|---|---|---|
| notable recall | 82.7 | 84.0 | +1.3 |
| hallucination ↓ | **5.0** | 6.5 | +1.5 |
| condition-exact | 72.0 | **77.6** | +5.6 |
| naming | 93.8 | 92.8 | −1.0 |
| defect recall | **64.6** | 59.3 | −5.3 |

The YOLOE run produced **315 crops** under `work/crops/`. VLM backends do not
copy `crop_path` onto output items (only `--backend offline` does); hints are
prompt-only.

**Reading the delta.** Condition grading improves modestly when the model gets a
per-photo object checklist — consistent with the design intent in `describe.py`.
Recall moves slightly; hallucination and defect recall move slightly the wrong
way, within one-run variance. **Detection is not a substitute for a better
describe model** (claude-v4 at 93.2% condition-exact still leads).

## Recommendations

| Use case | Setting |
|---|---|
| Normal `build` | Default `text` mode; ensure CLIP installed |
| Pre-capture / post-capture gap check | `homeinventory check CAPTURE/` |
| Fully offline £0 draft | `--backend offline` or `--detect-mode prompt_free` |
| Ablation / no GPU | `--no-detect` (whole-image describe still works) |
| Tuning vocabulary | Edit `HOUSEHOLD_VOCAB` in `detect.py`; re-run `eval_detect` |

**Do not switch default to `prompt_free`** on this fixture: higher raw recall,
unacceptable label noise and coverage-check failure rate.

## Limits and follow-ups

- **Resolution:** fixture photos are 800×600 PDF extractions; small wall-mounted
  items (smoke alarms, door stops) are missed by *all* backends including YOLOE.
- **Vocabulary gaps:** add Balcony/outdoor terms; alias “faucet”↔“tap” in matching
  or vocab if recall on wet rooms matters.
- **Licence:** YOLOE/Ultralytics is AGPL — commercial implications noted in
  `docs/02-research.md`.
- **Committed benchmark runs** in docs/04 were mostly whole-image (CLIP not in CI);
  re-scoring describe backends *with* detection is an open follow-up for claude-v4
  and gpt54mini-v4.

## Reproduce

```bash
# 1. Detector mode comparison
python evals/eval_detect.py benchmarks/inventoryflex/capture \
  evals/fixtures/inventoryflex/labels.json --device mps

# 2. Describe with vs without detection
homeinventory build … -o report-gemini35flash-detect \
  --backend openai --model gemini-3.5-flash --device mps
homeinventory build … -o report-gemini35flash --no-detect \
  --backend openai --model gemini-3.5-flash

# 3. Score
python evals/run_eval.py report-…/inventory.json \
  evals/fixtures/inventoryflex/labels.json
```

Reference JSON: `evals/fixtures/inventoryflex/detect-comparison-mps.json`
(July 2026, MPS). Earlier CPU run: `detect-comparison.json`.
