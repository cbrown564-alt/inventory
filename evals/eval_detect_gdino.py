#!/usr/bin/env python3
"""ML-E10: Benchmark Grounding DINO (Apache-2.0) vs YOLOE text on InventoryFlex.

Reuses ``eval_detect.py`` metrics: notable-item recall and unmatched-label
noise. Grounding DINO runs from ``evals/gdino_detect.py`` only — the build
pipeline keeps YOLOE (AGPL) as default until gate G3 (docs/19).

Usage:
    python benchmarks/extract_inventoryflex.py
    python evals/eval_detect_gdino.py benchmarks/inventoryflex/capture \\
        evals/fixtures/inventoryflex/labels.json
    python evals/eval_detect_gdino.py CAPTURE LABELS.json -o \\
        evals/fixtures/inventoryflex/detect-comparison-gdino.json --device cpu

Optional deps (eval only):
    pip install transformers accelerate
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

from eval_detect import evaluate_detector, evaluate_mode  # noqa: E402
from gdino_detect import DEFAULT_MODEL, GroundingDinoDetector  # noqa: E402
from homeinventory.detect import Detector, default_model  # noqa: E402
from homeinventory.ingest import ingest  # noqa: E402

DEFAULT_OUT = ROOT / "evals/fixtures/inventoryflex/detect-comparison-gdino.json"


def _gdino_recommendation(yoloe: dict, gdino: dict) -> str:
    if not gdino.get("available"):
        return (
            "yoloe text (default) — Grounding DINO deps unavailable; "
            "install transformers + torch and re-run eval_detect_gdino"
        )
    if not yoloe.get("available"):
        return "gdino — YOLOE unavailable on this machine"

    y_rec = yoloe.get("gold_recall_notable") or 0
    g_rec = gdino.get("gold_recall_notable") or 0
    y_noise = yoloe.get("unmatched_label_rate") or 100
    g_noise = gdino.get("unmatched_label_rate") or 100
    recall_delta = round(g_rec - y_rec, 1)

    if recall_delta >= 5 and g_noise <= y_noise + 5:
        return (
            f"gdino candidate — notable recall +{recall_delta}pp with noise "
            f"≤ YOLOE text (+{round(g_noise - y_noise, 1)}pp); meets ML-E10 "
            "recall bar — review latency before G3 swap (docs/19)"
        )
    if recall_delta >= 5 and g_noise > y_noise + 5:
        return (
            f"yoloe text (default) — gdino recall +{recall_delta}pp but unmatched "
            f"labels +{round(g_noise - y_noise, 1)}pp vs text; keep YOLOE until "
            "noise is controlled"
        )
    if recall_delta < 5:
        return (
            f"yoloe text (default) — gdino recall delta {recall_delta:+.1f}pp "
            "(need ≥+5pp for G3); Apache path still worth bbox labelling (ML-E11)"
        )
    return "yoloe text (default) — household vocabulary baseline on this fixture"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture_dir", type=Path)
    ap.add_argument("labels_json", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--model-yoloe", default=None, help="override YOLOE weights")
    ap.add_argument("--model-gdino", default=DEFAULT_MODEL,
                    help="Hugging Face Grounding DINO model id")
    ap.add_argument("--device", default=None)
    ap.add_argument("--room", help="comma-separated room filter")
    ap.add_argument("--skip-yoloe", action="store_true",
                    help="benchmark gdino only (offline Apache path)")
    args = ap.parse_args()

    if not args.capture_dir.is_dir():
        print(f"error: capture dir not found: {args.capture_dir}", file=sys.stderr)
        return 2
    if not args.labels_json.is_file():
        print(f"error: labels not found: {args.labels_json}", file=sys.stderr)
        return 2

    labels = json.loads(args.labels_json.read_text(encoding="utf-8"))
    rooms_filter = None
    if args.room:
        rooms_filter = {r.strip().lower() for r in args.room.split(",")}

    rooms_photos = ingest(args.capture_dir, args.capture_dir / ".eval-detect-work")
    results: list[dict] = []

    if not args.skip_yoloe:
        print("evaluating backend=yoloe mode=text …", flush=True)
        yoloe = evaluate_mode(
            args.capture_dir,
            labels,
            "text",
            match_threshold=args.threshold,
            conf=args.conf,
            model=args.model_yoloe,
            device=args.device,
            rooms_filter=rooms_filter,
        )
        results.append(yoloe)
        if yoloe.get("available"):
            print(f"  gold recall (notable): {yoloe['gold_recall_notable']}%  "
                  f"unmatched labels: {yoloe['unmatched_label_rate']}%")
        else:
            print(f"  unavailable: {yoloe.get('error')}", file=sys.stderr)

    print("evaluating backend=gdino …", flush=True)
    gdino_detector = GroundingDinoDetector(
        conf=args.conf,
        device=args.device,
        model_id=args.model_gdino,
    )
    gdino = evaluate_detector(
        args.capture_dir,
        labels,
        gdino_detector,
        backend="gdino",
        mode="text",
        model=args.model_gdino,
        match_threshold=args.threshold,
        device=args.device,
        conf=args.conf,
        rooms_filter=rooms_filter,
        rooms_photos=rooms_photos,
    )
    results.append(gdino)
    if gdino.get("available"):
        print(f"  gold recall (notable): {gdino['gold_recall_notable']}%  "
              f"unmatched labels: {gdino['unmatched_label_rate']}%")
    else:
        print(f"  unavailable: {gdino.get('error')}", file=sys.stderr)

    yoloe = next((r for r in results if r.get("backend") == "yoloe"), None)
    comparison: dict = {}
    if yoloe and gdino.get("available") and yoloe.get("available"):
        comparison = {
            "backends": ["yoloe", "gdino"],
            "gold_recall_notable_delta": round(
                (gdino.get("gold_recall_notable") or 0)
                - (yoloe.get("gold_recall_notable") or 0),
                1,
            ),
            "gold_recall_all_delta": round(
                (gdino.get("gold_recall_all") or 0)
                - (yoloe.get("gold_recall_all") or 0),
                1,
            ),
            "unmatched_label_rate_delta": round(
                (gdino.get("unmatched_label_rate") or 0)
                - (yoloe.get("unmatched_label_rate") or 0),
                1,
            ),
            "coverage_gap_rate_delta": round(
                (gdino.get("coverage_gap_rate") or 0)
                - (yoloe.get("coverage_gap_rate") or 0),
                1,
            ),
            "recommendation": _gdino_recommendation(yoloe, gdino),
        }
    elif gdino.get("available") is False:
        comparison = {
            "backends": [r.get("backend") for r in results],
            "gdino_available": False,
            "recommendation": _gdino_recommendation(yoloe or {}, gdino),
        }

    payload = {
        "experiment": "ML-E10",
        "capture_dir": str(args.capture_dir),
        "labels": str(args.labels_json),
        "vocab": "HOUSEHOLD_VOCAB",
        "device": args.device,
        "evaluated": date.today().isoformat(),
        "modes": results,
        "comparison": comparison,
        "dependency_notes": {
            "yoloe": "pip install -e '.[detect]' && "
                     "pip install git+https://github.com/ultralytics/CLIP.git",
            "gdino": "pip install transformers accelerate (Apache-2.0; eval only)",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    if comparison.get("recommendation"):
        print(f"recommendation: {comparison['recommendation']}")

    if gdino.get("available") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
