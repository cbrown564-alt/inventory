"""De-duplicate items reported across multiple photos of the same room.

The describe backend sees a whole room's photos in one call, so duplication is
already rare with the claude backend; the offline backend and any per-photo or
batched mode (the local Ollama backend sends photos in batches of six) need
this pass. Strategy: within a room, items describing the same thing merge —
keeping the longest description, the worst condition grade (conservative for
deposit purposes), the union of defects and photo references.

Two items are "the same thing" when their head nouns agree — i.e. one name
adds only descriptor words (material, colour, finish, qualifier) to the other.
"Walls (Cream Emulsion)" / "Walls" / "Walls painted white" all share the head
noun "walls" and merge; "Door" never absorbs "Door Handle and Lockset" because
that adds the new noun "handle". This is what collapses the cross-batch
structural duplication the batched local backend produces (the same wall /
floor / ceiling re-described per batch with different wording).
"""

from __future__ import annotations

import re

from .schema import CONDITION_GRADES, Item, Photo, Room

# Descriptor / non-head tokens: materials, colours, finishes, qualifiers,
# quantities and glue words. These are stripped before comparing names so that
# "Walls (Cream Emulsion)" and "Walls" reduce to the same head noun "walls".
_DESCRIPTOR_TOKENS = frozenset(
    "white cream grey gray black brown beige taupe magnolia oak wood wooden "
    "wood-effect woodeffect effect laminate vinyl engineered painted emulsion "
    "finish finished colour color light dark upper lower left right interior "
    "exterior internal external single double tall round large small mounted "
    "wall-mounted wallmounted upvc metal silver stainless steel brushed gloss "
    "matte fabric upholstered marble ceramic carpet section area side front "
    "back main primary x x2 x3 x4 and the a an to of for with or "
    "fitted built-in builtin built".split()
)


def _key(item: Item) -> str:
    base = item.detector_label or item.name
    base = re.sub(r"\bx\s*\d+$", "", base.strip().lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", base)


def _tokens(name: str) -> list[str]:
    """Lowercase content tokens of an item name, parentheticals flattened."""
    s = re.sub(r"\bx\s*\d+$", "", name.strip().lower())
    s = re.sub(r"\([^)]*\)", " ", s)            # flatten parentheticals
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w]


def _head_nouns(name: str) -> set[str]:
    """The discriminating noun tokens: everything that is not a descriptor."""
    return {t for t in _tokens(name) if t not in _DESCRIPTOR_TOKENS}


def _same_item(new_name: str, rep_name: str) -> bool:
    """True when *new_name* describes the same item as *rep_name*.

    Two names match when their head nouns are equal, or when the new name's
    heads are a subset of the rep's heads (the new name only qualifies an
    already-seen item with extra descriptors). A new name that introduces an
    extra head noun is a different item and never merges here.
    """
    new_heads = _head_nouns(new_name)
    rep_heads = _head_nouns(rep_name)
    if not new_heads or not rep_heads:
        return False                       # all-descriptor name: too generic
    return new_heads == rep_heads or new_heads <= rep_heads


def _worse(a: str | None, b: str | None) -> str | None:
    grades = [g for g in (a, b) if g in CONDITION_GRADES]
    if not grades:
        return a or b
    return max(grades, key=CONDITION_GRADES.index)


def _combine(into: Item, src: Item) -> None:
    """Fold *src* into *into* (deposit-conservative field union)."""
    if len(src.description) > len(into.description):
        into.description = src.description
    into.condition = _worse(into.condition, src.condition)
    into.cleanliness = into.cleanliness or src.cleanliness
    for d in src.defects:
        if d not in into.defects:
            into.defects.append(d)
    into.photo_ids = sorted(set(into.photo_ids) | set(src.photo_ids))
    into.quantity = max(into.quantity, src.quantity)
    into.crop_path = into.crop_path or src.crop_path
    if src.confidence and (not into.confidence or src.confidence > into.confidence):
        into.confidence = src.confidence


def merge_items(items: list[Item], room_code: str) -> list[Item]:
    # Greedy, non-transitive clustering: each item joins the first existing
    # cluster whose representative is "the same item", else starts a new one.
    # Non-transitivity is deliberate — A~B and B~C must not force A~C, which
    # is what collapsed distinct furniture when a shared generic descriptor
    # chained unrelated items together.
    clusters: list[Item] = []
    for it in items:
        target = next((c for c in clusters if _same_item(it.name, c.name)), None)
        if target is None:
            clusters.append(it)
        else:
            _combine(target, it)
    for i, it in enumerate(clusters, start=1):
        it.id = f"{room_code}-{i:03d}"
    return clusters


