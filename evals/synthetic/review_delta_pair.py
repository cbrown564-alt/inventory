#!/usr/bin/env python3
"""Run two independent subscription-backed reviews of Phase 3.5 delta pairs.

The reviewer sees the accepted T0 frame and the generated T1 frame side by
side and answers three questions per pair: is this the same room, is each
enumerated change visible, and — the one that decides the phase — what
material differences are present that nobody enumerated.

Any unenumerated material difference rejects the pair. Reviews read local
images through Antigravity CLI and never call an image or vision API endpoint.
The second reviewer receives the same evidence and never the first reviewer's
conclusion.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_delta_tasks import DELTA_VIEWS, load_specs
from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.review_pass_a import MODEL_MODE, _extract_json, _invoke
from evals.synthetic.run_eval import _cli_version, _resolve_cli

VALID_DECISIONS = {"accept", "reject", "escalate"}
VALID_VISIBILITY = {"clear", "ambiguous", "absent"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_rows(dataset_dir: Path) -> list[dict[str, str]]:
    path = dataset_dir / "delta_tasks.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist; run build_delta_tasks first")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def review_inputs(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """One review input per *pair*, carrying both views of both timepoints."""
    rows = _load_rows(dataset_dir)
    specs = {spec["id"]: spec for spec, _ in load_specs(dataset_dir, delta_ids)}
    by_delta: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if delta_ids is not None and row["delta_id"] not in delta_ids:
            continue
        if row["status"] != "review_pending":
            continue
        by_delta.setdefault(row["delta_id"], []).append(row)

    inputs: list[dict[str, Any]] = []
    for delta_id, packet in sorted(by_delta.items()):
        spec = specs.get(delta_id)
        if spec is None:
            raise ValueError(f"{delta_id}: no delta specification found")
        if {row["view_id"] for row in packet} != set(DELTA_VIEWS):
            raise ValueError(
                f"{delta_id}: a pair review needs every view in {list(DELTA_VIEWS)}"
            )
        views = []
        for row in sorted(packet, key=lambda item: item["view_id"]):
            t1_path = dataset_dir / row["output_path"]
            t0_path = dataset_dir / row["reference_path"]
            for path in (t0_path, t1_path):
                if not path.is_file():
                    raise FileNotFoundError(path)
            views.append({
                "view_id": row["view_id"],
                "t0_image_path": str(t0_path.resolve()),
                "t1_image_path": str(t1_path.resolve()),
                "t1_image_sha256": row["output_sha256"],
            })
        inputs.append({
            "delta_id": delta_id,
            "delta_class": spec["delta_class"],
            "room_type": packet[0]["room_type"],
            "views": views,
            "enumerated_changes": [
                {
                    "id": change["id"],
                    "kind": change["kind"],
                    "target": change["target"],
                    "description": change["description"],
                    "material": change["material"],
                }
                for change in spec["changes"]
            ],
            "unchanged_assertions": spec["unchanged_assertions"],
        })
    return inputs


def _prompt(inputs: list[dict[str, Any]], reviewer_id: str) -> str:
    return (
        "Act only as an independent reviewer of before/after room image pairs "
        "for a bounded synthetic property evaluation. Do not edit any file. "
        "Use the local image-reading tool to inspect every t0_image_path and "
        "t1_image_path before deciding. The T0 image is accepted ground "
        "evidence; the T1 image is a candidate re-render of the same room.\n\n"
        "For each pair decide three things.\n"
        "1. Same room: is the T1 image the same physical room as T0 — same "
        "layout, fittings, finishes and viewpoint? A different room, a "
        "re-imagined layout or a changed camera position is a hard failure.\n"
        "2. Enumerated changes: for each listed change, is it visible in T1 "
        "and absent in T0 as described?\n"
        "3. Unenumerated changes: list EVERY material difference you can see "
        "between T0 and T1 that is not in the enumerated list — new or moved "
        "objects, altered fittings, changed flooring or finishes, new marks or "
        "defects, removed items. This is the most important field. Report a "
        "difference even when it looks minor or incidental. Do not explain it "
        "away because the enumerated changes are present.\n\n"
        "Reject when the room identity fails, when any unenumerated material "
        "difference is present, or when a change listed as material is not "
        "visible. Escalate genuine visual uncertainty. Ignore pure image-noise "
        "differences such as compression grain.\n\n"
        "Return only a JSON array, one object per pair, with exactly: "
        "delta_id, decision (accept|reject|escalate), same_room (boolean), "
        "same_room_notes, enumerated [{change_id, visibility(clear|ambiguous|"
        "absent), notes}], unenumerated_changes [{target, description, "
        "material(boolean)}], reason. Do not wrap the JSON in Markdown. "
        f"Reviewer context: {reviewer_id}.\n\n"
        + json.dumps(inputs, ensure_ascii=False, indent=2)
    )


def _validate_review(
    expected: list[dict[str, Any]],
    review: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected_ids = {item["delta_id"] for item in expected}
    by_id = {item.get("delta_id"): item for item in review}
    if len(by_id) != len(review):
        raise ValueError("delta reviewer returned duplicate delta IDs")
    if set(by_id) != expected_ids:
        raise ValueError(
            f"review pair mismatch: missing={sorted(expected_ids - set(by_id))}, "
            f"extra={sorted(set(by_id) - expected_ids)}"
        )
    expected_changes = {
        item["delta_id"]: {change["id"] for change in item["enumerated_changes"]}
        for item in expected
    }
    for delta_id, item in by_id.items():
        if item.get("decision") not in VALID_DECISIONS:
            raise ValueError(f"{delta_id}: invalid decision")
        if not isinstance(item.get("same_room"), bool):
            raise ValueError(f"{delta_id}: same_room must be a boolean")
        enumerated = item.get("enumerated")
        if not isinstance(enumerated, list):
            raise ValueError(f"{delta_id}: enumerated is not a list")
        reported = {entry.get("change_id") for entry in enumerated}
        if reported != expected_changes[delta_id]:
            raise ValueError(
                f"{delta_id}: enumerated change IDs do not match the specification"
            )
        for entry in enumerated:
            if entry.get("visibility") not in VALID_VISIBILITY:
                raise ValueError(
                    f"{delta_id}.{entry.get('change_id')}: invalid visibility"
                )
        if not isinstance(item.get("unenumerated_changes"), list):
            raise ValueError(f"{delta_id}: unenumerated_changes is not a list")
    return by_id


def _material_drift(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        change
        for change in entry.get("unenumerated_changes", [])
        if change.get("material") is not False
    ]


def combine(
    expected: dict[str, Any],
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    """Merge two independent reviews into one conservative pair outcome.

    Agreement on accept is the only path to accept. Either reviewer seeing
    material drift, or the two disagreeing at all, sends the pair to the
    owner — a delta set that cannot hold identity must fail loudly.
    """
    drift = _material_drift(first) + _material_drift(second)
    missing_material = sorted(
        {
            entry["change_id"]
            for review in (first, second)
            for entry in review["enumerated"]
            if entry["visibility"] == "absent"
            and any(
                change["id"] == entry["change_id"] and change["material"]
                for change in expected["enumerated_changes"]
            )
        }
    )
    agreed = first["decision"] == second["decision"]
    if not (first["same_room"] and second["same_room"]):
        decision = "reject"
        basis = "room identity failed"
    elif drift:
        decision = "reject"
        basis = "unenumerated material change observed"
    elif missing_material:
        decision = "reject"
        basis = f"material change not visible: {', '.join(missing_material)}"
    elif agreed and first["decision"] == "accept":
        decision = "accept"
        basis = "both reviewers accepted"
    elif agreed:
        decision = first["decision"]
        basis = "both reviewers agreed"
    else:
        decision = "escalate"
        basis = (
            f"reviewers disagreed ({first['decision']} vs {second['decision']})"
        )
    return {
        "delta_id": expected["delta_id"],
        "delta_class": expected["delta_class"],
        "decision": decision,
        "decision_basis": basis,
        "reviewers_agreed": agreed,
        "unenumerated_material_changes": drift,
        "missing_material_changes": missing_material,
        "first_review": first,
        "second_review": second,
    }


def review(
    dataset_dir: Path,
    output_path: Path,
    delta_ids: set[str] | None = None,
    cli_path: Path | None = None,
    model: str = MODEL_MODE,
    batch_size: int = 1,
    timeout: int = 480,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    cli = _resolve_cli(cli_path)
    cli_version = _cli_version(cli)
    inputs = review_inputs(dataset_dir, delta_ids)
    if not inputs:
        raise ValueError("no delta pairs are ready for review")
    pairs: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    started_at = _utc_now()
    if output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        if previous.get("status") != "partial":
            raise FileExistsError(
                f"refusing to overwrite completed review: {output_path}"
            )
        if previous.get("reviewer_model_mode") != model:
            raise ValueError("partial review uses a different reviewer model")
        pairs = list(previous.get("pairs") or [])
        calls = list(previous.get("calls") or [])
        started_at = previous.get("reviewed_at") or started_at
    completed = [pair["delta_id"] for pair in pairs]
    if len(set(completed)) != len(completed):
        raise ValueError("partial delta review contains duplicate pairs")
    remaining = [item for item in inputs if item["delta_id"] not in set(completed)]

    def write_report(status: str) -> dict[str, Any]:
        counts = Counter(pair["decision"] for pair in pairs)
        report = {
            "review_type": "phase35_delta_pair_review",
            "status": status,
            "reviewed_at": started_at,
            "completed_at": _utc_now() if status == "complete" else None,
            "generation_path": "Antigravity CLI independent local-image review",
            "metered_api_call": False,
            "cli_version": cli_version,
            "reviewer_model_mode": model,
            "counts": dict(sorted(counts.items())),
            "pairs": pairs,
            "calls": calls,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)
        return report

    for offset in range(0, len(remaining), batch_size):
        batch = remaining[offset : offset + batch_size]
        batch_number = len(calls) + 1
        print(
            f"Delta review batch {batch_number}: first review "
            f"({len(batch)} pair(s))",
            flush=True,
        )
        first_prompt = _prompt(batch, f"first-{batch_number}")
        second_prompt = _prompt(batch, f"second-{batch_number}")
        first, first_wrapper, first_elapsed = _invoke(
            cli, model, first_prompt, timeout, dataset_dir
        )
        print(f"Delta review batch {batch_number}: second review", flush=True)
        second, second_wrapper, second_elapsed = _invoke(
            cli, model, second_prompt, timeout, dataset_dir
        )
        first_by_id = _validate_review(batch, first)
        second_by_id = _validate_review(batch, second)
        calls.append({
            "batch": batch_number,
            "delta_ids": [item["delta_id"] for item in batch],
            "first_prompt_sha256": _sha256_text(first_prompt),
            "second_prompt_sha256": _sha256_text(second_prompt),
            "first_latency_seconds": first_elapsed,
            "second_latency_seconds": second_elapsed,
            "first_wrapper": first_wrapper,
            "second_wrapper": second_wrapper,
        })
        for item in batch:
            pairs.append(
                combine(
                    item,
                    first_by_id[item["delta_id"]],
                    second_by_id[item["delta_id"]],
                )
            )
        write_report("partial")
    return write_report("complete")


def probe_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the docs/31 Phase 3.5 probe gate to a completed review.

    Pass needs at least two of three probe scenarios accepted with zero
    unenumerated material changes. The gate is deliberately not retryable at
    a looser bar.
    """
    pairs = report.get("pairs", [])
    accepted = [pair for pair in pairs if pair["decision"] == "accept"]
    drifted = [pair for pair in pairs if pair["unenumerated_material_changes"]]
    passed = len(accepted) >= 2 and not any(
        pair["unenumerated_material_changes"] for pair in accepted
    )
    return {
        "pairs_reviewed": len(pairs),
        "accepted": len(accepted),
        "pairs_with_unenumerated_material_change": len(drifted),
        "probe_passed": passed,
        "verdict": (
            "Probe passed — proceed to the Phase 3.5 pilot."
            if passed
            else "Probe failed — record the drift modes and abandon the "
            "extension. Do not retry at a looser bar (docs/31)."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delta", action="append", dest="deltas")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list eligible pairs without invoking Antigravity",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="print the Phase 3.5 probe verdict for a completed review",
    )
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--model", default=MODEL_MODE)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    delta_ids = set(args.deltas) if args.deltas else None
    if args.probe:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        print(json.dumps(probe_verdict(report), indent=2))
        return 0
    if args.dry_run:
        inputs = review_inputs(args.dataset_dir, delta_ids)
        print(json.dumps({
            "review_type": "phase35_delta_pair_preflight",
            "count": len(inputs),
            "pairs": [
                {
                    "delta_id": item["delta_id"],
                    "delta_class": item["delta_class"],
                    "views": [view["view_id"] for view in item["views"]],
                    "enumerated_changes": len(item["enumerated_changes"]),
                }
                for item in inputs
            ],
        }, indent=2))
        return 0
    report = review(
        args.dataset_dir,
        args.output,
        delta_ids,
        args.cli,
        args.model,
        args.batch_size,
        args.timeout,
    )
    print(json.dumps(report["counts"], indent=2))
    print(json.dumps(probe_verdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
