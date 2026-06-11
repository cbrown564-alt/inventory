"""List per-room missed gold items and unmatched predictions for a run.

Usage: python benchmarks/audit_matches.py <inventory.json> <labels.json>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.run_eval import assign_matches  # noqa: E402
from homeinventory.schema import Inventory  # noqa: E402

inv = Inventory.from_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
labels = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

inv_rooms = {r.name.lower(): r for r in inv.rooms}
for room_name, gold_room in labels["rooms"].items():
    room = inv_rooms.get(room_name.lower())
    preds = list(room.items) if room else []
    matches = assign_matches(preds, gold_room["items"])
    matched = {p.id for _, p in matches.values()}
    missed_gold = [
        gold["name"] + (" (notable)" if gold.get("notable", True) else "")
        for gi, gold in enumerate(gold_room["items"]) if gi not in matches
    ]
    unmatched_preds = [p.name for p in preds if p.id not in matched]
    print(f"\n== {room_name} ({len(preds)} preds, {len(gold_room['items'])} gold)")
    print("  missed gold:      " + (", ".join(missed_gold) or "-"))
    print("  unmatched preds:  " + (", ".join(unmatched_preds) or "-"))
