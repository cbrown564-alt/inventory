#!/usr/bin/env python3
"""Freeze the video-frame identity of a hero-cover benchmark report.

The pixels may remain private and untracked.  The manifest records enough
identity and acquisition provenance for the evaluator to reject a report made
from a different candidate pool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    inventory_path: Path,
    *,
    benchmark_id: str,
    segments_path: Path | None = None,
) -> dict:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    rooms: dict[str, dict] = {}
    frame_count = 0
    for room in inventory.get("rooms", []):
        video_photos = [
            photo for photo in room.get("photos", []) if photo.get("source_video")
        ]
        if not video_photos:
            continue
        candidates = [Path(photo["path"]).name for photo in video_photos]
        anchors = [
            Path(photo["path"]).name
            for photo in video_photos
            if photo.get("cover_anchor")
        ]
        if len(candidates) != len(set(candidates)):
            raise ValueError(f"duplicate frame names in {room['name']}")
        rooms[room["name"]] = {
            "candidates": candidates,
            "cover_anchors": anchors,
        }
        frame_count += len(candidates)

    manifest: dict = {
        "schema_version": 1,
        "benchmark_id": benchmark_id,
        "video": "IMG_5512.MOV",
        "frame_count": frame_count,
        "provenance": (
            "Generated from an offline build using the reviewed room segments. "
            "Private frame pixels remain untracked; room/frame identity, anchor "
            "provenance, and acquisition settings are frozen here."
        ),
        "acquisition": {
            "keyframes_per_minute": 12,
            "max_frames_per_segment": 24,
            "segment_boundary_trim_s": 2.0,
            "segment_cover_anchor_s": 2.0,
            "explicit_trim_lead_s": 0.0,
        },
        "rooms": rooms,
    }
    if segments_path is not None:
        manifest["segments_artifact"] = segments_path.name
        manifest["segments_sha256"] = sha256(segments_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--segments", type=Path)
    args = parser.parse_args()

    manifest = build_manifest(
        args.inventory,
        benchmark_id=args.benchmark_id,
        segments_path=args.segments,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} ({manifest['frame_count']} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
