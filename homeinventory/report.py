"""Render an Inventory to HTML (always) and PDF (when WeasyPrint can run)."""

from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .schema import CATEGORIES, Inventory, Item, Room

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"

# UK clerk walk-through order (InventoryFlex / AIIC convention).
CANONICAL_ROOM_ORDER = [
    "general",
    "entrance hall",
    "hallway",
    "hall",
    "walk in wardrobe",
    "wardrobe",
    "reception",
    "open plan kitchen",
    "living room",
    "kitchen",
    "dining",
    "bedroom",
    "bathroom",
    "utility",
    "balcony",
    "garden",
    "outside",
]

CATEGORY_HEADINGS: dict[str, str | None] = {
    "structure": None,
    "fixture": "Fixtures & fittings",
    "appliance": "Appliances",
    "furniture": "Furniture",
    "soft furnishing": "Soft furnishings",
    "electronics": "Electronics",
    "kitchenware": "Kitchenware",
    "decor": "Decor",
    "safety": "Safety equipment",
    "meter": "Meters",
    "other": "Miscellaneous items",
}


def _room_sort_key(name: str) -> tuple[int, str]:
    lower = name.lower()
    for idx, pattern in enumerate(CANONICAL_ROOM_ORDER):
        if pattern in lower:
            return (idx, lower)
    return (len(CANONICAL_ROOM_ORDER), lower)


def sort_rooms(rooms: list[Room]) -> list[Room]:
    return sorted(rooms, key=lambda r: _room_sort_key(r.name))


