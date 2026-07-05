#!/usr/bin/env python3
"""Lightweight bbox labelling helper for InventoryFlex (ML-E11, docs/19).

Defines the labels_boxes.json schema, validates entries against gold labels,
and renders an HTML gallery of capture photos with notable items to annotate.

Full pixel-accurate boxing is done by editing JSON (or exporting to CVAT —
see ``export-cvat`` stub). Coordinates are pixel xyxy, origin top-left, same
convention as homeinventory.detect.Detection.

Usage:
    uv run python evals/label_boxes.py schema
    uv run python evals/label_boxes.py gallery \\
        benchmarks/inventoryflex/capture \\
        evals/fixtures/inventoryflex/labels.json \\
        -o /tmp/bbox-gallery.html
    uv run python evals/label_boxes.py validate \\
        evals/fixtures/inventoryflex/labels_boxes.json \\
        evals/fixtures/inventoryflex/labels.json
    uv run python evals/label_boxes.py stats \\
        evals/fixtures/inventoryflex/labels_boxes.json

Capture photos are not committed — extract first:

    uv run python benchmarks/extract_inventoryflex.py
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE = ROOT / "benchmarks" / "inventoryflex" / "capture"
DEFAULT_LABELS = ROOT / "evals" / "fixtures" / "inventoryflex" / "labels.json"
DEFAULT_BOXES = ROOT / "evals" / "fixtures" / "inventoryflex" / "labels_boxes.json"
DEFAULT_SPLIT = ROOT / "evals" / "splits" / "inventoryflex.json"

ML_E11_ROOMS = ("Bathroom", "Reception & Open Plan Kitchen")

SCHEMA_DOC = {
    "schema_version": 1,
    "description": "Gold bounding boxes for InventoryFlex detection eval (ML-E11).",
    "fields": {
        "id": "unique string slug (room-item-photo)",
        "room": "must match labels.json room name",
        "photo": "filename under capture/<room>/",
        "item_name": "display name for the labeler",
        "gold_item": "must match labels.json item name in that room",
        "notable": "bool — align with gold notable flag",
        "box_xyxy": "[x1, y1, x2, y2] pixels, origin top-left; x2>x1, y2>y1",
        "labeler": "who drew the box",
        "verified": "bool — second review complete",
        "_example": "optional — true for template placeholders (ignored in metrics)",
    },
    "target": "50–100 boxes across Bathroom + Reception & Open Plan Kitchen (val split)",
    "split_ref": "evals/splits/inventoryflex.json val_rooms",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def gold_items_by_room(labels: dict) -> dict[str, list[dict]]:
    return {room: data.get("items", [])
            for room, data in labels.get("rooms", {}).items()}


def gold_names(room_items: list[dict]) -> set[str]:
    return {item["name"] for item in room_items}


def validate_boxes(boxes_doc: dict, labels: dict,
                   *, require_photos: bool = False,
                   capture_dir: Path | None = None) -> list[str]:
    """Return validation errors."""
    errs: list[str] = []
    boxes = boxes_doc.get("boxes")
    if not isinstance(boxes, list):
        return ["missing 'boxes' array"]

    by_room = gold_items_by_room(labels)
    seen_ids: set[str] = set()
    real_count = 0

    for i, box in enumerate(boxes):
        prefix = f"boxes[{i}]"
        if box.get("_example"):
            continue
        real_count += 1
        bid = box.get("id")
        if not bid:
            errs.append(f"{prefix}: missing id")
        elif bid in seen_ids:
            errs.append(f"{prefix}: duplicate id {bid!r}")
        else:
            seen_ids.add(bid)

        room = box.get("room")
        if room not in by_room:
            errs.append(f"{prefix}: unknown room {room!r}")
            continue

        gold_item = box.get("gold_item")
        if gold_item not in gold_names(by_room[room]):
            errs.append(f"{prefix}: gold_item {gold_item!r} not in labels.json "
                        f"for {room}")

        photo = box.get("photo")
        if not photo:
            errs.append(f"{prefix}: missing photo")
        elif require_photos and capture_dir:
            photo_path = capture_dir / room / photo
            if not photo_path.is_file():
                errs.append(f"{prefix}: photo not found {photo_path}")

        xyxy = box.get("box_xyxy")
        if not isinstance(xyxy, list) or len(xyxy) != 4:
            errs.append(f"{prefix}: box_xyxy must be [x1,y1,x2,y2]")
        else:
            try:
                x1, y1, x2, y2 = (float(v) for v in xyxy)
            except (TypeError, ValueError):
                errs.append(f"{prefix}: box_xyxy values must be numbers")
            else:
                if x2 <= x1 or y2 <= y1:
                    errs.append(f"{prefix}: box must have x2>x1 and y2>y1")
                if any(v < 0 for v in (x1, y1, x2, y2)):
                    errs.append(f"{prefix}: negative box coordinate")

    target = boxes_doc.get("target", {})
    min_boxes = target.get("min_boxes", 50)
    if real_count and real_count < min_boxes:
        errs.append(f"only {real_count} non-example boxes (target min {min_boxes})")
    return errs


def cmd_schema(_args: argparse.Namespace) -> int:
    print(json.dumps(SCHEMA_DOC, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    data = load_json(args.boxes.resolve())
    boxes = data.get("boxes", [])
    examples = sum(1 for b in boxes if b.get("_example"))
    real = [b for b in boxes if not b.get("_example")]
    by_room: dict[str, int] = {}
    for b in real:
        by_room[b.get("room", "?")] = by_room.get(b.get("room", "?"), 0) + 1
    summary = {
        "total": len(boxes),
        "examples": examples,
        "labelled": len(real),
        "by_room": by_room,
        "target": data.get("target"),
    }
    print(json.dumps(summary, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    boxes_doc = load_json(args.boxes.resolve())
    labels = load_json(args.labels.resolve())
    capture = args.capture.resolve() if args.capture else None
    errs = validate_boxes(
        boxes_doc, labels,
        require_photos=args.check_photos,
        capture_dir=capture,
    )
    if errs:
        for e in errs:
            print(f"error: {e}", file=sys.stderr)
        return 1
    n_real = sum(1 for b in boxes_doc.get("boxes", []) if not b.get("_example"))
    print(f"ok — {n_real} labelled boxes "
          f"({sum(1 for b in boxes_doc.get('boxes', []) if b.get('_example'))} examples skipped)")
    return 0


def list_photos(capture_dir: Path, room: str) -> list[Path]:
    room_dir = capture_dir / room
    if not room_dir.is_dir():
        return []
    return sorted(room_dir.glob("*.jpg")) + sorted(room_dir.glob("*.jpeg"))


def render_gallery_html(
        *,
        html_path: Path,
        capture_dir: Path,
        labels: dict,
        boxes_doc: dict | None,
        rooms: list[str],
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    boxes_by_key: dict[tuple[str, str], list[dict]] = {}
    if boxes_doc:
        for b in boxes_doc.get("boxes", []):
            key = (b.get("room", ""), b.get("photo", ""))
            boxes_by_key.setdefault(key, []).append(b)

    parts = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        "<title>InventoryFlex bbox labelling gallery</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:1rem;background:#111;color:#eee}",
        "h1,h2{margin:0.5rem 0}",
        ".meta{color:#aaa;font-size:14px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}",
        ".cell{background:#222;border-radius:8px;overflow:hidden;border:2px solid #333}",
        ".cell.has-box{border-color:#4a4}",
        ".cell img{width:100%;display:block;aspect-ratio:4/3;object-fit:contain;background:#000}",
        ".cap{padding:8px;font-size:12px;line-height:1.4}",
        ".items{color:#8cf;margin-top:4px}",
        ".box{color:#6f6}",
        ".example{color:#aa6}",
        "ul{margin:4px 0;padding-left:18px}",
        "</style></head><body>",
        "<h1>ML-E11 bbox labelling gallery</h1>",
        f"<p class='meta'>Capture: {html.escape(str(capture_dir))}</p>",
        "<p class='meta'>Annotate by editing labels_boxes.json — "
        "box_xyxy in pixels [x1,y1,x2,y2]. Run validate when done.</p>",
    ]

    for room in rooms:
        items = labels.get("rooms", {}).get(room, {}).get("items", [])
        notable = [it for it in items if it.get("notable", True)]
        photos = list_photos(capture_dir, room)
        parts.append(f"<h2>{html.escape(room)}</h2>")
        parts.append(f"<p class='meta'>{len(photos)} photos · "
                     f"{len(notable)} notable gold items to box</p>")
        if notable:
            parts.append("<p class='items'><strong>Notable items:</strong> "
                         + ", ".join(html.escape(it["name"]) for it in notable[:20]))
            if len(notable) > 20:
                parts.append(f" … +{len(notable) - 20} more")
            parts.append("</p>")
        if not photos:
            parts.append("<p class='meta'>No photos — run "
                         "benchmarks/extract_inventoryflex.py</p>")
            continue
        parts.append("<div class='grid'>")
        for photo_path in photos:
            key = (room, photo_path.name)
            box_list = boxes_by_key.get(key, [])
            real_boxes = [b for b in box_list if not b.get("_example")]
            has_box = bool(real_boxes)
            cls = "cell has-box" if has_box else "cell"
            try:
                href = html.escape(str(photo_path.relative_to(html_path.parent)))
            except ValueError:
                href = html.escape(str(photo_path))
            parts.append(f"<div class='{cls}'><img src='{href}' "
                         f"alt='{html.escape(photo_path.name)}' loading='lazy'>")
            parts.append(f"<div class='cap'><strong>{html.escape(photo_path.name)}</strong>")
            if box_list:
                parts.append("<ul>")
                for b in box_list:
                    tag = "example" if b.get("_example") else "box"
                    xy = b.get("box_xyxy", [])
                    parts.append(
                        f"<li class='{tag}'>{html.escape(b.get('gold_item', '?'))}: "
                        f"{xy}</li>")
                parts.append("</ul>")
            parts.append("</div></div>")
        parts.append("</div>")

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def cmd_gallery(args: argparse.Namespace) -> int:
    capture = args.capture.resolve()
    labels = load_json(args.labels.resolve())
    boxes_doc = load_json(args.boxes.resolve()) if args.boxes else None

    if args.rooms:
        rooms = args.rooms
    else:
        rooms = list(ML_E11_ROOMS)

    if not capture.is_dir():
        print(f"capture dir missing: {capture}", file=sys.stderr)
        print("run: uv run python benchmarks/extract_inventoryflex.py", file=sys.stderr)
        return 1

    out = args.output.resolve()
    render_gallery_html(
        html_path=out,
        capture_dir=capture,
        labels=labels,
        boxes_doc=boxes_doc,
        rooms=rooms,
    )
    print(f"wrote {out}")
    return 0


def cmd_export_cvat(args: argparse.Namespace) -> int:
    """Stub — document expected CVAT export mapping."""
    data = load_json(args.boxes.resolve())
    n = sum(1 for b in data.get("boxes", []) if not b.get("_example"))
    print("CVAT export stub — import InventoryFlex photos as a CVAT task, draw "
          "boxes, then map CVAT XML <box> attributes to labels_boxes.json fields:")
    print(json.dumps({
        "mapping": {
            "cvat label name": "gold_item",
            "xtl/ytl/xbr/ybr": "box_xyxy (round to int pixels)",
            "frame filename": "photo",
            "subset": "room name → labels_boxes.room",
        },
        "current_labelled_boxes": n,
        "note": "Re-run validate after manual merge into labels_boxes.json",
    }, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    schema = sub.add_parser("schema", help="print JSON schema documentation")
    schema.set_defaults(func=cmd_schema)

    stats = sub.add_parser("stats", help="count labelled vs example boxes")
    stats.add_argument("boxes", type=Path, nargs="?", default=DEFAULT_BOXES)
    stats.set_defaults(func=cmd_stats)

    val = sub.add_parser("validate", help="validate labels_boxes.json")
    val.add_argument("boxes", type=Path, nargs="?", default=DEFAULT_BOXES)
    val.add_argument("labels", type=Path, nargs="?", default=DEFAULT_LABELS)
    val.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE,
                     help="capture root for photo existence checks")
    val.add_argument("--check-photos", action="store_true",
                     help="require each photo file to exist under capture/")
    val.set_defaults(func=cmd_validate)

    gal = sub.add_parser("gallery", help="HTML contact sheet for bbox labelling")
    gal.add_argument("capture", type=Path, nargs="?", default=DEFAULT_CAPTURE)
    gal.add_argument("labels", type=Path, nargs="?", default=DEFAULT_LABELS)
    gal.add_argument("-o", "--output", type=Path,
                     default=ROOT / "evals" / "fixtures" / "inventoryflex"
                     / "bbox-gallery.html")
    gal.add_argument("--boxes", type=Path, default=DEFAULT_BOXES,
                     help="overlay existing boxes in gallery")
    gal.add_argument("--rooms", nargs="*", default=None,
                     help=f"rooms to show (default: {ML_E11_ROOMS})")
    gal.set_defaults(func=cmd_gallery)

    cvat = sub.add_parser("export-cvat", help="CVAT export mapping stub")
    cvat.add_argument("boxes", type=Path, nargs="?", default=DEFAULT_BOXES)
    cvat.set_defaults(func=cmd_export_cvat)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