def attach_detector_crops(items: list[Item], detections: dict) -> None:
    """Give schedule items a detector close-up thumbnail (docs/15 M4).

    The VLM backends cite photos but never map items to YOLOE boxes, so
    their items ship without crops. An item without one borrows the
    best-confidence detection whose label words all appear in the item's
    name, searched only within the photos the item itself cites —
    conservative by design: a wrong close-up is worse than none. The
    offline backend's own crops (and any prior crop) are never replaced.
    """
    for item in items:
        if item.crop_path:
            continue
        name_tokens = set(_tokens(item.name))
        if not name_tokens:
            continue
        best = None
        for pid in item.photo_ids:
            for det in detections.get(pid) or []:
                if not det.crop_path:
                    continue
                label_tokens = set(det.label.lower().split())
                if not label_tokens or not label_tokens <= name_tokens:
                    continue
                if best is None or det.confidence > best.confidence:
                    best = det
        if best is not None:
            item.crop_path = best.crop_path


def room_code(room_name: str, used: set[str]) -> str:
    letters = re.sub(r"[^A-Z]", "", room_name.upper())[:3] or "RM"
    code, n = letters, 2
    while code in used:
        code, n = f"{letters}{n}", n + 1
    used.add(code)
    return code


def _has_review_overlay(item: Item) -> bool:
    return bool(item.rejected_defects or item.comments or item.defect_regions
                or item.not_inspected)


def _apply_review_overlay(new: Item, prior: Item) -> None:
    """Copy human review annotations onto a freshly described item."""
    new.reviewed = prior.reviewed
    new.rejected = prior.rejected
    new.rejected_defects = list(prior.rejected_defects)
    new.not_inspected = prior.not_inspected
    new.defect_regions = list(prior.defect_regions)
    new.comments = list(prior.comments)


def _merge_photos(prior: list[Photo], new: list[Photo]) -> list[Photo]:
    """Keep ingest photos plus any reviewer-added photos from a prior run."""
    new_ids = {p.id for p in new}
    extra = [p for p in prior if p.id not in new_ids]
    return new + extra


def _used_id_numbers(items: list[Item], prefix: str) -> set[int]:
    used: set[int] = set()
    for it in items:
        if not it.id.startswith(f"{prefix}-"):
            continue
        tail = it.id.rsplit("-", 1)[-1]
        if tail.isdigit():
            used.add(int(tail))
    return used


def _renumber_items(items: list[Item], prefix: str,
                    reserved: set[int] | None = None) -> list[Item]:
    """Assign sequential ids, skipping numbers reserved by kept prior items."""
    used = set(reserved or ())
    n = 1
    for it in items:
        while n in used:
            n += 1
        it.id = f"{prefix}-{n:03d}"
        used.add(n)
        n += 1
    return items


def merge_room_with_prior(prior_room: Room | None, new_room: Room,
                          code: str) -> Room:
    """Re-describe a room but keep attested / hand-edited items from *prior_room*.

    Rules (deposit-conservative — never silently discard human work):
    - reviewer-added items (``added_by``) are kept verbatim
    - reviewed or rejected items are kept verbatim (photo refs unioned if AI
      cites more)
    - partial review overlays (struck defects, comments, regions) are copied
      onto matching fresh AI items by normalised name
    - unreviewed prior items absent from the new describe are dropped
    """
    if prior_room is None:
        return new_room

    kept: list[Item] = []
    kept_keys: set[str] = set()
    overlays: dict[str, Item] = {}

    for prior in prior_room.items:
        k = _key(prior)
        if prior.added_by or prior.reviewed or prior.rejected:
            kept.append(prior)
            kept_keys.add(k)
        elif _has_review_overlay(prior):
            overlays[k] = prior

    fresh: list[Item] = []
    for new in new_room.items:
        k = _key(new)
        if k in kept_keys:
            for item in kept:
                if _key(item) == k:
                    item.photo_ids = sorted(set(item.photo_ids) | set(new.photo_ids))
            continue
        if k in overlays:
            _apply_review_overlay(new, overlays[k])
        fresh.append(new)

    fresh = merge_items(fresh, code)
    for item in fresh:
        prior = overlays.get(_key(item))
        if prior:
            _apply_review_overlay(item, prior)

    fresh = _renumber_items(fresh, code, _used_id_numbers(kept, code))
    items = kept + fresh
    photos = _merge_photos(prior_room.photos, new_room.photos)
    return Room(name=new_room.name, summary=new_room.summary,
                items=items, photos=photos)
