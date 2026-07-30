#!/usr/bin/env python3
"""Fail-closed native-resolution InventoryFlex v1 quality gate."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from PIL import Image

try:
    from benchmarks.native_fixture import audit_fixture
except ModuleNotFoundError:  # direct ``python benchmarks/quality_gate.py``
    from native_fixture import audit_fixture

TARGETS = {"notable_recall": 0.90, "hallucination": 0.05,
           "defect_recall": 0.75}
MIN_NATIVE_MEGAPIXELS = 8.0
REQUIRED_EVIDENCE_CHECKS = (
    "two_external_properties",
    "source_authority_recorded",
    "independently_annotated",
    "notable_fact_denominator",
    "material_defect_denominator",
    "clean_negative_controls",
    "ambiguous_near_negatives",
    "property_capture_dirs",
    "fixture_frozen",
    "image_manifest_complete",
    "capture_dir_matches_fixture",
)


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


def evaluate(
    metrics: dict,
    resolution: dict,
    evidence: dict | None = None,
) -> dict:
    def metric(name: str, failure_value: float) -> float:
        try:
            value = float(metrics.get(name, failure_value))
        except (TypeError, ValueError):
            return failure_value
        return value

    supplied_evidence = dict((evidence or {}).get("checks") or {})
    evidence_checks = {
        name: bool(supplied_evidence.get(name))
        for name in REQUIRED_EVIDENCE_CHECKS
    }
    checks = {
        **evidence_checks,
        "all_fixture_images_decodable": (
            int(resolution.get("images") or 0)
            == int(((evidence or {}).get("counts") or {}).get("images") or -1)
        ),
        "native_resolution": bool(resolution.get("native_resolution")),
        "notable_recall": metric("notable_recall", -1)
        >= TARGETS["notable_recall"],
        "hallucination": metric("hallucination", 2)
        <= TARGETS["hallucination"],
        "defect_recall": metric("defect_recall", -1)
        >= TARGETS["defect_recall"],
    }
    return {"pass": all(checks.values()), "checks": checks,
            "targets": TARGETS, "resolution": resolution,
            "metrics": metrics, "evidence": evidence}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("metrics_json", type=Path,
                        help="JSON with notable_recall, hallucination, defect_recall as 0..1")
    parser.add_argument(
        "--fixture-manifest",
        type=Path,
        required=True,
        help="frozen external fixture.json with independent annotations",
    )
    parser.add_argument("-o", "--out", type=Path)
    args = parser.parse_args(argv)
    manifest = json.loads(args.fixture_manifest.read_text(encoding="utf-8"))
    fixture_dir = args.fixture_manifest.parent
    evidence = audit_fixture(fixture_dir, manifest)
    evidence["checks"]["capture_dir_matches_fixture"] = (
        args.capture_dir.resolve() == (fixture_dir / "capture").resolve()
    )
    result = evaluate(
        json.loads(args.metrics_json.read_text(encoding="utf-8")),
        capture_resolution(args.capture_dir),
        evidence,
    )
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
