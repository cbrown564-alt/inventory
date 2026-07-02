"""homeinventory CLI.

  homeinventory guide                          # print the photo capture checklist
  homeinventory build CAPTURE_DIR -o OUT_DIR   # run the full pipeline
  homeinventory review CAPTURE_DIR -o OUT_DIR  # local review web app (--share
                                               # adds a tenant link)
  homeinventory check CAPTURE_DIR              # detector-only coverage check
  homeinventory compare CHECKIN CHECKOUT       # v2 (stub)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from .schema import Inventory, Item, Room

log = logging.getLogger("homeinventory")

DETECT_MODE_CHOICES = ("text", "prompt_free")


def _detector_from_args(args) -> "Detector | None":
    from .detect import Detector, default_model

    if getattr(args, "no_detect", False):
        return None
    mode = getattr(args, "detect_mode", "text")
    model = getattr(args, "detect_model", None) or default_model(mode)
    return Detector(
        model_name=model,
        mode=mode,
        conf=args.det_conf,
        device=getattr(args, "device", None),
    )


def _add_detect_args(p):
    p.add_argument("--detect-mode", choices=DETECT_MODE_CHOICES, default="text",
                   help="YOLOE mode: text (household vocabulary) or prompt_free "
                        "(built-in LVIS/Objects365 vocab)")
    p.add_argument("--detect-model", default=None,
                   help="override YOLOE weights (default follows --detect-mode)")
    p.add_argument("--device", default=None,
                   help="torch device for YOLOE (cpu, cuda, 0, …)")


GUIDE = """\
HOMEINVENTORY CAPTURE GUIDE
===========================
Folder layout: one folder per room inside your capture folder, e.g.

  capture/
    Living Room/   Kitchen/   Bedroom 1/   Bathroom/   Hallway/

Photos beat video for quality; a steady, slow video per room also works
(sharp keyframes are extracted automatically). Keep your phone's date/time
correct — EXIF timestamps go into the evidence manifest.

PER ROOM (~15-25 photos):
  1. Wide shot of each wall, floor-to-ceiling           (4 photos)
  2. Floor coverage + close-up of any marks             (2-3)
  3. Ceiling and light fittings                         (1-2)
  4. Door (both sides), window(s) incl. frames/sills    (2-4)
  5. Each appliance: front + inside + behind if movable (2-3 each)
  6. Each large furniture item: front + wear points     (1-2 each)
  7. EVERY existing defect close-up, with context shot  (as needed)

WHOLE PROPERTY (put in a "General" folder):
  - All meters (close enough to read the numbers)
  - Smoke / CO alarms (one photo each, press test button)
  - Keys handed over, laid out on a plain surface
  - Boiler, stopcock, fuse box

