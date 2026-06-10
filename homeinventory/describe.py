"""Describe backends: turn a room's photos into a structured item schedule.

Four backends:

* ``claude``  — Claude vision with a JSON-schema-constrained output. Highest
  quality; costs pennies per property. Default model is claude-opus-4-8;
  pass --model claude-haiku-4-5 / claude-sonnet-4-6 to trade quality for cost.
* ``openai``  — any provider speaking the OpenAI chat-completions protocol:
  OpenAI itself (default gpt-4.1-mini), Google Gemini via its
  OpenAI-compatibility endpoint (--model gemini-3.1-flash-lite picks the
  right base URL automatically), or a custom --base-url.
* ``local``   — open-weight VLM via a local Ollama server (default
  qwen3.5:9b). Fully offline, £0 per run. Photos are sent in small batches so
  the KV cache fits consumer GPUs; the merge pass de-duplicates across
  batches. Ollama's structured-output grammar guarantees valid JSON.
* ``offline`` — no network, no model: items come straight from the detector
  (or a bare placeholder). Used for tests/evals and as a graceful fallback.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request
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


class FatalBackendError(RuntimeError):
    """Backend cannot work at all (no credentials, server down, model missing).

    Aborts the whole build immediately instead of failing room by room."""


class DescribeAuthError(FatalBackendError):
    """Credentials missing or rejected."""


def _parse_items(data: dict, photos: list[Photo]) -> tuple[str, list[Item]]:
    """Convert a schema-shaped payload into normalised Items.

    photo_ids are validated against the photos actually sent; hallucinated or
    missing ids fall back to attributing the item to the whole photo set.
    """
    valid_ids = {p.id for p in photos}
    all_ids = [p.id for p in photos]
    items = []
    for raw in data.get("items", []):
        ids = [i for i in (raw.get("photo_ids") or []) if i in valid_ids] or all_ids
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
            photo_ids=ids,
            confidence=raw.get("confidence"),
        ).normalise())
    return data.get("room_summary", ""), items


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
        return _parse_items(json.loads(text), photos)


class LocalBackend:
    """Open-weight VLM via a local Ollama server. Fully offline, £0 per run."""
    name = "local"

    DEFAULT_MODEL = "qwen3.5:9b"

    def __init__(self, model: Optional[str] = None, host: Optional[str] = None,
                 batch_size: int = 6, max_dim: int = 1120, num_ctx: int = 16384,
                 timeout: float = 900.0):
        self.model = model or self.DEFAULT_MODEL
        self.host = (host or os.environ.get("OLLAMA_HOST")
                     or "http://localhost:11434").rstrip("/")
        # consumer-GPU constraints: few images per call keeps the KV cache on
        # the card; smaller encode dim cuts vision tokens with no real loss
        # for inventory work. merge_items() de-duplicates across batches.
        self.batch_size = batch_size
        self.max_dim = max_dim
        self.num_ctx = num_ctx
        self.timeout = timeout

    def _chat(self, messages: list[dict]) -> dict:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": ITEM_SCHEMA,
            "options": {"num_ctx": self.num_ctx, "temperature": 0},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            if "not found" in detail.lower():
                raise FatalBackendError(
                    f"Ollama model not available: {detail!r} — run: "
                    f"ollama pull {self.model}") from e
            raise RuntimeError(f"Ollama error: {detail}") from e
        except urllib.error.URLError as e:
            raise FatalBackendError(
                f"Cannot reach Ollama at {self.host} ({e.reason}) — is it "
                "running? Start it with `ollama serve` or install from "
                "https://ollama.com") from e

    def describe_room(self, room_name, photos, photo_paths, detections):
        batches = [list(range(i, min(i + self.batch_size, len(photos))))
                   for i in range(0, len(photos), self.batch_size)]
        summaries: list[str] = []
        items: list[Item] = []
        for b, idxs in enumerate(batches, start=1):
            batch_photos = [photos[i] for i in idxs]
            images = [_encode_image(photo_paths[i], max_dim=self.max_dim)[1]
                      for i in idxs]
            id_list = ", ".join(p.id for p in batch_photos)
            prompt = (
                f"These photos all show the room: \"{room_name}\".\n"
                f"The {len(batch_photos)} attached photos are, in order: {id_list}.\n"
                f"(Batch {b} of {len(batches)} for this room.) Produce the complete "
                "item schedule for everything visible in THESE photos."
                + _detection_hints(batch_photos, detections)
            )
            log.info("  local batch %d/%d (%d photos)…", b, len(batches),
                     len(batch_photos))
            resp = self._chat([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt, "images": images},
            ])
            data = json.loads(resp["message"]["content"])
            summary, batch_items = _parse_items(data, batch_photos)
            summaries.append(summary)
            items.extend(batch_items)
        # keep the most complete narrative rather than concatenating near-dupes
        best_summary = max(summaries, key=len, default="")
        return best_summary, items


class OpenAICompatBackend:
    """Any provider speaking the OpenAI chat-completions protocol.

    Covers OpenAI itself, Google Gemini (whose OpenAI-compatibility endpoint
    is selected automatically for gemini-* models), and any other compatible
    server via --base-url. One whole-room call, like the claude backend.
    """
    name = "openai"

    DEFAULT_MODEL = "gpt-4.1-mini"
    GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: float = 300.0):
        self.model = model or self.DEFAULT_MODEL
        if base_url is None and self.model.startswith("gemini"):
            base_url = self.GEMINI_BASE
        base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                    or "https://api.openai.com/v1")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or self._resolve_key(self.base_url)
        self.timeout = timeout
        if not self.api_key:
            raise DescribeAuthError(
                "No API key found. Set OPENAI_API_KEY (or GEMINI_API_KEY for "
                "gemini-* models), or use another --backend."
            )

    @staticmethod
    def _resolve_key(base_url: str) -> Optional[str]:
        if "googleapis.com" in base_url:
            return (os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("GOOGLE_API_KEY"))
        return os.environ.get("OPENAI_API_KEY")

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except (ValueError, AttributeError):
                pass
            if e.code in (401, 403):
                raise DescribeAuthError(
                    f"API key rejected by {self.base_url}: {detail}") from e
            if e.code == 404:
                raise FatalBackendError(
                    f"Model or endpoint not found at {self.base_url}: {detail}") from e
            raise RuntimeError(f"API error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise FatalBackendError(
                f"Cannot reach {self.base_url} ({e.reason})") from e

    def describe_room(self, room_name, photos, photo_paths, detections):
        content = []
        for photo, path in zip(photos, photo_paths):
            media_type, data = _encode_image(path)
            content.append({"type": "text", "text": f"Photo {photo.id}:"})
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{data}"}})
        content.append({
            "type": "text",
            "text": (
                f"These photos all show the room: \"{room_name}\".\n"
                "Produce the complete item schedule for this room."
                + _detection_hints(photos, detections)
            ),
        })
        resp = self._post({
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "inventory_room", "strict": True, "schema": ITEM_SCHEMA}},
        })
        choice = resp["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError(
                f"item schedule for '{room_name}' was truncated at the output "
                "token limit — split the room into fewer photos per folder")
        return _parse_items(json.loads(choice["message"]["content"]), photos)


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


def get_backend(name: str, model: Optional[str] = None,
                base_url: Optional[str] = None) -> DescribeBackend:
    if name == "claude":
        return ClaudeBackend(model=model or "claude-opus-4-8")
    if name == "openai":
        return OpenAICompatBackend(model=model, base_url=base_url)
    if name == "local":
        return LocalBackend(model=model)
    if name == "offline":
        return OfflineBackend()
    raise ValueError(f"unknown describe backend: {name!r} "
                     "(expected claude|openai|local|offline)")
