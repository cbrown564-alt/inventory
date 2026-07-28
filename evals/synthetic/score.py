#!/usr/bin/env python3
"""Score cached Phase 1 outputs against verified observed-evidence labels."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from evals.run_eval import name_match
from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.prompts import PROMPTS


MATCH_THRESHOLD = 0.6
DEFECT_WORDS = {
    "chip", "chips", "chipped", "crack", "cracks", "cracked", "scuff",
    "scuffs", "scuffed", "scratch", "scratches", "scratched", "stain",
    "stains", "stained", "mould", "mold", "damp", "damage", "damaged",
    "limescale", "scale", "discoloured", "loose", "dent", "dented",
    "indentation", "wear", "worn",
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _tokens(value: str) -> set[str]:
    return set(_norm(value).split())


def _assign(
    predictions: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[int, tuple[float, int]]:
    pairs: list[tuple[float, int, int]] = []
    for claim_index, claim in enumerate(claims):
        gold = {
            "name": claim["canonical_name"],
            "aliases": claim.get("aliases", []),
        }
        for prediction_index, prediction in enumerate(predictions):
            score = name_match(prediction["name"], gold)
            if score >= MATCH_THRESHOLD:
                pairs.append((score, claim_index, prediction_index))
    pairs.sort(reverse=True)
    matched: dict[int, tuple[float, int]] = {}
    used_predictions: set[int] = set()
    for score, claim_index, prediction_index in pairs:
        if claim_index in matched or prediction_index in used_predictions:
            continue
        matched[claim_index] = (score, prediction_index)
        used_predictions.add(prediction_index)
    return matched


def _defect_found(prediction: dict[str, Any], gold_defect: dict[str, Any]) -> bool:
    predicted = " ".join(
        [prediction.get("description", ""), *prediction.get("defects", [])]
    )
    gold = f"{gold_defect['wording']} {gold_defect['location']}"
    gold_terms = _tokens(gold) & DEFECT_WORDS
    return bool(gold_terms & _tokens(predicted))


def _defect_prediction_matches(
    prediction: dict[str, Any],
    gold_defect: dict[str, Any],
    gold_frames: set[str],
) -> bool:
    """Match a visible defect even when the model groups the affected item."""
    predicted_frames = set(prediction.get("photo_ids") or [])
    return bool(
        predicted_frames & gold_frames
        and _defect_found(prediction, gold_defect)
    )


def _negative_terms(wording: str) -> set[str]:
    return _tokens(wording) & DEFECT_WORDS


def score_run(record: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    predictions = record["parsed_output"]["items"]
    claims = review["pass_b"]["claims"]
    accepted_frames = {
        frame["frame_id"]
        for frame in review["pass_a"]["frames"]
        if frame["decision"] == "accepted"
    }
    matches = _assign(predictions, claims)
    used_predictions = {prediction_index for _, prediction_index in matches.values()}

    missed_claims = []
    evidence_failures = []
    gold_defects = []
    found_defects = []
    unsupported_defects = []
    exactish = 0
    evidence_correct = 0
    for claim_index, claim in enumerate(claims):
        if claim_index not in matches:
            missed_claims.append(claim["canonical_name"])
            for defect in claim.get("defects", []):
                gold_entry = {"item": claim["canonical_name"], **defect}
                gold_defects.append(gold_entry)
                if any(
                    _defect_prediction_matches(
                        prediction,
                        defect,
                        set(claim["evidence_frame_ids"]),
                    )
                    for prediction in predictions
                ):
                    found_defects.append(gold_entry)
            continue
        score, prediction_index = matches[claim_index]
        prediction = predictions[prediction_index]
        if score >= 0.85:
            exactish += 1
        predicted_frames = set(prediction.get("photo_ids") or [])
        gold_frames = set(claim["evidence_frame_ids"])
        if (
            predicted_frames
            and predicted_frames <= accepted_frames
            and predicted_frames & gold_frames
        ):
            evidence_correct += 1
        else:
            evidence_failures.append(
                {
                    "item": claim["canonical_name"],
                    "predicted_photo_ids": sorted(predicted_frames),
                    "gold_photo_ids": sorted(gold_frames),
                }
            )

        for defect in claim.get("defects", []):
            gold_entry = {"item": claim["canonical_name"], **defect}
            gold_defects.append(gold_entry)
            if any(
                _defect_prediction_matches(
                    candidate,
                    defect,
                    set(claim["evidence_frame_ids"]),
                )
                for candidate in predictions
            ):
                found_defects.append(gold_entry)

        if not claim.get("defects"):
            for defect in prediction.get("defects", []):
                if _tokens(defect) & DEFECT_WORDS:
                    unsupported_defects.append(
                        {
                            "item": prediction["name"],
                            "defect": defect,
                            "photo_ids": prediction.get("photo_ids", []),
                        }
                    )

    unmatched_predictions = [
        predictions[index]
        for index in range(len(predictions))
        if index not in used_predictions
    ]
    for prediction in unmatched_predictions:
        for defect in prediction.get("defects", []):
            defect_terms = _tokens(defect) & DEFECT_WORDS
            supports_found_gold = any(
                defect_terms & _tokens(found["wording"])
                and set(prediction.get("photo_ids") or [])
                & {
                    frame
                    for claim in claims
                    if claim["canonical_name"] == found["item"]
                    for frame in claim["evidence_frame_ids"]
                }
                for found in found_defects
            )
            if defect_terms and not supports_found_gold:
                unsupported_defects.append(
                    {
                        "item": prediction["name"],
                        "defect": defect,
                        "photo_ids": prediction.get("photo_ids", []),
                    }
                )

    found_support = []
    for found in found_defects:
        claim = next(
            claim
            for claim in claims
            if claim["canonical_name"] == found["item"]
        )
        found_support.append(
            {
                "terms": _tokens(found["wording"]) & DEFECT_WORDS,
                "frames": set(claim["evidence_frame_ids"]),
            }
        )
    unsupported_defects = [
        defect
        for defect in unsupported_defects
        if not any(
            (_tokens(defect["defect"]) & support["terms"])
            and (set(defect.get("photo_ids") or []) & support["frames"])
            for support in found_support
        )
    ]

    negative_false_positives = []
    for negative in review["pass_b"]["negative_controls"]:
        terms = _negative_terms(negative["wording"])
        negative_frames = set(negative["evidence_frame_ids"])
        relevant_defect_tokens = set()
        for prediction in predictions:
            if set(prediction.get("photo_ids") or []) & negative_frames:
                relevant_defect_tokens |= _tokens(
                    " ".join(prediction.get("defects", []))
                )
        if terms & relevant_defect_tokens:
            negative_false_positives.append(negative["wording"])

    duplicate_names = [
        name
        for name, count in Counter(_norm(item["name"]) for item in predictions).items()
        if count > 1
    ]

    def pct(numerator: int, denominator: int) -> float | None:
        return round(100 * numerator / denominator, 1) if denominator else None

    usage = record.get("usage") or {}
    return {
        "run_id": record["run_id"],
        "scenario_id": record["scenario_id"],
        "room_type": record["room_type"],
        "image_provider": record.get("image_provider"),
        "image_model": record.get("image_model"),
        "architecture_id": record.get("architecture_id"),
        "prompt_id": record["prompt_id"],
        "item_recall_against_reviewed_gold": pct(len(matches), len(claims)),
        "naming_accuracy": pct(exactish, len(matches)),
        "defect_recall": pct(len(found_defects), len(gold_defects)),
        "evidence_link_accuracy": pct(evidence_correct, len(matches)),
        "unsupported_item_rate_against_reviewed_gold": pct(
            len(unmatched_predictions), len(predictions)
        ),
        "duplicate_rate": pct(len(duplicate_names), len(predictions)),
        "negative_control_false_positive_rate": pct(
            len(negative_false_positives),
            len(review["pass_b"]["negative_controls"]),
        ),
        "counts": {
            "reviewed_gold_items": len(claims),
            "matched_items": len(matches),
            "predicted_items": len(predictions),
            "gold_defects": len(gold_defects),
            "found_defects": len(found_defects),
            "unsupported_defects": len(unsupported_defects),
            "negative_controls": len(review["pass_b"]["negative_controls"]),
            "negative_false_positives": len(negative_false_positives),
        },
        "row_failures": {
            "missed_claims": missed_claims,
            "unmatched_predictions_need_review": [
                {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "defects": item.get("defects", []),
                    "photo_ids": item.get("photo_ids", []),
                }
                for item in unmatched_predictions
            ],
            "missed_defects": [
                defect for defect in gold_defects if defect not in found_defects
            ],
            "unsupported_defects": unsupported_defects,
            "evidence_link_failures": evidence_failures,
            "negative_control_false_positives": negative_false_positives,
            "duplicate_names": duplicate_names,
        },
        "latency_seconds": record["latency_seconds"],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
            "completion_tokens": usage.get(
                "completion_tokens", usage.get("output_tokens")
            ),
            "total_tokens": usage.get("total_tokens"),
        },
        "estimated_cost_usd": record["estimated_cost"]["amount"],
    }


def _aggregate(
    rows: list[dict[str, Any]],
    prompt_id: str,
    *,
    image_model: str | None = None,
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["prompt_id"] == prompt_id
        and (image_model is None or row["image_model"] == image_model)
    ]
    counts = Counter()
    for row in selected:
        counts.update(row["counts"])

    def pct(numerator: int, denominator: int) -> float | None:
        return round(100 * numerator / denominator, 1) if denominator else None

    prompt_tokens = sum(
        row["usage"]["prompt_tokens"] or 0 for row in selected
    )
    completion_tokens = sum(
        row["usage"]["completion_tokens"] or 0 for row in selected
    )
    return {
        "prompt_id": prompt_id,
        "image_model": image_model,
        "rooms": len(selected),
        "item_recall_against_reviewed_gold": pct(
            counts["matched_items"], counts["reviewed_gold_items"]
        ),
        "defect_recall": pct(counts["found_defects"], counts["gold_defects"]),
        "unsupported_defects": counts["unsupported_defects"],
        "negative_control_false_positive_rate": pct(
            counts["negative_false_positives"], counts["negative_controls"]
        ),
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "latency_seconds": round(
            sum(row["latency_seconds"] for row in selected), 3
        ),
        "estimated_cost_usd": round(
            sum(row["estimated_cost_usd"] or 0 for row in selected), 6
        ),
    }


def build_report(dataset_dir: Path = DEFAULT_DATASET) -> dict[str, Any]:
    reviews = {}
    for path in sorted((dataset_dir / "reviews").glob("RP-*.json")):
        review = _json(path)
        if review.get("review_status") == "verified_synthetic_gold":
            reviews[
                (review["scenario_id"], review["model_display_name"])
            ] = review

    rows = []
    output_root = (
        dataset_dir
        / "outputs"
        / "antigravity-cli"
        / "gemini-3.5-flash-low"
    )
    for path in sorted(output_root.glob("*/*.json")):
        record = _json(path)
        key = (record["scenario_id"], record["image_model"])
        if key not in reviews:
            continue
        rows.append(score_run(record, reviews[key]))
    if not rows:
        raise ValueError("no cached Antigravity outputs have verified gold")
    pair_members = Counter(
        (row["scenario_id"], row["image_model"]) for row in rows
    )
    incomplete = [
        f"{scenario_id}.{image_model}"
        for (scenario_id, image_model), count in pair_members.items()
        if count != len(PROMPTS)
    ]
    if incomplete:
        raise ValueError(
            "prompt pair incomplete for: " + ", ".join(incomplete)
        )

    aggregates = {
        prompt_id: _aggregate(rows, prompt_id) for prompt_id in PROMPTS
    }
    image_models = sorted(
        {row["image_model"] for row in rows if row["image_model"]}
    )
    generator_slices = {
        image_model: {
            prompt_id: _aggregate(
                rows, prompt_id, image_model=image_model
            )
            for prompt_id in PROMPTS
        }
        for image_model in image_models
    }
    paired_rows = []
    for scenario_id, image_model in sorted(pair_members):
        pair = {
            row["prompt_id"]: row
            for row in rows
            if row["scenario_id"] == scenario_id
            and row["image_model"] == image_model
        }
        baseline_row = pair["production-v1"]
        candidate_row = pair["evidence-bounded-coverage-v1"]
        paired_rows.append(
            {
                "scenario_id": scenario_id,
                "image_model": image_model,
                "item_recall_pp": round(
                    candidate_row["item_recall_against_reviewed_gold"]
                    - baseline_row["item_recall_against_reviewed_gold"],
                    1,
                ),
                "defect_recall_pp": round(
                    (candidate_row["defect_recall"] or 0)
                    - (baseline_row["defect_recall"] or 0),
                    1,
                ),
                "unsupported_defects": (
                    candidate_row["counts"]["unsupported_defects"]
                    - baseline_row["counts"]["unsupported_defects"]
                ),
            }
        )
    baseline = aggregates["production-v1"]
    candidate = aggregates["evidence-bounded-coverage-v1"]
    guardrail_passed = (
        candidate["unsupported_defects"] <= baseline["unsupported_defects"]
        and candidate["defect_recall"] >= baseline["defect_recall"]
    )
    return {
        "dataset_id": "synthetic-room-eval",
        "dataset_phase": "phase-1-representative-slice",
        "scope": (
            "Complete verified four-view packets evaluated through the pinned "
            "subscription-backed Antigravity CLI model/mode. No Gemini API "
            "endpoint is used."
        ),
        "metric_limits": [
            "The reviewed claims do not mark a notable subset, so notable recall is not reported.",
            "Unmatched predicted items require human review; the fixture records generator deviations but is not exhaustive enough for a public hallucination claim.",
            "Condition labels are descriptive rather than ordinal grades, so condition agreement is not reported.",
            "This synthetic slice is development evidence, not real-property accuracy evidence.",
        ],
        "rows": rows,
        "aggregates": aggregates,
        "generator_slices": generator_slices,
        "paired_rows": paired_rows,
        "paired_delta_candidate_minus_production": {
            "item_recall_pp": round(
                candidate["item_recall_against_reviewed_gold"]
                - baseline["item_recall_against_reviewed_gold"],
                1,
            ),
            "defect_recall_pp": round(
                candidate["defect_recall"] - baseline["defect_recall"], 1
            ),
            "unsupported_defects": (
                candidate["unsupported_defects"]
                - baseline["unsupported_defects"]
            ),
            "input_tokens": candidate["input_tokens"] - baseline["input_tokens"],
            "output_tokens": (
                candidate["output_tokens"] - baseline["output_tokens"]
            ),
            "latency_seconds": round(
                candidate["latency_seconds"] - baseline["latency_seconds"], 3
            ),
            "estimated_cost_usd": round(
                candidate["estimated_cost_usd"]
                - baseline["estimated_cost_usd"],
                6,
            ),
        },
        "material_claim_guardrail_passed": guardrail_passed,
        "phase_decision": (
            "Phase 1 comparison complete. Treat the result as directional; "
            "freeze no product prompt until the development and validation "
            "sets are complete. Antigravity wrapper results are development "
            "evidence and do not claim raw production-API equivalence."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    aggregates = report["aggregates"]
    lines = [
        "# Phase 1 synthetic prompt comparison",
        "",
        report["scope"],
        "",
        "| Prompt | Item recall | Defect recall | Unsupported defects | "
        "Input tokens | Output tokens | Cost (USD) | Latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for prompt_id in PROMPTS:
        row = aggregates[prompt_id]
        lines.append(
            f"| {prompt_id} | {row['item_recall_against_reviewed_gold']}% | "
            f"{row['defect_recall']}% | {row['unsupported_defects']} | "
            f"{row['input_tokens']} | {row['output_tokens']} | "
            f"${row['estimated_cost_usd']:.6f} | "
            f"{row['latency_seconds']:.3f}s |"
        )
    delta = report["paired_delta_candidate_minus_production"]
    lines.extend(
        [
            "",
            "## Paired direction",
            "",
            f"- Item recall: {delta['item_recall_pp']:+.1f} percentage points.",
            f"- Defect recall: {delta['defect_recall_pp']:+.1f} percentage points.",
            f"- Unsupported defects: {delta['unsupported_defects']:+d}.",
            f"- Estimated cost: ${delta['estimated_cost_usd']:+.6f}.",
            f"- Material-claim guardrail passed: "
            f"{'yes' if report['material_claim_guardrail_passed'] else 'no'}.",
            "",
            "## Limits",
            "",
        ]
    )
    lines.extend(["", "## Generator slices", ""])
    for image_model, prompts in report["generator_slices"].items():
        lines.append(f"### {image_model}")
        lines.append("")
        for prompt_id, row in prompts.items():
            lines.append(
                f"- {prompt_id}: item recall "
                f"{row['item_recall_against_reviewed_gold']}%, defect recall "
                f"{row['defect_recall']}%, unsupported defects "
                f"{row['unsupported_defects']}."
            )
    lines.extend(f"- {limit}" for limit in report["metric_limits"])
    lines.extend(["", "## Row-level failures", ""])
    for row in report["rows"]:
        failures = row["row_failures"]
        lines.append(f"### {row['run_id']}")
        lines.append("")
        lines.append(
            "- Missed reviewed claims: "
            + (", ".join(failures["missed_claims"]) or "none")
        )
        lines.append(
            "- Missed reviewed defects: "
            + (
                "; ".join(
                    f"{item['item']}: {item['wording']}"
                    for item in failures["missed_defects"]
                )
                or "none"
            )
        )
        lines.append(
            "- Defects without reviewed support: "
            + (
                "; ".join(
                    f"{item['item']}: {item['defect']}"
                    for item in failures["unsupported_defects"]
                )
                or "none"
            )
        )
        lines.append(
            "- Evidence-link failures: "
            + (
                ", ".join(
                    item["item"] for item in failures["evidence_link_failures"]
                )
                or "none"
            )
        )
        lines.append(
            "- Unmatched predicted items needing review: "
            + (
                ", ".join(
                    item["name"]
                    for item in failures[
                        "unmatched_predictions_need_review"
                    ]
                )
                or "none"
            )
        )
        lines.append("")
    lines.extend([report["phase_decision"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET
    )
    args = parser.parse_args()
    report = build_report(args.dataset_dir)
    reports_dir = args.dataset_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "phase1-prompt-comparison.json"
    md_path = reports_dir / "phase1-prompt-comparison.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report["aggregates"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
