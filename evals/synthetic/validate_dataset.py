#!/usr/bin/env python3
"""Validate synthetic-room files without mistaking intended facts for gold."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image

from evals.synthetic.build_tasks import DEFAULT_DATASET, build_rows


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _required(obj: dict, names: list[str], where: str, errors: list[str]) -> None:
    for name in names:
        if name not in obj:
            errors.append(f"{where}: missing {name}")


def validate(dataset_dir: Path, require_complete: bool = False) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    config_path = dataset_dir / "dataset.json"
    if not config_path.exists():
        return ["missing dataset.json"], warnings
    config = _load(config_path)
    _required(config, ["dataset_id", "phase", "providers", "terms_records"], "dataset.json", errors)

    scene_paths = sorted((dataset_dir / "scenarios").glob("RP-*.json"))
    if len(scene_paths) != 2:
        errors.append(f"representative slice requires 2 scenarios; found {len(scene_paths)}")
    scenario_ids: set[str] = set()
    for path in scene_paths:
        scene = _load(path)
        _required(scene, ["id", "room_type", "property_profile", "cleanliness", "lighting",
                          "continuity_requirements", "avoid", "provider_assignments", "views"], path.name, errors)
        scenario_ids.add(scene.get("id", ""))
        views = scene.get("views", [])
        if len(views) != 4:
            errors.append(f"{path.name}: expected four views; found {len(views)}")
        if len(set(v.get("id") for v in views)) != len(views):
            errors.append(f"{path.name}: duplicate view IDs")
        for i, view in enumerate(views):
            _required(view, ["id", "viewpoint", "shot_scale", "intended_visible_items",
                             "intended_defects", "intended_negatives"], f"{path.name} view {i}", errors)

    expected = build_rows(dataset_dir) if not errors else []
    expected_by_id = {row["task_id"]: row for row in expected}
    task_path = dataset_dir / "tasks.csv"
    if not task_path.exists():
        errors.append("missing tasks.csv")
        actual: list[dict[str, str]] = []
    else:
        with task_path.open(newline="", encoding="utf-8") as handle:
            actual = list(csv.DictReader(handle))
    if len(actual) != 16:
        errors.append(f"representative slice requires 16 tasks; found {len(actual)}")
    counts = Counter(row.get("scenario_id") for row in actual)
    for scenario_id in scenario_ids:
        if counts[scenario_id] != 8:
            errors.append(f"{scenario_id}: expected 8 provider/view tasks; found {counts[scenario_id]}")
    for row in actual:
        expected_row = expected_by_id.get(row.get("task_id", ""))
        if not expected_row:
            errors.append(f"unexpected task {row.get('task_id')}")
            continue
        for field in ("provider", "product", "model_display_name", "output_path", "prompt_sha256", "exact_prompt"):
            if row.get(field) != expected_row[field]:
                errors.append(f"{row['task_id']}: stale or changed {field}; rebuild tasks")
        image_path = dataset_dir / row["output_path"]
        if row.get("status") == "accepted":
            if not image_path.exists():
                errors.append(f"{row['task_id']}: accepted image is missing")
                continue
            try:
                with Image.open(image_path) as image:
                    width, height = image.size
                    expected_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}.get(image_path.suffix.lower())
                    if expected_format and image.format != expected_format:
                        errors.append(
                            f"{row['task_id']}: file extension {image_path.suffix} "
                            f"does not match {image.format} content"
                        )
                    if width < 1024 or height < 768:
                        errors.append(f"{row['task_id']}: resolution {width}x{height} is below 1024x768")
            except Exception as exc:
                errors.append(f"{row['task_id']}: unreadable image: {exc}")
            if not all(row.get(field) for field in (
                "operator", "generated_at", "generator_cli_version", "output_sha256"
            )):
                errors.append(f"{row['task_id']}: accepted task lacks required provenance")
        elif require_complete:
            errors.append(f"{row['task_id']}: status is {row.get('status') or 'blank'}, not accepted")
        else:
            warnings.append(f"{row['task_id']}: status is {row.get('status') or 'blank'}")

    for provider_id, provider in config.get("providers", {}).items():
        terms = config.get("terms_records", {}).get(provider["terms_record"])
        if not terms:
            errors.append(f"{provider_id}: missing terms record")
        elif terms.get("acceptance_permitted") is not True:
            warnings.append(f"{provider_id}: dataset acceptance paused by terms record")

    for review_path in sorted((dataset_dir / "reviews").glob("*.json")):
        review = _load(review_path)
        _required(review, ["scenario_id", "provider", "pass_a", "pass_b", "review_status"], review_path.name, errors)
        if review.get("review_status") == "verified_synthetic_gold":
            if not review.get("pass_a", {}).get("completed_at") or not review.get("pass_b", {}).get("completed_at"):
                errors.append(f"{review_path.name}: gold status without both completed passes")
            for claim in review.get("pass_b", {}).get("claims", []):
                if not claim.get("evidence_frame_ids"):
                    errors.append(f"{review_path.name}: claim {claim.get('canonical_name')} has no evidence frames")

    manifest = dataset_dir / "rejected/manifest.jsonl"
    if manifest.exists():
        for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"rejected/manifest.jsonl:{number}: {exc}")

    hashes: dict[str, str] = {}
    for row in actual:
        image_path = dataset_dir / row.get("output_path", "")
        if image_path.is_file():
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if row.get("output_sha256") and row["output_sha256"] != digest:
                errors.append(f"{row['task_id']}: output hash differs from recorded provenance")
            if digest in hashes:
                errors.append(f"duplicate image bytes: {hashes[digest]} and {row['task_id']}")
            hashes[digest] = row["task_id"]
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    errors, warnings = validate(args.dataset_dir, args.require_complete)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Validation: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
