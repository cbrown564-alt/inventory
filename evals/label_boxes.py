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
    uv run python evals/label_boxes.py bootstrap \\
        benchmarks/inventoryflex/capture \\
        evals/fixtures/inventoryflex/labels.json \\
        -o evals/fixtures/inventoryflex/labels_boxes.json
    uv run python evals/label_boxes.py render-review \\
        benchmarks/inventoryflex/capture \\
        evals/fixtures/inventoryflex/labels_boxes.json \\
        -o evals/fixtures/inventoryflex/bbox-review
    uv run python evals/label_boxes.py render-carousel

Capture photos are not committed — extract first:

    uv run python benchmarks/extract_inventoryflex.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeinventory.det_match import gold_for_detection  # noqa: E402
from homeinventory.detect import Detector  # noqa: E402
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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _best_gold_match(label: str, gold_items: list[dict], threshold: float) -> dict | None:
    result = gold_for_detection(
        label, gold_items, mode="bootstrap", threshold=threshold,
    )
    return result[0] if result else None


def bootstrap_boxes(
        *,
        capture_dir: Path,
        labels: dict,
        rooms: list[str],
        detector: Detector,
        match_threshold: float = 0.75,
        labeler: str = "yoloe-bootstrap",
        verified: bool = True,
        min_conf: float = 0.25,
) -> list[dict]:
    """Seed bbox gold from detector proposals matched to notable gold items."""
    boxes: list[dict] = []
    best_by_key: dict[tuple[str, str, str], tuple[float, dict]] = {}

    for room in rooms:
        gold_items = labels.get("rooms", {}).get(room, {}).get("items", [])
        for photo_path in list_photos(capture_dir, room):
            for det in detector.detect(photo_path):
                if det.confidence < min_conf:
                    continue
                gold = _best_gold_match(det.label, gold_items, match_threshold)
                if gold is None:
                    continue
                key = (room, photo_path.name, gold["name"])
                prev = best_by_key.get(key)
                if prev is None or det.confidence > prev[0]:
                    stem = photo_path.stem
                    bid = f"{_slug(room)}-{_slug(gold['name'])}-{stem}"
                    best_by_key[key] = (det.confidence, {
                        "id": bid,
                        "room": room,
                        "photo": photo_path.name,
                        "item_name": gold["name"],
                        "gold_item": gold["name"],
                        "notable": True,
                        "box_xyxy": list(det.box),
                        "det_label": det.label,
                        "det_confidence": round(det.confidence, 3),
                        "labeler": labeler,
                        "verified": verified,
                    })

    boxes.extend(entry for _, entry in sorted(best_by_key.values(),
                                              key=lambda kv: kv[1]["id"]))
    return boxes


def cmd_bootstrap(args: argparse.Namespace) -> int:
    capture = args.capture.resolve()
    labels = load_json(args.labels.resolve())
    rooms = args.rooms or list(ML_E11_ROOMS)

    if not capture.is_dir():
        print(f"capture dir missing: {capture}", file=sys.stderr)
        return 1

    detector = Detector(conf=args.conf, device=args.device)
    if not detector.available:
        print(f"detector unavailable: {getattr(detector, '_load_error', '?')}",
              file=sys.stderr)
        return 1

    boxes = bootstrap_boxes(
        capture_dir=capture,
        labels=labels,
        rooms=rooms,
        detector=detector,
        match_threshold=args.threshold,
        labeler=args.labeler,
        verified=not args.unverified,
        min_conf=args.conf,
    )

    out_doc = {
        "_schema_version": 1,
        "_source": (
            "ML-E11 bbox gold — YOLOE text-mode proposals matched to notable "
            "gold items (docs/19 §1.4). Review in bbox-gallery.html."
        ),
        "_schema_doc": "Run `uv run python evals/label_boxes.py schema` for field definitions.",
        "fixture": "inventoryflex",
        "labels_ref": "evals/fixtures/inventoryflex/labels.json",
        "split_ref": "evals/splits/inventoryflex.json",
        "rooms": rooms,
        "target": {
            "min_boxes": 50,
            "max_boxes": 100,
            "rooms": 2,
            "notable_only": True,
        },
        "boxes": boxes,
    }

    errs = validate_boxes(out_doc, labels)
    if errs:
        for e in errs:
            print(f"warning: {e}", file=sys.stderr)

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_doc, indent=2) + "\n", encoding="utf-8")
    verified_n = sum(1 for b in boxes if b.get("verified"))
    print(f"wrote {len(boxes)} boxes ({verified_n} verified) to {out}")
    return 0 if len(boxes) >= out_doc["target"]["min_boxes"] else 1


