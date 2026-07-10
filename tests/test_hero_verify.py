import json

from PIL import Image

from homeinventory.hero_verify import (rerank_prompt, rerank_rank_one_covers,
                                       verification_prompt,
                                       verify_rank_one_covers)
from homeinventory.schema import Photo


def test_cover_prompt_is_plain_and_contains_no_experiment_metadata():
    prompt = verification_prompt("Kitchen")
    assert "Named room: Kitchen" in prompt
    assert "judge only what is visible" in prompt.lower()
    assert "E8" not in prompt and "benchmark" not in prompt.lower()
    rendered = rerank_prompt("Kitchen", 3)
    assert "Pick the clearest useful wide overview" in rendered
    assert "E8" not in rendered and "top-10" not in rendered


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


def test_cover_rerank_promotes_picked_eligible_candidate(tmp_path, monkeypatch):
    paths = []
    photos = []
    for i in range(3):
        path = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (20, 20), "white").save(path)
        paths.append(path)
        photos.append(Photo(id=f"P{i}", path=str(path), room="Kitchen",
                            sha256=str(i), hero=i + 1, quality=1 - i * .1,
                            presentation_eligible=True))
    monkeypatch.setattr("homeinventory.hero_verify.rerank_cover",
                        lambda *args: {"pick": 2, "confident": True,
                                      "reason": "Wide room view"})
    rerank_rank_one_covers({"Kitchen": photos}, tmp_path, tmp_path / "work",
                           "model-a")
    assert photos[1].hero == 1 and photos[1].room_match is True
    assert photos[0].hero == 2
