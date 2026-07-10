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
import io
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
import qrcode
import qrcode.image.svg

# Server plumbing + the single copy of the browser-upload contract live in
# webbase (extracted for M5b so the phone capture server reuses them
# verbatim). sniff_extension/_safe_component stay importable from here.
from .webbase import (TEMPLATES, BaseHandler, WALKTHROUGH_ROOM, _safe_component,  # noqa: F401
                      lan_ip as _lan_ip, scan_capture, scan_rooms, sniff_extension)
from .ingest import (IMAGE_EXTS, ROOM_ALIASES_FILE, exif_capture_time,
                     find_root_videos)
from .progress import BuildProgress
from .dotenv import load_dotenv
from .schema import Inventory, Item, Photo, cover_value
from .integrity import sha256_file
from .usecases import DEFAULT_USE_CASE, REGISTRY, get_use_case, use_case_for
from .usecases.base import UseCase


def _pair_qr_data_url(url: str) -> str:
    """Return a self-contained QR image for an owner pairing capability URL.

    Owner pairing links grant full edit access, so this stays entirely local:
    the QR SVG is generated in-process and embedded in the review page rather
    than being sent to a hosted QR-code service.
    """
    if not url:
        return ""
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    code.add_data(url)
    code.make(fit=True)
    stream = io.BytesIO()
    code.make_image(
        image_factory=qrcode.image.svg.SvgPathImage,
        fill_color="#22262d",
    ).save(stream)
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"

log = logging.getLogger(__name__)

# Backend default models, mirrored from describe.get_backend so the UI can
# name what a confirmed build/redescribe would actually run (spend guard:
# no paid backend without a per-request confirm naming it).
_BACKEND_DEFAULT_MODEL = {"claude": "claude-opus-4-8",
                          "openai": "gemini-3.5-flash",
                          "local": "qwen3.5:9b"}
BUILD_CONFIRM = "yes"
_USE_CASE_OUTCOMES = {
    "tenancy": "Signed inventory + tenant link",
    "deepclean": "Before/after reports + comparison sheet",
}


