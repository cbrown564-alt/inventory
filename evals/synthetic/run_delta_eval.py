#!/usr/bin/env python3
"""Run the Phase 3.5 delta pairs through the product's compare surface.

``score_delta.py`` has always taken a ``compare_inventories`` JSON, and nothing
in this dataset produced one. This does. For each review-accepted pair it
describes T0 from the parent's accepted reference frames and T1 from the
generated delta frames, assembles both sides through the product's own parser
and merge, and aligns them with ``compare_inventories``.

Three properties make the result scorable rather than decorative:

* **The backend is never told that this is a delta.** No specification, no
  ``changes`` list, and no mention of the other timepoint reaches the prompt. A
  describe run that knows what changed reports the prompt instead of the
  photograph, and ``false_change_rate`` would then measure nothing at all.
* **The two calls differ only in their images.** The instruction text is hashed
  on both sides and the run fails if they diverge, because any other difference
  is confounded with the delta under test.
* **Only pairs accepted by a completed review are eligible**, exactly as in
  ``score_delta``. An unreviewed pair has no standing gold to score against.

Descriptions go through subscription-backed Antigravity CLI, like every vision
run in this dataset: no metered endpoint, and no image generation. The
comparison uses the offline rubric, because classification is not one of the
delta metrics and the openai rubric would be a metered call. ``grade_delta`` is
computed by compare itself, so severity direction still scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from homeinventory.compare import OfflineRubric, compare_inventories
from homeinventory.describe import ITEM_SCHEMA, _parse_items
from homeinventory.merge import merge_items, room_code
from homeinventory.schema import Inventory, Photo, Room

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.prompts import PROMPTS, prompt_sha256
from evals.synthetic.run_eval import (
    ARCHITECTURE_ID,
    BACKEND_ID,
    DEFAULT_MODEL,
    QUOTA_ACCOUNTING,
    _cli_version,
    _extract_json_response,
    _rendered_request,
    _resolve_cli,
    _sha256_file,
    _sha256_json,
    _slug,
    _utc_now,
)

SCHEMA_VERSION = 1
DEFAULT_PROMPT = "production-v1"
#: T0 is the accepted parent frame the delta was generated against; T1 is the
#: generated frame. The ledger holds both, so neither side is re-derived here.
SIDES = ("T0", "T1")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _accepted_pairs(review_path: Path) -> list[str]:
    review = _json(review_path)
    if review.get("status") != "complete":
        raise ValueError(f"{review_path}: delta review is not complete")
    return [
        pair["delta_id"]
        for pair in review.get("pairs", [])
        if pair["decision"] == "accept"
    ]


def _delta_rows(dataset_dir: Path) -> dict[str, dict[str, dict[str, str]]]:
    path = dataset_dir / "delta_tasks.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_delta: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        by_delta.setdefault(row["delta_id"], {})[row["view_id"]] = row
    return by_delta


def _side_inputs(
    dataset_dir: Path, views: dict[str, dict[str, str]], side: str
) -> list[dict[str, str]]:
    """Frames for one timepoint, in a fixed view order.

    The recorded hash is checked against the file on disk. A frame that no
    longer matches its ledger row is not the frame the review accepted, and
    scoring it would attribute a result to evidence nobody adjudicated.
    """
    path_column, hash_column = (
        ("reference_path", "reference_sha256")
        if side == "T0"
        else ("output_path", "output_sha256")
    )
    inputs: list[dict[str, str]] = []
    for view_id in sorted(views):
        row = views[view_id]
        relative = row[path_column].replace("\\", "/")
        image_path = dataset_dir / relative
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        actual = _sha256_file(image_path)
        recorded = row[hash_column]
        if recorded and actual != recorded:
            raise ValueError(
                f"{relative}: sha256 {actual} does not match the ledger's "
                f"{recorded}; this is not the frame the review accepted"
            )
        inputs.append(
            {
                "frame_id": image_path.stem,
                "view_id": view_id,
                "relative_path": relative,
                "sha256": actual,
            }
        )
    return inputs


def build_delta_run_plan(
    dataset_dir: Path = DEFAULT_DATASET,
    review_path: Path | None = None,
    prompt_id: str = DEFAULT_PROMPT,
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """One entry per accepted pair, each carrying its two describe runs."""
    if prompt_id not in PROMPTS:
        raise ValueError(f"unknown prompt id: {prompt_id!r}")
    config = _json(dataset_dir / "dataset.json")
    frozen = config["phase_1_prompt_comparison"]["prompts"]
    actual_hash = prompt_sha256(PROMPTS[prompt_id])
    if frozen.get(prompt_id) != actual_hash:
        raise ValueError(
            f"{prompt_id} differs from its frozen dataset hash; "
            "do not run after prompt drift"
        )
    if review_path is None:
        raise ValueError(
            "a completed delta review is required: only accepted pairs may be "
            "scored"
        )
    accepted = _accepted_pairs(review_path)
    by_delta = _delta_rows(dataset_dir)

    plan: list[dict[str, Any]] = []
    for delta_id in accepted:
        views = by_delta.get(delta_id)
        if not views:
            raise ValueError(f"{delta_id}: accepted by review but not in the ledger")
        any_row = next(iter(views.values()))
        runs = []
        for side in SIDES:
            output = (
                dataset_dir
                / "outputs"
                / "delta"
                / BACKEND_ID
                / model
                / prompt_id
                / f"{delta_id}.{side}.json"
            )
            runs.append(
                {
                    "delta_id": delta_id,
                    "side": side,
                    "room_type": any_row["room_type"],
                    "model": model,
                    "prompt_id": prompt_id,
                    "inputs": _side_inputs(dataset_dir, views, side),
                    "output": output,
                }
            )
        plan.append(
            {
                "delta_id": delta_id,
                "delta_class": any_row["delta_class"],
                "parent_scenario_id": any_row["parent_scenario_id"],
                "parent_split": any_row["parent_split"],
                "room_type": any_row["room_type"],
                "image_model": any_row["model_display_name"],
                "runs": runs,
                "comparison": (
                    dataset_dir
                    / "reports"
                    / "delta-compare"
                    / _slug(f"{model}-{prompt_id}")
                    / f"{delta_id}.json"
                ),
            }
        )
    return plan


def describe_side(
    run: dict[str, Any],
    dataset_dir: Path = DEFAULT_DATASET,
    cli: Path | None = None,
    *,
    dataset_phase: str = "phase-3.5-delta-pairs",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One whole-room describe call for one timepoint, cached immutably.

    ``dataset_phase`` and ``provenance`` exist for the Phase 0 repeat-describe
    control (docs/35), which needs a describe call that is byte-identical to
    this one in every input and differs only in that it happens a second time.
    Reusing this function rather than copying it is the point: a control whose
    call path had drifted from the runs it is the floor for would measure the
    drift instead of the non-determinism.
    """
    output = Path(run["output"])
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; cached evaluation outputs are immutable"
        )
    prompt = PROMPTS[run["prompt_id"]]
    rendered_request = _rendered_request(
        room_type=run["room_type"],
        prompt_id=run["prompt_id"],
        prompt=prompt,
        inputs=run["inputs"],
        model=run["model"],
    )
    cli_path = _resolve_cli(cli)
    cli_version = _cli_version(cli_path)
    image_mentions = "\n".join(
        f"- {item['frame_id']}: @{(dataset_dir / item['relative_path']).resolve()}"
        for item in run["inputs"]
    )
    model_prompt = (
        rendered_request["antigravity_instruction"]
        + "\n\nReferenced images and required photo IDs:\n"
        + image_mentions
        + "\n\nJSON schema:\n"
        + json.dumps(ITEM_SCHEMA, ensure_ascii=False, separators=(",", ":"))
    )
    command = [
        str(cli_path),
        "--sandbox",
        "--dangerously-skip-permissions",
        "--model",
        run["model"],
    ]
    # The CLI rejects --effort for models carrying their own reasoning budget;
    # every Gemini-mode record in this dataset was produced with it.
    if run["model"].startswith("gemini-"):
        command += ["--effort", "low"]
    command += [
        "--print-timeout",
        "5m",
        "--output-format",
        "json",
        "-p",
        model_prompt,
    ]
    started_at = _utc_now()
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=dataset_dir,
        capture_output=True,
        text=True,
        timeout=330,
    )
    elapsed = round(time.perf_counter() - started, 3)
    if result.returncode:
        raise RuntimeError(
            f"Antigravity CLI exited {result.returncode}: {result.stderr.strip()}"
        )
    wrapper = json.loads(result.stdout)
    if wrapper.get("status") != "SUCCESS":
        raise RuntimeError(f"Antigravity run failed: {wrapper}")
    # Conversation IDs are provider session data, not evaluation provenance.
    wrapper.pop("conversation_id", None)
    parsed = _extract_json_response(wrapper.get("response", ""))
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{run['delta_id']}.{run['side']}.{run['model']}.{run['prompt_id']}",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "dataset_id": "synthetic-room-eval",
        "dataset_phase": dataset_phase,
        "delta_id": run["delta_id"],
        "side": run["side"],
        "room_type": run["room_type"],
        "backend_provider": "Google Antigravity",
        "backend_model": run["model"],
        "architecture_id": ARCHITECTURE_ID,
        "sampling_controls": {
            "model_mode": run["model"],
            "effort": "low" if run["model"].startswith("gemini-") else "not sent",
            "temperature": "not exposed by Antigravity CLI",
        },
        "retry_policy": "none; a failed run remains failed for operator review",
        "prompt_id": run["prompt_id"],
        "prompt_sha256": prompt_sha256(prompt),
        # The delta is carried by the images alone: this hash must match across
        # T0 and T1, or the comparison is confounded with a prompt difference.
        "instruction_sha256": _sha256_json(
            rendered_request["antigravity_instruction"]
        ),
        "response_schema_sha256": _sha256_json(ITEM_SCHEMA),
        "inputs": run["inputs"],
        "rendered_request": rendered_request,
        "delta_blind": (
            "The describe call receives the room type, the frozen prompt and the "
            "images only. No delta specification, change list or reference to "
            "the other timepoint is supplied."
        ),
        "antigravity": {
            "cli_version": cli_version,
            "status": wrapper.get("status"),
            "num_turns": wrapper.get("num_turns"),
            "stderr": result.stderr.strip(),
        },
        "raw_response": wrapper,
        "parsed_output": parsed,
        "latency_seconds": elapsed,
        "usage": wrapper.get("usage") or {},
        "estimated_cost": {**QUOTA_ACCOUNTING, "amount": 0.0},
        **(provenance or {}),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def inventory_from_record(record: dict[str, Any]) -> Inventory:
    """Assemble one side through the product's own parse and merge.

    ``merge_items`` matters here rather than being ceremony: it is what
    deduplicates a room's schedule in the shipped pipeline, and duplicates left
    in would land in ``added``/``removed`` and inflate ``false_change_rate``
    against a model that did nothing wrong.
    """
    room_type = record["room_type"]
    photos = [
        Photo(
            id=item["frame_id"],
            path=item["relative_path"],
            room=room_type,
            sha256=item["sha256"],
        )
        for item in record["inputs"]
    ]
    summary, items = _parse_items(record["parsed_output"], photos)
    items = merge_items(items, room_code(room_type, set()))
    return Inventory(
        property_address=f"synthetic-room-eval {record['delta_id']}",
        inspected_by="evals.synthetic.run_delta_eval",
        inspected_at=record["completed_at"][:10],
        use_case="tenancy",
        describe_backend=f"{BACKEND_ID}/{record['backend_model']}",
        rooms=[Room(name=room_type, summary=summary, items=items, photos=photos)],
    )


