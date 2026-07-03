"""Check-in vs check-out comparison (M4): alignment, wear-vs-damage rubric,
grade-delta discussion sheet.

Alignment is deliberately lexical and offline — room match (normalised name)
plus head-noun matching reusing :mod:`homeinventory.merge`'s ``_head_nouns``
and containment rule. Zero API calls. An embedding matcher was considered and
not built for v1 (see docs/08-compare.md); renames that only add or drop
descriptor words ("Walls" / "Walls (Cream Emulsion)") align lexically already.

Classification (fair wear and tear vs damage vs cleaning vs landlord
responsibility) is a prompted, text-only rubric grounded in the TDS guidance
this repo holds (docs/02-research.md §"What a TDS-valid inventory contains" /
§adjudication; docs/AI Dispute Evidence.pdf). It runs only for aligned items
with a condition-grade delta or a new defect. The ``offline`` backend yields
``unclassified``. The output is a discussion sheet: it identifies and
classifies changes, it never prices them (no £ amounts — monetary valuation
is an explicit non-goal).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .merge import _head_nouns
from .schema import CONDITION_GRADES, Inventory, Item

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Alignment: room match + lexical head-noun matching (reuses merge.py)
# --------------------------------------------------------------------------


def _norm_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def match_score(checkin_name: str, checkout_name: str) -> int:
    """Lexical alignment score between two item names.

    4 = names equal after normalisation; 3 = head-noun sets equal (the names
    differ only in descriptor words — material, colour, finish, qualifier);
    2 = one head-noun set contains the other (one name only qualifies the
    other); 0 = no match. Reuses merge._head_nouns so compare and the merge
    pass share one definition of "the same thing".
    """
    if _norm_name(checkin_name) == _norm_name(checkout_name):
        return 4
    a, b = _head_nouns(checkin_name), _head_nouns(checkout_name)
    if not a or not b:
        return 0
    if a == b:
        return 3
    if a <= b or b <= a:
        return 2
    return 0


def align_items(checkin_items: list[Item], checkout_items: list[Item],
                ) -> tuple[list[tuple[Item, Item, int]], list[Item], list[Item]]:
    """Greedy one-to-one alignment of a room's items across the two reports.

    Candidate pairs are scored with :func:`match_score` and assigned best
    score first (ties broken by list order for determinism). Returns
    ``(pairs, removed, added)`` — every item lands in exactly one bucket;
    nothing is silently dropped.
    """
    candidates = []
    for i, ci in enumerate(checkin_items):
        for j, co in enumerate(checkout_items):
            s = match_score(ci.name, co.name)
            if s:
                candidates.append((-s, i, j))
    candidates.sort()

    used_ci: set[int] = set()
    used_co: set[int] = set()
    pairs: list[tuple[Item, Item, int]] = []
    for neg_s, i, j in candidates:
        if i in used_ci or j in used_co:
            continue
        used_ci.add(i)
        used_co.add(j)
        pairs.append((checkin_items[i], checkout_items[j], -neg_s))
    removed = [it for i, it in enumerate(checkin_items) if i not in used_ci]
    added = [it for j, it in enumerate(checkout_items) if j not in used_co]
    return pairs, removed, added


# --------------------------------------------------------------------------
# Change detection
# --------------------------------------------------------------------------


def _grade_index(grade: Optional[str]) -> Optional[int]:
    return CONDITION_GRADES.index(grade) if grade in CONDITION_GRADES else None


def _norm_defect(d: str) -> str:
    return " ".join(d.strip().lower().split())


def diff_pair(checkin: Item, checkout: Item) -> dict:
    """Structured delta for one aligned pair.

    ``grade_delta`` is checkout minus check-in on the ordinal grade scale —
    positive means worse at check-out. ``new_defects`` are check-out defects
    with no lexically-equal check-in counterpart; ``resolved_defects`` the
    reverse (informational — two independent describes word defects
    differently, so treat "resolved" as "not re-observed").
    """
    ci_idx, co_idx = _grade_index(checkin.condition), _grade_index(checkout.condition)
    delta = (co_idx - ci_idx) if ci_idx is not None and co_idx is not None else None
    ci_defects = {_norm_defect(d) for d in checkin.defects}
    co_defects = {_norm_defect(d) for d in checkout.defects}
    new_defects = [d for d in checkout.defects if _norm_defect(d) not in ci_defects]
    resolved = [d for d in checkin.defects if _norm_defect(d) not in co_defects]
    return {
        "checkin_id": checkin.id,
        "checkout_id": checkout.id,
        "name": checkout.name,
        "checkin_name": checkin.name,
        "checkin_condition": checkin.condition,
        "checkout_condition": checkout.condition,
        "grade_delta": delta,
        "checkin_defects": list(checkin.defects),
        "checkout_defects": list(checkout.defects),
        "new_defects": new_defects,
        "resolved_defects": resolved,
        "checkin_cleanliness": checkin.cleanliness,
        "checkout_cleanliness": checkout.cleanliness,
        "checkin_photo_ids": list(checkin.photo_ids),
        "checkout_photo_ids": list(checkout.photo_ids),
        "checkin_regions": list(checkin.defect_regions),
        "checkout_regions": list(checkout.defect_regions),
        "classification": None,
        "rationale": None,
    }


def needs_classification(change: dict) -> bool:
    """Rubric runs only for a condition-grade delta or a new defect."""
    return bool(change["grade_delta"]) or bool(change["new_defects"])


# --------------------------------------------------------------------------
# Wear-vs-damage rubric (text-only; cites repo-held TDS guidance)
# --------------------------------------------------------------------------

CLASSIFICATION_CLASSES = [
    "fair_wear_and_tear",     # tenant not liable: reasonable use + time
    "damage",                 # tenant liable: beyond fair wear and tear
    "cleaning",               # tenant cleaning charge: dirt is removable
    "landlord_responsibility",  # repairs / pre-existing: landlord's matter
]
CLASS_LABELS = {
    "fair_wear_and_tear": "Fair wear and tear",
    "damage": "Damage (tenant)",
    "cleaning": "Cleaning (tenant)",
    "landlord_responsibility": "Landlord responsibility",
    "unclassified": "Unclassified",
}

# Grounding: every principle below is held in this repository —
# docs/02-research.md ("What a TDS-valid inventory contains", "What
# adjudicators expect": TDS Guide to Inventories, Check in and Check out
# Reports; NRLA/TDS on fair wear and tear, proportionate costs and no
# betterment; TDS via Inventory Hive on condition vs cleanliness) and
# docs/AI Dispute Evidence.pdf (Housing Rights NI / TDS NI: deposit is the
# tenant's money, burden of proof on the landlord; Phase 4 check-out design:
# suggested issue cleaning/repair vs fair wear and tear).
RUBRIC_PROMPT = """\
You classify condition changes between a tenancy check-in inventory and a
check-out inspection, the way a UK Tenancy Deposit Scheme (TDS) adjudicator
would frame them. Assign exactly one class to each change:

