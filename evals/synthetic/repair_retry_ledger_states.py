"""Restore retry Pass A task states after a ledger-only metadata rewrite."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES


def repair(dataset_dir: Path, applied: Path) -> None:
    record = json.loads(applied.read_text(encoding="utf-8"))
    decisions = {item["task_id"]: item["final_decision"] for item in record["decisions"]}
    replacements = {
        "RP-019.gpt-image-2.C-inventory",
        "RP-019.gpt-image-2.D-condition",
    }
    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    seen = set()
    for row in rows:
        task_id = row["task_id"]
        if task_id in replacements:
            row["status"] = "review_pending"
            seen.add(task_id)
        elif task_id in decisions:
            row["status"] = (
                "pass_a_accepted" if decisions[task_id] == "accept" else "generator_failed"
            )
            seen.add(task_id)
    expected = set(decisions) | replacements
    if seen != expected:
        raise ValueError(f"retry state mismatch: missing={sorted(expected - seen)}")
    temporary = task_path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(task_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--applied", type=Path, required=True)
    args = parser.parse_args()
    repair(args.dataset_dir, args.applied)
    print("Repaired retry task states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
