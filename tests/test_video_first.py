"""Video-first pipeline: segmentation → rooms integration."""

import json
from pathlib import Path

import pytest
from PIL import Image

from homeinventory.cli import main
from homeinventory.ingest import extract_keyframes, ingest


def _img(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), "white").save(path)


def test_ingest_root_video_uses_segments_json(tmp_path):
    """Root walkthrough video + cached segments.json → named rooms."""
    cap = tmp_path / "capture"
    cap.mkdir()
    video = cap / "walk.avi"
    # minimal avi — keyframe extraction tested separately
    pytest.importorskip("cv2")
    import cv2
    import numpy as np
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10,
                         (48, 32))
    for i in range(50):
        vw.write(np.full((32, 48, 3), (i * 4) % 255, dtype=np.uint8))
    vw.release()

    work = tmp_path / "work"
    seg_dir = work / "segments"
    seg_dir.mkdir(parents=True)
    (seg_dir / "walk.json").write_text(json.dumps({
        "video": "walk.avi",
        "duration_s": 5.0,
        "segments": [
            {"room": "Kitchen", "start_s": 0.0, "end_s": 2.5},
            {"room": "Living Room", "start_s": 2.5, "end_s": 5.0},
        ],
    }), encoding="utf-8")

    rooms = ingest(cap, work, no_segment=False)
    assert set(rooms) == {"Kitchen", "Living Room"}
    assert sum(len(v) for v in rooms.values()) >= 2


def test_ingest_preserves_folder_rooms_with_segments(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Bathroom" / "a.jpg")
    pytest.importorskip("cv2")
    import cv2
    import numpy as np
    video = cap / "walk.avi"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10,
                         (48, 32))
    for _ in range(30):
        vw.write(np.full((32, 48, 3), 128, dtype=np.uint8))
    vw.release()
    work = tmp_path / "work"
    (work / "segments").mkdir(parents=True)
    (work / "segments" / "walk.json").write_text(json.dumps({
        "duration_s": 3.0,
        "segments": [{"room": "Kitchen", "start_s": 0.0, "end_s": 3.0}],
    }), encoding="utf-8")
    rooms = ingest(cap, work)
    assert "Bathroom" in rooms and "Kitchen" in rooms


def test_ingest_applies_room_aliases(tmp_path):
    """Review renames/merges (work/room-aliases.json) survive re-ingest."""
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Snug" / "s1.jpg")
    work = tmp_path / "work"
    work.mkdir()
    (work / "room-aliases.json").write_text(json.dumps(
        {"version": 1, "map": {"Kitchen": "Pantry", "Snug": "Pantry"}}),
        encoding="utf-8")
    rooms = ingest(cap, work)
    assert set(rooms) == {"Pantry"}
    assert len(rooms["Pantry"]) == 2
    assert all(p.room == "Pantry" for p in rooms["Pantry"])


def test_extract_keyframes_time_window(tmp_path):
    pytest.importorskip("cv2")
    import cv2
    import numpy as np

    fps, size = 10, (64, 48)
    video = tmp_path / "clip.avi"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    rng = np.random.default_rng(1)
    for _ in range(6 * fps):
        vw.write(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    vw.release()

    all_frames = extract_keyframes(video, tmp_path / "all", max_frames=12)
    mid = extract_keyframes(video, tmp_path / "mid", max_frames=12,
                            start_s=2.0, end_s=4.0)
    assert mid
    for f in mid:
        idx = int(f.stem.rsplit("_f", 1)[1])
        assert 2.0 * fps <= idx < 4.0 * fps
    assert len(mid) <= len(all_frames)


def test_build_offline_with_progress_file(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    out = tmp_path / "report"
    prog = out / "work" / "build-progress.json"
    rc = main(["build", str(cap), "-o", str(out),
               "--backend", "offline", "--no-detect",
               "--progress-file", str(prog)])
    assert rc == 0
    assert prog.is_file()
    data = json.loads(prog.read_text(encoding="utf-8"))
    assert data["status"] == "done"