TIPS: turn all lights on, open curtains, shoot landscape, hold still a
beat before each shot, avoid your reflection in mirrors/windows.
"""


def cmd_guide(_args) -> int:
    print(GUIDE)
    return 0


def _full_path(capture_dir: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else capture_dir / p


def _checkpoint_name(room_name: str) -> str:
    return re.sub(r"[^\w\- ]+", "_", room_name) + ".json"


def _load_prior(args, out_dir: Path) -> tuple[Inventory | None, bool]:
    """Return (prior inventory, preserve_hand_edits) for a rebuild."""
    inv_path = out_dir / "inventory.json"
    only = {r.strip().lower() for r in args.room.split(",")} if args.room else None
    preserve = args.from_json is not None
    if preserve:
        path = Path(args.from_json) if args.from_json else inv_path
        if not path.is_file():
            print(f"error: --from-json file not found: {path}", file=sys.stderr)
            return None, True
        return Inventory.from_json(path.read_text(encoding="utf-8")), True
    if only and inv_path.exists():
        return Inventory.from_json(inv_path.read_text(encoding="utf-8")), False
    return None, False


def cmd_build(args) -> int:
    from .describe import FatalBackendError, get_backend
    from .ingest import ingest
    from .integrity import build_manifest
    from .merge import merge_items, merge_room_with_prior, room_code
    from .report import render

    capture_dir = Path(args.capture_dir)
    out_dir = Path(args.out)
    if not capture_dir.is_dir():
        print(f"error: capture dir not found: {capture_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "work"

    # 1. ingest
    rooms_photos = ingest(capture_dir, work_dir)
    if not rooms_photos:
        print("error: no photos or videos found (see `homeinventory guide`)",
              file=sys.stderr)
        return 2
    n_photos = sum(len(v) for v in rooms_photos.values())
    log.info("ingested %d photos across %d rooms", n_photos, len(rooms_photos))

    # 2. integrity manifest
    build_manifest(capture_dir, rooms_photos, out_dir / "manifest.json")

    only = {r.strip().lower() for r in args.room.split(",")} if args.room else None
    selected = {name: photos for name, photos in rooms_photos.items()
                if not only or name.lower() in only}
    if not selected:
        print(f"error: --room matched nothing; available rooms: "
              f"{', '.join(sorted(rooms_photos))}", file=sys.stderr)
        return 2

    prior, preserve_edits = _load_prior(args, out_dir)
    if prior is None and args.from_json is not None:
        return 2

    # 3. detect (only the rooms being built)
    detector = _detector_from_args(args)
    detections: dict[str, list] = {}
    if detector:
        for photos in selected.values():
            for p in photos:
                detections[p.id] = detector.detect(_full_path(capture_dir, p.path),
                                                   crops_dir=work_dir / "crops")
        if not detector.available:
            log.warning("detector unavailable — continuing without crops/hints")

    # partial rebuild keeps every room not named in --room; --from-json also
    # preserves hand-edits inside rebuilt rooms

    # 4-5. describe + merge, room by room, checkpointing as we go
    try:
        backend = get_backend(args.backend, model=args.model,
                              base_url=args.base_url)
    except FatalBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    inv = Inventory(
        property_address=args.address or (prior.property_address if prior else ""),
        inspected_by=args.inspector or (prior.inspected_by if prior else ""),
        agent_name=args.agent_name or (prior.agent_name if prior else ""),
        agent_phone=args.agent_phone or (prior.agent_phone if prior else ""),
        property_type=args.property_type or (prior.property_type if prior else ""),
        tenant_name=args.tenant or (prior.tenant_name if prior else ""),
        landlord_name=args.landlord or (prior.landlord_name if prior else ""),
        report_ref=args.report_ref or (prior.report_ref if prior else ""),
        describe_backend=f"{backend.name}"
                         + (f" ({getattr(backend, 'model', None)})"
                            if getattr(backend, "model", None) else ""),
        notes=args.notes or (prior.notes if prior else ""),
    )
    if prior and preserve_edits:
        inv.inspected_at = prior.inspected_at
        inv.signatures = list(prior.signatures)
        if prior.schedule_summary:
            inv.schedule_summary = list(prior.schedule_summary)
    used_codes: set[str] = set()
    if prior:  # reserve item-id prefixes we are keeping
        for r in prior.rooms:
            if only and r.name.lower() in only and not preserve_edits:
                continue
            for it in r.items:
                code = it.id.rsplit("-", 1)[0]
                if code:
                    used_codes.add(code)

    ckpt_dir = work_dir / "checkpoints"
    if not args.resume and ckpt_dir.exists():
        shutil.rmtree(ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    built: dict[str, Room] = {}
    failures: list[str] = []
    for room_name in sorted(selected):
        photos = selected[room_name]
        ckpt = ckpt_dir / _checkpoint_name(room_name)
        if args.resume and ckpt.exists():
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
                print(f"error: {e}", file=sys.stderr)
                return 2
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
                 # LocalBackend records per-room Ollama timing (total wall
                 # time, prompt/eval token counts + throughput). Absent on
                 # other backends and on --resume (kept from the prior ckpt).
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

    # 6. report
    outputs = render(inv, capture_dir, out_dir, pdf=not args.no_pdf)
    print(f"\n{inv.item_count()} items across {len(inv.rooms)} rooms, "
          f"{inv.photo_count()} photos.")
    for kind, path in outputs.items():
        print(f"  {kind:5} {path}")
    if failures:
        print(f"\nWARNING: describe failed for: {', '.join(failures)}. "
              "Re-run the same command with --resume to retry only those rooms.",
              file=sys.stderr)
        return 1
    print("\nReview the report, edit inventory.json if needed, and re-render "
          "with: homeinventory render", flush=True)
    return 0


def cmd_render(args) -> int:
    """Re-render the report from an edited inventory.json (review loop)."""
    from .report import render
    out_dir = Path(args.out)
    inv = Inventory.from_json((out_dir / "inventory.json").read_text(encoding="utf-8"))
    render(inv, Path(args.capture_dir), out_dir, pdf=not args.no_pdf)
    print(f"re-rendered {out_dir / 'inventory.html'}")
    return 0


def cmd_review(args) -> int:
    """Serve the local review app (Level 2); --share adds the tenant link
    (Level 3). See docs/05-review-experience.md."""
    from .review import serve

    try:
        httpd = serve(Path(args.capture_dir), Path(args.out), port=args.port,
                      share=args.share, backend=args.backend, model=args.model,
                      base_url=args.base_url, open_browser=not args.no_open)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: could not bind port {args.port}: {e}", file=sys.stderr)
        return 2
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped — edits are already saved in inventory.json")
    finally:
        httpd.server_close()
    return 0


def cmd_check(args) -> int:
    """Detector-only capture coverage check — flags per-room gaps before the
    (paid) describe step. Cannot hallucinate items; only prompts a second look."""
    from .coverage import check_capture
    from .ingest import ingest

    capture_dir = Path(args.capture_dir)
    if not capture_dir.is_dir():
        print(f"error: capture dir not found: {capture_dir}", file=sys.stderr)
        return 2
    work_dir = Path(args.out) / "work" if args.out else capture_dir / ".check-work"
    rooms = ingest(capture_dir, work_dir)
    if not rooms:
        print("error: no photos or videos found (see `homeinventory guide`)",
              file=sys.stderr)
        return 2
    if args.room:
        only = {r.strip().lower() for r in args.room.split(",")}
        rooms = {k: v for k, v in rooms.items() if k.lower() in only}
        if not rooms:
            print("error: --room matched nothing", file=sys.stderr)
            return 2

    report = check_capture(capture_dir, rooms, conf=args.det_conf,
                           device=getattr(args, "device", None))
    if report is None:
        print("error: detector unavailable — install the detect extra:\n"
              "  pip install homeinventory[detect]", file=sys.stderr)
        return 2
    gaps_total = 0
    for room, gaps in report.items():
        if gaps:
            gaps_total += len(gaps)
            for g in gaps:
                print(f"  GAP  {room}: no {g} seen — photograph it or mark N/A")
        else:
            print(f"  ok   {room}: expected items all covered")
    if gaps_total:
        print(f"\n{gaps_total} coverage gap(s). The detector only checks "
              "presence — it cannot judge photo quality.")
        return 1
    print("\nNo coverage gaps against the per-room checklist.")
    return 0


def cmd_compare(_args) -> int:
    print("compare (check-in vs check-out) is the v2 feature — see "
          "docs/03-implementation-plan.md milestone 4.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="homeinventory",
                                     description="AI property inventory reports")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("guide", help="print the photo capture checklist") \
       .set_defaults(func=cmd_guide)

    b = sub.add_parser("build", help="build a report from a capture folder")
    b.add_argument("capture_dir")
    b.add_argument("-o", "--out", default="report")
    b.add_argument("--backend", choices=["claude", "openai", "local", "offline"],
                   default="claude")
    b.add_argument("--model", default=None,
                   help="model id for the backend: claude default "
                        "claude-opus-4-8 (claude-haiku-4-5 is the budget "
                        "option); openai default gpt-4.1-mini (gemini-* "
                        "models route to Google automatically); local "
                        "default qwen3.5:9b (any Ollama vision model)")
    b.add_argument("--base-url", default=None,
                   help="override the API base URL for --backend openai "
                        "(any OpenAI-compatible server)")
    b.add_argument("--address", help="property address for the cover page")
    b.add_argument("--inspector", help="name of the person attesting the report")
    b.add_argument("--agent-name", help="clerk / letting agent company name for the cover")
    b.add_argument("--agent-phone", help="agent contact phone for the PDF footer")
    b.add_argument("--property-type",
                   help="e.g. '1 Bedroom furnished apartment' for Schedule of Condition")
    b.add_argument("--tenant", help="tenant name(s) for the cover page")
    b.add_argument("--landlord", help="landlord or agent name for the cover page")
    b.add_argument("--report-ref", help="report reference number")
    b.add_argument("--notes", help="general notes for the report front matter")
    b.add_argument("--room", help="only (re)build these rooms, comma-separated; "
                                  "other rooms are kept from the existing inventory.json")
    b.add_argument("--from-json", nargs="?", const="", metavar="PATH",
                   help="preserve hand-edits from inventory.json when rebuilding "
                        "(default: OUT_DIR/inventory.json when the flag is given alone)")
    b.add_argument("--resume", action="store_true",
                   help="reuse per-room checkpoints from a previous run "
                        "(retries only rooms that failed or were not described)")
    b.add_argument("--no-detect", action="store_true",
                   help="skip YOLOE detection (no crops / hints)")
    _add_detect_args(b)
    b.add_argument("--det-conf", type=float, default=0.25)
    b.add_argument("--no-pdf", action="store_true")
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("render", help="re-render report from edited inventory.json")
    r.add_argument("capture_dir")
    r.add_argument("-o", "--out", default="report")
    r.add_argument("--no-pdf", action="store_true")
    r.set_defaults(func=cmd_render)

    rv = sub.add_parser("review",
                        help="serve the local review web app (edit, annotate, "
                             "sign; --share adds a tenant link)")
    rv.add_argument("capture_dir")
    rv.add_argument("-o", "--out", default="report")
    rv.add_argument("--port", type=int, default=8484)
    rv.add_argument("--share", action="store_true",
                    help="also serve a token-protected tenant link on the LAN "
                         "(comments + countersignature)")
    rv.add_argument("--backend", choices=["claude", "openai", "local", "offline"],
                    default="claude", help="backend used by 'Re-describe room'")
    rv.add_argument("--model", default=None)
    rv.add_argument("--base-url", default=None)
    rv.add_argument("--no-open", action="store_true",
                    help="don't open the browser automatically")
    rv.set_defaults(func=cmd_review)

    ck = sub.add_parser("check",
                        help="detector-only coverage check of a capture folder")
    ck.add_argument("capture_dir")
    ck.add_argument("-o", "--out", default=None,
                    help="reuse a report dir's work folder for video keyframes")
    ck.add_argument("--room", help="only check these rooms, comma-separated")
    _add_detect_args(ck)
    ck.add_argument("--det-conf", type=float, default=0.25)
    ck.set_defaults(func=cmd_check)

    c = sub.add_parser("compare", help="check-in vs check-out comparison (v2)")
    c.add_argument("checkin_dir", nargs="?")
    c.add_argument("checkout_dir", nargs="?")
    c.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
