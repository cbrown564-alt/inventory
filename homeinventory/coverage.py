"""Post-capture coverage check — no AI in the loop (docs/05, Level 4 sidebar).

After a room's photos land, run the local detector (free, fast) against a
per-room expectation list and flag gaps: "No radiator seen in Bedroom 2 —
photograph it or mark N/A." A checklist diff, not a conversation: it cannot
hallucinate items, only prompt a second look.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .schema import Photo

log = logging.getLogger(__name__)

# Expectation vocab must stay inside detect.HOUSEHOLD_VOCAB or YOLOE will
# never report it. "a|b" means any one of the alternatives satisfies the check.
GENERIC_EXPECTED = ["door", "window"]
ROOM_EXPECTATIONS: dict[str, list[str]] = {
    "kitchen": ["sink", "tap", "oven|stove", "refrigerator", "smoke alarm"],
    "bathroom": ["toilet", "sink", "bathtub|shower", "towel rail"],
    "shower": ["toilet", "sink", "bathtub|shower"],
    "wc": ["toilet", "sink"],
    "bedroom": ["radiator", "ceiling light|lamp|light fitting"],
    "living": ["radiator", "ceiling light|lamp|light fitting"],
    "lounge": ["radiator", "ceiling light|lamp|light fitting"],
    "hall": ["smoke alarm"],
    "landing": ["smoke alarm"],
    "general": ["smoke alarm"],
}


def expected_for(room_name: str) -> list[str]:
    name = room_name.lower()
    expected = list(GENERIC_EXPECTED)
    for key, extra in ROOM_EXPECTATIONS.items():
        if key in name:
            for e in extra:
                if e not in expected:
                    expected.append(e)
    return expected


def coverage_gaps(seen_labels: set[str], room_name: str) -> list[str]:
    """Expectations with no satisfying detection, as human-readable names."""
    gaps = []
    for exp in expected_for(room_name):
        if not any(alt in seen_labels for alt in exp.split("|")):
            gaps.append(exp.replace("|", " / "))
    return gaps


def check_capture(capture_dir: Path, rooms: dict[str, list[Photo]],
                  conf: float = 0.25) -> dict[str, list[str]] | None:
    """Detect across every room's photos; return {room: [missing, …]}.
    None means the detector stack is unavailable (no verdict, not a pass)."""
    from .detect import Detector

    detector = Detector(conf=conf)
    report: dict[str, list[str]] = {}
    for room_name, photos in sorted(rooms.items()):
        seen: set[str] = set()
        for p in photos:
            full = Path(p.path)
            if not full.is_absolute():
                full = capture_dir / p.path
            for det in detector.detect(full):
                seen.add(det.label)
        if not detector.available:
            return None
        report[room_name] = coverage_gaps(seen, room_name)
    return report
