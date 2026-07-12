"""Versioned hero-cover gold fixtures and candidate-pool compatibility.

The cover benchmark is meaningful only when gold labels and scorer candidates
refer to the same immutable room/frame pool.  These helpers keep that identity
check separate from the two quality questions:

* is rank 1 an acceptable cover?
* does rank 1 match the curator's preferred cover?
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 2


class HeroGoldValidationError(ValueError):
    """Raised when a gold fixture is internally contradictory or incomplete."""


def preferred_frames(room: dict) -> list[str]:
    """Ordered curator preferences, with legacy ``top`` compatibility."""
    return list(room.get("preferred", room.get("top", [])))


def acceptable_frames(room: dict) -> list[str]:
    """Frames that satisfy the cover bar, not merely the single favourite."""
    if "acceptable" in room:
        return list(room["acceptable"])
    return preferred_frames(room)


def rejected_frames(room: dict) -> list[str]:
    """Known-bad frames, with legacy ``bottom`` compatibility."""
    values = room.get("rejected", room.get("bottom", []))
    return [v["frame"] if isinstance(v, dict) else v for v in values]


def review_required_frames(room: dict) -> list[str]:
    """Contradictory or low-confidence labels excluded from scored sets."""
    return list(room.get("review_required", []))


def load_candidate_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    issues: list[str] = []
    all_candidates: list[str] = []
    for room_name, room in data.get("rooms", {}).items():
        candidates = room.get("candidates", [])
        dupes = _duplicates(candidates)
        if dupes:
            issues.append(f"{room_name}: duplicate candidates: {sorted(dupes)}")
        all_candidates.extend(candidates)
    assigned_twice = _duplicates(all_candidates)
    if assigned_twice:
        issues.append(f"frames assigned to multiple rooms: {sorted(assigned_twice)}")
    if data.get("frame_count") != len(all_candidates):
        issues.append(
            f"frame_count is {data.get('frame_count')}, expected {len(all_candidates)}"
        )

    source_name = data.get("source_artifact")
    expected_hash = data.get("source_artifact_sha256")
    if source_name and expected_hash:
        source = path.parent / source_name
        if not source.is_file():
            issues.append(f"source artifact is missing: {source_name}")
        else:
            actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual_hash != expected_hash.lower():
                issues.append(
                    f"source artifact hash differs: {actual_hash} != {expected_hash}"
                )
    if issues:
        raise HeroGoldValidationError("; ".join(issues))
    return data


def load_gold_document(path: Path) -> tuple[dict, dict | None]:
    """Load and validate a gold document plus its optional candidate manifest."""
    data = json.loads(path.read_text(encoding="utf-8"))
    manifest = None
    manifest_name = data.get("candidate_manifest")
    if manifest_name:
        manifest = load_candidate_manifest(path.parent / manifest_name)
    validate_gold_document(data, manifest)
    return data, manifest


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_gold_document(data: dict, manifest: dict | None = None) -> None:
    """Reject ambiguous labels and references outside the frozen candidate pool."""
    issues: list[str] = []
    schema = data.get("schema_version", 1)
    rooms = data.get("rooms")
    if not isinstance(rooms, dict) or not rooms:
        issues.append("rooms must be a non-empty object")
        rooms = {}

    if schema >= SCHEMA_VERSION:
        if not data.get("benchmark_id"):
            issues.append("benchmark_id is required for schema v2")
        if not data.get("candidate_manifest"):
            issues.append("candidate_manifest is required for schema v2")
        if manifest is None:
            issues.append("candidate manifest could not be loaded")

    manifest_rooms = (manifest or {}).get("rooms", {})
    if manifest is not None:
        if data.get("benchmark_id") != manifest.get("benchmark_id"):
            issues.append("gold and candidate manifest benchmark_id differ")
        declared = manifest.get("frame_count")
        actual = sum(len(v.get("candidates", [])) for v in manifest_rooms.values())
        if declared != actual:
            issues.append(
                f"candidate manifest frame_count is {declared}, expected {actual}"
            )

    for room_name, room in rooms.items():
        preferred = preferred_frames(room)
        acceptable = acceptable_frames(room)
        rejected = rejected_frames(room)
        review = review_required_frames(room)
        if not room.get("no_valid_candidate") and not acceptable:
            issues.append(f"{room_name}: acceptable must not be empty")
        if acceptable and not preferred:
            issues.append(f"{room_name}: preferred must not be empty")
        unaccepted_preferences = set(preferred) - set(acceptable)
        if unaccepted_preferences:
            issues.append(
                f"{room_name}: preferred frames must be acceptable: "
                f"{sorted(unaccepted_preferences)}"
            )
        for label, values in (
            ("preferred", preferred),
            ("acceptable", acceptable),
            ("rejected", rejected),
            ("review_required", review),
        ):
            dupes = _duplicates(values)
            if dupes:
                issues.append(f"{room_name}: duplicate {label}: {sorted(dupes)}")
        sets = {
            "acceptable": set(acceptable),
            "rejected": set(rejected),
            "review_required": set(review),
        }
        for left, right in (
            ("acceptable", "rejected"),
            ("acceptable", "review_required"),
            ("rejected", "review_required"),
        ):
            overlap = sets[left] & sets[right]
            if overlap:
                issues.append(
                    f"{room_name}: {left}/{right} overlap: {sorted(overlap)}"
                )

        if manifest is not None:
            candidates = set(manifest_rooms.get(room_name, {}).get("candidates", []))
            if not candidates:
                issues.append(f"{room_name}: absent from candidate manifest")
            labelled = set(preferred) | set(acceptable) | set(rejected) | set(review)
            unknown = labelled - candidates
            if unknown:
                issues.append(
                    f"{room_name}: labels absent from candidate pool: {sorted(unknown)}"
                )

    if issues:
        raise HeroGoldValidationError("; ".join(issues))


def actual_candidate_rooms(
    rooms: list[tuple[str, list[dict]]],
) -> dict[str, set[str]]:
    """Convert ``eval_hero_cover.load_rooms`` output to identity sets."""
    return {
        room_name: {Path(frame["path"]).name for frame in frames}
        for room_name, frames in rooms
    }


def compatibility_issues(
    manifest: dict,
    rooms: list[tuple[str, list[dict]]],
) -> list[str]:
    """Describe room/frame drift between a frozen manifest and a local report."""
    expected = {
        name: set(spec.get("candidates", []))
        for name, spec in manifest.get("rooms", {}).items()
    }
    actual = actual_candidate_rooms(rooms)
    issues: list[str] = []
    missing_rooms = sorted(set(expected) - set(actual))
    extra_rooms = sorted(set(actual) - set(expected))
    if missing_rooms:
        issues.append(f"missing rooms: {', '.join(missing_rooms)}")
    if extra_rooms:
        issues.append(f"unexpected rooms: {', '.join(extra_rooms)}")
    for room_name in sorted(set(expected) & set(actual)):
        missing = expected[room_name] - actual[room_name]
        extra = actual[room_name] - expected[room_name]
        if missing or extra:
            issues.append(
                f"{room_name}: {len(missing)} expected frames missing, "
                f"{len(extra)} unexpected frames"
            )
    return issues


def rank1_by_room(rooms: list[tuple[str, list[dict]]]) -> dict[str, str | None]:
    """Return the current product rank-1 filename for each video-backed room."""
    out: dict[str, str | None] = {}
    for room_name, frames in rooms:
        ranked = [frame for frame in frames if frame.get("hero")]
        best = min(ranked, key=lambda frame: frame["hero"], default=None)
        out[room_name] = Path(best["path"]).name if best else None
    return out
