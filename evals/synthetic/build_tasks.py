#!/usr/bin/env python3
"""Build exact generation prompts and a deterministic task queue."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "evals/fixtures/synthetic-room-eval"
FIELDNAMES = [
    "task_id", "scenario_id", "room_type", "provider", "product",
    "model_display_name", "view_id", "output_path", "prompt_sha256",
    "exact_prompt", "status", "attempts", "operator", "generated_at",
    "generator_cli_version", "output_sha256",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(scene: dict, view: dict) -> str:
    items = ", ".join(view["intended_visible_items"])
    defects = "; ".join(view.get("intended_defects", [])) or "none"
    negatives = "; ".join(view.get("intended_negatives", [])) or "none"
    continuity = "; ".join(scene["continuity_requirements"])
    avoid = ", ".join(scene["avoid"])
    return (
        "Create one photorealistic landscape photograph that looks like an ordinary "
        f"smartphone capture of a {scene['room_type'].lower()} in a "
        f"{scene['property_profile']}. This is view {view['id']}: "
        f"{view['viewpoint']}; {view['shot_scale']}. "
        f"Visible evidence required in this view: {items}. "
        f"Intended visible defects: {defects}. Negative controls: {negatives}. "
        f"The room is {scene['cleanliness']} under {scene['lighting']}. "
        f"Across views preserve: {continuity}. Avoid: {avoid}. "
        "Do not add labels, captions, borders, or inspection annotations. "
        "Show only visually supportable property evidence; do not make hidden areas visible."
    )


def build_rows(dataset_dir: Path) -> list[dict[str, str]]:
    config = _load(dataset_dir / "dataset.json")
    providers = config["providers"]
    rows: list[dict[str, str]] = []
    for scenario_path in sorted((dataset_dir / "scenarios").glob("RP-*.json")):
        scene = _load(scenario_path)
        for provider_id in scene["provider_assignments"]:
            provider = providers[provider_id]
            for view in scene["views"]:
                prompt = build_prompt(scene, view)
                extension = provider["file_extension"]
                output = Path("images") / provider["image_directory"] / f"{scene['id']}-{view['id']}.{extension}"
                rows.append({
                    "task_id": f"{scene['id']}.{provider_id}.{view['id']}",
                    "scenario_id": scene["id"],
                    "room_type": scene["room_type"],
                    "provider": provider["provider"],
                    "product": provider["product"],
                    "model_display_name": provider["model_display_name"],
                    "view_id": view["id"],
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


def write_tasks(dataset_dir: Path) -> list[dict[str, str]]:
    rows = build_rows(dataset_dir)
    path = dataset_dir / "tasks.csv"
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
    _write_review_templates(dataset_dir)
    return rows


def _write_review_templates(dataset_dir: Path) -> None:
    """Create provisional packet reviews without overwriting reviewer work."""
    config = _load(dataset_dir / "dataset.json")
    review_dir = dataset_dir / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    for scenario_path in sorted((dataset_dir / "scenarios").glob("RP-*.json")):
        scene = _load(scenario_path)
        for provider_id in scene["provider_assignments"]:
            provider = config["providers"][provider_id]
            output = review_dir / f"{scene['id']}.{provider_id}.json"
            if output.exists():
                continue
            review = {
                "scenario_id": scene["id"],
                "provider": provider["provider"],
                "product": provider["product"],
                "model_display_name": provider["model_display_name"],
                "review_status": "provisional",
                "pass_a": {
                    "reviewer": "",
                    "completed_at": None,
                    "frames": [{
                        "frame_id": view["id"],
                        "decision": "pending",
                        "requested_evidence": [
                            {"name": name, "visibility": "pending"}
                            for name in view["intended_visible_items"]
                        ],
                        "rejection_reasons": [],
                    } for view in scene["views"]],
                },
                "pass_b": {
                    "reviewer": "",
                    "completed_at": None,
                    "claims": [],
                    "generator_deviations": [],
                },
            }
            output.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    rows = write_tasks(args.dataset_dir)
    print(f"Wrote {len(rows)} tasks to {args.dataset_dir / 'tasks.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
