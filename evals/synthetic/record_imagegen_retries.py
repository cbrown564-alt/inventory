#!/usr/bin/env python3
"""Write an inspectable provenance ledger for GPT Image 2 retry outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_ledger(dataset_dir: Path) -> dict[str, Any]:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_id = {row["task_id"]: row for row in rows}
    retries = []
    for row in rows:
        if not (
            row["provider"] == "OpenAI"
            and int(row.get("attempts") or 0) == 2
            and "built-in imagegen" in row.get("operator", "").casefold()
        ):
            continue
        output_path = dataset_dir / row["output_path"]
        if not output_path.is_file():
            raise FileNotFoundError(output_path)
        output_hash = _sha256(output_path)
        if output_hash != row["output_sha256"]:
            raise ValueError(f"{row['task_id']}: output hash mismatch")

        reference_task_id = f"{row['scenario_id']}.gpt-image-2.A-wide"
        reference = by_id.get(reference_task_id)
        if reference is None:
            raise ValueError(f"{row['task_id']}: missing A-wide reference task")
        reference_path = dataset_dir / reference["output_path"]
        if not reference_path.is_file():
            raise FileNotFoundError(reference_path)
        reference_hash = _sha256(reference_path)
        if reference_hash != reference["output_sha256"]:
            raise ValueError(f"{row['task_id']}: reference image hash mismatch")

        retries.append(
            {
                "task_id": row["task_id"],
                "attempt": 2,
                "provider": row["provider"],
                "product": row["product"],
                "model_display_name": row["model_display_name"],
                "generation_path": "Codex built-in imagegen / GPT Image 2",
                "metered_api_call": False,
                "operator": row["operator"],
                "generated_at": row["generated_at"],
                "exact_prompt": row["exact_prompt"],
                "prompt_sha256": row["prompt_sha256"],
                "output_path": row["output_path"],
                "output_sha256": output_hash,
                "reference_image": {
                    "task_id": reference_task_id,
                    "path": reference["output_path"],
                    "sha256": reference_hash,
                    "identity_note": (
                        "The built-in imagegen path exposed a local reference "
                        "image, not a provider reference-image ID."
                    ),
                },
            }
        )
    return {
        "schema_version": 1,
        "record_type": "gpt_image_2_retry_generation_provenance",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": "synthetic-room-eval",
        "generation_policy": {
            "authorized_path": "Codex built-in imagegen only",
            "image_api_used": False,
            "reference_rule": (
                "Every retry used the accepted same-packet OpenAI A-wide "
                "frame as the explicit local reference image."
            ),
        },
        "retry_count": len(retries),
        "retries": retries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        args.dataset_dir / "reports" / "gpt-image-2-retries-2026-07-30.json"
    )
    ledger = build_ledger(args.dataset_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded {ledger['retry_count']} GPT Image 2 retries in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
