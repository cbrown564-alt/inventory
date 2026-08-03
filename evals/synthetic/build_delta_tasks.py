#!/usr/bin/env python3
"""Build generation tasks for Phase 3.5 delta pairs.

A delta pair is two renders of one room specification separated by an
enumerated ``changes`` list, plus ``unchanged_assertions`` that make the pair
scorable: without them an unenumerated drift cannot be told apart from a real
change, and the false-change metric means nothing (docs/31 Phase 3.5).

The T0 side is an already-accepted packet from the main pilot. This module
only builds the T1 (or counterfactual) side, and pins the accepted T0 frame as
the reference image so the generator holds room identity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET

#: Delta pairs render two views per timepoint, not four. Four doubles the
#: drift surface for no extra signal at probe scale (docs/31 Phase 3.5).
DELTA_VIEWS = ("A-wide", "D-condition")

DELTA_CLASSES = {"temporal", "counterfactual"}

VALID_CHANGE_KINDS = {
    "new_defect",
    "worsened",
    "improved",
    "item_removed",
    "item_added",
    "cleanliness",
    "immaterial",
}

#: Generation is single-provider from 3 Aug 2026 (docs/31 amendment).
DELTA_PROVIDER = "gpt-image-2"

FIELDNAMES = [
    "task_id", "delta_id", "parent_scenario_id", "delta_class", "timepoint",
    "room_type", "provider", "product", "model_display_name", "view_id",
    "reference_path", "reference_sha256", "output_path", "prompt_sha256",
    "exact_prompt", "status", "attempts", "operator", "generated_at",
    "generator_cli_version", "output_sha256",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_spec(spec: dict[str, Any], parent: dict[str, Any]) -> None:
    """Reject a delta spec that cannot produce scorable gold.

    Raises ``ValueError`` rather than warning: a malformed delta spec yields
    confidently wrong gold, which docs/31 rates worse than no gold at all.
    """
    delta_id = spec.get("id", "<missing id>")
    if spec.get("delta_class") not in DELTA_CLASSES:
        raise ValueError(
            f"{delta_id}: delta_class must be one of {sorted(DELTA_CLASSES)}"
        )
    if spec.get("delta_of") != parent["id"]:
        raise ValueError(f"{delta_id}: delta_of does not match the parent scenario")
    if not spec.get("timepoint"):
        raise ValueError(f"{delta_id}: timepoint is required")

    changes = spec.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError(f"{delta_id}: changes must be a non-empty list")
    seen: set[str] = set()
    for change in changes:
        change_id = change.get("id")
        if not change_id:
            raise ValueError(f"{delta_id}: every change needs an id")
        if change_id in seen:
            raise ValueError(f"{delta_id}: duplicate change id {change_id!r}")
        seen.add(change_id)
        if change.get("kind") not in VALID_CHANGE_KINDS:
            raise ValueError(
                f"{delta_id}.{change_id}: kind must be one of "
                f"{sorted(VALID_CHANGE_KINDS)}"
            )
        for field in ("target", "description"):
            if not change.get(field):
                raise ValueError(f"{delta_id}.{change_id}: {field} is required")
        if not isinstance(change.get("material"), bool):
            raise ValueError(
                f"{delta_id}.{change_id}: material must be an explicit boolean"
            )
        if change["kind"] == "immaterial" and change["material"]:
            raise ValueError(
                f"{delta_id}.{change_id}: immaterial changes cannot be material"
            )

    assertions = spec.get("unchanged_assertions")
    if not isinstance(assertions, list) or not assertions:
        raise ValueError(
            f"{delta_id}: unchanged_assertions must be a non-empty list — "
            "without it the pair cannot be scored for false changes"
        )
    if not any(change["material"] for change in changes):
        raise ValueError(
            f"{delta_id}: at least one change must be material, otherwise the "
            "pair carries no delta signal"
        )


def _change_lines(changes: list[dict[str, Any]]) -> str:
    return " ".join(
        f"({index}) {change['kind'].replace('_', ' ')} — {change['target']}: "
        f"{change['description']}."
        for index, change in enumerate(changes, start=1)
    )


def build_prompt(
    spec: dict[str, Any],
    parent: dict[str, Any],
    view: dict[str, Any],
    reference_name: str,
) -> str:
    """Exact generation prompt for one delta view.

    The prompt is deliberately lopsided: the enumerated changes get one
    sentence, and holding everything else identical gets the rest. Drift is
    the failure mode that silently poisons the gold.
    """
    changes = _change_lines(spec["changes"])
    unchanged = "; ".join(spec["unchanged_assertions"])
    avoid = ", ".join(parent["avoid"])
    horizon = spec.get("elapsed_description", "a single tenancy period")
    return (
        f"Re-photograph the exact room shown in the attached reference image "
        f"{reference_name}. This is the same physical "
        f"{parent['room_type'].lower()} at a later inspection, after "
        f"{horizon}. Reproduce view {view['id']}: {view['viewpoint']}; "
        f"{view['shot_scale']}. "
        "Keep the room identical to the reference in every respect — same "
        "layout, fittings, furniture, finishes, flooring, window, door "
        "positions, camera viewpoint and framing. "
        f"Apply only these changes: {changes} "
        f"Everything else must be unchanged, specifically: {unchanged}. "
        "Introduce no other new object, defect, mark, or alteration of any "
        "kind, and remove nothing that is not listed above. "
        f"Match the reference lighting ({parent['lighting']}) and keep the "
        "look of an ordinary smartphone capture. "
        f"Avoid: {avoid}. "
        "Do not add labels, captions, borders, or inspection annotations. "
        "Do not produce a before/after collage or any side-by-side layout; "
        "return one single photograph."
    )


def load_specs(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return validated ``(spec, parent_scene)`` pairs from ``deltas/``."""
    delta_dir = dataset_dir / "deltas"
    if not delta_dir.is_dir():
        return []
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for spec_path in sorted(delta_dir.glob("*.json")):
        spec = _load(spec_path)
        if delta_ids is not None and spec.get("id") not in delta_ids:
            continue
        parent_path = dataset_dir / "scenarios" / f"{spec.get('delta_of')}.json"
        if not parent_path.is_file():
            raise FileNotFoundError(
                f"{spec.get('id')}: parent scenario {parent_path} does not exist"
            )
        parent = _load(parent_path)
        validate_spec(spec, parent)
        pairs.append((spec, parent))
    return pairs


