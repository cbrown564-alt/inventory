"""Evidential integrity: SHA-256 manifest of all source images.

The manifest is written alongside the report and summarised in its appendix, so
the photo set underlying the report is tamper-evident: anyone holding the
original files can re-hash them and confirm they match what the report relied on.

Video captures are hashed twice over: the original video file (so the source
footage itself is pinned) and each extracted keyframe (so the exact images the
AI looked at are pinned). Keyframe paths are recorded relative to the report
directory, not as machine-specific absolute paths.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schema import Photo


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_video(capture_dir: Path, room: str, name: str) -> Optional[Path]:
    """Locate a source video by the filename recorded on its keyframes."""
    for cand in (capture_dir / room / name, capture_dir / name):
        if cand.is_file():
            return cand
    room_dir = capture_dir / room
    if room_dir.is_dir():  # ingest walks rooms recursively, so search nested dirs
        return next(room_dir.rglob(name), None)
    return None


def build_manifest(capture_dir: Path, rooms: dict[str, list[Photo]],
                   out_path: Path) -> dict:
    out_dir = out_path.parent.resolve()
    entries = []
    videos: dict[str, dict] = {}
    for room, photos in rooms.items():
        for p in photos:
            full = (capture_dir / p.path) if not Path(p.path).is_absolute() else Path(p.path)
            p.sha256 = sha256_file(full)
            rec_path = p.path
            if Path(p.path).is_absolute():
                # extracted keyframes live under the report's work dir — record
                # them relative to the manifest so the path is portable
                try:
                    rec_path = os.path.relpath(p.path, out_dir)
                except ValueError:  # different drive on Windows
                    pass
            entries.append({
                "photo_id": p.id,
                "room": room,
                "file": rec_path,
                "sha256": p.sha256,
                "captured_at": p.captured_at,
                "source_video": p.source_video,
                "bytes": full.stat().st_size,
            })
            if p.source_video and p.source_video not in videos:
                vid = _find_video(capture_dir, room, p.source_video)
                if vid is not None:
                    videos[p.source_video] = {
                        "file": os.path.relpath(vid, capture_dir),
                        "sha256": sha256_file(vid),
                        "bytes": vid.stat().st_size,
                    }
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "sha256",
        "files": entries,
    }
    if videos:
        manifest["source_videos"] = sorted(videos.values(), key=lambda v: v["file"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return manifest
