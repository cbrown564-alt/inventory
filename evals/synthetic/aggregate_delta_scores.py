#!/usr/bin/env python3
"""Pool the per-pair delta scores into one readable result.

Every pair is scored against its own specification and never against the set.
``score_delta`` matches gold to reported changes by target name across the whole
comparison, so pooling 27 pairs into one file would let one kitchen's kettle
satisfy another kitchen's gold, and would collide 27 rooms all named "Kitchen".
Scoring pair-by-pair and summing afterwards is the only arrangement in which the
numbers mean what they say.

Rates are recomputed from summed counts, not averaged over pairs. A mean of
per-pair rates weights a pair carrying one readable change the same as a pair
carrying nine — exactly the distortion the six thin-signal pairs would
introduce.

Two slices are reported separately rather than folded in, because pooling them
silently would hide a known property of the evidence:

* **thin signal** — pairs the review found to carry only one readable material
  change, where a single miss moves the pair's recall from 100% to 0%;
* **cross-view conflict** — pairs whose two T1 frames disagree about the state
  of something. The product describes a room from all its frames in one call, so
  a model handed contradictory evidence may report a change that is the
  generator's contradiction rather than its own invention.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from homeinventory.merge import _head_nouns

from evals.synthetic.build_delta_tasks import load_specs
from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.score_delta import score_delta

SCHEMA_VERSION = 1
METRIC_KEYS = (
    "delta_recall",
    "false_change_rate",
    "unchanged_stability",
    "severity_direction_accuracy",
    "immaterial_change_report_rate",
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def _metrics(rows: list[dict[str, Any]], totals: dict[str, int]) -> dict[str, float]:
    material = [row for row in rows if row["material"]]
    immaterial = [row for row in rows if not row["material"]]
    directional = [row for row in rows if row["direction_correct"] is not None]
    stability_total = totals["unchanged_reported"] + totals["false_changes"]
    return {
        "delta_recall": _pct(
            sum(1 for row in material if row["detected"]), len(material)
        ),
        "false_change_rate": _pct(
            totals["false_changes"], totals["reported_changes"]
        ),
        "unchanged_stability": _pct(totals["unchanged_reported"], stability_total),
        "severity_direction_accuracy": _pct(
            sum(1 for row in directional if row["direction_correct"]), len(directional)
        ),
        "immaterial_change_report_rate": _pct(
            sum(1 for row in immaterial if row["detected"]), len(immaterial)
        ),
    }


def _sum_totals(reports: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "material_changes",
        "material_changes_detected",
        "immaterial_changes",
        "reported_changes",
        "false_changes",
        "unchanged_reported",
        "directional_changes_scored",
    )
    return {
        key: sum(report["counts"][key] for report in reports) for key in keys
    }


def _slice(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for pair in pairs for row in pair["report"]["changes"]]
    totals = _sum_totals([pair["report"] for pair in pairs])
    return {
        "pairs": len(pairs),
        "delta_ids": sorted(pair["delta_id"] for pair in pairs),
        "metrics": _metrics(rows, totals),
        "counts": totals,
    }


def _grouped(pairs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        groups[pair[key]].append(pair)
    return {name: _slice(members) for name, members in sorted(groups.items())}


def _by_change_kind(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Recall by change kind. Rates only — a false change has no kind.

    Thirty pairs were sized for roughly five changes per kind, which is where
    per-kind rates start to be readable at all. They are still small: read them
    as direction, not as a measurement.
    """
    kinds: dict[str, dict[str, int]] = defaultdict(
        lambda: {"gold": 0, "detected": 0}
    )
    for pair in pairs:
        for row in pair["report"]["changes"]:
            if not row["material"]:
                continue
            entry = kinds[row["kind"]]
            entry["gold"] += 1
            entry["detected"] += int(row["detected"])
    return {
        kind: {
            "gold": entry["gold"],
            "detected": entry["detected"],
            "recall": _pct(entry["detected"], entry["gold"]),
        }
        for kind, entry in sorted(kinds.items())
    }


