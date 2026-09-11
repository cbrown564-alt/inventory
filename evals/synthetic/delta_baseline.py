#!/usr/bin/env python3
"""The 27 delta pairs as a regression gate, not a report (docs/36 §6.4).

docs/35 calls the scored pairs "a regression baseline now that they are
scored", and adds that their value dies if the pairs are regenerated or the
gold is edited to suit a result. Neither half had any enforcement: nothing
re-ran them, and nothing pinned the gold. This supplies both.

What is actually re-run matters. The describes are not — they are metered
Antigravity calls and their records are committed. What is re-run is
**everything downstream of them**: ``compare_inventories`` against the cached
schedules, then ``score_delta`` against the specs. That is precisely the
surface a change to ``homeinventory/compare.py`` moves, and the only product
code the whole synthetic programme has moved so far (``match_score`` tier 1,
5 Aug) lives inside it. The gate is free, offline, and catches the regression
the baseline exists to catch.

The gold digest is the other half. It covers every scored spec's ``changes``,
``observed_changes`` and ``retracted_changes`` — the three lists the score is
computed against — so editing gold to make a number go green fails the gate
instead of moving it. Editing gold *legitimately* is still allowed; it just
has to be a deliberate act that updates the pin in the same commit, which is
the difference between a correction and a quiet re-baseline.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

#: The gold-bearing lists. A spec's prose, its view list and its provenance can
#: change without changing what the pairs are scored against; these cannot.
GOLD_FIELDS = ("changes", "observed_changes", "retracted_changes")


def gold_digest(dataset_dir: Path, delta_ids: list[str]) -> str:
    """One hash over the gold the named pairs are scored against.

    Computed from the specs on disk rather than from the committed score
    report, so a gold edit that nobody re-scored is still caught.
    """
    payload = []
    for delta_id in sorted(delta_ids):
        spec_path = dataset_dir / "deltas" / f"{delta_id}.json"
        if not spec_path.is_file():
            raise FileNotFoundError(
                f"{spec_path}: scored pair {delta_id} has no delta specification"
            )
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        payload.append(
            {"id": delta_id, **{field: spec.get(field) for field in GOLD_FIELDS}}
        )
    rendered = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def rederive(
    dataset_dir: Path,
    review_path: Path,
    summary_path: Path | None,
    model: str,
    prompt_id: str,
) -> dict[str, Any]:
    """Recompute compare and score from the cached describe records.

    Deliberately not a read of ``reports/delta-compare/``. Those comparisons
    were produced by the compare surface as it stood on 5 Aug; reading them
    back would gate the numbers against themselves and pass for any change to
    ``compare_inventories`` whatsoever.
    """
    from evals.synthetic import aggregate_delta_scores
    from evals.synthetic.run_delta_eval import (
        SIDES,
        _accepted_pairs,
        _delta_rows,
        _json,
        compare_pair,
    )

    accepted = _accepted_pairs(review_path)
    by_delta = _delta_rows(dataset_dir)
    records_dir = (
        dataset_dir / "outputs" / "delta" / "antigravity-cli" / model / prompt_id
    )

    with tempfile.TemporaryDirectory(prefix="delta-baseline-") as tmp:
        comparison_dir = Path(tmp)
        for delta_id in accepted:
            views = by_delta.get(delta_id)
            if not views:
                raise ValueError(f"{delta_id}: accepted by review but not in the ledger")
            any_row = next(iter(views.values()))
            records = {}
            for side in SIDES:
                path = records_dir / f"{delta_id}.{side}.json"
                if not path.is_file():
                    raise FileNotFoundError(
                        f"{path}: no cached describe for {delta_id} {side}. The "
                        "baseline re-scores committed records; it does not call "
                        "a backend."
                    )
                records[side] = _json(path)
            pair = {
                "delta_id": delta_id,
                "delta_class": any_row["delta_class"],
                "parent_scenario_id": any_row["parent_scenario_id"],
                "parent_split": any_row["parent_split"],
                "room_type": any_row["room_type"],
                "image_model": any_row["model_display_name"],
            }
            result = compare_pair(pair, records)
            (comparison_dir / f"{delta_id}.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return aggregate_delta_scores.build_report(
            dataset_dir, comparison_dir, review_path, summary_path
        )


def _by_kind_recall(report: dict[str, Any]) -> dict[str, float]:
    return {
        kind: data["recall"]
        for kind, data in report.get("by_change_kind", {}).items()
        if data.get("recall") is not None
    }


def check(spec: dict, resolve) -> list[str]:
    """Hold one delta baseline to its pins; return failure messages.

    ``resolve`` maps a config path to an absolute one, so this shares
    ``ci_gate``'s single notion of where the repo root is.
    """
    name = spec["name"]
    dataset_dir = resolve(spec["dataset_dir"])
    review_path = resolve(spec["review"])
    summary_path = resolve(spec["summary"]) if spec.get("summary") else None

    for label, path in (("dataset dir", dataset_dir), ("review", review_path)):
        if not path.exists():
            return [f"{name}: missing {label} {path}"]

    report = rederive(
        dataset_dir,
        review_path,
        summary_path,
        spec.get("model", "gemini-3.5-flash-low"),
        spec.get("prompt", "production-v1"),
    )
    failures: list[str] = []

    scored = report["pairs_scored"]
    expected_pairs = spec.get("pairs_scored")
    if expected_pairs is not None and scored != expected_pairs:
        # A shrinking denominator moves every rate without any of them being a
        # regression, so it is checked before the rates are read.
        failures.append(
            f"{name}: scored {scored} pairs, baseline is {expected_pairs}. "
            "The pairs changed, so the metrics below are not comparable."
        )

    digest = gold_digest(
        dataset_dir, [pair["delta_id"] for pair in report["per_pair"]]
    )
    if digest != spec["gold_sha256"]:
        failures.append(
            f"{name}: gold digest {digest} does not match the pinned "
            f"{spec['gold_sha256']}. The delta specifications' changes, "
            "observed_changes or retracted_changes were edited. If the edit is "
            "a correction, re-pin it in the same commit and say why."
        )

    metrics = dict(report["all_pairs"]["metrics"])
    metrics.update(
        {f"recall_{kind}": value for kind, value in _by_kind_recall(report).items()}
    )

    for metric, floor in spec.get("floors", {}).items():
        value = metrics.get(metric)
        if value is None:
            failures.append(f"{name}: {metric} is not in the re-derived report")
        elif value < floor:
            failures.append(f"{name}: {metric} {value} < floor {floor}")

    for metric, ceiling in spec.get("ceilings", {}).items():
        value = metrics.get(metric)
        if value is None:
            failures.append(f"{name}: {metric} is not in the re-derived report")
        elif value > ceiling:
            failures.append(f"{name}: {metric} {value} > ceiling {ceiling}")

    if not failures:
        pinned = sorted(set(spec.get("floors", {})) | set(spec.get("ceilings", {})))
        summary = {metric: metrics[metric] for metric in pinned if metric in metrics}
        print(f"OK  {name}: {json.dumps(summary, sort_keys=True)}")
    return failures
