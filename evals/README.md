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

```sh
python evals/ci_gate.py
```

Floors live in `evals/fixtures/thresholds.json`.

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
`evals/fixtures/inventoryflex/detect-comparison.json`.

## Metrics & targets

| Metric | Target (v1) |
|---|---|
| `item_recall_notable` | ≥ 90 |
| `hallucination_rate` | ≤ 5 |
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
