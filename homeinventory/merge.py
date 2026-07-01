"""De-duplicate items reported across multiple photos of the same room.

The describe backend sees a whole room's photos in one call, so duplication is
already rare with the claude backend; the offline backend and any per-photo
mode need this pass. Strategy: within a room, items with the same normalised
name (or same detector label) merge — keeping the longest description, the
worst condition grade (conservative for deposit purposes), the union of
defects and photo references.
"""

from __future__ import annotations

import re

from .schema import CONDITION_GRADES, Item, Photo, Room


def _key(item: Item) -> str:
    base = item.detector_label or item.name
    base = re.sub(r"\bx\s*\d+$", "", base.strip().lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", base)


def _worse(a: str | None, b: str | None) -> str | None:
    grades = [g for g in (a, b) if g in CONDITION_GRADES]
    if not grades:
        return a or b
    return max(grades, key=CONDITION_GRADES.index)


def merge_items(items: list[Item], room_code: str) -> list[Item]:
    merged: dict[str, Item] = {}
    order: list[str] = []
    for it in items:
        k = _key(it)
        if k in merged:
            m = merged[k]
            if len(it.description) > len(m.description):
                m.description = it.description
            m.condition = _worse(m.condition, it.condition)
            m.cleanliness = m.cleanliness or it.cleanliness
            for d in it.defects:
                if d not in m.defects:
                    m.defects.append(d)
            m.photo_ids = sorted(set(m.photo_ids) | set(it.photo_ids))
            m.quantity = max(m.quantity, it.quantity)
            m.crop_path = m.crop_path or it.crop_path
            if it.confidence and (not m.confidence or it.confidence > m.confidence):
                m.confidence = it.confidence
        else:
            merged[k] = it
            order.append(k)
    out = [merged[k] for k in order]
    for i, it in enumerate(out, start=1):
        it.id = f"{room_code}-{i:03d}"
    return out


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
