"""Render an Inventory to HTML (always) and PDF (when WeasyPrint can run)."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .ingest import exif_capture_time, stamp_exif_capture_time
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

# These are intentionally broad, room-level evidence classes. They are not
# detector labels: they identify the finish/coverage rows where a context
# photo is often useful but a dedicated close-up would make the claim easier
# to verify.
FINISH_EVIDENCE_TERMS = (
    "ceiling", "wall", "floor", "skirting", "blind",
)


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


def _is_finish_item(name: str) -> bool:
    text = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return any(term in text for term in FINISH_EVIDENCE_TERMS)


def _evidence_state(item: Item, crop_src: dict[str, str]) -> str:
    """Return the evidence state visible to a report reader."""
    if item.id in crop_src:
        return "proposed" if item.crop_status == "proposed" else "crop"
    if item.photo_ids:
        return "context"
    return "missing"


def build_evidence_overview(inv: Inventory,
                            crop_src: dict[str, str]) -> dict:
    """Build the compact evidence desk shown above the schedule."""
    stats = {
        "total": 0, "closeups": 0, "proposed": 0, "context": 0,
        "missing": 0, "finish_gaps": 0, "defect_items": 0,
        "unreviewed": 0,
    }
    rooms: list[dict] = []
    for room in sort_rooms(inv.rooms):
        items = [item for item in room.items if not item.rejected]
        room_stats = {
            "name": room.name, "total": len(items), "closeups": 0,
            "proposed": 0, "context": 0, "missing": 0, "finish_gaps": 0,
            "defects": 0, "unreviewed": 0,
        }
        for item in items:
            state = _evidence_state(item, crop_src)
            stats["total"] += 1
            stats["closeups"] += state == "crop"
            stats["proposed"] += state == "proposed"
            stats["context"] += state == "context"
            stats["missing"] += state == "missing"
            room_stats["closeups"] += state == "crop"
            room_stats["proposed"] += state == "proposed"
            room_stats["context"] += state == "context"
            room_stats["missing"] += state == "missing"
            if _is_finish_item(item.name) and state != "crop":
                stats["finish_gaps"] += 1
                room_stats["finish_gaps"] += 1
            if item.defects or item.rejected_defects:
                stats["defect_items"] += 1
                room_stats["defects"] += 1
            if not item.reviewed and not item.rejected:
                stats["unreviewed"] += 1
                room_stats["unreviewed"] += 1
        rooms.append(room_stats)
    stats["attention"] = stats["context"] + stats["missing"] + stats["defect_items"]
    stats["coverage_percent"] = round(
        100 * stats["closeups"] / stats["total"], 1
    ) if stats["total"] else 0
    return {**stats, "rooms": rooms}


def build_evidence_media(inv: Inventory, photo_src: dict[str, str],
                         crop_src: dict[str, str]) -> dict[str, list[dict]]:
    """Build the lightbox media list for each schedule item.

    The crop comes first, followed by every cited source photo. Defect
    regions are scoped to the item so the viewer can show the claim in place
    without exposing unrelated annotations from the same room.
    """
    media_by_item: dict[str, list[dict]] = {}
    for room in inv.rooms:
        for item in room.items:
            media: list[dict] = []
            if crop_src.get(item.id):
                media.append({
                    "src": crop_src[item.id],
                    "label": "Proposed crop" if item.crop_status == "proposed"
                    else "Close-up",
                    "title": item.name,
                })
            for pid in item.photo_ids:
                src = photo_src.get(pid)
                if not src:
                    continue
                regions = []
                for region in item.defect_regions:
                    if region.get("photo_id") != pid:
                        continue
                    regions.append({
                        "x": region.get("x", 0), "y": region.get("y", 0),
                        "w": region.get("w", 0), "h": region.get("h", 0),
                        "defect": region.get("defect", ""),
                    })
                media.append({
                    "src": src, "label": pid,
                    "title": f"{room.name} · {item.name}",
                    "regions": regions,
                })
            media_by_item[item.id] = media
    return media_by_item


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


def split_heroes(photos: list) -> tuple[list, list]:
    """(hero photos in rank order, the disclosed rest).

    Inventories built before curation (docs/15 M2) have no hero ranks —
    everything is a hero, nothing is disclosed, the report is unchanged."""
    heroes = sorted((p for p in photos if getattr(p, "hero", None)),
                    key=lambda p: p.hero)
    if not heroes:
        return list(photos), []
    return heroes, [p for p in photos if not p.hero]


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
        heroes, more = split_heroes(room.photos)
        sections.append({
            "number": idx,
            "name": room.name,
            "summary": room.summary,
            "groups": grouped,
            "photos": room.photos,
            "hero_photos": heroes,
            "more_photos": more,
            # the top-ranked hero heads the section — but only when curation
            # actually elected a set; an uncurated room stays a plain strip
            "cover": heroes[0] if heroes and getattr(heroes[0], "hero", None)
                     else None,
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


def _timecode(seconds) -> str:
    """Seconds into the footage -> '4:12' (or '1:04:12' past the hour)."""
    s = max(0, int(seconds or 0))
    h, m, r = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{r:02d}" if h else f"{m}:{r:02d}"


def _display_path(photo_path: str, capture_dir: Path, out_dir: Path) -> str:
    """A path fit for the printed manifest: relative to the capture root or
    the report folder — never an absolute path from the build machine."""
    normalized = photo_path.replace("\\", "/")
    p = Path(photo_path)
    is_absolute = (
        p.is_absolute()
        or normalized.startswith("/")
        or (len(normalized) > 1 and normalized[1] == ":")
    )
    if not is_absolute:
        return normalized
    for root in (capture_dir, out_dir):
        try:
            return str(p.resolve().relative_to(root.resolve())).replace("\\", "/")
        except (ValueError, OSError):
            try:
                return str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
    parts = [part for part in normalized.strip("/").split("/") if part]
    return "/".join(parts[-3:]) if parts else normalized.lstrip("/")


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
            if not src.exists():
                if dest.exists() and pdest.exists():
                    log.warning("source photo %s is unavailable; keeping the existing exports", src)
                    continue
                log.warning("source photo %s is unavailable; omitting it from the rendered report", src)
                src_map.pop(p.id, None)
                print_map.pop(p.id, None)
                continue
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
                captured = p.captured_at or exif_capture_time(src)
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    if max(im.size) > max_dim:
                        im.thumbnail((max_dim, max_dim))
                    im.save(dest, quality=88)
                    if captured:
                        stamp_exif_capture_time(dest, captured)
                    dhash_map[p.id] = _dhash(im)
                    if max(im.size) > PRINT_MAX_DIM:
                        im.thumbnail((PRINT_MAX_DIM, PRINT_MAX_DIM))
                    im.save(pdest, quality=PRINT_QUALITY)
                    if captured:
                        stamp_exif_capture_time(pdest, captured)
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


def _export_crops(inv: Inventory, out_dir: Path) -> dict[str, str]:
    """Copy detector close-ups beside the exported photos so the report can
    reference them relatively — ``crops/<name>`` resolves both on disk and
    through the review server's /crops/ route. {item_id: rel src}."""
    crop_src: dict[str, str] = {}
    crops_dir = out_dir / "crops"
    for room in inv.rooms:
        for item in room.items:
            if not item.crop_path or item.rejected:
                continue
            recorded = Path(item.crop_path.replace("\\", "/"))
            candidates = [recorded if recorded.is_absolute()
                          else out_dir / recorded,
                          out_dir / "work" / "crops" / recorded.name]
            src = next((c for c in candidates if c.is_file()), None)
            if src is None:
                continue
            dest = crops_dir / src.name
            try:
                if not dest.exists() \
                        or dest.stat().st_mtime < src.stat().st_mtime:
                    crops_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
            except OSError as e:
                log.warning("could not export crop %s (%s)", src, e)
                continue
            crop_src[item.id] = f"crops/{src.name}"
    return crop_src


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


