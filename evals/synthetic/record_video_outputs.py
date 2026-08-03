#!/usr/bin/env python3
"""Record immutable provenance for staged video clips.

The image-arm equivalent is ``record_outputs.py``; this cannot reuse it because
the video ledger carries different columns (``duration_s``,
``reference_provenance``, no ``generator_cli_version``) and because a clip's
provenance includes something a still's does not: the take's duration, which is
what a truncated or extended generation shows up as before anyone watches it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evals.synthetic.build_video_tasks import DEFAULT_DATASET, FIELDNAMES


def _duration_s(path: Path) -> str:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return f"{float(json.loads(probe.stdout)['format']['duration']):.3f}"


def record(dataset_dir: Path, operator: str) -> int:
    task_path = dataset_dir / "video" / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    count = 0
    for row in rows:
        output = dataset_dir / row["output_path"]
        if not output.is_file():
            continue
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        if row.get("output_sha256") and row["output_sha256"] != digest:
            raise ValueError(
                f"{row['task_id']}: output changed after provenance was recorded"
            )
        row["output_sha256"] = digest
        row["duration_s"] = row.get("duration_s") or _duration_s(output)
        row["generated_at"] = row.get("generated_at") or datetime.fromtimestamp(
            output.stat().st_mtime, timezone.utc
        ).isoformat()
        if row.get("status") in {"pending", "retry_pending"}:
            row["operator"] = operator
            row["status"] = "review_pending"
        else:
            row["operator"] = row.get("operator") or operator
        if row.get("attempts") in ("", "0"):
            row["attempts"] = "1"
        count += 1
    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    print(f"Recorded provenance for {record(args.dataset_dir, args.operator)} clip(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
