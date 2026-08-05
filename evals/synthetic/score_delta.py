#!/usr/bin/env python3
"""Score a compare run against Phase 3.5 delta-pair gold.

These are compare metrics, not description metrics, and are reported in their
own table (docs/31 Phase 3.5). The headline is **false-change rate**: a
compare feature that invents change is worse than useless in an adjudication,
because it converts the landlord's evidence into the tenant's.

Input is the dict returned by :func:`homeinventory.compare.compare_inventories`
plus the accepted delta specifications. Only pairs accepted by
``review_delta_pair`` may be scored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.run_eval import name_match
from evals.synthetic.build_delta_tasks import load_specs, scorable_changes
from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.score import MATCH_THRESHOLD, _tokens, DEFECT_WORDS

#: Change kinds whose signal lives in the grade delta rather than a defect list.
DIRECTIONAL_KINDS = {"worsened": 1, "improved": -1}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_reported(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten every change the pipeline actually reported to the user.

    ``unchanged`` is excluded by design — it is the silence we want. Removed
    and added items are included, because to a landlord reading the report
    they are reported changes like any other.
    """
    reported: list[dict[str, Any]] = []
    for room in comparison.get("rooms", []):
        for change in room.get("changed", []):
            reported.append({
                "room": room["name"],
                "bucket": "changed",
                "name": change.get("name") or change.get("checkin_name", ""),
                "change": change,
            })
        for item in room.get("removed", []):
            reported.append({
                "room": room["name"],
                "bucket": "removed",
                "name": item.get("name", ""),
                "change": item,
            })
        for item in room.get("added", []):
            reported.append({
                "room": room["name"],
                "bucket": "added",
                "name": item.get("name", ""),
                "change": item,
            })
    return reported


def _iter_unchanged(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"room": room["name"], "name": entry.get("name", "")}
        for room in comparison.get("rooms", [])
        for entry in room.get("unchanged", [])
    ]


def _targets_match(target: str, name: str) -> bool:
    if not name:
        return False
    return name_match(name, {"name": target, "aliases": []}) >= MATCH_THRESHOLD


def _defect_mentioned(change: dict[str, Any], description: str) -> bool:
    text = " ".join([
        *change.get("new_defects", []),
        *change.get("checkout_defects", []),
        *change.get("defects", []),
    ])
    gold_terms = _tokens(description) & DEFECT_WORDS
    observed = _tokens(text)
    if gold_terms:
        return bool(gold_terms & observed)
    return bool(_tokens(description) & observed)


