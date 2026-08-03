"""Record an authorised GPT Image 2 replacement for terminal retry rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES


TARGETS = {
    "RP-019.gpt-image-2.C-inventory",
    "RP-019.gpt-image-2.D-condition",
}
OPERATOR = "Codex GPT Image 2 built-in imagegen"
CLI_VERSION = "Codex built-in imagegen / GPT Image 2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(dataset_dir: Path) -> int:
    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    now = datetime.now(timezone.utc).isoformat()
    found: set[str] = set()
    for row in rows:
        if row["task_id"] not in TARGETS:
            continue
        output = dataset_dir / row["output_path"]
        if not output.is_file():
            raise FileNotFoundError(output)
        found.add(row["task_id"])
        row["output_sha256"] = _sha256(output)
        row["status"] = "review_pending"
        row["attempts"] = "2"
        row["operator"] = OPERATOR
        row["generated_at"] = now
        row["generator_cli_version"] = CLI_VERSION
    if found != TARGETS:
        raise ValueError(f"target mismatch: found={sorted(found)}")
    temporary = task_path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(task_path)
    return len(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    print(f"Recorded {record(args.dataset_dir)} GPT Image 2 replacement outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
