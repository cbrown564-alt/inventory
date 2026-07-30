#!/usr/bin/env python3
"""Run independent observed-evidence labeling and blind second checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.run_eval import _cli_version, _resolve_cli


MODEL_MODE = "gemini-3.5-flash-low"
VALID_VISIBILITY = {"clear", "partial", "ambiguous", "not_visible"}
VALID_ASSESSMENTS = {"supported", "ambiguous", "not_visible"}
VALID_CHECK_DECISIONS = {"supported", "unsupported", "ambiguous"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
        if not starts:
            raise
        start = min(starts)
        closing = "]" if text[start] == "[" else "}"
        return json.loads(text[start : text.rfind(closing) + 1])


def _load_rows(dataset_dir: Path) -> list[dict[str, str]]:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _provider_id(task_id: str) -> str:
    return task_id.split(".")[1]


def _provenance_blocks(dataset_dir: Path) -> dict[str, str]:
    reports = sorted(
        (dataset_dir / "reports").glob(
            "google-generation-provenance-audit-*.json"
        )
    )
    if not reports:
        return {}
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    return {
        packet["packet_id"]: packet["reason"]
        for packet in payload.get("packets") or []
        if packet.get("pass_b_eligible") is not True
    }


def _packet_inputs(
    dataset_dir: Path,
    packet_ids: set[str] | None,
) -> list[dict[str, Any]]:
    rows = _load_rows(dataset_dir)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    provenance_blocks = _provenance_blocks(dataset_dir)
    for row in rows:
        packet_id = f"{row['scenario_id']}.{_provider_id(row['task_id'])}"
        grouped[packet_id].append(row)
    packets = []
    for packet_id, packet_rows in sorted(grouped.items()):
        scenario_id = packet_rows[0]["scenario_id"]
        if int(scenario_id.split("-")[1]) > 20:
            continue
        if packet_ids is not None and packet_id not in packet_ids:
            continue
        if packet_id in provenance_blocks:
            if packet_ids is not None:
                raise ValueError(
                    f"{packet_id}: Pass B blocked by generation provenance: "
                    f"{provenance_blocks[packet_id]}"
                )
            continue
        if packet_ids is None and not all(
            row["status"] in {"accepted", "pass_a_accepted"}
            for row in packet_rows
        ):
            continue
        if len(packet_rows) != 4:
            raise ValueError(f"{packet_id}: expected four task rows")
        review_path = (
            dataset_dir / "reviews" / f"{packet_id}.json"
        )
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if packet_ids is None and review["review_status"] == "verified_synthetic_gold":
            continue
        accepted_frames = {
            frame["frame_id"]
            for frame in review["pass_a"]["frames"]
            if frame["decision"] == "accepted"
        }
        if accepted_frames != {row["view_id"] for row in packet_rows}:
            raise ValueError(f"{packet_id}: Pass A does not accept all four frames")
        scenario = json.loads(
            (dataset_dir / "scenarios" / f"{scenario_id}.json").read_text(
                encoding="utf-8"
            )
        )
        images = []
        for row in sorted(packet_rows, key=lambda item: item["view_id"]):
            path = dataset_dir / row["output_path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            images.append(
                {
                    "frame_id": row["view_id"],
                    "path": str(path.resolve()),
                    "sha256": row["output_sha256"],
                }
            )
        packets.append(
            {
                "packet_id": packet_id,
                "scenario_id": scenario_id,
                "provider": packet_rows[0]["provider"],
                "room_type": packet_rows[0]["room_type"],
                "images": images,
                "scene_hypotheses": {
                    "views": scenario["views"],
                    "continuity_requirements": scenario[
                        "continuity_requirements"
                    ],
                },
            }
        )
    if packet_ids is not None:
        found = {packet["packet_id"] for packet in packets}
        if found != packet_ids:
            raise ValueError(
                f"packet selection mismatch: missing={sorted(packet_ids - found)}"
            )
    return packets


def _label_prompt(packets: list[dict[str, Any]], context_id: str) -> str:
    return (
        "Act only as the first independent Pass B observed-evidence reviewer "
        "for a synthetic property-room evaluation. Use the local image-reading "
        "tool to inspect all four local images in every packet. The scene "
        "content is a set of hypotheses for locating evidence, never truth. "
        "Label only what the pixels support. Do not infer identity, cause, "
        "working order, hidden damage, or absence outside the visible views. "
        "Use not_visible rather than assumed absence. Keep defect wording "
        "literal, with visible location and restrained severity. Record "
        "conflicting geometry or object continuity.\n\n"
        "Return only a JSON array with one object per packet and exactly: "
        "packet_id; claims [{canonical_name, aliases [string], "
        "evidence_frame_ids [string], visibility "
        "(clear|partial|ambiguous|not_visible), condition (string|null), "
        "defects [{wording, location, severity}]}]; negative_controls "
        "[{wording, evidence_frame_ids [string], assessment "
        "(supported|ambiguous|not_visible)}]; generator_deviations [string]; "
        "ambiguity_notes [string]; continuity_concerns [string]. "
        "A negative control is a specific visually checked non-defect or "
        "near-negative, not a broad claim about unseen space. Do not wrap the "
        f"JSON in Markdown. Independent context: {context_id}.\n\n"
        + json.dumps(packets, ensure_ascii=False, indent=2)
    )


def _ordinary_sample(packet_id: str, claims: list[dict[str, Any]]) -> set[int]:
    by_visibility: dict[str, list[int]] = defaultdict(list)
    for index, claim in enumerate(claims):
        if not claim.get("defects"):
            by_visibility[claim["visibility"]].append(index)
    selected = set()
    for visibility, indexes in sorted(by_visibility.items()):
        ranked = sorted(
            indexes,
            key=lambda index: hashlib.sha256(
                f"{packet_id}:{visibility}:{claims[index]['canonical_name']}".encode()
            ).hexdigest(),
        )
        selected.update(ranked[: math.ceil(len(ranked) / 4)])
    return selected


def _checks(packet: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    ordinary = _ordinary_sample(packet["packet_id"], packet["claims"])
    for index, claim in enumerate(packet["claims"]):
        required = bool(claim.get("defects")) or index in ordinary
        if required:
            checks.append(
                {
                    "check_id": f"claim-{index}",
                    "kind": "defect" if claim.get("defects") else "ordinary",
                    "hypothesis": {
                        "canonical_name": claim["canonical_name"],
                        "aliases": claim["aliases"],
                        "evidence_frame_ids": claim["evidence_frame_ids"],
                        "visibility": claim["visibility"],
                        "condition": claim["condition"],
                        "defects": claim["defects"],
                    },
                }
            )
    for index, negative in enumerate(packet["negative_controls"]):
        checks.append(
            {
                "check_id": f"negative-{index}",
                "kind": "negative",
                "hypothesis": negative,
            }
        )
    return checks


def _check_prompt(
    packets: list[dict[str, Any]],
    first_results: dict[str, dict[str, Any]],
    context_id: str,
) -> str:
    payload = []
    for packet in packets:
        first = first_results[packet["packet_id"]]
        payload.append(
            {
                "packet_id": packet["packet_id"],
                "room_type": packet["room_type"],
                "images": packet["images"],
                "hypotheses_to_check": _checks(first),
            }
        )
    return (
        "Act only as a fresh, independent Pass B checker. Inspect every local "
        "image yourself. You are given hypotheses to test, not another "
        "reviewer's decision, confidence, or reasoning. For each hypothesis, "
        "return supported only when the named item, frame links, visibility, "
        "condition, defect wording/location/severity, or negative-control "
        "assessment are all supported at the stated precision. Return "
        "unsupported for a clear contradiction and ambiguous when pixels do "
        "not decide it. Also report any additional visible material defect, "
        "false negative-control, identity conflict, or continuity problem "
        "that the hypotheses omit.\n\n"
        "Return only a JSON array with one object per packet and exactly: "
        "packet_id; checks [{check_id, decision "
        "(supported|unsupported|ambiguous), reason}]; "
        "additional_material_findings [string]; continuity_concerns [string]. "
        "Do not wrap the JSON in Markdown. Fresh context: "
        f"{context_id}.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _invoke(
    cli: Path,
    model: str,
    prompt: str,
    timeout: int,
    cwd: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    command = [
        str(cli),
        "--sandbox",
        "--dangerously-skip-permissions",
        "--model",
        model,
        "--effort",
        "low",
        "--print-timeout",
        f"{max(1, timeout // 60)}m",
        "--output-format",
        "json",
        "-p",
        prompt,
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout + 30,
    )
    elapsed = round(time.perf_counter() - started, 3)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    wrapper = json.loads(result.stdout)
    if wrapper.get("status") != "SUCCESS":
        raise RuntimeError(str(wrapper))
    wrapper.pop("conversation_id", None)
    parsed = _extract_json(wrapper.get("response"))
    if isinstance(parsed, dict):
        parsed = parsed.get("packets") or parsed.get("reviews")
    if not isinstance(parsed, list):
        raise ValueError("Pass B reviewer did not return a JSON array")
    return parsed, wrapper, elapsed


def _validate_first(
    expected: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected_ids = {packet["packet_id"] for packet in expected}
    by_id = {item.get("packet_id"): item for item in results}
    if len(by_id) != len(results):
        raise ValueError("first Pass B review returned duplicate packet IDs")
    if set(by_id) != expected_ids:
        raise ValueError("first Pass B packet IDs do not match the request")
    frame_ids = {
        packet["packet_id"]: {image["frame_id"] for image in packet["images"]}
        for packet in expected
    }
    for packet_id, item in by_id.items():
        for name in (
            "claims",
            "negative_controls",
            "generator_deviations",
            "ambiguity_notes",
            "continuity_concerns",
        ):
            if not isinstance(item.get(name), list):
                raise ValueError(f"{packet_id}: {name} is not a list")
        for claim in item["claims"]:
            if claim.get("visibility") not in VALID_VISIBILITY:
                raise ValueError(f"{packet_id}: invalid claim visibility")
            if not set(claim.get("evidence_frame_ids") or []) <= frame_ids[packet_id]:
                raise ValueError(f"{packet_id}: claim uses an unknown frame")
        for negative in item["negative_controls"]:
            if negative.get("assessment") not in VALID_ASSESSMENTS:
                raise ValueError(f"{packet_id}: invalid negative assessment")
            if not set(negative.get("evidence_frame_ids") or []) <= frame_ids[packet_id]:
                raise ValueError(f"{packet_id}: negative uses an unknown frame")
    return by_id


def _validate_second(
    expected: list[dict[str, Any]],
    first: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected_ids = {packet["packet_id"] for packet in expected}
    by_id = {item.get("packet_id"): item for item in results}
    if len(by_id) != len(results):
        raise ValueError("second Pass B review returned duplicate packet IDs")
    if set(by_id) != expected_ids:
        raise ValueError("second Pass B packet IDs do not match the request")
    for packet_id, item in by_id.items():
        expected_checks = {check["check_id"] for check in _checks(first[packet_id])}
        actual = {check.get("check_id"): check for check in item.get("checks") or []}
        if set(actual) != expected_checks:
            raise ValueError(f"{packet_id}: second-check IDs do not match")
        if any(
            check.get("decision") not in VALID_CHECK_DECISIONS
            for check in actual.values()
        ):
            raise ValueError(f"{packet_id}: invalid second-check decision")
        for name in ("additional_material_findings", "continuity_concerns"):
            if not isinstance(item.get(name), list):
                raise ValueError(f"{packet_id}: {name} is not a list")
    return by_id


def review(
    dataset_dir: Path,
    output_path: Path,
    packet_ids: set[str] | None = None,
    cli_path: Path | None = None,
    model: str = MODEL_MODE,
    batch_size: int = 2,
    timeout: int = 480,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    cli = _resolve_cli(cli_path)
    cli_version = _cli_version(cli)
    packets = _packet_inputs(dataset_dir, packet_ids)
    if not packets:
        raise ValueError("no complete Pass A packets are ready for Pass B")
    results: list[dict[str, Any]] = []
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
        results = list(previous.get("packets") or [])
        calls = list(previous.get("calls") or [])
        started_at = previous.get("reviewed_at") or started_at
    completed_ids = [packet["packet_id"] for packet in results]
    if len(set(completed_ids)) != len(completed_ids):
        raise ValueError("partial Pass B review contains duplicate packets")
    available_ids = {packet["packet_id"] for packet in packets}
    if not set(completed_ids) <= available_ids:
        raise ValueError("partial Pass B review contains packets outside the queue")
    remaining = [
        packet for packet in packets if packet["packet_id"] not in completed_ids
    ]

    def write_report(status: str) -> dict[str, Any]:
        counts = Counter(
            "escalated" if packet["escalations"] else "clear"
            for packet in results
        )
        report = {
            "review_type": "synthetic_pass_b_dual_independent",
            "status": status,
            "reviewed_at": started_at,
            "completed_at": _utc_now() if status == "complete" else None,
            "reviewer_model_mode": model,
            "cli_version": cli_version,
            "subscription_path": "Antigravity CLI",
            "metered_api_call": False,
            "second_check_policy": (
                "All proposed defects and negatives plus a deterministic "
                "visibility-stratified >=25% ordinary-claim sample."
            ),
            "counts": dict(sorted(counts.items())),
            "packets": results,
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
        batch_id = len(calls) + 1
        print(
            f"Pass B batch {batch_id}: first evidence labels "
            f"({len(batch)} packet(s))",
            flush=True,
        )
        first_prompt = _label_prompt(batch, f"pass-b-label-{batch_id}")
        first_raw, first_wrapper, first_elapsed = _invoke(
            cli, model, first_prompt, timeout, dataset_dir
        )
        first = _validate_first(batch, first_raw)
        print(f"Pass B batch {batch_id}: blind second checks", flush=True)
        second_prompt = _check_prompt(
            batch, first, f"pass-b-check-{batch_id}"
        )
        second_raw, second_wrapper, second_elapsed = _invoke(
            cli, model, second_prompt, timeout, dataset_dir
        )
        second = _validate_second(batch, first, second_raw)
        calls.append(
            {
                "batch": batch_id,
                "packet_ids": [packet["packet_id"] for packet in batch],
                "first_prompt_sha256": _sha256_text(first_prompt),
                "second_prompt_sha256": _sha256_text(second_prompt),
                "first_latency_seconds": first_elapsed,
                "second_latency_seconds": second_elapsed,
                "first_wrapper": first_wrapper,
                "second_wrapper": second_wrapper,
            }
        )
        for packet in batch:
            packet_id = packet["packet_id"]
            label = first[packet_id]
            check = second[packet_id]
            check_by_id = {
                item["check_id"]: item for item in check["checks"]
            }
            escalations = []
            for item in _checks(label):
                outcome = check_by_id[item["check_id"]]
                if outcome["decision"] != "supported":
                    escalations.append(
                        {
                            "escalation_id": f"{packet_id}:{item['check_id']}",
                            "kind": item["kind"],
                            "reason": outcome["reason"],
                            "first_hypothesis": item["hypothesis"],
                            "second_decision": outcome["decision"],
                        }
                    )
            for index, claim in enumerate(label["claims"]):
                if claim["visibility"] == "ambiguous":
                    escalations.append(
                        {
                            "escalation_id": f"{packet_id}:claim-{index}-ambiguity",
                            "kind": "ambiguity",
                            "reason": (
                                f"First reviewer marked "
                                f"{claim['canonical_name']} ambiguous."
                            ),
                        }
                    )
            for index, negative in enumerate(label["negative_controls"]):
                if negative["assessment"] == "ambiguous":
                    escalations.append(
                        {
                            "escalation_id": (
                                f"{packet_id}:negative-{index}-ambiguity"
                            ),
                            "kind": "ambiguity",
                            "reason": (
                                "First reviewer marked negative control "
                                f"ambiguous: {negative['wording']}"
                            ),
                        }
                    )
            for index, note in enumerate(label["ambiguity_notes"]):
                escalations.append(
                    {
                        "escalation_id": f"{packet_id}:first-ambiguity-{index}",
                        "kind": "ambiguity",
                        "reason": note,
                    }
                )
            for source, notes in (
                ("first-continuity", label["continuity_concerns"]),
                ("second-finding", check["additional_material_findings"]),
                ("second-continuity", check["continuity_concerns"]),
            ):
                for index, note in enumerate(notes):
                    escalations.append(
                        {
                            "escalation_id": f"{packet_id}:{source}-{index}",
                            "kind": source,
                            "reason": note,
                        }
                    )
            results.append(
                {
                    **packet,
                    "first_review": label,
                    "second_review": check,
                    "required_checks": _checks(label),
                    "escalations": escalations,
                }
            )
        write_report("partial")
        print(f"Pass B batch {batch_id}: checkpointed", flush=True)
    return write_report("complete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--packet", action="append", dest="packets")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list eligible immutable packets without invoking Antigravity",
    )
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--model", default=MODEL_MODE)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    packet_ids = set(args.packets) if args.packets else None
    if args.dry_run:
        packets = _packet_inputs(args.dataset_dir, packet_ids)
        print(
            json.dumps(
                {
                    "review_type": "synthetic_pass_b_preflight",
                    "count": len(packets),
                    "packets": [
                        {
                            "packet_id": packet["packet_id"],
                            "provider": packet["provider"],
                            "image_sha256": [
                                image["sha256"] for image in packet["images"]
                            ],
                        }
                        for packet in packets
                    ],
                },
                indent=2,
            )
        )
        return 0
    report = review(
        args.dataset_dir,
        args.output,
        packet_ids,
        args.cli,
        args.model,
        args.batch_size,
        args.timeout,
    )
    print(json.dumps(report["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