def _satisfies(gold: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Does one reported change account for one enumerated gold change?"""
    kind = gold["kind"]
    change = entry["change"]
    if kind == "item_removed":
        return entry["bucket"] == "removed"
    if kind == "item_added":
        return entry["bucket"] == "added"
    if entry["bucket"] != "changed":
        return False
    if kind == "new_defect":
        return _defect_mentioned(change, gold["description"])
    if kind in DIRECTIONAL_KINDS:
        delta = change.get("grade_delta")
        if delta is None:
            return _defect_mentioned(change, gold["description"])
        return delta != 0
    if kind == "cleanliness":
        return bool(change.get("cleanliness_delta"))
    # immaterial changes are satisfied by any report against the target
    return True


def _direction_correct(gold: dict[str, Any], entry: dict[str, Any]) -> bool | None:
    expected = DIRECTIONAL_KINDS.get(gold["kind"])
    if expected is None:
        return None
    delta = entry["change"].get("grade_delta")
    if delta is None or delta == 0:
        return None
    return (delta > 0) == (expected > 0)


def score_delta(
    comparison: dict[str, Any],
    specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score one compare run against every enumerated change in ``specs``.

    Gold is ``changes`` plus ``observed_changes``, minus anything retracted.
    Leaving the observed drift out would charge a compare run with a false
    change for correctly reporting something that is visibly in the frame — the
    metric would then be measuring the generator's drift rather than the
    model's invention, and it would penalise exactly the right answer. Keeping
    a retracted change in does the same damage from the other side: it costs
    recall for an absence no model could see, and rewards one that reports the
    prompt instead of the photograph.
    """
    gold_changes = [
        dict(change, delta_id=spec["id"]) for spec in specs
        for change in scorable_changes(spec) + list(spec.get("observed_changes") or [])
    ]
    reported = _iter_reported(comparison)
    matched_entries: set[int] = set()
    rows: list[dict[str, Any]] = []
    directions: list[bool] = []

    for gold in gold_changes:
        hit = None
        for index, entry in enumerate(reported):
            if index in matched_entries:
                continue
            if not _targets_match(gold["target"], entry["name"]):
                continue
            if _satisfies(gold, entry):
                hit = (index, entry)
                break
        if hit is not None:
            matched_entries.add(hit[0])
            direction = _direction_correct(gold, hit[1])
            if direction is not None:
                directions.append(direction)
        rows.append({
            "delta_id": gold["delta_id"],
            "change_id": gold["id"],
            "kind": gold["kind"],
            "target": gold["target"],
            "material": gold["material"],
            "detected": hit is not None,
            "reported_as": hit[1]["name"] if hit else None,
            "direction_correct": _direction_correct(gold, hit[1]) if hit else None,
        })

    material = [row for row in rows if row["material"]]
    immaterial = [row for row in rows if not row["material"]]
    false_changes = [
        {"room": entry["room"], "bucket": entry["bucket"], "name": entry["name"]}
        for index, entry in enumerate(reported)
        if index not in matched_entries
    ]
    unchanged = _iter_unchanged(comparison)
    stability_total = len(unchanged) + len(false_changes)

    def _pct(numerator: int, denominator: int) -> float:
        return round(100.0 * numerator / denominator, 1) if denominator else 0.0

    detected_material = sum(1 for row in material if row["detected"])
    reported_immaterial = sum(1 for row in immaterial if row["detected"])
    return {
        "metrics": {
            "delta_recall": _pct(detected_material, len(material)),
            "false_change_rate": _pct(len(false_changes), len(reported)),
            "unchanged_stability": _pct(len(unchanged), stability_total),
            "severity_direction_accuracy": _pct(
                sum(1 for value in directions if value), len(directions)
            ),
            "immaterial_change_report_rate": _pct(
                reported_immaterial, len(immaterial)
            ),
        },
        "counts": {
            "material_changes": len(material),
            "material_changes_detected": detected_material,
            "immaterial_changes": len(immaterial),
            "reported_changes": len(reported),
            "false_changes": len(false_changes),
            "unchanged_reported": len(unchanged),
            "directional_changes_scored": len(directions),
        },
        "changes": rows,
        "false_changes": false_changes,
        "missed_material_changes": [
            row for row in material if not row["detected"]
        ],
    }


def build_report(
    dataset_dir: Path,
    comparison_path: Path,
    review_path: Path | None = None,
) -> dict[str, Any]:
    comparison = _json(comparison_path)
    specs = [spec for spec, _ in load_specs(dataset_dir)]
    accepted: set[str] | None = None
    if review_path is not None:
        review = _json(review_path)
        if review.get("status") != "complete":
            raise ValueError(f"{review_path}: delta review is not complete")
        accepted = {
            pair["delta_id"] for pair in review.get("pairs", [])
            if pair["decision"] == "accept"
        }
        specs = [spec for spec in specs if spec["id"] in accepted]
    if not specs:
        raise ValueError(
            "no accepted delta specifications to score — only pairs accepted "
            "by review_delta_pair may be scored"
        )
    report = score_delta(comparison, specs)
    report["scored_deltas"] = sorted(spec["id"] for spec in specs)
    report["review_gated"] = accepted is not None
    report["evidence_class"] = (
        "Synthetic development evidence. Delta pairs cannot promote compare "
        "behaviour; that is gated on real check-in/check-out evidence (docs/08)."
    )
    return report


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    counts = report["counts"]
    lines = [
        "# Phase 3.5 delta-pair scores",
        "",
        f"Scored deltas: {', '.join(report['scored_deltas'])}",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Delta recall (material) | {metrics['delta_recall']}% |",
        f"| False-change rate | {metrics['false_change_rate']}% |",
        f"| Unchanged stability | {metrics['unchanged_stability']}% |",
        f"| Severity direction accuracy | {metrics['severity_direction_accuracy']}% |",
        f"| Immaterial changes reported | {metrics['immaterial_change_report_rate']}% |",
        "",
        f"Material changes: {counts['material_changes_detected']}/"
        f"{counts['material_changes']} detected. "
        f"Reported changes: {counts['reported_changes']}, of which "
        f"{counts['false_changes']} had no enumerated counterpart.",
        "",
    ]
    if report["missed_material_changes"]:
        lines.append("## Missed material changes")
        lines.append("")
        for row in report["missed_material_changes"]:
            lines.append(
                f"- `{row['delta_id']}.{row['change_id']}` "
                f"({row['kind']}) — {row['target']}"
            )
        lines.append("")
    if report["false_changes"]:
        lines.append("## False changes")
        lines.append("")
        for row in report["false_changes"]:
            lines.append(f"- {row['room']}: {row['name']} ({row['bucket']})")
        lines.append("")
    lines.extend([report["evidence_class"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path, help="compare_inventories JSON")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--review",
        type=Path,
        help="completed review_delta_pair report; restricts scoring to accepted pairs",
    )
    parser.add_argument("--out", type=Path, help="write JSON and Markdown here")
    args = parser.parse_args()
    report = build_report(args.dataset_dir, args.comparison, args.review)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        args.out.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
