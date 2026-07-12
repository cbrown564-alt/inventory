"""Canonical build pipeline — ingest through report render.

Both the CLI and the review web app call ``run_build()`` so orchestration
lives in one place (docs/00 Phase 0).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from io import StringIO
from pathlib import Path
from typing import Optional

from .schema import Inventory, Item, Room

log = logging.getLogger("homeinventory")

DETECT_MODE_CHOICES = ("text", "prompt_free")


@dataclass
class BuildOptions:
    capture_dir: Path
    out_dir: Path
    backend: str = "openai"
    model: Optional[str] = None
    base_url: Optional[str] = None
    address: str = ""
    inspector: str = ""
    agent_name: str = ""
    agent_phone: str = ""
    property_type: str = ""
    tenant: str = ""
    landlord: str = ""
    report_ref: str = ""
    use_case: Optional[str] = None
    party: list[str] = field(default_factory=list)
    notes: str = ""
    room: Optional[str] = None
    from_json: Optional[str] = None
    resume: bool = False
    trim_lead: float = 0.0
    segment_model: str = "gemini-3.5-flash"
    segment_every: float = 5.0
    segments_json: Optional[Path] = None
    no_segment: bool = False
    progress_file: Optional[Path] = None
    no_detect: bool = False
    detect_mode: str = "text"
    detect_model: Optional[str] = None
    device: Optional[str] = None
    det_conf: float = 0.25
    no_pdf: bool = False

    @classmethod
    def from_args(cls, args) -> BuildOptions:
        seg_json = getattr(args, "segments_json", None)
        progress = getattr(args, "progress_file", None)
        from_json = getattr(args, "from_json", None)
        if from_json == "":
            from_json = str(Path(args.out) / "inventory.json")
        return cls(
            capture_dir=Path(args.capture_dir),
            out_dir=Path(args.out),
            backend=args.backend,
            model=args.model,
            base_url=args.base_url,
            address=args.address or "",
            inspector=args.inspector or "",
            agent_name=args.agent_name or "",
            agent_phone=args.agent_phone or "",
            property_type=args.property_type or "",
            tenant=args.tenant or "",
            landlord=args.landlord or "",
            report_ref=args.report_ref or "",
            use_case=args.use_case,
            party=list(args.party),
            notes=args.notes or "",
            room=args.room,
            from_json=from_json,
            resume=args.resume,
            trim_lead=getattr(args, "trim_lead", 0.0),
            segment_model=getattr(args, "segment_model", "gemini-3.5-flash"),
            segment_every=getattr(args, "segment_every", 5.0),
            segments_json=Path(seg_json) if seg_json else None,
            no_segment=getattr(args, "no_segment", False),
            progress_file=Path(progress) if progress else None,
            no_detect=getattr(args, "no_detect", False),
            detect_mode=getattr(args, "detect_mode", "text"),
            detect_model=getattr(args, "detect_model", None),
            device=getattr(args, "device", None),
            det_conf=getattr(args, "det_conf", 0.25),
            no_pdf=args.no_pdf,
        )


@dataclass
class BuildResult:
    exit_code: int
    detail: str = ""
    failures: list[str] = field(default_factory=list)
    outputs: dict[str, Path] = field(default_factory=dict)


def _full_path(capture_dir: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else capture_dir / p


def _checkpoint_name(room_name: str) -> str:
    return re.sub(r"[^\w\- ]+", "_", room_name) + ".json"


def _load_prior(opts: BuildOptions) -> tuple[Inventory | None, bool]:
    inv_path = opts.out_dir / "inventory.json"
    only = {r.strip().lower() for r in opts.room.split(",")} if opts.room else None
    preserve = opts.from_json is not None
    if preserve:
        path = Path(opts.from_json) if opts.from_json else inv_path
        if not path.is_file():
            return None, True
        return Inventory.from_json(path.read_text(encoding="utf-8")), True
    if only and inv_path.exists():
        return Inventory.from_json(inv_path.read_text(encoding="utf-8")), False
    return None, False


def _make_detector(opts: BuildOptions):
    from .detect import Detector, default_model

    if opts.no_detect:
        return None
    model = opts.detect_model or default_model(opts.detect_mode)
    return Detector(
        model_name=model,
        mode=opts.detect_mode,
        conf=opts.det_conf,
        device=opts.device,
    )


def run_build(opts: BuildOptions, *,
              stdout: Optional[StringIO] = None) -> BuildResult:
    """Run the full ingest → curate → detect → describe → render pipeline."""
    from .describe import FatalBackendError, get_backend
    from .ingest import ingest
    from .integrity import build_manifest
    from .merge import merge_items, merge_room_with_prior, room_code
    from .progress import BuildProgress
    from .report import render
    from .usecases import DEFAULT_USE_CASE, get_use_case

    out = stdout or StringIO()
    failures: list[str] = []
    outputs: dict[str, Path] = {}

    def emit(msg: str = "", *, file=None):
        print(msg, file=file or out, flush=True)

    capture_dir = opts.capture_dir
    out_dir = opts.out_dir
    if not capture_dir.is_dir():
        emit(f"error: capture dir not found: {capture_dir}", file=sys.stderr)
        return BuildResult(2, detail=out.getvalue()[-2000:])

    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "work"
    progress = BuildProgress()
    progress.start(opts.progress_file)

    def _on_segmenting():
        progress.segmenting(opts.progress_file)

    def _on_segmented(n_rooms: int, room_names: list[str] | None = None):
        progress.segmented(opts.progress_file, n_rooms, room_names)

    def _on_extracting():
        progress.extracting(opts.progress_file)

    try:
        rooms_photos = ingest(
            capture_dir, work_dir,
            lead_trim_s=opts.trim_lead,
            segment_model=opts.segment_model,
            segment_every=opts.segment_every,
            segments_json=opts.segments_json,
            no_segment=opts.no_segment,
            on_segmenting=_on_segmenting,
            on_segmented=_on_segmented,
            on_extracting=_on_extracting,
        )
    except Exception as e:
        progress.failed(opts.progress_file, str(e))
        emit(f"error: ingest failed: {e}", file=sys.stderr)
        return BuildResult(2, detail=out.getvalue()[-2000:])

    if not rooms_photos:
        emit("error: no photos or videos found (see `homeinventory guide`)",
             file=sys.stderr)
        return BuildResult(2, detail=out.getvalue()[-2000:])

    n_photos = sum(len(v) for v in rooms_photos.values())
    log.info("ingested %d photos across %d rooms", n_photos, len(rooms_photos))

    build_manifest(capture_dir, rooms_photos, out_dir / "manifest.json")

    from .curate import curate
    curate(rooms_photos, capture_dir, work_dir)

    only = {r.strip().lower() for r in opts.room.split(",")} if opts.room else None
    selected = {name: photos for name, photos in rooms_photos.items()
                if not only or name.lower() in only}
    if not selected:
        emit(f"error: --room matched nothing; available rooms: "
             f"{', '.join(sorted(rooms_photos))}", file=sys.stderr)
        return BuildResult(2, detail=out.getvalue()[-2000:])

    prior, preserve_edits = _load_prior(opts)
    if prior is None and opts.from_json is not None:
        emit(f"error: --from-json file not found: {opts.from_json}",
             file=sys.stderr)
        return BuildResult(2, detail=out.getvalue()[-2000:])

    use_case = opts.use_case or (prior.use_case if prior else DEFAULT_USE_CASE)

    detector = _make_detector(opts)
    detections: dict[str, list] = {}
    if detector:
        for photos in selected.values():
            for p in photos:
                detections[p.id] = detector.detect(_full_path(capture_dir, p.path),
                                                   crops_dir=work_dir / "crops")
        if not detector.available:
            log.warning("detector unavailable — continuing without crops/hints")
        else:
            from .curate import (load_overrides,
                                 rerank_covers_with_detections)
            promoted = rerank_covers_with_detections(
                selected, detections, load_overrides(work_dir))
            for room_name, photo_id in promoted.items():
                log.info("detector-assisted cover for %s: %s",
                         room_name, photo_id)

    try:
        backend = get_backend(opts.backend, model=opts.model,
                              base_url=opts.base_url, use_case=use_case)
    except FatalBackendError as e:
        emit(f"error: {e}", file=sys.stderr)
        return BuildResult(2, detail=out.getvalue()[-2000:])

    inv = Inventory(
        property_address=opts.address or (prior.property_address if prior else ""),
        inspected_by=opts.inspector or (prior.inspected_by if prior else ""),
        agent_name=opts.agent_name or (prior.agent_name if prior else ""),
        agent_phone=opts.agent_phone or (prior.agent_phone if prior else ""),
        property_type=opts.property_type or (prior.property_type if prior else ""),
        tenant_name=opts.tenant or (prior.tenant_name if prior else ""),
        landlord_name=opts.landlord or (prior.landlord_name if prior else ""),
        report_ref=opts.report_ref or (prior.report_ref if prior else ""),
        describe_backend=f"{backend.name}"
                         + (f" ({getattr(backend, 'model', None)})"
                            if getattr(backend, "model", None) else ""),
        notes=opts.notes or (prior.notes if prior else ""),
    )
    inv.use_case = use_case
    default_title = Inventory.__dataclass_fields__["report_type"].default
    prior_title = prior.report_type if prior else ""
    inv.report_type = (prior_title
                       if prior_title and prior_title != default_title
                       else get_use_case(use_case).report_type)
    inv.parties = dict(prior.parties if prior else {})
    for spec in opts.party:
        key, _, name = spec.partition("=")
        if key:
            inv.parties[key] = name
    if prior and preserve_edits:
        inv.inspected_at = prior.inspected_at
        inv.signatures = list(prior.signatures)
        if prior.schedule_summary:
            inv.schedule_summary = list(prior.schedule_summary)

    used_codes: set[str] = set()
    if prior:
        for r in prior.rooms:
            if only and r.name.lower() in only and not preserve_edits:
                continue
            for it in r.items:
                code = it.id.rsplit("-", 1)[0]
                if code:
                    used_codes.add(code)

    ckpt_dir = work_dir / "checkpoints"
    if not opts.resume and ckpt_dir.exists():
        shutil.rmtree(ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    built: dict[str, Room] = {}
    room_names = sorted(selected)
    for ri, room_name in enumerate(room_names, start=1):
        progress.describing(opts.progress_file, ri, len(room_names), room_name)
        photos = selected[room_name]
        ckpt = ckpt_dir / _checkpoint_name(room_name)
        if opts.resume and ckpt.exists():
            log.info("reusing checkpoint for %s", room_name)
            data = json.loads(ckpt.read_text(encoding="utf-8"))
            summary = data["summary"]
            items = [Item(**i).normalise() for i in data["items"]]
        else:
            paths = [_full_path(capture_dir, p.path) for p in photos]
            log.info("describing %s (%d photos, backend=%s)…",
                     room_name, len(photos), backend.name)
            try:
                summary, items = backend.describe_room(room_name, photos, paths,
                                                       detections)
            except FatalBackendError as e:
                emit(f"error: {e}", file=sys.stderr)
                return BuildResult(2, detail=out.getvalue()[-2000:])
            except Exception as e:
                log.error("describe failed for %s: %s", room_name, e)
                failures.append(room_name)
                built[room_name] = Room(
                    name=room_name,
                    summary=f"[DESCRIBE FAILED: {e}] Re-run with --resume to "
                            "retry this room without re-describing the others.",
                    items=[], photos=photos)
                continue
            ckpt.write_text(json.dumps(
                {"summary": summary, "items": [asdict(i) for i in items],
                 "timing": getattr(backend, "last_room_timing", None)},
                ensure_ascii=False), encoding="utf-8")
        code = room_code(room_name, used_codes)
        prior_room = None
        if prior and preserve_edits:
            for r in prior.rooms:
                if r.name.lower() == room_name.lower():
                    prior_room = r
                    break
        if prior_room:
            new_room = Room(name=room_name, summary=summary,
                            items=items, photos=photos)
            built[room_name] = merge_room_with_prior(prior_room, new_room, code)
        else:
            items = merge_items(items, code)
            built[room_name] = Room(name=room_name, summary=summary,
                                    items=items, photos=photos)

    if detections:
        from .merge import attach_detector_crops, ground_missing_crops
        for room in built.values():
            attach_detector_crops(room.items, detections)
        if detector and detector.available and detector.mode == "text":
            photo_paths: dict[str, Path] = {}
            for photos in selected.values():
                for p in photos:
                    photo_paths[p.id] = _full_path(capture_dir, p.path)
            for room in built.values():
                n = ground_missing_crops(
                    room.items, photo_paths, detector, work_dir / "crops",
                    detections=detections)
                if n:
                    log.info("item-conditioned grounding attached %d crop(s) in %s",
                             n, room.name)

    if prior:
        built_by_lower = {k.lower(): k for k in built}
        rooms: list[Room] = []
        for r in prior.rooms:
            key = built_by_lower.pop(r.name.lower(), None)
            rooms.append(built[key] if key else r)
        rooms.extend(built[built_by_lower[k]] for k in sorted(built_by_lower))
        inv.rooms = rooms
    else:
        inv.rooms = [built[k] for k in sorted(built)]

    progress.rendering(opts.progress_file)
    outputs = render(inv, capture_dir, out_dir, pdf=not opts.no_pdf)
    progress.done(opts.progress_file)
    emit(f"\n{inv.item_count()} items across {len(inv.rooms)} rooms, "
         f"{inv.photo_count()} photos.")
    for kind, path in outputs.items():
        emit(f"  {kind:5} {path}")
    if failures:
        emit(f"\nWARNING: describe failed for: {', '.join(failures)}. "
             "Re-run the same command with --resume to retry only those rooms.",
             file=sys.stderr)
        return BuildResult(1, detail=out.getvalue()[-2000:],
                            failures=failures, outputs=outputs)
    emit("\nReview the report, edit inventory.json if needed, and re-render "
         "with: homeinventory render")
    return BuildResult(0, detail=out.getvalue()[-2000:], outputs=outputs)
