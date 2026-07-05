"""Check-in vs check-out comparison (M4): alignment, wear-vs-damage rubric,
grade-delta discussion sheet.

Alignment is deliberately lexical and offline — room match (normalised name)
plus head-noun matching reusing :mod:`homeinventory.merge`'s ``_head_nouns``
and containment rule. Zero API calls. An embedding matcher was considered and
not built for v1 (see docs/08-compare.md); renames that only add or drop
descriptor words ("Walls" / "Walls (Cream Emulsion)") align lexically already.

Classification is a prompted, text-only rubric driven by the active use-case
profile's :class:`~homeinventory.usecases.base.ComparisonSpec`. It runs only
for aligned items that pass the spec's gate. The ``offline`` backend yields
``unclassified``. The output is a discussion sheet: it identifies and
classifies changes, it never prices them (no £ amounts — monetary valuation
is an explicit non-goal).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Union

from .merge import _head_nouns
from .schema import CLEANLINESS_GRADES, CONDITION_GRADES, Inventory, Item
from .usecases import get_use_case, use_case_for
from .usecases.base import ComparisonSpec, UseCase
from .usecases.tenancy import (CLASSIFICATION_CLASSES, CLASS_LABELS,
                               RUBRIC_PROMPT, needs_classification)

log = logging.getLogger(__name__)

# Back-compat aliases (tenancy profile originals)
__all__ = [
    "CLASSIFICATION_CLASSES", "CLASS_LABELS", "RUBRIC_PROMPT",
    "needs_classification",
]

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


def _cleanliness_index(grade: Optional[str]) -> Optional[int]:
    return CLEANLINESS_GRADES.index(grade) if grade in CLEANLINESS_GRADES else None


def _norm_defect(d: str) -> str:
    return " ".join(d.strip().lower().split())


def diff_pair(checkin: Item, checkout: Item) -> dict:
    """Structured delta for one aligned pair.

    ``grade_delta`` is checkout minus check-in on the ordinal grade scale —
    positive means worse at check-out. ``cleanliness_delta`` uses the same
    sign convention on :data:`~homeinventory.schema.CLEANLINESS_GRADES`.
    ``new_defects`` are check-out defects with no lexically-equal check-in
    counterpart; ``resolved_defects`` the reverse (informational — two
    independent describes word defects differently, so treat "resolved" as
    "not re-observed").
    """
    ci_idx, co_idx = _grade_index(checkin.condition), _grade_index(checkout.condition)
    delta = (co_idx - ci_idx) if ci_idx is not None and co_idx is not None else None
    ci_cl, co_cl = (_cleanliness_index(checkin.cleanliness),
                   _cleanliness_index(checkout.cleanliness))
    cleanliness_delta = ((co_cl - ci_cl)
                         if ci_cl is not None and co_cl is not None else None)
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
        "cleanliness_delta": cleanliness_delta,
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


CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": CLASSIFICATION_CLASSES},
        "rationale": {"type": "string"},
    },
    "required": ["classification", "rationale"],
    "additionalProperties": False,
}


def _classify_schema(classes: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "properties": {
            "classification": {"type": "string", "enum": list(classes)},
            "rationale": {"type": "string"},
        },
        "required": ["classification", "rationale"],
        "additionalProperties": False,
    }


def change_prompt(change: dict, room: str, spec: ComparisonSpec,
                  context: Optional[dict] = None, age: Optional[str] = None,
                  checkin_description: str = "",
                  checkout_description: str = "") -> str:
    """User-message text for one change. Context values the caller did not
    provide are rendered literally as "not provided" — the rubric may cite
    only provided values."""
    context = context or {}

    def grade(g: Optional[str]) -> str:
        return g if g else "not graded"

    def defects(ds: list[str]) -> str:
        return "; ".join(ds) if ds else "none recorded"

    delta = change.get("grade_delta")
    if delta is None:
        delta_txt = "not gradeable (a grade is missing on one side)"
    elif delta > 0:
        delta_txt = f"{delta} grade(s) worse at {spec.followup.lower()}"
    elif delta < 0:
        delta_txt = f"{-delta} grade(s) better at {spec.followup.lower()}"
    else:
        delta_txt = "no grade change"

    def side_line(side_label: str, cond, clean, description, side_defects):
        line = f"{side_label} record: condition {grade(cond)}"
        if clean:
            line += f"; cleanliness {clean}"
        if description:
            line += f"; {description}"
        return line + f"; defects: {defects(side_defects)}"

    baseline = spec.baseline
    followup = spec.followup
    lines = [
        f"Item: {change.get('checkin_name') or change.get('name')} (room: {room})",
        side_line(baseline, change.get("checkin_condition"),
                  change.get("checkin_cleanliness"), checkin_description,
                  change.get("checkin_defects", [])),
        side_line(followup, change.get("checkout_condition"),
                  change.get("checkout_cleanliness"), checkout_description,
                  change.get("checkout_defects", []))
        + f"; new since {baseline.lower()}: {defects(change.get('new_defects', []))}"
        + (f"; resolved since {baseline.lower()}: "
           + "; ".join(change["resolved_defects"])
           if change.get("resolved_defects") else ""),
        f"Grade change: {delta_txt}",
    ]
    cl_delta = change.get("cleanliness_delta")
    if cl_delta is not None:
        lines.append("Cleanliness change: "
                     + (f"{cl_delta} grade(s) worse" if cl_delta > 0
                        else f"{-cl_delta} grade(s) better" if cl_delta < 0
                        else "no change")
                     + f" at {followup.lower()}")
    for param in spec.context_params:
        val = context.get(param.key)
        if val is not None and val != "":
            lines.append(f"{param.label}: {val}")
        else:
            lines.append(f"{param.label}: not provided")
    if spec.item_age_label:
        lines.append(f"{spec.item_age_label}: {age}" if age
                     else f"{spec.item_age_label}: not provided")
    lines.append("Classify this change.")
    return "\n".join(lines)


class OpenAIRubric:
    """Text-only rubric over any OpenAI-compatible API.

    Transport (base URL / key resolution / error mapping) is reused from
    describe.OpenAICompatBackend; only the payload differs (no images, the
    classification schema instead of the item schema). Default model is
    gpt-5.4-mini — the model the rubric's IMS agreement numbers were
    measured on (docs/08-compare.md).
    """

    name = "openai"
    DEFAULT_MODEL = "gpt-5.4-mini"

    def __init__(self, spec: ComparisonSpec, model: Optional[str] = None,
                 base_url: Optional[str] = None):
        from .describe import OpenAICompatBackend
        self.spec = spec
        self._classes = spec.classes
        self._schema = _classify_schema(spec.classes)
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
                {"role": "system", "content": self.spec.rubric_prompt},
                {"role": "user", "content": entry_text},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "change_classification", "strict": True,
                "schema": self._schema}},
        }
        resp = self._api._post(payload)
        self._accumulate(resp)
        data = json.loads(resp["choices"][0]["message"]["content"])
        cls = data.get("classification")
        if cls not in self._classes:
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


def get_rubric_backend(name: str, spec: ComparisonSpec,
                       model: Optional[str] = None,
                       base_url: Optional[str] = None):
    if name == "openai":
        return OpenAIRubric(spec, model=model, base_url=base_url)
    if name == "offline":
        return OfflineRubric()
    raise ValueError(f"unknown compare backend: {name!r} (expected openai|offline)")


# --------------------------------------------------------------------------
# Comparison orchestration
# --------------------------------------------------------------------------


def _resolve_use_case(checkin: Inventory, checkout: Inventory,
                      use_case: Optional[Union[str, UseCase]] = None) -> UseCase:
    if isinstance(use_case, UseCase):
        return use_case
    if use_case is not None:
        return get_use_case(use_case)
    ci = use_case_for(checkin)
    co = use_case_for(checkout)
    if ci.key != co.key:
        raise ValueError(
            f"use_case mismatch: check-in has {ci.key!r}, check-out has {co.key!r}")
    return ci


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
                        rubric=None, use_case: Optional[Union[str, UseCase]] = None,
                        context: Optional[dict] = None,
                        item_ages: Optional[dict[str, str]] = None) -> dict:
    """Align two inventories and classify changes that pass the use-case gate.

    Every item on either side is accounted for exactly once: matched
    (changed or unchanged), removed (baseline only) or added (followup only).
    ``rubric`` (see :func:`get_rubric_backend`) classifies gated matched
    items; ``None`` behaves like offline.
    """
    uc = _resolve_use_case(checkin, checkout, use_case)
    spec = uc.comparison
    if spec is None:
        raise ValueError(f"use case {uc.key!r} has no comparison profile")

    rubric = rubric or OfflineRubric()
    context = dict(context or {})
    item_ages = item_ages or {}
    gate = spec.gate

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
            if gate(change):
                entry = change_prompt(
                    change, room_name, spec, context,
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
        "use_case": uc.key,
        "labels": {"baseline": spec.baseline, "followup": spec.followup},
        "comparison": {
            "title": spec.title,
            "intro_note": spec.intro_note,
            "class_labels": spec.class_labels,
            "class_tones": spec.class_tones,
            "context_params": [
                {"key": p.key, "label": p.label} for p in spec.context_params
            ],
        },
        "params": {"context": context,
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


def _timecode(seconds) -> str:
    s = max(0, int(seconds or 0))
    h, m, r = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{r:02d}" if h else f"{m}:{r:02d}"


def _guess_capture_dir(report_dir: Path) -> Optional[Path]:
    """Deep-clean layout: sibling ``capture/<session>/`` next to ``report/``."""
    cap = report_dir.parent.parent / "capture" / report_dir.name
    return cap if cap.is_dir() else None


def _photo_times(inv: Inventory, report_dir: Path) -> dict[str, dict]:
    cap = _guess_capture_dir(report_dir)
    if cap is None:
        return {}
    from .videometa import video_payload
    _, photo_time = video_payload(inv, cap, report_dir / "work", "", {})
    return photo_time


def _evidence_photos(change: dict, side: str, inv: Inventory, side_dir: Path,
                     out_dir: Path, exported: dict,
                     photo_time: dict[str, dict] | None = None,
                     limit: int = 3) -> list[dict]:
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
        pt = (photo_time or {}).get(pid)
        entry = {
            "id": pid,
            "src": exported[key],
            "captured_at": getattr(photo, "captured_at", None),
            "source_video": getattr(photo, "source_video", None),
            "regions": [r for r in regions if r.get("photo_id") == pid],
        }
        if pt and pt.get("t") is not None:
            entry["seen_at"] = _timecode(pt["t"])
        shown.append(entry)
    return shown


def render_comparison(result: dict, checkin: Inventory, checkout: Inventory,
                      checkin_dir: Path, checkout_dir: Path, out_dir: Path,
                      pdf: bool = True) -> dict[str, Path]:
    """Write compare.json, compare.html (and compare.pdf when WeasyPrint can
    run) into *out_dir*. Photo evidence is copied under out_dir/photos/."""
    from jinja2 import Environment, FileSystemLoader

    out_dir.mkdir(parents=True, exist_ok=True)
    exported: dict = {}
    checkin_pt = _photo_times(checkin, checkin_dir)
    checkout_pt = _photo_times(checkout, checkout_dir)
    view_rooms = []
    filter_classes: list[str] = []
    for room in result["rooms"]:
        view_changed = []
        for change in room["changed"]:
            cls = change.get("classification") or "unclassified"
            if cls not in filter_classes:
                filter_classes.append(cls)
            view_changed.append({
                **change,
                "checkin_photos": _evidence_photos(
                    change, "checkin", checkin, checkin_dir, out_dir, exported,
                    checkin_pt),
                "checkout_photos": _evidence_photos(
                    change, "checkout", checkout, checkout_dir, out_dir, exported,
                    checkout_pt),
            })
        view_rooms.append({**room, "changed": view_changed})

    comp = result["comparison"]
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                      autoescape=True)
    env.filters["timecode"] = _timecode
    html = env.get_template("compare.html.j2").render(
        result=result, rooms=view_rooms,
        labels=result["labels"],
        class_labels=comp["class_labels"],
        class_tones=comp["class_tones"],
        context_params=comp["context_params"],
        filter_classes=filter_classes)

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
