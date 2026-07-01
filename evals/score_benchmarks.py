#!/usr/bin/env python3
"""Score all committed InventoryFlex benchmark runs against gold labels.

Usage:
    python evals/score_benchmarks.py
    python evals/score_benchmarks.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402
from homeinventory.schema import Inventory  # noqa: E402

BENCHMARK_ROOT = ROOT / "benchmarks" / "inventoryflex"
LABELS = ROOT / "evals" / "fixtures" / "inventoryflex" / "labels.json"


def score_all() -> dict[str, dict]:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for inv_path in sorted(BENCHMARK_ROOT.glob("report-*/inventory.json")):
        name = inv_path.parent.name.removeprefix("report-")
        inv = Inventory.from_json(inv_path.read_text(encoding="utf-8"))
        results = run_eval.evaluate(inv, labels)
        out[name] = {k: v for k, v in results.items() if not k.startswith("_")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    scores = score_all()
    if args.json:
        print(json.dumps(scores, indent=2, sort_keys=True))
        return 0

    cols = [
        "item_recall_notable", "hallucination_rate", "naming_accuracy",
        "condition_exact", "condition_within_one", "defect_recall",
    ]
    header = f"{'run':<22}" + "".join(f"{c:>22}" for c in cols)
    print(header)
    print("-" * len(header))
    for name, row in sorted(scores.items()):
        cells = []
        for c in cols:
            v = row.get(c)
            cells.append(f"{v:>22}" if v is not None else f"{'—':>22}")
        print(f"{name:<22}" + "".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