def _aggregate_cleanliness(items: list[Item]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        if item.cleanliness:
            counts[item.cleanliness] += 1
    if not counts:
        return "See room entries"
    return max(counts, key=counts.get).replace("_", " ").capitalize()


def _aggregate_condition(items: list[Item], *, structural: bool = False) -> str:
    grades = [i.condition for i in items if i.condition and not i.rejected]
    if not grades:
        return "See room entries"
    worst = max(grades, key=lambda g: ["new", "excellent", "good", "fair", "poor"].index(g))
    label = worst.capitalize()
    if structural:
        structural_items = [i for i in items if i.category == "structure" and not i.rejected]
        defects = [d for i in structural_items for d in i.defects[:2]]
        if defects:
            return f"{label} condition\n" + "\n".join(defects[:3])
    return f"{label} condition"


def default_schedule_summary(inv: Inventory) -> list[dict]:
    """Build section 1 rows when none were supplied manually."""
    if inv.schedule_summary:
        return inv.schedule_summary

    all_items = [i for r in inv.rooms for i in r.items if not i.rejected]
    structural = [i for i in all_items if i.category == "structure"]
    fixtures = [i for i in all_items if i.category == "fixture"]
    furniture = [i for i in all_items if i.category == "furniture"]
    appliances = [i for i in all_items if i.category == "appliance"]
    safety = [i for i in all_items if i.category == "safety"]

    rows = [
        {"ref": "1.1", "name": "Property details",
         "condition": inv.property_type or "As inspected"},
        {"ref": "1.2", "name": "Cleaning standard",
         "condition": _aggregate_cleanliness(all_items)},
        {"ref": "1.3", "name": "Decorative condition",
         "condition": _aggregate_condition(structural, structural=True)},
        {"ref": "1.4", "name": "Flooring",
         "condition": _aggregate_condition(
             [i for i in structural if "floor" in i.name.lower()])},
        {"ref": "1.5", "name": "Windows",
         "condition": _aggregate_condition(
             [i for i in all_items if "window" in i.name.lower()])},
        {"ref": "1.6", "name": "Fixtures / fittings",
         "condition": _aggregate_condition(fixtures)},
        {"ref": "1.7", "name": "Furniture",
         "condition": _aggregate_condition(furniture)},
        {"ref": "1.8", "name": "Curtains / blinds",
         "condition": _aggregate_condition(
             [i for i in all_items if "blind" in i.name.lower()
              or "curtain" in i.name.lower()])},
        {"ref": "1.9", "name": "Sanitary ware",
         "condition": "Water running / working — see bathroom entries"},
        {"ref": "1.10", "name": "Kitchen appliances",
         "condition": "Tested for power unless otherwise stated"
         if appliances else "See kitchen entries"},
        {"ref": "1.11", "name": "Electrics",
         "condition": "All lights working — see room entries"
         if any("light" in i.name.lower() for i in all_items) else "See room entries"},
        {"ref": "1.12", "name": "Linens",
         "condition": "See soft furnishing entries"},
        {"ref": "1.13", "name": "Main switches / fuses",
         "condition": "See utility / meter entries"},
        {"ref": "1.14", "name": "Outside area",
         "condition": _aggregate_condition(
             [i for r in inv.rooms for i in r.items
              if "balcony" in r.name.lower() or "garden" in r.name.lower()])},
        {"ref": "1.15", "name": "Appliance manuals",
         "condition": "See room entries"},
    ]
    if safety:
        tested = sum(1 for i in safety if i.not_inspected != "not tested")
        rows.append({"ref": "1.16", "name": "Smoke / CO alarms",
                     "condition": f"{tested} alarm{'s' if tested != 1 else ''} "
                                  "recorded — see room entries"})
    return rows


def _group_items_by_category(items: list[Item]) -> list[tuple[str | None, list[Item]]]:
    """One group per category heading, in canonical CATEGORIES order.

    Items are sorted (stably) by category first so a heading never repeats
    mid-table; within a category the pipeline's original order is kept."""
    rank = {c: i for i, c in enumerate(CATEGORIES)}
    ordered = sorted(items, key=lambda i: rank.get(i.category, len(rank)))
    groups: list[tuple[str | None, list[Item]]] = []
    current_heading: str | None = None
    bucket: list[Item] = []
    for item in ordered:
        heading = CATEGORY_HEADINGS.get(item.category, "Miscellaneous items")
        if bucket and heading != current_heading:
            groups.append((current_heading, bucket))
            bucket = []
        current_heading = heading
        bucket.append(item)
    if bucket:
        groups.append((current_heading, bucket))
    return groups


def _grades_line(item: Item) -> str:
    """The grade words only — defects are rendered as their own list so they
    stay in sentence case rather than inheriting small-caps."""
    parts: list[str] = []
    if item.not_inspected:
        parts.append(item.not_inspected.replace("_", " ").capitalize())
    if item.condition:
        parts.append(item.condition.capitalize())
    if item.cleanliness and item.cleanliness != item.condition:
        parts.append(item.cleanliness.capitalize())
    return " · ".join(parts) if parts else "—"


def prepare_room_sections(inv: Inventory) -> list[dict]:
    """Room blocks with clerk-style numbering and grouped items."""
    sections: list[dict] = []
    for idx, room in enumerate(sort_rooms(inv.rooms), start=2):
        visible_items = [i for i in room.items if not i.rejected]
        groups = _group_items_by_category(visible_items)
        item_num = 0
        grouped: list[dict] = []
        for heading, items in groups:
            rows: list[dict] = []
            for item in items:
                item_num += 1
                rows.append({
                    "item": item,
                    "ref": f"{idx}.{item_num}",
                    "grades_line": _grades_line(item),
                })
            grouped.append({"heading": heading, "rows": rows})
        sections.append({
            "number": idx,
            "name": room.name,
            "summary": room.summary,
            "groups": grouped,
            "photos": room.photos,
        })
    return sections


def human_date(value: str) -> str:
    """'2026-07-03' (or a full ISO timestamp) -> '3 July 2026'; anything
    unparseable is returned untouched."""
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return f"{dt.day} {dt.strftime('%B %Y')}"
    except ValueError:
        return value


def _display_path(photo_path: str, capture_dir: Path, out_dir: Path) -> str:
    """A path fit for the printed manifest: relative to the capture root or
    the report folder — never an absolute path from the build machine."""
    p = Path(photo_path.replace("\\", "/"))
    if not p.is_absolute():
        return str(p)
    for root in (capture_dir, out_dir):
        try:
            return str(p.relative_to(root.resolve()))
        except ValueError:
            try:
                return str(p.relative_to(root))
            except ValueError:
                continue
    return "/".join(p.parts[-3:])  # last resort: room/dir/file.jpg


def _export_photos(inv: Inventory, capture_dir: Path, out_dir: Path,
                   max_dim: int = 1400) -> dict[str, str]:
    """Copy (downscaled) report photos to out_dir/photos; return id -> rel path."""
    from PIL import Image

    photos_dir = out_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    src_map: dict[str, str] = {}
    for room in inv.rooms:
        for p in room.photos:
            src = Path(p.path.replace("\\", "/"))
            if not src.is_absolute():
                src = capture_dir / src
                if not src.exists() and (out_dir / p.path).exists():
                    # report-relative path (e.g. work/frames/… from a
                    # round-tripped Level-1 export)
                    src = out_dir / p.path
            dest = photos_dir / f"{p.id}.jpg"
            # unchanged source -> keep the existing export (a re-render after
            # review edits must not re-encode hundreds of untouched photos)
            try:
                if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
                    src_map[p.id] = f"photos/{p.id}.jpg"
                    continue
            except OSError:
                pass
            try:
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    if max(im.size) > max_dim:
                        im.thumbnail((max_dim, max_dim))
                    im.save(dest, quality=88)
            except Exception as e:
                log.warning("could not re-encode %s (%s); copying as-is — the "
                            "report image may not render", src, e)
                shutil.copyfile(src, dest)
            src_map[p.id] = f"photos/{p.id}.jpg"
    return src_map


def import_weasyprint():
    """Import WeasyPrint, retrying on macOS with Homebrew's lib dir on the
    dyld fallback path — a stock `brew install glib pango` lands where the
    default loader search does not look, and the difference between "works"
    and a 503 should not be one env var the user has to know about."""
    import sys
    try:
        import weasyprint
        return weasyprint
    except OSError:
        if sys.platform == "darwin" and Path("/opt/homebrew/lib").is_dir():
            import os
            paths = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                "/opt/homebrew/lib" + (":" + paths if paths else ""))
            for mod in [m for m in sys.modules if m.startswith("weasyprint")]:
                del sys.modules[mod]
            import weasyprint
            return weasyprint
        raise


