"""Ingest a capture folder into rooms of photos.

Convention: `capture/<Room Name>/...` — each first-level subfolder is a room.
Image files become photos directly; video files are reduced to keyframes
(sharpness-gated, frame-difference sampled). Loose files at the root go into
a room called "General".
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .schema import Photo

log = logging.getLogger(__name__)

# iPhones shoot HEIC by default; Pillow needs the pillow-heif plugin to decode
# it. Registering the opener here makes HEIC work everywhere PIL is used
# (EXIF, describe encoding, report export).
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HEIF_OK = True
except ImportError:
    _HEIF_OK = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
HEIF_EXTS = {".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def _decodable(path: Path) -> bool:
    if path.suffix.lower() in HEIF_EXTS and not _HEIF_OK:
        log.warning("skipping %s: install pillow-heif to ingest HEIC/HEIF photos "
                    "(or export as JPEG)", path)
        return False
    return True


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
                      min_window_s: float = 0.75,
                      min_diff: float = 12.0,
                      lead_trim_s: float = 0.0) -> list[Path]:
    """Keep the sharpest frame from each time window of the video.

    An absolute sharpness threshold doesn't transfer across devices, codecs
    and lighting, and rejects entire spans of hand-held footage while the
    camera pans — leaving coverage holes where items are never seen by the
    describe backend. Instead: split the video into equal time windows and
    keep the sharpest candidate (~3 sampled per second) from each window, so
    every part of the walkthrough is represented by its best available frame.
    Windows where the camera barely moved since the last kept frame are
    dropped via mean absolute grey difference.

    ``lead_trim_s`` skips the first N seconds of the video. Room segments cut
    from one continuous walkthrough with stream copy start on the previous
    keyframe, i.e. up to ~2s inside the *previous* room — those lead frames
    put the neighbouring room's items into this room's schedule (the M2
    boundary-bleed failure mode, docs/07). Trimming the lead removes the
    bleed at the source; default 0.0 leaves single-room videos untouched.
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = n_frames / fps if n_frames else 0.0
    window_s = max(duration / max_frames, min_window_s) if duration else min_window_s
    step = max(1, int(fps / 3))  # ~3 candidate frames per second
    out_dir.mkdir(parents=True, exist_ok=True)

    kept: list[Path] = []
    last_kept_small = None
    best: Optional[tuple[float, int, "np.ndarray"]] = None  # current window's best
    window = 0

    def flush():
        nonlocal last_kept_small
        if best is None or len(kept) >= max_frames:
            return
        _sharp, fidx, frame = best
        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
        if last_kept_small is not None and \
                float(np.mean(cv2.absdiff(small, last_kept_small))) < min_diff:
            return  # camera didn't move since the last kept frame
        out = out_dir / f"{video.stem}_f{fidx:06d}.jpg"
        cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        kept.append(out)
        last_kept_small = small

    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        if lead_trim_s and (idx / fps) < lead_trim_s:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        if not ok:
            idx += 1
            continue
        w = int((idx / fps) / window_s)
        if w != window:
            flush()
            best, window = None, w
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
        if best is None or sharpness > best[0]:
            best = (sharpness, idx, frame.copy())
        idx += 1
        if len(kept) >= max_frames:
            break
    flush()
    cap.release()
    return kept


def ingest(capture_dir: Path, work_dir: Path,
           lead_trim_s: float = 0.0) -> dict[str, list[Photo]]:
    """Return {room_name: [Photo, ...]}. Video keyframes land in work_dir/frames.

    ``lead_trim_s`` is forwarded to keyframe extraction — use it when per-room
    videos were cut from one continuous walkthrough (see extract_keyframes)."""
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
                    if _decodable(f):
                        add(room, f)
                elif ext in VIDEO_EXTS:
                    frames = extract_keyframes(f, work_dir / "frames" / room,
                                               lead_trim_s=lead_trim_s)
                    for fr in frames:
                        add(room, fr, source_video=f.name)
        elif entry.is_file() and entry.suffix.lower() in IMAGE_EXTS:
            if _decodable(entry):
                add("General", entry)
        elif entry.is_file() and entry.suffix.lower() in VIDEO_EXTS:
            for fr in extract_keyframes(entry, work_dir / "frames" / "General",
                                        lead_trim_s=lead_trim_s):
                add("General", fr, source_video=entry.name)
    return rooms
