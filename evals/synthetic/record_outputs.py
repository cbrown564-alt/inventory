#!/usr/bin/env python3
"""Record immutable provenance for generated task outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES


def record(dataset_dir: Path, operator: str, cli_version: str) -> int:
    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    count = 0
    for row in rows:
        output = dataset_dir / row["output_path"]
        if not output.is_file():
            continue
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        timestamp = datetime.fromtimestamp(output.stat().st_mtime, timezone.utc).isoformat()
        if row.get("output_sha256") and row["output_sha256"] != digest:
            raise ValueError(f"{row['task_id']}: output changed after provenance was recorded")
        row["output_sha256"] = digest
        row["generated_at"] = row.get("generated_at") or timestamp
        row["operator"] = row.get("operator") or operator
        row["generator_cli_version"] = row.get("generator_cli_version") or cli_version
        if row.get("status") == "retry_pending":
            row["attempts"] = str(int(row.get("attempts") or 0) + 1)
        elif row.get("attempts") in ("", "0"):
            row["attempts"] = "1"
        if row.get("status") in {"pending", "retry_pending"}:
            row["status"] = "review_pending"
        count += 1
    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--cli-version", required=True)
    args = parser.parse_args()
    count = record(args.dataset_dir, args.operator, args.cli_version)
    print(f"Recorded provenance for {count} output(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
