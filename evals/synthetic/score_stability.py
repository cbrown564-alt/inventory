#!/usr/bin/env python3
"""Describe-stability metrics for docs/35, on both instruments at once.

docs/35 asks one question — how much of the compare surface's 368 false changes
is the description moving rather than the room — and answers it by measuring
the same six things two ways:

* the **repeat-describe control**, where both runs read the same frames and
  every disagreement is non-determinism;
* the **delta pairs**, where the two runs read different photographs and the
  disagreement is non-determinism *plus* real difference.

The two are reported side by side and never averaged. Their difference is the
finding: what the control cannot explain is what the delta pairs add.

Both instruments are scored from the cached describe records alone. The
comparison is recomputed here with ``compare_inventories`` rather than read
from the ``*-compare`` directories, so a metric can never differ between the
instruments because of how its comparison happened to be produced. It is the
offline rubric and no network call, so recomputing is free.

The aligner is used for exactly the metrics that are about alignment.
``schedule_agreement`` deliberately is not: it is a multiset overlap on names,
so it stays readable if ``match_score`` changes underneath it, which it did on
5 Aug and will again.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from homeinventory.compare import (
    OfflineRubric,
    align_items,
    compare_inventories,
    _norm_name,
)
from homeinventory.merge import _head_nouns
from homeinventory.schema import CLEANLINESS_GRADES, CONDITION_GRADES, Item

from evals.run_eval import name_match
from evals.synthetic.build_delta_tasks import DELTA_VIEWS, load_specs
from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.run_delta_eval import (
    DEFAULT_PROMPT,
    _accepted_pairs,
    _json,
    inventory_from_record,
)
from evals.synthetic.run_eval import DEFAULT_MODEL
from evals.synthetic.run_repeat_describe import (
    BASE_SIDE,
    REPEAT_SIDE,
    assert_identical_calls,
    base_records_dir,
    repeat_records_dir,
)
from evals.synthetic.score import MATCH_THRESHOLD

SCHEMA_VERSION = 1
#: Delta-pair sides, in check-in/check-out order.
DELTA_SIDES = ("T0", "T1")


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return round(sum(values) / len(values), 2) if values else 0.0


def _exact_key(name: str) -> str:
    """Two runs wrote the same string, up to case and whitespace."""
    return _norm_name(name)


def _normalised_key(name: str) -> frozenset[str]:
    """The product's own head-noun key — the aligner's tier-3 equivalence class.

    Using ``merge._head_nouns`` rather than a bespoke normaliser keeps this
    honest in both directions: it is the same notion of "the same thing" the
    shipped merge and compare use, so a gap between the exact and normalised
    agreement is naming instability the product would actually feel, not a
    string-processing artefact.
    """
    return frozenset(_head_nouns(name))


def _multiset_agreement(
    names_a: list[str], names_b: list[str], key
) -> dict[str, int | float]:
    """Items reported by both runs over items reported by either.

    A multiset, not a set: a run that lists "Curtain" twice and one that lists
    it once disagree about the room by one curtain, and collapsing to a set
    would score that as perfect agreement.
    """
    a, b = Counter(key(n) for n in names_a), Counter(key(n) for n in names_b)
    both = sum((a & b).values())
    either = sum((a | b).values())
    return {"both": both, "either": either, "agreement": _pct(both, either)}


def _grade_gap(a: str | None, b: str | None, scale: list[str]) -> int | None:
    if a not in scale or b not in scale:
        return None
    return abs(scale.index(a) - scale.index(b))


def _view_map(record: dict[str, Any]) -> dict[str, str]:
    """Frame ID to the view it photographs.

    Photo IDs cannot be compared literally across the delta instrument: T0
    reads ``RP-002-A-wide`` and T1 reads ``P35-002-T1-A-wide``, so identical
    evidence would score zero agreement and the metric would measure the file
    naming. Views are the thing both runs actually share. An ID the model
    invented maps to nothing and is passed through, so it still counts as a
    disagreement — which it is.
    """
    return {item["frame_id"]: item.get("view_id", item["frame_id"])
            for item in record["inputs"]}


def _views(photo_ids: Iterable[str], view_map: dict[str, str]) -> set[str]:
    return {view_map.get(photo_id, photo_id) for photo_id in photo_ids}


def _intended_items(dataset_dir: Path, delta_ids: set[str]) -> dict[str, list[str]]:
    """``intended_visible_items`` per delta pair, for the views actually rendered.

    The scene specs carry this per view and delta work has never used it. Only
    the two views a delta pair renders count: an item the scene puts in a view
    nobody photographed is not a coverage failure.
    """
    intended: dict[str, list[str]] = {}
    for spec, parent in load_specs(dataset_dir, delta_ids):
        names: list[str] = []
        for view in parent["views"]:
            if view["id"] not in DELTA_VIEWS:
                continue
            for item in view.get("intended_visible_items", []):
                if item not in names:
                    names.append(item)
        intended[spec["id"]] = names
    return intended


def _names_cover(intended: str, names: list[str]) -> bool:
    gold = {"name": intended, "aliases": []}
    return any(name_match(name, gold) >= MATCH_THRESHOLD for name in names)


def _coverage(intended: list[str], names_a: list[str], names_b: list[str]) -> dict:
    """Which intended items each run named, and whether the two runs agree.

    Coverage is a per-run property, but the interesting Phase 0 number is the
    disagreement: an intended item one run names and the other does not is
    coverage instability directly, without any aligner in the way.
    """
    hits_a = [item for item in intended if _names_cover(item, names_a)]
    hits_b = [item for item in intended if _names_cover(item, names_b)]
    both = set(hits_a) & set(hits_b)
    either = set(hits_a) | set(hits_b)
    return {
        "intended": len(intended),
        "named_by_a": len(hits_a),
        "named_by_b": len(hits_b),
        "named_by_both": len(both),
        "named_by_either": len(either),
        "named_by_neither": len(intended) - len(either),
        "missed_by_both": [item for item in intended if item not in either],
        "unstable": sorted(either - both),
    }


def pair_stability(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
    intended: list[str] | None = None,
) -> dict[str, Any]:
    """Every docs/35 metric for one pair of describe runs.

    ``record_a``/``record_b`` are two ``run_delta_eval``-shaped describe records
    in check-in/check-out order. Nothing here knows or cares whether they read
    the same frames — that is what makes the same function the measurement for
    both instruments.
    """
    inv_a, inv_b = inventory_from_record(record_a), inventory_from_record(record_b)
    items_a: list[Item] = inv_a.rooms[0].items
    items_b: list[Item] = inv_b.rooms[0].items
    names_a = [item.name for item in items_a]
    names_b = [item.name for item in items_b]

    pairs, removed, added = align_items(items_a, items_b)
    comparison = compare_inventories(
        inv_a, inv_b, rubric=OfflineRubric(), use_case="tenancy"
    )
    totals = comparison["totals"]

    naming_churn = [
        {"a": ci.name, "b": co.name, "match_score": score}
        for ci, co, score in pairs
        if _norm_name(ci.name) != _norm_name(co.name)
    ]
    view_a, view_b = _view_map(record_a), _view_map(record_b)
    condition_exact = condition_within_one = condition_scored = 0
    cleanliness_exact = cleanliness_within_one = cleanliness_scored = 0
    quantity_agree = quantity_scored = 0
    photo_ids_agree = 0
    for ci, co, _ in pairs:
        gap = _grade_gap(ci.condition, co.condition, CONDITION_GRADES)
        if gap is not None:
            condition_scored += 1
            condition_exact += gap == 0
            condition_within_one += gap <= 1
        gap = _grade_gap(ci.cleanliness, co.cleanliness, CLEANLINESS_GRADES)
        if gap is not None:
            cleanliness_scored += 1
            cleanliness_exact += gap == 0
            cleanliness_within_one += gap <= 1
        if ci.quantity is not None and co.quantity is not None:
            quantity_scored += 1
            quantity_agree += ci.quantity == co.quantity
        photo_ids_agree += _views(ci.photo_ids, view_a) == _views(co.photo_ids, view_b)

    exact = _multiset_agreement(names_a, names_b, _exact_key)
    normalised = _multiset_agreement(names_a, names_b, _normalised_key)
    reported_changes = totals["changed"] + totals["removed"] + totals["added"]
    return {
        "counts": {
            "items_a": len(items_a),
            "items_b": len(items_b),
            "aligned": len(pairs),
            "unpaired_removed": len(removed),
            "unpaired_added": len(added),
            "membership_churn": len(removed) + len(added),
            "naming_churn": len(naming_churn),
            "changed": totals["changed"],
            "unchanged": totals["unchanged"],
            "reported_changes": reported_changes,
            "schedule_agreement_exact_both": exact["both"],
            "schedule_agreement_exact_either": exact["either"],
            "schedule_agreement_normalised_both": normalised["both"],
            "schedule_agreement_normalised_either": normalised["either"],
            "condition_scored": condition_scored,
            "condition_exact": condition_exact,
            "condition_within_one": condition_within_one,
            "cleanliness_scored": cleanliness_scored,
            "cleanliness_exact": cleanliness_exact,
            "cleanliness_within_one": cleanliness_within_one,
            "quantity_scored": quantity_scored,
            "quantity_agree": quantity_agree,
            "photo_ids_agree": photo_ids_agree,
        },
        "metrics": {
            "schedule_agreement_exact": exact["agreement"],
            "schedule_agreement_normalised": normalised["agreement"],
            "membership_churn": len(removed) + len(added),
            "naming_churn": len(naming_churn),
            "condition_agreement": _pct(condition_exact, condition_scored),
            "condition_agreement_within_one": _pct(
                condition_within_one, condition_scored
            ),
            "cleanliness_agreement": _pct(cleanliness_exact, cleanliness_scored),
            "cleanliness_agreement_within_one": _pct(
                cleanliness_within_one, cleanliness_scored
            ),
            "quantity_agreement": _pct(quantity_agree, quantity_scored),
            "photo_view_agreement": _pct(photo_ids_agree, len(pairs)),
        },
        "coverage": _coverage(intended or [], names_a, names_b),
        "naming_churn_pairs": naming_churn,
        "unpaired_removed": [item.name for item in removed],
        "unpaired_added": [item.name for item in added],
    }


#: Count keys that pool by summation. Rates are always recomputed from these,
#: never averaged over pairs — a 40-item room and a 9-item room do not carry
#: the same weight, and averaging their rates pretends they do
#: (``aggregate_delta_scores`` makes the same choice, for the same reason).
_SUMMED = (
    "items_a", "items_b", "aligned", "unpaired_removed", "unpaired_added",
    "membership_churn", "naming_churn", "changed", "unchanged",
    "reported_changes", "schedule_agreement_exact_both",
    "schedule_agreement_exact_either", "schedule_agreement_normalised_both",
    "schedule_agreement_normalised_either", "condition_scored",
    "condition_exact", "condition_within_one", "cleanliness_scored",
    "cleanliness_exact", "cleanliness_within_one", "quantity_scored",
    "quantity_agree", "photo_ids_agree",
)
_COVERAGE_SUMMED = (
    "intended", "named_by_a", "named_by_b", "named_by_both", "named_by_either",
    "named_by_neither",
)


def pool(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool per-pair results from summed counts."""
    counts = {
        key: sum(pair["stability"]["counts"][key] for pair in pairs)
        for key in _SUMMED
    }
    coverage = {
        key: sum(pair["stability"]["coverage"][key] for pair in pairs)
        for key in _COVERAGE_SUMMED
    }
    return {
        "pairs": len(pairs),
        "metrics": {
            "schedule_agreement_exact": _pct(
                counts["schedule_agreement_exact_both"],
                counts["schedule_agreement_exact_either"],
            ),
            "schedule_agreement_normalised": _pct(
                counts["schedule_agreement_normalised_both"],
                counts["schedule_agreement_normalised_either"],
            ),
            "membership_churn_per_room": _mean(
                pair["stability"]["counts"]["membership_churn"] for pair in pairs
            ),
            "naming_churn_per_room": _mean(
                pair["stability"]["counts"]["naming_churn"] for pair in pairs
            ),
            "condition_agreement": _pct(
                counts["condition_exact"], counts["condition_scored"]
            ),
            "condition_agreement_within_one": _pct(
                counts["condition_within_one"], counts["condition_scored"]
            ),
            "cleanliness_agreement": _pct(
                counts["cleanliness_exact"], counts["cleanliness_scored"]
            ),
            "cleanliness_agreement_within_one": _pct(
                counts["cleanliness_within_one"], counts["cleanliness_scored"]
            ),
            "quantity_agreement": _pct(
                counts["quantity_agree"], counts["quantity_scored"]
            ),
            "photo_view_agreement": _pct(counts["photo_ids_agree"], counts["aligned"]),
            "coverage_a": _pct(coverage["named_by_a"], coverage["intended"]),
            "coverage_b": _pct(coverage["named_by_b"], coverage["intended"]),
            "coverage_stability": _pct(
                coverage["named_by_both"], coverage["named_by_either"]
            ),
        },
        "counts": counts,
        "coverage": coverage,
    }


