"""Capture-strategy experiment scaffolding (docs/26).

Photo-mode ingest and folder-layout validation for V0/V1/V2/P1/P2 arms.
Not a product feature — lives behind ``--photo-mode`` until the experiment
decides the default capture instruction.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .ingest import IMAGE_EXTS, VIDEO_EXTS

EXPERIMENT_ARMS = ("V0", "V1", "V2", "P1", "P2")

# Soft ranges from docs/26 capture protocols — validation warns, not hard-fails.
ARM_PROTOCOLS: dict[str, dict] = {
    "V0": {
        "kind": "continuous_video",
        "videos_at_root": (1, 1),
    },
    "V1": {
        "kind": "continuous_video",
        "videos_at_root": (1, 1),
    },
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
    if proto["kind"] == "continuous_video":
        root_photos = root_videos = 0
        nested_media: list[str] = []
        for entry in sorted(capture_dir.rglob("*")):
            if entry.name.startswith(".") or not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if entry.parent == capture_dir:
                root_photos += int(ext in IMAGE_EXTS)
                root_videos += int(ext in VIDEO_EXTS)
            elif ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                nested_media.append(entry.relative_to(capture_dir).as_posix())
        report.rooms.append(
            RoomLayout(
                name="Continuous walkthrough",
                photos=root_photos,
                videos=root_videos,
            )
        )
        lo, hi = proto["videos_at_root"]
        if root_videos < lo or root_videos > hi:
            report.ok = False
            report.errors.append(
                f"capture root has {root_videos} video(s); {arm} expects "
                "exactly one continuous walkthrough"
            )
        if root_photos:
            report.ok = False
            report.errors.append(
                f"{root_photos} root photo(s) are outside the {arm} protocol"
            )
        if nested_media:
            report.ok = False
            report.errors.append(
                f"{len(nested_media)} nested media file(s) are outside the "
                f"{arm} continuous-video arm"
            )
        return report

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
    arm_template = {
        "status": "not_run",
        "capture": {
            "path": "",
            "sha256": "",
            "protocol_validated": False,
        },
        "untouched_draft": {
            "path": "",
            "sha256": "",
            "built_at": "",
            "backend": "",
        },
        **axes,
    }
    return {
        "schema_version": 2,
        "_doc": "Capture-strategy experiment scorecard (docs/26). "
                "Fill per arm × property; average across properties before deciding.",
        "property": "",
        "gold": {
            "path": "",
            "sha256": "",
            "frozen_at": "",
            "independent_reviewer": "",
        },
        "arms": {arm: deepcopy(arm_template) for arm in
                 ("V0", "V1", "V2", "P1", "P2", "H1")},
    }


def write_scorecard_template(path: Path) -> Path:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scorecard_template(), indent=2, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    return path


def layout_report_dict(report: LayoutReport) -> dict:
    d = asdict(report)
    d["total_photos"] = report.total_photos
    d["total_videos"] = report.total_videos
    return d


SCORECARD_METRICS = (
    "accuracy.recall",
    "accuracy.precision",
    "accuracy.hallucination",
    "image_qual.mean_hero_rating_1_5",
    "image_qual.pct_heroes_establishing_on_room",
    "capture_min",
    "effort.tlx_band",
    "cost.tokens",
    "cost.usd",
    "review.minutes_to_issue",
    "review.accepts_unchanged",
    "review.material_edits",
    "review.rejects",
    "review.missing_item_additions",
    "review.not_visible_marks",
    "review.recaptures",
    "structure.room_name_correctness",
    "structure.boundary_bleed_count",
    "structure.hero_pass_rate",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
RATIO_METRICS = (
    "accuracy.recall",
    "accuracy.precision",
    "accuracy.hallucination",
    "image_qual.pct_heroes_establishing_on_room",
    "structure.room_name_correctness",
    "structure.hero_pass_rate",
)
NONNEGATIVE_METRICS = (
    "capture_min",
    "cost.tokens",
    "cost.usd",
    "review.minutes_to_issue",
    "review.accepts_unchanged",
    "review.material_edits",
    "review.rejects",
    "review.missing_item_additions",
    "review.not_visible_marks",
    "review.recaptures",
    "structure.boundary_bleed_count",
)


def _value_at(payload: dict, dotted_path: str):
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def audit_scorecard(
    payload: dict,
    required_arms: tuple[str, ...] = ("V0", "V1", "P1", "P2"),
) -> dict:
    """Fail closed until comparable untouched-draft evidence is complete."""
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if not str(payload.get("property") or "").strip():
        errors.append("property is required")
    gold = payload.get("gold") or {}
    for field_name in ("path", "sha256", "frozen_at", "independent_reviewer"):
        if not str(gold.get(field_name) or "").strip():
            errors.append(f"gold.{field_name} is required")
    if gold.get("sha256") and not SHA256_PATTERN.fullmatch(str(gold["sha256"])):
        errors.append("gold.sha256 must be a 64-character SHA-256 digest")
    arms = payload.get("arms") or {}
    for arm in required_arms:
        evidence = arms.get(arm)
        if not isinstance(evidence, dict):
            errors.append(f"{arm}: scorecard entry is missing")
            continue
        if evidence.get("status") != "complete":
            errors.append(f"{arm}: status must be complete")
        capture = evidence.get("capture") or {}
        for field_name in ("path", "sha256"):
            if not str(capture.get(field_name) or "").strip():
                errors.append(f"{arm}: capture.{field_name} is required")
        if capture.get("sha256") and not SHA256_PATTERN.fullmatch(
            str(capture["sha256"])
        ):
            errors.append(
                f"{arm}: capture.sha256 must be a 64-character SHA-256 digest"
            )
        if capture.get("protocol_validated") is not True:
            errors.append(f"{arm}: capture protocol is not validated")
        draft = evidence.get("untouched_draft") or {}
        for field_name in ("path", "sha256", "built_at", "backend"):
            if not str(draft.get(field_name) or "").strip():
                errors.append(f"{arm}: untouched_draft.{field_name} is required")
        if draft.get("sha256") and not SHA256_PATTERN.fullmatch(
            str(draft["sha256"])
        ):
            errors.append(
                f"{arm}: untouched_draft.sha256 must be a 64-character "
                "SHA-256 digest"
            )
        for metric in SCORECARD_METRICS:
            if _value_at(evidence, metric) is None:
                errors.append(f"{arm}: metric {metric} is missing")
        for metric in RATIO_METRICS:
            value = _value_at(evidence, metric)
            if value is not None and (
                not _is_number(value) or not 0 <= value <= 1
            ):
                errors.append(f"{arm}: metric {metric} must be between 0 and 1")
        hero_rating = _value_at(
            evidence, "image_qual.mean_hero_rating_1_5"
        )
        if hero_rating is not None and (
            not _is_number(hero_rating) or not 1 <= hero_rating <= 5
        ):
            errors.append(
                f"{arm}: metric image_qual.mean_hero_rating_1_5 "
                "must be between 1 and 5"
            )
        for metric in NONNEGATIVE_METRICS:
            value = _value_at(evidence, metric)
            if value is not None and (
                not _is_number(value) or value < 0
            ):
                errors.append(f"{arm}: metric {metric} must be non-negative")
        tlx_band = _value_at(evidence, "effort.tlx_band")
        if tlx_band is not None and tlx_band not in {"low", "medium", "high"}:
            errors.append(f"{arm}: effort.tlx_band must be low, medium or high")
    extra_complete = sorted(
        arm
        for arm, evidence in arms.items()
        if arm not in required_arms
        and isinstance(evidence, dict)
        and evidence.get("status") == "complete"
    )
    if extra_complete:
        warnings.append(
            "completed non-required arms: " + ", ".join(extra_complete)
        )
    return {
        "ready": not errors,
        "property": payload.get("property") or "",
        "required_arms": list(required_arms),
        "errors": errors,
        "warnings": warnings,
    }
