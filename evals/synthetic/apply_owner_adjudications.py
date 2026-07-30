#!/usr/bin/env python3
"""Apply one complete Pass A review with owner adjudications.

The AI review owns clear accepts. Owner adjudications resolve AI rejects and
escalations. Optional protocol corrections preserve, rather than overwrite,
the original owner decision. With ``--prepare-retries``, rejected originals
are archived and their tasks become ``retry_pending``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET, FIELDNAMES


FINAL_FRAME_DECISIONS = {
    "accept": "accepted",
    "reject": "rejected",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_tasks(dataset_dir: Path) -> list[dict[str, str]]:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _provider_id(task_id: str) -> str:
    return task_id.split(".")[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decision_map(payload: dict[str, Any], field: str) -> dict[str, dict[str, Any]]:
    entries = payload.get(field) or []
    if isinstance(entries, dict):
        entries = list(entries.values())
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        task_id = entry.get("task_id")
        if not task_id:
            raise ValueError(f"{field} entry has no task_id")
        if task_id in result:
            raise ValueError(f"duplicate {field} entry: {task_id}")
        result[task_id] = entry
    return result


def build_final_decisions(
    review_payload: dict[str, Any],
    adjudication_payload: dict[str, Any],
    correction_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reconcile every source frame into one inspectable final decision."""
    owner = _decision_map(adjudication_payload, "decisions")
    corrections = _decision_map(correction_payload or {}, "corrections")
    frames = review_payload.get("frames") or []
    if not frames:
        raise ValueError("source review contains no frames")
    frame_ids = {frame["task_id"] for frame in frames}
    unknown_owner = set(owner) - frame_ids
    unknown_corrections = set(corrections) - frame_ids
    if unknown_owner:
        raise ValueError(f"owner decisions not in source review: {sorted(unknown_owner)}")
    if unknown_corrections:
        raise ValueError(
            f"protocol corrections not in source review: {sorted(unknown_corrections)}"
        )

    final = []
    for frame in frames:
        task_id = frame["task_id"]
        ai_decision = frame.get("pass_a_decision")
        if ai_decision not in {"accept", "reject", "escalate"}:
            raise ValueError(f"{task_id}: unsupported AI decision {ai_decision!r}")
        adjudication = owner.get(task_id)
        if ai_decision != "accept" and adjudication is None:
            raise ValueError(f"{task_id}: unresolved AI {ai_decision}")
        if adjudication and adjudication.get("owner_decision") not in {"accept", "reject"}:
            raise ValueError(f"{task_id}: unsupported owner decision")

        decision = "accept" if ai_decision == "accept" else adjudication["owner_decision"]
        source = "ai_accept" if ai_decision == "accept" else "owner_adjudication"
        reason = (
            frame.get("pass_a_reason")
            if ai_decision == "accept"
            else adjudication.get("owner_reason") or adjudication.get("ai_reason")
        )
        correction = corrections.get(task_id)
        if correction:
            corrected = correction.get("final_decision")
            if corrected not in {"accept", "reject"}:
                raise ValueError(f"{task_id}: unsupported protocol correction")
            if correction.get("replaces_decision") not in {None, decision}:
                raise ValueError(f"{task_id}: correction does not match prior decision")
            decision = corrected
            source = "protocol_correction"
            reason = correction.get("reason") or reason

        final.append(
            {
                "task_id": task_id,
                "scenario_id": frame["scenario_id"],
                "provider": frame["provider"],
                "view_id": frame["view_id"],
                "path": frame["path"],
                "ai_decision": ai_decision,
                "ai_reason": frame.get("pass_a_reason") or "",
                "second_review_agreed": frame.get("second_review_agreed"),
                "owner_adjudication": adjudication,
                "protocol_correction": correction,
                "final_decision": decision,
                "final_reason": reason or "",
                "decision_source": source,
            }
        )
    return final


