#!/usr/bin/env python3
"""Phase 0.5 — is the churn sampling? (docs/35 arm E, ordered by docs/36 §6.1)

docs/35 Phase 0 measured the floor: two describes of one photograph disagree
about as much as two describes of a changed room. Every intervention docs/35
proposes — name normalisation, conditioned describe, per-frame extraction,
detector grounding — is designed against a *cause* nobody has excluded, and
docs/35 says so in its own words: *"if the instability is largely sampling,
every other arm here is over-engineering."*

This excludes it, or fails to. Two independent describes of the same frames at
``temperature=0``, and two more at ``0.7``. If greedy decoding still churns ~10
items per room, sampling is not the mechanism and arms A–D are correctly aimed.
If greedy is stable and 0.7 churns, docs/35 is largely chasing a decode setting.

Four properties keep this an instrument check rather than a second dataset:

* **Neither run is cached.** The Phase 0 control reuses the cached T0 describe
  as its first run; this cannot. Those records are ``gemini-3.5-flash-low``
  through Antigravity, and pairing one against an Ollama run would measure the
  gap between two backends, not non-determinism inside one. Both sides are run
  here, per arm, which is why the call count is 4 per pair and not 1.
* **It is the production local path**, ``homeinventory.describe.LocalBackend``
  — the same system prompt, schema, batching and merge the shipped pipeline
  uses. A stability number for a call path the product does not have would
  answer nothing.
* **The arm's temperature cannot be overridden underneath it.** ``LocalBackend``
  reads ``HI_TEMPERATURE`` and friends from the environment and silently wins
  over its own constructor argument. A stray export would run both arms at one
  temperature and the experiment would report a null it did not measure, so any
  such variable being set is a hard refusal.
* **Nothing here enters the scored set.** Records land under
  ``outputs/local-stability/`` beside — never inside — the dataset's Antigravity
  outputs, under their own backend and prompt ids. docs/31's terms rule binds
  every *vision run for this dataset*; this produces no labels, no gold and no
  score against gold, and promotes nothing (docs/00).

**What it cannot tell you.** A local open-weight model's variance is not
``gemini-3.5-flash-low``'s variance, and the local path does not carry the
dataset's frozen ``production-v1`` prompt — it carries the product's own system
prompt, because that is what "the production describe path" means. So the
numbers here are not comparable in magnitude to Phase 0's 336. The question is
mechanism: does greedy decoding produce a stable schedule *at all*.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from homeinventory.describe import ITEM_SCHEMA, SYSTEM_PROMPT, LocalBackend
from homeinventory.schema import Item, Photo

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.run_delta_eval import (
    _accepted_pairs,
    _delta_rows,
    _json,
    _side_inputs,
)
from evals.synthetic.run_eval import _sha256_json, _utc_now
from evals.synthetic.run_repeat_describe import BASE_SIDE
from evals.synthetic.score_stability import _intended_items, pool

SCHEMA_VERSION = 1
DATASET_PHASE = "phase-0.5-local-sampling-control"
BACKEND_ID = "ollama-local"
ARCHITECTURE_ID = "local-ollama-whole-room-v1"
#: Deliberately not ``production-v1``. These runs carry the product's own
#: system prompt, not the dataset's frozen prompt, and a record that claimed
#: otherwise would invite a comparison against Phase 0 that is not valid.
PROMPT_ID = "local-system-v1"
#: Two independent runs of the same frames, per arm. Named A and B rather than
#: T0/T1 because neither is a timepoint — they are the same moment, twice.
RUN_SIDES = ("A", "B")
#: The arms. Greedy first: if it churns, the second arm is not needed to answer
#: the mechanism question, only to characterise it.
ARMS: dict[str, float] = {"t0": 0.0, "t07": 0.7}
DEFAULT_MODEL = LocalBackend.DEFAULT_MODEL
#: docs/36 §6.1 states the branch as "if temperature-0 still churns ~10 items
#: per room, sampling is excluded". Half the Phase 0 floor's 10.7 is the cut,
#: rather than the 10.7 itself, because a different model and a different
#: prompt are not expected to land on the same magnitude — the question is
#: whether greedy decoding is stable at all, and churn in this range is not.
#: Below it, the greedy arm is not self-evidently churning and the comparative
#: arm decides. Stated here rather than buried in a branch so that moving it
#: is a visible edit.
CHURN_EXCLUDES_SAMPLING = 5.0
#: ``LocalBackend`` reads all of these from the environment and lets them beat
#: its constructor arguments. Any one of them set turns this experiment into an
#: unlabelled different experiment, so the run refuses rather than reports.
SAMPLING_ENV_VARS = (
    "HI_TEMPERATURE",
    "HI_NUM_CTX",
    "HI_NUM_PREDICT",
    "HI_REPEAT_PENALTY",
    "HI_BATCH_SIZE",
    "HI_COMPACT_SCHEMA",
    "HI_THINK",
)


def assert_clean_sampling_env(env: dict[str, str] | None = None) -> None:
    """Refuse to run under an environment that overrides the arm.

    This is not defensiveness about a hypothetical. ``HI_TEMPERATURE`` is
    documented in ``describe.py`` as the knob for stabilising small models, so
    it is exactly the variable a person debugging a local model exports and
    forgets. With it set, both arms run at one temperature and the report says
    "sampling excluded" about a comparison that never happened.
    """
    active = {
        name: value
        for name, value in (env if env is not None else os.environ).items()
        if name in SAMPLING_ENV_VARS
    }
    if active:
        setting = ", ".join(f"{k}={v!r}" for k, v in sorted(active.items()))
        raise SystemExit(
            f"refusing to run: {setting} would override this control's own "
            "sampling settings and both arms could silently run identically. "
            f"Unset {' '.join(sorted(active))} and re-run."
        )


def path_safe_model(model: str) -> str:
    """Ollama tags (``qwen3.5:9b``) are not legal Windows directory names."""
    return model.replace(":", "_").replace("/", "_")


def records_dir(dataset_dir: Path, model: str, arm: str) -> Path:
    """Beside the dataset's outputs, never inside them.

    ``outputs/delta`` and ``outputs/repeat`` hold Antigravity records that are
    scored against gold. These are not those, and the path is the first place
    anybody reading the tree will look to find that out.
    """
    return (
        dataset_dir
        / "outputs"
        / "local-stability"
        / BACKEND_ID
        / path_safe_model(model)
        / arm
    )


def record_path(dataset_dir: Path, delta_id: str, model: str, arm: str, side: str) -> Path:
    return records_dir(dataset_dir, model, arm) / f"{delta_id}.{side}.json"


def select_pairs(accepted: list[str], limit: int | None) -> list[str]:
    """The subset to run, chosen by a rule rather than by hand.

    Sorted order, first ``limit``. The point of a subset is to answer the
    mechanism question sooner, and any deterministic rule does that; picking
    pairs by eye would let the arm be chosen after the fact.
    """
    ordered = sorted(accepted)
    return ordered if limit is None else ordered[:limit]


def build_local_run_plan(
    dataset_dir: Path = DEFAULT_DATASET,
    review_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    arms: tuple[str, ...] = tuple(ARMS),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """One entry per (pair, arm), each carrying its two independent runs."""
    if review_path is None:
        raise ValueError(
            "a completed delta review is required: only accepted pairs may be "
            "used for the control"
        )
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise ValueError(f"unknown arm(s): {', '.join(sorted(unknown))}")

    accepted = select_pairs(_accepted_pairs(review_path), limit)
    by_delta = _delta_rows(dataset_dir)

    plan: list[dict[str, Any]] = []
    for delta_id in accepted:
        views = by_delta.get(delta_id)
        if not views:
            raise ValueError(f"{delta_id}: accepted by review but not in the ledger")
        any_row = next(iter(views.values()))
        # The T0 columns: the review-accepted parent frames, which is the same
        # evidence Phase 0's control read. Hashes are checked against the
        # ledger inside ``_side_inputs``.
        inputs = _side_inputs(dataset_dir, views, BASE_SIDE)
        for arm in arms:
            plan.append(
                {
                    "delta_id": delta_id,
                    "arm": arm,
                    "temperature": ARMS[arm],
                    "room_type": any_row["room_type"],
                    "parent_scenario_id": any_row["parent_scenario_id"],
                    "parent_split": any_row["parent_split"],
                    "image_model": any_row["model_display_name"],
                    "runs": [
                        {
                            "delta_id": delta_id,
                            "side": side,
                            "arm": arm,
                            "temperature": ARMS[arm],
                            "room_type": any_row["room_type"],
                            "model": model,
                            "inputs": inputs,
                            "output": record_path(
                                dataset_dir, delta_id, model, arm, side
                            ),
                        }
                        for side in RUN_SIDES
                    ],
                }
            )
    return plan


def parsed_output_from_items(summary: str, items: list[Item]) -> dict[str, Any]:
    """Put ``describe_room``'s Items back into schema shape.

    ``LocalBackend.describe_room`` returns parsed ``Item`` objects, but every
    docs/35 metric reads a record's ``parsed_output`` and re-parses it, so a
    record has to carry the payload rather than the objects. The round trip is
    exact for the fields the metrics touch, and ``test_local_stability`` pins
    that by re-parsing this output and comparing the Items back.
    """
    return {
        "room_summary": summary,
        "items": [
            {
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "condition": item.condition,
                "cleanliness": item.cleanliness,
                "defects": list(item.defects),
                "quantity": item.quantity,
                "est_value_band": item.est_value_band,
                "photo_ids": list(item.photo_ids),
                "confidence": item.confidence,
            }
            for item in items
        ],
    }


def describe_local(
    run: dict[str, Any],
    dataset_dir: Path = DEFAULT_DATASET,
    backend: LocalBackend | None = None,
) -> dict[str, Any]:
    """One whole-room describe through the product's local path, cached immutably."""
    output = Path(run["output"])
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; cached evaluation outputs are immutable"
        )
    if backend is None:
        backend = LocalBackend(model=run["model"], temperature=run["temperature"])
    if backend.temperature != run["temperature"]:
        raise ValueError(
            f"{run['delta_id']} {run['side']}: backend temperature "
            f"{backend.temperature} is not the arm's {run['temperature']}; "
            "the record would name an arm it was not run at"
        )

    photos = [
        Photo(
            id=item["frame_id"],
            path=item["relative_path"],
            room=run["room_type"],
            sha256=item["sha256"],
        )
        for item in run["inputs"]
    ]
    photo_paths = [dataset_dir / item["relative_path"] for item in run["inputs"]]

    started_at = _utc_now()
    started = time.perf_counter()
    summary, items = backend.describe_room(
        run["room_type"], photos, photo_paths, detections={}
    )
    elapsed = round(time.perf_counter() - started, 3)

    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"{run['delta_id']}.{run['side']}.{run['model']}.{run['arm']}",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "dataset_id": "synthetic-room-eval",
        "dataset_phase": DATASET_PHASE,
        "delta_id": run["delta_id"],
        "side": run["side"],
        "arm": run["arm"],
        "room_type": run["room_type"],
        "backend_provider": "Ollama (local)",
        "backend_model": run["model"],
        "architecture_id": ARCHITECTURE_ID,
        "sampling_controls": {
            "temperature": run["temperature"],
            "num_ctx": backend.num_ctx,
            "num_predict": backend.num_predict,
            "repeat_penalty": backend.repeat_penalty,
            "batch_size": backend.batch_size,
            "max_dim": backend.max_dim,
            "think": backend.think,
            "note": (
                "The variable under test is temperature. Everything else is "
                "LocalBackend's shipped default and is held equal across arms."
            ),
        },
        "retry_policy": (
            "LocalBackend retries a malformed batch once at temperature 0.3. "
            "On a 2-frame room this is one batch; a retry would contaminate "
            "the arm, so retried_batches is recorded rather than assumed zero."
        ),
        "prompt_id": PROMPT_ID,
        "prompt_sha256": _sha256_json(SYSTEM_PROMPT),
        # Both sides of an arm must hash equal here or they were not the same
        # call. The room type is the only per-run text, and it is shared.
        "instruction_sha256": _sha256_json(
            {"system": SYSTEM_PROMPT, "room_type": run["room_type"]}
        ),
        "response_schema_sha256": _sha256_json(ITEM_SCHEMA),
        "inputs": run["inputs"],
        "delta_blind": (
            "The describe call receives the room type, the product's system "
            "prompt and the images only. No delta specification, change list "
            "or reference to any other run is supplied."
        ),
        "parsed_output": parsed_output_from_items(summary, items),
        "timing": getattr(backend, "last_room_timing", None),
        "latency_seconds": elapsed,
        "estimated_cost": {
            "billing_path": "local Ollama server",
            "metered_api_call": False,
            "marginal_cost_usd": 0.0,
        },
        "evidence_class": (
            "Instrument check. Produces no labels, enters no scored set, and "
            "promotes nothing (docs/00, docs/31 terms rule)."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def score_arms(
    dataset_dir: Path,
    review_path: Path,
    model: str = DEFAULT_MODEL,
    arms: tuple[str, ...] = tuple(ARMS),
    limit: int | None = None,
) -> dict[str, Any]:
    """Pool each arm's pairs with the Phase 0 metrics, and read nothing into it.

    ``pair_stability`` and ``pool`` are imported from ``score_stability`` rather
    than reimplemented, so a churn number here means the same thing it means in
    the Phase 0 report. Only pairs whose two records both exist are scored, and
    which those were is stated, because a subset that quietly shrank on a failed
    run would move the mean without moving anything visible.
    """
    from evals.synthetic.run_repeat_describe import assert_identical_calls
    from evals.synthetic.score_stability import pair_stability

    accepted = select_pairs(_accepted_pairs(review_path), limit)
    intended = _intended_items(dataset_dir, set(accepted))

    instruments: dict[str, Any] = {}
    for arm in arms:
        scored: list[dict[str, Any]] = []
        missing: list[str] = []
        for delta_id in accepted:
            paths = [
                record_path(dataset_dir, delta_id, model, arm, side)
                for side in RUN_SIDES
            ]
            if not all(path.is_file() for path in paths):
                missing.append(delta_id)
                continue
            record_a, record_b = (_json(path) for path in paths)
            assert_identical_calls(record_a, record_b)
            scored.append(
                {
                    "delta_id": delta_id,
                    "room_type": record_a["room_type"],
                    "stability": pair_stability(
                        record_a, record_b, intended.get(delta_id, [])
                    ),
                }
            )
        if not scored:
            raise FileNotFoundError(
                f"arm {arm}: no pair has both {RUN_SIDES[0]} and "
                f"{RUN_SIDES[1]} records under {records_dir(dataset_dir, model, arm)}"
            )
        pooled = pool(scored)
        instruments[arm] = {
            "temperature": ARMS[arm],
            "pairs_scored": len(scored),
            "pairs_missing_records": missing,
            "delta_ids": [pair["delta_id"] for pair in scored],
            "metrics": pooled["metrics"],
            "counts": pooled["counts"],
            "coverage": pooled["coverage"],
            "per_pair": [
                {
                    "delta_id": pair["delta_id"],
                    "room_type": pair["room_type"],
                    "metrics": pair["stability"]["metrics"],
                    "counts": pair["stability"]["counts"],
                }
                for pair in scored
            ],
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "local_sampling_control",
        "dataset_id": "synthetic-room-eval",
        "dataset_phase": DATASET_PHASE,
        "question": (
            "Does greedy decoding produce a stable item schedule at all? "
            "docs/35 arm E, ordered in front of arms A-D by docs/36 §6.1."
        ),
        "backend": {
            "backend_id": BACKEND_ID,
            "provider": "Ollama (local)",
            "model": model,
            "architecture_id": ARCHITECTURE_ID,
            "prompt_id": PROMPT_ID,
            "prompt_sha256": _sha256_json(SYSTEM_PROMPT),
        },
        "arms": instruments,
        "reading": _reading(instruments),
        "limits": [
            "A local open-weight model's variance is not "
            "gemini-3.5-flash-low's variance. This produces no magnitude for "
            "the production Antigravity path.",
            "These runs carry homeinventory's own system prompt, not the "
            "dataset's frozen production-v1. Churn here is not comparable "
            "like-for-like with the Phase 0 floor of 336.",
            "Sampling is excluded or implicated as a mechanism only for this "
            "model. A different decoder could behave differently.",
        ],
        "evidence_class": (
            "Instrument check on synthetic images. Promotes nothing (docs/00)."
        ),
    }


def _reading(instruments: dict[str, Any]) -> dict[str, Any]:
    """State what the two arms imply, and refuse to state it without both.

    The docs/36 §6.1 branch is written on the greedy arm alone — if temperature
    0 churns, sampling is excluded whatever 0.7 does — so a single-arm run gets
    a real reading rather than an error. The comparative claim needs both.
    """
    greedy = instruments.get("t0")
    sampled = instruments.get("t07")
    if greedy is None:
        return {
            "verdict": "indeterminate",
            "why": "the greedy arm was not run; every branch in docs/36 §6.1 "
            "turns on it",
        }
    churn = greedy["metrics"]["membership_churn_per_room"]
    if churn is None:
        return {"verdict": "indeterminate", "why": "greedy arm reported no churn count"}
    if churn >= CHURN_EXCLUDES_SAMPLING:
        verdict = "sampling_excluded"
        why = (
            f"greedy decoding still churns {churn} items per room. "
            "Non-determinism survives temperature 0, so sampling is not the "
            "mechanism and docs/35 arms A-D are correctly aimed."
        )
    elif sampled is None:
        verdict = "greedy_stable_second_arm_needed"
        why = (
            f"greedy churns {churn} items per room, which is low enough to "
            "implicate sampling, but the 0.7 arm was not run so the "
            "comparison is not made."
        )
    else:
        hot = sampled["metrics"]["membership_churn_per_room"]
        verdict = "sampling_implicated" if hot and hot > churn else "sampling_excluded"
        why = (
            f"greedy churns {churn} items per room against {hot} at "
            f"temperature 0.7."
        )
    return {
        "verdict": verdict,
        "why": why,
        "note": (
            "A verdict about this local model's decoder. It does not measure "
            "the production path and decides nothing on its own."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 0.5 — local sampling control",
        "",
        f"*{report['backend']['model']} via {report['backend']['provider']}. "
        f"{report['question']}*",
        "",
        "| Metric | " + " | ".join(
            f"temp {arm['temperature']}" for arm in report["arms"].values()
        ) + " |",
        "|---|" + "---:|" * len(report["arms"]),
    ]
    rows = [
        ("Pairs scored", "pairs_scored", None),
        ("Schedule agreement, exact names", "metrics", "schedule_agreement_exact"),
        (
            "Schedule agreement, normalised",
            "metrics",
            "schedule_agreement_normalised",
        ),
        ("Membership churn per room", "metrics", "membership_churn_per_room"),
        ("Naming churn per room", "metrics", "naming_churn_per_room"),
        ("Cleanliness agreement", "metrics", "cleanliness_agreement"),
        ("Coverage stability", "metrics", "coverage_stability"),
        ("Reported changes (total)", "counts", "reported_changes"),
    ]
    for label, key, sub in rows:
        values = []
        for arm in report["arms"].values():
            value = arm[key] if sub is None else arm[key].get(sub)
            values.append("—" if value is None else str(value))
        lines.append(f"| {label} | " + " | ".join(values) + " |")

    reading = report["reading"]
    lines += [
        "",
        f"**Reading: {reading['verdict']}.** {reading['why']}",
        "",
        "## Limits",
        "",
    ]
    lines += [f"- {limit}" for limit in report["limits"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--review",
        type=Path,
        required=True,
        help="completed review_delta_pair report; only accepted pairs are run",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--arm",
        action="append",
        choices=sorted(ARMS),
        help="limit to these arms; repeat to add (default: both)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="run the first N accepted pairs in sorted order (default: 10; "
        "pass 0 for all)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse records already cached rather than failing on the "
        "immutability check",
    )
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="score the records already on disk without describing anything",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the run plan and stop"
    )
    parser.add_argument("--out", type=Path, help="write JSON and Markdown here")
    args = parser.parse_args()

    arms = tuple(args.arm) if args.arm else tuple(ARMS)
    limit = None if args.limit == 0 else args.limit

    if not args.score_only:
        assert_clean_sampling_env()

    plan = build_local_run_plan(
        args.dataset_dir, args.review, args.model, arms, limit
    )
    if not plan:
        raise SystemExit("no accepted delta pairs to run")

    if args.dry_run:
        print(
            json.dumps(
                {
                    "instrument": "local-sampling-control",
                    "model": args.model,
                    "arms": {arm: ARMS[arm] for arm in arms},
                    "pairs": len({entry["delta_id"] for entry in plan}),
                    "describe_calls": sum(len(entry["runs"]) for entry in plan),
                    "metered_api_call": False,
                    "delta_ids": sorted({entry["delta_id"] for entry in plan}),
                },
                indent=2,
            )
        )
        return 0

    if not args.score_only:
        # One backend per arm, so the temperature is set once and every run in
        # the arm demonstrably shares it.
        backends = {
            arm: LocalBackend(model=args.model, temperature=ARMS[arm])
            for arm in arms
        }
        for entry in plan:
            for run in entry["runs"]:
                output = Path(run["output"])
                if output.exists() and args.resume:
                    print(f"{run['delta_id']} {entry['arm']}.{run['side']} cached")
                    continue
                print(
                    f"{run['delta_id']} {entry['arm']}.{run['side']} "
                    f"(temp {run['temperature']}) …",
                    flush=True,
                )
                record = describe_local(run, args.dataset_dir, backends[entry["arm"]])
                print(
                    f"  {len(record['parsed_output']['items'])} items in "
                    f"{record['latency_seconds']}s"
                )

    report = score_arms(args.dataset_dir, args.review, args.model, arms, limit)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        args.out.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                arm: {
                    "pairs_scored": data["pairs_scored"],
                    "metrics": data["metrics"],
                    "counts": data["counts"],
                }
                for arm, data in report["arms"].items()
            }
            | {"reading": report["reading"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
