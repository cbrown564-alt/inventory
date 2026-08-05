#!/usr/bin/env python3
"""Merge resumable Phase 3.5 pilot review reports without inventing review evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def merge(
    base_path: Path,
    part_paths: list[Path],
    owner_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    base = _load(base_path)
    reports = [base, *(_load(path) for path in part_paths)]
    pairs: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    independent_ai_pairs = 0
    for report in reports:
        if report.get("status") not in {"partial", "complete"}:
            raise ValueError(f"unsupported review status: {report.get('status')}")
        for pair in report.get("pairs", []):
            delta_id = pair["delta_id"]
            if delta_id in seen:
                raise ValueError(f"duplicate reviewed pair: {delta_id}")
            seen.add(delta_id)
            pairs.append(pair)
            independent_ai_pairs += 1

    # Merge calls with their owning report so every provenance record retains
    # its source, including the partial reports that were resumed or split.
    calls = []
    for path, report in zip([base_path, *part_paths], reports):
        calls.extend({"source_report": str(path), **call}
                     for call in report.get("calls", []))

    owner = _load(owner_path)
    owner_id = owner["delta_id"]
    if owner_id in seen:
        raise ValueError(f"owner adjudication duplicates reviewed pair: {owner_id}")
    if owner.get("decision") not in {"accept", "reject", "escalate"}:
        raise ValueError(f"invalid owner decision: {owner.get('decision')}")
    pairs.append({
        "delta_id": owner_id,
        "delta_class": "temporal",
        "decision": owner["decision"],
        "decision_basis": "owner adjudication; independent AI quota exception",
        "reviewers_agreed": None,
        "unenumerated_material_changes": [
            change for change in owner.get("unenumerated_changes", [])
            if change.get("material") is not False
        ],
        "missing_material_changes": [
            entry["change_id"] for entry in owner["enumerated"]
            if entry["visibility"] == "absent"
        ],
        "owner_adjudication": owner,
    })
    if len(pairs) != 30:
        raise ValueError(f"expected 30 pilot pairs, found {len(pairs)}")
    pairs.sort(key=lambda pair: pair["delta_id"])
    result = {
        "review_type": "phase35_delta_pair_review",
        "status": "complete",
        "reviewed_at": base.get("reviewed_at"),
        "completed_at": owner.get("adjudicated_at"),
        "generation_path": "Antigravity CLI independent local-image review plus one explicit owner adjudication",
        "metered_api_call": False,
        "reviewer_model_mode": base.get("reviewer_model_mode"),
        "review_proxy_dir": "reports/phase35-pilot-review-proxy-512-2026-08-04",
        "review_proxy_max_width": 512,
        "counts": {
            "accept": sum(pair["decision"] == "accept" for pair in pairs),
            "reject": sum(pair["decision"] == "reject" for pair in pairs),
            "escalate": sum(pair["decision"] == "escalate" for pair in pairs),
        },
        "pairs": pairs,
        "calls": calls,
        "completion": {
            "pilot_pairs": 30,
            "independent_ai_pairs": independent_ai_pairs,
            "owner_only_pairs": 1,
            "owner_only_pair_ids": [owner_id],
            "independent_ai_quota_blocker": True,
            "note": "The owner-only pair is retained as an explicit exception and must not be described as two independent AI reviews.",
        },
    }
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--part", type=Path, action="append", required=True)
    parser.add_argument("--owner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = merge(args.base, args.part, args.owner, args.output)
    print(json.dumps({"status": result["status"], "counts": result["counts"], "completion": result["completion"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
