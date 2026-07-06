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
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol

from .detect import Detection
from .schema import (CATEGORIES, CLEANLINESS_GRADES, CONDITION_GRADES, Item,
                     Photo)
from .usecases.base import UseCase

log = logging.getLogger(__name__)


def build_item_schema(uc: UseCase) -> dict:
    """JSON schema for a room's item schedule, parametrised by use case."""
    item_props = {
        "name": {"type": "string",
                 "description": "Short item name, e.g. 'Three-seat sofa'"},
        "category": {"type": "string", "enum": CATEGORIES},
        "description": {
            "type": "string",
            "description": "Material, colour, brand/model if visible, "
                           "approximate size.",
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
    }
    required = ["name", "category", "description", "condition",
                "cleanliness", "defects", "quantity", "photo_ids", "confidence"]
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
                "description": "2-4 sentence overall narrative: decorative order, "
                               "cleanliness, general state of the room as evidenced "
                               "by these photos.",
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


# Back-compat aliases from the tenancy profile (defined after build_item_schema
# so tenancy.py can import this function without a circular import).
from .usecases.tenancy import ITEM_SCHEMA, SYSTEM_PROMPT, VALUE_BANDS  # noqa: E402


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


# --- Ollama timing capture ------------------------------------------------
# Ollama returns nanosecond durations and token counts per response. We pull
# them out of the raw dict so describe_room can accumulate per-batch and cli
# can persist a room total into the checkpoint. A drastic eval_count /
# eval_duration drop is the tell-tale of CPU layer offload (the throughput
# question we previously couldn't answer from committed artefacts).
_OLLAMA_TIMING_FIELDS = (
    "total_duration", "load_duration", "prompt_eval_count",
    "prompt_eval_duration", "eval_count", "eval_duration",
)


def _ollama_timing(resp: dict) -> dict:
    """Extract the timing/throughput fields from an Ollama /api/chat response.

    Durations come back in nanoseconds; converted to seconds here. Missing or
    zero fields are omitted (older Ollama builds omit some; a zero eval_count
    means nothing was generated and would otherwise divide-by-zero downstream).
    """
    out: dict[str, float] = {}
    for key in _OLLAMA_TIMING_FIELDS:
        v = resp.get(key)
        if isinstance(v, (int, float)) and v > 0:
            if key.endswith("_duration"):
                out[key] = round(v / 1e9, 3)          # ns -> seconds
            elif key.endswith("_count"):
                out[key] = int(v)
    return out


def _aggregate_timing(batch_timings: list[dict]) -> dict:
    """Sum per-batch timing into a room total with a derived tok/s.

    eval tok/s uses eval_duration (generation only); prompt tok/s uses
    prompt_eval_duration (prefill). Either rate is None when the model emitted
    no tokens of that kind or the duration was missing.
    """
    total: dict[str, float] = {}
    for bt in batch_timings:
        for k, v in bt.items():
            total[k] = total.get(k, 0) + v
    # throughput, derived
    if total.get("eval_count") and total.get("eval_duration"):
        total["eval_tok_per_s"] = round(
            total["eval_count"] / total["eval_duration"], 1)
    if total.get("prompt_eval_count") and total.get("prompt_eval_duration"):
        total["prompt_tok_per_s"] = round(
            total["prompt_eval_count"] / total["prompt_eval_duration"], 1)
    return total


class FatalBackendError(RuntimeError):
    """Backend cannot work at all (no credentials, server down, model missing).

    Aborts the whole build immediately instead of failing room by room."""


class DescribeAuthError(FatalBackendError):
    """Credentials missing or rejected."""


def _extract_json(content: str) -> dict:
    """Parse a model's text response into a JSON object.

    Tolerates the common open-weight VLM quirks of wrapping JSON in markdown
    code fences or surrounding it with prose: strip a fenced block if present,
    then take the outermost balanced ``{ ... }``. Raises ``ValueError`` when no
    complete object can be recovered, so callers retry or skip the batch
    (truncated output is handled there, not by guessing at a repair).
    """
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

    def __init__(self, model: str = "claude-opus-4-8",
                 system_prompt: str = SYSTEM_PROMPT,
                 item_schema: dict | None = None):
        import anthropic
        self._anthropic = anthropic
        # Credential resolution is delegated to the SDK: ANTHROPIC_API_KEY,
        # ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile all work.
        self.client = anthropic.Anthropic()
        self.model = model
        self.system_prompt = system_prompt
        self.item_schema = item_schema if item_schema is not None else ITEM_SCHEMA

    def describe_room(self, room_name, photos, photo_paths, detections):
        # Reset per room so a failed call can't inherit the previous room's
        # numbers when cli persists it into the checkpoint's "timing" field.
        self.last_room_timing = None
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
                system=self.system_prompt,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema",
                                         "schema": self.item_schema}},
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
        # Mirror LocalBackend's last_room_timing: cli persists this into the
        # room checkpoint so a run records its own actual token spend instead
        # of being reconstructed after the fact (docs/06 cost method).
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_room_timing = {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            }
        text = next(b.text for b in response.content if b.type == "text")
        return _parse_items(json.loads(text), photos)


