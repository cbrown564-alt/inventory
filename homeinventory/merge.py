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

from .schema import CONDITION_GRADES, Item


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
