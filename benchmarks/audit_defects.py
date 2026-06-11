"""List, for each matched gold item, which gold defects were missed.

Usage: python benchmarks/audit_defects.py <inventory.json> <labels.json>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.run_eval import _norm, assign_matches  # noqa: E402
from homeinventory.schema import Inventory  # noqa: E402

inv = Inventory.from_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
labels = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

inv_rooms = {r.name.lower(): r for r in inv.rooms}
for room_name, gold_room in labels["rooms"].items():
    room = inv_rooms.get(room_name.lower())
    preds = list(room.items) if room else []
    matches = assign_matches(preds, gold_room["items"])
    print(f"\n== {room_name}")
    for gi, gold in enumerate(gold_room["items"]):
        if gi not in matches:
            continue
        best_score, best = matches[gi]
        blob = _norm(" ".join(best.defects) + " " + best.description)
        for gd in gold.get("defects", []):
            hit = any(w in blob for w in _norm(gd).split() if len(w) > 3)
            if not hit:
                print(f"  MISS [{gold['name']} -> {best.name}] {gd}")
                if best.defects:
                    print(f"       pred defects: {best.defects}")
