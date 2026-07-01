#!/usr/bin/env python3
"""CI regression gate: score reference runs and smoke-test the offline pipeline.

Usage:
    python evals/ci_gate.py
    python evals/ci_gate.py --skip-build     # reference scores only
    python evals/ci_gate.py --thresholds evals/fixtures/thresholds.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402
from homeinventory.cli import main as cli_main  # noqa: E402
from homeinventory.schema import Inventory  # noqa: E402

DEFAULT_THRESHOLDS = ROOT / "evals" / "fixtures" / "thresholds.json"

METRIC_HIGHER_IS_BETTER = {
    "item_recall_all",
    "item_recall_notable",
    "naming_accuracy",
    "condition_exact",
    "condition_within_one",
    "defect_recall",
}
METRIC_LOWER_IS_BETTER = {"hallucination_rate"}


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def check_reference(ref: dict) -> list[str]:
    """Score one reference run; return human-readable failure messages."""
    inv_path = _resolve(ref["inventory"])
    labels_path = _resolve(ref["labels"])
    if not inv_path.is_file():
        return [f"{ref['name']}: missing inventory {inv_path}"]
    if not labels_path.is_file():
        return [f"{ref['name']}: missing labels {labels_path}"]

    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    inv = Inventory.from_json(inv_path.read_text(encoding="utf-8"))
    results = run_eval.evaluate(inv, labels)
    failures: list[str] = []

    for metric, floor in ref.get("floors", {}).items():
        if metric not in METRIC_HIGHER_IS_BETTER:
            continue
        value = results.get(metric)
        if value is None:
            failures.append(f"{ref['name']}: {metric} is null (no pairs to score)")
        elif value < floor:
            failures.append(
                f"{ref['name']}: {metric} {value} < floor {floor}"
            )

    for metric, ceiling in ref.get("ceilings", {}).items():
        if metric not in METRIC_LOWER_IS_BETTER:
            continue
        value = results.get(metric)
        if value is None:
            continue
        if value > ceiling:
            failures.append(
                f"{ref['name']}: {metric} {value} > ceiling {ceiling}"
            )

    if not failures:
        summary = {k: results[k] for k in results if not k.startswith("_")}
        print(f"OK  {ref['name']}: {json.dumps(summary, sort_keys=True)}")
    return failures


def offline_build_smoke() -> list[str]:
    """Run ingest→describe(offline)→report on a synthetic capture; eval must not crash."""
    from PIL import Image

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="homeinventory-ci-") as tmp:
        root = Path(tmp)
        cap = root / "capture" / "Living Room"
        cap.mkdir(parents=True)
        Image.new("RGB", (48, 36), "white").save(cap / "a.jpg")
        out = root / "report"
        rc = cli_main([
            "build", str(root / "capture"), "-o", str(out),
            "--backend", "offline", "--no-detect", "--no-pdf",
        ])
        if rc != 0:
            return [f"offline build smoke: cli exited {rc}"]
        inv_path = out / "inventory.json"
        if not inv_path.is_file():
            return ["offline build smoke: inventory.json not written"]

        inv = Inventory.from_json(inv_path.read_text(encoding="utf-8"))
        labels = {"rooms": {"Living Room": {"items": []}}}
        results = run_eval.evaluate(inv, labels)
        if results["_counts"]["pred_items"] != 0:
            # offline without detector should emit zero items
            n = results["_counts"]["pred_items"]
            failures.append(f"offline build smoke: expected 0 items, got {n}")
        print(f"OK  offline-build-smoke: {results['_counts']['pred_items']} predicted items")
    return failures


def run_gate(thresholds_path: Path, *, skip_build: bool = False) -> int:
    cfg = json.loads(thresholds_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    for ref in cfg.get("references", []):
        failures.extend(check_reference(ref))

    if not skip_build:
        failures.extend(offline_build_smoke())

    if failures:
        print("\nEval CI gate FAILED:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    print("\nEval CI gate passed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    ap.add_argument("--skip-build", action="store_true",
                    help="only score committed reference runs")
    args = ap.parse_args()
    if not args.thresholds.is_file():
        print(f"thresholds file not found: {args.thresholds}", file=sys.stderr)
        return 2
    return run_gate(args.thresholds, skip_build=args.skip_build)


if __name__ == "__main__":
    raise SystemExit(main())
