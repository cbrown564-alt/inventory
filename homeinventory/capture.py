"""Mobile guided capture server (M5b).

`homeinventory capture CAPTURE_DIR` binds 0.0.0.0 and prints one
token-gated URL for the phone: `http://<lan-ip>:<port>/c/<token>`. The
trust model is the review server's Level 3 --share model: the random token
minted at startup is the credential, it is printed once and dies with the
process. Every phone route — page and API — requires it; a wrong token is
403.

The page is a plain mobile HTML form-post surface: room list + creation,
the structured shot list from homeinventory/guide.py with a localStorage
tick-off tally, `<input type="file" accept="image/*"
capture="environment">` for the camera (deliberately NOT getUserMedia and
NOT a PWA — both need a TLS secure context, which a LAN token server does
not have), the webbase upload contract, and the £0 detector coverage
check ("no radiator seen in Bedroom 2"). Photos only — the M5b posture:
per-room *photos* keep evidence per-item and avoid the 1.3 GB
video-walkthrough transfer problem.

"Live checklist" means shot-list tally + local detector coverage check;
live AI capture guidance stays parked (docs/05 Level 4).
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from .ingest import IMAGE_EXTS
from .schema import Photo
from .webbase import (BaseHandler, TEMPLATES, _safe_component, lan_ip,
                      scan_rooms)

log = logging.getLogger(__name__)


class CaptureState:
    """Shared state for the capture handler threads."""

    def __init__(self, capture_dir: Path, detect_mode: str = "text",
                 det_conf: float = 0.25, device: Optional[str] = None,
                 session: Optional[str] = None,
                 use_case_key: Optional[str] = None):
        from .usecases import DEFAULT_USE_CASE, get_use_case

        self.capture_dir = capture_dir
        self.session = (session or "").strip() or None
        if self.session and not _safe_component(self.session):
            raise ValueError("session must be a plain folder name — no path "
                             "separators, '..' or leading dots")
        self.data_dir = capture_dir / self.session if self.session else capture_dir
        self.use_case = get_use_case(use_case_key or DEFAULT_USE_CASE)
        self.detect_mode = detect_mode
        self.det_conf = det_conf
        self.device = device
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(16)

    def scan(self) -> list[dict]:
        return scan_rooms(self.data_dir)

    def room_photo_count(self, room: str) -> int:
        for r in self.scan():
            if r["name"] == room:
                return r["photos"]
        return 0

    def create_room(self, name: str) -> tuple[int, dict]:
        name = (name or "").strip()
        if not _safe_component(name):
            return 400, {"error": "room name must be a plain folder name — "
                                  "no path separators, '..' or leading dots"}
        room_dir = self.data_dir / name
        if room_dir.resolve().parent != self.data_dir.resolve():
            return 400, {"error": "room escapes the capture folder"}
        with self.lock:
            room_dir.mkdir(parents=True, exist_ok=True)
        return 200, {"ok": True, "room": name, "rooms": self.scan()}

    def check_room(self, room: str) -> tuple[int, dict]:
        """£0 detector coverage check for one room's photos. Detector
        unavailable is reported as such — never a silent pass."""
        from .coverage import check_capture

        room = (room or "").strip()
        if not _safe_component(room):
            return 400, {"error": "invalid room name"}
        room_dir = self.data_dir / room
        if not room_dir.is_dir():
            return 404, {"error": f"no such room: {room}"}
        path_prefix = f"{self.session}/{room}" if self.session else room
        photos = [Photo(id=f"C{i:03d}", path=f"{path_prefix}/{f.name}", room=room)
                  for i, f in enumerate(sorted(room_dir.iterdir()))
                  if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        if not photos:
            return 200, {"status": "no_photos", "room": room, "gaps": [],
                         "detail": "no photos in this room yet"}
        report = check_capture(self.data_dir, {room: photos},
                               conf=self.det_conf, device=self.device,
                               mode=self.detect_mode)
        if report is None:
            return 200, {"status": "unavailable", "room": room,
                         "detail": "detector unavailable on this machine — "
                                   "coverage NOT checked (this is not a "
                                   "pass); pip install homeinventory[detect]"}
        return 200, {"status": "checked", "room": room,
                     "photos": len(photos), "gaps": report.get(room, [])}


class CaptureHandler(BaseHandler):
    """Every route is token-gated; there are no ungated pages."""

    state: CaptureState  # set by serve_capture()

    def _token_ok(self, token: str) -> bool:
        return secrets.compare_digest(token, self.state.token)

    def _render_page(self) -> str:
        from .guide import TIPS
        st = self.state
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=True)
        return env.get_template("capture.html.j2").render(
            token=st.token, rooms=st.scan(),
            per_room_shots=st.use_case.per_room_shots,
            whole_property_shots=st.use_case.whole_property_shots,
            tips=TIPS)

    def do_GET(self):
        try:
            path = self.path.split("?", 1)[0]
            m = re.fullmatch(r"/c/([\w\-]+)", path)
            if m:
                if not self._token_ok(m.group(1)):
                    self._err(403, "invalid or expired capture link")
                    return
                self._html(self._render_page())
                return
            m = re.fullmatch(r"/api/c/([\w\-]+)/progress", path)
            if m:
                if not self._token_ok(m.group(1)):
                    self._err(403, "invalid or expired capture link")
                    return
                rooms = self.state.scan()
                self._json({"rooms": rooms,
                            "total_photos": sum(r["photos"] for r in rooms)})
                return
            self._err(404, "not found — the capture link is /c/<token>")
        except BrokenPipeError:
            pass
        except Exception as e:
            log.exception("GET %s failed", self.path)
            try:
                self._err(500, str(e))
            except Exception:
                pass

    def do_POST(self):
        st = self.state
        try:
            path = self.path.split("?", 1)[0]
            m = re.fullmatch(r"/api/c/([\w\-]+)/(rooms|photos|check)", path)
            if not m:
                self._err(404, "not found")
                return
            if not self._token_ok(m.group(1)):
                self._err(403, "invalid or expired capture link")
                return
            action = m.group(2)
            if action == "photos":
                payload = self._upload_photo_common(st.data_dir, st.lock)
                if payload is None:
                    return
                # the phone checklist shows a per-room running tally
                payload["room_photos"] = st.room_photo_count(payload["room"])
                self._json(payload)
                return
            body = self._body()
            if action == "rooms":
                code, payload = st.create_room(body.get("name") or "")
                self._json(payload, code)
                return
            if action == "check":
                code, payload = st.check_room(body.get("room") or "")
                self._json(payload, code)
                return
        except (ValueError, KeyError) as e:
            self._err(400, str(e))
        except BrokenPipeError:
            pass
        except Exception as e:
            log.exception("POST %s failed", self.path)
            try:
                self._err(500, str(e))
            except Exception:
                pass


def serve_capture(capture_dir: Path, port: int = 8485,
                  detect_mode: str = "text", det_conf: float = 0.25,
                  device: Optional[str] = None,
                  session: Optional[str] = None,
                  use_case_key: Optional[str] = None) -> ThreadingHTTPServer:
    """Build the capture server (returned so tests can drive it); call
    .serve_forever() to block. Always binds 0.0.0.0 — the phone is the
    client — with every route gated by the printed token."""
    capture_dir.mkdir(parents=True, exist_ok=True)
    state = CaptureState(capture_dir, detect_mode=detect_mode,
                         det_conf=det_conf, device=device,
                         session=session, use_case_key=use_case_key)
    state.data_dir.mkdir(parents=True, exist_ok=True)
    handler = type("BoundCaptureHandler", (CaptureHandler,), {"state": state})
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    httpd.capture_state = state  # type: ignore[attr-defined]

    actual_port = httpd.server_address[1]
    # flush: the link is the product — it must appear even when stdout is
    # redirected (block-buffered) rather than a TTY
    dest = f"{capture_dir}/{state.session}/" if state.session else f"{capture_dir}/"
    print(f"\nPhone capture link: http://{lan_ip()}:{actual_port}/c/{state.token}",
          flush=True)
    print(f"  Uploads land in {dest}<Room>/  "
          f"({state.use_case.display_name} shot list).", flush=True)
    print("  Open it on your phone (same Wi-Fi). Anyone with the link can "
          "add photos; it dies with this process — restart for a new link.",
          flush=True)
    return httpd
