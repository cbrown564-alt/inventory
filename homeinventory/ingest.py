"""Ingest a capture folder into rooms of photos.

Convention: `capture/<Room Name>/...` — each first-level subfolder is a room.
Image files become photos directly; video files are reduced to keyframes
(sharpness-gated, frame-difference sampled). Loose files at the root go into
a room called "General".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .schema import Photo

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def exif_capture_time(path: Path) -> Optional[str]:
    try:
        from PIL import Image, ExifTags
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            tag_ids = {v: k for k, v in ExifTags.TAGS.items()}
            for tag in ("DateTimeOriginal", "DateTime"):
                tid = tag_ids.get(tag)
                val = exif.get(tid) if tid else None
                if val:
                    # EXIF format: "YYYY:MM:DD HH:MM:SS"
                    return str(val).replace(":", "-", 2)
    except Exception:
        pass
    return None


def extract_keyframes(video: Path, out_dir: Path, max_frames: int = 24,
                      min_sharpness: float = 60.0) -> list[Path]:
    """Sample a video into at most `max_frames` sharp, mutually distinct frames.

    Strategy: sample ~3 candidate frames per second, score sharpness (variance of
    Laplacian), drop blurry frames, then greedily keep frames that differ enough
    from the last kept frame (mean absolute grey difference). This favours the
    moments the camera lingers, which is where users frame items deliberately.
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(fps / 3))
    out_dir.mkdir(parents=True, exist_ok=True)

    kept: list[Path] = []
    last_kept_grey = None
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        idx += 1
        if not ok:
            continue
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = cv2.Laplacian(grey, cv2.CV_64F).var()
        if sharpness < min_sharpness:
            continue
        small = cv2.resize(grey, (160, 90))
        if last_kept_grey is not None:
            diff = float(np.mean(cv2.absdiff(small, last_kept_grey)))
            if diff < 12.0:  # too similar to the previous keyframe
                continue
        out = out_dir / f"{video.stem}_f{idx:06d}.jpg"
        cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        kept.append(out)
        last_kept_grey = small
        if len(kept) >= max_frames:
            break
    cap.release()
    return kept


def ingest(capture_dir: Path, work_dir: Path) -> dict[str, list[Photo]]:
    """Return {room_name: [Photo, ...]}. Video keyframes land in work_dir/frames."""
    capture_dir = capture_dir.resolve()
    rooms: dict[str, list[Photo]] = {}
    counter = 0

    def add(room: str, path: Path, source_video: Optional[str] = None):
        nonlocal counter
        counter += 1
        path = path.resolve()
        # capture photos stay relative (portable manifest); extracted video
        # frames live under the work dir, so keep those absolute
        rooms.setdefault(room, []).append(Photo(
            id=f"P{counter:03d}",
            path=os.path.relpath(path, capture_dir) if path.is_relative_to(capture_dir)
                 else str(path),
            room=room,
            captured_at=exif_capture_time(path),
            source_video=source_video,
        ))

    entries = sorted(capture_dir.iterdir(), key=lambda p: p.name.lower())
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            room = entry.name
            for f in sorted(entry.rglob("*")):
                if f.name.startswith(".") or not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext in IMAGE_EXTS:
                    add(room, f)
                elif ext in VIDEO_EXTS:
                    frames = extract_keyframes(f, work_dir / "frames" / room)
                    for fr in frames:
                        add(room, fr, source_video=f.name)
        elif entry.is_file() and entry.suffix.lower() in IMAGE_EXTS:
            add("General", entry)
        elif entry.is_file() and entry.suffix.lower() in VIDEO_EXTS:
            for fr in extract_keyframes(entry, work_dir / "frames" / "General"):
                add("General", fr, source_video=entry.name)
    return rooms
