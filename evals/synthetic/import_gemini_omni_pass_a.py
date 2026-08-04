#!/usr/bin/env python3
"""Give the Gemini Omni stills ledger rows so they can go through Pass A.

docs/31 Amendment B item 6. Until now these 57 images existed on disk and in
two staging reports but had **zero rows** in ``tasks.csv``. That is why the
view mix-up survived: Pass A is where "is this the view it claims to be" is
caught, and nothing in the pilot's machinery could see these files at all.

The import is deliberately narrow.

**No completeness obligation (B9).** Google generation is retired, so a view
with no candidate is not a gap waiting to be filled. Those rows are written
``not_generated`` — terminal and honest — rather than ``pending``, which would
queue 43 generations that will never run.

**The prompt is a specification, not a transcript.** These images came off the
owner's subscription surface and the prompt actually used was not recorded.
The provider declares ``provenance: candidate_only_prompt_not_recorded`` and
every row carries it, so no later reader can mistake ``exact_prompt`` for what
produced the image.

**Owner review is not a Pass A.** Rows with a candidate are written
``review_pending``, which is the state the normal Pass A path consumes. The
existing owner opinion is not carried in as a decision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES, write_tasks

PROVIDER_ID = "gemini-omni"

#: The staging reports that recorded these files arriving.
STAGING_REPORTS = (
    "gemini-omni-prior-batches-2026-08-03.json",
    "gemini-omni-user-batch-2026-08-03.json",
)


def _staged_at(dataset_dir: Path) -> dict[str, str]:
    """Map an image filename to when it was staged.

    Taken from the staging reports rather than from file mtimes: a rename or a
    checkout rewrites mtimes, and this is the only surviving record of when the
    owner actually produced these.
    """
    staged: dict[str, str] = {}
    for name in STAGING_REPORTS:
        path = dataset_dir / "reports" / name
        if not path.is_file():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        for record in report["records"]:
            staged[Path(record["output_path"]).name] = record["generated_at"]
    return staged


def import_rows(dataset_dir: Path, operator: str) -> dict[str, Any]:
    write_tasks(dataset_dir)  # ensure the provider's rows exist at all
    task_path = dataset_dir / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    staged = _staged_at(dataset_dir)
    imported: list[dict[str, str]] = []
    absent: list[str] = []
    for row in rows:
        if not row["task_id"].endswith(f".{PROVIDER_ID}." + row["view_id"]):
            continue
        if row["status"] not in ("pending", "review_pending", "not_generated"):
            continue  # already adjudicated; the import must not reopen it
        image = dataset_dir / row["output_path"]
        if not image.is_file():
            row["status"] = "not_generated"
            row["attempts"] = "0"
            absent.append(row["task_id"])
            continue
        row["output_sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
        row["generated_at"] = staged.get(image.name, row["generated_at"])
        row["operator"] = operator
        row["attempts"] = "1"
        row["status"] = "review_pending"
        imported.append({"task_id": row["task_id"], "view_id": row["view_id"]})

    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "import": "gemini_omni_pass_a",
        "basis": "docs/31 Amendment B item 6; slice terms in B9",
        "review_pending": len(imported),
        "not_generated": len(absent),
        "note": "not_generated is terminal: Google generation is retired and "
                "this slice carries no completeness obligation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--operator", default="owner (Gemini Omni subscription surface)")
    args = parser.parse_args()
    result = import_rows(args.dataset_dir, args.operator)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
