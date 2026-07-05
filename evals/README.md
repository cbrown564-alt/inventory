# Evals

Quality *is* the product — an inaccurate inventory loses an adjudication — so any
pipeline change should be scored before it ships.

## Fixtures

A fixture case is a capture folder plus hand-written gold labels:

```
evals/fixtures/<case>/
  capture/<Room>/...photos...
  labels.json
```

`labels.json`:

```json
{
  "rooms": {
    "Living Room": {
      "items": [
        {
          "name": "three-seat sofa",
          "aliases": ["sofa", "settee", "couch"],
          "condition": "good",
          "defects": ["scuff on left arm"],
          "notable": true
        }
      ]
    }
  }
}
```

- `aliases`: acceptable alternative names (fuzzy-matched).
- `components`: optional finer-grained names the model may emit when it splits one
  clerk entry into several items (e.g. `"bath"` with components `["mixer controls",
  "shower handset"]`). Unmatched predictions that match a gold item's name, alias,
  or component are counted as **granularity splits**, not hallucinations.
- `notable: false` marks minor items whose omission shouldn't count against recall
  (e.g. a coaster); they still count if found.
- `condition` / `defects` are optional — omit for items where the gold labeller
  couldn't judge from the photos either.

## Running

```sh
homeinventory build evals/fixtures/<case>/capture -o /tmp/eval-out --backend claude
python evals/run_eval.py /tmp/eval-out/inventory.json evals/fixtures/<case>/labels.json
```

Run the same case against `--backend offline` (and later `local`) to quantify the
open-source-only quality gap instead of guessing at it.

### CI regression gate

Committed reference runs are scored on every push/PR:

```sh
python evals/ci_gate.py
```

Floors live in `evals/fixtures/thresholds.json`. The gate also smoke-tests
`homeinventory build --backend offline --no-detect` on a synthetic capture so
the eval harness stays wired to the pipeline.

To score every InventoryFlex benchmark output locally:

```sh
python evals/score_benchmarks.py
```

### Detector mode comparison (YOLOE text vs prompt-free)

Compare how well each YOLOE mode finds gold inventory items before spending
API credits on describe:

```sh
python evals/eval_detect.py CAPTURE_DIR evals/fixtures/<case>/labels.json
python evals/eval_detect.py CAPTURE_DIR labels.json -o detect-eval.json --device cuda
```

Metrics: **gold recall** (notable / all items matched by at least one detection
label in the room), **unmatched label rate** (detector noise), and **coverage
gap rate** (per-room checklist misses). Default runs both `text`
(household vocabulary) and `prompt_free` (LVIS/Objects365) and prints a
recommendation. Use `--detect-mode prompt_free` on `homeinventory build` to
try prompt-free in the full pipeline.

Reference run on the InventoryFlex fixture is at
`evals/fixtures/inventoryflex/detect-comparison.json`. Findings and install
notes: `docs/13-yoloe-detection.md`.

## Metrics & targets

| Metric | Target (v1) |
|---|---|
| `item_recall_notable` | ≥ 90 |
| `hallucination_rate` | ≤ 5 |
| `granularity_split_rate` | informational — finer splits of labelled items |
| `naming_accuracy` | ≥ 85 |
| `condition_exact` | ≥ 70 |
| `condition_within_one` | ≥ 95 |
| `defect_recall` | ≥ 75 |

Within-one matters because human clerks routinely disagree by a single grade on
the 5-point ordinal scale; exact-match alone would over-penalise.

## Building your first fixture

Label 2–3 rooms of a real property by hand (10 minutes/room): walk the room,
list every item a clerk would record, grade it, note defects. That single case
is enough to start prompt-tuning against; grow the set as failures appear.

## Eval scripts

All scripts live under `evals/`. Paths below are from the repo root; prefer
`uv run python evals/<script>.py …`.

### Pipeline scoring (describe / inventory quality)

| Script | Purpose | Typical command |
|---|---|---|
| `run_eval.py` | Score one `inventory.json` against a fixture `labels.json` | `uv run python evals/run_eval.py report/inventory.json evals/fixtures/inventoryflex/labels.json` |
| `score_benchmarks.py` | Score every committed `benchmarks/inventoryflex/report-*/` run | `uv run python evals/score_benchmarks.py` |
| `ci_gate.py` | CI regression gate vs `fixtures/thresholds.json` + offline build smoke | `uv run python evals/ci_gate.py` |

Metrics and v1 targets: table above. See `docs/01-scope-and-architecture.md` §5.

### Detection

