#!/usr/bin/env python3
"""Score a pipeline run against human-labelled fixtures.

Usage:
    python evals/run_eval.py report/inventory.json evals/fixtures/<case>/labels.json

labels.json format (one per fixture case — see evals/README.md):
{
  "rooms": {
    "Living Room": {
      "items": [
        {"name": "three-seat sofa", "aliases": ["sofa", "settee"],
         "condition": "good", "defects": ["scuff on left arm"], "notable": true}
      ]
    }
  }
}

Metrics: item recall (notable / all), hallucination rate, naming accuracy,
condition exact & within-one agreement, defect recall. See
docs/01-scope-and-architecture.md §5 for targets.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeinventory.schema import CONDITION_GRADES, Inventory  # noqa: E402


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def name_match(pred: str, gold: dict) -> float:
    """Best fuzzy similarity between a predicted name and gold name/aliases."""
    candidates = [gold["name"], *gold.get("aliases", [])]
    pred_n = _norm(pred)
    best = 0.0
    for c in candidates:
        c_n = _norm(c)
        if c_n in pred_n or pred_n in c_n:
            return 1.0
        best = max(best, difflib.SequenceMatcher(None, pred_n, c_n).ratio())
    return best


def evaluate(inv: Inventory, labels: dict, match_threshold: float = 0.6) -> dict:
    rooms_gold = labels["rooms"]
    stats = {
        "gold_items": 0, "gold_notable": 0, "found": 0, "found_notable": 0,
        "pred_items": 0, "hallucinated": 0, "name_exactish": 0,
        "cond_pairs": 0, "cond_exact": 0, "cond_within1": 0,
        "gold_defects": 0, "defects_found": 0,
    }
    inv_rooms = {r.name.lower(): r for r in inv.rooms}

    for room_name, gold_room in rooms_gold.items():
        room = inv_rooms.get(room_name.lower())
        preds = list(room.items) if room else []
        stats["pred_items"] += len(preds)
        matched_pred_ids: set[str] = set()

        for gold in gold_room["items"]:
            stats["gold_items"] += 1
            notable = gold.get("notable", True)
            if notable:
                stats["gold_notable"] += 1
            # best unmatched prediction
            best, best_score = None, 0.0
            for p in preds:
                if p.id in matched_pred_ids:
                    continue
                s = name_match(p.name, gold)
                if s > best_score:
                    best, best_score = p, s
            if best is None or best_score < match_threshold:
                continue
            matched_pred_ids.add(best.id)
            stats["found"] += 1
            if notable:
                stats["found_notable"] += 1
            if best_score >= 0.85:
                stats["name_exactish"] += 1
            if gold.get("condition") and best.condition in CONDITION_GRADES:
                stats["cond_pairs"] += 1
                gi = CONDITION_GRADES.index(gold["condition"])
                pi = CONDITION_GRADES.index(best.condition)
                if gi == pi:
                    stats["cond_exact"] += 1
                if abs(gi - pi) <= 1:
                    stats["cond_within1"] += 1
            for gd in gold.get("defects", []):
                stats["gold_defects"] += 1
                blob = _norm(" ".join(best.defects) + " " + best.description)
                if any(w in blob for w in _norm(gd).split() if len(w) > 3):
                    stats["defects_found"] += 1

        stats["hallucinated"] += sum(1 for p in preds if p.id not in matched_pred_ids)

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else None

    return {
        "item_recall_all": pct(stats["found"], stats["gold_items"]),
        "item_recall_notable": pct(stats["found_notable"], stats["gold_notable"]),
        "hallucination_rate": pct(stats["hallucinated"], stats["pred_items"]),
        "naming_accuracy": pct(stats["name_exactish"], stats["found"]),
        "condition_exact": pct(stats["cond_exact"], stats["cond_pairs"]),
        "condition_within_one": pct(stats["cond_within1"], stats["cond_pairs"]),
        "defect_recall": pct(stats["defects_found"], stats["gold_defects"]),
        "_counts": stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory_json")
    ap.add_argument("labels_json")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="fuzzy name-match threshold for item matching")
    args = ap.parse_args()

    inv = Inventory.from_json(Path(args.inventory_json).read_text(encoding="utf-8"))
    labels = json.loads(Path(args.labels_json).read_text(encoding="utf-8"))
    results = evaluate(inv, labels, args.threshold)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
