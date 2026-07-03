"""Shared stdlib-HTTP plumbing for the local web servers.

Two servers ride on this: the review server (docs/05 Levels 2–3,
`review.py`) and the phone capture server (M5b, `capture.py`). Both are
plain `http.server` — no framework, no npm, no websockets — and both take
browser photo uploads, so the upload contract (magic-byte-sniffed
extensions, 64 MiB cap, traversal rejection, never clobber) lives here
exactly once.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import socket
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from .ingest import IMAGE_EXTS, VIDEO_EXTS

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# Browser uploads: hard cap on one photo's decoded bytes; the request body
# cap adds base64's 4/3 inflation plus JSON envelope slack.
_UPLOAD_CAP = 64 * 1024 * 1024
_UPLOAD_BODY_CAP = _UPLOAD_CAP * 4 // 3 + 1024 * 1024
# Streamed binary uploads (/api/upload) also take walkthrough videos — the
# primary real-world capture format — which do not fit a base64 JSON body.
_VIDEO_CAP = 2 * 1024 * 1024 * 1024
_STREAM_CHUNK = 1024 * 1024


def sniff_extension(data: bytes) -> Optional[str]:
    """File extension from magic bytes only — the client's filename extension
    is never trusted. JPEG FF D8 -> .jpg; PNG 89 50 -> .png; ISO-BMFF
    ftyp with a HEIC/HEIF brand -> .heic. Anything else: None (reject)."""
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:2] == b"\x89P":
        return ".png"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand[:3] in (b"hei", b"hev") or brand in (b"mif1", b"msf1"):
            return ".heic"
    return None


_MP4_BRANDS = (b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41",
               b"mp42", b"avc1", b"mmp4", b"dash", b"M4V ", b"M4VP")


def sniff_media_extension(head: bytes) -> Optional[str]:
    """Image OR video extension from magic bytes (client filenames are never
    trusted). Images defer to sniff_extension; videos: ISO-BMFF ftyp with an
    MP4/QuickTime brand, Matroska/WebM EBML, or RIFF AVI. None = reject."""
    img = sniff_extension(head)
    if img:
        return img
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _MP4_BRANDS:
            return ".mp4"
        if brand == b"qt  ":
            return ".mov"
    if head[:4] == b"\x1aE\xdf\xa3":                 # EBML container
        return ".webm" if b"webm" in head[:64] else ".mkv"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return ".avi"
    return None


def _safe_component(name: str) -> bool:
    """One plain path component: no separators, no '..', no hidden names."""
    return bool(name) and not name.startswith(".") and ".." not in name \
        and "/" not in name and "\\" not in name and "\x00" not in name


def scan_rooms(capture_dir: Path) -> list[dict]:
    """Room subfolders of the capture dir with photo/video counts."""
    rooms: list[dict] = []
    if not capture_dir.is_dir():
        return rooms
    for d in sorted(capture_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        photos = videos = 0
        for f in d.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in IMAGE_EXTS:
                photos += 1
            elif ext in VIDEO_EXTS:
                videos += 1
        rooms.append({"name": d.name, "photos": photos, "videos": videos})
    return rooms


def store_photo(capture_dir: Path, room: str, filename: str,
                photo_b64: str) -> tuple[int, dict]:
    """The shared upload contract: validate, sniff, write UNMODIFIED bytes
    into capture/<Room>/. Returns (http_status, payload) — 200 payloads
    carry path/stored_as/sha256/bytes so the sender can verify identity.
    Callers serialise concurrent writes (hold their lock around this)."""
    room = (room or "").strip()
    filename = (filename or "").strip()
    if not room or not filename or not photo_b64:
        return 400, {"error": "room, filename and photo_b64 are required"}
    if not (_safe_component(room) and _safe_component(filename)):
        return 400, {"error": "room and filename must be plain names — no "
                              "path separators, '..' or leading dots"}
    try:
        data = base64.b64decode(photo_b64, validate=True)
    except Exception:
        return 400, {"error": "photo_b64 is not valid base64"}
    if len(data) > _UPLOAD_CAP:
        return 413, {"error": "photo exceeds the 64 MiB cap"}
    ext = sniff_extension(data)
    if ext is None:
        return 400, {"error": "unrecognised image bytes — JPEG, PNG or "
                              "HEIC only"}
    room_dir = capture_dir / room
    if room_dir.resolve().parent != capture_dir.resolve():
        return 400, {"error": "room escapes the capture folder"}
    room_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem or "photo"
    dest, k = room_dir / f"{stem}{ext}", 1
    while dest.exists():                   # never clobber an existing file
        dest = room_dir / f"{stem}-{k}{ext}"
        k += 1
    dest.write_bytes(data)                 # stored byte-for-byte as sent
    return 200, {"ok": True, "room": room, "stored_as": dest.name,
                 "path": f"{room}/{dest.name}",
                 "sha256": hashlib.sha256(data).hexdigest(),
                 "bytes": len(data)}


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no traffic actually sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class BaseHandler(BaseHTTPRequestHandler):
    """Request plumbing shared by the review and capture handlers."""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def _is_local(self) -> bool:
        return self.client_address[0] in _LOOPBACK

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    def _html(self, text: str) -> None:
        self._send(200, text.encode("utf-8"), "text/html; charset=utf-8")

    def _file(self, path: Path, ctype: str = "image/jpeg") -> None:
        if not path.is_file():
            self._err(404, "not found")
            return
        self._send(200, path.read_bytes(), ctype)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > _UPLOAD_CAP:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _upload_photo_common(self, capture_dir: Path, lock) -> Optional[dict]:
        """Run the shared upload contract for a POSTed photo. Sends the
        error response itself and returns None on failure; returns the
        (unsent) success payload so the caller can extend and send it."""
        n = int(self.headers.get("Content-Length") or 0)
        if n > _UPLOAD_BODY_CAP:
            self.close_connection = True   # body is unread; don't reuse
            self._err(413, "upload too large — photos are capped at 64 MiB")
            return None
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except ValueError:
            self._err(400, "invalid JSON body")
            return None
        with lock:
            code, payload = store_photo(capture_dir, body.get("room"),
                                        body.get("filename"),
                                        body.get("photo_b64") or "")
        if code != 200:
            self._err(code, payload["error"])
            return None
        return payload

    def _upload_stream_common(self, capture_dir: Path, lock) -> Optional[dict]:
        """Streamed binary upload (photos AND videos): raw file bytes as the
        body, room/filename in URL-encoded X-Room / X-Filename headers.
        Bytes stream to a temp file in 1 MiB chunks (the state lock is only
        held for the final no-clobber rename, never while a multi-GB video
        streams). Same guarantees as store_photo: magic-byte extension,
        traversal rejection, never clobber, bytes stored unmodified."""
        from urllib.parse import unquote
        import secrets

        room = unquote(self.headers.get("X-Room") or "").strip()
        filename = unquote(self.headers.get("X-Filename") or "").strip()
        n = int(self.headers.get("Content-Length") or 0)
        if not room or not filename or n <= 0:
            self.close_connection = True
            self._err(400, "X-Room and X-Filename headers and a non-empty "
                           "body are required")
            return None
        if not (_safe_component(room) and _safe_component(filename)):
            self.close_connection = True
            self._err(400, "room and filename must be plain names — no "
                           "path separators, '..' or leading dots")
            return None
        if n > _VIDEO_CAP:
            self.close_connection = True
            self._err(413, "upload too large — videos are capped at 2 GiB")
            return None
        room_dir = capture_dir / room
        if room_dir.resolve().parent != capture_dir.resolve():
            self.close_connection = True
            self._err(400, "room escapes the capture folder")
            return None

        head = self.rfile.read(min(n, _STREAM_CHUNK))
        ext = sniff_media_extension(head[:64])
        if ext is None:
            self.close_connection = True   # remaining body is unread
            self._err(400, "unrecognised bytes — photos (JPEG, PNG, HEIC) "
                           "or videos (MP4, MOV, MKV, WebM, AVI) only")
            return None
        is_image = ext in (".jpg", ".png", ".heic")
        if is_image and n > _UPLOAD_CAP:
            self.close_connection = True
            self._err(413, "upload too large — photos are capped at 64 MiB")
            return None

        room_dir.mkdir(parents=True, exist_ok=True)
        tmp = room_dir / f".upload-{secrets.token_hex(8)}.part"
        digest = hashlib.sha256(head)
        got = len(head)
        try:
            with open(tmp, "wb") as f:
                f.write(head)
                while got < n:
                    chunk = self.rfile.read(min(_STREAM_CHUNK, n - got))
                    if not chunk:
                        raise ConnectionError("body ended early")
                    digest.update(chunk)
                    f.write(chunk)
                    got += len(chunk)
            with lock:                     # no-clobber pick + rename only
                stem = Path(filename).stem or "upload"
                dest, k = room_dir / f"{stem}{ext}", 1
                while dest.exists():
                    dest = room_dir / f"{stem}-{k}{ext}"
                    k += 1
                tmp.rename(dest)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            self.close_connection = True
            self._err(400, f"upload failed: {e}")
            return None
        return {"ok": True, "room": room, "stored_as": dest.name,
                "path": f"{room}/{dest.name}", "kind":
                    "photo" if is_image else "video",
                "sha256": digest.hexdigest(), "bytes": got}
