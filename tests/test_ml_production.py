"""CI-safe tests for ML-E2 / ML-E8 / ML-E10 production wiring."""

from __future__ import annotations

from homeinventory.detect import Detection, make_build_detector
from homeinventory.gdino import verify_detections
from homeinventory.ml_api import vlm_api_available
from homeinventory.ml_cover import should_enable_vlm_cover
from homeinventory.ml_seam import seam_refine_available, try_refine_segments
from homeinventory.segment import Segment


def test_vlm_cover_defaults_off_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert vlm_api_available("gemini-3.5-flash") is False
    assert should_enable_vlm_cover(no_vlm_cover=False, model="gemini-3.5-flash") is False
    assert should_enable_vlm_cover(no_vlm_cover=True, model="claude-opus-4-8") is False


def test_vlm_cover_enables_when_key_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert should_enable_vlm_cover(no_vlm_cover=False, model="gemini-3.5-flash") is True


def test_gdino_verify_keeps_household_vocab_only():
    dets = [
        Detection("sofa", 0.9, (0, 0, 10, 10)),
        Detection("alien spaceship", 0.95, (0, 0, 10, 10)),
        Detection("refrigerator", 0.8, (0, 0, 10, 10)),
    ]
    kept = verify_detections(dets)
    assert [d.label for d in kept] == ["sofa", "refrigerator"]


def test_make_build_detector_yoloe_path():
    det = make_build_detector(backend="yoloe", detect_mode="text", conf=0.25)
    assert det is not None
    assert getattr(det, "mode", None) == "text"


def test_seam_refine_skips_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert seam_refine_available("gemini-3.5-flash") is False
    video = tmp_path / "walk.mp4"
    video.write_bytes(b"not-a-real-video")
    segs = [Segment("Hall", 0.0, 10.0), Segment("Kitchen", 10.0, 20.0)]
    out, meta = try_refine_segments(video, segs, model="gemini-3.5-flash")
    assert out == segs
    assert meta["enabled"] is False
