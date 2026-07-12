"""Ingest a capture folder into rooms of photos.

Convention: `capture/<Room Name>/...` — each first-level subfolder is a room.
Image files become photos directly; video files are reduced to keyframes
(sharpness-gated, frame-difference sampled). Loose files at the root go into
a room called "General".
"""

from __future__ import annotations

import json
import logging
import os
import re
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

# VLM segment seams and midpoint normalisation can land up to ~2s inside the
# previous room; trim that lead window when extracting keyframes per segment
# from one continuous walkthrough (docs/07, docs/11).
SEGMENT_BOUNDARY_TRIM_S = 2.0

# Establishing views often occur immediately as the camera enters a room. Keep
# one sharp candidate from that boundary window before applying the regular
# bleed trim. An explicit --trim-lead remains literal and disables this anchor.
SEGMENT_COVER_ANCHOR_S = 2.0


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


def segment_frame_budget(duration_s: float, base_max: int = 24,
                         min_frames: int = 4) -> int:
    """Keyframes for one segment — ~12 per minute, capped.

    Five-to-ten-second windows are short enough to retain brief wide room
    views that otherwise lose a whole-window sharpness contest to a floor,
    appliance, or other textured close-up.
    """
    return max(min_frames, min(base_max, round(duration_s / 60.0 * 12)))


def extract_keyframes(video: Path, out_dir: Path, max_frames: int = 24,
                      min_window_s: float = 0.75,
                      min_diff: float = 12.0,
                      lead_trim_s: float = 0.0,
                      start_s: float = 0.0,
                      end_s: Optional[float] = None) -> list[Path]:
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
    clip_end = end_s if end_s is not None else duration
    clip_start = max(0.0, start_s)
    clip_dur = max(clip_end - clip_start, 0.0)
    window_s = max(clip_dur / max_frames, min_window_s) if clip_dur else min_window_s
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
    if clip_start > 0:
        # Seek instead of decoding the whole prefix: per-segment extraction
        # over one walkthrough would otherwise re-decode from frame zero for
        # every room. The t_s < clip_start guard below stays as the fallback
        # for backends whose seek lands early (or fails and leaves idx at 0).
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(clip_start * fps))
        idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        t_s = idx / fps
        if t_s < clip_start:
            idx += 1
            continue
        if end_s is not None and t_s >= clip_end:
            break
        if lead_trim_s and t_s < clip_start + lead_trim_s:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        if not ok:
            idx += 1
            continue
        w = int((t_s - clip_start) / window_s)
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


ROOM_ALIASES_FILE = "room-aliases.json"


def load_room_aliases(work_dir: Path) -> dict[str, str]:
    """Review-time room renames/merges ({old name: new name}).

    Rebuilds re-derive room names from capture folders and the cached
    segments.json, so corrections made in review must be re-applied at
    ingest or a rebuild resurrects the old names and orphans hand edits."""
    path = work_dir / ROOM_ALIASES_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    amap = data.get("map") if isinstance(data, dict) else None
    return amap if isinstance(amap, dict) else {}