def _instrument(
    delta_ids: list[str],
    sides: tuple[tuple[Path, str], tuple[Path, str]],
    intended: dict[str, list[str]],
    *,
    identical_calls: bool,
) -> list[dict[str, Any]]:
    """Score one instrument's pairs, or explain precisely which record is missing."""
    results: list[dict[str, Any]] = []
    for delta_id in delta_ids:
        paths = [directory / f"{delta_id}.{side}.json" for directory, side in sides]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"{delta_id}: missing describe record(s) " + ", ".join(missing)
            )
        record_a, record_b = (_json(path) for path in paths)
        if identical_calls:
            assert_identical_calls(record_a, record_b)
        results.append(
            {
                "delta_id": delta_id,
                "room_type": record_a["room_type"],
                "stability": pair_stability(
                    record_a, record_b, intended.get(delta_id, [])
                ),
            }
        )
    return results


def build_report(
    dataset_dir: Path,
    review_path: Path,
    model: str = DEFAULT_MODEL,
    prompt_id: str = DEFAULT_PROMPT,
    delta_score_path: Path | None = None,
) -> dict[str, Any]:
    """Both instruments, pooled separately, plus the docs/35 Phase 0 gate."""
    accepted = _accepted_pairs(review_path)
    intended = _intended_items(dataset_dir, set(accepted))

    delta_dir = base_records_dir(dataset_dir, model, prompt_id)
    repeat_dir = repeat_records_dir(dataset_dir, model, prompt_id)
    control = _instrument(
        accepted,
        ((delta_dir, BASE_SIDE), (repeat_dir, REPEAT_SIDE)),
        intended,
        identical_calls=True,
    )
    delta = _instrument(
        accepted,
        ((delta_dir, DELTA_SIDES[0]), (delta_dir, DELTA_SIDES[1])),
        intended,
        identical_calls=False,
    )

    control_pooled = pool(control)
    delta_pooled = pool(delta)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "phase0_describe_stability",
        "dataset_id": "synthetic-room-eval",
        "review": review_path.name,
        "backend_model": model,
        "prompt_id": prompt_id,
        "instruments": {
            "repeat_describe_control": {
                "note": (
                    f"{BASE_SIDE} against a second describe of the same frames. "
                    "No room change, no framing change, no generator drift: "
                    "every reported change is non-determinism."
                ),
                **control_pooled,
            },
            "delta_pairs": {
                "note": (
                    f"{DELTA_SIDES[0]} against {DELTA_SIDES[1]} — different "
                    "photographs. Disagreement here is non-determinism plus "
                    "real difference, and is an upper bound on instability."
                ),
                "coverage_caveat": (
                    "intended_visible_items describe the parent scene, and a "
                    "delta pair deliberately removes some of them at T1. Read "
                    "coverage_b on this instrument as a floor, not a score."
                ),
                **delta_pooled,
            },
        },
        "gate": _gate(control_pooled, delta_pooled, delta_score_path),
        "per_pair": {
            "repeat_describe_control": _per_pair(control),
            "delta_pairs": _per_pair(delta),
        },
        "control_naming_churn_pairs": [
            dict(entry, delta_id=pair["delta_id"])
            for pair in control
            for entry in pair["stability"]["naming_churn_pairs"]
        ],
        "control_unpaired": [
            {
                "delta_id": pair["delta_id"],
                "removed": pair["stability"]["unpaired_removed"],
                "added": pair["stability"]["unpaired_added"],
            }
            for pair in control
            if pair["stability"]["counts"]["membership_churn"]
        ],
        "coverage_missed_by_both": sorted(
            {
                item
                for pair in control
                for item in pair["stability"]["coverage"]["missed_by_both"]
            }
        ),
        "evidence_class": (
            "Synthetic development evidence. This measures describe stability "
            "on one generator's images and promotes nothing (docs/00, docs/35)."
        ),
    }


