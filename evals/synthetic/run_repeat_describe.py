#!/usr/bin/env python3
"""Instrument 0 — describe the identical frame set twice (docs/35 Phase 0).

Scoring the 27 delta pairs found that nine in ten reported changes had no gold
counterpart, and the decomposition said those were the *description* moving
rather than the room: rename pairs, unpaired additions, unpaired removals. But
the delta pairs cannot prove it. T0 and T1 are different photographs, so when
T1 omits what T0 listed there are three live explanations — a non-deterministic
describe run, a framing that genuinely does not show the item, and generator
drift — and no way to tell them apart.

This removes two of the three. Both sides read **the same frames**: the T0
describe already cached by ``run_delta_eval`` is one run, and this makes a
second call against byte-identical images with a byte-identical instruction.
There is no room change, no framing change and no drift, so every change
``compare_inventories`` then reports is pure non-determinism. That is the noise
floor, and it is the denominator docs/35's gate turns on.

Three properties keep it a control rather than a second experiment:

* **The second call is the first call.** It goes through
  ``run_delta_eval.describe_side`` — the same prompt, schema, model, effort and
  image mentions. A control whose call path had drifted would measure the
  drift.
* **Identity is verified, not assumed.** Instruction hash, prompt hash, schema
  hash, model and every frame's sha256 are checked equal across the two runs
  before they are compared. Any difference and the pair is refused, because a
  "floor" confounded with a prompt or frame difference is worse than no floor.
* **Only review-accepted pairs run**, as everywhere else in this dataset, so
  the control covers exactly the pairs the 368 was measured on.

27 pairs × 1 extra call, through subscription-backed Antigravity CLI: no
metered endpoint and no image generation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from homeinventory.compare import OfflineRubric, compare_inventories

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.prompts import PROMPTS
from evals.synthetic.run_delta_eval import (
    DEFAULT_PROMPT,
    _accepted_pairs,
    _delta_rows,
    _json,
    _side_inputs,
    describe_side,
    inventory_from_record,
)
from evals.synthetic.run_eval import BACKEND_ID, DEFAULT_MODEL, _slug

SCHEMA_VERSION = 1
DATASET_PHASE = "phase-0-describe-stability"
#: The cached ``run_delta_eval`` side reused as the first run. T0 is the
#: review-accepted parent frame — the reference the whole pair was generated
#: against — so the floor is measured on the same evidence that produced the
#: check-in half of every delta comparison.
BASE_SIDE = "T0"
#: The second describe of those same frames.
REPEAT_SIDE = "R2"
#: Fields that must be identical across the two runs. Anything here differing
#: means the two calls were not the same call, and their disagreement is not
#: non-determinism.
IDENTITY_FIELDS = (
    "instruction_sha256",
    "prompt_sha256",
    "response_schema_sha256",
    "backend_model",
    "prompt_id",
    "room_type",
    "architecture_id",
)


def base_records_dir(dataset_dir: Path, model: str, prompt_id: str) -> Path:
    """Where ``run_delta_eval`` cached the runs this control pairs against."""
    return dataset_dir / "outputs" / "delta" / BACKEND_ID / model / prompt_id


def repeat_records_dir(dataset_dir: Path, model: str, prompt_id: str) -> Path:
    return dataset_dir / "outputs" / "repeat" / BACKEND_ID / model / prompt_id


def base_record_path(
    dataset_dir: Path, delta_id: str, model: str, prompt_id: str
) -> Path:
    return base_records_dir(dataset_dir, model, prompt_id) / f"{delta_id}.{BASE_SIDE}.json"


def repeat_record_path(
    dataset_dir: Path, delta_id: str, model: str, prompt_id: str
) -> Path:
    return (
        repeat_records_dir(dataset_dir, model, prompt_id)
        / f"{delta_id}.{REPEAT_SIDE}.json"
    )


def build_repeat_run_plan(
    dataset_dir: Path = DEFAULT_DATASET,
    review_path: Path | None = None,
    prompt_id: str = DEFAULT_PROMPT,
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """One entry per accepted pair: its cached T0 run and the repeat to make.

    The cached T0 record must already exist. Describing fresh frames here
    instead would give a floor for runs nobody scored; the point is to pair the
    repeat with the very run that produced the delta comparison.
    """
    if review_path is None:
        raise ValueError(
            "a completed delta review is required: only accepted pairs may be "
            "used for the control"
        )
    accepted = _accepted_pairs(review_path)
    by_delta = _delta_rows(dataset_dir)

    plan: list[dict[str, Any]] = []
    for delta_id in accepted:
        views = by_delta.get(delta_id)
        if not views:
            raise ValueError(f"{delta_id}: accepted by review but not in the ledger")
        base = base_record_path(dataset_dir, delta_id, model, prompt_id)
        if not base.is_file():
            raise FileNotFoundError(
                f"{base}: no cached {BASE_SIDE} describe for {delta_id}. Run "
                "evals.synthetic.run_delta_eval first — the control pairs the "
                "repeat with an existing run, it does not make a new pair."
            )
        any_row = next(iter(views.values()))
        plan.append(
            {
                "delta_id": delta_id,
                "delta_class": any_row["delta_class"],
                "parent_scenario_id": any_row["parent_scenario_id"],
                "parent_split": any_row["parent_split"],
                "room_type": any_row["room_type"],
                "image_model": any_row["model_display_name"],
                "base_record": base,
                "run": {
                    "delta_id": delta_id,
                    "side": REPEAT_SIDE,
                    "room_type": any_row["room_type"],
                    "model": model,
                    "prompt_id": prompt_id,
                    # The same frames as the base run, by construction: both
                    # sides read the T0 columns of the same ledger rows.
                    "inputs": _side_inputs(dataset_dir, views, BASE_SIDE),
                    "output": repeat_record_path(
                        dataset_dir, delta_id, model, prompt_id
                    ),
                },
                "comparison": (
                    dataset_dir
                    / "reports"
                    / "repeat-compare"
                    / _slug(f"{model}-{prompt_id}")
                    / f"{delta_id}.json"
                ),
            }
        )
    return plan


def describe_repeat(
    run: dict[str, Any],
    dataset_dir: Path = DEFAULT_DATASET,
    cli: Path | None = None,
) -> dict[str, Any]:
    """The second describe of an already-described frame set."""
    return describe_side(
        run,
        dataset_dir,
        cli,
        dataset_phase=DATASET_PHASE,
        provenance={
            "control": {
                "instrument": "repeat-describe",
                "base_side": BASE_SIDE,
                "note": (
                    "Second describe of the frames already described as "
                    f"{BASE_SIDE}. Same images, same instruction, same model. "
                    "Any disagreement between the two runs is "
                    "non-determinism, not a change in the room."
                ),
            }
        },
    )


def assert_identical_calls(base: dict[str, Any], repeat: dict[str, Any]) -> None:
    """Refuse a pair whose two runs were not the same call.

    Checked rather than trusted because the floor is only interpretable if the
    two runs differ in nothing but the fact of being run twice. A mismatch here
    is a bug in the plan, not a finding about the model.
    """
    for field in IDENTITY_FIELDS:
        if base.get(field) != repeat.get(field):
            raise ValueError(
                f"{base.get('delta_id')}: {field} differs between "
                f"{BASE_SIDE} and {REPEAT_SIDE} "
                f"({base.get(field)!r} vs {repeat.get(field)!r}); the two runs "
                "are not the same call and their disagreement is not "
                "non-determinism"
            )
    base_frames = [(item["frame_id"], item["sha256"]) for item in base["inputs"]]
    repeat_frames = [(item["frame_id"], item["sha256"]) for item in repeat["inputs"]]
    if base_frames != repeat_frames:
        raise ValueError(
            f"{base.get('delta_id')}: the two runs did not read the same "
            "frames; this is not a repeat-describe control"
        )


def compare_repeat(
    pair: dict[str, Any], base: dict[str, Any], repeat: dict[str, Any]
) -> dict[str, Any]:
    """Align one pair's two runs of the same frames.

    ``compare_inventories`` is handed the two schedules in the same
    check-in/check-out roles the delta comparison uses, so the two instruments
    are read by identical machinery and their numbers are comparable. Every
    change it reports here is spurious by construction.
    """
    assert_identical_calls(base, repeat)
    result = compare_inventories(
        inventory_from_record(base),
        inventory_from_record(repeat),
        rubric=OfflineRubric(),
        use_case="tenancy",
    )
    result["stability_eval"] = {
        "schema_version": SCHEMA_VERSION,
        "instrument": "repeat-describe",
        "dataset_phase": DATASET_PHASE,
        "delta_id": pair["delta_id"],
        "delta_class": pair["delta_class"],
        "parent_scenario_id": pair["parent_scenario_id"],
        "parent_split": pair["parent_split"],
        "room_type": pair["room_type"],
        "image_model": pair["image_model"],
        "backend_model": base["backend_model"],
        "prompt_id": base["prompt_id"],
        "prompt_sha256": base["prompt_sha256"],
        "instruction_sha256": base["instruction_sha256"],
        "rubric": "offline",
        "sides": {
            side: {
                "run_id": record["run_id"],
                "frames": [item["relative_path"] for item in record["inputs"]],
                "frame_sha256": [item["sha256"] for item in record["inputs"]],
                "item_count": len(record["parsed_output"].get("items", [])),
            }
            for side, record in ((BASE_SIDE, base), (REPEAT_SIDE, repeat))
        },
        "control_note": (
            "Both sides describe the same frames. There is no room change, no "
            "framing change and no generator drift, so every reported change "
            "is non-determinism in the describe step."
        ),
        "evidence_class": (
            "Synthetic development evidence. This measures describe stability "
            "on one generator's images and promotes nothing (docs/00)."
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
        help="reuse repeat runs that are already cached, rather than failing "
        "on the immutability check",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the run plan without calling Antigravity",
    )
    args = parser.parse_args()

    plan = build_repeat_run_plan(
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
                    "instrument": "repeat-describe",
                    "pairs": len(plan),
                    "describe_calls": len(plan),
                    "reused_cached_runs": len(plan),
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
        base = _json(Path(pair["base_record"]))
        output = Path(pair["run"]["output"])
        if output.exists() and args.resume:
            repeat = _json(output)
        else:
            print(f"{pair['delta_id']} {REPEAT_SIDE} …", flush=True)
            repeat = describe_repeat(pair["run"], args.dataset_dir, args.cli)
        comparison_path = Path(pair["comparison"])
        if comparison_path.exists() and not args.resume:
            raise FileExistsError(f"{comparison_path} already exists")
        result = compare_repeat(pair, base, repeat)
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        comparison_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        totals = result["totals"]
        print(
            f"{pair['delta_id']}: {totals['changed']} changed, "
            f"{totals['removed']} removed, {totals['added']} added, "
            f"{totals['unchanged']} unchanged — all spurious"
        )
        completed += 1
    print(f"\n{completed} pair(s) compared against their own repeat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
