#!/usr/bin/env python3
"""Audit Google packet integrity separately from generation provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from evals.synthetic.build_tasks import DEFAULT_DATASET


DEFAULT_SCENARIOS = {"RP-009", "RP-012", "RP-018"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_records(dataset_dir: Path, scenario_id: str) -> list[dict[str, Any]]:
    run_dir = dataset_dir / "generation_runs" / "antigravity"
    paths = sorted(run_dir.glob(f"{scenario_id}*.json"))
    records = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("scenario_id") == scenario_id:
            records.append({"path": path, "payload": payload})
    return records


def audit(
    dataset_dir: Path,
    scenario_ids: set[str] = DEFAULT_SCENARIOS,
) -> dict[str, Any]:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    packets = []
    for scenario_id in sorted(scenario_ids):
        # Selected by provider key, not by the provider *name*: "Google" now
        # names two arms — the Antigravity generation this audit is about, and
        # the Gemini Omni bias-check slice, which has no generation run records
        # to audit and would silently double every packet.
        packet_rows = [
            row
            for row in rows
            if row["scenario_id"] == scenario_id
            and row["task_id"].split(".")[1] == "antigravity-builtin"
        ]
        if len(packet_rows) != 4:
            raise ValueError(f"{scenario_id}: expected four Google tasks")
        records = _run_records(dataset_dir, scenario_id)
        successful_hashes = set()
        recovered_hashes = set()
        record_summaries = []
        for record in records:
            payload = record["payload"]
            hashes = {
                output.get("task_id"): output.get("sha256")
                for output in payload.get("outputs") or []
            }
            raw_status = (payload.get("raw_cli_response") or {}).get("status")
            if raw_status == "SUCCESS":
                successful_hashes.update(hashes.values())
            if payload.get("status") == "files_recovered_after_wrapper_error":
                recovered_hashes.update(hashes.values())
            record_summaries.append(
                {
                    "path": record["path"].relative_to(dataset_dir).as_posix(),
                    "status": payload.get("status") or raw_status or "unknown",
                    "has_successful_raw_cli_response": raw_status == "SUCCESS",
                    "output_hashes": hashes,
                }
            )
        outputs = []
        all_integrity = True
        current_hashes = []
        for row in packet_rows:
            path = dataset_dir / row["output_path"]
            if not path.is_file():
                all_integrity = False
                outputs.append(
                    {
                        "task_id": row["task_id"],
                        "path": row["output_path"],
                        "integrity": "missing",
                    }
                )
                continue
            digest = _sha256(path)
            current_hashes.append(digest)
            with Image.open(path) as image:
                image.load()
                image_info = {
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                }
            matches_task = digest == row["output_sha256"]
            valid_image = (
                image_info["format"] == "JPEG"
                and image_info["width"] >= 1024
                and image_info["height"] >= 768
            )
            all_integrity = all_integrity and matches_task and valid_image
            outputs.append(
                {
                    "task_id": row["task_id"],
                    "path": row["output_path"],
                    "sha256": digest,
                    "matches_task_record": matches_task,
                    "prompt_sha256": row["prompt_sha256"],
                    **image_info,
                    "matched_successful_run": digest in successful_hashes,
                    "matched_recovery_ledger": digest in recovered_hashes,
                }
            )
        all_successful = all(
            output.get("matched_successful_run") for output in outputs
        )
        all_recovered = all(
            output.get("matched_recovery_ledger") for output in outputs
        )
        if all_integrity and all_successful:
            provenance_status = "verified"
            reason = "Every current output hash is pinned by a successful raw run."
        elif all_integrity and all_recovered:
            provenance_status = "integrity_only"
            reason = (
                "All files are intact and pinned by a recovery ledger, but no "
                "successful raw generation response proves their origin."
            )
        else:
            provenance_status = "insufficient"
            reason = (
                "Current files pass local integrity checks, but one or more "
                "hashes lack a successful raw generation record."
                if all_integrity
                else "One or more current files fail local integrity checks."
            )
        packets.append(
            {
                "packet_id": f"{scenario_id}.antigravity-builtin",
                "integrity_verified": all_integrity
                and len(current_hashes) == len(set(current_hashes)),
                "generation_provenance_status": provenance_status,
                "pass_b_eligible": provenance_status == "verified",
                "reason": reason,
                "outputs": outputs,
                "generation_records": record_summaries,
            }
        )
    return {
        "schema_version": 1,
        "record_type": "google_generation_provenance_audit",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "rule": (
            "File integrity and task hashes do not substitute for a successful "
            "raw generation record. Integrity-only packets remain provisional."
        ),
        "packets": packets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        args.dataset_dir
        / "reports"
        / "google-generation-provenance-audit-2026-07-30.json"
    )
    report = audit(
        args.dataset_dir,
        set(args.scenarios) if args.scenarios else DEFAULT_SCENARIOS,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for packet in report["packets"]:
        print(
            f"{packet['packet_id']}: "
            f"{packet['generation_provenance_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
