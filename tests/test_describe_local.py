"""LocalBackend batch resilience and JSON extraction (no live Ollama needed)."""

from pathlib import Path

import pytest

from homeinventory.describe import LocalBackend, _extract_json
from homeinventory.schema import Photo


def _photos(n):
    return [Photo(id=f"P00{i}", path=f"r/{i}.jpg", room="r") for i in range(n)]


def _paths(tmp_path, n):
    from PIL import Image
    paths = []
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (16, 16), "white").save(p)
        paths.append(p)
    return paths


_GOOD_ITEM = {
    "name": "Walls", "category": "other", "description": "d",
    "condition": "good", "cleanliness": "clean", "defects": [],
    "quantity": 1, "est_value_band": "<£50", "photo_ids": [], "confidence": 0.5,
}
import json as _json


def test_extract_json_strips_markdown_fence_and_prose():
    blob = 'Here is the schedule:\n```json\n{"room_summary": "ok", "items": []}\n```\nthanks'
    assert _extract_json(blob) == {"room_summary": "ok", "items": []}


def test_extract_json_takes_outermost_balanced_object():
    # prose before/after + a nested object must still yield the whole schedule
    blob = 'sure:\n{"room_summary":"ok","items":[{"name":"Walls"}]}\ndone'
    assert _extract_json(blob) == {"room_summary": "ok",
                                   "items": [{"name": "Walls"}]}


def test_extract_json_raises_when_no_object():
    with pytest.raises(ValueError):
        _extract_json("the model refused: cannot help with that")


def test_local_backend_skips_failed_batch_and_keeps_others(tmp_path, monkeypatch):
    # 12 photos -> 2 batches of 6. Batch 1 returns good JSON, batch 2 always
    # malforms even on retry. The room must still return batch 1's items
    # instead of the whole room dying with zero items (the prior behaviour).
    backend = LocalBackend(batch_size=6)
    photos = _photos(12)
    paths = _paths(tmp_path, 12)
    calls = {"n": 0}
    good = {"message": {"content": _json.dumps(
        {"room_summary": "s", "items": [_GOOD_ITEM]})}}

    def fake_chat(self, messages, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return good
        return {"message": {"content": "not json at all"}}  # -> ValueError

    monkeypatch.setattr(LocalBackend, "_chat", fake_chat)
    summary, items = backend.describe_room("r", photos, paths, {})
    assert [i.name for i in items] == ["Walls"]
    assert calls["n"] == 3  # batch1 ok(1) + batch2 fail(2) + retry fail(3) -> skip


def test_local_backend_skips_transient_server_error(tmp_path, monkeypatch):
    # A transient Ollama RuntimeError on one batch must not take the room down.
    backend = LocalBackend(batch_size=6)
    photos = _photos(12)
    paths = _paths(tmp_path, 12)
    calls = {"n": 0}
    good = {"message": {"content": _json.dumps(
        {"room_summary": "s", "items": [_GOOD_ITEM]})}}

    def fake_chat(self, messages, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return good
        raise RuntimeError("Ollama error: 500")

    monkeypatch.setattr(LocalBackend, "_chat", fake_chat)
    summary, items = backend.describe_room("r", photos, paths, {})
    assert [i.name for i in items] == ["Walls"]


def test_local_backend_skips_socket_timeout(tmp_path, monkeypatch):
    # A thinking model can hang on one batch until the 900s socket timeout
    # fires; TimeoutError is an OSError (not a RuntimeError) so it must be
    # caught here too, else the whole room dies as happened on Reception.
    import socket
    backend = LocalBackend(batch_size=6)
    photos = _photos(12)
    paths = _paths(tmp_path, 12)
    calls = {"n": 0}
    good = {"message": {"content": _json.dumps(
        {"room_summary": "s", "items": [_GOOD_ITEM]})}}

    def fake_chat(self, messages, temperature=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return good
        raise socket.timeout("read timed out")

    monkeypatch.setattr(LocalBackend, "_chat", fake_chat)
    summary, items = backend.describe_room("r", photos, paths, {})
    assert [i.name for i in items] == ["Walls"]