def spend_info(backend: str, model: Optional[str] = None) -> dict:
    """Plain-language spend copy for the UI — no backend or model names."""
    if backend == "offline":
        return {"label": "Draft mode", "estimate": "£0",
                "note": "No AI — useful for testing the journey."}
    if backend == "openai":
        return {"label": "Smart report", "estimate": "pennies–£1",
                "note": "Default quality path — review the output carefully."}
    if backend == "claude":
        return {"label": "Premium report", "estimate": "~£1–3",
                "note": "Best for hard items and the signed PDF."}
    if backend == "local":
        return {"label": "On-device draft", "estimate": "£0",
                "note": "Runs on your machine — slower, needs review."}
    return {"label": "AI report", "estimate": "varies",
            "note": "Uses a paid API."}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectState:
    """Project-level state: use case, compare job, session map."""

    def __init__(self, capture_dir: Path, out_dir: Path,
                 backend: str = "openai", model: Optional[str] = None,
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
        self.tenant_token: Optional[str] = self._resolve_tenant_token(share)
        self.owner_token: Optional[str] = self._resolve_owner_token(share)
        self.compare = {"status": "idle", "detail": "", "cmd": None}
        self.sessions: dict[str, SessionState] = {}
        self._init_sessions()

    @property
    def project_path(self) -> Path:
        return self.out_dir / "project.json"

    @property
    def share_path(self) -> Path:
        """Persisted tenant token so a saved share link survives restarts
        (docs/24 F4). Only written when sharing is explicitly enabled."""
        return self.out_dir / "share.json"

    def _resolve_tenant_token(self, share: bool) -> Optional[str]:
        """Mint a fresh token, or reuse the persisted one so an existing link
        keeps working after a server restart."""
        if not share:
            return None
        existing = self._load_share_token()
        token = existing or secrets.token_urlsafe(16)
        if not existing:
            self._save_share_token(token)
        return token

    def _load_share_token(self) -> Optional[str]:
        if not self.share_path.is_file():
            return None
        try:
            data = json.loads(self.share_path.read_text(encoding="utf-8"))
            token = data.get("tenant_token")
            if isinstance(token, str) and token:
                return token
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            pass
        return None

    def _save_share_token(self, token: str) -> None:
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.share_path.write_text(
                json.dumps({"tenant_token": token}, indent=2),
                encoding="utf-8")
        except OSError as e:
            log.warning("could not persist tenant token to %s (%s)",
                        self.share_path, e)

    @property
    def owner_pairing_path(self) -> Path:
        """Local-only owner capability for a paired phone.

        This deliberately lives apart from the tenant share record. A tenant
        link is read/comment/countersign access; an owner pairing link can
        change the evidence record and must never be confused with it.
        """
        return self.out_dir / "owner-pairing.json"

    def _resolve_owner_token(self, share: bool) -> Optional[str]:
        if not share:
            return None
        existing = self._load_owner_token()
        token = existing or secrets.token_urlsafe(24)
        if not existing:
            self._save_owner_token(token)
        return token

    def _load_owner_token(self) -> Optional[str]:
        if not self.owner_pairing_path.is_file():
            return None
        try:
            data = json.loads(self.owner_pairing_path.read_text(encoding="utf-8"))
            token = data.get("owner_token")
            return token if isinstance(token, str) and token else None
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            return None

    def _save_owner_token(self, token: str) -> None:
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.owner_pairing_path.write_text(
                json.dumps({"owner_token": token}, indent=2),
                encoding="utf-8")
        except OSError as e:
            log.warning("could not persist owner pairing token to %s (%s)",
                        self.owner_pairing_path, e)

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

    def session_status(self, route_prefix: str = "") -> list[dict]:
        out = []
        for spec in self.uc.sessions:
            st = self.sessions[spec.key]
            built = st.inv_path.exists()
            entry = {
                "key": spec.key, "label": spec.label, "built": built,
                "prefix": route_prefix + st.route_prefix,
            }
            if built:
                inv = st.load()
                entry["room_count"] = len(inv.rooms)
                entry["item_count"] = inv.item_count()
            out.append(entry)
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
        self._video_probe_cache: dict = {}

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

    def scan_capture(self) -> dict:
        return scan_capture(self.capture_dir)

    def remove_capture_file(self, name: str) -> None:
        """Delete one root-level upload from the pre-build evidence set."""
        safe = _safe_component(name)
        if not safe or safe != name:
            raise ValueError("invalid filename")
        from .ingest import IMAGE_EXTS, VIDEO_EXTS
        allowed = {
            p.name for p in self.capture_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
        }
        if safe not in allowed:
            raise FileNotFoundError(f"no such walkthrough: {safe}")
        (self.capture_dir / safe).unlink()

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

    def photo_src(self, inv: Inventory, route_prefix: Optional[str] = None) -> dict[str, str]:
        prefix = self.route_prefix if route_prefix is None else route_prefix
        out = {}
        for room in inv.rooms:
            for p in room.photos:
                if (self.out_dir / "photos" / f"{p.id}.jpg").exists():
                    out[p.id] = f"{prefix}/photos/{p.id}.jpg"
        return out

    def crop_src(self, inv: Inventory, route_prefix: Optional[str] = None) -> dict[str, str]:
        prefix = self.route_prefix if route_prefix is None else route_prefix
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

    def video_meta(self, inv: Inventory,
                   route_prefix: Optional[str] = None) -> tuple[dict, dict]:
        """(videos, photo_time) linking evidence frames to their moment in
        the source footage. Probe results cache for the server's life."""
        from .videometa import video_payload
        prefix = self.route_prefix if route_prefix is None else route_prefix
        return video_payload(inv, self.capture_dir, self.out_dir / "work",
                             prefix, self._video_probe_cache)

    def video_file(self, rel: str) -> Optional[Path]:
        """Resolve a capture-relative video path safely, or None."""
        if not rel or rel.startswith(("/", "\\")) or ".." in rel \
                or "\x00" in rel:
            return None
        target = (self.capture_dir / rel).resolve()
        try:
            target.relative_to(self.capture_dir.resolve())
        except ValueError:
            return None
        from .ingest import VIDEO_EXTS
        if not target.is_file() or target.suffix.lower() not in VIDEO_EXTS:
            return None
        return target

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
                pid = self._next_photo_id(inv)
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

    @staticmethod
    def _next_photo_id(inv: Inventory) -> str:
        """Return the next unused stable exhibit id for a reviewed photo."""
        taken = {p.id for room in inv.rooms for p in room.photos}
        number = 1
        while f"P{number:03d}" in taken:
            number += 1
        return f"P{number:03d}"

    def attach_review_photo(self, item_id: str, source_path: str,
                            author: str = "reviewer") -> dict:
        """Attach an already streamed close-up to one existing claim.

        ``/api/upload`` is deliberately the only binary ingress.  This
        follow-up operation only accepts its room-relative stored path, checks
        that it is an original image in the claim's room, then gives that
        original a stable exhibit id, hash-manifest row and item link.  It
        means a phone reviewer can add one decisive close-up without creating
        an uncited orphan or having to run another capture workflow.
        """
        item_id = (item_id or "").strip()
        raw_path = (source_path or "").strip().replace("\\", "/")
        parts = raw_path.split("/")
        if (not item_id or not raw_path
                or any(part in ("", ".", "..") for part in parts)):
            raise ValueError("item_id and a plain room-relative photo path are required")

        with self.lock:
            inv = self.load()
            room = None
            item = None
            for candidate_room in inv.rooms:
                found = next((candidate for candidate in candidate_room.items
                              if candidate.id == item_id), None)
                if found is not None:
                    room, item = candidate_room, found
                    break
            if room is None or item is None:
                raise KeyError(f"no such item: {item_id}")

            capture_root = self.capture_dir.resolve()
            room_dir = (self.capture_dir / room.name).resolve()
            source = (self.capture_dir.joinpath(*parts)).resolve()
            try:
                source.relative_to(capture_root)
            except ValueError as e:
                raise ValueError("photo path escapes the capture folder") from e
            if source.parent != room_dir:
                raise ValueError("photo must be uploaded to the item's room")
            if not source.is_file() or source.suffix.lower() not in IMAGE_EXTS:
                raise ValueError("uploaded evidence must be a recognised photo")

            portable_path = source.relative_to(capture_root).as_posix()
            source_hash = sha256_file(source)
            photo = next((candidate for candidate in room.photos
                          if candidate.path.replace("\\", "/") == portable_path),
                         None)
            # If the phone repeated a completed single-shot upload after it
            # lost the attachment response, retain the duplicate original in
            # capture but do not manufacture a second exhibit for identical
            # bytes.  This mirrors the resumable video rule at the evidence
            # record level rather than relying only on a browser retry.
            if photo is None:
                photo = next((candidate for candidate in room.photos
                              if candidate.sha256 == source_hash), None)
            created = photo is None
            linked = False
            if photo is None:
                photo = Photo(
                    id=self._next_photo_id(inv), path=portable_path,
                    room=room.name, sha256=source_hash,
                    captured_at=exif_capture_time(source),
                    note=f"close photo added during mobile review by {author}",
                )
                room.photos.append(photo)
                self._append_manifest_entry(photo, source)
            if photo.id not in item.photo_ids:
                item.photo_ids.append(photo.id)
                linked = True
            if created or linked:
                self.save(inv)

        if created or linked:
            self.ack(author, self.uc.owner_role.key, "attach_review_photo",
                     portable_path, item_id)
            with self.lock:
                self.rerender()
        return {"photo": asdict(photo), "item_id": item_id,
                "created": created, "linked": linked}

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
        from .pipeline import BuildOptions, run_build

        with self.lock:
            if self._busy():
                return False
            self.redescribe = {"status": "running", "room": room, "detail": ""}
        opts = BuildOptions(
            capture_dir=self.capture_dir,
            out_dir=self.out_dir,
            backend=self.backend,
            model=self.model,
            base_url=self.base_url,
            use_case=self.uc.key if self.uc.key != DEFAULT_USE_CASE else None,
            room=room,
            from_json=str(self.out_dir / "inventory.json"),
            no_detect=self.no_detect,
            no_pdf=True,
        )

        def run():
            try:
                result = run_build(opts)
                with self.lock:
                    self.redescribe = {
                        "status": "done" if result.exit_code == 0 else "failed",
                        "room": room,
                        "detail": result.detail,
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
        from .pipeline import BuildOptions, run_build

        with self.lock:
            if self._busy():
                return False
            progress_path = self.out_dir / "work" / "build-progress.json"
            opts = BuildOptions(
                capture_dir=self.capture_dir,
                out_dir=self.out_dir,
                backend=self.backend,
                model=self.model,
                base_url=self.base_url,
                use_case=self.uc.key if self.uc.key != DEFAULT_USE_CASE else None,
                from_json=str(self.out_dir / "inventory.json")
                if self.inv_path.exists() else None,
                progress_file=progress_path,
                no_detect=self.no_detect,
            )
            self.build = {"status": "running", "detail": "",
                          "progress_path": str(progress_path)}

        def run():
            try:
                result = run_build(opts)
                ok = result.exit_code == 0
                with self.lock:
                    self.build = {
                        "status": "done" if ok else "failed",
                        "detail": result.detail,
                        "progress_path": str(progress_path),
                    }
                if ok and self.project.is_multi and self.project.all_sessions_built():
                    if not (self.project.compare_dir / "compare.html").is_file():
                        self.project.start_compare()
            except Exception as e:
                with self.lock:
                    self.build = {"status": "failed", "detail": str(e),
                                  "progress_path": str(progress_path)}
        threading.Thread(target=run, daemon=True).start()
        self.ack("reviewer", self.uc.owner_role.key, "build",
                 f"backend={self.backend} no_detect={self.no_detect}")
        return True

    def build_status(self) -> dict:
        with self.lock:
            out = dict(self.build)
        path = out.get("progress_path")
        if path:
            prog = BuildProgress.load(Path(path))
            out.update({
                "stage": prog.stage,
                "stage_detail": prog.detail,
                "rooms_found": prog.rooms_found,
                "room_names": prog.room_names,
                "room_index": prog.room_index,
                "room_total": prog.room_total,
                "room_name": prog.room_name,
            })
        return out

    def _record_room_alias(self, old: str, new: str) -> None:
        """Persist a review-time rename/merge so rebuilds honour it.

        Builds re-derive room names from capture folders and the cached
        segments.json; without the alias a re-describe of a renamed room
        finds no photos and a full rebuild resurrects the old name."""
        path = self.out_dir / "work" / ROOM_ALIASES_FILE
        amap: dict[str, str] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data.get("map"), dict):
                    amap = data["map"]
            except json.JSONDecodeError:
                pass
        for k, v in amap.items():
            if v.lower() == old.lower():
                amap[k] = new
        amap[old] = new
        amap = {k: v for k, v in amap.items() if k != v}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "map": amap}, indent=2,
                                   ensure_ascii=False), encoding="utf-8")

    def rename_room(self, old_name: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("new room name is required")
        with self.lock:
            inv = self.load()
            room = next((r for r in inv.rooms
                         if r.name.lower() == old_name.lower()), None)
            if room is None:
                raise KeyError(f"no such room: {old_name}")
            if any(r.name.lower() == new_name.lower() and r is not room
                   for r in inv.rooms):
                raise ValueError(f"room already exists: {new_name}")
            old_canonical = room.name
            room.name = new_name
            for p in room.photos:
                p.room = new_name
            self.save(inv)
            self._record_room_alias(old_canonical, new_name)
        self.rerender()
        self.ack("reviewer", self.uc.owner_role.key, "rename_room",
                 f"{old_name} → {new_name}")

    def merge_rooms(self, source: str, into: str) -> None:
        with self.lock:
            inv = self.load()
            src = next((r for r in inv.rooms
                        if r.name.lower() == source.lower()), None)
            dst = next((r for r in inv.rooms
                        if r.name.lower() == into.lower()), None)
            if src is None or dst is None:
                raise KeyError("source and target rooms must exist")
            if src is dst:
                raise ValueError("cannot merge a room into itself")
            dst.photos.extend(src.photos)
            dst.items.extend(src.items)
            for p in dst.photos:
                p.room = dst.name
            inv.rooms = [r for r in inv.rooms if r is not src]
            self.save(inv)
            self._record_room_alias(src.name, dst.name)
        self.rerender()
        self.ack("reviewer", self.uc.owner_role.key, "merge_rooms",
                 f"{source} → {into}")

    def set_hero_override(self, photo_id: str, action: str) -> dict:
        """Promote/demote a frame in the room's default view, now and
        across rebuilds (docs/15 M3 — the curation.json override survives
        the next build's re-election)."""
        from .curate import apply_override
        with self.lock:
            inv = self.load()
            result = apply_override(inv, photo_id, action,
                                    self.out_dir / "work")
            self.save(inv)
            self.rerender(inv)
        self.ack("reviewer", self.uc.owner_role.key,
                 f"curate_{action}", photo_id)
        return result

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


def _already_signed(inv: Inventory, name: str, role: str) -> bool:
    """Has this party already signed the current (unchanged) content? Re-signing
    identical content is a no-op rather than a duplicate row (docs/24 F5)."""
    sha = inv.content_sha256()
    return any(
        s.get("name") == name and s.get("role") == role
        and s.get("inventory_sha256") == sha
        for s in inv.signatures
    )


def _address_ok(inv: Inventory, uc: UseCase) -> bool:
    """Cover address must be set to a real value before signing."""
    addr = (inv.property_address or "").strip()
    if not addr:
        return False
    for field in uc.cover_fields:
        if field.name == "property_address" and field.placeholder:
            if addr.lower() == field.placeholder.strip().lower():
                return False
    return True


_WEASYPRINT_OK: bool | None = None


def _weasyprint_available(*, force: bool = False) -> bool:
    """Probe WeasyPrint once per process (docs/24 F1 / craft N)."""
    global _WEASYPRINT_OK
    if force:
        _WEASYPRINT_OK = None
    if _WEASYPRINT_OK is not None:
        return _WEASYPRINT_OK
    try:
        from .report import import_weasyprint
        import_weasyprint()
        _WEASYPRINT_OK = True
    except Exception:
        _WEASYPRINT_OK = False
    return _WEASYPRINT_OK


def _pdf_meta(st: SessionState) -> dict:
    pdf_path = st.out_dir / "inventory.pdf"
    inv_path = st.inv_path
    ready = pdf_path.is_file()
    stale = True
    if ready and inv_path.is_file():
        # Equal timestamps are ambiguous on filesystems with coarse mtimes:
        # a just-saved inventory can otherwise look older than its PDF.
        stale = inv_path.stat().st_mtime >= pdf_path.stat().st_mtime
    elif not ready:
        stale = True
    else:
        stale = False
    return {
        "ready": ready,
        "stale": stale,
        "weasyprint_available": _weasyprint_available(),
    }


class ReviewHandler(BaseHandler):
    """Review/tenant routes; request plumbing inherited from webbase."""

    project: ProjectState  # set by serve()

    def _tenant_token_ok(self, token: str) -> bool:
        expected = self.project.tenant_token
        return bool(expected) and secrets.compare_digest(token, expected)

    def _owner_token_ok(self, token: str) -> bool:
        expected = self.project.owner_token
        return bool(expected) and secrets.compare_digest(token, expected)

    def _owner_path(self, path: str) -> tuple[str, str, bool, bool]:
        """Return (stripped_path, prefix, authenticated, was_owner_path)."""
        m = re.fullmatch(r"/o/([\w\-]+)(/.*)?", path)
        if not m:
            return path, "", False, False
        token = m.group(1)
        if not self._owner_token_ok(token):
            return path, "", False, True
        return m.group(2) or "/", f"/o/{token}", True, True

    def _owner_pair_url(self) -> str:
        token = self.project.owner_token
        if not token:
            return ""
        port = self.server.server_address[1]
        return f"http://{_lan_ip()}:{port}/o/{token}"

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

    def _review_payload(self, st: SessionState, inv: Inventory,
                        route_prefix: Optional[str] = None, **extra) -> dict:
        uc = st.uc
        roles: dict = {
            "owner": {"key": uc.owner_role.key, "label": uc.owner_role.label},
            "counterparty": {"key": uc.counterparty_role.key,
                             "label": uc.counterparty_role.label},
        }
        if uc.agent_role:
            roles["agent"] = {"key": uc.agent_role.key,
                              "label": uc.agent_role.label}
        prefix = st.route_prefix if route_prefix is None else route_prefix
        videos, photo_time = st.video_meta(inv, prefix)
        payload = {
            "inventory": asdict(inv),
            "content_sha256": inv.content_sha256(),
            "photo_src": st.photo_src(inv, prefix),
            "crop_src": st.crop_src(inv, prefix),
            "videos": videos,
            "photo_time": photo_time,
            "backend": st.backend,
            "backend_label": st.backend_label,
            "spend": spend_info(st.backend, st.model),
            "build_confirm": BUILD_CONFIRM,
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
            "pdf_meta": _pdf_meta(st),
        }
        payload.update(extra)
        return payload

    def _render_app(self, st: SessionState, template: str,
                    route_prefix: Optional[str] = None, **extra) -> str:
        inv = st.load()
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        prefix = st.route_prefix if route_prefix is None else route_prefix
        return env.get_template(template).render(
            inv=inv, payload=self._review_payload(st, inv, prefix, **extra),
            share_url=extra.get("share_url", ""),
            pair_url=extra.get("pair_url", ""),
            pair_qr_src=_pair_qr_data_url(extra.get("pair_url", "")),
            paired_phone=extra.get("paired_phone", False),
            pairing_available=extra.get("pairing_available", False),
            route_prefix=prefix)

    def _render_workspace(self, st: SessionState, *, route_prefix: str = "",
                          show_picker: bool = False,
                          initial_screen: str = "overview", **extra) -> str:
        """Render the phone-first field workspace.

        The workspace is deliberately a new surface over the existing
        evidence contract.  Capture, review and issue all continue to use the
        same upload API, Inventory schema, acknowledgement trail and renderer;
        the old evidence-room interface remains available at ``/review`` while
        users need its more specialised controls.
        """
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        has_inventory = st.inv_path.exists()
        inv = st.load() if has_inventory else None
        share_url = ""
        if st.tenant_token:
            share_url = f"{st.route_prefix}/t/{st.tenant_token}" \
                if self.project.is_multi else f"/t/{st.tenant_token}"
        return env.get_template("workspace.html.j2").render(
            prebuild=not has_inventory,
            inv=inv,
            payload=(self._review_payload(st, inv, route_prefix, **extra)
                     if inv else {}),
            capture=st.scan_capture(),
            spend=spend_info(st.backend, st.model),
            walkthrough_room=WALKTHROUGH_ROOM,
            has_inventory=has_inventory,
            show_picker=show_picker,
            use_case=st.uc.key,
            use_case_label=st.uc.display_name,
            use_cases=[{"key": u.key, "label": u.display_name,
                        "description": u.description,
                        "outcome": _USE_CASE_OUTCOMES.get(u.key, "")}
                       for u in REGISTRY.values()],
            share_url=share_url,
            initial_screen=initial_screen,
            route_prefix=route_prefix)

    def _render_start(self, st: SessionState, *, show_picker: bool | None = None,
                      route_prefix: Optional[str] = None) -> str:
        proj = self.project
        env = Environment(loader=FileSystemLoader(TEMPLATES),
                          autoescape=select_autoescape(["html"]))
        if show_picker is None:
            show_picker = (not proj.project_path.exists() and not proj.is_legacy
                           and not st.inv_path.exists())
        picker = show_picker
        prefix = st.route_prefix if route_prefix is None else route_prefix
        return env.get_template("start.html.j2").render(
            capture=st.scan_capture(), backend=st.backend,
            spend=spend_info(st.backend, st.model),
            capture_dir=str(st.capture_dir),
            has_inventory=st.inv_path.exists(),
            use_case=proj.uc.key,
            use_case_label=proj.uc.display_name,
            show_picker=picker,
            walkthrough_room=WALKTHROUGH_ROOM,
            use_cases=[{"key": u.key, "name": u.display_name,
                        "description": u.description,
                        "outcome": _USE_CASE_OUTCOMES.get(u.key, "")}
                       for u in REGISTRY.values()],
            route_prefix=prefix)

    def _render_project(self, route_prefix: str = "") -> str:
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
            sessions=proj.session_status(route_prefix),
            compare_ready=compare_ready,
            compare_built=compare_built,
            compare_running=proj.compare["status"] == "running",
            route_prefix=route_prefix)

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
        except (BrokenPipeError, ConnectionResetError):
            pass   # client hung up mid-stream (video seeks do this constantly)
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
        raw, owner_prefix, owner_authenticated, owner_path = self._owner_path(raw)
        if owner_path and not owner_authenticated:
            self._err(403, "invalid or expired owner pairing link")
            return
        owner_ok = self._is_local() or owner_authenticated

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
            m = re.fullmatch(r"/video/(.+)", subpath)
            if m:
                from urllib.parse import unquote
                from .videometa import VIDEO_CTYPES
                target = st.video_file(unquote(m.group(1)))
                if target is None:
                    self._err(404, "not found")
                    return True
                self._file_stream(target, VIDEO_CTYPES.get(
                    target.suffix.lower(), "application/octet-stream"))
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
            self._redirect(owner_prefix + "/compare/")
            return
        if path == "/compare/" or path.startswith("/compare/"):
            if not owner_ok and not path.startswith("/t/"):
                self._err(403, "owner routes are localhost-only")
                return
            sub = path[len("/compare"):] if path.startswith("/compare") else "/"
            self._serve_compare(sub)
            return

        if path == "/api/compare":
            if not owner_ok:
                self._err(403, "owner routes are localhost-only")
                return
            with proj.lock:
                self._json(dict(proj.compare))
            return

        if not owner_ok:
            self._err(403, "owner routes are localhost-only")
            return

        if path == "/" and proj.is_multi and session_key is None:
            self._html(self._render_project(route_prefix=owner_prefix))
            return

        if st is None:
            try:
                st = proj.session()
            except KeyError:
                # multi-session: bare paths have no session — a clean 404,
                # not a KeyError 500 (e.g. /favicon.ico)
                self._err(404, "not found")
                return

        if path in ("/", "/finish"):
            route_prefix = owner_prefix + st.route_prefix
            self._html(self._render_workspace(
                st, route_prefix=route_prefix,
                show_picker=(not proj.project_path.exists() and not proj.is_legacy
                             and not st.inv_path.exists()),
                initial_screen="finish" if path == "/finish" else "overview"))
            return
        if path == "/review":
            # Transitional evidence desk: preserves every specialist review
            # control while the field workspace owns the default journey.
            share_url = ""
            if st.tenant_token:
                share_url = f"{st.route_prefix}/t/{st.tenant_token}" \
                    if proj.is_multi else f"/t/{st.tenant_token}"
            local_owner = self._is_local()
            pair_url = self._owner_pair_url() if local_owner else ""
            self._html(self._render_app(
                st, "review.html.j2",
                route_prefix=owner_prefix + st.route_prefix,
                share_url=share_url, pair_url=pair_url,
                paired_phone=owner_authenticated,
                pairing_available=bool(pair_url)))
            return
        if path == "/start":
            self._html(self._render_workspace(
                st, show_picker=False,
                route_prefix=owner_prefix + st.route_prefix))
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
                        # Treat equal mtimes as stale too.  Windows can write
                        # an autosaved JSON edit and its prior HTML within one
                        # timestamp tick, which must never hide the edit.
                        or html.stat().st_mtime <= st.inv_path.stat().st_mtime):
                    st.rerender()
            self._file(html, "text/html; charset=utf-8")
            return
        if path == "/api/build":
            self._json(st.build_status())
            return
        if path == "/api/pdf":
            with st.lock:
                self._json(dict(st.pdf))
            return
        if path == "/api/rooms":
            self._json(st.scan_capture())
            return
        m = re.fullmatch(r"/api/upload/([\w\-]{8,64})", path)
        if m:
            payload = self._upload_status(st.capture_dir, m.group(1))
            if payload is not None:
                self._json(payload)
            return
        if path == "/api/inventory":
            inv = st.load()
            route_prefix = owner_prefix + st.route_prefix
            videos, photo_time = st.video_meta(inv, route_prefix)
            self._json({"inventory": asdict(inv),
                        "photo_src": st.photo_src(inv, route_prefix),
                        "crop_src": st.crop_src(inv, route_prefix),
                        "videos": videos, "photo_time": photo_time})
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
            raw, _owner_prefix, owner_authenticated, owner_path = self._owner_path(raw)
            if owner_path and not owner_authenticated:
                self._err(403, "invalid or expired owner pairing link")
                return
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

            if not (self._is_local() or owner_authenticated):
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

            if path == "/api/upload":
                payload = self._upload_stream_common(st.capture_dir, st.lock)
                if payload is None:
                    return
                if payload.get("complete") is False:
                    self._json(payload)
                    return
                st.ack("reviewer", st.uc.owner_role.key, "upload_media",
                       payload["path"])
                self._json(payload)
                return
            if path == "/api/evidence/attach":
                b = self._body()
                try:
                    result = st.attach_review_photo(
                        b.get("item_id") or "", b.get("path") or "",
                        b.get("author") or "reviewer")
                except (ValueError, KeyError) as e:
                    self._err(400, str(e))
                    return
                self._json({"ok": True, **result})
                return
            if path == "/api/capture/remove":
                b = self._body()
                name = (b.get("name") or "").strip()
                if not name:
                    self._err(400, "name is required")
                    return
                with st.lock:
                    if st.build.get("status") == "running":
                        self._err(409, "cannot remove while a build is running")
                        return
                    try:
                        st.remove_capture_file(name)
                    except ValueError as e:
                        self._err(400, str(e))
                        return
                    except FileNotFoundError as e:
                        self._err(404, str(e))
                        return
                    st.ack("reviewer", st.uc.owner_role.key, "remove_walkthrough",
                           name)
                self._json({"ok": True, "capture": st.scan_capture()})
                return
            if path == "/api/build":
                b = self._body()
                if (b.get("confirm") or "") != BUILD_CONFIRM:
                    self._err(400, 'build must be confirmed with {"confirm": "yes"}')
                    return
                if not st.start_build():
                    self._err(409, "a build or re-describe is already running")
                    return
                self._json({"ok": True, "status": "running"})
                return
            if path == "/api/pdf":
                if not _weasyprint_available():
                    self._json({
                        "ok": False,
                        "status": "unavailable",
                        "weasyprint_available": False,
                        "error": ("Server PDF needs WeasyPrint "
                                  "(pip install homeinventory[pdf]). "
                                  "Use Print → Save as PDF from the "
                                  "final issue instead."),
                        "fallback": "print",
                    }, 503)
                    return
                if not st.start_pdf():
                    self._err(409, "a PDF export is already running")
                    return
                self._json({"ok": True, "status": "running",
                            "weasyprint_available": True})
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
                if (b.get("confirm") or "") != BUILD_CONFIRM:
                    self._err(400, 're-describe must be confirmed with '
                                   '{"confirm": "yes"}')
                    return
                if not st.start_redescribe(b["room"]):
                    self._err(409, "a build or re-describe is already running")
                    return
                self._json({"ok": True})
                return
            if path == "/api/rooms/rename":
                b = self._body()
                try:
                    st.rename_room(b.get("from") or b.get("old") or "",
                                   b.get("to") or b.get("new") or "")
                except (ValueError, KeyError) as e:
                    self._err(400, str(e))
                    return
                self._json({"ok": True})
                return
            if path == "/api/rooms/merge":
                b = self._body()
                try:
                    st.merge_rooms(b.get("source") or b.get("from") or "",
                                   b.get("into") or b.get("to") or "")
                except (ValueError, KeyError) as e:
                    self._err(400, str(e))
                    return
                self._json({"ok": True})
                return
            if path == "/api/curation":
                b = self._body()
                result = st.set_hero_override(b.get("photo_id") or "",
                                              (b.get("action") or "").strip())
                self._json({"ok": True, **result})
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
                inv = st.load()
                if not _address_ok(inv, st.uc):
                    self._err(400, "property address required before signing")
                    return
                with st.lock:
                    inv = st.load()
                    if not _already_signed(inv, name, role):
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
            if not _already_signed(inv, name, st.uc.counterparty_role.key):
                inv.signatures.append(_signature(
                    inv, name, st.uc.counterparty_role.key,
                    "shared review link (level 3)"))
                st.save(inv)
        st.ack(name, st.uc.counterparty_role.key, "sign",
               "acknowledged receipt and countersigned")
        self._json({"ok": True})


def serve(capture_dir: Path, out_dir: Path, port: int = 8484,
          share: bool = False, backend: str = "openai",
          model: Optional[str] = None, base_url: Optional[str] = None,
          open_browser: bool = True,
          no_detect: bool = False,
          use_case: Optional[str] = None) -> ThreadingHTTPServer:
    """Build the server (returned so tests can drive it); call
    .serve_forever() to block."""
    load_dotenv()
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
        print("Owner phone pairing: "
              f"http://{_lan_ip()}:{actual_port}/o/{project.owner_token}",
              flush=True)
        print(f"{noun.capitalize()} link: "
              f"http://{_lan_ip()}:{actual_port}/t/{project.tenant_token}",
              flush=True)
        print("  The owner pairing link has full edit access. Treat it like a key.\n"
              "  Anyone with the tenant link can read the inventory, comment and "
              "countersign.\n  It is saved to share.json and persists across "
              "restarts (re-run with --share to reuse it).")
    if open_browser:
        import webbrowser
        threading.Timer(0.4, webbrowser.open,
                        args=(f"http://127.0.0.1:{actual_port}/",)).start()
    return httpd
