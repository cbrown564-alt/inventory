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

    def fake_chat(messages):
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
