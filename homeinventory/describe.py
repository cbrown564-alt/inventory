"""Describe backends with ontology-constrained machine identity.

The backend transports live in ``_describe_impl``. This module owns the
model-facing schema and parser contract so canonical identity is established
at generation time rather than reconstructed from report prose afterwards.
"""
from __future__ import annotations

from .canonical_contract import build_canonical_item_schema, validate_decomposition
from .ontology import ONTOLOGY_VERSION
from .schema import CATEGORIES, CLEANLINESS_GRADES, CONDITION_GRADES, Item, Photo
from .usecases.base import UseCase


def build_item_schema(uc: UseCase) -> dict:
    """Build the production room schema with canonical item identity required."""
    canonical = build_canonical_item_schema(include_value_band=False)["properties"]["items"]["items"]["properties"]
    item_props = {
        "name": {"type": "string", "description": "Natural report label; presentation only, not machine identity."},
        "item_type": canonical["item_type"],
        "subtype": canonical["subtype"],
        "attributes": canonical["attributes"],
        "instance_key": canonical["instance_key"],
        "category": {"type": "string", "enum": CATEGORIES},
        "description": {"type": "string", "description": "Material, colour, brand/model if visible, approximate size."},
        "condition": {"type": "string", "enum": CONDITION_GRADES},
        "cleanliness": {"type": "string", "enum": CLEANLINESS_GRADES},
        "defects": {"type": "array", "items": {"type": "string"}, "description": "Specific localized defects. Empty if none visible."},
        "quantity": {"type": "integer", "minimum": 1},
        "photo_ids": {"type": "array", "items": {"type": "string"}, "description": "IDs of the photos this item is visible in."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "0-1 confidence that the item is correctly identified and graded."},
    }
    required = ["name", "item_type", "subtype", "attributes", "instance_key", "category", "description", "condition", "cleanliness", "defects", "quantity", "photo_ids", "confidence"]
    if uc.value_bands is not None:
        item_props["est_value_band"] = {"type": "string", "enum": list(uc.value_bands)}
        required.append("est_value_band")
    return {
        "type": "object",
        "properties": {
            "room_summary": {"type": "string", "description": "2-4 sentence evidence-based room narrative."},
            "items": {"type": "array", "items": {"type": "object", "properties": item_props, "required": required, "additionalProperties": False}},
        },
        "required": ["room_summary", "items"],
        "additionalProperties": False,
    }


from . import _describe_impl as _impl  # noqa: E402
from ._describe_impl import *  # noqa: E402,F401,F403
# Star-import intentionally excludes private names. describe.py historically
# exposed several helpers used by tests, benchmarks and eval tooling, so keep
# the module split API-transparent.
for _compat_name in dir(_impl):
    if (_compat_name.startswith("_") and not _compat_name.startswith("__")
            and _compat_name != "_parse_items"):
        globals().setdefault(_compat_name, getattr(_impl, _compat_name))


def _parse_items(data: dict, photos: list[Photo]) -> tuple[str, list[Item]]:
    """Parse both canonical production payloads and legacy/compact payloads.

    Canonical outputs are strictly validated. Legacy and compact local outputs
    predate item_type and retain their old semantics; this is required for
    cached eval records and the intentionally smaller local response schema.
    """
    valid_ids = {p.id for p in photos}
    all_ids = [p.id for p in photos]
    items: list[Item] = []
    for raw in data.get("items", []):
        ids = [i for i in (raw.get("photo_ids") or []) if i in valid_ids] or all_ids
        canonical = raw.get("item_type") is not None
        if canonical:
            errors = validate_decomposition({
                "ontology_version": ONTOLOGY_VERSION,
                "items": [{
                    "item_type": raw.get("item_type"),
                    "display_name": raw.get("name", "Unidentified item"),
                    "quantity": raw.get("quantity") or 1,
                }],
            })
            if errors:
                raise ValueError("; ".join(errors))
        item = Item(
            id="", name=raw.get("name", "Unidentified item"),
            item_type=raw.get("item_type"), subtype=raw.get("subtype"),
            attributes=dict(raw.get("attributes") or {}), instance_key=raw.get("instance_key"),
            ontology_version=ONTOLOGY_VERSION if canonical else None,
            category=raw.get("category", "other"), description=raw.get("description", ""),
            condition=raw.get("condition"), cleanliness=raw.get("cleanliness"),
            defects=list(raw.get("defects") or []), quantity=int(raw.get("quantity") or 1),
            est_value_band=raw.get("est_value_band"), photo_ids=ids, confidence=raw.get("confidence"),
        ).normalise()
        if not canonical:
            # Preserve the historical compact/legacy parser contract. Ontology
            # backfill remains available when loading persisted inventories via
            # Inventory.from_json, but a compact inference response is not
            # silently promoted into the constrained-generation experiment.
            item.item_type = None
            item.subtype = None
            item.attributes = {}
            item.instance_key = None
            item.ontology_version = None
            item.category = raw.get("category", "other") if raw.get("category", "other") in CATEGORIES else "other"
        items.append(item)
    return data.get("room_summary", ""), items


_impl.build_item_schema = build_item_schema
_impl._parse_items = _parse_items

from .usecases.tenancy import TENANCY as _TENANCY  # noqa: E402
ITEM_SCHEMA = build_item_schema(_TENANCY)
_impl.ITEM_SCHEMA = ITEM_SCHEMA
