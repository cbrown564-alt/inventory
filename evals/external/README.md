# External datasets (Tier A)

Adjacent open datasets for ML pretrain and spike oracles — **not** committed to
git. Download to a local cache (default `evals/external/data/`, gitignored) and
record which ML-E experiment consumed each set.

See docs/19 §2.4 for the full survey, licence caveats, and Tier B–D sets.

## Layout

```text
evals/external/
  README.md          ← this file
  data/              ← local cache (gitignored — create after download)
  scripts/           ← optional helper scripts (download only, no archives in git)
```

Add to `.gitignore` if not already present:

```gitignore
evals/external/data/
```

## Tier A — download first

| Dataset | ML-E | Task | Licence | Size (approx) |
|---|---|---|---|---|
| [KonIQ-10k](https://database.mmsp-kn.de/koniq-10k-database.html) | **ML-E17** | NR-IQA pretrain → ONNX distill | Research download (MOS scores) | ~2 GB |
| [MIT Indoor 67](https://web.mit.edu/torralba/www/indoor.html) / [HF indoor-scene-classification](https://huggingface.co/datasets/keremberke/indoor-scene-classification) | **ML-E16** | Room-type classifier 67→10 classes | Research / CC BY (HF) | ~150 MB (HF) |
| [Open Images V7](https://storage.googleapis.com/openimages/web/index.html) (household subset) | **ML-E18** | Detector pretrain before InventoryFlex eval | Apache 2.0 | ~5–30 GB filtered; full set ~561 GB |
| [types-of-film-shots](https://huggingface.co/datasets/szymonrucinski/types-of-film-shots) | **ML-E19** | Shot-scale (LS vs CU) establishing baseline | CC BY 4.0 | ~925 images, <100 MB |

Tier C sets used by **ML-E20** (defect pre-filter) are documented in docs/19 §2.4
(BD3, StructDamage) — defer until ML-E15/E20 spike.

---

### KonIQ-10k — ML-E17

**Purpose:** Pretrain or distil a licence-clean NR-IQA ranker; complements MUSIQ
oracle (eval-only, NC licence).

**Download:**

1. Register at https://database.mmsp-kn.de/koniq-10k-database.html
2. Download images + `koniq10k_distributions_sets.csv`

```sh
mkdir -p evals/external/data/koniq10k
# after manual download, unpack to evals/external/data/koniq10k/
# expected: images/ + koniq10k_distributions_sets.csv
```

**Licence:** Research use; check database terms before product weights.

---

### MIT Indoor 67 / Hugging Face — ML-E16

**Purpose:** Fine-tune room-type head; eval wrong-room rejection on
`evals/fixtures/ownproperty-bleed-exclusions.json`.

**Download (HF — smallest path):**

```sh
uv run python - <<'PY'
from pathlib import Path
try:
    from datasets import load_dataset
except ImportError:
    raise SystemExit("pip install datasets huggingface_hub, then re-run")
out = Path("evals/external/data/indoor-scene")
out.mkdir(parents=True, exist_ok=True)
ds = load_dataset("keremberke/indoor-scene-classification")
ds.save_to_disk(str(out))
print(f"saved to {out}")
PY
```

**Alternative (original MIT Indoor 67):**

```sh
mkdir -p evals/external/data/mit-indoor67
curl -L -o evals/external/data/mit-indoor67/Indoor67.tar \
  "http://groups.csail.mit.edu/vision/LabelMe/NewImages/indoorCVPR_09.tar"
# unpack per MIT page instructions
```

**Licence:** Research (MIT page); HF derivative CC BY.

---

### Open Images V7 (household filter) — ML-E18

**Purpose:** Pretrain Grounding DINO / YOLO on ~30–40 household classes aligned
with `HOUSEHOLD_VOCAB` before InventoryFlex eval.

**Do not download the full 561 GB corpus.** Filter by class:

```sh
mkdir -p evals/external/data/open-images-v7
uv run python - <<'PY'
"""Fetch Open Images class list and write a household subset manifest.
Requires: pip install fiftyone  (heavy — optional extra for one-off download)
"""
HOUSEHOLD = {
    "Bathtub", "Bed", "Chair", "Coffee table", "Couch", "Desk", "Dishwasher",
    "Door", "Faucet", "House", "Kitchen & dining room table", "Lamp",
    "Microwave oven", "Mirror", "Oven", "Picture frame", "Refrigerator",
    "Sink", "Sofa bed", "Stool", "Table", "Television", "Toilet", "Washing machine",
    "Window", "Cabinetry", "Chest of drawers", "Countertop", "Tap", "Shower",
}
print("Household class filter:", len(HOUSEHOLD), "terms")
print("Use FiftyOne zoo.open_images download with classes= above,")
print("or aws s3 sync s3://open-images-dataset/ with class-filtered CSVs.")
print("See https://storage.googleapis.com/openimages/web/download.html")
PY
```

**FiftyOne one-liner (after `pip install fiftyone`):**

```sh
fiftyone datasets download open-images-v7 \
  --classes Bathtub,Bed,Chair,Dishwasher,Door,Faucet,Mirror,Oven,Refrigerator,Sink,Toilet,Washing machine \
  --max-samples 50000 \
  --dataset-dir evals/external/data/open-images-v7
```

**Licence:** Apache 2.0.

---

### types-of-film-shots — ML-E19

**Purpose:** Quick shot-scale baseline (long shot ≈ establishing) before SigLIP
prompts (ML-E4/E7).

**Download:**

```sh
mkdir -p evals/external/data/film-shots
uv run python - <<'PY'
from pathlib import Path
try:
    from datasets import load_dataset
except ImportError:
    raise SystemExit("pip install datasets huggingface_hub")
out = Path("evals/external/data/film-shots")
out.mkdir(parents=True, exist_ok=True)
ds = load_dataset("szymonrucinski/types-of-film-shots")
ds.save_to_disk(str(out))
print(f"saved to {out}")
PY
```

**Licence:** CC BY 4.0.

---

## Experiment log

When a spike consumes a dataset, add a row:

| Date | ML-E | Dataset path | Notes |
|---|---|---|---|
| — | — | — | (fill on first download) |

## Related

- docs/19-ml-dl-exploration-plan.md §2.4, §4 (ML-E16–E20)
- `evals/splits/inventoryflex.json` — held-out rooms for eval after pretrain
- `evals/fixtures/inventoryflex/labels.json` — in-repo gold (no external download)