def decompose_false_changes(report: dict[str, Any]) -> dict[str, Any]:
    """Split a pair's false changes into alignment churn and lost items.

    A false change is any reported change with no gold counterpart, and the
    metric is right to count them all. But they are not one phenomenon. When a
    removed item and an added item share a discriminating noun — ``Recessed
    spotlight`` out, ``Ceiling spotlight`` in — one lamp nobody touched has been
    reported twice because ``match_score`` failed to align two names for it.
    That is the aligner's strictness. An unpaired removal or addition is
    something else: the two describe runs disagreed about what is in the room.

    Pairing uses the product's own :func:`_head_nouns`, requiring only a shared
    token where ``match_score`` requires set equality or containment. It is
    therefore exactly the question "would a laxer aligner have matched these",
    and never a licence to subtract them from the headline.
    """
    removed = [row for row in report["false_changes"] if row["bucket"] == "removed"]
    added = [row for row in report["false_changes"] if row["bucket"] == "added"]
    candidates = []
    for i, out in enumerate(removed):
        for j, into in enumerate(added):
            shared = _head_nouns(out["name"]) & _head_nouns(into["name"])
            if shared:
                candidates.append((-len(shared), i, j, sorted(shared)))
    candidates.sort()
    used_out: set[int] = set()
    used_in: set[int] = set()
    renames = []
    for _, i, j, shared in candidates:
        if i in used_out or j in used_in:
            continue
        used_out.add(i)
        used_in.add(j)
        renames.append(
            {
                "removed": removed[i]["name"],
                "added": added[j]["name"],
                "shared_tokens": shared,
            }
        )
    return {
        "rename_candidates": renames,
        "counts": {
            "false_changes": len(report["false_changes"]),
            "alignment_churn": 2 * len(renames),
            "unpaired_removed": len(removed) - len(renames),
            "unpaired_added": len(added) - len(renames),
            "changed_bucket": sum(
                1 for row in report["false_changes"] if row["bucket"] == "changed"
            ),
        },
    }


def _decomposition_summary(
    decompositions: list[dict[str, Any]], totals: dict[str, int]
) -> dict[str, Any]:
    keys = (
        "false_changes",
        "alignment_churn",
        "unpaired_removed",
        "unpaired_added",
        "changed_bucket",
    )
    counts = {
        key: sum(entry["counts"][key] for entry in decompositions) for key in keys
    }
    churn = counts["alignment_churn"]
    remaining_false = counts["false_changes"] - churn
    remaining_reported = totals["reported_changes"] - churn
    return {
        "counts": counts,
        "share_of_false_changes_that_are_alignment_churn": _pct(
            churn, counts["false_changes"]
        ),
        "false_change_rate_if_renames_aligned": _pct(
            remaining_false, remaining_reported
        ),
        "diagnostic_note": (
            "false_change_rate_if_renames_aligned is a diagnostic, not a "
            "corrected metric. The reported rate stands as measured: a landlord "
            "reading the report sees both halves of a rename as real changes."
        ),
    }


