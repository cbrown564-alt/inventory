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
    design = config.get("target_design", {})
    expected_scenarios = int(design.get("matched_scenarios", 25))
    expected_tasks = int(design.get("task_images", expected_scenarios * 8))
    views_per_packet = int(design.get("views_per_packet", 4))
    providers_per_scenario = int(
        design.get("provider_packets_per_scenario", 2)
    )
    # A bias-check slice is not part of the matched design: it is opportunistic,
    # unbalanced, and carries no completeness obligation (docs/31 Amendment B
    # B9). Counting it against the matched targets would make every scenario
    # look short by however many candidates happen to exist.
    slice_providers = {
        provider_id
        for provider_id, provider in config.get("providers", {}).items()
        if provider.get("role") == "bias_check_slice"
    }
    slice_tasks_per_scenario = views_per_packet * len(slice_providers)

    scene_paths = sorted((dataset_dir / "scenarios").glob("RP-*.json"))
    if len(scene_paths) != expected_scenarios:
        errors.append(
            f"pilot requires {expected_scenarios} scenarios; "
            f"found {len(scene_paths)}"
        )
    scenario_ids: set[str] = set()
    for path in scene_paths:
        scene = _load(path)
        _required(scene, ["id", "room_type", "property_profile", "cleanliness", "lighting",
                          "continuity_requirements", "avoid", "provider_assignments", "views"], path.name, errors)
        scenario_ids.add(scene.get("id", ""))
        views = scene.get("views", [])
        if len(views) != views_per_packet:
            errors.append(
                f"{path.name}: expected {views_per_packet} views; "
                f"found {len(views)}"
            )
        assignments = scene.get("provider_assignments", [])
        matched_assignments = [a for a in assignments if a not in slice_providers]
        if len(matched_assignments) != providers_per_scenario:
            errors.append(
                f"{path.name}: expected {providers_per_scenario} matched "
                f"providers; found {len(matched_assignments)}"
            )
        for provider_id in assignments:
            if provider_id not in config.get("providers", {}):
                errors.append(
                    f"{path.name}: unknown provider assignment {provider_id}"
                )
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
    expected_total = expected_tasks + expected_scenarios * slice_tasks_per_scenario
    if len(actual) != expected_total:
        errors.append(
            f"pilot requires {expected_tasks} matched tasks plus "
            f"{expected_scenarios * slice_tasks_per_scenario} bias-check tasks; "
            f"found {len(actual)}"
        )
    counts = Counter(row.get("scenario_id") for row in actual)
    for scenario_id in scenario_ids:
        expected_per_scenario = (
            views_per_packet * providers_per_scenario + slice_tasks_per_scenario
        )
        if counts[scenario_id] != expected_per_scenario:
            errors.append(
                f"{scenario_id}: expected {expected_per_scenario} "
                f"provider/view tasks; found {counts[scenario_id]}"
            )
    for row in actual:
        expected_row = expected_by_id.get(row.get("task_id", ""))
        if not expected_row:
            errors.append(f"unexpected task {row.get('task_id')}")
            continue
        for field in ("provider", "product", "model_display_name", "output_path", "prompt_sha256", "exact_prompt"):
            if row.get(field) != expected_row[field]:
                errors.append(f"{row['task_id']}: stale or changed {field}; rebuild tasks")
        image_path = dataset_dir / row["output_path"]
        is_accepted = row.get("status") in {"accepted", "pass_a_accepted"}
        if image_path.exists():
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
        elif is_accepted:
            errors.append(f"{row['task_id']}: accepted image is missing")
        if is_accepted:
            required = ["operator", "generated_at", "output_sha256"]
            # generator_cli_version is only meaningful where a CLI generated the
            # image. The bias-check slice came off a subscription surface, so
            # demanding one would force a value to be invented — the precise
            # falsification the provenance field exists to prevent. What that
            # slice must carry instead is the admission itself.
            if row.get("provenance", "recorded") == "recorded":
                required.append("generator_cli_version")
            elif not row.get("provenance"):
                errors.append(
                    f"{row['task_id']}: accepted task has no provenance declared"
                )
            if not all(row.get(field) for field in required):
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

    split_paths = [
        dataset_dir / "splits/development.json",
        dataset_dir / "splits/validation.json",
        dataset_dir / "splits/sealed.json",
    ]
    split_ids: list[str] = []
    for split_path in split_paths:
        if not split_path.is_file():
            errors.append(f"missing {split_path.relative_to(dataset_dir)}")
            continue
        split = _load(split_path)
        ids = split.get("scenario_ids", [])
        if not isinstance(ids, list) or not ids:
            errors.append(f"{split_path.name}: missing scenario_ids")
            continue
        split_ids.extend(ids)
    duplicates = [
        scenario_id
        for scenario_id, count in Counter(split_ids).items()
        if count > 1
    ]
    if duplicates:
        errors.append(
            "scenario IDs cross split boundaries: " + ", ".join(duplicates)
        )
    if set(split_ids) != scenario_ids:
        missing = sorted(scenario_ids - set(split_ids))
        extra = sorted(set(split_ids) - scenario_ids)
        if missing:
            errors.append("split assignment missing: " + ", ".join(missing))
        if extra:
            errors.append("split assignment unknown: " + ", ".join(extra))

    for review_path in sorted((dataset_dir / "reviews").glob("*.json")):
        review = _load(review_path)
        _required(review, ["scenario_id", "provider", "pass_a", "pass_b", "review_status"], review_path.name, errors)
        pass_b = review.get("pass_b", {})
        _required(pass_b, ["reviewer", "completed_at", "claims", "negative_controls", "generator_deviations"],
                  f"{review_path.name} pass_b", errors)
        if review.get("review_status") == "verified_synthetic_gold":
            if not review.get("pass_a", {}).get("completed_at") or not pass_b.get("completed_at"):
                errors.append(f"{review_path.name}: gold status without both completed passes")
            claims = pass_b.get("claims", [])
            if not claims:
                errors.append(f"{review_path.name}: gold status without observed claims")
            for claim in claims:
                if not claim.get("evidence_frame_ids"):
                    errors.append(f"{review_path.name}: claim {claim.get('canonical_name')} has no evidence frames")
                if claim.get("defects") and (
                    claim.get("second_review", {}).get("required") is not True
                    or claim.get("second_review", {}).get("decision") not in {"agreed", "resolved"}
                ):
                    errors.append(f"{review_path.name}: defect claim {claim.get('canonical_name')} lacks a completed second review")
            ordinary_checks = sum(
                claim.get("second_review", {}).get("required") is True
                and claim.get("second_review", {}).get("decision") in {"agreed", "resolved"}
                for claim in claims if not claim.get("defects")
            )
            ordinary_count = sum(not claim.get("defects") for claim in claims)
            if ordinary_count and ordinary_checks * 4 < ordinary_count:
                errors.append(f"{review_path.name}: fewer than 25% of ordinary claims have a completed second review")
            negatives = pass_b.get("negative_controls", [])
            if not negatives:
                errors.append(f"{review_path.name}: gold status without negative controls")
            for negative in negatives:
                if not negative.get("evidence_frame_ids"):
                    errors.append(f"{review_path.name}: negative control {negative.get('wording')} has no evidence frames")
                if (
                    negative.get("second_review", {}).get("required") is not True
                    or negative.get("second_review", {}).get("decision") not in {"agreed", "resolved"}
                ):
                    errors.append(f"{review_path.name}: negative control {negative.get('wording')} lacks a completed second review")

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
