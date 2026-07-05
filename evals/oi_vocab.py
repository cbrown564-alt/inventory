"""Open Images V7 household subset aligned with ``HOUSEHOLD_VOCAB`` (ML-E18).

Documents ~40 OI display names used for filtered download and detector
pretrain. Maps OI labels back to inventory terms for InventoryFlex eval.
"""

from __future__ import annotations

from homeinventory.detect import HOUSEHOLD_VOCAB

# Open Images V7 display names — household / furniture subset (~40 classes).
# Filter download with FiftyOne; do not fetch the full ~561 GB corpus.
OPEN_IMAGES_HOUSEHOLD_CLASSES: list[str] = [
    "Armchair",
    "Bathtub",
    "Bed",
    "Bicycle",
    "Bookcase",
    "Cabinetry",
    "Carpet",
    "Ceiling fan",
    "Chair",
    "Chest of drawers",
    "Clock",
    "Coffee table",
    "Computer monitor",
    "Couch",
    "Countertop",
    "Cupboard",
    "Curtain",
    "Desk",
    "Dishwasher",
    "Door",
    "Drawer",
    "Faucet",
    "Houseplant",
    "Kitchen & dining room table",
    "Lamp",
    "Laptop",
    "Microwave oven",
    "Mirror",
    "Oven",
    "Picture frame",
    "Poster",
    "Range hood",
    "Refrigerator",
    "Sink",
    "Shower",
    "Sofa bed",
    "Stool",
    "Table",
    "Television",
    "Toilet",
    "Washing machine",
    "Window",
]

# OI display name (normalised key) → canonical HOUSEHOLD_VOCAB term for eval.
OI_CLASS_TO_HOUSEHOLD: dict[str, str] = {
    "armchair": "armchair",
    "bathtub": "bathtub",
    "bed": "bed",
    "bicycle": "bicycle",
    "bookcase": "bookshelf",
    "cabinetry": "cabinet",
    "carpet": "carpet",
    "ceiling fan": "ceiling light",
    "chair": "chair",
    "chest of drawers": "chest of drawers",
    "clock": "clock",
    "coffee table": "coffee table",
    "computer monitor": "monitor",
    "couch": "sofa",
    "countertop": "cabinet",
    "cupboard": "cabinet",
    "curtain": "curtains",
    "desk": "desk",
    "dishwasher": "dishwasher",
    "door": "door",
    "drawer": "chest of drawers",
    "faucet": "tap",
    "houseplant": "plant pot",
    "kitchen & dining room table": "dining table",
    "kitchen and dining room table": "dining table",
    "lamp": "lamp",
    "laptop": "laptop",
    "microwave oven": "microwave",
    "mirror": "mirror",
    "oven": "oven",
    "picture frame": "picture frame",
    "poster": "painting",
    "range hood": "stove",
    "refrigerator": "refrigerator",
    "sink": "sink",
    "shower": "shower",
    "sofa bed": "sofa",
    "stool": "chair",
    "table": "dining table",
    "television": "television",
    "toilet": "toilet",
    "washing machine": "washing machine",
    "window": "window",
}

DEFAULT_OI_WEIGHTS = "evals/external/data/open-images-v7/weights/gdino-oi-household.pt"

FIFTYONE_CLASSES_CSV = ",".join(OPEN_IMAGES_HOUSEHOLD_CLASSES)


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").replace("&", " and ").split())


def household_terms_covered_by_oi() -> list[str]:
    """HOUSEHOLD_VOCAB terms with at least one OI class alias."""
    covered = set(OI_CLASS_TO_HOUSEHOLD.values())
    return [v for v in HOUSEHOLD_VOCAB if v in covered]


def household_terms_missing_from_oi() -> list[str]:
    covered = set(OI_CLASS_TO_HOUSEHOLD.values())
    return [v for v in HOUSEHOLD_VOCAB if v not in covered]


def expanded_proxy_vocab() -> list[str]:
    """Phrase list for GDINO proxy: OI names plus uncovered inventory terms."""
    phrases = list(OPEN_IMAGES_HOUSEHOLD_CLASSES)
    missing = household_terms_missing_from_oi()
    for term in missing:
        if term not in phrases:
            phrases.append(term.replace("_", " "))
    return phrases


