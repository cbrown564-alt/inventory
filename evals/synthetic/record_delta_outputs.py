#!/usr/bin/env python3
"""Record provenance for generated Phase 3.5 delta frames.

This is the step between generation and pair review: ``review_delta_pair``
reads only rows at ``review_pending`` carrying an ``output_sha256``, and
nothing else writes them.

A delta frame carries an integrity risk the main pilot's frames do not. There,
a generator that echoed its reference produced a duplicate that the dataset
duplicate check caught as an obvious failure. Here, a T1 that is a copy of its
own T0 reference is the *ideal-looking* result — perfect room identity, no
unenumerated drift — and it fails only on the enumerated changes being absent,
which reads as an ordinary generator miss. That is the confidently wrong gold
docs/31 rates worse than no gold, so the copy is refused here by hash rather
than left for a reviewer to catch by eye.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_delta_tasks import FIELDNAMES
from evals.synthetic.build_tasks import DEFAULT_DATASET

#: docs/31 Phase 3.5: "≥2 of 3 probe scenarios yield an acceptable pair within
#: 2 attempts each". A third attempt is outside the gate, not a retry.
MAX_PROBE_ATTEMPTS = 2

GENERATION_POLICY = {
    "authorized_path": "Codex built-in imagegen only",
    "image_api_used": False,
    "packet_rule": (
        "T1 generated with the accepted T0 frame of the same view pinned as "
        "the local reference."
    ),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _existing_hashes(dataset_dir: Path, skip: set[Path]) -> dict[str, Path]:
    """Hash every image already in the dataset, so a copy can be named.

    Keyed by digest: the caller only ever asks "has this exact content already
    been saved somewhere else", and the answer is more useful with the path
    that already holds it.
    """
    index: dict[str, Path] = {}
    images = dataset_dir / "images"
    if not images.is_dir():
        return index
    for path in sorted(images.rglob("*")):
        if not path.is_file() or path in skip:
            continue
        index.setdefault(_sha256_file(path), path)
    return index


def record(
    dataset_dir: Path,
    operator: str,
    cli_version: str,
    delta_ids: set[str] | None = None,
) -> dict[str, Any]:
    task_path = dataset_dir / "delta_tasks.csv"
    if not task_path.is_file():
        raise FileNotFoundError(
            f"{task_path} does not exist; run build_delta_tasks first"
        )
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    pending = [
        row
        for row in rows
        if (delta_ids is None or row["delta_id"] in delta_ids)
        and (dataset_dir / row["output_path"]).is_file()
    ]
    outputs = {dataset_dir / row["output_path"] for row in pending}
    index = _existing_hashes(dataset_dir, skip=outputs)

    now = datetime.now(timezone.utc).isoformat()
    recorded: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for row in pending:
        task_id = row["task_id"]
        output = dataset_dir / row["output_path"]
        reference = dataset_dir / row["reference_path"]

        if not reference.is_file():
            raise FileNotFoundError(f"{task_id}: T0 reference {reference} is missing")
        reference_digest = _sha256_file(reference)
        if reference_digest != row["reference_sha256"]:
            raise ValueError(
                f"{task_id}: T0 reference has changed since the queue was built "
                f"({reference.name}). The enumerated gold describes the pinned "
                "frame, so this pair would be scored against a different image."
            )

        digest = _sha256_file(output)
        if row.get("output_sha256") and row["output_sha256"] != digest:
            raise ValueError(
                f"{task_id}: output changed after provenance was recorded"
            )
        if digest == reference_digest:
            raise ValueError(
                f"{task_id}: T1 output is byte-identical to its T0 reference. "
                "The generator returned the reference, so the pair has no "
                "delta. Reject the attempt rather than recording it."
            )
        if digest in seen:
            raise ValueError(
                f"{task_id}: identical content already recorded for "
                f"{seen[digest]}; one render was saved to both paths"
            )
        if digest in index:
            raise ValueError(
                f"{task_id}: output duplicates an existing dataset image "
                f"({index[digest].relative_to(dataset_dir).as_posix()})"
            )
        seen[digest] = task_id

        attempts = int(row.get("attempts") or 0)
        if row["status"] in {"pending", "retry_pending"}:
            attempts += 1
        if attempts > MAX_PROBE_ATTEMPTS:
            raise ValueError(
                f"{task_id}: attempt {attempts} exceeds the {MAX_PROBE_ATTEMPTS}-"
                "attempt probe gate. docs/31 forbids retrying the probe at a "
                "looser bar; record the drift modes and fail the phase instead."
            )

        row["output_sha256"] = digest
        row["attempts"] = str(attempts)
        row["generated_at"] = row.get("generated_at") or now
        row["operator"] = operator
        row["generator_cli_version"] = cli_version
        if row["status"] in {"pending", "retry_pending"}:
            row["status"] = "review_pending"
        recorded.append({
            "task_id": task_id,
            "delta_id": row["delta_id"],
            "parent_scenario_id": row["parent_scenario_id"],
            "view_id": row["view_id"],
            "attempt": attempts,
            "provider": row["provider"],
            "product": row["product"],
            "model_display_name": row["model_display_name"],
            "generation_path": cli_version,
            "metered_api_call": False,
            "operator": operator,
            "generated_at": row["generated_at"],
            "exact_prompt": row["exact_prompt"],
            "prompt_sha256": row["prompt_sha256"],
            "reference_path": row["reference_path"],
            "reference_sha256": reference_digest,
            "output_path": row["output_path"],
            "output_sha256": digest,
        })

    temporary = task_path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(task_path)

    return {
        "schema_version": 1,
        "record_type": "phase35_delta_generation_provenance",
        "recorded_at": now,
        "dataset_id": "synthetic-room-eval",
        "generation_policy": GENERATION_POLICY,
        "generation_count": len(recorded),
        "generations": recorded,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--cli-version", required=True)
    parser.add_argument("--delta", action="append", dest="deltas")
    parser.add_argument(
        "--report",
        type=Path,
        help="write the immutable generation provenance record here",
    )
    args = parser.parse_args()
    delta_ids = set(args.deltas) if args.deltas else None
    report = record(args.dataset_dir, args.operator, args.cli_version, delta_ids)
    if args.report:
        if args.report.exists():
            raise SystemExit(f"refusing to overwrite {args.report}")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(f"Recorded provenance for {report['generation_count']} delta frame(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
