#!/usr/bin/env python3
"""Write a delta review's gold corrections back into the delta specifications.

A pair review produces two findings the gold cannot express on its own. It
finds enumerated changes that are not in the frames — either never rendered,
or asserting a T0 state the reference never showed — and it finds real
differences nobody enumerated. Both distort scoring in opposite directions:
the first costs recall for an absence and invites a false change, the second
charges a false change for reporting what is plainly there.

Neither can be fixed by editing ``changes``. That list is the frozen
generation prompt of an image that already exists, and its hash pins the
frame's provenance. So corrections go to two side lists — ``retracted_changes``
and ``observed_changes`` — and this script verifies afterwards that every
prompt hash in the ledger still matches the prompt the specs produce. If a
correction ever reached the prompt path, that check fails and nothing is
written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_delta_tasks import (
    RETRACTED_CHANGES_FIELD,
    RETRACTION_ISSUES,
    build_prompt,
    load_specs,
    validate_spec,
)
from evals.synthetic.build_tasks import DEFAULT_DATASET

#: Framing notes are review context, not changes in the room. Recording "the
#: T1 view is slightly closer" as gold would invite a compare run to report a
#: camera move as a property change and be scored right for it.
NON_OBJECT_TARGETS = {"camera"}


def _dump_spec(spec: dict[str, Any]) -> str:
    """Serialise a delta spec the way the delta specs are written by hand.

    ``json.dumps(indent=2)`` explodes every change onto seven lines, so a
    two-line correction arrives as a 78-line diff and the reviewer cannot see
    what changed. These files are read as evidence; the diff is the audit.
    """
    lines = ["{"]
    items = list(spec.items())
    for index, (key, value) in enumerate(items):
        tail = "," if index < len(items) - 1 else ""
        if isinstance(value, list) and value and all(
            isinstance(entry, dict) for entry in value
        ):
            lines.append(f"  {json.dumps(key)}: [")
            for position, entry in enumerate(value):
                comma = "," if position < len(value) - 1 else ""
                lines.append(
                    "    " + json.dumps(entry, ensure_ascii=False) + comma
                )
            lines.append(f"  ]{tail}")
        else:
            rendered = json.dumps(value, ensure_ascii=False)
            lines.append(f"  {json.dumps(key)}: {rendered}{tail}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _observed_from(pair: dict[str, Any]) -> list[dict[str, Any]]:
    """Incidental differences, as gold that is real but not required.

    They are written ``immaterial``: a compare run that reports one is not
    inventing a change, and one that stays quiet has not missed a required
    detection. That is exactly the standing of a tea towel that moved.
    """
    return [
        difference
        for difference in pair.get("incidental_differences") or []
        if difference.get("target") not in NON_OBJECT_TARGETS
    ]


def plan(
    dataset_dir: Path,
    review_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    source = review_path.name
    specs = {spec["id"]: spec for spec, _ in load_specs(dataset_dir)}
    edits: list[dict[str, Any]] = []
    issues: Counter[str] = Counter()

    for pair in review["pairs"]:
        delta_id = pair["delta_id"]
        spec = specs.get(delta_id)
        if spec is None:
            raise ValueError(f"{delta_id}: no delta specification found")
        existing_retractions = {
            item["id"] for item in spec.get(RETRACTED_CHANGES_FIELD) or []
        }
        retractions = []
        for correction in pair.get("gold_corrections") or []:
            if correction["issue"] not in RETRACTION_ISSUES:
                # e.g. spec_contradiction: a wording problem in the
                # unchanged assertions, which no side list can repair.
                issues[f"skipped:{correction['issue']}"] += 1
                continue
            if correction["change_id"] in existing_retractions:
                continue
            retractions.append({
                "id": correction["change_id"],
                "issue": correction["issue"],
                "reason": correction["recommendation"],
                "source": source,
                "retracted_at": review.get("completed_at"),
            })
            issues[correction["issue"]] += 1

        used = {change["id"] for change in spec["changes"]}
        used.update(item["id"] for item in spec.get("observed_changes") or [])
        described = {
            item["description"] for item in spec.get("observed_changes") or []
        }
        observed = []
        for difference in _observed_from(pair):
            if difference["description"] in described:
                continue
            index = len(observed) + 1
            while f"O{index}" in used:
                index += 1
            change_id = f"O{index}"
            used.add(change_id)
            observed.append({
                "id": change_id,
                "kind": "immaterial",
                "target": difference["target"],
                "description": difference["description"],
                "material": False,
                "source": source,
            })
            issues["observed"] += 1

        if retractions or observed:
            edits.append({
                "delta_id": delta_id,
                "retractions": retractions,
                "observed": observed,
            })
    return edits, {"counts": dict(sorted(issues.items())), "source": source}


def _prompt_hashes(dataset_dir: Path) -> dict[str, str]:
    """Every delta prompt hash the current specs produce, by task id."""
    with (dataset_dir / "delta_tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    parents = {}
    specs = {}
    for spec, parent in load_specs(dataset_dir):
        specs[spec["id"]] = spec
        parents[spec["id"]] = parent
    hashes = {}
    for row in rows:
        spec = specs[row["delta_id"]]
        parent = parents[row["delta_id"]]
        view = next(
            item for item in parent["views"] if item["id"] == row["view_id"]
        )
        reference_name = Path(row["reference_path"]).name
        prompt = build_prompt(spec, parent, view, reference_name)
        hashes[row["task_id"]] = hashlib.sha256(prompt.encode()).hexdigest()
    return hashes


def apply(
    dataset_dir: Path,
    review_path: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    before = _prompt_hashes(dataset_dir)
    edits, summary = plan(dataset_dir, review_path)
    reformatted: list[str] = []
    for edit in edits:
        path = dataset_dir / "deltas" / f"{edit['delta_id']}.json"
        original = path.read_text(encoding="utf-8")
        spec = json.loads(original)
        style_preserved = _dump_spec(spec) == original
        if not style_preserved:
            reformatted.append(edit["delta_id"])
        if edit["retractions"]:
            spec.setdefault(RETRACTED_CHANGES_FIELD, []).extend(edit["retractions"])
        if edit["observed"]:
            spec.setdefault("observed_changes", []).extend(edit["observed"])
        path.write_text(
            _dump_spec(spec) if style_preserved
            else json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    for spec, parent in load_specs(dataset_dir):
        validate_spec(spec, parent)
    after = _prompt_hashes(dataset_dir)
    moved = sorted(task_id for task_id, value in before.items() if after[task_id] != value)
    if moved:
        raise RuntimeError(
            "gold corrections changed a generation prompt hash, which orphans "
            f"the rendered frame from its provenance: {moved}"
        )
    report = {
        "schema_version": 1,
        "record_type": "phase35_delta_gold_corrections_applied",
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "review": summary["source"],
        "specs_edited": [edit["delta_id"] for edit in edits],
        "counts": summary["counts"],
        "prompt_hashes_unchanged": True,
        "specs_reformatted": reformatted,
        "note": (
            "Retractions and observed changes never reach build_prompt, so "
            "every rendered frame keeps the prompt hash it was made under."
        ),
        "edits": edits,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        edits, summary = plan(args.dataset_dir, args.review)
        print(json.dumps({
            "record_type": "phase35_delta_gold_corrections_preflight",
            "specs_to_edit": len(edits),
            "counts": summary["counts"],
            "edits": edits,
        }, indent=2, ensure_ascii=False))
        return 0
    report = apply(args.dataset_dir, args.review, args.report)
    print(json.dumps({
        "specs_edited": len(report["specs_edited"]),
        "counts": report["counts"],
        "prompt_hashes_unchanged": report["prompt_hashes_unchanged"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