def build_report(
    dataset_dir: Path,
    comparison_dir: Path,
    review_path: Path,
    summary_path: Path | None = None,
    thin_signal: set[str] | None = None,
    cross_view_conflict: set[str] | None = None,
) -> dict[str, Any]:
    review = _json(review_path)
    if review.get("status") != "complete":
        raise ValueError(f"{review_path}: delta review is not complete")
    accepted = {
        pair["delta_id"]
        for pair in review.get("pairs", [])
        if pair["decision"] == "accept"
    }
    if summary_path is not None:
        summary = _json(summary_path)
        thin_signal = set(summary.get("thin_signal_pairs") or []) & accepted
        cross_view_conflict = set(summary.get("cross_view_conflict_pairs") or []) & accepted
    thin_signal = thin_signal or set()
    cross_view_conflict = cross_view_conflict or set()

    specs = {spec["id"]: spec for spec, _ in load_specs(dataset_dir)}
    pairs: list[dict[str, Any]] = []
    for path in sorted(comparison_dir.glob("*.json")):
        comparison = _json(path)
        meta = comparison.get("delta_eval")
        if meta is None:
            raise ValueError(f"{path}: not a run_delta_eval comparison")
        delta_id = meta["delta_id"]
        if delta_id not in accepted:
            raise ValueError(
                f"{delta_id}: comparison present but the review did not accept it"
            )
        spec = specs.get(delta_id)
        if spec is None:
            raise FileNotFoundError(f"{delta_id}: no delta specification")
        report = score_delta(comparison, [spec])
        pairs.append(
            {
                "delta_id": delta_id,
                "delta_class": meta["delta_class"],
                "room_type": meta["room_type"],
                "parent_split": meta["parent_split"],
                "report": report,
                "decomposition": decompose_false_changes(report),
            }
        )

    missing = sorted(accepted - {pair["delta_id"] for pair in pairs})
    scored = [
        pair
        for pair in pairs
        if pair["delta_id"] not in thin_signal
        and pair["delta_id"] not in cross_view_conflict
    ]
    all_rows = [row for pair in pairs for row in pair["report"]["changes"]]
    all_totals = _sum_totals([pair["report"] for pair in pairs])

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "phase35_delta_score_aggregate",
        "dataset_id": "synthetic-room-eval",
        "review": review_path.name,
        "comparison_dir": comparison_dir.name,
        "pairs_scored": len(pairs),
        "pairs_accepted_by_review": len(accepted),
        "pairs_not_yet_run": missing,
        "backend": (
            _json(sorted(comparison_dir.glob("*.json"))[0])["delta_eval"]
            if pairs
            else None
        ),
        "all_pairs": {
            "metrics": _metrics(all_rows, all_totals),
            "counts": all_totals,
        },
        "clean_slice": {
            "note": (
                "Pairs with neither a thin-signal nor a cross-view-conflict "
                "caveat. This is the number to quote."
            ),
            **_slice(scored),
        },
        "thin_signal_slice": {
            "note": (
                "Review found only one readable material change; one miss takes "
                "the pair from 100% to 0%."
            ),
            **_slice([pair for pair in pairs if pair["delta_id"] in thin_signal]),
        },
        "cross_view_conflict_slice": {
            "note": (
                "The two T1 frames disagree about some state. The whole-room "
                "architecture describes both frames in one call, so a reported "
                "change here may be the generator's contradiction rather than "
                "the model's invention."
            ),
            **_slice(
                [pair for pair in pairs if pair["delta_id"] in cross_view_conflict]
            ),
        },
        "false_change_decomposition": _decomposition_summary(
            [pair["decomposition"] for pair in pairs], all_totals
        ),
        "by_change_kind": _by_change_kind(pairs),
        "by_delta_class": _grouped(pairs, "delta_class"),
        "by_room_type": _grouped(pairs, "room_type"),
        "per_pair": [
            {
                "delta_id": pair["delta_id"],
                "delta_class": pair["delta_class"],
                "room_type": pair["room_type"],
                "metrics": pair["report"]["metrics"],
                "counts": pair["report"]["counts"],
                "thin_signal": pair["delta_id"] in thin_signal,
                "cross_view_conflict": pair["delta_id"] in cross_view_conflict,
                "false_change_decomposition": pair["decomposition"]["counts"],
            }
            for pair in pairs
        ],
        "rename_candidates": [
            dict(entry, delta_id=pair["delta_id"])
            for pair in pairs
            for entry in pair["decomposition"]["rename_candidates"]
        ],
        "missed_material_changes": [
            row
            for pair in pairs
            for row in pair["report"]["missed_material_changes"]
        ],
        "false_changes": [
            dict(row, delta_id=pair["delta_id"])
            for pair in pairs
            for row in pair["report"]["false_changes"]
        ],
        "evidence_class": (
            "Synthetic development evidence. Delta pairs cannot promote compare "
            "behaviour; that is gated on real check-in/check-out evidence "
            "(docs/08). Never present a synthetic delta pair as a real tenancy "
            "comparison."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 3.5 delta scoring",
        "",
        f"{report['pairs_scored']} of {report['pairs_accepted_by_review']} "
        "review-accepted pairs scored.",
        "",
        "| Slice | Pairs | Delta recall | False change | Unchanged stability |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("clean_slice", "Clean"),
        ("thin_signal_slice", "Thin signal"),
        ("cross_view_conflict_slice", "Cross-view conflict"),
        ("all_pairs", "All pairs"),
    ):
        section = report[key]
        metrics = section["metrics"]
        pairs = section.get("pairs", report["pairs_scored"])
        lines.append(
            f"| {label} | {pairs} | {metrics['delta_recall']}% | "
            f"{metrics['false_change_rate']}% | "
            f"{metrics['unchanged_stability']}% |"
        )
    decomposition = report["false_change_decomposition"]
    counts = decomposition["counts"]
    lines += [
        "",
        "## What the false changes are",
        "",
        f"{counts['alignment_churn']} of {counts['false_changes']} "
        f"({decomposition['share_of_false_changes_that_are_alignment_churn']}%) "
        "are one object reported twice because the two runs named it "
        "differently and `match_score` did not align them.",
        "",
        f"- alignment churn (rename pairs): {counts['alignment_churn']}",
        f"- unpaired removals — T1 omitted what T0 listed: {counts['unpaired_removed']}",
        f"- unpaired additions — T1 listed what T0 omitted: {counts['unpaired_added']}",
        f"- reported in the changed bucket: {counts['changed_bucket']}",
        "",
        f"Diagnostic: with renames aligned the rate would be "
        f"{decomposition['false_change_rate_if_renames_aligned']}%. "
        + decomposition["diagnostic_note"],
        "",
        "## Recall by change kind",
        "",
        "| Kind | Gold | Detected | Recall |",
        "|---|---:|---:|---:|",
    ]
    for kind, entry in report["by_change_kind"].items():
        lines.append(
            f"| {kind} | {entry['gold']} | {entry['detected']} | {entry['recall']}% |"
        )
    lines += ["", "## By pair class", "", "| Class | Pairs | Delta recall | False change |",
              "|---|---:|---:|---:|"]
    for name, entry in report["by_delta_class"].items():
        lines.append(
            f"| {name} | {entry['pairs']} | {entry['metrics']['delta_recall']}% | "
            f"{entry['metrics']['false_change_rate']}% |"
        )
    lines += ["", report["evidence_class"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison_dir", type=Path)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument(
        "--summary",
        type=Path,
        help="pilot summary supplying the thin-signal and cross-view-conflict "
        "pair lists, so the slices have one source of truth",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = build_report(
        args.dataset_dir, args.comparison_dir, args.review, args.summary
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        args.out.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report["all_pairs"]["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
