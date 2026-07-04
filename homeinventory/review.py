"""Local review server (Level 2) and multi-party share mode (Level 3).

`homeinventory review CAPTURE_DIR -o REPORT_DIR` serves a single-machine web
app over stdlib http.server — no accounts, no hosting, nothing leaves the
machine unless --share is given:

  * owner app at /            edit grades/defects, annotate defect regions on
                              photos, add missed items, re-describe a room,
                              write straight back to inventory.json
  * tenant app at /t/<token>  (--share) read-only walk-through with per-item
                              comments and a countersignature

Multi-session projects (e.g. deepclean before/after) add ``project.json``,
per-session dirs under ``OUT/<session>/``, prefix routing at ``/s/<key>/``,
and a browser-driven compare at ``/compare/``.

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
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Server plumbing + the single copy of the browser-upload contract live in
# webbase (extracted for M5b so the phone capture server reuses them
# verbatim). sniff_extension/_safe_component stay importable from here.
from .webbase import (TEMPLATES, BaseHandler, _safe_component,  # noqa: F401
                      lan_ip as _lan_ip, scan_rooms, sniff_extension)
from .schema import Inventory, Item, Photo, cover_value
from .integrity import sha256_file
from .usecases import DEFAULT_USE_CASE, REGISTRY, get_use_case, use_case_for
from .usecases.base import UseCase

log = logging.getLogger(__name__)

# Backend default models, mirrored from describe.get_backend so the UI can
# name what a confirmed build/redescribe would actually run (spend guard:
# no paid backend without a per-request confirm naming it).
_BACKEND_DEFAULT_MODEL = {"claude": "claude-opus-4-8", "openai": "gpt-4.1-mini",
                          "local": "qwen3.5:9b"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectState:
    """Project-level state: use case, compare job, session map."""

    def __init__(self, capture_dir: Path, out_dir: Path,
                 backend: str = "claude", model: Optional[str] = None,
                 base_url: Optional[str] = None, share: bool = False,
                 no_detect: bool = False, use_case: Optional[str] = None):
        self.capture_dir = capture_dir
        self.out_dir = out_dir
        self.backend = backend
        self.model = model
        self.base_url = base_url
        self.no_detect = no_detect
        self.use_case = use_case
        self.lock = threading.Lock()
        self.tenant_token: Optional[str] = (
            secrets.token_urlsafe(16) if share else None)
        self.compare = {"status": "idle", "detail": "", "cmd": None}
        self.sessions: dict[str, SessionState] = {}
        self._init_sessions()

    @property
    def project_path(self) -> Path:
        return self.out_dir / "project.json"

    @property
    def legacy_inv_path(self) -> Path:
        return self.out_dir / "inventory.json"

    @property
    def is_legacy(self) -> bool:
        """Root inventory.json — single-session tenancy layout, unchanged."""
        return self.legacy_inv_path.is_file()

    @property
    def is_multi(self) -> bool:
        if self.is_legacy:
            return False
        if self.project_path.is_file():
            return len(self.uc.sessions) > 1
        return False

    @property
    def compare_dir(self) -> Path:
        return self.out_dir / "compare"

    @property
    def backend_label(self) -> str:
        if self.backend == "offline":
            return "offline (no AI)"
        model = self.model or _BACKEND_DEFAULT_MODEL.get(self.backend,
                                                         "default model")
        return f"{self.backend} ({model})"

    @property
    def compare_backend(self) -> str:
        """Compare CLI accepts openai|offline; map review backends."""
        return "offline" if self.backend == "offline" else "openai"

    def _resolve_use_case_key(self) -> str:
        if self.project_path.exists():
            try:
                data = json.loads(self.project_path.read_text(encoding="utf-8"))
                key = data.get("use_case")
                if key:
                    return key
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        if self.use_case:
            return self.use_case
        return DEFAULT_USE_CASE

    def _root_session(self) -> SessionState:
        """Single-session state rooted at capture_dir / out_dir."""
        for s in self.sessions.values():
            if s.out_dir.resolve() == self.out_dir.resolve():
                return s
        spec = get_use_case(self._resolve_use_case_key()).sessions[0]
        st = SessionState(self, spec.key, self.capture_dir, self.out_dir,
                          label=spec.label)
        self.sessions[spec.key] = st
        return st

    def _init_sessions(self) -> None:
        self.sessions.clear()
        if self.is_multi:
            uc = self.uc
            for spec in uc.sessions:
                cap = self.capture_dir / spec.key
                out = self.out_dir / spec.key
                self.sessions[spec.key] = SessionState(
                    self, spec.key, cap, out, label=spec.label)
        else:
            self._root_session()

    def session(self, key: Optional[str] = None) -> SessionState:
        if not self.is_multi:
            return self._root_session()
        if key is None or key not in self.sessions:
            raise KeyError(key or "session")
        return self.sessions[key]

    @property
    def uc(self) -> UseCase:
        """Resolve profile: inventory.json → project.json → CLI flag → tenancy."""
        if self.is_legacy:
            return use_case_for(self._root_session().load())
        if self.project_path.exists():
            try:
                data = json.loads(self.project_path.read_text(encoding="utf-8"))
                key = data.get("use_case")
                if key:
                    return get_use_case(key)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        if self.use_case:
            return get_use_case(self.use_case)
        return get_use_case(DEFAULT_USE_CASE)

    def any_built(self) -> bool:
        return any(s.inv_path.exists() for s in self.sessions.values())

    def all_sessions_built(self) -> bool:
        if not self.is_multi:
            return False
        return all(s.inv_path.exists() for s in self.sessions.values())

    def create_project(self, use_case_key: str) -> None:
        if self.any_built():
            raise RuntimeError("project is locked after the first build")
        if self.project_path.exists():
            data = json.loads(self.project_path.read_text(encoding="utf-8"))
            if data.get("use_case") == use_case_key:
                return
            raise RuntimeError("project.json already exists")
        uc = get_use_case(use_case_key)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.project_path.write_text(json.dumps(
            {"version": 1, "use_case": use_case_key}, indent=2),
            encoding="utf-8")
        if len(uc.sessions) > 1:
            for spec in uc.sessions:
                (self.capture_dir / spec.key).mkdir(parents=True, exist_ok=True)
                (self.out_dir / spec.key).mkdir(parents=True, exist_ok=True)
        self.use_case = use_case_key
        self._init_sessions()

    def _compare_flags(self) -> list[str]:
        flags = ["--backend", self.compare_backend, "--no-pdf"]
        if self.model and self.compare_backend == "openai":
            flags += ["--model", self.model]
        if self.base_url and self.compare_backend == "openai":
            flags += ["--base-url", self.base_url]
        key = self.uc.key
        if key != DEFAULT_USE_CASE:
            flags += ["--use-case", key]
        return flags

    def _busy(self) -> bool:
        if self.compare["status"] == "running":
            return True
        return any(s._session_busy() for s in self.sessions.values())

    def start_compare(self) -> bool:
        if not self.is_multi or not self.all_sessions_built():
            return False
        keys = [s.key for s in self.uc.sessions]
        before_dir = self.out_dir / keys[0]
        after_dir = self.out_dir / keys[1]
        with self.lock:
            if self._busy():
                return False
            cmd = [sys.executable, "-m", "homeinventory.cli", "compare",
                   str(before_dir), str(after_dir),
                   "-o", str(self.compare_dir)]
            cmd += self._compare_flags()
            self.compare = {"status": "running", "detail": "", "cmd": cmd}

        def run():
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=3600)
                ok = proc.returncode == 0
                with self.lock:
                    self.compare = {
                        "status": "done" if ok else "failed",
                        "detail": (proc.stdout if ok else
                                   (proc.stderr or proc.stdout))[-2000:],
                        "cmd": cmd,
                    }
            except Exception as e:
                with self.lock:
                    self.compare = {"status": "failed", "detail": str(e),
                                    "cmd": cmd}
        threading.Thread(target=run, daemon=True).start()
        return True

    def session_status(self) -> list[dict]:
        out = []
        for spec in self.uc.sessions:
            st = self.sessions[spec.key]
            built = st.inv_path.exists()
            out.append({
                "key": spec.key, "label": spec.label, "built": built,
                "prefix": st.route_prefix,
                "rooms": len(st.scan_capture()) if not built else None,
            })
        return out

    def followup_session(self) -> SessionState:
        """Session the counterparty reviews — the last session in the profile."""
        return self.session(self.uc.sessions[-1].key)


class SessionState:
    """Per-session review state — today's ReviewState fields."""

    def __init__(self, project: ProjectState, key: str,
                 capture_dir: Path, out_dir: Path,
                 label: str = ""):
        self.project = project
        self.key = key
        self.capture_dir = capture_dir
        self.out_dir = out_dir
        self.label = label
        self.redescribe = {"status": "idle", "room": None, "detail": ""}
        self.build = {"status": "idle", "detail": "", "cmd": None}
        self.pdf = {"status": "idle", "detail": ""}
        self._last_save_ack = 0.0
        self._last_save_counts: Optional[tuple[int, int]] = None

    @property
    def lock(self):
        return self.project.lock

    @property
    def backend(self) -> str:
        return self.project.backend

    @property
    def model(self) -> Optional[str]:
        return self.project.model

    @property
    def base_url(self) -> Optional[str]:
        return self.project.base_url

    @property
    def no_detect(self) -> bool:
        return self.project.no_detect

    @property
    def use_case(self) -> Optional[str]:
        return self.project.use_case

    @property
    def tenant_token(self) -> Optional[str]:
        return self.project.tenant_token

    @property
    def route_prefix(self) -> str:
        if self.project.is_multi:
            return f"/s/{self.key}"
        return ""

    @property
    def uc(self) -> UseCase:
        return self.project.uc

    @property
    def backend_label(self) -> str:
        return self.project.backend_label

    def scan_capture(self) -> list[dict]:
        return scan_rooms(self.capture_dir)

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

    @property
    def ack_path(self) -> Path:
        return self.out_dir / "acknowledgements.jsonl"

    def ack(self, actor: str, role: str, action: str,
            detail: str = "", item_id: Optional[str] = None) -> dict:
        with self.lock:
            prev = ""
            if self.ack_path.exists():
                lines = self.ack_path.read_text(encoding="utf-8").strip()
                if lines:
                    prev = json.loads(lines.rsplit("\n", 1)[-1]).get("sha256", "")
            rec = {
                "at": _now(), "actor": actor, "role": role, "action": action,
                "detail": detail, "item_id": item_id,
                "inventory_sha256": (self.load().content_sha256()
                                     if self.inv_path.exists() else ""),
                "prev": prev,
            }
            canon = json.dumps(rec, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":"))
            rec["sha256"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()
            with open(self.ack_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return rec

    def photo_src(self, inv: Inventory) -> dict[str, str]:
        prefix = self.route_prefix
        out = {}
        for room in inv.rooms:
            for p in room.photos:
                if (self.out_dir / "photos" / f"{p.id}.jpg").exists():
                    out[p.id] = f"{prefix}/photos/{p.id}.jpg"
        return out

    def crop_src(self, inv: Inventory) -> dict[str, str]:
        prefix = self.route_prefix
        out = {}
        crops = self.out_dir / "work" / "crops"
        for room in inv.rooms:
            for it in room.items:
                if not it.crop_path:
                    continue
                name = Path(it.crop_path).name
                if (crops / name).exists():
                    out[it.id] = f"{prefix}/crops/{name}"
        return out

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
                while pid in taken:
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
        self.ack(author, self.uc.owner_role.key, "add_item", name, item.id)
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

    def _session_busy(self) -> bool:
        return (self.redescribe["status"] == "running"
                or self.build["status"] == "running")

    def _busy(self) -> bool:
        return self.project._busy()

    def start_redescribe(self, room: str) -> bool:
        with self.lock:
            if self._busy():
                return False
            self.redescribe = {"status": "running", "room": room, "detail": ""}
        cmd = [sys.executable, "-m", "homeinventory.cli", "build",
               str(self.capture_dir), "-o", str(self.out_dir),
               "--room", room, "--from-json", "--backend", self.backend, "--no-pdf"]
        cmd += self._build_flags()

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
        self.ack("reviewer", self.uc.owner_role.key, "redescribe", room)
        return True

    def _build_flags(self) -> list[str]:
        flags: list[str] = []
        if self.no_detect:
            flags.append("--no-detect")
        if self.model:
            flags += ["--model", self.model]
        if self.base_url:
            flags += ["--base-url", self.base_url]
        key = self.uc.key
        if key != DEFAULT_USE_CASE:
            flags += ["--use-case", key]
        return flags

    def start_build(self) -> bool:
        with self.lock:
            if self._busy():
                return False
            cmd = [sys.executable, "-m", "homeinventory.cli", "build",
                   str(self.capture_dir), "-o", str(self.out_dir),
                   "--backend", self.backend, "--no-pdf"]
            if self.inv_path.exists():
                cmd.append("--from-json")
            cmd += self._build_flags()
            self.build = {"status": "running", "detail": "", "cmd": cmd}

        def run():
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=3600)
                ok = proc.returncode == 0
                with self.lock:
                    self.build = {
                        "status": "done" if ok else "failed",
                        "detail": (proc.stdout if ok else
                                   (proc.stderr or proc.stdout))[-2000:],
                        "cmd": cmd,
                    }
            except Exception as e:
                with self.lock:
                    self.build = {"status": "failed", "detail": str(e),
                                  "cmd": cmd}
        threading.Thread(target=run, daemon=True).start()
        self.ack("reviewer", self.uc.owner_role.key, "build",
                 f"backend={self.backend} no_detect={self.no_detect}")
        return True

    def start_pdf(self) -> bool:
        """PDF export as a background job (WeasyPrint runs outside the lock)."""
        with self.lock:
            if self.pdf["status"] == "running":
                return False
            self.pdf = {"status": "running", "detail": ""}

        def run():
            try:
                from .report import import_weasyprint, render
                weasyprint = import_weasyprint()
                with self.lock:
                    inv = self.load()
                    render(inv, self.capture_dir, self.out_dir, pdf=False)
                    html_text = (self.out_dir / "inventory.html").read_text(
                        encoding="utf-8")
                pdf_path = self.out_dir / "inventory.pdf"
                weasyprint.HTML(string=html_text,
                                base_url=str(self.out_dir)).write_pdf(
                                    str(pdf_path))
                with self.lock:
                    self.pdf = {"status": "done", "detail": pdf_path.name}
            except Exception as e:
                with self.lock:
                    self.pdf = {"status": "failed", "detail": str(e)}
        threading.Thread(target=run, daemon=True).start()
        self.ack("reviewer", self.uc.owner_role.key, "export_pdf")
        return True


# Back-compat alias — single-session tests and callers use ReviewState
ReviewState = SessionState


def _signature(inv: Inventory, name: str, role: str, via: str) -> dict:
    return {"role": role, "name": name, "signed_at": _now(),
            "inventory_sha256": inv.content_sha256(), "via": via}


class ReviewHandler(BaseHandler):
    """Review/tenant routes; request plumbing inherited from webbase."""

    project: ProjectState  # set by serve()

    def _tenant_token_ok(self, token: str) -> bool:
        expected = self.project.tenant_token
        return bool(expected) and secrets.compare_digest(token, expected)

    def _resolve_path(self, path: str) -> tuple[Optional[str], str, bool]:
        """Return (session_key, subpath, tenant_compare_share).

        *session_key* is None for bare single-session routes; ``__legacy__``
        is normalised away.  *tenant_compare_share* is True for read-only
        ``/t/<token>/compare/…`` routes.
        """
        m = re.fullmatch(r"/t/([\w\-]+)/compare(/.*)?", path)
        if m and self._tenant_token_ok(m.group(1)):
            rest = m.group(2) or "/"
            return None, rest, True
        if m and not self._tenant_token_ok(m.group(1)):
            return None, path, False  # invalid token handled by caller

        m = re.fullmatch(r"/s/([\w\-]+)(/.*)?", path)
        if m:
            return m.group(1), m.group(2) or "/", False
        if self.project.is_multi:
            return None, path, False
        return None, path, False

    def _session_for(self, session_key: Optional[str]) -> SessionState:
        if self.project.is_multi:
            if session_key is None:
                raise KeyError("session")
            return self.project.session(session_key)
        return self.project.session()

    def _review_payload(self, st: SessionState, inv: Inventory, **extra) -> dict:
        uc = st.uc
        roles: dict = {
            "owner": {"key": uc.owner_role.key, "label": uc.owner_role.label},
            "counterparty": {"key": uc.counterparty_role.key,
                             "label": uc.counterparty_role.label},
        }
        if uc.agent_role:
            roles["agent"] = {"key": uc.agent_role.key,
                              "label": uc.agent_role.label}
        payload = {
            "inventory": asdict(inv),
            "photo_src": st.photo_src(inv),
            "crop_src": st.crop_src(inv),
            "backend": st.backend,
            "backend_label": st.backend_label,
            "use_case": uc.key,
            "roles": roles,
            "signing_roles": list(uc.signing_role_keys),
            "cover_fields": [
                {"name": f.name, "label": f.label, "placeholder": f.placeholder,
                 "value": cover_value(inv, f)}
                for f in uc.cover_fields
            ],
            "share": {
                "link_noun": uc.share_page.link_noun,
                "kicker": uc.share_page.kicker,
                "howto": uc.share_page.howto,
                "sign_bar": uc.share_page.sign_bar,
                "placeholder": uc.share_page.placeholder,
            },
        }
        payload.update(extra)
        return payload

    def _render_app(self, st: SessionState, template: str, **extra) -> str:
        inv = st.load()
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        return env.get_template(template).render(
            inv=inv, payload=self._review_payload(st, inv, **extra),
            share_url=extra.get("share_url", ""))

    def _render_start(self, st: SessionState, *, show_picker: bool | None = None) -> str:
        proj = self.project
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        if show_picker is None:
            show_picker = (not proj.project_path.exists() and not proj.is_legacy
                           and not st.inv_path.exists())
        picker = show_picker
        return env.get_template("start.html.j2").render(
            rooms=st.scan_capture(), backend=st.backend,
            backend_label=st.backend_label,
            capture_dir=str(st.capture_dir),
            has_inventory=st.inv_path.exists(),
            use_case=proj.uc.key,
            use_case_label=proj.uc.display_name,
            show_picker=picker,
            use_cases=[{"key": u.key, "name": u.display_name,
                        "description": u.description}
                       for u in REGISTRY.values()],
            route_prefix=st.route_prefix)

    def _render_project(self) -> str:
        proj = self.project
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        compare_ready = proj.all_sessions_built()
        compare_built = (proj.compare_dir / "compare.html").is_file()
        return env.get_template("project.html.j2").render(
            use_case=proj.uc.key,
            use_case_label=proj.uc.display_name,
            backend_label=proj.backend_label,
            backend=proj.backend,
            sessions=proj.session_status(),
            compare_ready=compare_ready,
            compare_built=compare_built,
            compare_running=proj.compare["status"] == "running")

    def _serve_compare(self, subpath: str, share: bool = False) -> None:
        proj = self.project
        base = proj.compare_dir.resolve()
        if subpath in ("", "/"):
            html = base / "compare.html"
            if not html.is_file():
                self._err(404, "compare report not built yet")
                return
            self._file(html, "text/html; charset=utf-8")
            return
        rel = subpath.lstrip("/")
        if ".." in rel or rel.startswith("/"):
            self._err(400, "invalid path")
            return
        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            self._err(404, "not found")
            return
        if not target.is_file():
            self._err(404, "not found")
            return
        ctype = "application/pdf" if target.suffix == ".pdf" else \
            "application/json" if target.suffix == ".json" else \
            "image/jpeg" if target.suffix == ".jpg" else \
            "text/html; charset=utf-8" if target.suffix == ".html" else \
            "application/octet-stream"
        self._file(target, ctype)

    def _redirect(self, location: str) -> None:
        self.send_response(301)
        self.send_header("Location", location)
        self.end_headers()

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
        proj = self.project
        raw = self.path.split("?", 1)[0]

        # share compare (read-only, any client)
        m = re.fullmatch(r"/t/([\w\-]+)/compare(/.*)?", raw)
        if m:
            if not self._tenant_token_ok(m.group(1)):
                self._err(403, "invalid or expired link")
                return
            sub = m.group(2) or "/"
            if sub == "":
                self._redirect(f"/t/{m.group(1)}/compare/")
                return
            self._serve_compare(sub, share=True)
            return

        session_key, path, _ = self._resolve_path(raw)

        def _serve_session_assets(st: SessionState, subpath: str) -> bool:
            m = re.fullmatch(r"/photos/(P\d+\.jpg)", subpath)
            if m:
                self._file(st.out_dir / "photos" / m.group(1))
                return True
            m = re.fullmatch(r"/photos/print/(P\d+\.jpg)", subpath)
            if m:
                self._file(st.out_dir / "photos" / "print" / m.group(1))
                return True
            m = re.fullmatch(r"/crops/([\w.\- ]+\.jpg)", subpath)
            if m:
                self._file(st.out_dir / "work" / "crops" / m.group(1))
                return True
            return False

        # tenant routes (single- or multi-session)
        m = re.fullmatch(r"/t/([\w\-]+)", path)
        if m:
            if not self._tenant_token_ok(m.group(1)):
                self._err(403, "invalid or expired link")
                return
            st = proj.followup_session() if proj.is_multi else proj.session()
            self._html(self._render_app(st, "tenant.html.j2", token=m.group(1)))
            return
        m = re.fullmatch(r"/api/t/([\w\-]+)/inventory", path)
        if m:
            if not self._tenant_token_ok(m.group(1)):
                self._err(403, "invalid or expired link")
                return
            st = proj.followup_session() if proj.is_multi else proj.session()
            inv = st.load()
            self._json({"inventory": asdict(inv),
                        "photo_src": st.photo_src(inv)})
            return

        st: Optional[SessionState] = None
        if not proj.is_multi:
            if _serve_session_assets(proj.session(), path):
                return
        elif session_key:
            try:
                st = self._session_for(session_key)
            except KeyError:
                self._err(404, "not found")
                return
            if _serve_session_assets(st, path):
                return

        # project-level compare (owner or share handled above)
        if path == "/compare":
            self._redirect("/compare/")
            return
        if path == "/compare/" or path.startswith("/compare/"):
            if not self._is_local() and not path.startswith("/t/"):
                self._err(403, "owner routes are localhost-only")
                return
            sub = path[len("/compare"):] if path.startswith("/compare") else "/"
            self._serve_compare(sub)
            return

        if path == "/api/compare":
            if not self._is_local():
                self._err(403, "owner routes are localhost-only")
                return
            with proj.lock:
                self._json(dict(proj.compare))
            return

        if not self._is_local():
            self._err(403, "owner routes are localhost-only")
            return

        if path == "/" and proj.is_multi and session_key is None:
            self._html(self._render_project())
            return

        if st is None:
            st = proj.session()

        if path == "/":
            if not st.inv_path.exists():
                self._html(self._render_start(st))
                return
            share_url = ""
            if st.tenant_token:
                share_url = f"{st.route_prefix}/t/{st.tenant_token}" \
                    if proj.is_multi else f"/t/{st.tenant_token}"
            self._html(self._render_app(st, "review.html.j2", share_url=share_url))
            return
        if path == "/start":
            self._html(self._render_start(st, show_picker=False))
            return
        if path == "/pdf":
            self._file(st.out_dir / "inventory.pdf", "application/pdf")
            return
        if path in ("/report", "/issue"):
            name = "inventory.html" if path == "/report" else \
                "inventory-issue.html"
            html = st.out_dir / name
            with st.lock:
                if st.inv_path.exists() and (
                        not html.exists()
                        or html.stat().st_mtime < st.inv_path.stat().st_mtime):
                    st.rerender()
            self._file(html, "text/html; charset=utf-8")
            return
        if path == "/api/build":
            with st.lock:
                self._json(dict(st.build))
            return
        if path == "/api/pdf":
            with st.lock:
                self._json(dict(st.pdf))
            return
        if path == "/api/rooms":
            self._json({"rooms": st.scan_capture()})
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
        proj = self.project
        try:
            raw = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            session_key, path, _ = self._resolve_path(raw)

            m = re.fullmatch(r"/api/t/([\w\-]+)/comments", path)
            if m:
                if not self._tenant_token_ok(m.group(1)):
                    self._err(403, "invalid or expired link")
                    return
                st = proj.followup_session() if proj.is_multi else proj.session()
                self._tenant_comment(st, self._body())
                return
            m = re.fullmatch(r"/api/t/([\w\-]+)/sign", path)
            if m:
                if not self._tenant_token_ok(m.group(1)):
                    self._err(403, "invalid or expired link")
                    return
                st = proj.followup_session() if proj.is_multi else proj.session()
                self._tenant_sign(st, self._body())
                return

            if not self._is_local():
                self._err(403, "owner routes are localhost-only")
                return

            if path == "/api/project" and session_key is None:
                b = self._body()
                key = (b.get("use_case") or "").strip()
                if key not in REGISTRY:
                    self._err(400, f"use_case must be one of: "
                                   f"{sorted(REGISTRY)}")
                    return
                try:
                    proj.create_project(key)
                except RuntimeError as e:
                    self._err(409, str(e))
                    return
                self._json({"ok": True, "use_case": key,
                            "multi": proj.is_multi})
                return

            if path == "/api/compare" and session_key is None:
                b = self._body()
                confirm = proj.compare_backend
                if (b.get("confirm") or "") != confirm:
                    self._err(400, "compare must be confirmed with the "
                                   f"configured backend name ({confirm!r})"
                                   " in {\"confirm\": ...}")
                    return
                if not proj.all_sessions_built():
                    self._err(400, "both sessions must be built before compare")
                    return
                if not proj.start_compare():
                    self._err(409, "a build, re-describe or compare is already running")
                    return
                self._json({"ok": True, "status": "running"})
                return

            if session_key is None:
                if proj.is_multi:
                    self._err(404, "not found")
                    return
                st = proj.session()
            else:
                try:
                    st = self._session_for(session_key)
                except KeyError:
                    self._err(404, "not found")
                    return

            if path == "/api/photos":
                self._upload_photo(st)
                return
            if path == "/api/upload":
                payload = self._upload_stream_common(st.capture_dir, st.lock)
                if payload is None:
                    return
                st.ack("reviewer", st.uc.owner_role.key, "upload_media",
                       payload["path"])
                self._json(payload)
                return
            if path == "/api/build":
                b = self._body()
                if (b.get("confirm") or "") != st.backend:
                    self._err(400, "build must be confirmed with the "
                                   f"configured backend name ({st.backend!r})"
                                   " in {\"confirm\": ...}")
                    return
                if not st.start_build():
                    self._err(409, "a build or re-describe is already running")
                    return
                self._json({"ok": True, "status": "running"})
                return
            if path == "/api/pdf":
                try:
                    from .report import import_weasyprint
                    import_weasyprint()
                except Exception:
                    self._err(503, "PDF export needs WeasyPrint — "
                                   "pip install homeinventory[pdf]")
                    return
                if not st.start_pdf():
                    self._err(409, "a PDF export is already running")
                    return
                self._json({"ok": True, "status": "running"})
                return
            if path == "/api/inventory":
                body = self._body()
                inv = Inventory.from_json(json.dumps(body))
                with st.lock:
                    st.save(inv)
                    if "render=1" in query:
                        st.rerender(inv)
                counts = (inv.reviewed_count(), inv.item_count())
                autosave = "autosave=1" in query
                if (not autosave or counts != st._last_save_counts
                        or time.time() - st._last_save_ack > 300):
                    st.ack(inv.inspected_by or "reviewer", st.uc.owner_role.key,
                           "save_inventory",
                           f"{counts[0]}/{counts[1]} reviewed"
                           + (" (autosave)" if autosave else ""))
                    st._last_save_ack = time.time()
                    st._last_save_counts = counts
                self._json({"ok": True,
                            "reviewed": counts[0], "total": counts[1]})
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
                if (b.get("confirm") or "") != st.backend:
                    self._err(400, "re-describe must be confirmed with the "
                                   f"configured backend name ({st.backend!r})"
                                   " in {\"confirm\": ...}")
                    return
                if not st.start_redescribe(b["room"]):
                    self._err(409, "a build or re-describe is already running")
                    return
                self._json({"ok": True})
                return
            if path == "/api/sign":
                b = self._body()
                name = (b.get("name") or "").strip()
                role = (b.get("role") or st.uc.owner_role.key).strip().lower()
                allowed = st.uc.signing_role_keys
                if not name or role not in allowed:
                    self._err(400, "name and role ("
                                   + "|".join(allowed) + ") required")
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

    def _upload_photo(self, st: SessionState):
        payload = self._upload_photo_common(st.capture_dir, st.lock)
        if payload is None:
            return
        st.ack("reviewer", st.uc.owner_role.key, "upload_photo", payload["path"])
        self._json(payload)

    def _tenant_comment(self, st: SessionState, b: dict):
        item_id = b.get("item_id")
        text = (b.get("text") or "").strip()
        author = (b.get("author") or st.uc.counterparty_role.key).strip() or \
            st.uc.counterparty_role.key
        cp_role = st.uc.counterparty_role.key
        if not item_id or not text:
            self._err(400, "item_id and text are required")
            return
        with st.lock:
            inv = st.load()
            for room in inv.rooms:
                for it in room.items:
                    if it.id == item_id:
                        it.comments.append({"author": author, "role": cp_role,
                                            "text": text, "at": _now()})
                        st.save(inv)
                        break
                else:
                    continue
                break
            else:
                self._err(404, f"no such item: {item_id}")
                return
        st.ack(author, cp_role, "comment", text, item_id)
        self._json({"ok": True})

    def _tenant_sign(self, st: SessionState, b: dict):
        name = (b.get("name") or "").strip()
        if not name:
            self._err(400, "name is required")
            return
        with st.lock:
            inv = st.load()
            inv.signatures.append(_signature(
                inv, name, st.uc.counterparty_role.key,
                "shared review link (level 3)"))
            st.save(inv)
        st.ack(name, st.uc.counterparty_role.key, "sign",
               "acknowledged receipt and countersigned")
        self._json({"ok": True})


def serve(capture_dir: Path, out_dir: Path, port: int = 8484,
          share: bool = False, backend: str = "claude",
          model: Optional[str] = None, base_url: Optional[str] = None,
          open_browser: bool = True,
          no_detect: bool = False,
          use_case: Optional[str] = None) -> ThreadingHTTPServer:
    """Build the server (returned so tests can drive it); call
    .serve_forever() to block."""
    project = ProjectState(capture_dir, out_dir, backend=backend, model=model,
                           base_url=base_url, share=share, no_detect=no_detect,
                           use_case=use_case)
    if project.is_multi:
        st = project.sessions[project.uc.sessions[0].key]
    else:
        st = project.session()
    if not project.is_multi and not st.inv_path.exists():
        print(f"\nNo {st.inv_path} yet — serving the start page "
              "(upload photos, then run the first build from the browser).")
        out_dir.mkdir(parents=True, exist_ok=True)
    elif project.is_multi and not project.any_built():
        print(f"\nMulti-session project ({project.uc.display_name}) — "
              "open the project home to capture and build each session.")

    handler = type("BoundHandler", (ReviewHandler,), {"project": project})
    host = "0.0.0.0" if share else "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), handler)
    # Back-compat: legacy tests expect review_state on the session object
    httpd.review_state = st  # type: ignore[attr-defined]
    httpd.project_state = project  # type: ignore[attr-defined]

    actual_port = httpd.server_address[1]
    print(f"\nReview app:  http://127.0.0.1:{actual_port}/", flush=True)
    if share:
        noun = project.uc.share_page.link_noun
        print(f"{noun.capitalize()} link: "
              f"http://{_lan_ip()}:{actual_port}/t/{project.tenant_token}",
              flush=True)
        print("  Anyone with this link can read the inventory, comment and "
              "countersign.\n  It dies with this process; restart for a new link.")
    if open_browser:
        import webbrowser
        threading.Timer(0.4, webbrowser.open,
                        args=(f"http://127.0.0.1:{actual_port}/",)).start()
    return httpd
