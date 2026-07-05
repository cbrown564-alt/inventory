#!/usr/bin/env python3
"""ML-E15: zero-shot anomaly pre-filter on InventoryFlex (docs/19 §1.7).

Scores each deliberate-capture photo with OpenCLIP defect vs clean prompts.
InventoryFlex photos are clerk-quality **clean** captures — ground truth is
*no visible anomaly*. False positive rate = fraction flagged as defect.

Pass bar: FP rate <10% on InventoryFlex.

Usage:
    python benchmarks/extract_inventoryflex.py
    uv run python evals/eval_defect_zeroshot.py
    uv run python evals/eval_defect_zeroshot.py --demo --no-torch
    uv run python evals/eval_defect_zeroshot.py benchmarks/inventoryflex/capture \\
        -o evals/fixtures/inventoryflex/defect-filter-report.json --device cpu

Optional deps (eval only):
    uv pip install open-clip-torch
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

from defect_zeroshot import (  # noqa: E402
    CLEAN_PROMPTS,
    DEFECT_PROMPTS,
    DEFAULT_THRESHOLD,
    DefectZeroshotScorer,
    synthetic_defect_score,
)
from homeinventory.ingest import ingest  # noqa: E402

DEFAULT_CAPTURE = ROOT / "benchmarks/inventoryflex/capture"
DEFAULT_OUT = ROOT / "evals/fixtures/inventoryflex/defect-filter-report.json"
PASS_BAR_FP_PCT = 10.0


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def collect_photos(capture_dir: Path) -> list[tuple[str, Path]]:
    work = capture_dir / ".eval-defect-zeroshot-work"
    rooms = ingest(capture_dir, work)
    out: list[tuple[str, Path]] = []
    for room, photos in sorted(rooms.items()):
        for p in photos:
            full = Path(p.path)
            if not full.is_absolute():
                full = capture_dir / full
            out.append((room, full))
    return out


def score_photos(
        photos: list[tuple[str, Path]],
        *,
        device: str,
        no_torch: bool,
        max_photos: int | None,
) -> list[dict]:
    if max_photos is not None:
        photos = photos[:max_photos]

    scorer = None if no_torch else DefectZeroshotScorer(device=device)
    if scorer and not scorer.available:
        raise SystemExit(f"OpenCLIP unavailable: {scorer._load_error}")

    rows: list[dict] = []
    for room, path in photos:
        if no_torch:
            scores = synthetic_defect_score(path)
        else:
            scores = scorer.score_path(path)
        rows.append({
            "room": room,
            "path": _rel(path),
            **scores,
        })
    return rows


def aggregate(rows: list[dict], threshold: float) -> dict:
    n = len(rows)
    flagged = [r for r in rows if r.get("defect_prob", 0) >= threshold]
    fp_pct = round(100.0 * len(flagged) / n, 1) if n else 0.0
    probs = [r["defect_prob"] for r in rows if "defect_prob" in r]
    margins = [r["margin"] for r in rows if "margin" in r]
    by_room: dict[str, dict] = {}
    for room in sorted({r["room"] for r in rows}):
        room_rows = [r for r in rows if r["room"] == room]
        room_flagged = [r for r in room_rows if r.get("defect_prob", 0) >= threshold]
        by_room[room] = {
            "n_photos": len(room_rows),
            "n_flagged": len(room_flagged),
            "fp_pct": round(100.0 * len(room_flagged) / len(room_rows), 1),
        }
    return {
        "n_photos": n,
        "n_flagged": len(flagged),
        "fp_pct": fp_pct,
        "pass_bar_fp_pct": PASS_BAR_FP_PCT,
        "pass": fp_pct < PASS_BAR_FP_PCT,
        "threshold_defect_prob": threshold,
        "mean_defect_prob": round(sum(probs) / len(probs), 4) if probs else None,
        "mean_margin": round(sum(margins) / len(margins), 4) if margins else None,
        "per_room": by_room,
    }


def top_flagged(rows: list[dict], n: int = 12) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("defect_prob", 0), reverse=True)[:n]


def build_payload(
        *,
        capture_dir: Path,
        rows: list[dict],
        metrics: dict,
        device: str,
        no_torch: bool,
        demo: bool,
) -> dict:
    passed = metrics["pass"]
    fp = metrics["fp_pct"]
    return {
        "experiment": "ML-E15",
        "date": date.today().isoformat(),
        "capture_dir": _rel(capture_dir),
        "method": "openclip_zeroshot" if not no_torch else "synthetic_demo",
        "encoder": "ViT-B-32/openai" if not no_torch else "synthetic",
        "device": device,
        "defect_prompts": DEFECT_PROMPTS,
        "clean_prompts": CLEAN_PROMPTS,
        "pass_bar_fp_pct": PASS_BAR_FP_PCT,
        "metrics": metrics,
        "pass": passed,
        "demo": demo,
        "note": (
            "InventoryFlex capture photos are deliberate clean clerk shots — high "
            "zero-shot FP is expected (wood grain, shadows, specular highlights). "
            "Use as pre-filter oracle only; do not gate describe pool until native-res "
            "defect labels exist (docs/19 §1.7)."
        ),
        "recommendation": (
            f"fail — FP {fp}% exceeds {PASS_BAR_FP_PCT}% bar; zero-shot CLIP prompts "
            "unsuitable as pre-filter on clean inventory photos"
            if not passed else
            f"pass — FP {fp}% below {PASS_BAR_FP_PCT}% bar (unexpected on IFlex clean set)"
        ),
        "top_flagged": top_flagged(rows),
    }


def run(args: argparse.Namespace) -> dict:
    capture_dir = args.capture_dir.resolve()
    if not capture_dir.is_dir():
        raise SystemExit(
            f"error: capture dir not found: {capture_dir}\n"
            "run: python benchmarks/extract_inventoryflex.py"
        )

    photos = collect_photos(capture_dir)
    if not photos:
        raise SystemExit(f"error: no photos under {capture_dir}")

    max_photos = args.max_photos
    if args.demo and max_photos is None and args.no_torch:
        max_photos = 24

    rows = score_photos(
        photos,
        device=args.device,
        no_torch=args.no_torch,
        max_photos=max_photos,
    )
    metrics = aggregate(rows, args.threshold)
    payload = build_payload(
        capture_dir=capture_dir,
        rows=rows,
        metrics=metrics,
        device=args.device,
        no_torch=args.no_torch,
        demo=args.demo,
    )

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
                    help="subset / synthetic mode for CI smoke")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-torch", action="store_true",
                    help="deterministic synthetic scores (no OpenCLIP)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="defect softmax probability threshold")
    ap.add_argument("--max-photos", type=int, default=None,
                    help="cap photos scored (demo/CI)")
    args = ap.parse_args()

    payload = run(args)
    print(json.dumps({k: v for k, v in payload.items() if k != "top_flagged"}, indent=2))
    print(f"wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
