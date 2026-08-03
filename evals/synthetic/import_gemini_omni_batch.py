#!/usr/bin/env python3
"""Stage a user-supplied Gemini Omni image batch without overwriting evidence."""

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Attachment order supplied by the operator. Prefixes are used because some
# Finder names contain a literal ellipsis character.
BATCH = [
    ("Sink_cabinet_condition_detail_", "RP-018", "D-condition"),
    ("Inventory_view_C-window_radiator", "RP-013", "C-inventory"),
    ("Appliances_view_laundry_room_", "RP-018", "C-inventory"),
    ("Shower_inventory_medium_fixtures", "RP-007", "C-inventory"),
    ("Base_unit_door_skirting_board_", "RP-004", "D-condition"),
    ("Room_with_fireplace_and_armchair_", "RP-012", "B-reverse"),
    ("Room_view_with_window_and_", "RP-013", "B-reverse"),
    ("Oak_tabletop_chair_upholstery_ti", "RP-017", "D-condition"),
    ("Quartz_worktop_island_cabinet_ba", "RP-005", "D-condition"),
    ("Medium_fixtures_view_C-inventory_", "RP-016", "C-inventory"),
    ("Sofa_view_with_balcony_door_", "RP-011", "C-inventory"),
    ("Kitchen_units_window_blind_radiator_", "RP-001", "B-reverse"),
    ("Display_cabinet_medium_fixtures_", "RP-017", "C-inventory"),
    ("Island_view_with_patio_doors_", "RP-005", "B-reverse"),
    ("Room_view_cooker_looking_back_", "RP-004", "B-reverse"),
    ("View_D-condition_low_view_202608032205", "RP-013", "D-condition"),
    ("Range_cooker_medium_fixtures_view_", "RP-005", "C-inventory"),
    ("Desk_wall_medium_fixtures_view_", "RP-010", "C-inventory"),
    ("Inventory_view_C_bath_shower_", "RP-002", "C-inventory"),
    ("Room_view_with_laundry_supplies_", "RP-018", "B-reverse"),
    ("Room_interior_with_furniture_and", "RP-017", "B-reverse"),
]


def find_source(downloads: Path, prefix: str) -> Path:
    matches = sorted(downloads.glob(prefix + "*.jpeg"))
    if len(matches) != 1:
        raise SystemExit(f"Expected one source for {prefix!r}, found {len(matches)}: {matches}")
    return matches[0]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--downloads", type=Path, default=Path("/Users/cobro/Downloads"))
    ap.add_argument("--date", default="2026-08-03")
    args = ap.parse_args()

    out_dir = ROOT / "fixtures/synthetic-room-eval/images/google/gemini-omni"
    report_dir = ROOT / "fixtures/synthetic-room-eval/reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for ordinal, (prefix, scenario_id, view_id) in enumerate(BATCH, 1):
        source = find_source(args.downloads, prefix)
        target = out_dir / f"{scenario_id}-{view_id}.jpeg"
        if target.exists() and sha256(target) != sha256(source):
            raise SystemExit(f"Refusing to overwrite different candidate: {target}")
        shutil.copy2(source, target)
        records.append({
            "ordinal": ordinal,
            "scenario_id": scenario_id,
            "view_id": view_id,
            "source_filename": source.name,
            "output_path": str(target.relative_to(ROOT)),
            "source_sha256": sha256(source),
            "output_sha256": sha256(target),
            "provider": "Google",
            "product": "Gemini Omni (user-provided output)",
            "model_display_name": "Gemini Omni",
            "provenance_status": "candidate_only",
            "generated_at": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
        })

    report = {
        "batch_id": f"gemini-omni-user-batch-{args.date}",
        "source": "user-supplied Downloads batch",
        "mapping_rule": "attachment order is authoritative",
        "count": len(records),
        "records": records,
        "ledger_effect": "none; existing tasks.csv rows and approved evidence are unchanged",
    }
    report_path = report_dir / f"gemini-omni-user-batch-{args.date}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Staged {len(records)} Gemini Omni candidates")
    print(report_path)


if __name__ == "__main__":
    main()
