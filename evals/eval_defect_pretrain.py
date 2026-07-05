#!/usr/bin/env python3
"""ML-E20: StructDamage/BD3 defect pre-filter pretrain stub (docs/19 §2.4 Tier C).

Documents Tier C data needs (BD3, StructDamage) and evaluates FP rate on
InventoryFlex. Without downloaded pretrain weights, ``--demo`` reuses the
ML-E15 OpenCLIP zero-shot bootstrap as a proxy — real pretrain requires
BD3/StructDamage download per ``evals/external/README.md``.

Pass bar: FP <10% on InventoryFlex.

Usage:
    uv run python evals/eval_defect_pretrain.py --demo
    uv run python evals/eval_defect_pretrain.py benchmarks/inventoryflex/capture \\
        -o evals/fixtures/inventoryflex/defect-pretrain-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from defect_zeroshot import DEFAULT_THRESHOLD  # noqa: E402
from eval_defect_zeroshot import (  # noqa: E402
    DEFAULT_CAPTURE,
    PASS_BAR_FP_PCT,
    aggregate,
    collect_photos,
    score_photos,
    top_flagged,
)

DEFAULT_OUT = ROOT / "evals/fixtures/inventoryflex/defect-pretrain-report.json"
EXTERNAL_DATA = ROOT / "evals/external/data"
BD3_DIR = EXTERNAL_DATA / "bd3"
STRUCT_DAMAGE_DIR = EXTERNAL_DATA / "structdamage"

TIER_C_DATASETS = [
    {
        "name": "BD3",
        "url": "https://github.com/Praveenkottari/BD3-Dataset",
        "scale": "~4k images (stain, peel, spall, crack)",
        "licence": "research — check repo",
        "local_path": "evals/external/data/bd3",
    },
    {
        "name": "StructDamage",
        "url": "https://arxiv.org/abs/2603.10484",
        "scale": "~78k aggregated structural damage images (CC BY 4.0)",
        "licence": "CC BY 4.0",
        "local_path": "evals/external/data/structdamage",
    },
    {
        "name": "RBDID",
        "url": "https://doi.org/10.57760/sciencedb.28941",
        "scale": "~26k residential interior defect images",
        "licence": "ScienceDB — registration",
        "local_path": "evals/external/data/rbdid",
        "note": "closest residential interior bbox set; still not UK tenancy scuffs",
    },
]

TRAINING_RECIPE = {
    "summary": (
        "Binary surface-anomaly classifier pretrain on BD3 + StructDamage; "
        "fine-tune head on RBDID optional; eval FP on InventoryFlex clean captures."
    ),
    "steps": [
        "Download BD3 and StructDamage to evals/external/data/ (gitignored).",
        "Train binary defect head (ResNet-50 or ViT-B/16) — ~1 GPU session.",
        "Export weights ≤10 MB or document download script.",
        "Re-run this harness with --weights path/to/checkpoint.pt.",
        "Pass bar: FP <10% on benchmarks/inventoryflex/capture.",
    ],
    "caveats": [
        "Exterior/structural defects ≠ interior fair-wear scuffs (docs/19 §2.4).",
        "Expect high FP on wood grain, shadows, and patina without UK tenancy labels.",
        "Pre-filter only — never silent-delete evidence (docs/15).",
    ],
}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def find_pretrain_weights(weights_arg: Path | None) -> Path | None:
    if weights_arg and weights_arg.is_file():
        return weights_arg.resolve()
    for candidate in (
        EXTERNAL_DATA / "defect-pretrain.pt",
        BD3_DIR / "checkpoint.pt",
        STRUCT_DAMAGE_DIR / "checkpoint.pt",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def data_status() -> dict:
    return {
        "bd3_present": BD3_DIR.is_dir() and any(BD3_DIR.iterdir()),
        "structdamage_present": STRUCT_DAMAGE_DIR.is_dir()
        and any(STRUCT_DAMAGE_DIR.iterdir()),
        "tier_c_datasets": TIER_C_DATASETS,
        "download_doc": "evals/external/README.md",
    }


def run(args: argparse.Namespace) -> dict:
    capture_dir = args.capture_dir.resolve()
    if not capture_dir.is_dir():
        raise SystemExit(
            f"error: capture dir not found: {capture_dir}\n"
            "run: python benchmarks/extract_inventoryflex.py"
        )

    weights = find_pretrain_weights(args.weights)
    pretrain_available = weights is not None

    photos = collect_photos(capture_dir)
    if not photos:
        raise SystemExit(f"error: no photos under {capture_dir}")

    max_photos = args.max_photos
    if args.demo and max_photos is None and args.no_torch:
        max_photos = 24

    # Without Tier C weights, bootstrap with the same OpenCLIP zero-shot as ML-E15.
    use_no_torch = args.no_torch
    method = "openclip_zeroshot_bootstrap_mle15"
    if pretrain_available and not args.no_torch:
        method = "pretrain_weights_present_inference_stub"
        # TODO: load checkpoint when inference is implemented.
        use_no_torch = False
    elif use_no_torch:
        method = "synthetic_demo"

    rows = score_photos(
        photos,
        device=args.device,
        no_torch=use_no_torch,
        max_photos=max_photos,
    )
    metrics = aggregate(rows, args.threshold)
    fp = metrics["fp_pct"]
    passed = metrics["pass"]

    payload = {
        "experiment": "ML-E20",
        "date": date.today().isoformat(),
        "capture_dir": _rel(capture_dir),
        "pretrain_available": pretrain_available,
        "pretrain_weights": _rel(weights) if weights else None,
        "method": method,
        "pass_bar_fp_pct": PASS_BAR_FP_PCT,
        "metrics": metrics,
        "pass": passed,
        "demo": args.demo,
        "data_needs": data_status(),
        "training_recipe": TRAINING_RECIPE,
        "note": (
            "Tier C BD3/StructDamage not downloaded — metrics use ML-E15 OpenCLIP "
            "zero-shot bootstrap (same prompts/threshold). Re-run after pretrain "
            "with --weights evals/external/data/defect-pretrain.pt."
        ),
        "recommendation": (
            f"blocked on data — download BD3/StructDamage; current bootstrap FP {fp}% "
            f"vs {PASS_BAR_FP_PCT}% bar"
            if not pretrain_available else
            f"pretrain weights found but inference stub — bootstrap FP {fp}%"
        ),
    }

    if not passed:
        payload["recommendation"] += (
            "; zero-shot / bootstrap unsuitable as pre-filter on clean IFlex photos"
        )

    payload["top_flagged"] = top_flagged(rows)

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture_dir", nargs="?", type=Path, default=DEFAULT_CAPTURE)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--demo", action="store_true",
                    help="subset / synthetic bootstrap for CI")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-torch", action="store_true",
                    help="deterministic synthetic scores")
    ap.add_argument("--weights", type=Path, default=None,
                    help="pretrained defect checkpoint (when available)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--max-photos", type=int, default=None)
    args = ap.parse_args()

    payload = run(args)
    print(json.dumps({k: v for k, v in payload.items()
                      if k not in ("top_flagged", "training_recipe", "data_needs")},
                     indent=2))
    print(f"wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