def find_root_videos(capture_dir: Path) -> list[Path]:
    """Walkthrough videos dropped at the capture root (video-first journey)."""
    out: list[Path] = []
    if not capture_dir.is_dir():
        return out
    for entry in sorted(capture_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and not entry.name.startswith(".") \
                and entry.suffix.lower() in VIDEO_EXTS:
            out.append(entry)
    return out


def _load_segments(video: Path, work_dir: Path, *,
                   segment_model: str, every_s: float,
                   segments_json: Optional[Path]) -> list:
    """Return segment list, caching to work_dir/segments/."""
    from dataclasses import asdict
    from .segment import Segment, segment_video

    cache = segments_json or work_dir / "segments" / f"{video.stem}.json"
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        segments = [Segment(**s) for s in data["segments"]]
        log.info("loaded %d segments from %s", len(segments), cache)
        return segments
    segments, meta = segment_video(video, every_s=every_s, model=segment_model)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(
        {**meta, "segments": [asdict(s) for s in segments]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    return segments


def _ingest_root_video(video: Path, work_dir: Path, capture_dir: Path, add,
                       *, segment_model: str, segment_every: float,
                       segments_json: Optional[Path], no_segment: bool,
                       lead_trim_s: float,
                       on_segmented=None, on_extracting=None) -> None:
    if no_segment:
        for fr in extract_keyframes(video, work_dir / "frames" / "General",
                                    lead_trim_s=lead_trim_s):
            add("General", fr, source_video=video.name)
        if on_segmented:
            on_segmented(1, ["General"])
        return
    segments = _load_segments(video, work_dir, segment_model=segment_model,
                              every_s=segment_every,
                              segments_json=segments_json)
    room_names = sorted({s.room for s in segments})
    if on_segmented:
        on_segmented(len(room_names), room_names)
    if on_extracting:
        on_extracting()
    boundary_trim = lead_trim_s if lead_trim_s > 0 else SEGMENT_BOUNDARY_TRIM_S
    for i, seg in enumerate(segments):
        seg_dur = max(seg.end_s - seg.start_s, 0.1)
        budget = segment_frame_budget(seg_dur)
        safe = re.sub(r"[^\w\- ]+", "_", seg.room)[:40]
        frame_dir = work_dir / "frames" / f"{safe}_seg{i:02d}"
        # First segment starts at t=0; later segments inherit bleed from the
        # previous room at the seam unless we trim the lead window.
        seg_trim = boundary_trim if i > 0 else 0.0
        seen: set[Path] = set()
        # The VLM boundary is also commonly the first wide view into the new
        # room. Preserve one sharp entry candidate, while the main pool below
        # still starts after the defensive boundary trim. If a caller supplied
        # --trim-lead explicitly, honour it literally and suppress the anchor.
        if i > 0 and lead_trim_s <= 0:
            anchor_end = min(seg.end_s, seg.start_s + SEGMENT_COVER_ANCHOR_S)
            for fr in extract_keyframes(
                    video, frame_dir, max_frames=1, min_diff=0.0,
                    start_s=seg.start_s, end_s=anchor_end):
                resolved = fr.resolve()
                if resolved not in seen:
                    add(seg.room, fr, source_video=video.name,
                        cover_anchor=True)
                    seen.add(resolved)
        for fr in extract_keyframes(video, frame_dir, max_frames=budget,
                                    lead_trim_s=seg_trim,
                                    start_s=seg.start_s, end_s=seg.end_s):
            resolved = fr.resolve()
            if resolved not in seen:
                add(seg.room, fr, source_video=video.name)
                seen.add(resolved)


def ingest(capture_dir: Path, work_dir: Path,
           lead_trim_s: float = 0.0,
           *,
           segment_model: str = "gemini-3.5-flash",
           segment_every: float = 5.0,
           segments_json: Optional[Path] = None,
           no_segment: bool = False,
           on_segmenting=None,
           on_segmented=None,
           on_extracting=None) -> dict[str, list[Photo]]:
    """Return {room_name: [Photo, ...]}. Video keyframes land in work_dir/frames.

    ``lead_trim_s`` is forwarded to keyframe extraction — use it when per-room
    videos were cut from one continuous walkthrough (see extract_keyframes)."""
    capture_dir = capture_dir.resolve()
    rooms: dict[str, list[Photo]] = {}
    counter = 0

    def add(room: str, path: Path, source_video: Optional[str] = None,
            cover_anchor: bool = False):
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
            cover_anchor=cover_anchor,
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
            if on_segmenting:
                on_segmenting()
            _ingest_root_video(entry, work_dir, capture_dir, add,
                               segment_model=segment_model,
                               segment_every=segment_every,
                               segments_json=segments_json,
                               no_segment=no_segment,
                               lead_trim_s=lead_trim_s,
                               on_segmented=on_segmented,
                               on_extracting=on_extracting)

    aliases = load_room_aliases(work_dir)
    if aliases:
        lower = {k.lower(): v for k, v in aliases.items()}
        aliased: dict[str, list[Photo]] = {}
        for name, photos in rooms.items():
            target = lower.get(name.lower(), name)
            for p in photos:
                p.room = target
            aliased.setdefault(target, []).extend(photos)
        rooms = aliased
    return rooms