def _label_mismatch(box: dict) -> bool:
    gold = box.get("gold_item", "").lower()
    det = box.get("det_label", "").lower()
    if not gold or not det:
        return False
    return gold not in det and det not in gold


def _risk_flags(box: dict, img_w: int, img_h: int) -> list[str]:
    flags: list[str] = []
    conf = box.get("det_confidence", 1.0)
    if conf < 0.35:
        flags.append("low_conf")
    elif conf < 0.5:
        flags.append("med_conf")
    if _label_mismatch(box):
        flags.append("label_mismatch")
    x1, y1, x2, y2 = box["box_xyxy"]
    bw, bh = x2 - x1, y2 - y1
    if bw < 40 or bh < 40:
        flags.append("tiny_box")
    if x1 <= 2 or y1 <= 2 or x2 >= img_w - 2 or y2 >= img_h - 2:
        flags.append("edge_box")
    area_frac = (bw * bh) / max(1, img_w * img_h)
    if area_frac > 0.85:
        flags.append("huge_box")
    return flags


def render_review_pack(
        *,
        capture_dir: Path,
        boxes_doc: dict,
        out_dir: Path,
        pad_frac: float = 0.25,
) -> dict:
    """Render per-box review crops + manifest for agent/human adjudication."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = out_dir / "crops"
    full_dir = out_dir / "full"
    crops_dir.mkdir(exist_ok=True)
    full_dir.mkdir(exist_ok=True)

    by_photo: dict[tuple[str, str], list[dict]] = {}
    entries: list[dict] = []

    for box in boxes_doc.get("boxes", []):
        if box.get("_example"):
            continue
        key = (box["room"], box["photo"])
        by_photo.setdefault(key, []).append(box)

    for (room, photo), photo_boxes in sorted(by_photo.items()):
        photo_path = capture_dir / room / photo
        if not photo_path.is_file():
            continue
        img = Image.open(photo_path).convert("RGB")
        w, h = img.size
        full_out = full_dir / _slug(room) / photo
        full_out.parent.mkdir(parents=True, exist_ok=True)
        full_copy = img.copy()
        full_draw = ImageDraw.Draw(full_copy)
        for box in photo_boxes:
            x1, y1, x2, y2 = box["box_xyxy"]
            full_draw.rectangle([x1, y1, x2, y2], outline="#00ff66", width=3)
            full_draw.text((x1 + 2, max(0, y1 - 14)),
                           box["gold_item"][:24], fill="#00ff66")
        full_copy.save(full_out, quality=90)

        for box in photo_boxes:
            x1, y1, x2, y2 = box["box_xyxy"]
            pad_x = int((x2 - x1) * pad_frac)
            pad_y = int((y2 - y1) * pad_frac)
            cx1 = max(0, x1 - pad_x)
            cy1 = max(0, y1 - pad_y)
            cx2 = min(w, x2 + pad_x)
            cy2 = min(h, y2 + pad_y)
            crop = img.crop((cx1, cy1, cx2, cy2))
            draw = ImageDraw.Draw(crop)
            rx1, ry1 = x1 - cx1, y1 - cy1
            rx2, ry2 = x2 - cx1, y2 - cy1
            draw.rectangle([rx1, ry1, rx2, ry2], outline="#ff3333", width=2)
            crop_path = crops_dir / f"{box['id']}.jpg"
            crop.save(crop_path, quality=90)
            flags = _risk_flags(box, w, h)
            entries.append({
                "id": box["id"],
                "room": room,
                "photo": photo,
                "gold_item": box["gold_item"],
                "det_label": box.get("det_label"),
                "det_confidence": box.get("det_confidence"),
                "box_xyxy": box["box_xyxy"],
                "image_size": [w, h],
                "crop_path": str(crop_path.relative_to(out_dir)),
                "full_path": str(full_out.relative_to(out_dir)),
                "risk_flags": flags,
                "risk_score": len(flags) + (0 if box.get("det_confidence", 1) >= 0.5 else 1),
            })

    entries.sort(key=lambda e: (-e["risk_score"], e["id"]))
    manifest = {
        "schema_version": 1,
        "description": "ML-E11 bbox review pack — one crop per box for visual adjudication",
        "verdict_values": ["accept", "reject", "relocate", "uncertain"],
        "entries": entries,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for room in boxes_doc.get("rooms", ML_E11_ROOMS):
        room_entries = [e for e in entries if e["room"] == room]
        (out_dir / f"manifest-{_slug(room)}.json").write_text(
            json.dumps({**manifest, "room": room, "entries": room_entries}, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest


def cmd_render_review(args: argparse.Namespace) -> int:
    capture = args.capture.resolve()
    boxes_doc = load_json(args.boxes.resolve())
    out_dir = args.output.resolve()

    if not capture.is_dir():
        print(f"capture dir missing: {capture}", file=sys.stderr)
        return 1

    manifest = render_review_pack(
        capture_dir=capture,
        boxes_doc=boxes_doc,
        out_dir=out_dir,
        pad_frac=args.pad,
    )
    n = len(manifest["entries"])
    risky = sum(1 for e in manifest["entries"] if e["risk_flags"])
    print(f"wrote {n} review crops to {out_dir} ({risky} with risk flags)")
    return 0


def merge_reviews(pass1_paths: list[Path], pass2_path: Path | None = None) -> dict:
    """Merge first- and second-pass review JSON into adjudication queue."""
    pass1: dict[str, dict] = {}
    for path in pass1_paths:
        data = load_json(path)
        for v in data.get("verdicts", []):
            pass1[v["id"]] = v

    pass2: dict[str, dict] = {}
    if pass2_path and pass2_path.is_file():
        data = load_json(pass2_path)
        for v in data.get("verdicts", []):
            pass2[v["id"]] = v

    manifest_path = pass1_paths[0].parent / "manifest.json"
    if not manifest_path.is_file():
        manifest_path = DEFAULT_BOXES.parent / "bbox-review" / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else {"entries": []}
    by_id = {e["id"]: e for e in manifest.get("entries", [])}

    queue: list[dict] = []
    for bid, meta in by_id.items():
        v1 = pass1.get(bid, {})
        v2 = pass2.get(bid, {})
        verdict1 = v1.get("verdict", "missing")
        verdict2 = v2.get("verdict")
        reasons: list[str] = []
        if verdict1 in ("reject", "uncertain", "relocate"):
            reasons.append(f"pass1:{verdict1}")
        if verdict2 in ("reject", "uncertain", "relocate"):
            reasons.append(f"pass2:{verdict2}")
        if verdict1 != verdict2 and verdict2 and verdict1 != "missing":
            reasons.append("disagreement")
        if meta.get("risk_flags"):
            reasons.append("risk:" + ",".join(meta["risk_flags"]))
        if not reasons:
            continue
        queue.append({
            "id": bid,
            "room": meta.get("room"),
            "photo": meta.get("photo"),
            "gold_item": meta.get("gold_item"),
            "det_label": meta.get("det_label"),
            "det_confidence": meta.get("det_confidence"),
            "risk_flags": meta.get("risk_flags", []),
            "crop_path": meta.get("crop_path"),
            "full_path": meta.get("full_path"),
            "pass1_verdict": verdict1,
            "pass1_note": v1.get("note", ""),
            "pass2_verdict": verdict2,
            "pass2_note": v2.get("note", ""),
            "reasons": reasons,
            "priority": len(reasons) + meta.get("risk_score", 0),
        })

    queue.sort(key=lambda q: (-q["priority"], q["id"]))
    return {
        "schema_version": 1,
        "description": "Boxes needing human adjudication after agent review passes",
        "total_reviewed": len(by_id),
        "needs_adjudication": len(queue),
        "queue": queue,
    }


def cmd_adjudicate(args: argparse.Namespace) -> int:
    pass1 = [p.resolve() for p in args.pass1]
    pass2 = args.pass2.resolve() if args.pass2 else None
    out = args.output.resolve()
    result = merge_reviews(pass1, pass2)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote adjudication queue ({result['needs_adjudication']} items) to {out}")
    return 0


def apply_human_review(boxes_doc: dict, review: dict) -> tuple[dict, dict]:
    """Merge human carousel verdicts into labels_boxes.json."""
    verdicts = {v["id"]: v for v in review.get("verdicts", [])}
    kept: list[dict] = []
    stats = {"keep": 0, "drop": 0, "redraw": 0, "unsure": 0, "unchanged": 0}

    for box in boxes_doc.get("boxes", []):
        if box.get("_example"):
            continue
        v = verdicts.get(box["id"])
        if v is None:
            kept.append(box)
            stats["unchanged"] += 1
            continue
        verdict = v.get("verdict", "")
        if verdict == "drop":
            stats["drop"] += 1
            continue
        box = dict(box)
        box["human_review"] = {
            "verdict": verdict,
            "note": v.get("note", ""),
            "reviewed_at": v.get("reviewed_at"),
        }
        if verdict == "keep":
            box["verified"] = True
            box["labeler"] = "human-review"
            stats["keep"] += 1
        elif verdict == "redraw":
            box["verified"] = False
            box["needs_redraw"] = True
            box["labeler"] = "human-review"
            stats["redraw"] += 1
        elif verdict == "unsure":
            box["verified"] = False
            stats["unsure"] += 1
        else:
            stats["unchanged"] += 1
        kept.append(box)

    out = dict(boxes_doc)
    out["boxes"] = kept
    out["_human_review"] = {
        "source": review.get("exported_at"),
        "reviewer": review.get("reviewer", "human"),
        "summary": review.get("summary"),
        "applied": stats,
    }
    return out, stats


def cmd_apply_review(args: argparse.Namespace) -> int:
    boxes_doc = load_json(args.boxes.resolve())
    review = load_json(args.review.resolve())
    labels = load_json(args.labels.resolve())

    out_doc, stats = apply_human_review(boxes_doc, review)
    errs = validate_boxes(out_doc, labels)
    for e in errs:
        print(f"warning: {e}", file=sys.stderr)

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_doc, indent=2) + "\n", encoding="utf-8")
    n = len(out_doc["boxes"])
    print(f"applied human review → {n} boxes ({stats})")
    return 0 if n >= out_doc.get("target", {}).get("min_boxes", 50) else 1


def load_agent_reviews(review_dir: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Load pass-1 and pass-2 verdicts keyed by box id."""
    pass1: dict[str, dict] = {}
    for path in sorted(review_dir.glob("review-pass1-*.json")):
        for v in load_json(path).get("verdicts", []):
            pass1[v["id"]] = v
    pass2: dict[str, dict] = {}
    p2_path = review_dir / "review-pass2.json"
    if p2_path.is_file():
        for v in load_json(p2_path).get("verdicts", []):
            pass2[v["id"]] = v
    return pass1, pass2


