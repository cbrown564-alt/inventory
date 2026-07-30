#!/usr/bin/env python3
"""Apply a dual-review retry Pass A report.

Accepted second attempts become ``pass_a_accepted``. Rejected second attempts
are archived and become terminal ``generator_failed`` records. Escalations
must be resolved by an explicit owner adjudication before application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.apply_owner_adjudications import (
    _csv_bytes,
    _load_json,
    _load_tasks,
    _provider_id,
    _replace_files,
)
from evals.synthetic.build_tasks import DEFAULT_DATASET


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _owner_map(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    entries = payload.get("decisions") or []
    if isinstance(entries, dict):
        entries = list(entries.values())
    result = {}
    for entry in entries:
        task_id = entry["task_id"]
        if entry.get("owner_decision") not in {"accept", "reject"}:
            raise ValueError(f"{task_id}: unsupported owner retry decision")
        result[task_id] = entry
    return result


def _evidence_visibility(item: dict[str, Any], evidence_name: str) -> str:
    """Return the narrowest supported visibility from both blind reviews."""

    observations = []
    for review_key in ("first_review", "second_review"):
        requested = item.get(review_key, {}).get("requested_evidence") or []
        for evidence in requested:
            if str(evidence.get("name", "")).casefold() == evidence_name.casefold():
                visibility = evidence.get("visibility")
                if visibility == "malformed":
                    visibility = "ambiguous"
                if visibility in {"clear", "ambiguous", "absent"}:
                    observations.append(visibility)
                break
    if not observations:
        return "ambiguous"
    if len(set(observations)) == 1:
        return observations[0]
    return "ambiguous"


def apply(
    dataset_dir: Path,
    report_path: Path,
    adjudication_path: Path | None = None,
    output_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    report = _load_json(report_path)
    owner_payload = _load_json(adjudication_path) if adjudication_path else None
    owner = _owner_map(owner_payload)
    frames = report.get("frames") or []
    rows = _load_tasks(dataset_dir)
    by_id = {row["task_id"]: row for row in rows}
    decisions = []
    unresolved = []
    for frame in frames:
        task_id = frame["task_id"]
        if task_id not in by_id:
            raise ValueError(f"unknown task: {task_id}")
        decision = frame["pass_a_decision"]
        adjudication = owner.get(task_id)
        if decision == "escalate":
            if adjudication is None:
                unresolved.append(task_id)
                continue
            decision = adjudication["owner_decision"]
        decisions.append(
            {
                **frame,
                "final_decision": decision,
                "owner_adjudication": adjudication,
            }
        )
    counts = Counter(item["final_decision"] for item in decisions)
    summary = {
        "counts": dict(sorted(counts.items())),
        "unresolved": sorted(unresolved),
        "terminal_moves": [],
    }
    if dry_run or unresolved:
        return summary

    by_packet: dict[tuple[str, str], list[dict[str, Any]]] = {}
    moves: list[tuple[Path, Path]] = []
    manifest_entries = []
    for item in decisions:
        row = by_id[item["task_id"]]
        if row["status"] != "review_pending" or int(row.get("attempts") or 0) != 2:
            raise ValueError(
                f"{item['task_id']}: expected review_pending second attempt"
            )
        path = dataset_dir / row["output_path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        digest = _sha256(path)
        if row.get("output_sha256") != digest:
            raise ValueError(f"{item['task_id']}: retry image hash mismatch")
        key = (row["scenario_id"], _provider_id(row["task_id"]))
        by_packet.setdefault(key, []).append(item)
        if item["final_decision"] == "accept":
            row["status"] = "pass_a_accepted"
            continue
        destination = (
            dataset_dir
            / "rejected"
            / f"{item['task_id']}-attempt-2{path.suffix.lower()}"
        )
        if destination.exists():
            raise FileExistsError(destination)
        moves.append((path, destination))
        row["status"] = "generator_failed"
        manifest_entries.append(
            {
                "task_id": item["task_id"],
                "attempt": 2,
                "output_path": destination.relative_to(dataset_dir).as_posix(),
                "sha256": digest,
                "rejected_at": _utc_now(),
                "operator": "Independent AI retry Pass A",
                "reasons": [item.get("pass_a_reason") or "retry rejected"],
                "terminal": True,
                "source_review": report_path.name,
            }
        )

    review_updates: dict[Path, bytes] = {}
    for (scenario_id, provider_id), packet_items in by_packet.items():
        path = dataset_dir / "reviews" / f"{scenario_id}.{provider_id}.json"
        review = _load_json(path)
        by_view = {item["view_id"]: item for item in packet_items}
        for frame in review["pass_a"]["frames"]:
            item = by_view.get(frame["frame_id"])
            if item is None:
                continue
            decision = item["final_decision"]
            frame["decision"] = "accepted" if decision == "accept" else "rejected"
            frame["rejection_reasons"] = (
                [] if decision == "accept" else [item["pass_a_reason"]]
            )
            frame["retry_review"] = {
                "attempt": 2,
                "source": report_path.name,
                "image_sha256": item["image_sha256"],
                "reviewer_model_mode": report["reviewer_model_mode"],
                "cli_version": report["cli_version"],
                "first_review": item["first_review"],
                "second_review": item["second_review"],
                "reconciled_decision": item["pass_a_decision"],
                "owner_adjudication": item["owner_adjudication"],
            }
            for evidence in frame.get("requested_evidence", []):
                evidence["visibility"] = _evidence_visibility(
                    item, evidence.get("name", "")
                )
        review["pass_a"]["completed_at"] = report["reviewed_at"]
        review["pass_a"]["reviewer"] = (
            "Two independent Antigravity CLI Pass A contexts"
        )
        review["pass_a"]["review_prompt_sha256"] = sorted(
            {
                call["first_prompt_sha256"]
                for call in report["calls"]
                if item_id_in_call(packet_items, call)
            }
            | {
                call["second_prompt_sha256"]
                for call in report["calls"]
                if item_id_in_call(packet_items, call)
            }
        )
        review["review_status"] = "provisional"
        review_updates[path] = (
            json.dumps(review, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")

    record_path = output_path or (
        dataset_dir
        / "reports"
        / f"retry-pass-a-applied-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    )
    record = {
        "review_type": "retry_pass_a_application",
        "source_review": report_path.name,
        "source_adjudications": adjudication_path.name if adjudication_path else None,
        "applied_at": _utc_now(),
        **summary,
        "decisions": decisions,
    }
    contents = {
        **review_updates,
        dataset_dir / "tasks.csv": _csv_bytes(rows),
        record_path: (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    }
    if manifest_entries:
        manifest_path = dataset_dir / "rejected" / "manifest.jsonl"
        previous = manifest_path.read_text(encoding="utf-8")
        contents[manifest_path] = (
            previous
            + "".join(
                json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n"
                for entry in manifest_entries
            )
        ).encode("utf-8")

    completed_moves = []
    try:
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, destination)
            completed_moves.append((source, destination))
        _replace_files(contents)
    except Exception:
        for source, destination in reversed(completed_moves):
            if destination.exists() and not source.exists():
                shutil.move(destination, source)
        raise
    summary["terminal_moves"] = [
        destination.relative_to(dataset_dir).as_posix() for _, destination in moves
    ]
    summary["record"] = str(record_path)
    return summary


def item_id_in_call(
    packet_items: list[dict[str, Any]],
    call: dict[str, Any],
) -> bool:
    packet_ids = {item["task_id"] for item in packet_items}
    return bool(packet_ids & set(call["task_ids"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = apply(
        args.dataset_dir,
        args.report,
        args.adjudications,
        args.output,
        args.dry_run,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