def map_oi_label_to_household(label: str) -> str:
    key = _norm(label)
    if key in OI_CLASS_TO_HOUSEHOLD:
        return OI_CLASS_TO_HOUSEHOLD[key]
    for oi_key, household in OI_CLASS_TO_HOUSEHOLD.items():
        if oi_key in key or key in oi_key:
            return household
    return label.strip()


def find_oi_weights(path: str | None = None) -> str | None:
    """Return path to OI-pretrained weights if present."""
    from pathlib import Path

    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    root = Path(__file__).resolve().parents[1]
    candidates.extend([
        root / "evals/external/data/open-images-v7/weights/gdino-oi-household.pt",
        root / "evals/external/data/open-images-v7/weights/gdino-oi-household.safetensors",
        root / "evals/external/data/open-images-v7/weights/pytorch_model.bin",
    ])
    weights_dir = root / "evals/external/data/open-images-v7/weights"
    if weights_dir.is_dir():
        candidates.extend(sorted(weights_dir.glob("*.pt")))
        candidates.extend(sorted(weights_dir.glob("*.safetensors")))
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return str(candidate)
    return None


def training_recipe(weights_path: str = DEFAULT_OI_WEIGHTS) -> dict:
    """Documented path when OI-pretrained weights are not on disk."""
    return {
        "summary": (
            "Fine-tune Grounding DINO (Apache-2.0) on the Open Images V7 "
            "household subset, then eval notable recall on InventoryFlex vs "
            "ML-E10 GDINO baseline (docs/19 ML-E18)."
        ),
        "dataset": {
            "name": "Open Images V7 (household filter)",
            "licence": "Apache-2.0",
            "do_not_download_full_corpus": "Full OI V7 is ~561 GB — use class filter only",
            "class_count": len(OPEN_IMAGES_HOUSEHOLD_CLASSES),
            "classes": OPEN_IMAGES_HOUSEHOLD_CLASSES,
            "fiftyone_command": (
                "fiftyone datasets download open-images-v7 "
                f"--classes {FIFTYONE_CLASSES_CSV} "
                "--max-samples 50000 "
                "--dataset-dir evals/external/data/open-images-v7"
            ),
            "docs": "evals/external/README.md § Open Images V7 — ML-E18",
        },
        "household_vocab": {
            "source": "homeinventory.detect.HOUSEHOLD_VOCAB",
            "terms_covered_by_oi": household_terms_covered_by_oi(),
            "terms_missing_from_oi": household_terms_missing_from_oi(),
        },
        "steps": [
            "Download filtered OI V7 via FiftyOne (see evals/external/README.md).",
            "Export COCO-style annotations from the FiftyOne dataset.",
            "Fine-tune IDEA-Research/grounding-dino-tiny on household classes "
            "(LoRA or full head; laptop / single-GPU session).",
            f"Save checkpoint to {weights_path}.",
            "Re-run: python3 evals/eval_detect_oi_pretrain.py "
            "benchmarks/inventoryflex/capture evals/fixtures/inventoryflex/labels.json",
        ],
        "weights_path": weights_path,
        "pass_bar": "Notable recall ↑ vs ML-E10 GDINO baseline on InventoryFlex",
        "reference": "docs/19-ml-dl-exploration-plan.md § ML-E18",
    }


def open_images_subset_doc() -> dict:
    """JSON-serialisable OI household subset metadata."""
    covered = household_terms_covered_by_oi()
    return {
        "version": "Open Images V7",
        "licence": "Apache-2.0",
        "full_corpus_size_gb": 561,
        "filtered_estimate_gb": "5–30 (class filter; max-samples dependent)",
        "class_count": len(OPEN_IMAGES_HOUSEHOLD_CLASSES),
        "classes": OPEN_IMAGES_HOUSEHOLD_CLASSES,
        "household_vocab_size": len(HOUSEHOLD_VOCAB),
        "household_terms_covered": len(covered),
        "household_terms_missing": household_terms_missing_from_oi(),
        "fiftyone_filter": {
            "command": training_recipe()["dataset"]["fiftyone_command"],
            "max_samples_note": "Tune --max-samples for disk budget; 50k ≈ 5–15 GB",
        },
    }
