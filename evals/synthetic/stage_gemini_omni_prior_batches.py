#!/usr/bin/env python3
"""Stage the earlier operator-supplied Gemini Omni four-view packets."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = Path("/Users/cobro/Downloads")
OUT = ROOT / "fixtures/synthetic-room-eval/images/google/gemini-omni"
REPORTS = ROOT / "fixtures/synthetic-room-eval/reports"

# Each tuple is (source filename prefix, scenario ID); views are assigned
# A-wide, B-reverse, C-inventory, D-condition in the operator's supplied order.
BATCHES = {
    "RP-003": [
        "Splashback_tiles_grout_worktop_edge_202608032123",
        "Cooking_wall_inventory_view_202608032122",
        "Rear_corner_view_entrance_fridge_202608032122",
        "Kitchen_photograph_refurbished_c",
    ],
    "RP-014": [
        "Front_door_lower_panel_condition_202608032123",
        "Entry_controls_medium_fixtures_view_202608032123",
        "View_B-reverse_front_door_202608032123",
        "Hallway_with_striped_runner_202608032123",
    ],
    "RP-015": [
        "View_D-condition__low_view_202608032122",
        "Inventory_view_medium_fixtures_202608032122",
        "Stair_foot_facing_door_view_202608032122",
        "Entrance_hall_with_open_coat_202608032122",
    ],
    "RP-019": [
        "View_D-condition_low_view_202608032141",
        "Inventory_view_upper_services_fi",
        "Utility_cupboard_with_storage_202608032140",
        "Inside_view_facing_door_202608032141",
    ],
    "RP-021": [
        "Stair_runner_tread_edge_condition_202608032141",
        "Inventory_view_C-stair_landing_202608032141",
        "Boxes_under_dim_warm_light_202608032141",
        "Stairs_and_landing_with_boxes_202608032141",
    ],
    "RP-022": [
        "WC_base_vinyl_floor_skirting_202608032141",
        "Basin_wall_medium_fixtures_view_202608032141",
        "View_B-reverse_looking_back_202608032141",
        "WC_in_small_cloakroom_202608032141",
    ],
    "RP-023": [
        "Clear_floor_area_view_condition_202608032141",
        "Service_wall_medium_fixtures_view_202608032141",
        "Cluttered_room_with_boxes_storage_202608032141",
        "Storage_cupboard_in_UK_rental_202608032141",
    ],
    "RP-024": [
        "Desk_surface_drawer_chair_carpet_202608032141",
        "Desk_wall_view_medium_fixtures_202608032141",
        "Room_view_with_evidence_202608032141",
        "Home_office_in_UK_flat_202608032141",
    ],
    "RP-025": [
        "View_of_floor_tiles_and_202608032143",
        "Balustrade_corner_medium_fixture",
        "Patio_door_external_light_chairs_202608032142",
        "Balcony_in_modern_UK_apartment_202608032142",
    ],
}
VIEWS = ["A-wide", "B-reverse", "C-inventory", "D-condition"]

# The order the operator actually supplied the four files in: condition detail
# first, wide establishing view last. This ran originally as `zip(VIEWS, ...)`,
# which assigned the labels the other way round and mislabelled all 36 stills —
# every packet's wide view was filed as its condition detail and vice versa.
# Nothing caught it because these files were never in tasks.csv and so never saw
# Pass A. Repaired on 4 Aug 2026 by repair_gemini_omni_views.py; see docs/34
# "Day 1 result" for the evidence and what it cost.
#
# Positional assignment is the underlying hazard and it is still here, because
# this is the record of one batch that has already been staged. Any future
# import must name a view per file, the way import_gemini_omni_batch.py does.
SUPPLIED_ORDER = ["D-condition", "C-inventory", "B-reverse", "A-wide"]


def source_for(prefix: str) -> Path:
    matches = sorted(DOWNLOADS.glob(prefix + "*.jpeg"))
    if len(matches) != 1:
        raise SystemExit(f"Expected one source for {prefix!r}, found {len(matches)}: {matches}")
    return matches[0]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    records = []
    ordinal = 0
    for scenario_id, prefixes in BATCHES.items():
        if len(prefixes) != 4:
            raise SystemExit(f"{scenario_id} does not contain four sources")
        for view_id, prefix in zip(SUPPLIED_ORDER, prefixes):
            ordinal += 1
            source = source_for(prefix)
            target = OUT / f"{scenario_id}-{view_id}.jpeg"
            if target.exists() and digest(target) != digest(source):
                raise SystemExit(f"Refusing to overwrite different candidate: {target}")
            shutil.copy2(source, target)
            records.append({
                "ordinal": ordinal,
                "scenario_id": scenario_id,
                "view_id": view_id,
                "source_filename": source.name,
                "output_path": str(target.relative_to(ROOT)),
                "source_sha256": digest(source),
                "output_sha256": digest(target),
                "provider": "Google",
                "product": "Gemini Omni (user-provided output)",
                "model_display_name": "Gemini Omni",
                "provenance_status": "candidate_only",
                "generated_at": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
            })
    report = {
        "batch_id": "gemini-omni-prior-batches-2026-08-03",
        "source": "user-supplied Downloads batches",
        "mapping_rule": "nine batches in the stated order; four views per batch in stated order",
        "count": len(records),
        "batches": list(BATCHES),
        "records": records,
        "ledger_effect": "none; existing tasks.csv rows and approved evidence are unchanged",
    }
    path = REPORTS / "gemini-omni-prior-batches-2026-08-03.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Staged {len(records)} Gemini Omni candidates")
    print(path)


if __name__ == "__main__":
    main()
