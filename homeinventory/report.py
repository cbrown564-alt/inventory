"""Render an Inventory to HTML (always) and PDF (when WeasyPrint can run)."""

from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import Inventory, Item, Room

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

    from .usecases.tenancy import tenancy_schedule_summary

    return tenancy_schedule_summary(inv)


def _group_items_by_category(items: list[Item]) -> list[tuple[str | None, list[Item]]]:
    groups: list[tuple[str | None, list[Item]]] = []
    current_heading: str | None = None
    bucket: list[Item] = []
    for item in items:
        heading = CATEGORY_HEADINGS.get(item.category, "Miscellaneous items")
        if bucket and heading != current_heading:
            groups.append((current_heading, bucket))
            bucket = []
        current_heading = heading
        bucket.append(item)
    if bucket:
        groups.append((current_heading, bucket))
    return groups


def _condition_cell(item: Item) -> str:
    parts: list[str] = []
    if item.not_inspected:
        parts.append(item.not_inspected.replace("_", " ").capitalize())
    if item.condition:
        parts.append(item.condition.capitalize())
    if item.cleanliness and item.cleanliness != item.condition:
        parts.append(item.cleanliness.capitalize())
    for defect in item.defects:
        parts.append(defect)
    return "\n".join(parts) if parts else "—"


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
                    "condition_text": _condition_cell(item),
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
            dest = photos_dir / f"{p.id}.jpg"
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


def render(inv: Inventory, capture_dir: Path, out_dir: Path,
           pdf: bool = True) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    inv.rooms = sort_rooms(inv.rooms)
    photo_src = _export_photos(inv, capture_dir, out_dir)
    schedule = default_schedule_summary(inv)
    room_sections = prepare_room_sections(inv)

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        inv=inv,
        photo_src=photo_src,
        total_items=inv.item_count(),
        total_photos=inv.photo_count(),
        reviewed_items=inv.reviewed_count(),
        schedule_summary=schedule,
        room_sections=room_sections,
        agent_display=inv.agent_name or inv.inspected_by,
        # embedded for the in-report review layer (Level 1)
        payload={"inventory": asdict(inv), "photo_src": photo_src},
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
            from weasyprint import HTML
            pdf_path = out_dir / "inventory.pdf"
            HTML(string=html, base_url=str(out_dir)).write_pdf(str(pdf_path))
            outputs["pdf"] = pdf_path
        except Exception as e:
            log.warning("PDF generation unavailable (%s); HTML report is complete "
                        "— print it to PDF from a browser if needed.", e)
    return outputs
