"""Render an Inventory to HTML (always) and PDF (when WeasyPrint can run)."""

from __future__ import annotations

import json
import logging
import shutil
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .schema import CATEGORIES, Inventory, Item, Room, cover_value
from .usecases import get_use_case, use_case_for
from .usecases.base import UseCase

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


# Cover fields rendered elsewhere on the page (addr block, agent banner, footer).
_COVER_TABLE_SKIP = frozenset({
    "property_address", "agent_name", "agent_phone", "property_type",
})


def summary_rows(inv: Inventory, uc: UseCase) -> list[dict]:
    """Section-1 summary rows: a manual schedule wins, else the profile's."""
    if inv.schedule_summary:
        return inv.schedule_summary
    if uc.summary_rows:
        return uc.summary_rows(inv)
    return []


def default_schedule_summary(inv: Inventory) -> list[dict]:
    """Back-compat alias delegating to the tenancy profile."""
    return summary_rows(inv, get_use_case("tenancy"))


def build_cover_rows(inv: Inventory, uc: UseCase) -> list[dict]:
    """Cover-table party rows from the use-case profile, skipping empties."""
    rows: list[dict] = []
    for field in uc.cover_fields:
        if field.name in _COVER_TABLE_SKIP:
            continue
        value = cover_value(inv, field)
        if value:
            rows.append({"label": field.label, "value": value})
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
    normalized = photo_path.replace("\\", "/")
    p = Path(normalized)
    # POSIX-style /abs paths aren't pathlib-absolute on Windows; still treat
    # them as machine-absolute so we never echo them verbatim in the manifest.
    if not p.is_absolute() and not normalized.startswith("/"):
        return p.as_posix()
    for root in (capture_dir, out_dir):
        try:
            return p.relative_to(root.resolve()).as_posix()
        except ValueError:
            try:
                return p.relative_to(root).as_posix()
            except ValueError:
                continue
    return "/".join(p.parts[-3:])  # last resort: room/dir/file.jpg


# Appendix B prints photos at ~6 cm wide; a second, smaller derivative keeps
# the PDF emailable while the full-tier export still feeds the on-screen
# lightbox (size budget: docs/10 §5).
PRINT_MAX_DIM = 900
PRINT_QUALITY = 72


def _dhash(im) -> int:
    """64-bit difference hash of a PIL image — perceptual near-duplicate
    detection for consecutive walkthrough-video frames."""
    g = im.convert("L").resize((9, 8))
    px = g.tobytes()   # row-major 8-bit greyscale
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _export_photos(inv: Inventory, capture_dir: Path, out_dir: Path,
                   max_dim: int = 1400) -> tuple[dict[str, str],
                                                 dict[str, str],
                                                 dict[str, int]]:
    """Copy (downscaled) report photos to out_dir/photos plus a smaller
    print tier to out_dir/photos/print. Returns (id -> rel path,
    id -> print rel path, id -> dhash)."""
    from PIL import Image

    photos_dir = out_dir / "photos"
    print_dir = photos_dir / "print"
    print_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "work" / "photo-hashes.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    src_map: dict[str, str] = {}
    print_map: dict[str, str] = {}
    dhash_map: dict[str, int] = {}
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
            pdest = print_dir / f"{p.id}.jpg"
            src_map[p.id] = f"photos/{p.id}.jpg"
            print_map[p.id] = f"photos/print/{p.id}.jpg"
            # unchanged source -> keep the existing exports (a re-render after
            # review edits must not re-encode hundreds of untouched photos)
            try:
                src_mtime = src.stat().st_mtime
            except OSError:
                src_mtime = None
            entry = cache.get(p.id) or {}
            if (src_mtime is not None
                    and dest.exists() and dest.stat().st_mtime >= src_mtime
                    and pdest.exists() and pdest.stat().st_mtime >= src_mtime
                    and entry.get("src_mtime") == src_mtime):
                if entry.get("dhash") is not None:
                    dhash_map[p.id] = entry["dhash"]
                continue
            try:
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    if max(im.size) > max_dim:
                        im.thumbnail((max_dim, max_dim))
                    im.save(dest, quality=88)
                    dhash_map[p.id] = _dhash(im)
                    if max(im.size) > PRINT_MAX_DIM:
                        im.thumbnail((PRINT_MAX_DIM, PRINT_MAX_DIM))
                    im.save(pdest, quality=PRINT_QUALITY)
                cache[p.id] = {"src_mtime": src_mtime,
                               "dhash": dhash_map[p.id]}
            except Exception as e:
                log.warning("could not re-encode %s (%s); copying as-is — the "
                            "report image may not render", src, e)
                shutil.copyfile(src, dest)
                shutil.copyfile(src, pdest)
                cache[p.id] = {"src_mtime": src_mtime, "dhash": None}
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return src_map, print_map, dhash_map