class LocalBackend:
    """Open-weight VLM via a local Ollama server. Fully offline, £0 per run."""
    name = "local"

    DEFAULT_MODEL = "qwen3.5:9b"

    def __init__(self, model: Optional[str] = None, host: Optional[str] = None,
                 batch_size: int = 6, max_dim: int = 1120, num_ctx: int = 24576,
                 num_predict: int = 12288, repeat_penalty: float = 1.1,
                 temperature: float = 0.0, timeout: float = 900.0,
                 system_prompt: str = SYSTEM_PROMPT,
                 item_schema: dict | None = None):
        self.model = model or self.DEFAULT_MODEL
        self.system_prompt = system_prompt
        self.item_schema = item_schema if item_schema is not None else ITEM_SCHEMA
        self.host = (host or os.environ.get("OLLAMA_HOST")
                     or "http://localhost:11434").rstrip("/")
        # consumer-GPU constraints: few images per call keeps the KV cache on
        # the card; smaller encode dim cuts vision tokens with no real loss
        # for inventory work. merge_items() de-duplicates across batches.
        # HI_BATCH_SIZE override: photos per Ollama call. Smaller batches mean
        # shorter expected output and less KV-cache pressure but more calls and
        # more merge work. NOTE: an attempt to fix gemma4:26b's malformed-JSON
        # batch skips by halving batch_size (6 -> 3) did NOT work — the failing
        # Bathroom batch failed identically at bs3, and probing showed the real
        # cause is a temperature-0 repetition loop (`done_reason: length`,
        # repeated-token tail), not batch composition. The fix for that lives
        # in sampling (HI_REPEAT_PENALTY / HI_TEMPERATURE), not here; this knob
        # is retained for the general ctx/throughput trade-off it exposes.
        if os.environ.get("HI_BATCH_SIZE"):
            try:
                batch_size = int(os.environ["HI_BATCH_SIZE"])
            except ValueError:
                pass
        self.batch_size = batch_size
        self.max_dim = max_dim
        # HI_NUM_CTX override (no CLI flag): the 24K default spills ~30% of
        # qwen9b's weights to CPU on an 8 GB card (4.9/7.0 GB in VRAM ->
        # ~15 tok/s, batches timing out at 900s). Dropping ctx shrinks the KV
        # cache so the whole model fits on-GPU; this knob lets a benchmark
        # sweep the ctx-vs-throughput trade-off without code changes.
        if os.environ.get("HI_NUM_CTX"):
            try:
                num_ctx = int(os.environ["HI_NUM_CTX"])
            except ValueError:
                pass
        self.num_ctx = num_ctx
        # HI_NUM_PREDICT override: 12288 fits qwen3.5's compact output but
        # smaller models can need more (or less) room. The knob avoids code
        # edits per model.
        if os.environ.get("HI_NUM_PREDICT"):
            try:
                num_predict = int(os.environ["HI_NUM_PREDICT"])
            except ValueError:
                pass
        self.num_predict = num_predict
        # HI_REPEAT_PENALTY override: greedy decoding (temperature 0) makes
        # small models fall into repetition loops — qwen2.5vl:3b emitted the
        # same "ceiling" item 34 times until num_predict truncated it. A
        # mild 1.1 penalty (Ollama's own default is 1.0) breaks the loop and
        # yields 12 distinct items at done_reason=stop, with no truncation.
        # Kept on at temp 0.3 (the retry path) too; harmless there.
        if os.environ.get("HI_REPEAT_PENALTY"):
            try:
                repeat_penalty = float(os.environ["HI_REPEAT_PENALTY"])
            except ValueError:
                pass
        self.repeat_penalty = repeat_penalty
        # HI_TEMPERATURE override: the temp-0 greedy default is fine for
        # qwen3.5 but unstable for smaller models — qwen2.5vl:3b falls into
        # repetition loops or emits empty output at temp 0. A mild 0.3 is
        # the smallest value that reliably stabilises it (validated: 6-12
        # distinct items, done_reason=stop, ~11s/batch). Kept at 0 by default
        # so stronger models stay reproducible.
        if os.environ.get("HI_TEMPERATURE"):
            try:
                temperature = float(os.environ["HI_TEMPERATURE"])
            except ValueError:
                pass
        self.temperature = temperature
        # HI_TIMEOUT override: makes the previously-hardcoded 900s per-batch
        # socket deadline tunable without a code change or CLI flag. The
        # default covers qwen3.5:9b on an 8 GB card; a heavyweight thinking
        # model under spillover, or a deliberately large batch, can need
        # longer, so set it per-run for those (e.g. HI_TIMEOUT=3600). Note
        # this is general plumbing: on the gemma4:26b InventoryFlex run no
        # batch actually timed out (the skipped batches failed with malformed
        # JSON, not socket deadlines), so raising it alone will not recover
        # that run's defect recall — see docs/03 for the real lever.
        if os.environ.get("HI_TIMEOUT"):
            try:
                timeout = float(os.environ["HI_TIMEOUT"])
            except ValueError:
                pass
        self.timeout = timeout

    def _chat(self, messages: list[dict], temperature: float = 0.0) -> dict:
        # Budget note for thinking models (qwen3.5+): they emit a `thinking`
        # field (observed 13K-26K chars) before the JSON `content`, and
        # everything generated competes for num_ctx with the ~7K-token prompt
        # of a 6-photo batch. Without explicit num_predict, content is often
        # empty or cut mid-string. `think: false` is NOT the fix on Ollama
        # 0.30: it silently drops the `format` schema and the model returns
        # free-form markdown.
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": self.item_schema,
            "options": {"num_ctx": self.num_ctx, "temperature": temperature,
                        "num_predict": self.num_predict,
                        "repeat_penalty": self.repeat_penalty},
        }
        body = json.dumps(payload).encode()
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
        batch_timings: list[dict] = []
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
            msgs = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt, "images": images},
            ]
            resp = None
            try:
                resp = self._chat(msgs, temperature=self.temperature)
                data = _extract_json(resp["message"]["content"])
            except (ValueError, RuntimeError, OSError) as e:
                # malformed/empty JSON, a transient Ollama error, or a socket
                # timeout (a thinking model can hang on one batch): one retry
                # at a different temperature, jittered off whatever path
                # produced the failure. Even with a non-zero primary temp a
                # single malformed batch is possible; the retry breaks it.
                log.warning("  batch %d failed (%s) — retrying", b, e)
                try:
                    resp = self._chat(msgs, temperature=0.3)
                    data = _extract_json(resp["message"]["content"])
                except (ValueError, RuntimeError, OSError) as e:
                    # A single unrecoverable batch must not kill the whole
                    # room: a prior run lost 2 of 6 rooms entirely because one
                    # bad batch propagated up and zeroed 27 photos' worth of
                    # items. Skip the batch, keep what the others produced.
                    log.error("  batch %d failed after retry (%s) — skipping, "
                              "keeping %d items so far", b, e, len(items))
                    continue
            if resp is not None:
                batch_timings.append(_ollama_timing(resp))
            summary, batch_items = _parse_items(data, batch_photos)
            summaries.append(summary)
            items.extend(batch_items)
        # keep the most complete narrative rather than concatenating near-dupes
        best_summary = max(summaries, key=len, default="")
        # room-level timing for the checkpoint + a one-line throughput log.
        # eval_tok_per_s is the headline: a steep drop vs a prior run means
        # Ollama offloaded layers to CPU (VRAM pressure), which is the GPU-vs-
        # CPU question we couldn't previously answer from committed artefacts.
        self.last_room_timing = _aggregate_timing(batch_timings)
        if batch_timings:
            t = self.last_room_timing
            tok_s = t.get("eval_tok_per_s")
            secs = t.get("eval_duration")
            n = t.get("eval_count")
            if tok_s is not None:
                log.info("  room timing: %d tok in %.1fs (%.1f tok/s gen)",
                         n, secs, tok_s)
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
                 api_key: Optional[str] = None, timeout: float = 300.0,
                 system_prompt: str = SYSTEM_PROMPT,
                 item_schema: dict | None = None):
        self.model = model or self.DEFAULT_MODEL
        self.system_prompt = system_prompt
        self.item_schema = item_schema if item_schema is not None else ITEM_SCHEMA
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
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "inventory_room", "strict": True,
                "schema": self.item_schema}},
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
                base_url: Optional[str] = None,
                use_case: Optional[str] = None) -> DescribeBackend:
    from .usecases import DEFAULT_USE_CASE, get_use_case

    uc = get_use_case(use_case or DEFAULT_USE_CASE)
    schema = build_item_schema(uc)
    prompt = uc.system_prompt
    if name == "claude":
        return ClaudeBackend(model=model or "claude-opus-4-8",
                             system_prompt=prompt, item_schema=schema)
    if name == "openai":
        return OpenAICompatBackend(model=model, base_url=base_url,
                                   system_prompt=prompt, item_schema=schema)
    if name == "local":
        return LocalBackend(model=model, system_prompt=prompt, item_schema=schema)
    if name == "offline":
        return OfflineBackend()
    raise ValueError(f"unknown describe backend: {name!r} "
                     "(expected claude|openai|local|offline)")