- "fair_wear_and_tear": deterioration from reasonable use of the premises by
  the tenant and the ordinary passage of time. Not chargeable to the tenant.
- "damage": deterioration beyond fair wear and tear — breakage, burns,
  stains, unauthorised alterations, or loss of an item that still had
  residual value. Chargeable to the tenant.
- "cleaning": the item is sound but not clean. Condition and cleanliness are
  distinct: dirt is removable, so an unclean item is a cleaning matter, not
  damage. Chargeable to the tenant as cleaning, not repair.
- "landlord_responsibility": mechanical or inherent failure within the
  landlord's repairing obligations, or a state already recorded at check-in
  (pre-existing) — the landlord's matter, not the tenant's.

Principles (TDS guidance and dispute-evidence research held in this
repository: docs/02-research.md; docs/AI Dispute Evidence.pdf):
1. The deposit is the tenant's money and the burden of proving an
   entitlement to deduct lies with the landlord (Housing Rights NI / TDS NI).
   Where the evidence is genuinely ambiguous, prefer the tenant-favourable
   class.
2. Damage must EXCEED fair wear and tear to be chargeable, and any remedy
   must be proportionate with no "betterment" — the landlord cannot end up
   better off (NRLA on TDS adjudication). Weigh the item's age and condition
   at check-in: an item already old, worn or below average at check-in has
   little residual value, so further deterioration — or its loss — is
   usually fair wear and tear rather than a chargeable loss.
3. "Exceeds fair wear and tear" is a real threshold, not a label for any
   deterioration (rubric v2 — added after the v1 IMS agreement run, see
   docs/08-compare.md): minor localised marks of everyday use — small chips,
   dents, scuffs, rub marks, screw/hook holes from ordinary picture- or
   hook-hanging — that do not impair the item's function are fair wear and
   tear, and the loss of low-value minor contents (brushes, bins, mats,
   ornaments) with no meaningful residual value is likewise recorded as fair
   wear and tear rather than a chargeable loss. Reserve "damage" for what
   reasonable use cannot explain: breakage, burns, significant staining,
   unauthorised alteration, or loss of items of real value.
