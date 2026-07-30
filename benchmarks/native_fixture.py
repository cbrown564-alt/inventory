#!/usr/bin/env python3
"""Prepare, freeze and audit the external native-resolution v1 fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MIN_PROPERTIES = 2
MIN_NOTABLE_FACTS = 100
MIN_MATERIAL_DEFECTS = 20


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _images(capture_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in capture_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS
    )


def _labels_ready(manifest: dict) -> tuple[dict[str, bool], dict[str, int]]:
    properties = manifest.get("properties") or []
    counts = {
        "properties": len(properties),
        "notable_facts": sum(
            len(prop.get("notable_facts") or []) for prop in properties
        ),
        "material_defects": sum(
            len(prop.get("material_defects") or []) for prop in properties
        ),
        "clean_negative_controls": sum(
            len((prop.get("negative_controls") or {}).get("clean") or [])
            for prop in properties
        ),
        "ambiguous_near_negatives": sum(
            len((prop.get("negative_controls") or {}).get("ambiguous") or [])
            for prop in properties
        ),
    }
    checks = {
        "two_external_properties": (
            len(
                {
                    str(prop.get("property_id") or "").strip()
                    for prop in properties
                    if str(prop.get("property_id") or "").strip()
                }
            )
            >= MIN_PROPERTIES
        ),
        "source_authority_recorded": bool(properties)
        and all(
            str(prop.get("source_authority") or "").strip()
            for prop in properties
        ),
        "independently_annotated": bool(properties)
        and all(
            prop.get("independently_annotated") is True
            and str(prop.get("annotator") or "").strip()
            for prop in properties
        ),
        "notable_fact_denominator": (
            counts["notable_facts"] >= MIN_NOTABLE_FACTS
        ),
        "material_defect_denominator": (
            counts["material_defects"] >= MIN_MATERIAL_DEFECTS
        ),
        "clean_negative_controls": counts["clean_negative_controls"] > 0,
        "ambiguous_near_negatives": counts["ambiguous_near_negatives"] > 0,
    }
    return checks, counts


def audit_fixture(fixture_dir: Path, manifest: dict) -> dict:
    fixture_dir = fixture_dir.resolve()
    capture_dir = fixture_dir / "capture"
    checks, counts = _labels_ready(manifest)
    expected = manifest.get("image_manifest") or []
    expected_by_path = {
        str(item.get("path") or "").replace("\\", "/"): item
        for item in expected
    }
    actual_paths = _images(capture_dir) if capture_dir.is_dir() else []
    actual_rel = {
        path.relative_to(capture_dir).as_posix(): path for path in actual_paths
    }
    declared_subdirs = [
        str(prop.get("capture_subdir") or "").replace("\\", "/").strip("/")
        for prop in manifest.get("properties") or []
    ]
    property_capture_dirs = (
        bool(declared_subdirs)
        and len(set(declared_subdirs)) == len(declared_subdirs)
        and all(
            subdir
            and not Path(subdir).is_absolute()
            and ".." not in Path(subdir).parts
            for subdir in declared_subdirs
        )
        and all(
            any(
                relative == subdir or relative.startswith(f"{subdir}/")
                for relative in actual_rel
            )
            for subdir in declared_subdirs
        )
        and all(
            any(
                relative == subdir or relative.startswith(f"{subdir}/")
                for subdir in declared_subdirs
            )
            for relative in actual_rel
        )
    )
    safe_paths = all(
        path
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        for path in expected_by_path
    )
    hashes_match = safe_paths and bool(expected_by_path)
    if hashes_match:
        hashes_match = set(expected_by_path) == set(actual_rel)
    if hashes_match:
        hashes_match = all(
            str(expected_by_path[path].get("sha256") or "") == _sha256(source)
            for path, source in actual_rel.items()
        )
    checks.update(
        {
            "property_capture_dirs": property_capture_dirs,
            "fixture_frozen": (
                manifest.get("status") == "frozen"
                and bool(str(manifest.get("frozen_at") or "").strip())
            ),
            "image_manifest_complete": hashes_match,
        }
    )
    counts["images"] = len(actual_paths)
    errors = [
        name.replace("_", " ")
        for name, passed in checks.items()
        if not passed
    ]
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "counts": counts,
        "errors": errors,
    }


def initialise(fixture_dir: Path, property_ids: list[str]) -> Path:
    fixture_dir = fixture_dir.resolve()
    manifest_path = fixture_dir / "fixture.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    property_ids = [str(value).strip() for value in property_ids]
    if any(
        not value
        or Path(value).is_absolute()
        or len(Path(value).parts) != 1
        or value in {".", ".."}
        for value in property_ids
    ):
        raise ValueError("property IDs must be non-empty directory names")
    distinct_ids = {value.casefold() for value in property_ids}
    if len(distinct_ids) != len(property_ids):
        raise ValueError("property IDs must be distinct")
    if len(distinct_ids) < MIN_PROPERTIES:
        raise ValueError("at least two distinct external properties are required")
    (fixture_dir / "capture").mkdir(parents=True, exist_ok=True)
    properties = []
    for property_id in property_ids:
        (fixture_dir / "capture" / property_id).mkdir(parents=True, exist_ok=True)
        properties.append(
            {
                "property_id": property_id,
                "capture_subdir": property_id,
                "source_authority": "",
                "annotator": "",
                "independently_annotated": False,
                "notable_facts": [],
                "material_defects": [],
                "negative_controls": {"clean": [], "ambiguous": []},
            }
        )
    payload = {
        "schema_version": 1,
        "status": "intake",
        "frozen_at": "",
        "properties": properties,
        "image_manifest": [],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def freeze(fixture_dir: Path) -> dict:
    fixture_dir = fixture_dir.resolve()
    manifest_path = fixture_dir / "fixture.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    label_checks, counts = _labels_ready(manifest)
    missing = [name for name, passed in label_checks.items() if not passed]
    if missing:
        raise ValueError(
            "fixture labels are not freeze-ready: " + ", ".join(missing)
        )
    capture_dir = fixture_dir / "capture"
    images = _images(capture_dir)
    if not images:
        raise ValueError("fixture contains no source images")
    manifest["image_manifest"] = [
        {
            "path": path.relative_to(capture_dir).as_posix(),
            "sha256": _sha256(path),
        }
        for path in images
    ]
    manifest["frozen_at"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "frozen"
    result = audit_fixture(fixture_dir, manifest)
    if not result["ready"]:
        raise ValueError(
            "fixture cannot be frozen: " + ", ".join(result["errors"])
        )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"manifest": str(manifest_path), **result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("fixture_dir", type=Path)
    init.add_argument("--property", action="append", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("fixture_dir", type=Path)
    freeze_cmd = sub.add_parser("freeze")
    freeze_cmd.add_argument("fixture_dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "init":
        path = initialise(args.fixture_dir, args.property)
        print(path)
        return 0
    if args.command == "freeze":
        result = freeze(args.fixture_dir)
    else:
        manifest_path = args.fixture_dir / "fixture.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = audit_fixture(args.fixture_dir, manifest)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
