"""EXIF capture metadata for extracted video keyframes (deposit-scheme spec)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import Base

from homeinventory.ingest import (
    exif_capture_time,
    extract_keyframes,
    frame_captured_at,
    ingest,
    stamp_exif_capture_time,
    video_recorded_epoch,
)
from homeinventory.schema import Inventory, Photo, Room
from homeinventory.videometa import video_payload


def _write_test_video(path: Path, *, fps: int = 10, seconds: int = 4) -> None:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps,
                         (64, 48))
    rng = np.random.default_rng(0)
    for _ in range(seconds * fps):
        vw.write(rng.integers(0, 255, (48, 64, 3), dtype=np.uint8))
    vw.release()


def _set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def test_extracted_keyframes_carry_exif_datetime_original(tmp_path):
    cv2 = pytest.importorskip("cv2")

    video = tmp_path / "walk.avi"
    _write_test_video(video, fps=10, seconds=4)
    recorded = datetime(2026, 7, 8, 14, 0, 0)
    _set_mtime(video, recorded)

    frames = extract_keyframes(video, tmp_path / "frames", max_frames=4)
    assert frames
    for frame in frames:
        idx = int(frame.stem.rsplit("_f", 1)[1])
        expected = frame_captured_at(video, idx, 10.0)
        assert exif_capture_time(frame) == expected
        with Image.open(frame) as im:
            exif = im.getexif()
            assert exif.get(Base.DateTimeOriginal) == expected.replace("-", ":", 2)


def test_ingest_sets_captured_at_on_extracted_frames(tmp_path):
    cap = tmp_path / "capture"
    room = cap / "Kitchen"
    room.mkdir(parents=True)
    video = room / "kitchen.avi"
    _write_test_video(video, fps=10, seconds=3)
    _set_mtime(video, datetime(2026, 7, 8, 9, 30, 0))

    work = tmp_path / "work"
    rooms = ingest(cap, work)
    photos = rooms["Kitchen"]
    assert photos
    for photo in photos:
        assert photo.source_video == "kitchen.avi"
        assert photo.captured_at
        assert exif_capture_time(Path(photo.path)) == photo.captured_at


def test_native_photo_captured_at_unchanged(tmp_path):
    cap = tmp_path / "capture"
    cap.mkdir()
    photo_path = cap / "native.jpg"
    exif_dt = "2025:11:03 16:45:12"
    im = Image.new("RGB", (32, 24), "white")
    exif = im.getexif()
    exif[Base.DateTimeOriginal] = exif_dt
    exif[Base.DateTime] = exif_dt
    im.save(photo_path, exif=exif)

    rooms = ingest(cap, tmp_path / "work")
    photo = rooms["General"][0]
    assert photo.captured_at == "2025-11-03 16:45:12"
    assert photo.source_video is None


def test_video_payload_keeps_timecode_provenance(tmp_path):
    cv2 = pytest.importorskip("cv2")

    cap = tmp_path / "capture"
    room = cap / "Kitchen"
    room.mkdir(parents=True)
    video = room / "kitchen.mp4"
    w = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"),
                        10.0, (64, 48))
    import numpy as np
    for i in range(40):
        w.write(np.full((48, 64, 3), i * 5 % 255, dtype=np.uint8))
    w.release()

    work = tmp_path / "work"
    rooms = ingest(cap, work)
    assert rooms["Kitchen"]
    inv = Inventory(rooms=[Room(name="Kitchen", photos=rooms["Kitchen"])])
    _videos, photo_time = video_payload(inv, cap, work, "", {})
    sample = next(p for p in rooms["Kitchen"] if photo_time.get(p.id))
    idx = int(Path(sample.path).stem.rsplit("_f", 1)[1])
    assert photo_time[sample.id]["t"] == pytest.approx(idx / 10.0, abs=0.2)
    assert sample.captured_at


def test_stamp_exif_capture_time_roundtrip(tmp_path):
    path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), "red").save(path)
    stamp_exif_capture_time(path, "2026-07-12 18:05:33")
    assert exif_capture_time(path) == "2026-07-12 18:05:33"


def test_video_recorded_epoch_prefers_mtime_for_avi(tmp_path):
    video = tmp_path / "clip.avi"
    video.write_bytes(b"fake")
    anchor = datetime(2026, 1, 15, 12, 0, 0)
    _set_mtime(video, anchor)
    assert video_recorded_epoch(video) == pytest.approx(anchor.timestamp())


def test_frame_captured_at_adds_offset(tmp_path):
    video = tmp_path / "clip.avi"
    video.write_bytes(b"fake")
    anchor = datetime(2026, 1, 15, 12, 0, 0)
    _set_mtime(video, anchor)
    got = datetime.strptime(frame_captured_at(video, 50, 10.0), "%Y-%m-%d %H:%M:%S")
    assert got == anchor + timedelta(seconds=5)