4. Condition is not cleanliness (TDS): grade-relevant wear is physical;
   removable dirt, limescale, grease or marks that cleaning would lift are
   "cleaning".
5. Fair wear scales with tenancy length and occupancy: a longer tenancy and
   heavier occupancy justify more wear as "fair".
6. Use ONLY the tenancy length, occupancy and item age you are given. Where
   a value reads "not provided", you must not assume one and must not cite
   it in the rationale.

Respond with JSON: {"classification": <one class>, "rationale": <1-3
sentences citing the observed change and only the provided context values>}.
"""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": CLASSIFICATION_CLASSES},
        "rationale": {"type": "string"},
    },
    "required": ["classification", "rationale"],
    "additionalProperties": False,
}


def change_prompt(change: dict, room: str, tenancy_months: Optional[int],
                  occupancy: Optional[str], age: Optional[str],
                  checkin_description: str = "",
                  checkout_description: str = "") -> str:
    """User-message text for one change. Context values the caller did not
    provide are rendered literally as "not provided" — the rubric may cite
    only provided values."""

    def grade(g: Optional[str]) -> str:
        return g if g else "not graded"

    def defects(ds: list[str]) -> str:
        return "; ".join(ds) if ds else "none recorded"

    delta = change.get("grade_delta")
    if delta is None:
        delta_txt = "not gradeable (a grade is missing on one side)"
    elif delta > 0:
        delta_txt = f"{delta} grade(s) worse at check-out"
    elif delta < 0:
        delta_txt = f"{-delta} grade(s) better at check-out"
    else:
        delta_txt = "no grade change"

    lines = [
        f"Item: {change.get('checkin_name') or change.get('name')} (room: {room})",
        f"Check-in record: condition {grade(change.get('checkin_condition'))}"
        + (f"; {checkin_description}" if checkin_description else "")
        + f"; defects: {defects(change.get('checkin_defects', []))}",
        f"Check-out record: condition {grade(change.get('checkout_condition'))}"
        + (f"; {checkout_description}" if checkout_description else "")
        + f"; defects: {defects(change.get('checkout_defects', []))}"
        + f"; new since check-in: {defects(change.get('new_defects', []))}",
        f"Grade change: {delta_txt}",
        f"Tenancy length: {tenancy_months} months" if tenancy_months
        else "Tenancy length: not provided",
        f"Occupancy: {occupancy}" if occupancy else "Occupancy: not provided",
        f"Item age at check-in: {age}" if age
        else "Item age at check-in: not provided",
        "Classify this change.",
    ]
    return "\n".join(lines)


class OpenAIRubric:
    """Text-only wear-vs-damage rubric over any OpenAI-compatible API.

    Transport (base URL / key resolution / error mapping) is reused from
    describe.OpenAICompatBackend; only the payload differs (no images, the
    classification schema instead of the item schema). Default model is
    gpt-5.4-mini — the model the rubric's IMS agreement numbers were
    measured on (docs/08-compare.md).
    """

    name = "openai"
    DEFAULT_MODEL = "gpt-5.4-mini"

    def __init__(self, model: Optional[str] = None,
                 base_url: Optional[str] = None):
        from .describe import OpenAICompatBackend
        self._api = OpenAICompatBackend(model=model or self.DEFAULT_MODEL,
                                        base_url=base_url)
        self.model = self._api.model
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _accumulate(self, resp: dict) -> None:
        u = resp.get("usage") or {}
        for k in self.usage:
            v = u.get(k)
            if isinstance(v, (int, float)):
                self.usage[k] += int(v)

    def classify(self, entry_text: str) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": RUBRIC_PROMPT},
                {"role": "user", "content": entry_text},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "change_classification", "strict": True,
                "schema": CLASSIFY_SCHEMA}},
        }
        resp = self._api._post(payload)
        self._accumulate(resp)
        data = json.loads(resp["choices"][0]["message"]["content"])
        cls = data.get("classification")
        if cls not in CLASSIFICATION_CLASSES:
            return {"classification": "unclassified",
                    "rationale": f"backend returned unknown class {cls!r}"}
        return {"classification": cls,
                "rationale": data.get("rationale", "")}


class OfflineRubric:
    """No network, no model: every change stays ``unclassified``."""

    name = "offline"
    model = None

    def __init__(self):
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def classify(self, entry_text: str) -> dict:
        return {"classification": "unclassified",
                "rationale": "offline backend: no classification performed"}


def get_rubric_backend(name: str, model: Optional[str] = None,
                       base_url: Optional[str] = None):
    if name == "openai":
        return OpenAIRubric(model=model, base_url=base_url)
    if name == "offline":
        return OfflineRubric()
    raise ValueError(f"unknown compare backend: {name!r} (expected openai|offline)")


# --------------------------------------------------------------------------
# Comparison orchestration
# --------------------------------------------------------------------------


def _item_ages(raw_inventory_json: str) -> dict[str, str]:
    """Optional per-item age from the raw check-in JSON.

    ``Inventory.from_json`` tolerantly drops unknown keys, so an ``"age"``
    key hand-added to a check-in item (e.g. ``"age": "fitted 2019"``) never
    reaches the dataclass — read it from the raw JSON instead. Keyed by item
    id."""
    ages: dict[str, str] = {}
    try:
        raw = json.loads(raw_inventory_json)
    except ValueError:
        return ages
    for room in raw.get("rooms", []):
        for it in room.get("items", []):
            if it.get("age") and it.get("id"):
                ages[it["id"]] = str(it["age"])
    return ages


def _active_items(items: list[Item]) -> list[Item]:
    """Reviewer-rejected items are struck from the attested schedule
    (report.py excludes them everywhere); compare does the same."""
    return [i for i in items if not i.rejected]


def compare_inventories(checkin: Inventory, checkout: Inventory,
                        rubric=None, tenancy_months: Optional[int] = None,
                        occupancy: Optional[str] = None,
                        item_ages: Optional[dict[str, str]] = None) -> dict:
    """Align two inventories and classify the deteriorations.

    Every item on either side is accounted for exactly once: matched
    (changed or unchanged), removed (check-in only) or added (check-out
    only). ``rubric`` (see :func:`get_rubric_backend`) classifies matched
    items with a grade delta or new defect; ``None`` behaves like offline.
    """
    rubric = rubric or OfflineRubric()
    item_ages = item_ages or {}

    ci_rooms = {_norm_name(r.name): r for r in checkin.rooms}
    co_rooms = {_norm_name(r.name): r for r in checkout.rooms}

    rooms_out: list[dict] = []
    totals = {"matched": 0, "changed": 0, "unchanged": 0,
              "removed": 0, "added": 0, "classified": 0}

    def _stub(item: Item) -> dict:
        return {"id": item.id, "name": item.name,
                "condition": item.condition,
                "defects": list(item.defects),
                "photo_ids": list(item.photo_ids)}

    all_room_keys = list(ci_rooms) + [k for k in co_rooms if k not in ci_rooms]
    for key in all_room_keys:
        ci_room, co_room = ci_rooms.get(key), co_rooms.get(key)
        room_name = (co_room or ci_room).name
        ci_items = _active_items(ci_room.items) if ci_room else []
        co_items = _active_items(co_room.items) if co_room else []
        pairs, removed, added = align_items(ci_items, co_items)

        changed: list[dict] = []
        unchanged: list[dict] = []
        for ci, co, score in pairs:
            change = diff_pair(ci, co)
            change["match_score"] = score
            if needs_classification(change):
                entry = change_prompt(
                    change, room_name, tenancy_months, occupancy,
                    item_ages.get(ci.id),
                    checkin_description=ci.description,
                    checkout_description=co.description)
                try:
                    verdict = rubric.classify(entry)
                except Exception as e:  # one change must not kill the run
                    log.error("classification failed for %s (%s)", co.name, e)
                    verdict = {"classification": "unclassified",
                               "rationale": f"classification failed: {e}"}
                change.update(verdict)
                if change["classification"] != "unclassified":
                    totals["classified"] += 1
                changed.append(change)
            else:
                unchanged.append({"checkin_id": ci.id, "checkout_id": co.id,
                                  "name": co.name})
        rooms_out.append({
            "name": room_name,
            "checkin_room_present": ci_room is not None,
            "checkout_room_present": co_room is not None,
            "changed": changed,
            "unchanged": unchanged,
            "removed": [_stub(i) for i in removed],
            "added": [_stub(i) for i in added],
        })
        totals["matched"] += len(pairs)
        totals["changed"] += len(changed)
        totals["unchanged"] += len(unchanged)
        totals["removed"] += len(removed)
        totals["added"] += len(added)

    return {
        "checkin": {"address": checkin.property_address,
                    "inspected_at": checkin.inspected_at,
                    "backend": checkin.describe_backend},
        "checkout": {"address": checkout.property_address,
                     "inspected_at": checkout.inspected_at,
                     "backend": checkout.describe_backend},
        "params": {"tenancy_months": tenancy_months, "occupancy": occupancy,
                   "backend": rubric.name, "model": getattr(rubric, "model", None)},
        "rooms": rooms_out,
        "totals": totals,
        "usage": dict(getattr(rubric, "usage", {})),
    }


# --------------------------------------------------------------------------
# Rendering: paired-photo delta report
# --------------------------------------------------------------------------


def _photo_lookup(inv: Inventory) -> dict[str, object]:
    return {p.id: p for r in inv.rooms for p in r.photos}


def _resolve_photo(side_dir: Path, photo) -> Optional[Path]:
    """Find the image file for a photo id: prefer the report's exported
    ``photos/<id>.jpg``, fall back to the recorded capture path."""
    exported = side_dir / "photos" / f"{photo.id}.jpg"
    if exported.is_file():
        return exported
    p = Path(str(photo.path).replace("\\", "/"))
    if not p.is_absolute():
        p = side_dir / p
    return p if p.is_file() else None


def _export_photo(src: Path, dest: Path, max_dim: int = 1000) -> bool:
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if max(im.size) > max_dim:
                im.thumbnail((max_dim, max_dim))
            im.save(dest, quality=85)
        return True
    except Exception as e:
        log.warning("could not export evidence photo %s (%s)", src, e)
        return False


def _evidence_photos(change: dict, side: str, inv: Inventory, side_dir: Path,
                     out_dir: Path, exported: dict, limit: int = 3) -> list[dict]:
    """Pick up to *limit* evidence photos for one side of a changed item —
    photos carrying this item's defect_regions first (the docs/05 Level 2
    regions are the alignment anchor), then the remaining cited photos."""
    lookup = _photo_lookup(inv)
    regions = change[f"{side}_regions"]
    region_ids = [r.get("photo_id") for r in regions if r.get("photo_id")]
    ids = list(dict.fromkeys(region_ids + change[f"{side}_photo_ids"]))[:limit]
    shown = []
    for pid in ids:
        photo = lookup.get(pid)
        if photo is None:
            continue
        key = (side, pid)
        if key not in exported:
            src = _resolve_photo(side_dir, photo)
            rel = f"photos/{side}/{pid}.jpg"
            ok = bool(src) and _export_photo(src, out_dir / rel)
            exported[key] = rel if ok else None
        shown.append({
            "id": pid,
            "src": exported[key],
            "captured_at": getattr(photo, "captured_at", None),
            "regions": [r for r in regions if r.get("photo_id") == pid],
        })
    return shown


def render_comparison(result: dict, checkin: Inventory, checkout: Inventory,
                      checkin_dir: Path, checkout_dir: Path, out_dir: Path,
                      pdf: bool = True) -> dict[str, Path]:
    """Write compare.json, compare.html (and compare.pdf when WeasyPrint can
    run) into *out_dir*. Photo evidence is copied under out_dir/photos/."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    out_dir.mkdir(parents=True, exist_ok=True)
    exported: dict = {}
    view_rooms = []
    for room in result["rooms"]:
        view_changed = []
        for change in room["changed"]:
            view_changed.append({
                **change,
                "checkin_photos": _evidence_photos(
                    change, "checkin", checkin, checkin_dir, out_dir, exported),
                "checkout_photos": _evidence_photos(
                    change, "checkout", checkout, checkout_dir, out_dir, exported),
            })
        view_rooms.append({**room, "changed": view_changed})

    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                      autoescape=select_autoescape(["html"]))
    html = env.get_template("compare.html.j2").render(
        result=result, rooms=view_rooms, class_labels=CLASS_LABELS)

    outputs: dict[str, Path] = {}
    json_path = out_dir / "compare.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    outputs["json"] = json_path
    html_path = out_dir / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    outputs["html"] = html_path
    if pdf:
        try:
            from weasyprint import HTML
            pdf_path = out_dir / "compare.pdf"
            HTML(string=html, base_url=str(out_dir)).write_pdf(str(pdf_path))
            outputs["pdf"] = pdf_path
        except Exception as e:
            log.warning("PDF generation unavailable (%s); HTML report is "
                        "complete.", e)
    return outputs


def load_inventory_arg(path: Path) -> tuple[Inventory, Path, str]:
    """Accept a report directory or an inventory.json path; return
    (inventory, report_dir, raw_json_text)."""
    p = Path(path)
    if p.is_dir():
        p = p / "inventory.json"
    if not p.is_file():
        raise FileNotFoundError(f"no inventory.json at {path}")
    raw = p.read_text(encoding="utf-8")
    return Inventory.from_json(raw), p.parent, raw
