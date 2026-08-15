#!/usr/bin/env python3
"""Compare check: aligned-state readout on the 27 scored delta pairs.

Completes the second half of the simplified synthetic programme. Uses only
committed describe records and the existing Phase 0 / Phase 3.5 aggregates —
no generation, no describe calls, no metered endpoints.

Headline is aligned-item state signal versus the repeat-describe noise floor,
not ``false_change_rate`` alone (Finding 01 of the forensic reconstruction).
Also reports the shipped cleanliness-gate sensitivity as a product diagnostic.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from homeinventory.compare import OfflineRubric, compare_inventories
from homeinventory.usecases import get_use_case

from evals.synthetic.build_delta_tasks import load_specs
from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.run_delta_eval import (
    DEFAULT_PROMPT,
    _accepted_pairs,
    inventory_from_record,
)
from evals.synthetic.run_eval import DEFAULT_MODEL
from evals.synthetic.run_repeat_describe import base_records_dir
from evals.synthetic.score_delta import score_delta

PHASE0_REPORT = "phase0-describe-stability-2026-08-06.json"
DELTA_SCORE_REPORT = "phase35-delta-score-2026-08-05.json"
DELTA_REVIEW = "phase35-pilot-review-recut-2026-08-05.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ratio(delta: float, control: float) -> float | None:
    if control == 0:
        return None
    return round(delta / control, 2)


def _disagreements(counts: dict[str, Any], key_scored: str, key_exact: str) -> int:
    return int(counts[key_scored]) - int(counts[key_exact])


def signal_ratios(phase0: dict[str, Any]) -> list[dict[str, Any]]:
    """Control-vs-delta ratios: 1.0 means the changed room looks like noise."""
    control = phase0["instruments"]["repeat_describe_control"]["counts"]
    delta = phase0["instruments"]["delta_pairs"]["counts"]
    rows = [
        ("Naming churn", control["naming_churn"], delta["naming_churn"], False),
        (
            "Unpaired removals",
            control["unpaired_removed"],
            delta["unpaired_removed"],
            False,
        ),
        (
            "Membership churn",
            control["membership_churn"],
            delta["membership_churn"],
            False,
        ),
        (
            "Unpaired additions",
            control["unpaired_added"],
            delta["unpaired_added"],
            False,
        ),
        (
            "Condition disagreements",
            _disagreements(control, "condition_scored", "condition_exact"),
            _disagreements(delta, "condition_scored", "condition_exact"),
            True,
        ),
        (
            "Cleanliness disagreements",
            _disagreements(control, "cleanliness_scored", "cleanliness_exact"),
            _disagreements(delta, "cleanliness_scored", "cleanliness_exact"),
            True,
        ),
        (
            "Items reported changed",
            control["changed"],
            delta["changed"],
            True,
        ),
    ]
    return [
        {
            "label": label,
            "control": control_n,
            "delta": delta_n,
            "ratio": _ratio(delta_n, control_n),
            "aligned_state_signal": signal,
        }
        for label, control_n, delta_n, signal in rows
    ]


def gate_shipped(change: dict[str, Any]) -> bool:
    return (change.get("grade_delta") or 0) > 0 or bool(change.get("new_defects"))


def gate_cleanliness_worsen(change: dict[str, Any]) -> bool:
    return gate_shipped(change) or (change.get("cleanliness_delta") or 0) > 0


def gate_any_grade_or_cleanliness(change: dict[str, Any]) -> bool:
    return (
        (change.get("grade_delta") or 0) != 0
        or (change.get("cleanliness_delta") or 0) != 0
        or bool(change.get("new_defects"))
    )


def _pool_changes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    material = [row for row in rows if row["material"]]
    cleanliness = [row for row in material if row["kind"] == "cleanliness"]
    worsened = [row for row in material if row["kind"] == "worsened"]
    return {
        "material": len(material),
        "material_detected": sum(1 for row in material if row["detected"]),
        "cleanliness": len(cleanliness),
        "cleanliness_detected": sum(1 for row in cleanliness if row["detected"]),
        "worsened": len(worsened),
        "worsened_detected": sum(1 for row in worsened if row["detected"]),
    }


def _pct(numer: int, denom: int) -> float | None:
    if denom == 0:
        return None
    return round(100.0 * numer / denom, 1)


def _use_case_with_gate(gate: Callable[[dict[str, Any]], bool]):
    base = get_use_case("tenancy")
    assert base.comparison is not None
    return replace(base, comparison=replace(base.comparison, gate=gate))


def rescore_gates(
    dataset_dir: Path,
    review_path: Path,
    model: str = DEFAULT_MODEL,
    prompt_id: str = DEFAULT_PROMPT,
) -> list[dict[str, Any]]:
    """Re-compare cached describes under three tenancy gates; score each."""
    accepted = _accepted_pairs(review_path)
    specs = {spec["id"]: spec for spec, _parent in load_specs(dataset_dir)}
    records_dir = base_records_dir(dataset_dir, model, prompt_id)
    gates: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("as_shipped", gate_shipped),
        ("cleanliness_worsening", gate_cleanliness_worsen),
        ("any_grade_or_cleanliness", gate_any_grade_or_cleanliness),
    ]
    rubric = OfflineRubric()
    pooled: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in gates}
    false_by_gate: dict[str, int] = {name: 0 for name, _ in gates}
    reported_by_gate: dict[str, int] = {name: 0 for name, _ in gates}

    for delta_id in accepted:
        spec = specs[delta_id]
        record_a = _json(records_dir / f"{delta_id}.T0.json")
        record_b = _json(records_dir / f"{delta_id}.T1.json")
        inv_a = inventory_from_record(record_a)
        inv_b = inventory_from_record(record_b)
        for gate_name, gate in gates:
            comparison = compare_inventories(
                inv_a,
                inv_b,
                rubric=rubric,
                use_case=_use_case_with_gate(gate),
            )
            report = score_delta(comparison, [spec])
            pooled[gate_name].extend(report["changes"])
            false_by_gate[gate_name] += report["counts"]["false_changes"]
            reported_by_gate[gate_name] += report["counts"]["reported_changes"]

    results = []
    for gate_name, _ in gates:
        pool = _pool_changes(pooled[gate_name])
        results.append(
            {
                "gate": gate_name,
                "cleanliness_recall": _pct(
                    pool["cleanliness_detected"], pool["cleanliness"]
                ),
                "worsened_recall": _pct(pool["worsened_detected"], pool["worsened"]),
                "delta_recall": _pct(
                    pool["material_detected"], pool["material"]
                ),
                "false_change_rate": _pct(
                    false_by_gate[gate_name], reported_by_gate[gate_name]
                ),
                "counts": {
                    **pool,
                    "false_changes": false_by_gate[gate_name],
                    "reported_changes": reported_by_gate[gate_name],
                },
            }
        )
    return results


def build_report(dataset_dir: Path) -> dict[str, Any]:
    reports = dataset_dir / "reports"
    phase0 = _json(reports / PHASE0_REPORT)
    delta_score = _json(reports / DELTA_SCORE_REPORT)
    review_path = reports / DELTA_REVIEW
    ratios = signal_ratios(phase0)
    gates = rescore_gates(dataset_dir, review_path)
    all_pairs = delta_score["all_pairs"]
    return {
        "schema_version": 1,
        "record_type": "compare_check",
        "created_at": _utc_now(),
        "pairs": 27,
        "sources": {
            "phase0": PHASE0_REPORT,
            "delta_score": DELTA_SCORE_REPORT,
            "delta_review": DELTA_REVIEW,
            "describe_records": (
                "outputs/delta/antigravity-cli/gemini-3.5-flash-low/production-v1/"
            ),
        },
        "headline": {
            "note": (
                "Aligned-item state separates from the noise floor; schedule "
                "membership does not. false_change_rate remains dominated by "
                "membership churn and is not the compare-check headline."
            ),
            "items_reported_changed_ratio": next(
                row["ratio"]
                for row in ratios
                if row["label"] == "Items reported changed"
            ),
            "condition_disagreement_ratio": next(
                row["ratio"]
                for row in ratios
                if row["label"] == "Condition disagreements"
            ),
            "cleanliness_disagreement_ratio": next(
                row["ratio"]
                for row in ratios
                if row["label"] == "Cleanliness disagreements"
            ),
            "delta_recall_pct": all_pairs["metrics"]["delta_recall"],
            "false_change_rate_pct": all_pairs["metrics"]["false_change_rate"],
        },
        "signal_ratios": ratios,
        "noise_floor": phase0["gate"],
        "delta_score_summary": {
            "metrics": all_pairs["metrics"],
            "counts": all_pairs["counts"],
            "by_change_kind": delta_score["by_change_kind"],
            "false_change_decomposition": delta_score["false_change_decomposition"],
            "missed_condition_attribution": delta_score["missed_condition_attribution"],
        },
        "cleanliness_gate_sensitivity": gates,
        "evidence_class": (
            "Synthetic development evidence. Delta pairs cannot promote compare "
            "behaviour; that is gated on real check-in/check-out evidence "
            "(docs/08)."
        ),
    }


def write_results_note(dataset_dir: Path, report: dict[str, Any]) -> Path:
    ratios = report["signal_ratios"]
    gates = report["cleanliness_gate_sensitivity"]
    kind = report["delta_score_summary"]["by_change_kind"]
    decomp = report["delta_score_summary"]["false_change_decomposition"]
    lines = [
        "# Compare check results",
        "",
        f"Recorded {report['created_at']}.",
        "",
        "## Set",
        "",
        "Twenty-seven review-accepted GPT Image 2 delta pairs (Phase 3.5), "
        "scored against committed describe records. No new generation or describe.",
        "",
        "## Method",
        "",
        "- Instrument: product `compare_inventories` on cached T0/T1 describes "
        "(gemini-3.5-flash-low / production-v1).",
        "- Noise floor: Phase 0 repeat-describe control (same frames twice).",
        "- Headline: aligned-item state signal (condition / cleanliness / items "
        "reported changed) versus that floor — not `false_change_rate` alone.",
        "- Readout: diagnostics only — no pass bar. Promotes nothing (docs/08).",
        "",
        "## Signal versus noise",
        "",
        "| Quantity | Control | Delta | Ratio |",
        "|---|---:|---:|---:|",
    ]
    for row in ratios:
        mark = " ← signal" if row["aligned_state_signal"] else ""
        lines.append(
            f"| {row['label']} | {row['control']} | {row['delta']} | "
            f"{row['ratio']}×{mark} |"
        )
    lines.extend(
        [
            "",
            "Schedule membership (naming / unpaired / membership churn) sits at "
            "~1× the control. Aligned-item state does not: items reported changed "
            f"**{report['headline']['items_reported_changed_ratio']}×**, "
            f"cleanliness disagreements "
            f"**{report['headline']['cleanliness_disagreement_ratio']}×**, "
            f"condition disagreements "
            f"**{report['headline']['condition_disagreement_ratio']}×**.",
            "",
            "## Scored gold changes",
            "",
            f"- Delta recall: **{report['headline']['delta_recall_pct']}%** "
            f"({report['delta_score_summary']['counts']['material_changes_detected']} / "
            f"{report['delta_score_summary']['counts']['material_changes']})",
            f"- False-change rate (membership-dominated): "
            f"**{report['headline']['false_change_rate_pct']}%**",
            (
                f"- Of {decomp['counts']['false_changes']} false changes: "
                f"{decomp['counts']['alignment_churn']} alignment churn, "
                f"{decomp['counts']['unpaired_removed']} unpaired removals, "
                f"{decomp['counts']['unpaired_added']} unpaired additions, "
                f"{decomp['counts']['changed_bucket']} in the changed bucket"
            ),
            "",
            "| Kind | Gold | Detected | Recall |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, entry in kind.items():
        lines.append(
            f"| {name} | {entry['gold']} | {entry['detected']} | {entry['recall']}% |"
        )
    lines.extend(
        [
            "",
            "## Cleanliness gate (product diagnostic)",
            "",
            "Cached records re-compared under three gates. No new describes.",
            "",
            "| Gate | Cleanliness recall | Worsened | Delta recall | False-change rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for gate in gates:
        lines.append(
            f"| {gate['gate']} | {gate['cleanliness_recall']}% | "
            f"{gate['worsened_recall']}% | {gate['delta_recall']}% | "
            f"{gate['false_change_rate']}% |"
        )
    lines.extend(
        [
            "",
            "The shipped tenancy gate ignores cleanliness-only worsenings. "
            "Widening it is a product decision (deposit cleaning claims), not an "
            "eval one.",
            "",
            "## Stop",
            "",
            "Compare check measurement is complete. The instrument works on "
            "aligned-item state; schedule-membership noise dominates "
            "`false_change_rate`. Further synthetic compare work is backlog "
            "(naming alignment, cleanliness gate product decision, real "
            "check-in/out transfer) — see the synthetic backlog plan.",
            "",
            "## Artifacts",
            "",
            f"- Score JSON: `reports/compare-check-score-2026-08-06.json`",
            f"- Sources: `{PHASE0_REPORT}`, `{DELTA_SCORE_REPORT}`",
            "",
        ]
    )
    out = dataset_dir / "reports" / "compare-check-results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    report = build_report(args.dataset_dir)
    score_path = args.dataset_dir / "reports" / "compare-check-score-2026-08-06.json"
    score_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    note = write_results_note(args.dataset_dir, report)
    print(f"wrote {score_path}")
    print(f"wrote {note}")
    print(json.dumps(report["headline"], indent=2))
    print(json.dumps(report["cleanliness_gate_sensitivity"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