def _payload_inventory(inv: Inventory, display_path: dict[str, str]) -> dict:
    """The inventory as embedded in the HTML artefact: identical data, but
    photo paths rewritten to capture/report-relative form so a report handed
    to another party never leaks the build machine's filesystem layout."""
    body = asdict(inv)
    for room in body["rooms"]:
        for p in room["photos"]:
            p["path"] = display_path.get(p["id"], p["path"])
            if p.get("source_video"):
                p["source_video"] = Path(
                    str(p["source_video"]).replace("\\", "/")).name
    return body


def render(inv: Inventory, capture_dir: Path, out_dir: Path,
           pdf: bool = True) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    inv.rooms = sort_rooms(inv.rooms)
    photo_src = _export_photos(inv, capture_dir, out_dir)
    schedule = default_schedule_summary(inv)
    room_sections = prepare_room_sections(inv)

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=True)
    env.filters["human_date"] = human_date
    env.filters["basename"] = lambda p: Path(str(p).replace("\\", "/")).name
    photo_display_path = {
        p.id: _display_path(p.path, capture_dir, out_dir)
        for room in inv.rooms for p in room.photos
    }
    # defect regions grouped by photo, for the photo strips and Appendix B
    regions_by_photo: dict[str, list[dict]] = defaultdict(list)
    for room in inv.rooms:
        for item in room.items:
            if item.rejected:
                continue
            for reg in item.defect_regions:
                if reg.get("photo_id"):
                    regions_by_photo[reg["photo_id"]].append(
                        {"item_id": item.id, **reg})
    html = env.get_template("report.html.j2").render(
        inv=inv,
        photo_src=photo_src,
        photo_display_path=photo_display_path,
        regions_by_photo=dict(regions_by_photo),
        total_items=inv.item_count(),
        total_photos=inv.photo_count(),
        reviewed_items=inv.reviewed_count(),
        schedule_summary=schedule,
        room_sections=room_sections,
        agent_display=inv.agent_name or inv.inspected_by,
        # embedded for the in-report review layer (Level 1); photo paths are
        # sanitised so the artefact never carries the build machine's paths
        payload={"inventory": _payload_inventory(inv, photo_display_path),
                 "photo_src": photo_src},
    )

    outputs: dict[str, Path] = {}
    html_path = out_dir / "inventory.html"
    html_path.write_text(html, encoding="utf-8")
    outputs["html"] = html_path

    json_path = out_dir / "inventory.json"
    json_path.write_text(inv.to_json(), encoding="utf-8")
    outputs["json"] = json_path

    if pdf:
        try:
            weasyprint = import_weasyprint()
            pdf_path = out_dir / "inventory.pdf"
            weasyprint.HTML(string=html,
                            base_url=str(out_dir)).write_pdf(str(pdf_path))
            outputs["pdf"] = pdf_path
        except Exception as e:
            log.warning("PDF generation unavailable (%s); HTML report is complete "
                        "— print it to PDF from a browser if needed.", e)
    return outputs
