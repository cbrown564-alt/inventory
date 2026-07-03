#!/usr/bin/env python3
"""Generate a seeded synthetic check-out inventory from a check-in inventory.

Five mutation classes (the compare feature's test surface — docs/08-compare.md):

  grade_drop    condition worsened by one step
  new_defect    a defect string appended (condition untouched)
  item_removed  item deleted from the check-out (compare must report "removed")
  item_added    a new item inserted (compare must report "added")
  alias_rename  item renamed with descriptor-only words (material/colour/
                finish) so the lexical head-noun matcher must still align it

Deterministic for a given (--seed, --per-class, input): targets are chosen by
``random.Random(seed)`` over items sorted by id. Alongside the mutated
``inventory.json`` a ``mutations.json`` ground-truth manifest is written so
tests can assert each mutation class's outcome individually.

Privacy note: the generator is committed; run it on whatever inventory you
like. Committed fixtures must only ever be built from public inputs
(examples/sample-report) or fully synthetic inventories — never from
own-property data (report/ is gitignored).

Usage:
    python benchmarks/make_synthetic_checkout.py CHECKIN_JSON -o OUT_DIR \
        [--seed 7] [--per-class 2] [--photos-from DIR]
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeinventory.merge import _head_nouns  # noqa: E402
from homeinventory.schema import CONDITION_GRADES, Inventory, Item  # noqa: E402

MUTATION_CLASSES = ["grade_drop", "new_defect", "item_removed", "item_added",
                    "alias_rename"]

SYNTHETIC_DEFECTS = [
    "synthetic: scuff mark low level left hand side",
    "synthetic: angle chip to leading edge",
    "synthetic: water mark to surface, right hand side",
    "synthetic: crack to join, high level",
    "synthetic: burn mark approx 2cm, centre",
]

# Only descriptor tokens (merge._DESCRIPTOR_TOKENS) may be added by a rename,
# so head-noun sets stay equal and the lexical matcher must still align.
RENAME_SUFFIXES = [" (white painted)", " (light oak effect)",
                   " (brushed steel finish)", " (cream emulsion)"]

ADDED_ITEMS = [
    ("Clothes airer", "furniture", "Folding metal clothes airer, silver."),
    ("Waste paper bin", "other", "Plastic waste paper bin, grey."),
    ("Table lamp", "fixture", "Small table lamp, fabric shade."),
    ("Bath mat", "soft furnishing", "Cotton bath mat, white."),
    ("Door wedge", "other", "Rubber door wedge, brown."),
]


def _eligible(items: list[Item]) -> list[Item]:
    """Mutation targets: items whose head-noun set is unique in the room, so
    per-class assertions can identify the outcome unambiguously."""
    seen: dict[frozenset, int] = {}
    for it in items:
        seen[frozenset(_head_nouns(it.name))] = \
            seen.get(frozenset(_head_nouns(it.name)), 0) + 1
    return sorted((it for it in items
                   if seen[frozenset(_head_nouns(it.name))] == 1
                   and _head_nouns(it.name)),
                  key=lambda it: it.id)


def generate(checkin: Inventory, seed: int = 7, per_class: int = 2,
             ) -> tuple[Inventory, list[dict]]:
    """Return (mutated check-out inventory, ground-truth mutation list)."""
    rng = random.Random(seed)
    checkout = copy.deepcopy(checkin)
    mutations: list[dict] = []

    pool = [(room, it) for room in checkout.rooms
            for it in _eligible(room.items)]
    rng.shuffle(pool)
    if len(pool) < 4 * per_class:
        raise SystemExit(
            f"error: inventory too small — need {4 * per_class} unique-named "
            f"items for 4 in-place mutation classes, found {len(pool)}")

    def take(n: int):
        return [pool.pop() for _ in range(n)]

    # grade drop: one step worse (items already 'poor' get a defect instead
    # of silently doing nothing — but we only pick gradeable, droppable ones)
    droppable = [(r, i) for r, i in pool
                 if i.condition in CONDITION_GRADES[:-1]]
    if len(droppable) < per_class:
        raise SystemExit("error: not enough gradeable items (condition set, "
                         "not already 'poor') for the grade_drop class")
    for room, item in droppable[:per_class]:
        pool.remove((room, item))
        old = item.condition
        item.condition = CONDITION_GRADES[CONDITION_GRADES.index(old) + 1]
        mutations.append({"class": "grade_drop", "room": room.name,
                          "checkin_id": item.id, "name": item.name,
                          "from": old, "to": item.condition})

    for k, (room, item) in enumerate(take(per_class)):
        defect = SYNTHETIC_DEFECTS[k % len(SYNTHETIC_DEFECTS)]
        item.defects.append(defect)
        mutations.append({"class": "new_defect", "room": room.name,
                          "checkin_id": item.id, "name": item.name,
                          "defect": defect})

    for room, item in take(per_class):
        room.items.remove(item)
        mutations.append({"class": "item_removed", "room": room.name,
                          "checkin_id": item.id, "name": item.name})

    for k, (room, item) in enumerate(take(per_class)):
        old = item.name
        item.name = old + RENAME_SUFFIXES[k % len(RENAME_SUFFIXES)]
        assert _head_nouns(item.name) == _head_nouns(old), \
            f"rename changed head nouns: {old!r} -> {item.name!r}"
        mutations.append({"class": "alias_rename", "room": room.name,
                          "checkin_id": item.id, "from": old,
                          "to": item.name})

    rooms = sorted(checkout.rooms, key=lambda r: r.name)
    for k in range(per_class):
        name, category, description = ADDED_ITEMS[k % len(ADDED_ITEMS)]
        room = rooms[k % len(rooms)]
        photo_ids = [room.photos[0].id] if room.photos else []
        room.items.append(Item(id="", name=name, category=category,
                               description=description, condition="good",
                               photo_ids=photo_ids))
        mutations.append({"class": "item_added", "room": room.name,
                          "name": name})

    # a real check-out is a fresh build: renumber ids so alignment cannot
    # lean on them (compare aligns by room + name only)
    for room in checkout.rooms:
        prefix = (room.items[0].id.rsplit("-", 1)[0]
                  if room.items and "-" in room.items[0].id else "RM")
        for n, item in enumerate(room.items, start=1):
            item.id = f"{prefix}-{n + 500:03d}"

    checkout.describe_backend = f"synthetic-checkout (seed {seed})"
    checkout.notes = (f"SYNTHETIC check-out generated by "
                      f"benchmarks/make_synthetic_checkout.py seed={seed} "
                      f"per_class={per_class} — not a real inspection. "
                      + (checkout.notes or ""))
    return checkout, mutations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("checkin", help="check-in inventory.json (or report dir)")
    ap.add_argument("-o", "--out", required=True, help="output directory")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--per-class", type=int, default=2,
                    help="mutations per class (default 2)")
    ap.add_argument("--photos-from", default=None, metavar="DIR",
                    help="copy this photos/ dir into the output so the "
                         "compare report can render check-out evidence "
                         "(a synthetic check-out has no photos of its own)")
    args = ap.parse_args()

    src = Path(args.checkin)
    if src.is_dir():
        src = src / "inventory.json"
    checkin = Inventory.from_json(src.read_text(encoding="utf-8"))
    checkout, mutations = generate(checkin, seed=args.seed,
                                   per_class=args.per_class)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(checkout.to_json(), encoding="utf-8")
    (out / "mutations.json").write_text(
        json.dumps({"seed": args.seed, "per_class": args.per_class,
                    "source": str(src), "mutations": mutations},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    if args.photos_from:
        dest = out / "photos"
        if not dest.exists():
            shutil.copytree(args.photos_from, dest)
    print(f"wrote {out / 'inventory.json'} ({len(mutations)} mutations, "
          f"manifest {out / 'mutations.json'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
