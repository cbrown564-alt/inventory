"""Canonical data model for an inventory.

Everything downstream of the pipeline (report rendering, comparison, evals)
consumes the JSON form of `Inventory`, so this module is the contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# Industry-standard vocabularies (AIIC/TDS practice). Ordinal, best -> worst.
CONDITION_GRADES = ["new", "excellent", "good", "fair", "poor"]
CLEANLINESS_GRADES = ["professionally cleaned", "cleaned to domestic standard", "requires cleaning"]

CATEGORIES = [
    "structure",      # ceiling, walls, woodwork, doors, windows, flooring
    "fixture",        # light fittings, sockets, radiators, blinds, built-ins
    "appliance",
    "furniture",
    "soft furnishing",
    "electronics",
    "kitchenware",
    "decor",
    "safety",         # smoke/CO alarms, extinguishers
    "meter",
    "other",
]


def _norm_grade(value: Optional[str], allowed: list[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    if v in allowed:
        return v
    # tolerate common variants from model output
    aliases = {
        "very good": "excellent", "ok": "fair", "okay": "fair", "worn": "fair",
        "damaged": "poor", "used - good": "good", "as new": "new",
        "professional": "professionally cleaned", "clean": "cleaned to domestic standard",
        "domestic": "cleaned to domestic standard", "dirty": "requires cleaning",
        "needs cleaning": "requires cleaning",
    }
    return aliases.get(v, v if v in allowed else None)


@dataclass
class Photo:
    """A source image (original photo or extracted video keyframe)."""
    id: str                    # e.g. "P012"
    path: str                  # path relative to the capture root
    room: str
    sha256: str = ""
    captured_at: Optional[str] = None   # ISO 8601, from EXIF when available
    source_video: Optional[str] = None  # set when extracted from a video
    note: Optional[str] = None


@dataclass
class Item:
    id: str                    # e.g. "KIT-003"
    name: str
    category: str = "other"
    description: str = ""      # material/colour/brand detail
    condition: Optional[str] = None      # CONDITION_GRADES
    cleanliness: Optional[str] = None    # CLEANLINESS_GRADES
    defects: list[str] = field(default_factory=list)
    quantity: int = 1
    est_value_band: Optional[str] = None  # "<£50" | "£50-250" | "£250-1000" | ">£1000"
    photo_ids: list[str] = field(default_factory=list)
    crop_path: Optional[str] = None      # detector crop used as report thumbnail
    detector_label: Optional[str] = None
    confidence: Optional[float] = None   # describe-backend confidence 0..1

    def normalise(self) -> "Item":
        self.condition = _norm_grade(self.condition, CONDITION_GRADES)
        self.cleanliness = _norm_grade(self.cleanliness, CLEANLINESS_GRADES)
        if self.category not in CATEGORIES:
            self.category = "other"
        self.quantity = max(1, int(self.quantity or 1))
        return self


@dataclass
class Room:
    name: str
    summary: str = ""          # overall decorative order / cleanliness narrative
    items: list[Item] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)


@dataclass
class Inventory:
    property_address: str = ""
    inspected_by: str = ""
    inspected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    report_type: str = "Inventory & Schedule of Condition"
    rooms: list[Room] = field(default_factory=list)
    notes: str = ""
    tool_version: str = "0.1.0"
    describe_backend: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "Inventory":
        raw = json.loads(text)
        rooms = []
        for r in raw.get("rooms", []):
            items = [Item(**i).normalise() for i in r.get("items", [])]
            photos = [Photo(**p) for p in r.get("photos", [])]
            rooms.append(Room(name=r["name"], summary=r.get("summary", ""),
                              items=items, photos=photos))
        keep = {k: v for k, v in raw.items() if k != "rooms"}
        inv = Inventory(**{k: v for k, v in keep.items()
                           if k in Inventory.__dataclass_fields__})
        inv.rooms = rooms
        return inv

    def item_count(self) -> int:
        return sum(len(r.items) for r in self.rooms)

    def photo_count(self) -> int:
        return sum(len(r.photos) for r in self.rooms)
