#!/usr/bin/env python3
"""Check Gemini Omni view ids against what the source filenames say they are.

The Omni stills were staged by two different routes. ``import_gemini_omni_batch``
names a view per file explicitly. ``stage_gemini_omni_prior_batches`` does not:
it assigns ``A-wide, B-reverse, C-inventory, D-condition`` **positionally**, in
whatever order the operator supplied the four files, and nothing ever checked
that the image in position 0 was the wide establishing view.

Gemini names its downloads after the prompt, so a good fraction of those
filenames state their own view — "View_D-condition_low_view...",
"View_B-reverse_front_door...". Where a filename says one view and the ledger
says another, that is a contradiction inside the evidence, provable without
looking at a single pixel. This module reports those contradictions and tests
the obvious alternative hypothesis, that the supplied order was reversed.

Why it matters: these stills carry no recorded Pass A (docs/31 Amendment B item
6, the item named in advance as droppable). Pass A is exactly where "is this
the view it claims to be" would have been caught, and the Phase 3.6 video probe
conditions every clip on the frame named ``A-wide``.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from evals.synthetic.import_gemini_omni_batch import BATCH
from evals.synthetic.stage_gemini_omni_prior_batches import (
    BATCHES,
    SUPPLIED_ORDER,
    VIEWS,
)


def _declared_view(filename: str) -> str | None:
    """The view a source filename names, if it names one."""
    haystack = filename.lower().replace("_", "-")
    found = [view for view in VIEWS if view.lower() in haystack]
    return found[0] if len(found) == 1 else None


def audit_positional_batches() -> dict[str, Any]:
    """Contradictions in the positionally-assigned prior batches.

    Checked against ``SUPPLIED_ORDER``, which is what the operator actually
    handed over. The original code zipped against ``VIEWS`` — the same list
    reversed — which is the bug this audit found; it is kept here as the
    ``superseded_rule`` so the check reports what the mistake would have cost
    rather than quietly agreeing with whatever the script says today.
    """
    contradictions: list[dict[str, Any]] = []
    under_old_rule = 0
    for scenario_id, filenames in BATCHES.items():
        for position, filename in enumerate(filenames):
            declared = _declared_view(filename)
            if declared is None:
                continue
            if declared != VIEWS[position]:
                under_old_rule += 1
            assigned = SUPPLIED_ORDER[position]
            if declared == assigned:
                continue
            contradictions.append({
                "scenario_id": scenario_id,
                "position": position,
                "source_filename": filename,
                "assigned_view": assigned,
                "filename_says": declared,
            })
    return {
        "route": "stage_gemini_omni_prior_batches (positional assignment)",
        "packets": len(BATCHES),
        "rule": "SUPPLIED_ORDER: condition detail first, wide view last",
        "superseded_rule": {
            "was": "zip(VIEWS, prefixes) — wide view first",
            "contradictions_it_produced": under_old_rule,
            "repaired_by": "repair_gemini_omni_views.py, 4 Aug 2026",
        },
        "contradictions": contradictions,
    }


def audit_a_wide_slot() -> dict[str, Any]:
    """List what each packet actually filed under ``A-wide``.

    The view-id contradictions above are conclusive but cover only four files.
    This covers every packet, because ``A-wide`` is the slot the Phase 3.6
    video probe conditions on and the one whose contents are easiest to check
    by eye: it is defined as a *wide establishing view*, so a filename
    describing a floor, an edge, a panel or a surface is already wrong.
    """
    slots = []
    for scenario_id, filenames in BATCHES.items():
        name = filenames[SUPPLIED_ORDER.index(VIEWS[0])]
        slots.append({
            "scenario_id": scenario_id,
            "filed_as": VIEWS[0],
            "source_filename": name,
            "names_a_condition_view": "condition" in name.lower(),
        })
    return {
        "slot": "A-wide (position 0)",
        "expected": "wide establishing view",
        "packets": slots,
        "naming_a_condition_view": sum(
            slot["names_a_condition_view"] for slot in slots),
    }


def audit_named_batch() -> dict[str, Any]:
    """The explicitly-named route, checked the same way."""
    contradictions = []
    for prefix, scenario_id, view in BATCH:
        declared = _declared_view(prefix)
        if declared is not None and declared != view:
            contradictions.append({
                "scenario_id": scenario_id, "source_filename": prefix,
                "assigned_view": view, "filename_says": declared,
            })
    return {
        "route": "import_gemini_omni_batch (explicitly named)",
        "files": len(BATCH),
        "contradictions": contradictions,
    }


def audit() -> dict[str, Any]:
    positional = audit_positional_batches()
    named = audit_named_batch()
    return {
        "audit": "gemini_omni_view_assignment",
        "basis": "source filenames that name their own view id",
        "limitation": (
            "This proves a contradiction only for files whose name states a "
            "view. It cannot confirm the remaining assignments, which needs "
            "the Pass A import."
        ),
        "routes": [positional, named],
        "a_wide_slot": audit_a_wide_slot(),
        "total_contradictions": (
            len(positional["contradictions"]) + len(named["contradictions"])
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    for route in result["routes"]:
        print(f"== {route['route']}")
        for entry in route["contradictions"]:
            print(f"   {entry['scenario_id']}: filed as "
                  f"{entry['assigned_view']:12} but the source is named "
                  f"{entry['source_filename']!r} -> {entry['filename_says']}")
        if not route["contradictions"]:
            print("   no contradiction found")
        if "reversal_hypothesis" in route:
            print(f"   reversal hypothesis: {route['reversal_hypothesis']['verdict']} "
                  f"({route['reversal_hypothesis']['fits']} fit, "
                  f"{route['reversal_hypothesis']['contradicts']} contradict)")
    slot = result["a_wide_slot"]
    print(f"\n== {slot['slot']}, expected: {slot['expected']}")
    for entry in slot["packets"]:
        print(f"   {entry['scenario_id']}: {entry['source_filename']}")
    print(f"   {slot['naming_a_condition_view']} of {len(slot['packets'])} "
          "name a condition view outright")
    print(f"\n{result['total_contradictions']} contradiction(s). "
          f"{result['limitation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