def _payload_inventory(inv: Inventory, display_path: dict[str, str],
                       crop_src: dict[str, str]) -> dict:
    """The inventory as embedded in the HTML artefact: identical data, but
    photo and crop paths rewritten to capture/report-relative form so a
    report handed to another party never leaks the build machine's
    filesystem layout."""
    body = asdict(inv)
    for room in body["rooms"]:
        for p in room["photos"]:
            p["path"] = display_path.get(p["id"], p["path"])
            if p.get("source_video"):
                p["source_video"] = Path(
                    str(p["source_video"]).replace("\\", "/")).name
        for it in room["items"]:
            it["crop_path"] = crop_src.get(it["id"])
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
    env.filters["timecode"] = _timecode
    env.globals["is_finish_item"] = _is_finish_item

    # exhibit provenance: each extracted frame's second in its source video
    try:
        from .videometa import video_payload
        _videos, photo_time = video_payload(inv, capture_dir,
                                            out_dir / "work", "", {})
    except Exception:              # never let provenance break the render
        photo_time = {}
    photo_display_path = {
        p.id: _display_path(p.path, capture_dir, out_dir)
        for room in inv.rooms for p in room.photos
    }
    # defect regions grouped by photo, for the photo strips and Appendix B.
    # Exhibit numbers are stable per item (sort by photo, then y/x).
    regions_by_photo: dict[str, list[dict]] = defaultdict(list)
    for room in inv.rooms:
        for item in room.items:
            if item.rejected:
                continue
            regs = sorted(
                [r for r in item.defect_regions if r.get("photo_id")],
                key=lambda r: (r.get("photo_id") or "",
                               float(r.get("y") or 0),
                               float(r.get("x") or 0)),
            )
            for i, reg in enumerate(regs, start=1):
                regions_by_photo[reg["photo_id"]].append(
                    {"item_id": item.id, "exhibit": i, **reg})
    # photos the printed document must show: cited as evidence by a live
    # item, or carrying a defect-region annotation
    keep_ids = set(regions_by_photo)
    for room in inv.rooms:
        for item in room.items:
            if not item.rejected:
                keep_ids.update(item.photo_ids or [])
    for section in room_sections:
        # the printed appendix cannot disclose progressively, so it carries
        # the hero set plus everything the evidence chain needs (cited or
        # annotated photos) — the rest is analysed, hashed in Appendix A,
        # and reachable behind the screen report's disclosure
        hero_ids = {p.id for p in section["hero_photos"]}
        pool = [p for p in section["photos"]
                if p.id in hero_ids or p.id in keep_ids]
        kept, _ = _prune_near_duplicates(pool, keep_ids, dhash_map)
        section["appendix_photos"] = kept
        section["appendix_pruned"] = len(section["photos"]) - len(kept)

    crop_src = _export_crops(inv, out_dir)
    evidence_overview = build_evidence_overview(inv, crop_src)
    evidence_media = build_evidence_media(inv, photo_src, crop_src)
    context = dict(
        inv=inv,
        uc=uc,
        photo_src=photo_src,
        photo_print_src=photo_print_src,
        crop_src=crop_src,
        photo_time=photo_time,
        photo_display_path=photo_display_path,
        regions_by_photo=dict(regions_by_photo),
        total_items=inv.item_count(),
        total_photos=inv.photo_count(),
        hero_total=sum(len(s["hero_photos"]) for s in room_sections),
        reviewed_items=inv.reviewed_count(),
        evidence_overview=evidence_overview,
        schedule_summary=schedule,
        cover_rows=build_cover_rows(inv, uc),
        room_sections=room_sections,
        agent_display=inv.agent_name or inv.inspected_by,
        # embedded for the in-report review layer (Level 1); photo paths are
        # sanitised so the artefact never carries the build machine's paths
        payload={"inventory": _payload_inventory(inv, photo_display_path,
                                                 crop_src),
                 "photo_src": photo_src,
                 "crop_src": crop_src,
                 "evidence_media": evidence_media,
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
