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


def apply_adjudications(dataset_dir: Path, adjudication_path: Path) -> dict[str, Any]:
    """Resolve ``owner_review_pending`` rows from a gallery export.

    ``apply_owner_adjudications.py`` cannot do this: it writes the owner's
    decision into the packet's Pass B review record at
    ``reviews/<scenario>.<provider>.json``, and this arm has none — it is a
    Pass A bias-check slice, not a labelled packet set. So the decision lands
    on the ledger row and nowhere else.

    Only escalated rows may be resolved. An adjudication that reaches a row the
    reviewers agreed on would be overturning a decision this file never saw
    the evidence for.
    """
    payload = json.loads(adjudication_path.read_text(encoding="utf-8"))
    entries = payload.get("decisions") or []
    if isinstance(entries, dict):
        entries = list(entries.values())

    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["task_id"]: row for row in rows}

    applied: list[dict[str, str]] = []
    for entry in entries:
        task_id = entry["task_id"]
        decision = entry.get("owner_decision")
        if decision not in ("accept", "reject"):
            raise ValueError(f"{task_id}: unsupported owner decision {decision!r}")
        row = by_id.get(task_id)
        if row is None:
            raise ValueError(f"unknown task: {task_id}")
        if task_id.split(".")[1] != PROVIDER_ID:
            raise ValueError(f"{task_id}: not a {PROVIDER_ID} task")
        if row["status"] != "owner_review_pending":
            raise ValueError(
                f"{task_id}: status is {row['status']!r}, not owner_review_pending; "
                "only an escalated row may be resolved by adjudication"
            )
        row["status"] = STATUS[decision]
        applied.append({"task_id": task_id, "status": row["status"]})

    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    remaining = sum(1 for row in rows
                    if row["task_id"].split(".")[1] == PROVIDER_ID
                    and row["status"] == "owner_review_pending")
    return {
        "adjudicated": len(applied),
        "counts": dict(sorted(Counter(e["status"] for e in applied).items())),
        "still_escalated": remaining,
        "source": adjudication_path.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path,
                        help="the Pass A review, or an owner adjudication "
                             "export when --adjudications is passed")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--adjudications", action="store_true",
                        help="treat the file as a gallery export and resolve "
                             "owner_review_pending rows")
    args = parser.parse_args()
    result = (apply_adjudications(args.dataset_dir, args.review)
              if args.adjudications
              else apply(args.dataset_dir, args.review))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
