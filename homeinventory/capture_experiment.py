"""Capture-strategy experiment scaffolding (docs/26).

Photo-mode ingest and folder-layout validation for P1/P2/V2 arms.
Not a product feature — lives behind ``--photo-mode`` until the experiment
decides the default capture instruction.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .ingest import IMAGE_EXTS, VIDEO_EXTS

EXPERIMENT_ARMS = ("P1", "P2", "V2")

# Soft ranges from docs/26 capture protocols — validation warns, not hard-fails.
ARM_PROTOCOLS: dict[str, dict] = {
    "P1": {
        "kind": "photos",
        "photos_per_room": (3, 4),
        "total_photos": (25, 35),
    },
    "P2": {
        "kind": "photos",
        "photos_per_room": (8, 10),
        "total_photos": (70, 90),
    },
    "V2": {
        "kind": "video_per_room",
        "videos_per_room": (1, 1),
    },
}


@dataclass
class RoomLayout:
    name: str
    photos: int = 0
    videos: int = 0


@dataclass
class LayoutReport:
    arm: str
    capture_dir: str
    rooms: list[RoomLayout] = field(default_factory=list)
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_photos(self) -> int:
        return sum(r.photos for r in self.rooms)

    @property
    def total_videos(self) -> int:
        return sum(r.videos for r in self.rooms)


def _scan_room(room_dir: Path) -> RoomLayout:
    layout = RoomLayout(name=room_dir.name)
    for f in sorted(room_dir.rglob("*")):
        if f.name.startswith(".") or not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in IMAGE_EXTS:
            layout.photos += 1
        elif ext in VIDEO_EXTS:
            layout.videos += 1
    return layout


def validate_capture_layout(capture_dir: Path, arm: str) -> LayoutReport:
    """Check ``capture/<Room>/…`` layout against an experiment arm protocol."""
    arm = arm.upper()
    if arm not in EXPERIMENT_ARMS:
        raise ValueError(f"unknown arm {arm!r}; choose from {EXPERIMENT_ARMS}")

    capture_dir = capture_dir.resolve()
    report = LayoutReport(arm=arm, capture_dir=str(capture_dir))
    if not capture_dir.is_dir():
        report.ok = False
        report.errors.append(f"capture dir not found: {capture_dir}")
        return report

    proto = ARM_PROTOCOLS[arm]
    room_dirs = sorted(
        (p for p in capture_dir.iterdir()
         if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )
    if not room_dirs:
        report.ok = False
        report.errors.append(
            "no room subfolders — expected capture/<Room Name>/…")
        return report

    loose_images = loose_videos = 0
    for entry in capture_dir.iterdir():
        if entry.name.startswith(".") or not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if ext in IMAGE_EXTS:
            loose_images += 1
        elif ext in VIDEO_EXTS:
            loose_videos += 1

    if loose_images or loose_videos:
        report.warnings.append(
            f"{loose_images} loose photo(s) and {loose_videos} root video(s) "
            "at capture root — experiment arms expect room subfolders only")

    for room_dir in room_dirs:
        layout = _scan_room(room_dir)
        report.rooms.append(layout)
        if proto["kind"] == "photos":
            lo, hi = proto["photos_per_room"]
            if layout.videos:
                report.errors.append(
                    f"{layout.name}: {layout.videos} video(s) — "
                    f"{arm} expects photos only")
                report.ok = False
            if layout.photos == 0:
                report.errors.append(f"{layout.name}: no photos found")
                report.ok = False
            elif layout.photos < lo or layout.photos > hi:
                report.warnings.append(
                    f"{layout.name}: {layout.photos} photo(s) "
                    f"(protocol {lo}–{hi})")
        else:  # V2
            lo, hi = proto["videos_per_room"]
            if layout.photos:
                report.warnings.append(
                    f"{layout.name}: {layout.photos} photo(s) mixed with video")
            if layout.videos < lo or layout.videos > hi:
                msg = (f"{layout.name}: {layout.videos} video(s) "
                       f"(protocol {lo}–{hi})")
                if layout.videos == 0:
                    report.errors.append(msg)
                    report.ok = False
                else:
                    report.warnings.append(msg)

    if proto["kind"] == "photos":
        lo, hi = proto["total_photos"]
        total = report.total_photos
        if total < lo or total > hi:
            report.warnings.append(
                f"property total {total} photos (protocol ~{lo}–{hi})")

    return report


def scorecard_template() -> dict:
    """Empty per-arm scorecard structure from docs/26 metrics section."""
    axes = {
        "accuracy": {
            "recall": None,
            "precision": None,
            "hallucination": None,
        },
        "image_qual": {
            "mean_hero_rating_1_5": None,
            "pct_heroes_establishing_on_room": None,
        },
        "capture_min": None,
        "effort": {"tlx_band": None, "observer_notes": ""},
        "cost": {"tokens": None, "usd": None},
        "review": {
            "minutes_to_issue": None,
            "accepts_unchanged": None,
            "material_edits": None,
            "rejects": None,
            "missing_item_additions": None,
            "not_visible_marks": None,
            "recaptures": None,
        },
        "structure": {
            "room_name_correctness": None,
            "boundary_bleed_count": None,
            "hero_pass_rate": None,
        },
    }
    return {
        "_doc": "Capture-strategy experiment scorecard (docs/26). "
                "Fill per arm × property; average across properties before deciding.",
        "property": "",
        "arms": {arm: dict(axes) for arm in
                 ("V0", "V1", "V2", "P1", "P2", "H1")},
    }


def write_scorecard_template(path: Path) -> Path:
    path = path.resolve()
    path.write_text(json.dumps(scorecard_template(), indent=2, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    return path


def layout_report_dict(report: LayoutReport) -> dict:
    d = asdict(report)
    d["total_photos"] = report.total_photos
    d["total_videos"] = report.total_videos
    return d
