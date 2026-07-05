"""Video metadata for the review UI: the photo → footage-moment mapping.

Keyframe filenames encode the absolute frame index in their source video
(``<stem>_f<idx>.jpg``, written by ingest.extract_keyframes), so a photo's
moment in the walkthrough is ``idx / fps``. Probing fps/duration uses cv2
when available; extracted frames can only exist if cv2 ran at build time,
so on a machine that never built from video this degrades to "no video
links" rather than an error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .ingest import VIDEO_EXTS

_FRAME_RE = re.compile(r"_f(\d+)\.jpe?g$", re.IGNORECASE)

VIDEO_CTYPES = {
    ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
}


def probe(path: Path) -> Optional[dict]:
    """{"fps", "duration"} for a video, or None (no cv2 / unreadable)."""
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    cap.release()
    if fps <= 0:
        return None
    return {"fps": fps, "duration": round(n / fps, 2) if n else 0.0}


def frame_index(photo_path: str) -> Optional[int]:
    m = _FRAME_RE.search(photo_path)
    return int(m.group(1)) if m else None


def capture_videos(capture_dir: Path) -> dict[str, Path]:
    """{capture-relative posix path: absolute path} for every video."""
    out: dict[str, Path] = {}
    if not capture_dir.is_dir():
        return out
    for p in sorted(capture_dir.rglob("*")):
        if p.is_file() and not p.name.startswith(".") \
                and p.suffix.lower() in VIDEO_EXTS:
            out[p.relative_to(capture_dir).as_posix()] = p
    return out


def load_segments(work_dir: Path, stem: str) -> list[dict]:
    """Room chapters cached by ingest for a root walkthrough video."""
    cache = work_dir / "segments" / f"{stem}.json"
    if not cache.is_file():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    segs = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segs, list):
        return []
    return [{"room": s.get("room", ""),
             "start": float(s.get("start_s", 0.0)),
             "end": float(s.get("end_s", 0.0))}
            for s in segs if isinstance(s, dict)]


def video_payload(inv, capture_dir: Path, work_dir: Path, src_prefix: str,
                  cache: dict) -> tuple[dict, dict]:
    """(videos, photo_time) for the review payload.

    videos:     {rel: {"name", "src", "fps", "duration", "segments"}}
    photo_time: {photo_id: {"video": rel, "t": seconds}}

    ``cache`` persists probe results across requests (keyed by rel path);
    a None entry records an unprobeable video so it is not re-opened.
    """
    paths = capture_videos(capture_dir)
    by_name: dict[str, list[str]] = {}
    for rel in paths:
        by_name.setdefault(Path(rel).name, []).append(rel)

    def meta_for(rel: str) -> Optional[dict]:
        if rel not in cache:
            m = probe(paths[rel])
            if m is not None:
                m = {**m, "name": Path(rel).name,
                     "src": f"{src_prefix}/video/{quote(rel)}",
                     "segments": load_segments(work_dir, Path(rel).stem)}
            cache[rel] = m
        return cache[rel]

    videos: dict[str, dict] = {}
    photo_time: dict[str, dict] = {}
    for room in inv.rooms:
        for ph in room.photos:
            if not ph.source_video:
                continue
            cands = by_name.get(ph.source_video)
            if not cands:
                continue
            # duplicate filenames across rooms: the photo's room folder wins
            rel = next((r for r in cands
                        if r.rsplit("/", 1)[0] == ph.room and "/" in r),
                       cands[0])
            meta = meta_for(rel)
            if meta is None:
                continue
            videos[rel] = meta
            idx = frame_index(ph.path)
            if idx is not None:
                photo_time[ph.id] = {"video": rel,
                                     "t": round(idx / meta["fps"], 2)}
    return videos, photo_time
