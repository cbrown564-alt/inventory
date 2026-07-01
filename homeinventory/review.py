"""Local review server (Level 2) and multi-party share mode (Level 3).

`homeinventory review CAPTURE_DIR -o REPORT_DIR` serves a single-machine web
app over stdlib http.server — no accounts, no hosting, nothing leaves the
machine unless --share is given:

  * owner app at /            edit grades/defects, annotate defect regions on
                              photos, add missed items, re-describe a room,
                              write straight back to inventory.json
  * tenant app at /t/<token>  (--share) read-only walk-through with per-item
                              comments and a countersignature

Security model: owner routes answer only to loopback clients; tenant routes
require the random token minted at startup. Every mutation is appended to a
hash-chained acknowledgements.jsonl so the review trail is tamper-evident in
the same spirit as the photo manifest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import socket
import subprocess
import sys
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import Inventory, Item, Photo
from .integrity import sha256_file

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"

_LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReviewState:
    """Everything the handler threads share, guarded by one lock."""

    def __init__(self, capture_dir: Path, out_dir: Path,
                 backend: str = "claude", model: Optional[str] = None,
                 base_url: Optional[str] = None, share: bool = False):
        self.capture_dir = capture_dir
        self.out_dir = out_dir
        self.backend = backend
        self.model = model
        self.base_url = base_url
        self.lock = threading.Lock()
        self.tenant_token: Optional[str] = (
            secrets.token_urlsafe(16) if share else None)
        self.redescribe = {"status": "idle", "room": None, "detail": ""}

    # ---- inventory I/O -------------------------------------------------
    @property
    def inv_path(self) -> Path:
        return self.out_dir / "inventory.json"

    def load(self) -> Inventory:
        return Inventory.from_json(self.inv_path.read_text(encoding="utf-8"))

    def save(self, inv: Inventory) -> None:
        self.inv_path.write_text(inv.to_json(), encoding="utf-8")

    def rerender(self, inv: Optional[Inventory] = None) -> None:
        from .report import render
        render(inv or self.load(), self.capture_dir, self.out_dir, pdf=False)

    # ---- tamper-evident acknowledgement trail --------------------------
    @property
    def ack_path(self) -> Path:
        return self.out_dir / "acknowledgements.jsonl"

    def ack(self, actor: str, role: str, action: str,
            detail: str = "", item_id: Optional[str] = None) -> dict:
        """Append one hash-chained record; each record pins the inventory
        content hash and the previous record's hash."""
        with self.lock:
            prev = ""
            if self.ack_path.exists():
                lines = self.ack_path.read_text(encoding="utf-8").strip()
                if lines:
                    prev = json.loads(lines.rsplit("\n", 1)[-1]).get("sha256", "")
            rec = {
                "at": _now(), "actor": actor, "role": role, "action": action,
                "detail": detail, "item_id": item_id,
                "inventory_sha256": self.load().content_sha256(),
                "prev": prev,
            }
            canon = json.dumps(rec, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"))
            rec["sha256"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()
            with open(self.ack_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return rec

    # ---- photo / crop maps for the UIs ---------------------------------
    def photo_src(self, inv: Inventory) -> dict[str, str]:
        # absolute paths: the tenant app lives at /t/<token>, so relative
        # photo URLs would resolve under /t/
        out = {}
        for room in inv.rooms:
            for p in room.photos:
                if (self.out_dir / "photos" / f"{p.id}.jpg").exists():
                    out[p.id] = f"/photos/{p.id}.jpg"
        return out

    def crop_src(self, inv: Inventory) -> dict[str, str]:
        out = {}
        crops = self.out_dir / "work" / "crops"
        for room in inv.rooms:
            for it in room.items:
                if not it.crop_path:
                    continue
                name = Path(it.crop_path).name
                if (crops / name).exists():
                    out[it.id] = f"/crops/{name}"
        return out

    # ---- add a missed item ---------------------------------------------
    def add_item(self, room_name: str, name: str, description: str = "",
                 condition: Optional[str] = None,
                 photo_b64: Optional[str] = None,
                 author: str = "reviewer") -> dict:
        with self.lock:
            inv = self.load()
            room = next((r for r in inv.rooms
                         if r.name.lower() == room_name.lower()), None)
            if room is None:
                raise KeyError(f"no such room: {room_name}")

            # item id: continue the room's existing prefix sequence
            prefix, top = None, 0
            for it in room.items:
                m = re.match(r"([A-Z0-9]+)-(\d+)$", it.id or "")
                if m:
                    prefix = prefix or m.group(1)
                    top = max(top, int(m.group(2)))
            if prefix is None:
                from .merge import room_code
                used = {re.match(r"([A-Z0-9]+)-", i.id).group(1)
                        for r in inv.rooms for i in r.items
                        if re.match(r"([A-Z0-9]+)-", i.id or "")}
                prefix = room_code(room.name, used)
            item = Item(id=f"{prefix}-{top + 1:03d}", name=name,
                        description=description, condition=condition,
                        reviewed=True, added_by=author)

            if photo_b64:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                fname = f"review-added-{stamp}.jpg"
                dest = self.capture_dir / room.name / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(base64.b64decode(photo_b64))
                pid = f"P{1 + sum(len(r.photos) for r in inv.rooms):03d}"
                taken = {p.id for r in inv.rooms for p in r.photos}
                while pid in taken:  # photo numbering may have gaps
                    pid = f"P{int(pid[1:]) + 1:03d}"
                photo = Photo(id=pid, path=f"{room.name}/{fname}",
                              room=room.name, sha256=sha256_file(dest),
                              captured_at=_now(),
                              note=f"added during review by {author}")
                room.photos.append(photo)
                item.photo_ids = [pid]
                self._append_manifest_entry(photo, dest)

            room.items.append(item)
            self.save(inv)
        self.ack(author, "landlord", "add_item", name, item.id)
        with self.lock:
            self.rerender()
        return asdict(item)

    def _append_manifest_entry(self, photo: Photo, full: Path) -> None:
        mpath = self.out_dir / "manifest.json"
        if not mpath.exists():
            return
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest.setdefault("files", []).append({
            "photo_id": photo.id, "room": photo.room, "file": photo.path,
            "sha256": photo.sha256, "captured_at": photo.captured_at,
            "source_video": None, "bytes": full.stat().st_size,
        })
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    # ---- re-describe one room (subprocess, background thread) ----------
    def start_redescribe(self, room: str) -> bool:
        with self.lock:
            if self.redescribe["status"] == "running":
                return False
            self.redescribe = {"status": "running", "room": room, "detail": ""}
        cmd = [sys.executable, "-m", "homeinventory.cli", "build",
               str(self.capture_dir), "-o", str(self.out_dir),
               "--room", room, "--from-json", "--backend", self.backend, "--no-pdf"]
        if self.model:
            cmd += ["--model", self.model]
        if self.base_url:
            cmd += ["--base-url", self.base_url]

        def run():
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=1800)
                ok = proc.returncode == 0
                with self.lock:
                    self.redescribe = {
                        "status": "done" if ok else "failed", "room": room,
                        "detail": (proc.stdout if ok else
                                   (proc.stderr or proc.stdout))[-2000:],
                    }
            except Exception as e:
                with self.lock:
                    self.redescribe = {"status": "failed", "room": room,
                                       "detail": str(e)}
        threading.Thread(target=run, daemon=True).start()
        self.ack("reviewer", "landlord", "redescribe", room)
        return True


def _signature(inv: Inventory, name: str, role: str, via: str) -> dict:
    return {"role": role, "name": name, "signed_at": _now(),
            "inventory_sha256": inv.content_sha256(), "via": via}


class ReviewHandler(BaseHTTPRequestHandler):
    state: ReviewState  # set by serve()
    protocol_version = "HTTP/1.1"

    # ---- plumbing ------------------------------------------------------
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
        if n > 64 * 1024 * 1024:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _tenant_token_ok(self, token: str) -> bool:
        expected = self.state.tenant_token
        return bool(expected) and secrets.compare_digest(token, expected)

    def _render_app(self, template: str, **extra) -> str:
        st = self.state
        inv = st.load()
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        payload = {"inventory": asdict(inv),
                   "photo_src": st.photo_src(inv),
                   "crop_src": st.crop_src(inv)}
        payload.update(extra)
        return env.get_template(template).render(
            inv=inv, payload=payload,
            share_url=extra.get("share_url", ""))

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        try:
            self._route_get()
        except BrokenPipeError:
            pass
        except Exception as e:
            log.exception("GET %s failed", self.path)
            try:
                self._err(500, str(e))
            except Exception:
                pass

    def do_POST(self):
        self._mutate()

    def do_PUT(self):
        self._mutate()

    def _route_get(self):
        st = self.state
        path = self.path.split("?", 1)[0]

        m = re.fullmatch(r"/photos/(P\d+\.jpg)", path)
        if m:
            self._file(st.out_dir / "photos" / m.group(1))
            return
        m = re.fullmatch(r"/crops/([\w.\- ]+\.jpg)", path)
        if m:
            self._file(st.out_dir / "work" / "crops" / m.group(1))
            return

        # tenant routes: token is the credential, any client IP allowed
        m = re.fullmatch(r"/t/([\w\-]+)", path)
        if m:
            if not self._tenant_token_ok(m.group(1)):
                self._err(403, "invalid or expired link")
                return
            self._html(self._render_app("tenant.html.j2", token=m.group(1)))
            return
        m = re.fullmatch(r"/api/t/([\w\-]+)/inventory", path)
        if m:
            if not self._tenant_token_ok(m.group(1)):
                self._err(403, "invalid or expired link")
                return
            inv = st.load()
            self._json({"inventory": asdict(inv),
                        "photo_src": st.photo_src(inv)})
            return

        # everything below is owner-only
        if not self._is_local():
            self._err(403, "owner routes are localhost-only")
            return
        if path == "/":
            share_url = ""
            if st.tenant_token:
                share_url = f"/t/{st.tenant_token}"
            self._html(self._render_app("review.html.j2", share_url=share_url))
            return
        if path == "/report":
            self._file(st.out_dir / "inventory.html",
                       "text/html; charset=utf-8")
            return
        if path == "/api/inventory":
            inv = st.load()
            self._json({"inventory": asdict(inv),
                        "photo_src": st.photo_src(inv),
                        "crop_src": st.crop_src(inv)})
            return
        if path == "/api/redescribe":
            with st.lock:
                self._json(dict(st.redescribe))
            return
        self._err(404, "not found")

    def _mutate(self):
        st = self.state
        try:
            path = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""

            # tenant mutations -------------------------------------------
            m = re.fullmatch(r"/api/t/([\w\-]+)/comments", path)
            if m:
                if not self._tenant_token_ok(m.group(1)):
                    self._err(403, "invalid or expired link")
                    return
                self._tenant_comment(self._body())
                return
            m = re.fullmatch(r"/api/t/([\w\-]+)/sign", path)
            if m:
                if not self._tenant_token_ok(m.group(1)):
                    self._err(403, "invalid or expired link")
                    return
                self._tenant_sign(self._body())
                return

            # owner mutations --------------------------------------------
            if not self._is_local():
                self._err(403, "owner routes are localhost-only")
                return
            if path == "/api/inventory":
                body = self._body()
                inv = Inventory.from_json(json.dumps(body))  # validates
                with st.lock:
                    st.save(inv)
                    if "render=1" in query:
                        st.rerender(inv)
                st.ack(inv.inspected_by or "reviewer", "landlord",
                       "save_inventory",
                       f"{inv.reviewed_count()}/{inv.item_count()} reviewed")
                self._json({"ok": True,
                            "reviewed": inv.reviewed_count(),
                            "total": inv.item_count()})
                return
            if path == "/api/render":
                with st.lock:
                    st.rerender()
                self._json({"ok": True})
                return
            if path == "/api/items":
                b = self._body()
                if not b.get("room") or not b.get("name"):
                    self._err(400, "room and name are required")
                    return
                item = st.add_item(b["room"], b["name"],
                                   b.get("description", ""),
                                   b.get("condition"),
                                   b.get("photo_b64"),
                                   b.get("author", "reviewer"))
                self._json({"ok": True, "item": item})
                return
            if path == "/api/redescribe":
                b = self._body()
                if not b.get("room"):
                    self._err(400, "room is required")
                    return
                if not st.start_redescribe(b["room"]):
                    self._err(409, "a re-describe is already running")
                    return
                self._json({"ok": True})
                return
            if path == "/api/sign":
                b = self._body()
                name = (b.get("name") or "").strip()
                role = (b.get("role") or "landlord").strip().lower()
                if not name or role not in ("landlord", "agent"):
                    self._err(400, "name and role (landlord|agent) required")
                    return
                with st.lock:
                    inv = st.load()
                    inv.signatures.append(_signature(
                        inv, name, role, "review server (level 2)"))
                    st.save(inv)
                st.ack(name, role, "sign")
                self._json({"ok": True, "signatures": st.load().signatures})
                return
            self._err(404, "not found")
        except (ValueError, KeyError) as e:
            self._err(400, str(e))
        except BrokenPipeError:
            pass
        except Exception as e:
            log.exception("%s %s failed", self.command, self.path)
            try:
                self._err(500, str(e))
            except Exception:
                pass

    # ---- tenant actions --------------------------------------------------
    def _tenant_comment(self, b: dict):
        st = self.state
        item_id = b.get("item_id")
        text = (b.get("text") or "").strip()
        author = (b.get("author") or "tenant").strip() or "tenant"
        if not item_id or not text:
            self._err(400, "item_id and text are required")
            return
        with st.lock:
            inv = st.load()
            for room in inv.rooms:
                for it in room.items:
                    if it.id == item_id:
                        it.comments.append({"author": author, "role": "tenant",
                                            "text": text, "at": _now()})
                        st.save(inv)
                        break
                else:
                    continue
                break
            else:
                self._err(404, f"no such item: {item_id}")
                return
        st.ack(author, "tenant", "comment", text, item_id)
        self._json({"ok": True})

    def _tenant_sign(self, b: dict):
        st = self.state
        name = (b.get("name") or "").strip()
        if not name:
            self._err(400, "name is required")
            return
        with st.lock:
            inv = st.load()
            inv.signatures.append(_signature(
                inv, name, "tenant", "shared review link (level 3)"))
            st.save(inv)
        st.ack(name, "tenant", "sign", "acknowledged receipt and countersigned")
        self._json({"ok": True})


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no traffic actually sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def serve(capture_dir: Path, out_dir: Path, port: int = 8484,
          share: bool = False, backend: str = "claude",
          model: Optional[str] = None, base_url: Optional[str] = None,
          open_browser: bool = True) -> ThreadingHTTPServer:
    """Build the server (returned so tests can drive it); call
    .serve_forever() to block."""
    state = ReviewState(capture_dir, out_dir, backend=backend, model=model,
                        base_url=base_url, share=share)
    if not state.inv_path.exists():
        raise FileNotFoundError(
            f"{state.inv_path} not found — run `homeinventory build` first")

    handler = type("BoundHandler", (ReviewHandler,), {"state": state})
    host = "0.0.0.0" if share else "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.review_state = state  # type: ignore[attr-defined]

    actual_port = httpd.server_address[1]
    print(f"\nReview app:  http://127.0.0.1:{actual_port}/")
    if share:
        print(f"Tenant link: http://{_lan_ip()}:{actual_port}/t/{state.tenant_token}")
        print("  Anyone with this link can read the inventory, comment and "
              "countersign.\n  It dies with this process; restart for a new link.")
    if open_browser:
        import webbrowser
        threading.Timer(0.4, webbrowser.open,
                        args=(f"http://127.0.0.1:{actual_port}/",)).start()
    return httpd
