#!/usr/bin/env python3
"""Apply the Gemini Omni Pass A import review to the ledger.

``apply_retry_pass_a.py`` cannot be reused, and the reason is semantic rather
than structural. That tool applies a *retry*: a rejected second attempt is a
generation that failed twice, so it archives the file and writes a terminal
``generator_failed``. Nothing here is a retry. These are candidates that
already existed being screened for the first time, and Google generation is
retired, so a rejected candidate is not a generation to fail — it is a
candidate excluded from the slice. It becomes ``pass_a_rejected`` and its file
stays exactly where the staging reports say it is.

Escalations become ``owner_review_pending``. Under docs/31 an escalation is the
one thing owner review is actually *for*, and the whole point of this import is
that owner review alone was never the recorded protocol.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES

PROVIDER_ID = "gemini-omni"

STATUS = {
    "accept": "pass_a_accepted",
    "reject": "pass_a_rejected",
    "escalate": "owner_review_pending",
}


def apply(dataset_dir: Path, review_path: Path) -> dict[str, Any]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("status") != "complete":
        raise ValueError(
            f"{review_path.name} is {review.get('status')!r}; a partial review "
            "cannot be applied"
        )
    decisions = {frame["task_id"]: frame for frame in review["frames"]}

    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["task_id"]: row for row in rows}

    unknown = set(decisions) - set(by_id)
    if unknown:
        raise ValueError(f"review names tasks not in the ledger: {sorted(unknown)}")
    foreign = [task_id for task_id in decisions
               if task_id.split(".")[1] != PROVIDER_ID]
    if foreign:
        raise ValueError(
            f"review covers non-{PROVIDER_ID} tasks: {sorted(foreign)}"
        )

    for task_id, frame in decisions.items():
        row = by_id[task_id]
        if frame.get("image_sha256") and row["output_sha256"] != frame["image_sha256"]:
            raise ValueError(
                f"{task_id}: the image changed after it was reviewed; the "
                "review does not describe the file now in the ledger"
            )
        row["status"] = STATUS[frame["pass_a_decision"]]

    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(STATUS[frame["pass_a_decision"]]
                     for frame in decisions.values())
    return {
        "applied": len(decisions),
        "counts": dict(sorted(counts.items())),
        "review": review_path.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    print(json.dumps(apply(args.dataset_dir, args.review), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
