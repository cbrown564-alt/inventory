#!/usr/bin/env python3
"""Fail-closed native-resolution InventoryFlex v1 quality gate."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from PIL import Image

TARGETS = {"notable_recall": 0.90, "hallucination": 0.05,
           "defect_recall": 0.75}
MIN_NATIVE_MEGAPIXELS = 8.0


def capture_resolution(capture_dir: Path) -> dict:
    megapixels = []
    for path in capture_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            with Image.open(path) as image:
                megapixels.append(image.width * image.height / 1_000_000)
        except Exception:
            continue
    median = statistics.median(megapixels) if megapixels else 0.0
    return {"images": len(megapixels), "median_megapixels": round(median, 3),
            "native_resolution": bool(megapixels)
            and median >= MIN_NATIVE_MEGAPIXELS}


def evaluate(metrics: dict, resolution: dict) -> dict:
    checks = {
        "native_resolution": bool(resolution.get("native_resolution")),
        "notable_recall": float(metrics.get("notable_recall", -1))
        >= TARGETS["notable_recall"],
        "hallucination": float(metrics.get("hallucination", 2))
        <= TARGETS["hallucination"],
        "defect_recall": float(metrics.get("defect_recall", -1))
        >= TARGETS["defect_recall"],
    }
    return {"pass": all(checks.values()), "checks": checks,
            "targets": TARGETS, "resolution": resolution,
            "metrics": metrics}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("metrics_json", type=Path,
                        help="JSON with notable_recall, hallucination, defect_recall as 0..1")
    parser.add_argument("-o", "--out", type=Path)
    args = parser.parse_args(argv)
    result = evaluate(json.loads(args.metrics_json.read_text(encoding="utf-8")),
                      capture_resolution(args.capture_dir))
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
