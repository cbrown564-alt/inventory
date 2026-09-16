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

CONDITION_GRADES = ["new", "excellent", "good", "fair", "poor"]
CLEANLINESS_GRADES = ["professionally cleaned", "cleaned to domestic standard", "requires cleaning"]

CATEGORIES = [
    "structure", "fixture", "appliance", "furniture", "soft furnishing",
    "electronics", "kitchenware", "decor", "safety", "meter", "other",
]


def _norm_grade(value: Optional[str], allowed: list[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    if v in allowed:
        return v
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
    id: str
    path: str
    room: str
    sha256: str = ""
    captured_at: Optional[str] = None
    source_video: Optional[str] = None
    cover_anchor: bool = False
    note: Optional[str] = None
    hero: Optional[int] = None
    quality: Optional[float] = None
    describe_eligible: Optional[bool] = None
    presentation_eligible: Optional[bool] = None


@dataclass
class Item:
    id: str
    name: str
    category: str = "other"
    description: str = ""
    # Stable machine identity. `name` remains human-readable presentation text.
    # Legacy inventories may leave these unset; normalise() safely derives an
    # item_type only for known, unambiguous aliases.
    item_type: Optional[str] = None
    subtype: Optional[str] = None
    attributes: dict[str, str] = field(default_factory=dict)
    instance_key: Optional[str] = None
    ontology_version: Optional[str] = None
    condition: Optional[str] = None
    cleanliness: Optional[str] = None
    defects: list[str] = field(default_factory=list)
    quantity: int = 1
    est_value_band: Optional[str] = None
    photo_ids: list[str] = field(default_factory=list)
    crop_path: Optional[str] = None
    crop_confidence: Optional[float] = None
    crop_status: Optional[str] = None
    detector_label: Optional[str] = None
    confidence: Optional[float] = None
    reviewed: bool = False
    rejected: bool = False
    rejected_defects: list[str] = field(default_factory=list)
    not_inspected: Optional[str] = None
    added_by: Optional[str] = None
    defect_regions: list[dict] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)

    def normalise(self) -> "Item":
        from .ontology import (ITEM_TYPE_BY_KEY, ONTOLOGY_VERSION,
                               canonicalize_name, category_for)

        self.condition = _norm_grade(self.condition, CONDITION_GRADES)
        self.cleanliness = _norm_grade(self.cleanliness, CLEANLINESS_GRADES)
        if self.item_type not in ITEM_TYPE_BY_KEY:
            self.item_type = canonicalize_name(self.name)
        if self.item_type:
            # Canonical identity owns category; this removes another source of
            # model-to-model drift while retaining the old field for reports.
            self.category = category_for(self.item_type)
            self.ontology_version = self.ontology_version or ONTOLOGY_VERSION
        elif self.category not in CATEGORIES:
            self.category = "other"
        self.quantity = max(1, int(self.quantity or 1))
        return self


@dataclass
class Room:
    name: str
    summary: str = ""
    items: list[Item] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)
    cover_status: Optional[str] = None
    cover_review_reason: Optional[str] = None


@dataclass
class Inventory:
    property_address: str = ""
    inspected_by: str = ""
    inspected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    report_type: str = "Inventory & Schedule of Condition"
    agent_name: str = ""
    agent_phone: str = ""
    property_type: str = ""
    tenant_name: str = ""
    landlord_name: str = ""
    report_ref: str = ""
    use_case: str = "tenancy"
    parties: dict = field(default_factory=dict)
    schedule_summary: list[dict] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    notes: str = ""
    tool_version: str = "0.1.0"
    describe_backend: str = ""
    signatures: list[dict] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "Inventory":
        raw = json.loads(text)

        def known(cls, d):
            return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}

        rooms = []
        for r in raw.get("rooms", []):
            items = [Item(**known(Item, i)).normalise() for i in r.get("items", [])]
            photos = [Photo(**known(Photo, p)) for p in r.get("photos", [])]
            rooms.append(Room(name=r["name"], summary=r.get("summary", ""), items=items,
                              photos=photos, cover_status=r.get("cover_status"),
                              cover_review_reason=r.get("cover_review_reason")))
        keep = {k: v for k, v in raw.items() if k != "rooms"}
        inv = Inventory(**known(Inventory, keep))
        inv.rooms = rooms
        return inv

    def item_count(self) -> int:
        return sum(len(r.items) for r in self.rooms)

    def photo_count(self) -> int:
        return sum(len(r.photos) for r in self.rooms)

    def reviewed_count(self) -> int:
        return sum(1 for r in self.rooms for i in r.items if i.reviewed or i.rejected)

    def content_sha256(self) -> str:
        body = asdict(self)
        body.pop("signatures", None)
        canon = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
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