# Two frames of the same walkthrough video within this dHash distance are
# treated as near-duplicates for Appendix B. Cited or annotated photos are
# never pruned — the printed evidence chain (item -> "Evidence: Pnnn" ->
# Appendix B) must always resolve; Appendix A lists every file regardless.
PRUNE_HAMMING = 8


def _prune_near_duplicates(photos, keep_ids: set[str],
                           dhash: dict[str, int]) -> tuple[list, int]:
    """Drop uncited, unannotated video frames that look like the last kept
    frame of the same source video. Returns (kept photos, pruned count)."""
    kept, pruned = [], 0
    last_by_video: dict[str, int] = {}
    for p in photos:
        h = dhash.get(p.id)
        video = p.source_video
        if (video and h is not None and p.id not in keep_ids):
            prev = last_by_video.get(video)
            if prev is not None and _hamming(prev, h) <= PRUNE_HAMMING:
                pruned += 1
                continue
        if video and h is not None:
            last_by_video[video] = h
        kept.append(p)
    return kept, pruned


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
           pdf: bool = True, *, use_case: str | None = None) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    inv.rooms = sort_rooms(inv.rooms)
    uc = get_use_case(use_case) if use_case else use_case_for(inv)
    photo_src, photo_print_src, dhash_map = _export_photos(
        inv, capture_dir, out_dir)
    schedule = summary_rows(inv, uc)
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
    # photos the printed document must show: cited as evidence by a live
    # item, or carrying a defect-region annotation
    keep_ids = set(regions_by_photo)
    for room in inv.rooms:
        for item in room.items:
            if not item.rejected:
                keep_ids.update(item.photo_ids or [])
    for section in room_sections:
        kept, pruned = _prune_near_duplicates(section["photos"], keep_ids,
                                              dhash_map)
        section["appendix_photos"] = kept
        section["appendix_pruned"] = pruned

    context = dict(
        inv=inv,
        uc=uc,
        photo_src=photo_src,
        photo_print_src=photo_print_src,
        photo_display_path=photo_display_path,
        regions_by_photo=dict(regions_by_photo),
        total_items=inv.item_count(),
        total_photos=inv.photo_count(),
        reviewed_items=inv.reviewed_count(),
        schedule_summary=schedule,
        cover_rows=build_cover_rows(inv, uc),
        room_sections=room_sections,
        agent_display=inv.agent_name or inv.inspected_by,
        # embedded for the in-report review layer (Level 1); photo paths are
        # sanitised so the artefact never carries the build machine's paths
        payload={"inventory": _payload_inventory(inv, photo_display_path),
                 "photo_src": photo_src,
                 "owner_role": uc.owner_role.key,
                 "counterparty_role": uc.counterparty_role.key,
                 "signing_roles": list(uc.signing_role_keys)},
    )
    template = env.get_template("report.html.j2")
    html = template.render(final=False, **context)

    outputs: dict[str, Path] = {}
    html_path = out_dir / "inventory.html"
    html_path.write_text(html, encoding="utf-8")
    outputs["html"] = html_path

    # the final issue: the same document stripped of the review instrument
    # (docket, embedded payload, review-state chips) — the copy you send
    issue_path = out_dir / "inventory-issue.html"
    issue_path.write_text(template.render(final=True, **context),
                          encoding="utf-8")
    outputs["issue"] = issue_path

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