def compare_pair(
    pair: dict[str, Any], records: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Align one pair's two timepoints and record how it was produced."""
    instructions = {records[side]["instruction_sha256"] for side in SIDES}
    if len(instructions) != 1:
        raise ValueError(
            f"{pair['delta_id']}: T0 and T1 instructions differ; the comparison "
            "would be confounded with a prompt difference"
        )
    checkin = inventory_from_record(records["T0"])
    checkout = inventory_from_record(records["T1"])
    result = compare_inventories(
        checkin, checkout, rubric=OfflineRubric(), use_case="tenancy"
    )
    result["delta_eval"] = {
        "schema_version": SCHEMA_VERSION,
        "delta_id": pair["delta_id"],
        "delta_class": pair["delta_class"],
        "parent_scenario_id": pair["parent_scenario_id"],
        "parent_split": pair["parent_split"],
        "room_type": pair["room_type"],
        "image_model": pair["image_model"],
        "backend_model": records["T0"]["backend_model"],
        "prompt_id": records["T0"]["prompt_id"],
        "prompt_sha256": records["T0"]["prompt_sha256"],
        "instruction_sha256": instructions.pop(),
        "rubric": "offline",
        "rubric_note": (
            "Gated changes stay unclassified. Classification is not a delta "
            "metric and the openai rubric would be a metered call; grade_delta "
            "is computed by compare, so severity direction still scores."
        ),
        "sides": {
            side: {
                "run_id": records[side]["run_id"],
                "frames": [item["relative_path"] for item in records[side]["inputs"]],
                "frame_sha256": [item["sha256"] for item in records[side]["inputs"]],
                "item_count": len(records[side]["parsed_output"].get("items", [])),
            }
            for side in SIDES
        },
        "evidence_class": (
            "Synthetic development evidence. Delta pairs cannot promote compare "
            "behaviour; that is gated on real check-in/check-out evidence "
            "(docs/08)."
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--review",
        type=Path,
        required=True,
        help="completed review_delta_pair report; only accepted pairs are run",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, choices=sorted(PROMPTS))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cli", type=Path, help="path to agy (default: PATH)")
    parser.add_argument(
        "--pair", action="append", help="limit to these delta ids; repeat to add"
    )
    parser.add_argument(
        "--limit", type=int, help="run at most this many pairs this invocation"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip pairs whose describe runs are already cached, rather than "
        "failing on the immutability check",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the run plan without calling Antigravity",
    )
    args = parser.parse_args()

    plan = build_delta_run_plan(
        args.dataset_dir, args.review, args.prompt, args.model
    )
    if args.pair:
        wanted = set(args.pair)
        plan = [pair for pair in plan if pair["delta_id"] in wanted]
        missing = wanted - {pair["delta_id"] for pair in plan}
        if missing:
            raise SystemExit(
                "not accepted by this review: " + ", ".join(sorted(missing))
            )
    if not plan:
        raise SystemExit("no accepted delta pairs to run")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "pairs": len(plan),
                    "describe_calls": sum(len(pair["runs"]) for pair in plan),
                    "model": args.model,
                    "prompt": args.prompt,
                    "metered_api_call": False,
                    "delta_ids": [pair["delta_id"] for pair in plan],
                },
                indent=2,
            )
        )
        return 0

    completed = 0
    for pair in plan:
        if args.limit is not None and completed >= args.limit:
            break
        records: dict[str, dict[str, Any]] = {}
        for run in pair["runs"]:
            output = Path(run["output"])
            if output.exists() and args.resume:
                records[run["side"]] = _json(output)
                continue
            print(f"{pair['delta_id']} {run['side']} …", flush=True)
            records[run["side"]] = describe_side(run, args.dataset_dir, args.cli)
        comparison_path = Path(pair["comparison"])
        if comparison_path.exists() and not args.resume:
            raise FileExistsError(f"{comparison_path} already exists")
        result = compare_pair(pair, records)
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        comparison_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        totals = result["totals"]
        print(
            f"{pair['delta_id']}: {totals['changed']} changed, "
            f"{totals['removed']} removed, {totals['added']} added, "
            f"{totals['unchanged']} unchanged"
        )
        completed += 1
    print(f"\n{completed} pair(s) compared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
