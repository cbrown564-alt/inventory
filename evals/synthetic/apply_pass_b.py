#!/usr/bin/env python3
"""Apply verified Pass B packets, blocking unresolved escalations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.apply_owner_adjudications import _replace_files
from evals.synthetic.build_tasks import DEFAULT_DATASET


VALID_RESOLUTIONS = {
    "keep_first",
    "remove_claim",
    "replace_claim",
    "remove_negative",
    "replace_negative",
    "resolved_no_label_change",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _owner_map(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    result = {}
    for entry in payload.get("decisions") or []:
        escalation_id = entry["escalation_id"]
        if entry.get("resolution") not in VALID_RESOLUTIONS:
            raise ValueError(f"{escalation_id}: unsupported owner resolution")
        if not entry.get("reason"):
            raise ValueError(f"{escalation_id}: owner reason is required")
        result[escalation_id] = entry
    return result


def _packet_rows(
    rows: list[dict[str, str]],
    packet_id: str,
) -> list[dict[str, str]]:
    scenario_id, provider_id = packet_id.split(".", 1)
    return [
        row
        for row in rows
        if row["scenario_id"] == scenario_id
        and row["task_id"].split(".")[1] == provider_id
    ]


def _resolve_labels(
    packet: dict[str, Any],
    owner: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    first = packet["first_review"]
    claims = [dict(claim) for claim in first["claims"]]
    negatives = [dict(negative) for negative in first["negative_controls"]]
    unresolved = [
        item["escalation_id"]
        for item in packet["escalations"]
        if item["escalation_id"] not in owner
    ]
    if unresolved:
        return claims, negatives, unresolved

    remove_claims: set[int] = set()
    remove_negatives: set[int] = set()
    for escalation in packet["escalations"]:
        decision = owner[escalation["escalation_id"]]
        resolution = decision["resolution"]
        check_id = escalation["escalation_id"].split(":")[-1]
        if check_id.startswith("claim-") and check_id.count("-") == 1:
            index = int(check_id.split("-")[1])
            if resolution == "remove_claim":
                remove_claims.add(index)
            elif resolution == "replace_claim":
                claims[index] = decision["replacement"]
            elif resolution not in {"keep_first", "resolved_no_label_change"}:
                raise ValueError(
                    f"{escalation['escalation_id']}: invalid claim resolution"
                )
        elif check_id.startswith("negative-") and check_id.count("-") == 1:
            index = int(check_id.split("-")[1])
            if resolution == "remove_negative":
                remove_negatives.add(index)
            elif resolution == "replace_negative":
                negatives[index] = decision["replacement"]
            elif resolution not in {"keep_first", "resolved_no_label_change"}:
                raise ValueError(
                    f"{escalation['escalation_id']}: invalid negative resolution"
                )
        elif resolution != "resolved_no_label_change":
            raise ValueError(
                f"{escalation['escalation_id']}: note resolution must not edit labels"
            )
    claims = [
        claim for index, claim in enumerate(claims) if index not in remove_claims
    ]
    negatives = [
        negative
        for index, negative in enumerate(negatives)
        if index not in remove_negatives
    ]
    return claims, negatives, []


def _attach_second_reviews(
    packet: dict[str, Any],
    claims: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
    owner: dict[str, dict[str, Any]],
) -> None:
    original_claims = packet["first_review"]["claims"]
    original_negatives = packet["first_review"]["negative_controls"]
    checks = {item["check_id"]: item for item in packet["required_checks"]}
    outcomes = {
        item["check_id"]: item for item in packet["second_review"]["checks"]
    }
    packet_id = packet["packet_id"]
    for claim in claims:
        try:
            index = next(
                index
                for index, original in enumerate(original_claims)
                if original["canonical_name"] == claim["canonical_name"]
            )
        except StopIteration:
            raise ValueError(
                f"{packet_id}: replacement claim must preserve canonical_name"
            )
        check_id = f"claim-{index}"
        required = check_id in checks
        escalation = f"{packet_id}:{check_id}"
        claim["second_review"] = {
            "required": required,
            "reviewer": (
                "Independent Antigravity CLI Pass B checker"
                if required
                else None
            ),
            "decision": (
                "resolved"
                if escalation in owner
                else "agreed"
                if required and outcomes[check_id]["decision"] == "supported"
                else "pending"
            ),
        }
    for negative in negatives:
        try:
            index = next(
                index
                for index, original in enumerate(original_negatives)
                if original["wording"] == negative["wording"]
            )
        except StopIteration:
            raise ValueError(
                f"{packet_id}: replacement negative must preserve wording"
            )
        check_id = f"negative-{index}"
        escalation = f"{packet_id}:{check_id}"
        negative["second_review"] = {
            "required": True,
            "reviewer": "Independent Antigravity CLI Pass B checker",
            "decision": "resolved" if escalation in owner else "agreed",
        }


def _validate_candidate(
    review: dict[str, Any],
    packet_rows: list[dict[str, str]],
    dataset_dir: Path,
) -> None:
    packet_id = (
        f"{review['scenario_id']}."
        f"{'antigravity-builtin' if review['provider'] == 'Google' else 'gpt-image-2'}"
    )
    if len(packet_rows) != 4:
        raise ValueError(f"{packet_id}: expected four task rows")
    if any(
        row["status"] not in {"accepted", "pass_a_accepted"}
        for row in packet_rows
    ):
        raise ValueError(f"{packet_id}: task status is not Pass A accepted")
    for row in packet_rows:
        path = dataset_dir / row["output_path"]
        if not path.is_file() or _sha256(path) != row["output_sha256"]:
            raise ValueError(f"{row['task_id']}: image provenance mismatch")
        if not all(
            row.get(field)
            for field in (
                "operator",
                "generated_at",
                "generator_cli_version",
                "output_sha256",
            )
        ):
            raise ValueError(f"{row['task_id']}: incomplete provenance")
    frame_ids = {row["view_id"] for row in packet_rows}
    accepted = {
        frame["frame_id"]
        for frame in review["pass_a"]["frames"]
        if frame["decision"] == "accepted"
    }
    if accepted != frame_ids:
        raise ValueError(f"{packet_id}: not all frames are Pass A accepted")

    claims = review["pass_b"]["claims"]
    if not claims:
        raise ValueError(f"{packet_id}: no observed claims")
    names = [claim["canonical_name"].casefold() for claim in claims]
    if len(names) != len(set(names)):
        raise ValueError(f"{packet_id}: duplicate canonical claim names")
    for claim in claims:
        evidence = set(claim.get("evidence_frame_ids") or [])
        if not evidence or not evidence <= frame_ids:
            raise ValueError(
                f"{packet_id}: invalid evidence for {claim['canonical_name']}"
            )
        second = claim.get("second_review") or {}
        if claim.get("defects") and not (
            second.get("required") is True
            and second.get("decision") in {"agreed", "resolved"}
        ):
            raise ValueError(
                f"{packet_id}: unchecked defect on {claim['canonical_name']}"
            )
    ordinary = [claim for claim in claims if not claim.get("defects")]
    checked = [
        claim
        for claim in ordinary
        if claim["second_review"]["required"]
        and claim["second_review"]["decision"] in {"agreed", "resolved"}
    ]
    if len(checked) < math.ceil(len(ordinary) / 4):
        raise ValueError(f"{packet_id}: ordinary second-check sample below 25%")
    negatives = review["pass_b"]["negative_controls"]
    if not negatives:
        raise ValueError(f"{packet_id}: no checked negative controls")
    for negative in negatives:
        evidence = set(negative.get("evidence_frame_ids") or [])
        if not evidence or not evidence <= frame_ids:
            raise ValueError(f"{packet_id}: invalid negative-control evidence")
        if negative["second_review"]["decision"] not in {"agreed", "resolved"}:
            raise ValueError(f"{packet_id}: unchecked negative control")


def apply(
    dataset_dir: Path,
    report_path: Path,
    adjudication_path: Path | None = None,
    output_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    report = _load(report_path)
    if report.get("status") == "partial":
        raise ValueError("Pass B report is partial and cannot be applied")
    owner_payload = _load(adjudication_path) if adjudication_path else None
    owner = _owner_map(owner_payload)
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    updates: dict[Path, bytes] = {}
    applied = []
    unresolved: dict[str, list[str]] = {}
    for packet in report["packets"]:
        packet_id = packet["packet_id"]
        claims, negatives, missing = _resolve_labels(packet, owner)
        if missing:
            unresolved[packet_id] = missing
            continue
        _attach_second_reviews(packet, claims, negatives, owner)
        review_path = dataset_dir / "reviews" / f"{packet_id}.json"
        review = _load(review_path)
        review["pass_b"] = {
            "reviewer": (
                "Independent Antigravity CLI observed-evidence review with "
                "blind second check"
            ),
            "completed_at": report.get("completed_at") or report["reviewed_at"],
            "claims": claims,
            "negative_controls": negatives,
            "generator_deviations": packet["first_review"][
                "generator_deviations"
            ],
            "review_provenance": {
                "source_report": report_path.name,
                "reviewer_model_mode": report["reviewer_model_mode"],
                "cli_version": report["cli_version"],
                "metered_api_call": report["metered_api_call"],
                "prompt_sha256": sorted(
                    {
                        value
                        for call in report["calls"]
                        if packet_id in call["packet_ids"]
                        for value in (
                            call["first_prompt_sha256"],
                            call["second_prompt_sha256"],
                        )
                    }
                ),
                "escalations": packet["escalations"],
                "owner_resolutions": [
                    owner[item["escalation_id"]]
                    for item in packet["escalations"]
                ],
            },
        }
        review["review_status"] = "verified_synthetic_gold"
        _validate_candidate(
            review, _packet_rows(rows, packet_id), dataset_dir
        )
        updates[review_path] = (
            json.dumps(review, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        applied.append(packet_id)

    summary = {
        "counts": dict(
            Counter(
                ["verified_synthetic_gold"] * len(applied)
                + ["unresolved"] * len(unresolved)
            )
        ),
        "applied_packets": applied,
        "unresolved": unresolved,
    }
    if dry_run:
        return summary
    record_path = output_path or (
        dataset_dir
        / "reports"
        / f"pass-b-applied-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    )
    record = {
        "record_type": "pass_b_application",
        "source_report": report_path.name,
        "source_adjudications": adjudication_path.name if adjudication_path else None,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        **summary,
    }
    updates[record_path] = (
        json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    _replace_files(updates)
    summary["record"] = str(record_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--adjudications", type=Path)
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
