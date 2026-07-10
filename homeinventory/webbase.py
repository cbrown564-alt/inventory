"""Stdlib-HTTP plumbing for the local web server (`review.py`).

Plain `http.server` — no framework, no npm, no websockets. The browser
upload contract (magic-byte-sniffed extensions, size caps, traversal
rejection, never clobber) lives here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import socket
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from .ingest import IMAGE_EXTS, VIDEO_EXTS, find_root_videos

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# Browser uploads: hard cap on one photo's bytes.
_UPLOAD_CAP = 64 * 1024 * 1024
# Streamed binary uploads (/api/upload) also take walkthrough videos — the
# primary real-world capture format.
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


# Walkthrough videos upload to the capture root (video-first journey).
WALKTHROUGH_ROOM = "__walkthrough__"


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


def scan_capture(capture_dir: Path) -> dict:
    """Capture folder summary for the upload-first UI."""
    from .videometa import probe

    walkthroughs: list[dict] = []
    root_photos: list[dict] = []
    if capture_dir.is_dir():
        for p in sorted(capture_dir.iterdir(), key=lambda item: item.name.lower()):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                root_photos.append({
                    "name": p.name,
                    "path": p.name,
                    "size": p.stat().st_size,
                    "kind": "photo",
                })
    for p in find_root_videos(capture_dir):
        meta = probe(p) or {}
        walkthroughs.append({
            "name": p.name,
            "path": p.name,
            "size": p.stat().st_size,
            "duration": meta.get("duration"),
            "kind": "walkthrough",
        })
    return {
        "rooms": scan_rooms(capture_dir),
        "walkthrough_videos": len(walkthroughs),
        "walkthrough_files": walkthroughs,
        "root_photos": len(root_photos),
        "root_photo_files": root_photos,
        "root_files": root_photos + walkthroughs,
    }


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
        self.send_header("Referrer-Policy", "no-referrer")
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

    def _file_stream(self, path: Path, ctype: str) -> None:
        """Serve a file honouring single-range requests. ``<video>`` seeking
        requires 206 partial responses; whole multi-GB walkthroughs are
        streamed in chunks, never read into memory."""
        if not path.is_file():
            self._err(404, "not found")
            return
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        m = re.fullmatch(r"bytes=(\d*)-(\d*)",
                         (self.headers.get("Range") or "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:                          # suffix range: the last N bytes
                start = max(size - int(m.group(2)), 0)
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(_STREAM_CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > _UPLOAD_CAP:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _upload_room_dir(self, capture_dir: Path, room: str,
                         filename: str) -> Optional[Path]:
        """Validate upload target; return room_dir or send 400/413 and None."""
        at_root = room == WALKTHROUGH_ROOM
        if not filename or (not room and not at_root):
            self.close_connection = True
            self._err(400, "X-Room and X-Filename headers are required")
            return None
        if at_root:
            if not _safe_component(filename):
                self.close_connection = True
                self._err(400, "filename must be a plain name")
                return None
        elif not (_safe_component(room) and _safe_component(filename)):
            self.close_connection = True
            self._err(400, "room and filename must be plain names — no "
                           "path separators, '..' or leading dots")
            return None
        room_dir = capture_dir if at_root else capture_dir / room
        if not at_root and room_dir.resolve().parent != capture_dir.resolve():
            self.close_connection = True
            self._err(400, "room escapes the capture folder")
            return None
        return room_dir

    def _upload_finalize(self, tmp: Path, room_dir: Path, filename: str,
                         ext: str, lock) -> Path:
        """No-clobber rename of a completed temp upload."""
        with lock:
            stem = Path(filename).stem or "upload"
            dest, k = room_dir / f"{stem}{ext}", 1
            while dest.exists():
                dest = room_dir / f"{stem}-{k}{ext}"
                k += 1
            tmp.rename(dest)
        return dest

    def _upload_digest(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_STREAM_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _upload_status(self, capture_dir: Path, upload_id: str) -> Optional[dict]:
        """Return the durable state of a chunked upload.

        A completed slice can reach the server just as a phone drops the
        response.  Keeping a small receipt beside an in-progress upload lets
        the browser ask what actually happened before it sends more bytes.
        This is intentionally an owner-only route (enforced by review.py),
        and exposes progress only for the supplied opaque upload id.
        """
        if not re.fullmatch(r"[\w\-]{8,64}", upload_id):
            self._err(400, "invalid upload id")
            return None
        if not capture_dir.is_dir():
            self._err(404, "no upload found")
            return None

        meta_name = f".upload-{upload_id}.meta.json"
        receipt_name = f".upload-{upload_id}.complete.json"
        metas = list(capture_dir.rglob(meta_name))
        receipts = list(capture_dir.rglob(receipt_name))
        if len(metas) + len(receipts) > 1:
            self._err(409, "ambiguous upload state")
            return None
        if receipts:
            try:
                return json.loads(receipts[0].read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                self._err(409, "upload receipt is unreadable")
                return None
        if not metas:
            self._err(404, "no upload found")
            return None

        meta_path = metas[0]
        tmp = meta_path.with_name(f".upload-{upload_id}.part")
        if not tmp.is_file():
            self._err(409, "upload state is incomplete — restart")
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            total = int(meta["total"])
        except (OSError, ValueError, KeyError, TypeError):
            self._err(409, "upload state is unreadable — restart")
            return None
        return {"ok": True, "complete": False, "received": tmp.stat().st_size,
                "total": total}

    def _upload_chunked(self, capture_dir: Path, lock, room: str,
                        filename: str, upload_id: str, offset: int,
                        total: int, n: int) -> Optional[dict]:
        """Resume-friendly chunked upload for large walkthrough videos.

        Safari/WebKit often drops single-shot XHR uploads above ~1 GiB; the
        browser sends 32 MiB slices with X-Upload-Id/Offset/Total instead."""
        if not re.fullmatch(r"[\w\-]{8,64}", upload_id):
            self.close_connection = True
            self._err(400, "X-Upload-Id must be 8–64 word characters")
            return None
        if total <= 0 or total > _VIDEO_CAP:
            self.close_connection = True
            self._err(413 if total > _VIDEO_CAP else 400,
                      "upload too large — videos are capped at 2 GiB"
                      if total > _VIDEO_CAP else "invalid X-Upload-Total")
            return None
        if offset < 0 or n <= 0 or offset + n > total:
            self.close_connection = True
            self._err(400, "chunk range exceeds declared upload size")
            return None
        room_dir = self._upload_room_dir(capture_dir, room, filename)
        if room_dir is None:
            return None
        room_dir.mkdir(parents=True, exist_ok=True)
        tmp = room_dir / f".upload-{upload_id}.part"
        meta_path = room_dir / f".upload-{upload_id}.meta.json"
        receipt_path = room_dir / f".upload-{upload_id}.complete.json"
        at_root = room == WALKTHROUGH_ROOM

        if offset == 0:
            if tmp.exists() or meta_path.exists() or receipt_path.exists():
                self.close_connection = True
                self._err(409, "upload already exists — resume it first")
                return None
            head = self.rfile.read(n)
            if len(head) != n:
                self.close_connection = True
                self._err(400, "body ended early")
                return None
            ext = sniff_media_extension(head[:64])
            if ext is None:
                self.close_connection = True
                self._err(400, "unrecognised bytes — photos (JPEG, PNG, HEIC) "
                               "or videos (MP4, MOV, MKV, WebM, AVI) only")
                return None
            if ext in (".jpg", ".png", ".heic") and total > _UPLOAD_CAP:
                self.close_connection = True
                self._err(413, "upload too large — photos are capped at 64 MiB")
                return None
            meta_path.write_text(json.dumps(
                {"total": total, "ext": ext, "filename": filename}),
                encoding="utf-8")
            with open(tmp, "wb") as f:
                f.write(head)
        else:
            if not meta_path.is_file() or not tmp.is_file():
                self.close_connection = True
                self._err(409, "no in-progress upload for this id — restart")
                return None
            if tmp.stat().st_size != offset:
                self.close_connection = True
                self._err(409, f"expected offset {tmp.stat().st_size}, "
                               f"got {offset}")
                return None
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("total") != total or meta.get("filename") != filename:
                self.close_connection = True
                self._err(409, "upload metadata does not match this file")
                return None
            ext = meta["ext"]
            with open(tmp, "ab") as f:
                got = 0
                while got < n:
                    chunk = self.rfile.read(min(_STREAM_CHUNK, n - got))
                    if not chunk:
                        self.close_connection = True
                        self._err(400, "body ended early")
                        return None
                    f.write(chunk)
                    got += len(chunk)

        if tmp.stat().st_size < total:
            return {"ok": True, "complete": False,
                    "received": tmp.stat().st_size}

        if tmp.stat().st_size != total:
            tmp.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            self.close_connection = True
            self._err(400, "upload size mismatch")
            return None
        try:
            dest = self._upload_finalize(tmp, room_dir, filename, ext, lock)
            digest = self._upload_digest(dest)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            self.close_connection = True
            self._err(400, f"upload failed: {e}")
            return None
        is_image = ext in (".jpg", ".png", ".heic")
        payload = {"ok": True, "complete": True,
                   "room": "" if at_root else room,
                   "stored_as": dest.name,
                   "path": dest.name if at_root else f"{room}/{dest.name}",
                   "kind": "photo" if is_image else "video",
                   "sha256": digest, "bytes": total}
        try:
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")
        finally:
            meta_path.unlink(missing_ok=True)
        return payload

    def _upload_stream_common(self, capture_dir: Path, lock) -> Optional[dict]:
        """Streamed binary upload (photos AND videos): raw file bytes as the
        body, room/filename in URL-encoded X-Room / X-Filename headers.
        Bytes stream to a temp file in 1 MiB chunks (the state lock is only
        held for the final no-clobber rename, never while a multi-GB video
        streams). Same guarantees as store_photo: magic-byte extension,
        traversal rejection, never clobber, bytes stored unmodified.

        Large videos use chunked mode: X-Upload-Id, X-Upload-Offset and
        X-Upload-Total accompany each slice (see _upload_chunked)."""
        from urllib.parse import unquote

        room = unquote(self.headers.get("X-Room") or "").strip()
        filename = unquote(self.headers.get("X-Filename") or "").strip()
        n = int(self.headers.get("Content-Length") or 0)
        upload_id = (self.headers.get("X-Upload-Id") or "").strip()
        offset_raw = self.headers.get("X-Upload-Offset")
        total_raw = self.headers.get("X-Upload-Total")
        if upload_id or offset_raw is not None or total_raw is not None:
            if not (upload_id and offset_raw is not None
                    and total_raw is not None):
                self.close_connection = True
                self._err(400, "chunked uploads require X-Upload-Id, "
                               "X-Upload-Offset and X-Upload-Total")
                return None
            return self._upload_chunked(
                capture_dir, lock, room, filename, upload_id,
                int(offset_raw), int(total_raw), n)

        at_root = room == WALKTHROUGH_ROOM
        if not filename or n <= 0 or (not room and not at_root):
            self.close_connection = True
            self._err(400, "X-Room and X-Filename headers and a non-empty "
                           "body are required")
            return None
        if n > _VIDEO_CAP:
            self.close_connection = True
            self._err(413, "upload too large — videos are capped at 2 GiB")
            return None
        room_dir = self._upload_room_dir(capture_dir, room, filename)
        if room_dir is None:
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
            dest = self._upload_finalize(tmp, room_dir, filename, ext, lock)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            self.close_connection = True
            self._err(400, f"upload failed: {e}")
            return None
        return {"ok": True, "room": "" if at_root else room,
                "stored_as": dest.name,
                "path": dest.name if at_root else f"{room}/{dest.name}",
                "kind":
                    "photo" if is_image else "video",
                "sha256": digest.hexdigest(), "bytes": got}
