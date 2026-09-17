"""Experimental ontology-constrained generation contract.

Kept separate from the production describe path until the correspondence
experiment establishes that constrained decomposition improves stability
without hiding genuine additions/removals.
"""
from __future__ import annotations

from .ontology import ITEM_TYPE_BY_KEY, ITEM_TYPE_KEYS, ONTOLOGY_VERSION
from .schema import CLEANLINESS_GRADES, CONDITION_GRADES

DECOMPOSITION_RULES = """\
Canonical identity rules:
- `item_type` is machine identity. Select exactly one allowed ontology key.
- `display_name` is report prose. Never encode identity only in display_name.
- Material, colour, finish, brand, size and style are attributes/description,
  not new item types.
- Split components when they can independently carry condition or change:
  door vs door_frame vs door_handle; bed vs mattress; basin vs tap; bath vs
  bath_panel; shower vs shower_screen vs shower_tray; window vs window_sill.
- Do not split stylistic refinements into identities: pedestal basin remains
  basin; recessed/pendant/table lamps remain light; roller blind remains blind;
  dining/office chair remains chair; fridge-freezer remains refrigerator.
- Do not combine different canonical concepts into one record. For example,
  never emit 'window and sill', 'door and handle', or 'patio doors and windows'.
- Group genuinely interchangeable repeated items only when they are intended
  to be tracked together. Otherwise use `instance_key` as a stable positional
  discriminator such as left_of_bed/right_of_bed.
- Use `other` only when no allowed item_type fits. Do not force an unknown
  object into a semantically wrong class.
"""


def build_canonical_item_schema(*, include_value_band: bool = True) -> dict:
    """Strict schema for the constrained-generation experiment."""
    props = {
        "item_type": {
            "type": "string", "enum": list(ITEM_TYPE_KEYS),
            "description": "Stable machine identity from tenancy-items-v1.",
        },
        "display_name": {
            "type": "string",
            "description": "Natural report label; descriptive only, not identity.",
        },
        "subtype": {
            "type": ["string", "null"],
            "description": "Optional refinement that does not define presence/absence.",
        },
        "attributes": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Visible material/colour/finish/mounting/configuration attributes.",
        },
        "instance_key": {
            "type": ["string", "null"],
            "description": "Stable discriminator only for repeated independently tracked items.",
        },
        "description": {"type": "string"},
        "condition": {"type": "string", "enum": CONDITION_GRADES},
        "cleanliness": {"type": "string", "enum": CLEANLINESS_GRADES},
        "defects": {"type": "array", "items": {"type": "string"}},
        "quantity": {"type": "integer", "minimum": 1},
        "photo_ids": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    required = list(props)
    if include_value_band:
        props["est_value_band"] = {
            "type": "string", "enum": ["<£50", "£50-250", "£250-1000", ">£1000"]
        }
        required.append("est_value_band")
    return {
        "type": "object",
        "properties": {
            "ontology_version": {"type": "string", "const": ONTOLOGY_VERSION},
            "room_summary": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        },
        "required": ["ontology_version", "room_summary", "items"],
        "additionalProperties": False,
    }


def validate_decomposition(payload: dict) -> list[str]:
    """Cheap deterministic checks before a constrained output is scored."""
    errors: list[str] = []
    if payload.get("ontology_version") != ONTOLOGY_VERSION:
        errors.append("wrong ontology_version")
    for idx, item in enumerate(payload.get("items") or []):
        item_type = item.get("item_type")
        if item_type not in ITEM_TYPE_BY_KEY:
            errors.append(f"items[{idx}].item_type is not an allowed ontology key")
        if not item.get("display_name"):
            errors.append(f"items[{idx}].display_name is empty")
        if int(item.get("quantity") or 0) < 1:
            errors.append(f"items[{idx}].quantity must be >= 1")
    return errors
