"""homeinventory CLI.

  homeinventory guide                          # print the photo capture checklist
  homeinventory build CAPTURE_DIR -o OUT_DIR   # run the full pipeline
  homeinventory compare CHECKIN CHECKOUT       # v2 (stub)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .schema import Inventory, Room

log = logging.getLogger("homeinventory")

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


def cmd_build(args) -> int:
    from .describe import get_backend
    from .detect import Detector
    from .ingest import ingest
    from .integrity import build_manifest
    from .merge import merge_items, room_code
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

    # 3. detect
    detector = Detector(conf=args.det_conf) if not args.no_detect else None
    detections: dict[str, list] = {}
    if detector:
        for room, photos in rooms_photos.items():
            for p in photos:
                full = capture_dir / p.path if not Path(p.path).is_absolute() else Path(p.path)
                detections[p.id] = detector.detect(full, crops_dir=work_dir / "crops")
        if not detector.available:
            log.warning("detector unavailable — continuing without crops/hints")

    # 4-5. describe + merge, room by room
    backend = get_backend(args.backend, model=args.model)
    inv = Inventory(
        property_address=args.address or "",
        inspected_by=args.inspector or "",
        describe_backend=f"{backend.name}"
                         + (f" ({args.model})" if args.backend == "claude" and args.model else ""),
        notes=args.notes or "",
    )
    used_codes: set[str] = set()
    only = {r.strip().lower() for r in args.room.split(",")} if args.room else None
    for room_name in sorted(rooms_photos):
        if only and room_name.lower() not in only:
            continue
        photos = rooms_photos[room_name]
        paths = [capture_dir / p.path if not Path(p.path).is_absolute() else Path(p.path)
                 for p in photos]
        log.info("describing %s (%d photos, backend=%s)…",
                 room_name, len(photos), backend.name)
        summary, items = backend.describe_room(room_name, photos, paths, detections)
        items = merge_items(items, room_code(room_name, used_codes))
        inv.rooms.append(Room(name=room_name, summary=summary,
                              items=items, photos=photos))

    # 6. report
    outputs = render(inv, capture_dir, out_dir, pdf=not args.no_pdf)
    print(f"\n{inv.item_count()} items across {len(inv.rooms)} rooms, "
          f"{inv.photo_count()} photos.")
    for kind, path in outputs.items():
        print(f"  {kind:5} {path}")
    print("\nReview the report, edit inventory.json if needed, and re-render "
          "with: homeinventory render", flush=True)
    return 0


def cmd_render(args) -> int:
    """Re-render the report from an edited inventory.json (review loop)."""
    from .report import render
    out_dir = Path(args.out)
    inv = Inventory.from_json((out_dir / "inventory.json").read_text())
    render(inv, Path(args.capture_dir), out_dir, pdf=not args.no_pdf)
    print(f"re-rendered {out_dir / 'inventory.html'}")
    return 0


def cmd_compare(_args) -> int:
    print("compare (check-in vs check-out) is the v2 feature — see "
          "docs/03-implementation-plan.md milestone 3.", file=sys.stderr)
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
    b.add_argument("--backend", choices=["claude", "offline"], default="claude")
    b.add_argument("--model", default=None,
                   help="claude model id (default claude-opus-4-8; "
                        "claude-haiku-4-5 is the budget option)")
    b.add_argument("--address", help="property address for the cover page")
    b.add_argument("--inspector", help="name of the person attesting the report")
    b.add_argument("--notes", help="general notes for the report front matter")
    b.add_argument("--room", help="only (re)build these rooms, comma-separated")
    b.add_argument("--no-detect", action="store_true",
                   help="skip YOLOE detection (no crops / hints)")
    b.add_argument("--det-conf", type=float, default=0.25)
    b.add_argument("--no-pdf", action="store_true")
    b.set_defaults(func=cmd_build)

    r = sub.add_parser("render", help="re-render report from edited inventory.json")
    r.add_argument("capture_dir")
    r.add_argument("-o", "--out", default="report")
    r.add_argument("--no-pdf", action="store_true")
    r.set_defaults(func=cmd_render)

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
