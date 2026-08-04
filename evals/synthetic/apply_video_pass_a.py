#!/usr/bin/env python3
"""Write a completed video Pass A review into the ledger.

This deliberately does **not** archive rejected clips or set them up for
retry, which is what the image arm's apply step does. Moving the artefact is
destructive and consumes a slot from a ten-clip daily ceiling, so it stays a
deliberate owner act through ``reject_video_clip.py``. An AI screen writes
``pass_a_rejected`` — a recommendation — and stops there.

The strip hash lands in the ledger here rather than at staging time, because
``video/dataset.json`` ties it to acceptance: "any accepted clip records the
sampled strip's hash alongside the clip hash". A strip hash on an unreviewed
row would claim a review that has not happened.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from evals.synthetic.build_video_tasks import DEFAULT_DATASET, FIELDNAMES

#: Pass A decision -> ledger status.
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
    decisions = {clip["clip_id"]: clip for clip in review["clips"]}

    task_path = dataset_dir / "video" / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    unknown = set(decisions) - {row["clip_id"] for row in rows}
    if unknown:
        raise ValueError(f"review names clips not in the ledger: {sorted(unknown)}")

    applied: list[dict[str, str]] = []
    for row in rows:
        clip = decisions.get(row["clip_id"])
        if clip is None:
            continue
        if row["output_sha256"] != clip["clip_sha256"]:
            raise ValueError(
                f"{row['clip_id']}: the clip changed after it was reviewed; "
                "the review does not describe the staged file"
            )
        row["status"] = STATUS[clip["pass_a_decision"]]
        row["strip_sha256"] = clip["strip_sha256"]
        applied.append({"clip_id": row["clip_id"], "status": row["status"]})

    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return {"review": review_path.name, "applied": applied}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    result = apply(args.dataset_dir, args.review)
    for entry in result["applied"]:
        print(f"{entry['clip_id']:24} -> {entry['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