def _box_key(box: dict) -> tuple[str, str, str]:
    return (box["room"], box["photo"], box["gold_item"])


def consensus_reject_keys(
        pass1: dict[str, dict],
        pass2: dict[str, dict],
) -> set[tuple[str, str, str]]:
    """(room, photo, gold_item) tuples where both agent passes rejected."""
    keys: set[tuple[str, str, str]] = set()
    all_ids = set(pass1) | set(pass2)
    for bid in all_ids:
        v1 = pass1.get(bid, {}).get("verdict")
        v2 = pass2.get(bid, {}).get("verdict")
        if v1 == "reject" and v2 == "reject":
            # recover key from pass1/pass2 metadata if present, else parse id
            meta = pass1.get(bid) or pass2.get(bid) or {}
            if "room" in meta:
                keys.add((meta["room"], meta["photo"], meta["gold_item"]))
    return keys


def build_consensus_reject_keys_from_manifest(
        review_dir: Path,
        pass1: dict[str, dict],
        pass2: dict[str, dict],
) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    manifest_path = review_dir / "manifest.json"
    if not manifest_path.is_file():
        return keys
    by_id = {e["id"]: e for e in load_json(manifest_path).get("entries", [])}
    for bid in set(pass1) | set(pass2):
        if pass1.get(bid, {}).get("verdict") != "reject":
            continue
        if pass2.get(bid, {}).get("verdict") != "reject":
            continue
        entry = by_id.get(bid)
        if entry:
            keys.add((entry["room"], entry["photo"], entry["gold_item"]))
    return keys


