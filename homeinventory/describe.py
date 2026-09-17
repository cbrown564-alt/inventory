"""Describe backends: turn a room's photos into a structured item schedule.

Four backends:

* ``openai`` — OpenAI-compatible providers, including Gemini and OpenRouter.
* ``claude`` — Claude vision with JSON-schema-constrained output.
* ``local`` — open-weight VLM via a local Ollama server.
* ``offline`` — detector-only fallback used for tests/evals.
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

from .canonical_contract import canonical_item_schema, validate_canonical_payload
from .detect import Detection
from .ontology import ONTOLOGY_VERSION
from .schema import (CATEGORIES, CLEANLINESS_GRADES, CONDITION_GRADES, Item,
                     Photo)
from .usecases.base import UseCase

log = logging.getLogger(__name__)


def build_item_schema(uc: UseCase) -> dict:
    """JSON schema for a room schedule with ontology-constrained identity."""
    canonical = canonical_item_schema()["properties"]
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
                "description": "2-4 sentence overall narrative: decorative order, cleanliness, general state of the room as evidenced by these photos.",
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


from .usecases.tenancy import ITEM_SCHEMA, SYSTEM_PROMPT, VALUE_BANDS  # noqa: E402


COMPACT_LOCAL_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "condition": {"type": "string", "enum": CONDITION_GRADES},
                    "defects": {"type": "array", "items": {"type": "string"}},
                    "photo_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "condition", "defects", "photo_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


class DescribeBackend(Protocol):
    name: str

    def describe_room(self, room_name: str, photos: list[Photo],
                      photo_paths: list[Path],
                      detections: dict[str, list[Detection]]) -> tuple[str, list[Item]]:
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
    from io import BytesIO
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()


_OLLAMA_TIMING_FIELDS = (
    "total_duration", "load_duration", "prompt_eval_count",
    "prompt_eval_duration", "eval_count", "eval_duration",
)


def _ollama_timing(resp: dict) -> dict:
    out: dict[str, float] = {}
    for key in _OLLAMA_TIMING_FIELDS:
        v = resp.get(key)
        if isinstance(v, (int, float)) and v > 0:
            if key.endswith("_duration"):
                out[key] = round(v / 1e9, 3)
            elif key.endswith("_count"):
                out[key] = int(v)
    return out


def _aggregate_timing(batch_timings: list[dict]) -> dict:
    total: dict[str, float] = {}
    for bt in batch_timings:
        for k, v in bt.items():
            total[k] = total.get(k, 0) + v
    if total.get("eval_count") and total.get("eval_duration"):
        total["eval_tok_per_s"] = round(total["eval_count"] / total["eval_duration"], 1)
    if total.get("prompt_eval_count") and total.get("prompt_eval_duration"):
        total["prompt_tok_per_s"] = round(total["prompt_eval_count"] / total["prompt_eval_duration"], 1)
    return total


class FatalBackendError(RuntimeError):
    pass


class DescribeAuthError(FatalBackendError):
    pass


def _extract_json(content: str) -> dict:
    text = content or ""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in response")
    depth = 0
    for end in range(start, len(text)):
        c = text[end]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:end + 1])
    raise ValueError("unterminated JSON object")


def _parse_items(data: dict, photos: list[Photo]) -> tuple[str, list[Item]]:
    valid_ids = {p.id for p in photos}
    all_ids = [p.id for p in photos]
    items = []
    for raw in data.get("items", []):
        ids = [i for i in (raw.get("photo_ids") or []) if i in valid_ids] or all_ids
        # Providers are asked to enforce the JSON schema, but validate identity
        # again here before it becomes persisted inventory state.
        validate_canonical_payload({
            "item_type": raw.get("item_type"),
            "display_name": raw.get("name", "Unidentified item"),
            "subtype": raw.get("subtype"),
            "attributes": raw.get("attributes") or {},
            "instance_key": raw.get("instance_key"),
        })
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


class ClaudeBackend:
    name = "claude"

    def __init__(self, model: str = "claude-opus-4-8",
                 system_prompt: str = SYSTEM_PROMPT,
                 item_schema: dict | None = None):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.system_prompt = system_prompt
        self.item_schema = item_schema if item_schema is not None else ITEM_SCHEMA

    def describe_room(self, room_name, photos, photo_paths, detections):
        self.last_room_timing = None
        content = []
        for photo, path in zip(photos, photo_paths):
            media_type, data = _encode_image(path)
            content.append({"type": "text", "text": f"Photo {photo.id}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}})
        if detections:
            crop_entries = []
            for photo in photos:
                for det in (detections.get(photo.id) or []):
                    if det.crop_path and Path(det.crop_path).is_file() and det.confidence >= 0.30:
                        crop_entries.append((photo.id, det))
            if crop_entries:
                content.append({"type": "text", "text": "High-resolution detail crops of detected items/surfaces in this room (inspect these close-up crops for localized marks, chips, scratches, wear, hairline cracks, limescale, stains, or blemishes):"})
                for photo_id, det in crop_entries[:24]:
                    crop_type, crop_data = _encode_image(Path(det.crop_path), max_dim=800)
                    content.append({"type": "text", "text": f"Detail crop from Photo {photo_id} showing [{det.label}]:"})
                    content.append({"type": "image", "source": {"type": "base64", "media_type": crop_type, "data": crop_data}})
        content.append({"type": "text", "text": f"These photos all show the room: \"{room_name}\".\nProduce the complete item schedule for this room." + _detection_hints(photos, detections)})
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=16000, system=self.system_prompt,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": self.item_schema}},
            )
        except self._anthropic.AuthenticationError as e:
            raise DescribeAuthError("Anthropic rejected the credentials. Set a valid ANTHROPIC_API_KEY, run `ant auth login`, or use --backend offline.") from e
        except TypeError as e:
            if "authentication" in str(e).lower():
                raise DescribeAuthError("No Anthropic credentials found. Set ANTHROPIC_API_KEY, run `ant auth login`, or use --backend offline.") from e
            raise
        if response.stop_reason == "max_tokens":
            raise RuntimeError(f"item schedule for '{room_name}' was truncated at the output token limit — split the room into fewer photos per folder")
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_room_timing = {"input_tokens": int(getattr(usage, "input_tokens", 0) or 0), "output_tokens": int(getattr(usage, "output_tokens", 0) or 0)}
        text = next(b.text for b in response.content if b.type == "text")
        return _parse_items(json.loads(text), photos)


class LocalBackend:
    name = "local"
    DEFAULT_MODEL = "qwen3.5:9b"

    def __init__(self, model: Optional[str] = None, host: Optional[str] = None,
                 batch_size: int = 6, max_dim: int = 1120, num_ctx: int = 24576,
                 num_predict: int = 12288, repeat_penalty: float = 1.1,
                 temperature: float = 0.0, timeout: float = 900.0,
                 system_prompt: str = SYSTEM