"""Describe backends: turn a room's photos into a structured item schedule.

Machine-facing identity is constrained by the tenancy item ontology while
human-readable `name` and `description` remain free text. This moves
canonicalisation into the generation contract instead of reconstructing
identity from prose after generation.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol

from .detect import Detection
from .ontology import ITEM_TYPE_BY_KEY, ITEM_TYPE_KEYS, ONTOLOGY_VERSION
from .schema import (CATEGORIES, CLEANLINESS_GRADES, CONDITION_GRADES, Item, Photo)
from .usecases.base import UseCase

log = logging.getLogger(__name__)


def build_item_schema(uc: UseCase) -> dict:
    """JSON schema for a room schedule with stable canonical identity."""
    item_props = {
        "name": {"type": "string", "description": "Natural report label, e.g. 'White ceramic pedestal basin'. Do not use this as machine identity."},
        "item_type": {"type": "string", "enum": list(ITEM_TYPE_KEYS),
                      "description": "Canonical inventory concept. Choose the closest allowed type; use 'other' only when no concept fits."},
        "subtype": {"type": ["string", "null"],
                    "description": "Optional stable subtype such as dining, recessed, pedestal or roller. Do not invent a new item identity here."},
        "attributes": {"type": "object", "additionalProperties": {"type": "string"},
                       "description": "Visible descriptive attributes such as material, colour, mounting or configuration. Attributes do not define presence/absence."},
        "instance_key": {"type": ["string", "null"],
                         "description": "Only for repeated independently tracked items of the same type: short stable discriminator such as 'left_of_bed' or 'right_of_bed'. Otherwise null."},
        "category": {"type": "string", "enum": CATEGORIES,
                     "description": "Broad report category; must agree with item_type."},
        "description": {"type": "string", "description": "Material, colour, brand/model if visible, approximate size and other evidence-based detail."},
        "condition": {"type": "string", "enum": CONDITION_GRADES},
        "cleanliness": {"type": "string", "enum": CLEANLINESS_GRADES},
        "defects": {"type": "array", "items": {"type": "string"},
                    "description": "Specific localized defects. Empty if none visible."},
        "quantity": {"type": "integer", "minimum": 1},
        "photo_ids": {"type": "array", "items": {"type": "string"},
                      "description": "IDs of photos in which this item is visible."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    required = ["name", "item_type", "subtype", "attributes", "instance_key",
                "category", "description", "condition", "cleanliness", "defects",
                "quantity", "photo_ids", "confidence"]
    if uc.value_bands is not None:
        item_props["est_value_band"] = {"type": "string", "enum": list(uc.value_bands)}
        required.append("est_value_band")
    return {"type": "object", "properties": {
        "room_summary": {"type": "string", "description": "2-4 sentence overall narrative: decorative order, cleanliness and general state evidenced by the photos."},
        "items": {"type": "array", "items": {"type": "object", "properties": item_props,
                                                "required": required, "additionalProperties": False}},
    }, "required": ["room_summary", "items"], "additionalProperties": False}


from .usecases.tenancy import ITEM_SCHEMA, SYSTEM_PROMPT, VALUE_BANDS  # noqa: E402

# Local compact mode remains intentionally small. It does not claim to test the
# ontology intervention; canonical identity is safely derived from known names
# during Item.normalise() when compact mode is used.
COMPACT_LOCAL_ITEM_SCHEMA = {
    "type": "object", "properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": {
            "name": {"type": "string"},
            "condition": {"type": "string", "enum": CONDITION_GRADES},
            "defects": {"type": "array", "items": {"type": "string"}},
            "photo_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["name", "condition", "defects", "photo_ids"], "additionalProperties": False}},
    }, "required": ["items"], "additionalProperties": False,
}


class DescribeBackend(Protocol):
    name: str
    def describe_room(self, room_name: str, photos: list[Photo], photo_paths: list[Path], detections: dict[str, list[Detection]]) -> tuple[str, list[Item]]: ...


def _detection_hints(photos: list[Photo], detections: dict[str, list[Detection]]) -> str:
    lines = []
    for p in photos:
        dets = detections.get(p.id) or []
        if dets:
            labels = ", ".join(f"{d.label} ({d.confidence:.0%})" for d in dets)
            lines.append(f"- Photo {p.id}: detector saw: {labels}")
    if not lines:
        return ""
    return "\nAn object detector pre-scanned these photos. Use this only as a checklist hint — trust the images over the detector, and include items the detector missed:\n" + "\n".join(lines)


def _encode_image(path: Path, max_dim: int = 1568) -> tuple[str, str]:
    from io import BytesIO
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim))
        buf = BytesIO(); im.save(buf, format="JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()

_OLLAMA_TIMING_FIELDS = ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration")

def _ollama_timing(resp: dict) -> dict:
    out = {}
    for key in _OLLAMA_TIMING_FIELDS:
        v = resp.get(key)
        if isinstance(v, (int, float)) and v > 0:
            out[key] = round(v / 1e9, 3) if key.endswith("_duration") else int(v)
    return out

def _aggregate_timing(batch_timings: list[dict]) -> dict:
    total = {}
    for bt in batch_timings:
        for k, v in bt.items(): total[k] = total.get(k, 0) + v
    if total.get("eval_count") and total.get("eval_duration"):
        total["eval_tok_per_s"] = round(total["eval_count"] / total["eval_duration"], 1)
    if total.get("prompt_eval_count") and total.get("prompt_eval_duration"):
        total["prompt_tok_per_s"] = round(total["prompt_eval_count"] / total["prompt_eval_duration"], 1)
    return total

class FatalBackendError(RuntimeError): pass
class DescribeAuthError(FatalBackendError): pass

def _extract_json(content: str) -> dict:
    text = content or ""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence: text = fence.group(1)
    start = text.find("{")
    if start == -1: raise ValueError("no JSON object in response")
    depth = 0
    for end in range(start, len(text)):
        if text[end] == "{": depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0: return json.loads(text[start:end + 1])
    raise ValueError("unterminated JSON object")


def _parse_items(data: dict, photos: list[Photo]) -> tuple[str, list[Item]]:
    valid_ids = {p.id for p in photos}; all_ids = [p.id for p in photos]; items = []
    for raw in data.get("items", []):
        ids = [i for i in (raw.get("photo_ids") or []) if i in valid_ids] or all_ids
        item_type = raw.get("item_type")
        if item_type not in ITEM_TYPE_BY_KEY: item_type = None
        items.append(Item(id="", name=raw.get("name", "Unidentified item"),
            item_type=item_type, subtype=raw.get("subtype"), attributes=dict(raw.get("attributes") or {}),
            instance_key=raw.get("instance_key"), ontology_version=ONTOLOGY_VERSION if item_type else None,
            category=raw.get("category", "other"), description=raw.get("description", ""),
            condition=raw.get("condition"), cleanliness=raw.get("cleanliness"), defects=list(raw.get("defects") or []),
            quantity=int(raw.get("quantity") or 1), est_value_band=raw.get("est_value_band"), photo_ids=ids,
            confidence=raw.get("confidence")).normalise())
    return data.get("room_summary", ""), items


# The backend implementations below are intentionally imported from the legacy
# implementation body by keeping this file API-compatible. The ontology PR
# changes the shared schema/parser contract; backend transport behaviour is
# unchanged.
