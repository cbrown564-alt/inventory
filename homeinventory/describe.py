"""Describe backends: turn a room's photos into a structured item schedule.

Two backends ship in the prototype:

* ``claude``  — Claude vision with a JSON-schema-constrained output. Highest
  quality; costs pennies per property. Default model is claude-opus-4-8;
  pass --model claude-haiku-4-5 / claude-sonnet-4-6 to trade quality for cost.
* ``offline`` — no network, no model: items come straight from the detector
  (or a bare placeholder). Used for tests/evals and as a graceful fallback.

A ``local`` backend (open-weight VLM via Ollama, same prompt contract) is the
planned fully-open-source path — see docs/03-implementation-plan.md M2.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional, Protocol

from .detect import Detection
from .schema import (CATEGORIES, CLEANLINESS_GRADES, CONDITION_GRADES, Item,
                     Photo)

log = logging.getLogger(__name__)

VALUE_BANDS = ["<£50", "£50-250", "£250-1000", ">£1000"]

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "room_summary": {
            "type": "string",
            "description": "2-4 sentence overall narrative: decorative order, "
                           "cleanliness, general state of the room as evidenced "
                           "by these photos.",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short item name, e.g. 'Three-seat sofa'"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "description": {
                        "type": "string",
                        "description": "Material, colour, brand/model if visible, "
                                       "approximate size. Written like a professional "
                                       "inventory clerk.",
                    },
                    "condition": {"type": "string", "enum": CONDITION_GRADES},
                    "cleanliness": {"type": "string", "enum": CLEANLINESS_GRADES},
                    "defects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific localized defects, e.g. 'scuff mark "
                                       "10cm left of door handle'. Empty if none visible.",
                    },
                    "quantity": {"type": "integer"},
                    "est_value_band": {"type": "string", "enum": VALUE_BANDS},
                    "photo_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs of the photos this item is visible in.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0-1: how confident you are this item is "
                                       "correctly identified and graded.",
                    },
                },
                "required": ["name", "category", "description", "condition",
                             "cleanliness", "defects", "quantity",
                             "est_value_band", "photo_ids", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["room_summary", "items"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are a professional property inventory clerk preparing a Tenancy Deposit
Scheme (TDS) compliant Inventory & Schedule of Condition. You are exhaustive,
precise, and evidence-based.

Rules:
- List EVERY distinct item of note visible in the photos: structural elements
  (ceiling, walls, woodwork, doors, windows, flooring), fixtures (lights,
  sockets, radiators, blinds), appliances, furniture, soft furnishings,
  electronics, and notable contents. Group identical small items (e.g.
  "Dining chairs x4").
- Each room's structural elements (walls, ceiling, flooring, door, window)
  should each appear as their own item with their own grade.
- Condition grades: new / excellent / good / fair / poor. "Good" means sound
  with light wear; reserve "fair" for visible wear/marks and "poor" for damage.
- Be SPECIFIC about defects and their location ("chip to front-left corner of
  worktop"), since adjudicators weigh specificity heavily. Never invent
  defects you cannot see; if the photo is ambiguous, omit rather than guess.
- Describe materials and colours like a clerk: "Oak-effect laminate flooring",
  "Emulsioned magnolia walls", not "wooden floor".
- Only report items actually visible in the supplied photos.
"""


class DescribeBackend(Protocol):
    name: str

    def describe_room(self, room_name: str, photos: list[Photo],
                      photo_paths: list[Path],
                      detections: dict[str, list[Detection]]) -> tuple[str, list[Item]]:
        """Return (room_summary, items) for one room."""
        ...


def _detection_hints(photos: list[Photo],
                     detections: dict[str, list[Detection]]) -> str:
    lines = []
    for p in photos:
        dets = detections.get(p.id) or []
        if dets:
            labels = ", ".join(f"{d.label} ({d.confidence:.0%})" for d in dets)
            lines.append(f"- Photo {p.id}: detector saw: {labels}")
    if not lines:
        return ""
    return (
        "\nAn object detector pre-scanned these photos. Use this only as a "
        "checklist hint — trust the images over the detector, and include "
        "items the detector missed:\n" + "\n".join(lines)
    )