def trim_agent_consensus(
        boxes_doc: dict,
        review_dir: Path,
        *,
        human_review: dict | None = None,
) -> tuple[dict, dict]:
    """Drop bootstrap boxes with agent consensus reject; re-apply human overrides."""
    pass1, pass2 = load_agent_reviews(review_dir)
    reject_keys = build_consensus_reject_keys_from_manifest(review_dir, pass1, pass2)
    human_by_id = {}
    if human_review:
        human_by_id = {v["id"]: v for v in human_review.get("verdicts", [])}

    kept: list[dict] = []
    stats = {
        "bootstrap": 0,
        "consensus_drop": 0,
        "human_drop": 0,
        "human_keep": 0,
        "human_redraw": 0,
        "kept_bootstrap": 0,
    }

    for box in boxes_doc.get("boxes", []):
        if box.get("_example"):
            continue
        stats["bootstrap"] += 1
        bid = box["id"]
        human = human_by_id.get(bid)

        if human and human.get("verdict") == "drop":
            stats["human_drop"] += 1
            continue

        key = _box_key(box)
        if human is None and key in reject_keys:
            stats["consensus_drop"] += 1
            continue

        box = dict(box)
        if human:
            box["human_review"] = {
                "verdict": human["verdict"],
                "note": human.get("note", ""),
                "reviewed_at": human.get("reviewed_at"),
            }
            if human["verdict"] == "keep":
                box["verified"] = True
                box["labeler"] = "human-review"
                stats["human_keep"] += 1
            elif human["verdict"] == "redraw":
                box["verified"] = False
                box["needs_redraw"] = True
                box["labeler"] = "human-review"
                stats["human_redraw"] += 1
            else:
                stats["kept_bootstrap"] += 1
        else:
            box["verified"] = True
            box["labeler"] = box.get("labeler", "yoloe-bootstrap")
            stats["kept_bootstrap"] += 1
        kept.append(box)

    out = dict(boxes_doc)
    out["boxes"] = kept
    out["_trim"] = {
        "consensus_reject_keys": len(reject_keys),
        "stats": stats,
    }
    return out, stats


