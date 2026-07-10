"""Room segmentation: the pure parts (normalisation, dotenv). The VLM pass
itself is validated against real footage — see the spike record in docs/11."""

import math
import json
import os

from homeinventory.audio_cues import load_audio_cues, segmentation_hint
from homeinventory.dotenv import load_dotenv
from homeinventory.segment import (SampledFrame, Segment, _normalise,
                                   refine_segment_seams)


def test_normalise_forces_contiguity_and_merges_same_room():
    segs = _normalise([
        Segment("Hallway", 0.0, 30.0),
        Segment("Kitchen", 34.0, 90.0),          # 4s gap -> midpoint seam
        Segment("kitchen", 90.0, 120.0),         # same room, case-insensitive
        Segment("Living Room", 118.0, 200.0),    # 2s overlap -> midpoint seam
    ], duration_s=210.0)
    assert [s.room for s in segs] == ["Hallway", "Kitchen", "Living Room"]
    assert segs[0].start_s == 0.0
    assert segs[0].end_s == segs[1].start_s == 32.0
    assert segs[1].end_s == segs[2].start_s == 119.0
    assert segs[-1].end_s == 210.0               # snapped to duration


def test_normalise_drops_empty_and_survives_garbage():
    segs = _normalise([Segment("Kitchen", 50.0, 50.0)], duration_s=60.0)
    assert [s.room for s in segs] == ["Property"]  # honest fallback, full span
    assert segs[0].start_s == 0.0 and segs[0].end_s == 60.0


def test_normalise_repairs_invalid_chunk_seams_and_clamps_to_video():
    segs = _normalise([
        Segment("Kitchen", 85.0, 80.0),          # negative duration: discard
        Segment("Hallway", -20.0, 40.0),         # clip to video start
        Segment("Living Room", 35.0, 140.0),
        Segment("Bathroom", 320.0, 215.0),       # negative duration: discard
        Segment("Loft Room", 130.0, 999.0),      # clip to video end
        Segment("NaN", math.nan, 50.0),           # non-finite: discard
    ], duration_s=200.0)

    assert [s.room for s in segs] == ["Hallway", "Living Room", "Loft Room"]
    assert segs[0].start_s == 0.0
    assert segs[-1].end_s == 200.0
    assert all(0.0 <= s.start_s < s.end_s <= 200.0 for s in segs)
    assert all(a.end_s == b.start_s for a, b in zip(segs, segs[1:]))


def test_normalise_drops_segments_wholly_outside_video():
    segs = _normalise([
        Segment("Before", -20.0, -10.0),
        Segment("After", 80.0, 90.0),
    ], duration_s=60.0)
    assert segs == [Segment("Property", 0.0, 60.0)]


def test_audio_cue_artifact_is_validated_and_prompt_is_plain(tmp_path):
    path = tmp_path / "audio-cues.json"
    path.write_text(json.dumps({
        "source": {"video": "walk.mov", "fps": 30},
        "transcript": [{"start_s": 9, "end_s": 10,
                        "text": "this is the kitchen", "confidence": 0.93}],
        "room_cues": [
            {"t_s": 9, "room": "Kitchen", "confidence": 0.93},
            {"t_s": 12, "room": "Guess", "confidence": 0.2},
        ],
        "establishing_cues": [{"start_s": 10, "end_s": 13,
                               "room": "Kitchen", "confidence": 0.9,
                               "source": "post-name hold"}],
    }), encoding="utf-8")
    cues = load_audio_cues(path)
    prompt = segmentation_hint(cues, 0, 20)
    assert "9.0s: Kitchen" in prompt
    assert "Guess" not in prompt
    assert "trust the images" in prompt.lower()
    assert "ablation" not in prompt.lower()
    assert len(cues["sha256"]) == 64


def test_audio_cue_artifact_rejects_non_finite_values(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"source":{"video":"walk.mov","fps":NaN}}',
                    encoding="utf-8")
    try:
        load_audio_cues(path)
    except ValueError as exc:
        assert "finite" in str(exc)
    else:
        raise AssertionError("non-finite fps accepted")


def test_seam_refine_rechecks_bounded_interval_and_moves_boundary(monkeypatch):
    frames = [SampledFrame(float(t), b"jpg") for t in range(0, 101, 5)]
    segments = [Segment("Hallway", 0, 50), Segment("Kitchen", 50, 100)]

    def fake_segment(local, duration, every_s, model):
        assert duration == 60
        return [Segment("Hallway", 0, 25), Segment("Kitchen", 25, 60)], {}

    monkeypatch.setattr("homeinventory.segment.segment_frames", fake_segment)
    result, meta = refine_segment_seams(frames, segments, 100, 5,
                                        model="model-a")
    assert result[0].end_s == result[1].start_s == 45
    assert meta["api_calls"] == 1 and meta["seams_changed"] == 1


def test_load_dotenv_sets_without_overriding(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "# comment\nANTHROPIC_API_KEY='sk-test'\nHI_EXISTING=file\n\nBAD LINE\n",
        encoding="utf-8")
    monkeypatch.setenv("HI_EXISTING", "env-wins")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    n = load_dotenv(tmp_path)
    assert n == 1
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"   # quotes stripped
    assert os.environ["HI_EXISTING"] == "env-wins"        # never overridden
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_load_dotenv_walks_up_from_subdir(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HI_FROM_PARENT=yes\n", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.delenv("HI_FROM_PARENT", raising=False)
    assert load_dotenv(sub) == 1
    assert os.environ["HI_FROM_PARENT"] == "yes"
    monkeypatch.delenv("HI_FROM_PARENT", raising=False)
