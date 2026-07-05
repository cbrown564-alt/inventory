"""Segmented walkthrough ingest: boundary bleed at room seams."""

import json
from pathlib import Path

import pytest

from homeinventory.ingest import (
    SEGMENT_BOUNDARY_TRIM_S,
    extract_keyframes,
    ingest,
)


def _two_tone_video(path: Path, *, fps: int = 10, seconds: int = 6) -> None:
    """First half red (BGR), second half blue — simulates Hallway → Kitchen."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps,
                         (64, 48))
    assert vw.isOpened()
    mid = seconds * fps // 2
    for i in range(seconds * fps):
        color = (0, 0, 255) if i < mid else (255, 0, 0)
        vw.write(np.full((48, 64, 3), color, dtype=np.uint8))
    vw.release()


def _frame_index(path: Path) -> int:
    return int(path.stem.rsplit("_f", 1)[1])


def test_segment_ingest_trims_lead_at_boundaries(tmp_path):
    """Kitchen keyframes must not include Hallway frames at the segment seam."""
    cv2 = pytest.importorskip("cv2")

    cap = tmp_path / "capture"
    cap.mkdir()
    video = cap / "walk.avi"
    fps = 10
    _two_tone_video(video, fps=fps, seconds=6)

    work = tmp_path / "work"
    seg_dir = work / "segments"
    seg_dir.mkdir(parents=True)
    boundary_s = 3.0
    (seg_dir / "walk.json").write_text(json.dumps({
        "video": "walk.avi",
        "duration_s": 6.0,
        "segments": [
            {"room": "Hallway", "start_s": 0.0, "end_s": boundary_s},
            {"room": "Kitchen", "start_s": boundary_s, "end_s": 6.0},
        ],
    }), encoding="utf-8")

    rooms = ingest(cap, work)
    assert set(rooms) == {"Hallway", "Kitchen"}
    assert rooms["Kitchen"], "expected keyframes in Kitchen segment"

    bleed_cutoff = int((boundary_s + SEGMENT_BOUNDARY_TRIM_S) * fps)
    for photo in rooms["Kitchen"]:
        frame_path = Path(photo.path)
        idx = _frame_index(frame_path)
        assert idx >= bleed_cutoff, (
            f"{frame_path.name} at frame {idx} is inside the lead-trim "
            f"window ({boundary_s}s + {SEGMENT_BOUNDARY_TRIM_S}s)"
        )
        img = cv2.imread(str(frame_path))
        assert img is not None
        # Kitchen segment frames should be predominantly blue (BGR channel 0).
        assert float(img[:, :, 0].mean()) > float(img[:, :, 2].mean())


def test_segment_lead_trim_respects_explicit_override(tmp_path):
    """--trim-lead overrides the default segment boundary trim."""
    cap = tmp_path / "capture"
    cap.mkdir()
    video = cap / "walk.avi"
    fps = 10
    _two_tone_video(video, fps=fps, seconds=6)

    work = tmp_path / "work"
    seg_dir = work / "segments"
    seg_dir.mkdir(parents=True)
    boundary_s = 3.0
    custom_trim = 1.0
    (seg_dir / "walk.json").write_text(json.dumps({
        "duration_s": 6.0,
        "segments": [
            {"room": "Hallway", "start_s": 0.0, "end_s": boundary_s},
            {"room": "Kitchen", "start_s": boundary_s, "end_s": 6.0},
        ],
    }), encoding="utf-8")

    rooms = ingest(cap, work, lead_trim_s=custom_trim)
    min_kitchen = min(_frame_index(Path(p.path)) for p in rooms["Kitchen"])
    assert min_kitchen >= int((boundary_s + custom_trim) * fps)


def test_extract_keyframes_lead_trim_within_segment_window(tmp_path):
    """lead_trim_s applies relative to clip_start, not t=0."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    fps, size = 10, (64, 48)
    video = tmp_path / "clip.avi"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    rng = np.random.default_rng(2)
    for _ in range(8 * fps):
        vw.write(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    vw.release()

    start_s, trim_s = 3.0, 2.0
    frames = extract_keyframes(video, tmp_path / "seg", max_frames=8,
                               start_s=start_s, end_s=7.0,
                               lead_trim_s=trim_s)
    assert frames
    for f in frames:
        idx = _frame_index(f)
        assert idx >= (start_s + trim_s) * fps