def cmd_trim_consensus(args: argparse.Namespace) -> int:
    boxes_doc = load_json(args.boxes.resolve())
    review_dir = args.review_dir.resolve()
    labels = load_json(args.labels.resolve())
    human = load_json(args.human.resolve()) if args.human else None

    out_doc, stats = trim_agent_consensus(boxes_doc, review_dir, human_review=human)
    errs = validate_boxes(out_doc, labels)
    for e in errs:
        print(f"warning: {e}", file=sys.stderr)

    out = args.output.resolve()
    out.write_text(json.dumps(out_doc, indent=2) + "\n", encoding="utf-8")
    n = len(out_doc["boxes"])
    print(f"trimmed → {n} boxes ({stats})")
    return 0 if n >= out_doc.get("target", {}).get("min_boxes", 50) else 1


def build_carousel_data(review_dir: Path) -> dict:
    """Assemble review carousel payload from manifest + agent reviews."""
    review_dir = review_dir.resolve()
    manifest = load_json(review_dir / "manifest.json")

    pass1: dict[str, dict] = {}
    for path in sorted(review_dir.glob("review-pass1-*.json")):
        for v in load_json(path).get("verdicts", []):
            pass1[v["id"]] = v

    pass2: dict[str, dict] = {}
    p2_path = review_dir / "review-pass2.json"
    if p2_path.is_file():
        for v in load_json(p2_path).get("verdicts", []):
            pass2[v["id"]] = v

    queue_ids: set[str] = set()
    queue_by_id: dict[str, dict] = {}
    adj_path = review_dir / "bbox-adjudication.json"
    if adj_path.is_file():
        for q in load_json(adj_path).get("queue", []):
            queue_ids.add(q["id"])
            queue_by_id[q["id"]] = q

    shortlist_ids: list[str] = []
    sl_path = review_dir / "bbox-adjudication-shortlist.json"
    if sl_path.is_file():
        for tier in load_json(sl_path).get("start_here", []):
            shortlist_ids.extend(tier.get("items", []))

    items: list[dict] = []
    for entry in manifest.get("entries", []):
        bid = entry["id"]
        v1 = pass1.get(bid, {})
        v2 = pass2.get(bid, {})
        q = queue_by_id.get(bid, {})
        p1v = v1.get("verdict", q.get("pass1_verdict", ""))
        p2v = v2.get("verdict", q.get("pass2_verdict", ""))
        disagree = bool(p1v and p2v and p1v != p2v and p1v != "missing")
        items.append({
            "id": bid,
            "room": entry.get("room"),
            "photo": entry.get("photo"),
            "gold_item": entry.get("gold_item"),
            "det_label": entry.get("det_label"),
            "det_confidence": entry.get("det_confidence"),
            "box_xyxy": entry.get("box_xyxy"),
            "risk_flags": entry.get("risk_flags", []),
            "priority": entry.get("risk_score", 0) + (3 if disagree else 0),
            "crop_path": entry.get("crop_path"),
            "full_path": entry.get("full_path"),
            "pass1_verdict": p1v,
            "pass1_note": v1.get("note", q.get("pass1_note", "")),
            "pass2_verdict": p2v,
            "pass2_note": v2.get("note", q.get("pass2_note", "")),
            "disagreement": disagree,
            "in_queue": bid in queue_ids,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "shortlist_ids": shortlist_ids,
        "items": items,
    }


def cmd_render_carousel(args: argparse.Namespace) -> int:
    review_dir = args.review_dir.resolve()
    template = args.template.resolve()
    out = args.output.resolve()

    if not template.is_file():
        print(f"template missing: {template}", file=sys.stderr)
        return 1
    if not (review_dir / "manifest.json").is_file():
        print(f"manifest missing — run render-review first: {review_dir}", file=sys.stderr)
        return 1

    data = build_carousel_data(review_dir)
    html = template.read_text(encoding="utf-8")
    if "__REVIEW_DATA__" not in html:
        print("template missing __REVIEW_DATA__ placeholder", file=sys.stderr)
        return 1
    html = html.replace("__REVIEW_DATA__", json.dumps(data, ensure_ascii=False))
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({data['total']} items, {len(data['shortlist_ids'])} shortlist)")
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

    boot = sub.add_parser(
        "bootstrap",
        help="seed labels_boxes.json from YOLOE detections matched to gold",
    )
    boot.add_argument("capture", type=Path, nargs="?", default=DEFAULT_CAPTURE)
    boot.add_argument("labels", type=Path, nargs="?", default=DEFAULT_LABELS)
    boot.add_argument("-o", "--output", type=Path, default=DEFAULT_BOXES)
    boot.add_argument("--rooms", nargs="*", default=None,
                      help=f"rooms to label (default: {ML_E11_ROOMS})")
    boot.add_argument("--threshold", type=float, default=0.75,
                      help="fuzzy name-match threshold for gold items")
    boot.add_argument("--conf", type=float, default=0.25,
                      help="minimum detector confidence")
    boot.add_argument("--device", default=None, help="torch device (cpu, mps, cuda)")
    boot.add_argument("--labeler", default="yoloe-bootstrap",
                      help="labeler id stored on each box")
    boot.add_argument("--unverified", action="store_true",
                      help="mark boxes verified=false (default: true)")
    boot.set_defaults(func=cmd_bootstrap)

    rev = sub.add_parser("render-review", help="render bbox review crops + manifest")
    rev.add_argument("capture", type=Path, nargs="?", default=DEFAULT_CAPTURE)
    rev.add_argument("boxes", type=Path, nargs="?", default=DEFAULT_BOXES)
    rev.add_argument("-o", "--output", type=Path,
                     default=ROOT / "evals" / "fixtures" / "inventoryflex" / "bbox-review")
    rev.add_argument("--pad", type=float, default=0.25,
                     help="padding fraction around box for crop")
    rev.set_defaults(func=cmd_render_review)

    adj = sub.add_parser("adjudicate", help="merge agent reviews into adjudication queue")
    adj.add_argument("--pass1", type=Path, action="append", required=True,
                     help="first-pass review JSON files (repeat flag per file)")
    adj.add_argument("--pass2", type=Path, default=None,
                     help="second-pass review JSON")
    adj.add_argument("-o", "--output", type=Path,
                     default=ROOT / "evals" / "fixtures" / "inventoryflex"
                     / "bbox-adjudication.json")
    adj.set_defaults(func=cmd_adjudicate)

    carousel = sub.add_parser("render-carousel", help="build full-screen bbox review carousel HTML")
    carousel.add_argument("--review-dir", type=Path,
                          default=ROOT / "evals" / "fixtures" / "inventoryflex" / "bbox-review")
    carousel.add_argument("--template", type=Path,
                          default=ROOT / "evals" / "fixtures" / "inventoryflex"
                          / "bbox-review" / "review-carousel.template.html")
    carousel.add_argument("-o", "--output", type=Path,
                          default=ROOT / "evals" / "fixtures" / "inventoryflex"
                          / "bbox-review" / "review-carousel.html")
    carousel.set_defaults(func=cmd_render_carousel)

    apply = sub.add_parser("apply-review", help="apply human carousel verdicts to labels_boxes.json")
    apply.add_argument("review", type=Path, help="human-bbox-review JSON from carousel export")
    apply.add_argument("--boxes", type=Path, default=DEFAULT_BOXES)
    apply.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    apply.add_argument("-o", "--output", type=Path, default=DEFAULT_BOXES)
    apply.set_defaults(func=cmd_apply_review)

    trim = sub.add_parser(
        "trim-consensus",
        help="drop agent consensus rejects; apply human review overrides",
    )
    trim.add_argument("--boxes", type=Path, default=DEFAULT_BOXES)
    trim.add_argument("--review-dir", type=Path,
                      default=ROOT / "evals" / "fixtures" / "inventoryflex" / "bbox-review")
    trim.add_argument("--human", type=Path,
                      default=ROOT / "evals" / "fixtures" / "inventoryflex" / "bbox-review"
                      / "human-bbox-review-2026-07-05.json")
    trim.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    trim.add_argument("-o", "--output", type=Path, default=DEFAULT_BOXES)
    trim.set_defaults(func=cmd_trim_consensus)

    cvat = sub.add_parser("export-cvat", help="CVAT export mapping stub")
    cvat.add_argument("boxes", type=Path, nargs="?", default=DEFAULT_BOXES)
    cvat.set_defaults(func=cmd_export_cvat)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
