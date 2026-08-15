from unittest.mock import MagicMock, patch
from homeinventory.detect import (
    Detection,
    verify_detection_proposals,
    vlm_verify_detection_proposals,
)


def test_detection_verify_keeps_repeat_support_or_strong_singletons():
    proposals = {
        "P1": [Detection("chair", 0.3, (0, 0, 50, 50)),
               Detection("ghost", 0.2, (0, 0, 50, 50))],
        "P2": [Detection("chair", 0.32, (0, 0, 50, 50)),
               Detection("oven", 0.7, (0, 0, 50, 50))],
    }
    verified = verify_detection_proposals(proposals)
    assert [d.label for d in verified["P1"]] == ["chair"]
    assert [d.label for d in verified["P2"]] == ["chair", "oven"]


def test_vlm_verify_detection_proposals_fallback_when_no_api(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    proposals = {
        "P1": [Detection("chair", 0.3, (0, 0, 50, 50)),
               Detection("ghost", 0.2, (0, 0, 50, 50))],
        "P2": [Detection("chair", 0.32, (0, 0, 50, 50)),
               Detection("oven", 0.7, (0, 0, 50, 50))],
    }
    verified = vlm_verify_detection_proposals(proposals, model="google/gemini-3.7-flash")
    assert [d.label for d in verified["P1"]] == ["chair"]
    assert [d.label for d in verified["P2"]] == ["chair", "oven"]


def test_vlm_verify_detection_proposals_runs_vlm_on_crops(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    crop_file = tmp_path / "crop.jpg"
    crop_file.write_bytes(b"fake-image-bytes")

    proposals = {
        "P1": [
            Detection("oven", 0.8, (0, 0, 50, 50)),
            Detection("unknown_fixture", 0.35, (0, 0, 50, 50), crop_path=str(crop_file)),
            Detection("ghost_item", 0.25, (0, 0, 50, 50), crop_path=str(crop_file)),
        ]
    }

    mock_resp = {
        "choices": [{"message": {"content": '{"valid_indices": [1]}'}}]
    }

    with patch("homeinventory.describe.OpenAICompatBackend._post", return_value=mock_resp):
        verified = vlm_verify_detection_proposals(proposals, model="google/gemini-3.7-flash")
        labels = [d.label for d in verified["P1"]]
        assert "oven" in labels
        assert "unknown_fixture" in labels
        assert "ghost_item" not in labels
