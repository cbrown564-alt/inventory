"""ClaudeBackend contract tests — no network, the client is stubbed."""

import json
from types import SimpleNamespace

from PIL import Image

from homeinventory.describe import ClaudeBackend
from homeinventory.schema import Photo


def _photos(tmp_path, n):
    photos, paths = [], []
    for i in range(n):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (32, 24), "white").save(p)
        photos.append(Photo(id=f"P{i+1:03d}", path=p.name, room="Kitchen"))
        paths.append(p)
    return photos, paths


def _backend(response):
    """Build a ClaudeBackend around a canned response, skipping __init__
    (no anthropic import, no credentials)."""
    from homeinventory.describe import ITEM_SCHEMA, SYSTEM_PROMPT

    b = ClaudeBackend.__new__(ClaudeBackend)
    b.model = "claude-opus-4-8"
    b.system_prompt = SYSTEM_PROMPT
    b.item_schema = ITEM_SCHEMA
    b._anthropic = SimpleNamespace(AuthenticationError=type(
        "AuthenticationError", (Exception,), {}))
    b.client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kwargs: response))
    return b


def _response(usage):
    payload = {"room_summary": "tidy kitchen",
               "items": [{"name": "Oven", "condition": "good",
                          "photo_ids": ["P001"]}]}
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=usage,
    )


def test_describe_room_records_token_usage(tmp_path):
    """response.usage lands in last_room_timing so cli persists the room's
    actual token spend into the checkpoint (docs/06 cost method)."""
    photos, paths = _photos(tmp_path, 1)
    b = _backend(_response(SimpleNamespace(input_tokens=12345, output_tokens=678)))
    summary, items = b.describe_room("Kitchen", photos, paths, {})
    assert summary == "tidy kitchen" and items[0].name == "Oven"
    assert b.last_room_timing == {"input_tokens": 12345, "output_tokens": 678}


def test_describe_room_usage_missing_is_none(tmp_path):
    """No usage block -> timing stays None (older SDKs / stubbed responses)."""
    photos, paths = _photos(tmp_path, 1)
    b = _backend(_response(None))
    b.last_room_timing = {"input_tokens": 1, "output_tokens": 1}  # stale
    b.describe_room("Kitchen", photos, paths, {})
    assert b.last_room_timing is None
