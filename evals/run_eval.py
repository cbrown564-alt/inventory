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
         "components": ["left arm", "seat cushion"],
         "condition": "good", "defects": ["scuff on left arm"], "notable": true}
      ]
    }
  }
}

Metrics: item recall (notable / all), hallucination rate, granularity split rate,
naming accuracy, condition exact & within-one agreement, defect recall. See
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


def _match_names(pred: str, candidates: list[str]) -> tuple[float, bool]:
    """Return (best_score, used_substring_match)."""
    pred_n = _norm(pred)
    best = 0.0
    substring = False
    for c in candidates:
        c_n = _norm(c)
        if c_n in pred_n or pred_n in c_n:
            shorter, longer = sorted((c_n, pred_n), key=len)
            score = 0.9 + 0.1 * (len(shorter) / len(longer))
            substring = True
        else:
            score = difflib.SequenceMatcher(None, pred_n, c_n).ratio()
            if max(len(pred_n), len(c_n)) <= 5 and score < 0.85:
                score = min(score, 0.55)
            substring = False
        if score > best:
            best = score
    return best, substring


def name_match(pred: str, gold: dict) -> float:
    """Best fuzzy similarity between a predicted name and gold name/aliases."""
    score, _ = _match_names(pred, [gold["name"], *gold.get("aliases", [])])
    return score


def pred_is_covered(pred_name: str, gold: dict, *,
                    threshold: float = 0.6,
                    fuzzy_threshold: float = 0.75) -> bool:
    """Whether an unmatched pred is a finer split of a labelled gold item."""
    comp_score, comp_sub = _match_names(pred_name, gold.get("components", []))
    if comp_score >= threshold:
        return True
    name_score, name_sub = _match_names(
        pred_name, [gold["name"], *gold.get("aliases", [])])
    if name_sub and name_score >= threshold:
        return True
    return name_score >= fuzzy_threshold


def pred_covers_any(pred, gold_items: list[dict], **kwargs) -> bool:
    return any(pred_is_covered(pred.name, g, **kwargs) for g in gold_items)


def assign_matches(preds: list, gold_items: list[dict],
                   threshold: float = 0.6) -> dict[int, tuple[float, object]]:
    """Score-ordered one-to-one assignment of predictions to gold items."""
    pairs = []
    for gi, gold in enumerate(gold_items):
        for p in preds:
            s = name_match(p.name, gold)
            if s >= threshold:
                pairs.append((s, gi, p))
    pairs.sort(key=lambda t: -t[0])
    out: dict[int, tuple[float, object]] = {}
    used: set[str] = set()
    for s, gi, p in pairs:
        if gi in out or p.id in used:
            continue
        out[gi] = (s, p)
        used.add(p.id)
    return out


def evaluate(inv: Inventory, labels: dict, match_threshold: float = 0.6) -> dict:
    rooms_gold = labels["rooms"]
    stats = {
        "gold_items": 0, "gold_notable": 0, "found": 0, "found_notable": 0,
        "pred_items": 0, "hallucinated": 0, "granularity_splits": 0,
        "name_exactish": 0,
        "cond_pairs": 0, "cond_exact": 0, "cond_within1": 0,
        "gold_defects": 0, "defects_found": 0,
    }
    inv_rooms = {r.name.lower(): r for r in inv.rooms}

    for room_name, gold_room in rooms_gold.items():
        room = inv_rooms.get(room_name.lower())
        preds = list(room.items) if room else []
        stats["pred_items"] += len(preds)
        matched_pred_ids: set[str] = set()

        # Globally score-ordered assignment: every (gold, pred) pair above the
        # threshold competes at once, best score wins. A per-gold greedy pass
        # let an early gold item steal a later item's natural partner ("front
        # door" matched to "Door frame and architrave"), inflating
        # hallucinations and burying defect credit.
        match_for_gold = assign_matches(preds, gold_room["items"], match_threshold)
        matched_pred_ids.update(p.id for _, p in match_for_gold.values())

        for gi, gold in enumerate(gold_room["items"]):
            stats["gold_items"] += 1
            notable = gold.get("notable", True)
            if notable:
                stats["gold_notable"] += 1
            if gi not in match_for_gold:
                continue
            best_score, best = match_for_gold[gi]
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
                gd_words = [w for w in _norm(gd).split() if len(w) > 3]
                hit = any(w in blob for w in gd_words)
                if not hit:
                    # part-split credit: the clerk merges (one "Bed & Mattress"
                    # entry), the model splits (bed base / headboard / mattress).
                    # If the gold defect names the part ("hole to edge of
                    # mattress"), look for it on unmatched preds carrying that
                    # part's name.
                    for p in preds:
                        if p.id in matched_pred_ids:
                            continue
                        p_words = [w for w in _norm(p.name).split() if len(w) > 3]
                        if not any(w in _norm(gd) for w in p_words):
                            continue
                        part_blob = _norm(" ".join(p.defects) + " " + p.description)
                        if any(w in part_blob for w in gd_words):
                            hit = True
                            break
                if hit:
                    stats["defects_found"] += 1

        for p in preds:
            if p.id in matched_pred_ids:
                continue
            if pred_covers_any(p, gold_room["items"], threshold=match_threshold):
                stats["granularity_splits"] += 1
            else:
                stats["hallucinated"] += 1

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else None

    return {
        "item_recall_all": pct(stats["found"], stats["gold_items"]),
        "item_recall_notable": pct(stats["found_notable"], stats["gold_notable"]),
        "hallucination_rate": pct(stats["hallucinated"], stats["pred_items"]),
        "granularity_split_rate": pct(stats["granularity_splits"], stats["pred_items"]),
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