| Script | ML-E | Purpose | Typical command |
|---|---|---|---|
| `eval_detect.py` | — | YOLOE text vs prompt-free recall/noise on labelled capture | `uv run python evals/eval_detect.py benchmarks/inventoryflex/capture evals/fixtures/inventoryflex/labels.json` |
| `eval_detect_gdino.py` | E10 | Grounding DINO vs YOLOE text (Apache-2.0 eval path) | `uv run python evals/eval_detect_gdino.py benchmarks/inventoryflex/capture evals/fixtures/inventoryflex/labels.json -o evals/fixtures/inventoryflex/detect-comparison-gdino.json` |
| `gdino_detect.py` | E10 | Eval-only Grounding DINO backend (imported by `eval_detect_gdino.py`) | — |

Reference fixtures: `evals/fixtures/inventoryflex/detect-comparison.json`,
`detect-comparison-gdino.json`. Findings: `docs/13-yoloe-detection.md`,
`docs/20-ml-dl-experiment-log.md`.

Extract InventoryFlex photos first: `uv run python benchmarks/extract_inventoryflex.py`.

### Hero cover and IQA (own-property / IMG_5512)

Requires a walkthrough build output dir (`report/` or similar) with
`inventory.json` and frame paths. Video not committed — see
`docs/20-ml-dl-experiment-log.md` blockers.

| Script | ML-E | Purpose | Typical command |
|---|---|---|---|
| `eval_hero_cover.py` | — | Per-room contact sheets; gold top-1/top-3, Spearman (docs/18) | `uv run python evals/eval_hero_cover.py report --gold evals/fixtures/own-property/hero-gold.json` |
| `eval_iqa.py` | — | MUSIQ / CLIP-IQA oracle vs classical (eval only, NC licence) | `uv run python evals/eval_iqa.py report -o evals/fixtures/own-property/iqa-comparison-mps.json` |
| `eval_relevance_siglip.py` | E4 | SigLIP/OpenCLIP relevance margin vs hero-gold | `uv run python evals/eval_relevance_siglip.py report --gold evals/fixtures/own-property/hero-gold.json` |
| `eval_mslap_cover.py` | E5 | Multi-scale Laplacian ratio contact sheet | `uv run python evals/eval_mslap_cover.py report --gold evals/fixtures/own-property/hero-gold.json` |
| `eval_shot_scale.py` | E19 | CLIP long-shot vs close-up margin vs hero-gold | `uv run python evals/eval_shot_scale.py report --gold evals/fixtures/own-property/hero-gold.json` |
| `train_iqa_linear.py` | E6 | Ridge regression classical features → MUSIQ; writes MIT weights | `uv run python evals/train_iqa_linear.py --report report -o evals/fixtures/own-property/iqa-linear-weights.json` |
| `export_onnx.py` | E6/E17 | Optional ONNX export stub for linear IQA weights | `uv run python evals/export_onnx.py evals/fixtures/own-property/iqa-linear-weights.json` |

`eval_hero_cover.py --scorer` values: `cover` (product E5), `hard-gates`,
`mslap`, `relevance`, `clip`, `linear-musiq`.

Gold fixture: `evals/fixtures/own-property/hero-gold.json`. Experiment log:
`docs/20-ml-dl-experiment-log.md`.

### Segmentation and pre-process

| Script | ML-E | Purpose | Typical command |
|---|---|---|---|
| `eval_segment_embed.py` | E1 | DINOv2/CLIP embedding changepoint vs `segment-gold.json` | `uv run python evals/eval_segment_embed.py examples/videos/IMG_5512.MOV` |
| `eval_describe_pool.py` | E3 | Two-tier pool token-savings estimate (no describe gating) | `uv run python evals/eval_describe_pool.py report` |
| `label_segments.py` | E1 data | Scrub video, export boundary JSON / segments.json | `uv run python evals/label_segments.py strip VIDEO -o /tmp/seg-label` |

### Labelling helpers (Phase 0 data)

| Script | ML-E | Purpose | Typical command |
|---|---|---|---|
| `label_boxes.py` | E11 | Bbox schema, gallery, validate InventoryFlex boxes | `uv run python evals/label_boxes.py gallery benchmarks/inventoryflex/capture evals/fixtures/inventoryflex/labels.json` |

Split protocol: `evals/splits/inventoryflex.json`. External datasets:
`evals/external/README.md`.

### Shared ML utilities

| Module | Purpose |
|---|---|
| `ml_scorers.py` | Optional torch encoders (OpenCLIP, DINOv2, SigLIP) for E1/E4 harnesses |

Install eval-only torch stack when needed:

```sh
uv pip install torch torchvision open-clip-torch timm transformers accelerate
```

pyiqa (MUSIQ oracle) is **not** a project dependency — install manually for
`eval_iqa.py` only; CC BY-NC-SA, never ship in product (docs/19 G5).

