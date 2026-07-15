#!/usr/bin/env python3
"""Archive a rejected generation and leave its task ready for retry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES


def reject(dataset_dir: Path, task_id: str, reasons: list[str], terminal: bool = False) -> Path:
    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = next((candidate for candidate in rows if candidate["task_id"] == task_id), None)
    if row is None:
        raise ValueError(f"unknown task: {task_id}")
    source = dataset_dir / row["output_path"]
    if not source.is_file():
        raise ValueError(f"missing output for {task_id}")
    attempt = int(row.get("attempts") or 1)
    destination = dataset_dir / "rejected" / f"{task_id}-attempt-{attempt}{source.suffix.lower()}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"rejected artifact already exists: {destination}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.move(source, destination)
    entry = {
        "task_id": task_id,
        "attempt": attempt,
        "output_path": destination.relative_to(dataset_dir).as_posix(),
        "sha256": digest,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "operator": row.get("operator"),
        "reasons": reasons,
    }
    with (dataset_dir / "rejected/manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    row["status"] = "generator_failed" if terminal else "retry_pending"
    for field in ("generated_at", "generator_cli_version", "output_sha256"):
        row[field] = ""
    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("reason", nargs="+")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--terminal", action="store_true",
                        help="record the stopping-rule failure instead of preparing another retry")
    args = parser.parse_args()
    destination = reject(args.dataset_dir, args.task_id, args.reason, args.terminal)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
