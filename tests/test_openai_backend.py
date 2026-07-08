import json

import pytest
from PIL import Image

from homeinventory.describe import DescribeAuthError, OpenAICompatBackend
from homeinventory.schema import Photo


def _photos(tmp_path, n):
    photos, paths = [], []
    for i in range(n):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (32, 24), "white").save(p)
        photos.append(Photo(id=f"P{i+1:03d}", path=p.name, room="Kitchen"))
        paths.append(p)
    return photos, paths


def test_no_key_is_fatal(monkeypatch):
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(DescribeAuthError):
        OpenAICompatBackend()


def test_gemini_model_routes_to_google(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    b = OpenAICompatBackend(model="gemini-3.1-flash-lite")
    assert "googleapis.com" in b.base_url
    assert b.api_key == "g-key"


def test_explicit_base_url_wins(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    b = OpenAICompatBackend(model="anything", base_url="http://localhost:11434/v1/")
    assert b.base_url == "http://localhost:11434/v1"


def test_describe_room_payload_and_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    photos, paths = _photos(tmp_path, 2)
    b = OpenAICompatBackend(model="gpt-4.1-mini")
    sent = {}

    def fake_post(payload):
        sent.update(payload)
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "room_summary": "tidy kitchen",
            "items": [{"name": "Oven", "condition": "good", "photo_ids": ["P002"]}],
        })}}]}

    monkeypatch.setattr(b, "_post", fake_post)
    summary, items = b.describe_room("Kitchen", photos, paths, {})

    assert summary == "tidy kitchen"
    assert items[0].name == "Oven" and items[0].photo_ids == ["P002"]
    assert sent["model"] == "gpt-4.1-mini"
    assert sent["response_format"]["json_schema"]["strict"] is True
    user_content = sent["messages"][1]["content"]
    images = [c for c in user_content if c["type"] == "image_url"]
    assert len(images) == 2
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_truncation_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    photos, paths = _photos(tmp_path, 1)
    b = OpenAICompatBackend(model="gpt-4.1-mini")
    monkeypatch.setattr(b, "_post", lambda payload: {
        "choices": [{"finish_reason": "length", "message": {"content": "{"}}]})
    with pytest.raises(RuntimeError, match="truncated"):
        b.describe_room("Kitchen", photos, paths, {})
