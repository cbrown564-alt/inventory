import json
from pathlib import Path

from PIL import Image

from homeinventory.describe import LocalBackend, _parse_items
from homeinventory.schema import Photo


def _photos(tmp_path, n):
    photos, paths = [], []
    for i in range(n):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (32, 24), "white").save(p)
        photos.append(Photo(id=f"P{i+1:03d}", path=p.name, room="Living Room"))
        paths.append(p)
    return photos, paths


def test_parse_items_validates_photo_ids(tmp_path):
    photos, _ = _photos(tmp_path, 2)
    summary, items = _parse_items({
        "room_summary": "ok",
        "items": [
            {"name": "Sofa", "photo_ids": ["P001", "P999"]},   # P999 hallucinated
            {"name": "Lamp", "photo_ids": []},                  # missing -> all
        ],
    }, photos)
    assert summary == "ok"
    assert items[0].photo_ids == ["P001"]
    assert items[1].photo_ids == ["P001", "P002"]


def test_local_backend_batches_and_collects(tmp_path, monkeypatch):
    photos, paths = _photos(tmp_path, 7)
    backend = LocalBackend(batch_size=3)
    calls = []

    def fake_chat(messages, temperature=0.0):
        calls.append(messages)
        n = len(messages[-1]["images"])
        return {"message": {"content": json.dumps({
            "room_summary": f"summary with {n} photos" + " x" * n,
            "items": [{"name": f"Item batch {len(calls)}"}],
        })}}

    monkeypatch.setattr(backend, "_chat", fake_chat)
    summary, items = backend.describe_room("Living Room", photos, paths, {})

    assert len(calls) == 3                      # 3 + 3 + 1 photos
    assert [len(c[-1]["images"]) for c in calls] == [3, 3, 1]
    assert "P001, P002, P003" in calls[0][-1]["content"]
    assert len(items) == 3                      # one per batch, merged later by cli
    assert summary.startswith("summary with 3 photos")  # longest kept


def test_local_backend_timeout_from_env(monkeypatch):
    # HI_TIMEOUT makes the hardcoded 900s per-batch socket deadline tunable.
    # General plumbing: override applied, bad value falls back to default,
    # unset stays at default.
    monkeypatch.setenv("HI_TIMEOUT", "3600")
    assert LocalBackend().timeout == 3600.0

    monkeypatch.setenv("HI_TIMEOUT", "not-a-number")
    assert LocalBackend().timeout == 900.0

    monkeypatch.delenv("HI_TIMEOUT", raising=False)
    assert LocalBackend().timeout == 900.0


def test_local_backend_batch_size_from_env(monkeypatch):
    # HI_BATCH_SIZE tunes photos-per-call (ctx/throughput trade-off). Override
    # applied, bad value falls back to default, unset stays at default (6).
    monkeypatch.setenv("HI_BATCH_SIZE", "3")
    assert LocalBackend().batch_size == 3

    monkeypatch.setenv("HI_BATCH_SIZE", "nope")
    assert LocalBackend().batch_size == 6

    monkeypatch.delenv("HI_BATCH_SIZE", raising=False)
    assert LocalBackend().batch_size == 6


def test_local_backend_captures_room_timing(tmp_path, monkeypatch):
    # Ollama returns ns durations + token counts; describe_room must convert,
    # accumulate across batches, and expose a room total on last_room_timing
    # (this is the throughput we previously couldn't recover from a committed
    # run — GPU vs CPU offload shows up as the eval_tok_per_s rate).
    photos, paths = _photos(tmp_path, 7)
    backend = LocalBackend(batch_size=3)

    def fake_chat(messages, temperature=0.0):
        return {
            "message": {"content": json.dumps(
                {"room_summary": "s", "items": [{"name": "x"}]})},
            # realistic-shaped Ollama fields (nanoseconds)
            "total_duration": 6_000_000_000,
            "load_duration": 500_000_000,
            "prompt_eval_count": 700,
            "prompt_eval_duration": 500_000_000,
            "eval_count": 300,
            "eval_duration": 5_000_000_000,
        }

    monkeypatch.setattr(backend, "_chat", fake_chat)
    backend.describe_room("Living Room", photos, paths, {})

    t = backend.last_room_timing
    assert t["eval_count"] == 900              # 300 across 3 batches
    assert t["eval_duration"] == 15.0          # 5s * 3, ns -> s
    assert t["prompt_eval_count"] == 2100
    assert t["eval_tok_per_s"] == 60.0         # 900 / 15.0
    assert t["prompt_tok_per_s"] == 1400.0     # 2100 / 1.5
