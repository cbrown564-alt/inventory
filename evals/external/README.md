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

**Purpose:** Pretrain Grounding DINO / YOLO on **42 household classes** aligned
with `homeinventory.detect.HOUSEHOLD_VOCAB` (~35/48 inventory terms covered;
long-tail gaps like *towel rail* and *smoke alarm* stay in our fixtures).
Eval harness: `evals/eval_detect_oi_pretrain.py` →
`evals/fixtures/inventoryflex/detect-comparison-oi.json`.

**Do not download the full 561 GB corpus.** Use the class filter only (~5–30 GB
depending on `--max-samples`).

**Household subset (OI display names)** — canonical list in `evals/oi_vocab.py`:

```text
Armchair, Bathtub, Bed, Bicycle, Bookcase, Cabinetry, Carpet, Ceiling fan,
Chair, Chest of drawers, Clock, Coffee table, Computer monitor, Couch,
Countertop, Cupboard, Curtain, Desk, Dishwasher, Door, Drawer, Faucet,
Houseplant, Kitchen & dining room table, Lamp, Laptop, Microwave oven, Mirror,
Oven, Picture frame, Poster, Range hood, Refrigerator, Sink, Shower, Sofa bed,
Stool, Table, Television, Toilet, Washing machine, Window
```

**Inspect subset metadata (no download):**

```sh
python3 - <<'PY'
from evals.oi_vocab import open_images_subset_doc
import json
print(json.dumps(open_images_subset_doc(), indent=2))
PY
```

**FiftyOne filter command** (after `pip install fiftyone`):

```sh
mkdir -p evals/external/data/open-images-v7
fiftyone datasets download open-images-v7 \
  --classes Armchair,Bathtub,Bed,Bicycle,Bookcase,Cabinetry,Carpet,Ceiling fan,Chair,Chest of drawers,Clock,Coffee table,Computer monitor,Couch,Countertop,Cupboard,Curtain,Desk,Dishwasher,Door,Drawer,Faucet,Houseplant,Kitchen & dining room table,Lamp,Laptop,Microwave oven,Mirror,Oven,Picture frame,Poster,Range hood,Refrigerator,Sink,Shower,Sofa bed,Stool,Table,Television,Toilet,Washing machine,Window \
  --max-samples 50000 \
  --dataset-dir evals/external/data/open-images-v7
```

Tune `--max-samples` for disk budget (50k ≈ 5–15 GB). Alternative: AWS CLI with
[class-filtered CSVs](https://storage.googleapis.com/openimages/web/download.html)
if FiftyOne is unavailable.

**After pretrain**, save fine-tuned Grounding DINO weights to:

```text
evals/external/data/open-images-v7/weights/gdino-oi-household.pt
```

Then re-run ML-E18 eval (compares vs ML-E10 GDINO baseline):

```sh
python benchmarks/extract_inventoryflex.py
python3 evals/eval_detect_oi_pretrain.py benchmarks/inventoryflex/capture \
  evals/fixtures/inventoryflex/labels.json
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
| 2026-07-05 | **ML-E16** | HF `keremberke/indoor-scene-classification` (stub) | Demo weights + bleed eval; no full download |
| 2026-07-05 | **ML-E17** | KonIQ-10k (bootstrap fallback) | MUSIQ-proxy linear head; real KonIQ needs manual download |
| 2026-07-06 | **ML-E16** | `evals/external/data/indoor-scene/` (456 MB, HF `datasets` arrow format) | Full download via `download_datasets.py indoor67`. Real training run: `train_room_classifier.py --encoder-model ViT-L-14 --pretrained laion2b_s32b_b82k --device cuda --epochs 60` → 98.97% train acc. Fixed a bug where the loader only checked the `label` column; the actual dataset uses `labels` (plural) — see `load_indoor67_split` in `evals/train_room_classifier.py`. Only 7/10 inventory rooms have an Indoor67 analog (no mapping for Loft Bedroom, En-suite Shower Room, Loft Shower Room). |
| 2026-07-06 | **ML-E18** | FiftyOne zoo cache `~/fiftyone/open-images-v7/` (30,000 images, 8.8 GB, household-class filtered) | Downloaded via `download_datasets.py open-images --max-samples 30000`. Note: the script's own "export to `evals/external/data/open-images-v7`" step silently produced an empty directory — the real data lives in FiftyOne's default zoo cache instead. Not a blocker: `evals/train_gdino_oi.py` (new, this date) consumes it directly via `foz.load_zoo_dataset(...)`, no export needed. First download attempt crashed (`ModuleNotFoundError: No module named 'google'`, missing protobuf dep for fiftyone's multimodal module); retry after installing it succeeded. FiftyOne also reported `Ignoring invalid classes ['Armchair', 'Carpet', 'Faucet', 'Range hood']` — 4 of the ~40 names in `evals/oi_vocab.py`'s household list don't match real Open Images class names (pre-existing gap; `household_terms_missing_from_oi()` already tracks this). |
| 2026-07-06 | **ML-E17** (code only) | none (KonIQ still not downloaded — needs manual registration) | Deprioritised per docs/23 §5 recommendation. Built the "correct E17" as code instead: `evals/embed_head.py` (shared embed + linear-head engine, classification + new regression heads) and `evals/train_iqa_embed.py` (regression over real embeddings vs hand-crafted PIL features), wired into `eval_hero_cover.py` as a new `embed-iqa` scorer. Self-tests pass; ready to train for real once KonIQ is downloaded. |

## Related

- docs/19-ml-dl-exploration-plan.md §2.4, §4 (ML-E16–E20)
- `evals/splits/inventoryflex.json` — held-out rooms for eval after pretrain
- `evals/fixtures/inventoryflex/labels.json` — in-repo gold (no external download)