def _encode_image(path: Path, max_dim: int = 1568) -> tuple[str, str]:
    """Return (media_type, base64) — downscaled to keep token cost sane."""
    from io import BytesIO
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()


class DescribeAuthError(RuntimeError):
    """Credentials missing or rejected — fatal for the whole build, not one room."""


class ClaudeBackend:
    name = "claude"

    def __init__(self, model: str = "claude-opus-4-8"):
        import anthropic
        self._anthropic = anthropic
        # Credential resolution is delegated to the SDK: ANTHROPIC_API_KEY,
        # ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile all work.
        self.client = anthropic.Anthropic()
        self.model = model

    def describe_room(self, room_name, photos, photo_paths, detections):
        content = []
        for photo, path in zip(photos, photo_paths):
            media_type, data = _encode_image(path)
            content.append({"type": "text", "text": f"Photo {photo.id}:"})
            content.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": media_type, "data": data}})
        content.append({
            "type": "text",
            "text": (
                f"These photos all show the room: \"{room_name}\".\n"
                "Produce the complete item schedule for this room."
                + _detection_hints(photos, detections)
            ),
        })

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": ITEM_SCHEMA}},
            )
        except self._anthropic.AuthenticationError as e:
            raise DescribeAuthError(
                "Anthropic rejected the credentials. Set a valid ANTHROPIC_API_KEY, "
                "run `ant auth login`, or use --backend offline."
            ) from e
        except TypeError as e:
            if "authentication" in str(e).lower():
                raise DescribeAuthError(
                    "No Anthropic credentials found. Set ANTHROPIC_API_KEY, run "
                    "`ant auth login`, or use --backend offline."
                ) from e
            raise
        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"item schedule for '{room_name}' was truncated at the output "
                "token limit — split the room into fewer photos per folder"
            )
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)

        items = []
        for i, raw in enumerate(data.get("items", []), start=1):
            raw.setdefault("photo_ids", [p.id for p in photos])
            items.append(Item(
                id="",  # assigned during merge
                name=raw.get("name", "Unidentified item"),
                category=raw.get("category", "other"),
                description=raw.get("description", ""),
                condition=raw.get("condition"),
                cleanliness=raw.get("cleanliness"),
                defects=list(raw.get("defects") or []),
                quantity=int(raw.get("quantity") or 1),
                est_value_band=raw.get("est_value_band"),
                photo_ids=list(raw.get("photo_ids") or []),
                confidence=raw.get("confidence"),
            ).normalise())
        return data.get("room_summary", ""), items


class OfflineBackend:
    """Detector-only: structurally complete report, minimal descriptions."""
    name = "offline"

    def describe_room(self, room_name, photos, photo_paths, detections):
        # aggregate detector labels across the room's photos
        by_label: dict[str, dict] = {}
        for p in photos:
            for d in detections.get(p.id) or []:
                entry = by_label.setdefault(d.label, {
                    "photos": [], "best_conf": 0.0, "crop": None, "count_by_photo": {}})
                entry["photos"].append(p.id)
                entry["count_by_photo"][p.id] = entry["count_by_photo"].get(p.id, 0) + 1
                if d.confidence > entry["best_conf"]:
                    entry["best_conf"] = d.confidence
                    entry["crop"] = d.crop_path
        items = []
        for label, e in sorted(by_label.items()):
            # quantity: max simultaneous instances in a single photo
            qty = max(e["count_by_photo"].values())
            items.append(Item(
                id="",
                name=label.capitalize(),
                category="other",
                description=f"Detected automatically ({e['best_conf']:.0%} confidence). "
                            "Review and add material/colour details.",
                condition=None,
                cleanliness=None,
                quantity=qty,
                photo_ids=sorted(set(e["photos"])),
                crop_path=e["crop"],
                detector_label=label,
                confidence=e["best_conf"],
            ).normalise())
        summary = (f"{len(items)} item type(s) auto-detected in {room_name}. "
                   "Offline mode: condition grades require manual review or a "
                   "VLM backend (--backend claude).")
        return summary, items


def get_backend(name: str, model: Optional[str] = None) -> DescribeBackend:
    if name == "claude":
        return ClaudeBackend(model=model or "claude-opus-4-8")
    if name == "offline":
        return OfflineBackend()
    raise ValueError(f"unknown describe backend: {name!r} (expected claude|offline)")
