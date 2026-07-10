import json

from PIL import Image

from homeinventory.hero_verify import (verification_prompt,
                                       verify_rank_one_covers)
from homeinventory.schema import Photo


def test_cover_prompt_is_plain_and_contains_no_experiment_metadata():
    prompt = verification_prompt("Kitchen")
    assert "Named room: Kitchen" in prompt
    assert "judge only what is visible" in prompt.lower()
    assert "E8" not in prompt and "benchmark" not in prompt.lower()


def test_cover_verdict_is_cached_by_room_evidence_and_model(tmp_path,
                                                            monkeypatch):
    image = tmp_path / "cover.jpg"
    Image.new("RGB", (20, 20), "white").save(image)
    photo = Photo(id="P001", path=str(image), room="Kitchen", sha256="abc",
                  hero=1, presentation_eligible=True)
    calls = []

    def fake_verify(room, path, model):
        calls.append((room, path, model))
        return {"shows_named_room": True, "is_establishing_view": True,
                "reason": "Wide kitchen view"}

    monkeypatch.setattr("homeinventory.hero_verify.verify_cover", fake_verify)
    rooms = {"Kitchen": [photo]}
    work = tmp_path / "work"
    verify_rank_one_covers(rooms, tmp_path, work, "model-a")
    verify_rank_one_covers(rooms, tmp_path, work, "model-a")
    assert len(calls) == 1
    assert photo.room_match is True
    assert json.loads((work / "cover-verification.json").read_text())
