"""The capture shot list, as structured data (M5b).

Single source of truth for what to photograph: `homeinventory guide`
prints :func:`guide_text` and the phone capture page renders the same
categories from the active use-case profile (`per_room_shots` /
`whole_property_shots`), so the two surfaces cannot drift.
"""

from __future__ import annotations

from .usecases import DEFAULT_USE_CASE, get_use_case
from .usecases.tenancy import TENANCY

# Back-compat aliases — default tenancy profile.
PER_ROOM_SHOTS: list[dict] = list(TENANCY.per_room_shots)
WHOLE_PROPERTY_SHOTS: list[str] = list(TENANCY.whole_property_shots)

TIPS = ("turn all lights on, open curtains, shoot landscape, hold still a\n"
        "beat before each shot, avoid your reflection in mirrors/windows.")

_HEADER = """\
HOMEINVENTORY CAPTURE GUIDE
===========================
Folder layout: one folder per room inside your capture folder, e.g.

  capture/
    Living Room/   Kitchen/   Bedroom 1/   Bathroom/   Hallway/

Photos beat video for quality; a steady, slow video per room also works
(sharp keyframes are extracted automatically). Keep your phone's date/time
correct — EXIF timestamps go into the evidence manifest.
"""


def guide_text(use_case_key: str | None = None) -> str:
    """Reconstruct the printed guide from the use-case profile shot list."""
    uc = get_use_case(use_case_key or DEFAULT_USE_CASE)
    per_room = uc.per_room_shots
    whole = uc.whole_property_shots
    width = max(len(s["label"]) for s in per_room) + 1
    lines = [_HEADER, f"{uc.display_name} — per room (~15-25 photos):"]
    for i, shot in enumerate(per_room, start=1):
        lines.append(f"  {i}. {shot['label']:<{width}}({shot['count']})")
    lines.append("")
    lines.append('WHOLE PROPERTY (put in a "General" folder):')
    for shot in whole:
        lines.append(f"  - {shot}")
    lines.append("")
    lines.append(f"TIPS: {TIPS}")
    return "\n".join(lines) + "\n"
