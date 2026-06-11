"""List per-room missed gold items and unmatched predictions for a run.

Usage: python benchmarks/audit_matches.py <inventory.json> <labels.json>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.run_eval import name_match  # noqa: E402
from homeinventory.schema import Inventory  # noqa: E402

inv = Inventory.from_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
labels = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
threshold = 0.6

inv_rooms = {r.name.lower(): r for r in inv.rooms}
for room_name, gold_room in labels["rooms"].items():
    room = inv_rooms.get(room_name.lower())
    preds = list(room.items) if room else []
    matched: set[str] = set()
    missed_gold = []
    for gold in gold_room["items"]:
        best, best_score = None, 0.0
        for p in preds:
            if p.id in matched:
                continue
            s = name_match(p.name, gold)
            if s > best_score:
                best, best_score = p, s
        if best is None or best_score < threshold:
            missed_gold.append(gold["name"] + (" (notable)" if gold.get("notable", True) else ""))
        else:
            matched.add(best.id)
    unmatched_preds = [p.name for p in preds if p.id not in matched]
    print(f"\n== {room_name} ({len(preds)} preds, {len(gold_room['items'])} gold)")
    print("  missed gold:      " + (", ".join(missed_gold) or "-"))
    print("  unmatched preds:  " + (", ".join(unmatched_preds) or "-"))
