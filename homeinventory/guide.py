"""The capture shot list, as structured data (M5b).

Single source of truth for what to photograph: `homeinventory guide`
prints :func:`guide_text` and the phone capture page renders the same
categories (`PER_ROOM_SHOTS` / `WHOLE_PROPERTY_SHOTS`), so the two
surfaces cannot drift. The text output is byte-identical to the GUIDE
string that previously lived in cli.py.
"""

from __future__ import annotations

# Per-room shot categories: label + expected shot count. The phone page's
# tick-off checklist and the printed guide both render from this list.
PER_ROOM_SHOTS: list[dict] = [
    {"label": "Wide shot of each wall, floor-to-ceiling", "count": "4 photos"},
    {"label": "Floor coverage + close-up of any marks", "count": "2-3"},
    {"label": "Ceiling and light fittings", "count": "1-2"},
    {"label": "Door (both sides), window(s) incl. frames/sills", "count": "2-4"},
    {"label": "Each appliance: front + inside + behind if movable", "count": "2-3 each"},
    {"label": "Each large furniture item: front + wear points", "count": "1-2 each"},
    {"label": "EVERY existing defect close-up, with context shot", "count": "as needed"},
]

# Whole-property shots (conventionally a "General" room folder).
WHOLE_PROPERTY_SHOTS: list[str] = [
    "All meters (close enough to read the numbers)",
    "Smoke / CO alarms (one photo each, press test button)",
    "Keys handed over, laid out on a plain surface",
    "Boiler, stopcock, fuse box",
]

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


def guide_text() -> str:
    """Reconstruct the printed guide from the structured shot list."""
    width = max(len(s["label"]) for s in PER_ROOM_SHOTS) + 1
    lines = [_HEADER, "PER ROOM (~15-25 photos):"]
    for i, shot in enumerate(PER_ROOM_SHOTS, start=1):
        lines.append(f"  {i}. {shot['label']:<{width}}({shot['count']})")
    lines.append("")
    lines.append('WHOLE PROPERTY (put in a "General" folder):')
    for shot in WHOLE_PROPERTY_SHOTS:
        lines.append(f"  - {shot}")
    lines.append("")
    lines.append(f"TIPS: {TIPS}")
    return "\n".join(lines) + "\n"
