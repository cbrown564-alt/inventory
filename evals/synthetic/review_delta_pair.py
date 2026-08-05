#!/usr/bin/env python3
"""Run two independent subscription-backed reviews of Phase 3.5 delta pairs.

The reviewer sees the accepted T0 frame and the generated T1 frame side by
side and answers three questions per pair: is this still the same room, is
each enumerated change visible, and what else differs.

What "else differs" costs the pair changed on 5 Aug 2026. The first rubric
treated every unenumerated difference as fatal, so a tea towel that moved to a
different oven handle rejected a pair on the same footing as an oven that
moved — and 27 of the 30 pilot pairs were rejected on movable clutter while
the real fixed-fitting drift sat buried in the same list. The owner's rule
replaces it: a pair fails when the room stops being the same room. Movable
objects are recorded, because a compare run may legitimately report them and
the gold has to be complete, but they never reject.

Reviews read local images through Antigravity CLI and never call an image or
vision API endpoint. The second reviewer receives the same evidence and never
the first reviewer's conclusion.
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


def _review_proxy(
    source: Path,
    destination: Path,
    max_width: int = 1024,
) -> str:
    """Create a smaller lossless review copy without changing source evidence.

    Antigravity's local image reader can spend its entire timeout tokenising a
    two-pair batch of 1536px PNGs. The reviewer needs the visible room and
    delta, not the source raster dimensions, so the proxy is deliberately
    derived and its hash is recorded alongside the original hash.
    """
    from PIL import Image

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((max_width, max_width))
            image.save(destination, format="PNG", optimize=True)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def _load_rows(dataset_dir: Path) -> list[dict[str, str]]:
    path = dataset_dir / "delta_tasks.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist; run build_delta_tasks first")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def review_inputs(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
    proxy_dir: Path | None = None,
    proxy_width: int = 1024,
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
            view = {
                "view_id": row["view_id"],
                "t0_image_path": str(t0_path.resolve()),
                "t1_image_path": str(t1_path.resolve()),
                "t1_image_sha256": row["output_sha256"],
            }
            if proxy_dir is not None:
                t0_proxy = proxy_dir / delta_id / f"{row['view_id']}-t0.png"
                t1_proxy = proxy_dir / delta_id / f"{row['view_id']}-t1.png"
                view.update({
                    "source_t0_image_path": view["t0_image_path"],
                    "source_t1_image_path": view["t1_image_path"],
                    "source_t0_image_sha256": row["reference_sha256"],
                    "source_t1_image_sha256": row["output_sha256"],
                    "t0_proxy_sha256": _review_proxy(t0_path, t0_proxy, proxy_width),
                    "t1_proxy_sha256": _review_proxy(t1_path, t1_proxy, proxy_width),
                    "t0_image_path": str(t0_proxy.resolve()),
                    "t1_image_path": str(t1_proxy.resolve()),
                })
            views.append(view)
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
        "evidence; the T1 image is a candidate re-render of the same room "
        "after a period of tenancy.\n\n"
        "The question that decides a pair is whether T1 is still the same "
        "room. It is not whether everything in the room stayed put: a tenant "
        "moves towels, mugs, bottles, cushions, books and shoes, and those "
        "differences are expected. Judge the room, not the clutter.\n\n"
        "For each pair report four things.\n"
        "1. Same room: does the fixed fabric hold? Room geometry, walls, "
        "ceilings, floors and finishes; windows and doors; fitted units, "
        "built-in and freestanding appliances, sanitary fittings, radiators "
        "and fixed light fittings; large defining furniture. Any of these "
        "moving, resizing, changing model or disappearing is a hard failure, "
        "as is a re-imagined layout or a viewpoint that has moved so far it no "
        "longer shows the same part of the room. So is a contradiction between "
        "the two views of the same timepoint about any of it.\n"
        "2. Room identity findings: for each such failure, name the view, the "
        "element and what differs. Be specific about which fitting moved and "
        "how you know it is the fitting rather than the camera — check whether "
        "surrounding fixed edges held position.\n"
        "3. Enumerated changes: for each listed change, is it visible in T1 "
        "and absent in T0 as described? Mark 'absent' when the change did not "
        "render, and also when the T0 frame does not show what the change "
        "assumes was there. Mark 'ambiguous' when it is too fine to resolve.\n"
        "4. Incidental differences: list every other difference you can see — "
        "movable objects added, removed or moved, textiles, toiletries, "
        "worktop clutter, small decor, and modest framing drift. These never "
        "reject a pair. They are recorded because the gold has to name "
        "everything that differs, or a correct compare run reporting one of "
        "them scores as a false change.\n\n"
        "Reject only when room identity fails, or when no enumerated material "
        "change is observable at all so the pair carries no delta signal. "
        "Escalate genuine visual uncertainty about identity. Ignore pure "
        "image-noise differences such as compression grain.\n\n"
        "Return only a JSON array, one object per pair, with exactly: "
        "delta_id, decision (accept|reject|escalate), same_room (boolean), "
        "same_room_notes, room_identity_findings [{view, element, "
        "description}], enumerated [{change_id, visibility(clear|ambiguous|"
        "absent), notes}], incidental_differences [{target, description}], "
        "reason. Do not wrap the JSON in Markdown. "
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
        if not isinstance(item.get("room_identity_findings"), list):
            raise ValueError(f"{delta_id}: room_identity_findings is not a list")
        if not isinstance(item.get("incidental_differences"), list):
            raise ValueError(f"{delta_id}: incidental_differences is not a list")
    return by_id


def _material_ids(expected: dict[str, Any]) -> set[str]:
    return {
        change["id"] for change in expected["enumerated_changes"] if change["material"]
    }


def _visible_material(
    expected: dict[str, Any], *reviews: dict[str, Any]
) -> list[str]:
    """Material changes at least one reviewer read as clearly present."""
    material = _material_ids(expected)
    return sorted(
        {
            entry["change_id"]
            for review in reviews
            for entry in review["enumerated"]
            if entry["visibility"] == "clear" and entry["change_id"] in material
        }
    )


def combine(
    expected: dict[str, Any],
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    """Merge two independent reviews into one pair outcome.

    Only two things reject a pair: the room stopped being the same room, or
    nothing the pair was built to show is visible in it. An absent enumerated
    change is a fault in the gold rather than in the pair, so it is reported
    as a correction to make before scoring and does not throw the frames away.
    Incidental drift is carried through for the same reason — the gold has to
    name it, or a compare run that reports it is scored as inventing a change.
    """
    identity = [
        finding
        for review in (first, second)
        for finding in review.get("room_identity_findings", [])
    ]
    incidental = [
        difference
        for review in (first, second)
        for difference in review.get("incidental_differences", [])
    ]
    missing_material = sorted(
        {
            entry["change_id"]
            for review in (first, second)
            for entry in review["enumerated"]
            if entry["visibility"] == "absent"
            and entry["change_id"] in _material_ids(expected)
        }
    )
    visible_material = _visible_material(expected, first, second)
    agreed = first["decision"] == second["decision"]
    if not (first["same_room"] and second["same_room"]) or identity:
        decision = "reject"
        basis = "room identity failed"
    elif not visible_material:
        decision = "reject"
        basis = (
            "no enumerated material change is observable, so the pair carries "
            "no delta signal"
        )
    elif agreed and first["decision"] == "accept":
        decision = "accept"
        basis = "room identity holds"
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
        "same_room": not identity,
        "room_identity_findings": identity,
        "observable_material_changes": len(visible_material),
        "visible_material_changes": visible_material,
        "missing_material_changes": missing_material,
        "incidental_differences": incidental,
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
    proxy_dir: Path | None = None,
    proxy_width: int = 1024,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    cli = _resolve_cli(cli_path)
    cli_version = _cli_version(cli)
    inputs = review_inputs(dataset_dir, delta_ids, proxy_dir, proxy_width)
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
            "review_proxy_dir": str(proxy_dir.resolve()) if proxy_dir else None,
            "review_proxy_max_width": proxy_width if proxy_dir else None,
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


def _identity_findings(pair: dict[str, Any]) -> list[dict[str, Any]]:
    """Identity findings, tolerating reports written under the old rubric."""
    if "room_identity_findings" in pair:
        return pair["room_identity_findings"]
    return [] if pair.get("same_room", True) else [{"description": pair["decision_basis"]}]


def probe_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the docs/31 Phase 3.5 probe gate to a completed review.

    Pass needs at least two of three probe scenarios accepted with the room
    intact in each. The gate is deliberately not retryable at a looser bar.
    """
    pairs = report.get("pairs", [])
    accepted = [pair for pair in pairs if pair["decision"] == "accept"]
    drifted = [pair for pair in pairs if _identity_findings(pair)]
    passed = len(accepted) >= 2 and not any(
        _identity_findings(pair) for pair in accepted
    )
    return {
        "pairs_reviewed": len(pairs),
        "accepted": len(accepted),
        "pairs_with_room_identity_finding": len(drifted),
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
    parser.add_argument(
        "--proxy-dir",
        type=Path,
        help="write/use 1024px lossless review proxies while retaining source hashes",
    )
    parser.add_argument("--proxy-width", type=int, default=1024)
    args = parser.parse_args()
    delta_ids = set(args.deltas) if args.deltas else None
    if args.probe:
        report = json.loads(args.output.read_text(encoding="utf-8"))
        print(json.dumps(probe_verdict(report), indent=2))
        return 0
    if args.dry_run:
        inputs = review_inputs(
            args.dataset_dir, delta_ids, args.proxy_dir, args.proxy_width
        )
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
        args.proxy_dir,
        args.proxy_width,
    )
    print(json.dumps(report["counts"], indent=2))
    print(json.dumps(probe_verdict(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
