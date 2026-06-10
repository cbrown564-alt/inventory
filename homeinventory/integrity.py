"""Evidential integrity: SHA-256 manifest of all source images.

The manifest is written alongside the report and summarised in its appendix, so
the photo set underlying the report is tamper-evident: anyone holding the
original files can re-hash them and confirm they match what the report relied on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import Photo


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(capture_dir: Path, rooms: dict[str, list[Photo]],
                   out_path: Path) -> dict:
    entries = []
    for room, photos in rooms.items():
        for p in photos:
            full = (capture_dir / p.path) if not Path(p.path).is_absolute() else Path(p.path)
            p.sha256 = sha256_file(full)
            entries.append({
                "photo_id": p.id,
                "room": room,
                "file": p.path,
                "sha256": p.sha256,
                "captured_at": p.captured_at,
                "source_video": p.source_video,
                "bytes": full.stat().st_size,
            })
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "sha256",
        "files": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    return manifest
