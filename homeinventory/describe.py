"""Describe backends with ontology-constrained machine identity.

The backend transports live in ``_describe_impl``.  This module owns the
model-facing schema and parser contract so canonical identity is established
at generation time rather than reconstructed from report prose afterwards.
"""
from __future__ import annotations

from .canonical_contract import build_canonical_item_schema, validate_decomposition
from .ontology import ONTOLOGY_VERSION
from .schema import (CATEGORIES, CLEANLINESS_GRADES, CONDITION_GRADES, Item,
                     Photo)
from .usecases.base import UseCase


def build_item_schema(uc: UseCase) -> dict:
    """Build the production room schema with canonical item identity required."""
    canonical = build_canonical_item_schema(include_value_band=False)["properties"]["items"]["items"]["properties"]
    item_props = {
        "name": {
            "type": "string",
            "description": "Natural report label; presentation only, not machine identity.",
        },
        "item_type": canonical["item_type"],
        "subtype": canonical["subtype"],
        "attributes": canonical["attributes"],
        "instance_key": canonical["instance_key"],
        "category": {"type": "string", "enum": CATEGORIES},
        "description": {
            "type": "string",
            "description": "Material, colour, brand/model if visible, approximate size.",
        },
        "condition": {"type": "string", "enum": CONDITION_GRADES},
        "cleanliness": {"type": "string", "enum": CLEANLINESS_GRADES},
        "defects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific localized defects. Empty if none visible.",
        },
        "quantity": {"type": "integer", "minimum": 1},
        "photo_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of the photos this item is visible in.",
        },
        "confidence": {
            "type": "number", "minimum": 0, "maximum": 1,
            "description": "0-1 confidence that the item is correctly identified and graded.",
        },
    }
    required = [
        "name", "item_type", "subtype", "attributes", "instance_key",
        "category", "description", "condition", "cleanliness", "defects",
        "quantity", "photo_ids", "confidence",
    ]
    if uc.value_bands is not None:
        item_props["est_value_band"] = {
            "type": "string", "enum": list(uc.value_bands),
        }
        required.append("est_value_band")
    return {
        "type": "object",
        "properties": {
            "room_summary": {
                "type": "string",
                "description": "2-4 sentence evidence-based room narrative.",
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        },
        "required": ["room_summary", "items"],
        "additionalProperties": False,
    }


# Import transports only after build_item_schema exists. tenancy.ITEM_SCHEMA is
# lazy and calls back into this function while _describe_impl is importing.
from . import _describe_impl as _impl  # noqa: E402
from ._describe_impl import *  # noqa: E402,F401,F403


def _parse_items(data: dict, photos: list[Photo]) -> tuple[str, list[Item]]:
    """Persist model-emitted canonical identity after defensive validation."""
    valid_ids = {p.id for p in photos}
    all_ids = [p.id for p in photos]
    items: list[Item] = []
    for raw in data.get("items", []):
        ids = [i for i in (raw.get("photo_ids") or []) if i in valid_ids] or all_ids
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
        items.append(Item(
            id="",
            name=raw.get("name", "Unidentified item"),
            item_type=raw.get("item_type"),
            subtype=raw.get("subtype"),
            attributes=dict(raw.get("attributes") or {}),
            instance_key=raw.get("instance_key"),
            ontology_version=ONTOLOGY_VERSION,
            category=raw.get("category", "other"),
            description=raw.get("description", ""),
            condition=raw.get("condition"),
            cleanliness=raw.get("cleanliness"),
            defects=list(raw.get("defects") or []),
            quantity=int(raw.get("quantity") or 1),
            est_value_band=raw.get("est_value_band"),
            photo_ids=ids,
            confidence=raw.get("confidence"),
        ).normalise())
    return data.get("room_summary", ""), items


# Functions/classes defined in _describe_impl resolve these globals at call
# time. Patch them once so every non-compact backend uses the canonical schema
# and parser without duplicating the transport implementation.
_impl.build_item_schema = build_item_schema
_impl._parse_items = _parse_items

# Refresh the public back-compat schema after patching. The default get_backend
# path builds a fresh schema per use case; this constant is for direct imports.
from .usecases.tenancy import TENANCY as _TENANCY  # noqa: E402
ITEM_SCHEMA = build_item_schema(_TENANCY)
_impl.ITEM_SCHEMA = ITEM_SCHEMA
