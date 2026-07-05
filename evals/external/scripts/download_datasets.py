#!/usr/bin/env python3
"""Cross-platform Tier-A dataset downloader (docs/23 GPU re-run runbook).

Replaces the bash heredocs in ``evals/external/README.md`` so this runs on
Windows PowerShell / cmd as well as macOS/Linux. Downloads to the gitignored
cache ``evals/external/data/``.

    uv run python evals/external/scripts/download_datasets.py --list
    uv run python evals/external/scripts/download_datasets.py indoor67
    uv run python evals/external/scripts/download_datasets.py film-shots
    uv run python evals/external/scripts/download_datasets.py open-images --max-samples 30000
    uv run python evals/external/scripts/download_datasets.py koniq   # prints manual steps
    uv run python evals/external/scripts/download_datasets.py all      # everything scriptable

Requires the ml extra: ``uv pip install -e .[ml]`` (datasets, huggingface_hub,
fiftyone). See docs/23 for the CUDA torch install.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "evals" / "external" / "data"

DATASETS = {
    "indoor67": {
        "ml": "ML-E16",
        "hf": "keremberke/indoor-scene-classification",
        "dir": DATA / "indoor-scene",
        "size": "~150 MB",
        "licence": "Research (MIT page) / CC BY (HF derivative)",
    },
    "film-shots": {
        "ml": "ML-E19",
        "hf": "szymonrucinski/types-of-film-shots",
        "dir": DATA / "film-shots",
        "size": "<100 MB",
        "licence": "CC BY 4.0",
    },
    "koniq": {
        "ml": "ML-E17",
        "hf": None,  # manual — registration required
        "dir": DATA / "koniq10k",
        "size": "~2 GB",
        "licence": "Research download (register)",
    },
    "open-images": {
        "ml": "ML-E18",
        "hf": None,  # via fiftyone class filter
        "dir": DATA / "open-images-v7",
        "size": "~5–15 GB (filtered)",
        "licence": "Apache 2.0",
    },
}


def do_hf(spec: dict) -> int:
    try:
        from datasets import load_dataset
    except ImportError:
        print("pip install datasets huggingface_hub  (or: uv pip install -e .[ml])",
              file=sys.stderr)
        return 1
    out = spec["dir"]
    out.mkdir(parents=True, exist_ok=True)
    print(f"downloading {spec['hf']} → {out} ({spec['size']}) …", flush=True)
    ds = load_dataset(spec["hf"])
    ds.save_to_disk(str(out))
    print(f"saved {spec['hf']} to {out}")
    return 0


def do_koniq(spec: dict) -> int:
    out = spec["dir"]
    out.mkdir(parents=True, exist_ok=True)
    print(
        "KonIQ-10k needs manual registration (no redistributable HF mirror):\n"
        "  1. Register + download at "
        "https://database.mmsp-kn.de/koniq-10k-database.html\n"
        "  2. Unpack images + koniq10k_distributions_sets.csv into:\n"
        f"       {out}\n"
        "  3. Expected: images/ (or 512x384/) + a *scores*/distributions CSV\n"
        "Then: uv run python evals/train_iqa_koniq.py  (auto-detects the cache)"
    )
    return 0


def do_open_images(spec: dict, max_samples: int) -> int:
    try:
        import fiftyone as fo  # noqa: F401
        import fiftyone.zoo as foz
    except ImportError:
        print("pip install fiftyone  (or: uv pip install -e .[ml])", file=sys.stderr)
        return 1
    from evals.oi_vocab import OPEN_IMAGES_HOUSEHOLD_CLASSES  # canonical list

    out = spec["dir"]
    out.mkdir(parents=True, exist_ok=True)
    print(f"downloading Open Images V7 household subset "
          f"({len(OPEN_IMAGES_HOUSEHOLD_CLASSES)} classes, max {max_samples}) "
          f"→ {out} …", flush=True)
    foz.load_zoo_dataset(
        "open-images-v7",
        split="train",
        label_types=["detections"],
        classes=list(OPEN_IMAGES_HOUSEHOLD_CLASSES),
        max_samples=max_samples,
        dataset_dir=str(out),
    )
    print(f"saved OI V7 subset to {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dataset", nargs="?",
                    choices=[*DATASETS, "all"], help="dataset key")
    ap.add_argument("--list", action="store_true", help="list datasets and exit")
    ap.add_argument("--max-samples", type=int, default=30000,
                    help="open-images cap (tune for disk)")
    args = ap.parse_args()

    if args.list or not args.dataset:
        print(f"{'key':<14}{'ML-E':<8}{'size':<20}licence")
        for k, s in DATASETS.items():
            print(f"{k:<14}{s['ml']:<8}{s['size']:<20}{s['licence']}")
        print(f"\ncache dir: {DATA}")
        return 0

    keys = list(DATASETS) if args.dataset == "all" else [args.dataset]
    rc = 0
    for k in keys:
        spec = DATASETS[k]
        print(f"\n=== {k} ({spec['ml']}) ===")
        if k == "koniq":
            rc |= do_koniq(spec)
        elif k == "open-images":
            rc |= do_open_images(spec, args.max_samples)
        elif spec["hf"]:
            rc |= do_hf(spec)
    return rc


if __name__ == "__main__":
    sys.exit(main())