def _updated_review(
    original: dict[str, Any],
    decisions: list[dict[str, Any]],
    source_review: str,
    reviewed_at: str,
) -> dict[str, Any]:
    review = json.loads(json.dumps(original))
    by_view = {item["view_id"]: item for item in decisions}
    frames = review.setdefault("pass_a", {}).setdefault("frames", [])
    for frame in frames:
        decision = by_view.get(frame.get("frame_id"))
        if decision is None:
            continue
        final = decision["final_decision"]
        frame["decision"] = FINAL_FRAME_DECISIONS[final]
        frame["rejection_reasons"] = (
            [] if final == "accept" else [decision["final_reason"]]
        )
        frame["ai_review"] = {
            "source": source_review,
            "reviewed_at": reviewed_at,
            "decision": decision["ai_decision"],
            "reason": decision["ai_reason"],
            "second_review_agreed": decision["second_review_agreed"],
        }
        if decision["owner_adjudication"]:
            frame["owner_adjudication"] = decision["owner_adjudication"]
        if decision["protocol_correction"]:
            frame["protocol_correction"] = decision["protocol_correction"]
        for evidence in frame.get("requested_evidence", []):
            if evidence.get("visibility") == "pending":
                evidence["visibility"] = (
                    "clear" if final == "accept" else "absent"
                )
    pending = any(
        frame.get("decision") in {None, "", "pending", "escalate"}
        for frame in frames
    )
    review["pass_a"]["reviewer"] = "Independent AI review with owner exceptions"
    review["pass_a"]["completed_at"] = reviewed_at
    review["pass_a"]["source_review"] = source_review
    review["pass_a"]["provenance_warning"] = (
        "The source aggregate did not record reviewer model IDs or review-prompt "
        "hashes. This historical Pass A decision set is retained, but does not "
        "satisfy the stronger provenance requirement for retry reviews."
    )
    # Pass A completion alone never promotes a packet beyond provisional.
    review["review_status"] = "provisional"
    return review


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _replace_files(contents: dict[Path, bytes]) -> None:
    """Replace several files and restore their original bytes on failure."""
    originals = {
        path: path.read_bytes() if path.exists() else None for path in contents
    }
    staged: dict[Path, Path] = {}
    try:
        for path, data in contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            staged[path] = Path(name)
        for path, temporary in staged.items():
            temporary.replace(path)
    except Exception:
        for path, data in originals.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def apply(
    dataset_dir: Path,
    review_path: Path,
    adjudication_path: Path,
    correction_path: Path | None = None,
    output_path: Path | None = None,
    prepare_retries: bool = False,
    dry_run: bool = False,
    operator: str = "project owner",
) -> dict[str, Any]:
    review_payload = _load_json(review_path)
    adjudication_payload = _load_json(adjudication_path)
    correction_payload = _load_json(correction_path) if correction_path else None
    decisions = build_final_decisions(
        review_payload, adjudication_payload, correction_payload
    )
    rows = _load_tasks(dataset_dir)
    by_id = {row["task_id"]: row for row in rows}
    unknown = {item["task_id"] for item in decisions} - set(by_id)
    if unknown:
        raise ValueError(f"source review contains unknown tasks: {sorted(unknown)}")

    counts = Counter(item["final_decision"] for item in decisions)
    by_provider: dict[str, Counter] = defaultdict(Counter)
    by_view: dict[str, Counter] = defaultdict(Counter)
    for item in decisions:
        by_provider[item["provider"]][item["final_decision"]] += 1
        by_view[item["view_id"]][item["final_decision"]] += 1
    summary: dict[str, Any] = {
        "counts": dict(sorted(counts.items())),
        "by_provider": {
            key: dict(sorted(value.items())) for key, value in sorted(by_provider.items())
        },
        "by_view": {
            key: dict(sorted(value.items())) for key, value in sorted(by_view.items())
        },
        "protocol_corrections": sum(
            item["protocol_correction"] is not None for item in decisions
        ),
        "retry_moves": [],
    }
    if dry_run:
        return summary

    decisions_by_packet: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in decisions:
        decisions_by_packet[(item["scenario_id"], _provider_id(item["task_id"]))].append(
            item
        )

    review_updates: dict[Path, bytes] = {}
    for (scenario_id, provider_id), packet_decisions in decisions_by_packet.items():
        packet_path = dataset_dir / "reviews" / f"{scenario_id}.{provider_id}.json"
        if not packet_path.is_file():
            raise FileNotFoundError(packet_path)
        updated = _updated_review(
            _load_json(packet_path),
            packet_decisions,
            review_path.name,
            str(review_payload.get("reviewed_at") or ""),
        )
        review_updates[packet_path] = (
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")

    moves: list[tuple[Path, Path]] = []
    manifest_entries = []
    for item in decisions:
        row = by_id[item["task_id"]]
        if item["final_decision"] == "accept":
            row["status"] = "pass_a_accepted"
            continue
        if not prepare_retries:
            continue
        source = dataset_dir / row["output_path"]
        if not source.is_file():
            raise FileNotFoundError(f"rejected source is missing: {source}")
        digest = _sha256(source)
        recorded = row.get("output_sha256")
        if recorded and recorded != digest:
            raise ValueError(f"{item['task_id']}: image hash changed before rejection")
        attempt = max(1, int(row.get("attempts") or 1))
        destination = (
            dataset_dir
            / "rejected"
            / f"{item['task_id']}-attempt-{attempt}{source.suffix.lower()}"
        )
        if destination.exists():
            raise FileExistsError(destination)
        moves.append((source, destination))
        manifest_entries.append(
            {
                "task_id": item["task_id"],
                "attempt": attempt,
                "output_path": destination.relative_to(dataset_dir).as_posix(),
                "sha256": digest,
                "rejected_at": _utc_now(),
                "operator": operator,
                "reasons": [item["final_reason"]],
                "decision_source": item["decision_source"],
            }
        )
        row["status"] = "retry_pending"
        row["operator"] = operator
        for field in ("generated_at", "generator_cli_version", "output_sha256"):
            row[field] = ""

    record_path = output_path or (
        dataset_dir
        / "reports"
        / f"pass-a-final-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    )
    record = {
        "review_type": "phase3_pass_a_final",
        "source_review": review_path.name,
        "source_adjudications": adjudication_path.name,
        "source_protocol_corrections": correction_path.name if correction_path else None,
        "applied_at": _utc_now(),
        "prepare_retries": prepare_retries,
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
        previous = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        appended = "".join(
            json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n"
            for entry in manifest_entries
        )
        contents[manifest_path] = (previous + appended).encode("utf-8")

    completed_moves: list[tuple[Path, Path]] = []
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
    summary["retry_moves"] = [
        destination.relative_to(dataset_dir).as_posix() for _, destination in moves
    ]
    summary["record"] = str(record_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path, help="Complete phase-3 AI review JSON")
    parser.add_argument("adjudications", type=Path, help="Owner adjudication export")
    parser.add_argument("--corrections", type=Path, help="Protocol correction record")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--prepare-retries",
        action="store_true",
        help="Archive rejected originals and set retry_pending",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--operator", default="project owner")
    args = parser.parse_args()
    summary = apply(
        args.dataset_dir,
        args.review,
        args.adjudications,
        args.corrections,
        args.output,
        args.prepare_retries,
        args.dry_run,
        args.operator,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