def _per_pair(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "delta_id": pair["delta_id"],
            "room_type": pair["room_type"],
            "metrics": pair["stability"]["metrics"],
            "counts": pair["stability"]["counts"],
        }
        for pair in pairs
    ]


def _gate(
    control: dict[str, Any],
    delta: dict[str, Any],
    delta_score_path: Path | None,
) -> dict[str, Any]:
    """The docs/35 Phase 0 gate: state the fraction, decide nothing.

    The gate turns on how much of the delta pairs' invented change the control
    can account for. The denominator is the *scored* false-change count, read
    from the delta score aggregate rather than restated here, so there is one
    source of truth for the 368 and it moves if that scoring is ever re-run.

    No pass/fail is emitted. docs/35 is explicit that Phase 0 exits on a
    measurement, and a script that graded its own gate would be deciding the
    programme's direction by threshold rather than by judgement.
    """
    floor = control["counts"]["reported_changes"]
    gate: dict[str, Any] = {
        "control_reported_changes": floor,
        "delta_reported_changes": delta["counts"]["reported_changes"],
        "note": (
            "Every change the control reports is spurious by construction, so "
            "control_reported_changes is the non-determinism floor in the same "
            "units as the delta pairs' false changes."
        ),
        "decision": (
            "Not decided here. docs/35 Phase 0 exits on a measurement, and the "
            "decision is recorded against the number by a person."
        ),
    }
    if delta_score_path is None:
        gate["delta_false_changes"] = None
        gate["floor_share_of_delta_false_changes"] = None
        gate["denominator_note"] = (
            "Pass --delta-score to state the fraction against the scored "
            "false-change count."
        )
        return gate
    scored = _json(delta_score_path)
    false_changes = scored["all_pairs"]["counts"]["false_changes"]
    gate["delta_false_changes"] = false_changes
    gate["delta_score_report"] = delta_score_path.name
    gate["floor_share_of_delta_false_changes"] = _pct(floor, false_changes)
    return gate


