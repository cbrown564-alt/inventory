"""Portable, tamper-evident project evidence archives.

The hosted delivery spine needs one bounded object that can be retained,
downloaded and independently checked.  This module deliberately has no web or
storage dependency: local review, a future object-store worker and a recovery
tool can all produce the same ZIP contract.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ARCHIVE_FORMAT_VERSION = 1
_SECRET_REPORT_FILES = {"owner-pairing.json", "share.json"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if path.is_file() and not path.is_symlink():
            yield path


def build_evidence_archive(capture_dir: Path, report_dir: Path,
                           destination: Path) -> dict:
    """Write a portable ZIP and return its embedded index.

    Capability tokens are operational secrets, not evidence, and are never
    exported. Symlinks are skipped so an archive cannot escape either project
    root. The destination may live inside ``report_dir``; it is excluded to
    prevent recursive/self inclusion.
    """
    capture_dir = capture_dir.resolve()
    report_dir = report_dir.resolve()
    destination = destination.resolve()
    members: list[tuple[str, bytes]] = []

    for prefix, root in (("capture", capture_dir), ("report", report_dir)):
        for path in _files(root) or ():
            if path.resolve() == destination:
                continue
            rel = path.relative_to(root)
            if prefix == "report" and rel.as_posix() in _SECRET_REPORT_FILES:
                continue
            members.append((f"{prefix}/{rel.as_posix()}", path.read_bytes()))

    index = {
        "format": "homeinventory-evidence-archive",
        "version": ARCHIVE_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "sha256",
        "files": [
            {"path": name, "bytes": len(data), "sha256": _sha256(data)}
            for name, data in members
        ],
    }
    index_bytes = json.dumps(index, indent=2, ensure_ascii=False).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for name, data in members:
                archive.writestr(name, data)
            archive.writestr("evidence-index.json", index_bytes)
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)
    return index


def verify_evidence_archive(path: Path) -> list[str]:
    """Return human-readable integrity failures; an empty list means valid."""
    failures: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            index = json.loads(archive.read("evidence-index.json"))
            if index.get("format") != "homeinventory-evidence-archive":
                failures.append("unsupported archive format")
            if index.get("version") != ARCHIVE_FORMAT_VERSION:
                failures.append("unsupported archive version")
            for entry in index.get("files", []):
                try:
                    data = archive.read(entry["path"])
                except KeyError:
                    failures.append(f"missing: {entry.get('path', '?')}")
                    continue
                if len(data) != entry.get("bytes"):
                    failures.append(f"size mismatch: {entry['path']}")
                if _sha256(data) != entry.get("sha256"):
                    failures.append(f"hash mismatch: {entry['path']}")
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        failures.append(f"invalid archive: {exc}")
    return failures
