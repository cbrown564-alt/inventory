"""Canonical data model for an inventory.

Everything downstream of the pipeline (report rendering, comparison, evals)
consumes the JSON form of `Inventory`, so this module is the contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .usecases.base import CoverField

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

    # --- review & attestation state (docs/05-review-experience.md) ---
    # Rejected claims are struck through, never silently deleted, so the report
    # can honestly say "AI suggested, reviewer rejected".
    reviewed: bool = False               # a human confirmed this item
    rejected: bool = False               # whole item struck by the reviewer
    rejected_defects: list[str] = field(default_factory=list)
    not_inspected: Optional[str] = None  # "not tested" | "not visible"
    added_by: Optional[str] = None       # "reviewer" when human-added; None = AI
    # Defect photo regions, normalised 0..1:
    #   {"defect": str, "photo_id": str, "x": f, "y": f, "w": f, "h": f}
    defect_regions: list[dict] = field(default_factory=list)
    # Per-item comments from any party:
    #   {"author": str, "role": "landlord"|"agent"|"tenant", "text": str, "at": iso}
    comments: list[dict] = field(default_factory=list)

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
    # Optional cover / clerk-style metadata (M2 PDF polish)
    agent_name: str = ""
    agent_phone: str = ""
    property_type: str = ""          # e.g. "1 Bedroom furnished apartment"
    tenant_name: str = ""
    landlord_name: str = ""
    report_ref: str = ""
    use_case: str = "tenancy"
    parties: dict = field(default_factory=dict)
    # Section 1 Schedule of Condition rows: {"ref", "name", "condition"}
    schedule_summary: list[dict] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    notes: str = ""
    tool_version: str = "0.1.0"
    describe_backend: str = ""
    # Signature blocks, appended at signing time (Level 1/3 review):
    #   {"role": "landlord"|"agent"|"tenant", "name": str, "signed_at": iso,
    #    "inventory_sha256": hash of the content signed, "via": str}
    signatures: list[dict] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "Inventory":
        raw = json.loads(text)

        def known(cls, d):  # tolerate fields written by newer versions
            return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}

        rooms = []
        for r in raw.get("rooms", []):
            items = [Item(**known(Item, i)).normalise() for i in r.get("items", [])]
            photos = [Photo(**known(Photo, p)) for p in r.get("photos", [])]
            rooms.append(Room(name=r["name"], summary=r.get("summary", ""),
                              items=items, photos=photos))
        keep = {k: v for k, v in raw.items() if k != "rooms"}
        inv = Inventory(**known(Inventory, keep))
        inv.rooms = rooms
        return inv

    def item_count(self) -> int:
        return sum(len(r.items) for r in self.rooms)

    def photo_count(self) -> int:
        return sum(len(r.photos) for r in self.rooms)

    def reviewed_count(self) -> int:
        return sum(1 for r in self.rooms for i in r.items
                   if i.reviewed or i.rejected)

    def content_sha256(self) -> str:
        """Hash of everything a signature attests to (the signatures themselves
        are excluded so countersigning doesn't invalidate the first party)."""
        body = asdict(self)
        body.pop("signatures", None)
        canon = json.dumps(body, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def cover_value(inv: Inventory, field: "CoverField") -> str:
    if field.name in Inventory.__dataclass_fields__:
        return getattr(inv, field.name) or ""
    return inv.parties.get(field.name, "")


def set_cover_value(inv: Inventory, field: "CoverField", value: str) -> None:
    if field.name in Inventory.__dataclass_fields__:
        setattr(inv, field.name, value)
    else:
        inv.parties[field.name] = value