def _markdown(report: dict[str, Any]) -> str:
    control = report["instruments"]["repeat_describe_control"]
    delta = report["instruments"]["delta_pairs"]
    gate = report["gate"]
    rows = (
        ("Schedule agreement, exact names", "schedule_agreement_exact", "%"),
        ("Schedule agreement, normalised", "schedule_agreement_normalised", "%"),
        ("Membership churn per room", "membership_churn_per_room", ""),
        ("Naming churn per room", "naming_churn_per_room", ""),
        ("Condition agreement", "condition_agreement", "%"),
        ("Condition agreement, within one", "condition_agreement_within_one", "%"),
        ("Cleanliness agreement", "cleanliness_agreement", "%"),
        ("Cleanliness agreement, within one", "cleanliness_agreement_within_one", "%"),
        ("Quantity agreement", "quantity_agreement", "%"),
        ("Photo-ID agreement", "photo_view_agreement", "%"),
        ("Coverage, run A", "coverage_a", "%"),
        ("Coverage, run B", "coverage_b", "%"),
        ("Coverage stability", "coverage_stability", "%"),
    )
    lines = [
        "# Phase 0 — the describe-stability floor",
        "",
        f"{control['pairs']} pairs, {report['backend_model']} / "
        f"{report['prompt_id']}. The two instruments measure different things "
        "and are never averaged.",
        "",
        "| Metric | Repeat-describe control | Delta pairs |",
        "|---|---:|---:|",
    ]
    for label, key, unit in rows:
        lines.append(
            f"| {label} | {control['metrics'][key]}{unit} | "
            f"{delta['metrics'][key]}{unit} |"
        )
    lines += [
        "",
        "The control's two runs read the same frames, so every change it "
        "reports is non-determinism. The delta pairs' two runs read different "
        "photographs, so theirs is non-determinism plus real difference.",
        "",
        "## The gate",
        "",
        "| | |",
        "|---|---:|",
        f"| Changes reported by the control (all spurious) | "
        f"**{gate['control_reported_changes']}** |",
        f"| Changes reported on the delta pairs | {gate['delta_reported_changes']} |",
    ]
    if gate.get("delta_false_changes") is not None:
        lines += [
            f"| Delta-pair false changes (scored) | {gate['delta_false_changes']} |",
            f"| Floor as a share of them | "
            f"**{gate['floor_share_of_delta_false_changes']}%** |",
        ]
    lines += [
        "",
        gate["decision"],
        "",
        "## What the control's churn is",
        "",
        f"- unpaired removals: {control['counts']['unpaired_removed']}",
        f"- unpaired additions: {control['counts']['unpaired_added']}",
        f"- aligned but renamed: {control['counts']['naming_churn']}",
        f"- aligned and reported as changed: {control['counts']['changed']}",
        "",
        report["evidence_class"],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--review",
        type=Path,
        required=True,
        help="completed review_delta_pair report; only accepted pairs are scored",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--delta-score",
        type=Path,
        help="aggregate_delta_scores report supplying the scored false-change "
        "count the gate's fraction is stated against",
    )
    parser.add_argument("--out", type=Path, help="write JSON and Markdown here")
    args = parser.parse_args()
    report = build_report(
        args.dataset_dir,
        args.review,
        args.model,
        args.prompt,
        args.delta_score,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        args.out.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "repeat_describe_control": report["instruments"][
                    "repeat_describe_control"
                ]["metrics"],
                "delta_pairs": report["instruments"]["delta_pairs"]["metrics"],
                "gate": report["gate"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
