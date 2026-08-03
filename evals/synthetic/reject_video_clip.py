#!/usr/bin/env python3
"""Reject a generated clip and leave its task ready for retry.

The image-arm equivalent is ``reject_output.py``, which archives the rejected
artefact before writing the manifest entry. That guarantee does not hold on the
video surface: clips are watched in the browser on the subscription surface and
a bad take is often discarded there without ever being downloaded, so the
common case is a rejection with no artefact to archive.

Discarding the file is allowed; discarding the *attempt* is not. The attempt
consumed a slot from the ten-clip daily ceiling, and a rejected rung is a
finding about the generator rather than an absence of data. So this records the
rejection either way and marks ``artifact_retained`` so a later reader can tell
"we looked and it was bad" from "we still have the evidence".
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from evals.synthetic.build_video_tasks import DEFAULT_DATASET, FIELDNAMES


def reject(dataset_dir: Path, task_id: str, reasons: list[str],
           terminal: bool = False, operator: str | None = None) -> dict[str, object]:
    task_path = dataset_dir / "video" / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    row = next((candidate for candidate in rows if candidate["task_id"] == task_id), None)
    if row is None:
        raise ValueError(f"unknown task: {task_id}")
    if operator:
        row["operator"] = operator
    attempt = max(1, int(row.get("attempts") or 1))

    source = dataset_dir / row["output_path"]
    entry: dict[str, object] = {
        "task_id": task_id,
        "attempt": attempt,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "operator": row.get("operator"),
        "reasons": reasons,
        "terminal": terminal,
        "artifact_retained": source.is_file(),
    }
    if source.is_file():
        destination = (dataset_dir / "video" / "rejected"
                       / f"{task_id}-attempt-{attempt}{source.suffix.lower()}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError(f"rejected artifact already exists: {destination}")
        entry["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.move(source, destination)
        entry["output_path"] = destination.relative_to(dataset_dir).as_posix()

    manifest = dataset_dir / "video" / "rejected" / "manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")

    row["status"] = "generator_failed" if terminal else "retry_pending"
    row["attempts"] = str(attempt)
    for field in ("generated_at", "duration_s", "output_sha256"):
        row[field] = ""
    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("reason", nargs="+")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--terminal", action="store_true",
                        help="record the stopping-rule failure instead of preparing another retry")
    parser.add_argument("--operator")
    args = parser.parse_args()
    entry = reject(args.dataset_dir, args.task_id, args.reason,
                   args.terminal, args.operator)
    print(json.dumps(entry, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