def build_rows(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    config = _load(dataset_dir / "dataset.json")
    provider = config["providers"][DELTA_PROVIDER]
    extension = provider["file_extension"]
    rows: list[dict[str, str]] = []
    for spec, parent in load_specs(dataset_dir, delta_ids):
        views = {view["id"]: view for view in parent["views"]}
        for view_id in DELTA_VIEWS:
            if view_id not in views:
                raise ValueError(
                    f"{spec['id']}: parent {parent['id']} has no view {view_id}"
                )
            reference = (
                dataset_dir
                / "images"
                / provider["image_directory"]
                / f"{parent['id']}-{view_id}.{extension}"
            )
            if not reference.is_file():
                raise FileNotFoundError(
                    f"{spec['id']}: T0 reference {reference} is missing — a "
                    "delta pair may only be built on an accepted T0 frame"
                )
            prompt = build_prompt(spec, parent, views[view_id], reference.name)
            output = (
                Path("images")
                / provider["image_directory"]
                / "deltas"
                / f"{spec['id']}-{view_id}.{extension}"
            )
            rows.append({
                "task_id": f"{spec['id']}.{DELTA_PROVIDER}.{view_id}",
                "delta_id": spec["id"],
                "parent_scenario_id": parent["id"],
                "delta_class": spec["delta_class"],
                "timepoint": spec["timepoint"],
                "room_type": parent["room_type"],
                "provider": provider["provider"],
                "product": provider["product"],
                "model_display_name": provider["model_display_name"],
                "view_id": view_id,
                "reference_path": reference.relative_to(dataset_dir).as_posix(),
                "reference_sha256": _sha256_file(reference),
                "output_path": output.as_posix(),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "exact_prompt": prompt,
                "status": "pending",
                "attempts": "0",
                "operator": "",
                "generated_at": "",
                "generator_cli_version": "",
                "output_sha256": "",
            })
    return rows


def write_tasks(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    """Write ``delta_tasks.csv``, preserving operator progress on stable prompts."""
    rows = build_rows(dataset_dir, delta_ids)
    path = dataset_dir / "delta_tasks.csv"
    previous: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            previous = {row["task_id"]: row for row in csv.DictReader(handle)}
    for row in rows:
        old = previous.get(row["task_id"])
        if old and old.get("prompt_sha256") == row["prompt_sha256"]:
            for field in ("status", "attempts", "operator", "generated_at",
                          "generator_cli_version", "output_sha256"):
                row[field] = old.get(field, row[field])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--delta", action="append", dest="deltas")
    parser.add_argument(
        "--print-prompts",
        action="store_true",
        help="print exact prompts for manual Codex imagegen generation",
    )
    args = parser.parse_args()
    delta_ids = set(args.deltas) if args.deltas else None
    rows = write_tasks(args.dataset_dir, delta_ids)
    if args.print_prompts:
        for row in rows:
            print(f"--- {row['task_id']} (reference: {row['reference_path']})")
            print(row["exact_prompt"])
            print()
    print(
        f"Wrote {len(rows)} delta tasks to "
        f"{args.dataset_dir / 'delta_tasks.csv'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
