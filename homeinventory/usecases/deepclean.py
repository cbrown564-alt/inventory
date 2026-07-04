"""Deep-clean before/after use-case profile."""

from __future__ import annotations

from ..schema import Inventory
from .base import (DEFECT_SWEEP, LOCALISATION_RULES, ComparisonSpec, ContextParam,
                   CoverField, Role, SessionSpec, SharePageSpec, UseCase)

CLASSIFICATION_CLASSES = [
    "not_cleaned",
    "cleaning_damage",
    "pre_existing",
]
CLASS_LABELS = {
    "not_cleaned": "Not cleaned",
    "cleaning_damage": "Cleaning damage",
    "pre_existing": "Pre-existing",
    "unclassified": "Unclassified",
}
CLASS_TONES = {
    "not_cleaned": "reject",
    "cleaning_damage": "reject",
    "pre_existing": "pend",
    "unclassified": "muted",
}

RUBRIC_PROMPT = """\
You classify cleanliness and condition changes between a before-cleaning report
and an after-cleaning report. Assign exactly one class to each change:

- "not_cleaned": the item or area was not brought to the agreed cleaning
  standard — dirt, grease, limescale or residue remains that cleaning should
  have removed.
- "cleaning_damage": damage caused by the cleaning process itself — scratches,
  water marks, chemical burns, lifted finishes, or broken fittings from
  over-aggressive cleaning.
- "pre_existing": the state was already present before cleaning, or the change
  is wear unrelated to the cleaning visit — not attributable to the cleaner.

Principles:
1. Condition and cleanliness are distinct: removable dirt is "not_cleaned";
   physical damage from cleaning technique is "cleaning_damage".
2. Where the evidence is genuinely ambiguous between cleaning_damage and
   pre_existing, prefer "pre_existing" — the cleaner should not be blamed
   without clear evidence.
3. Use ONLY the scope and clean date you are given. Where a value reads
   "not provided", you must not assume one and must not cite it in the
   rationale.

Respond with JSON: {"classification": <one class>, "rationale": <1-3
sentences citing the observed change and only the provided context values>}.
"""

SYSTEM_PROMPT = f"""\
You are a professional cleaning-condition inspector preparing a before/after
Cleaning Condition Report. You are exhaustive, precise, and evidence-based.

Rules:
- List EVERY distinct item of note visible in the photos: structural elements
  (ceiling, walls, woodwork, doors, windows, flooring), fixtures (lights,
  sockets, radiators, blinds), appliances, furniture, soft furnishings,
  and notable contents. Group identical small items (e.g. "Dining chairs x4").
- Condition grades: new / excellent / good / fair / poor. "Good" means sound
  with light wear; reserve "fair" for visible wear/marks and "poor" for damage.
- Cleanliness grades: professionally cleaned / cleaned to domestic standard /
  requires cleaning. Record the actual cleanliness visible, not what was
  promised.

Defects — document what the photos show:
{DEFECT_SWEEP}
{LOCALISATION_RULES}
- Cleanliness findings are ALSO defects: when glazing is not clean, chrome
  ware carries limescale, grouting is discoloured, a hob or sink shows
  cleaning scratches, frames hold dust, or a surface is smeared or water
  marked, record it as a localised defect on that item — not only in the
  cleanliness grade.
- Never invent defects you cannot see; if the photo is ambiguous, omit rather
  than guess.

- Describe materials and colours precisely: "Oak-effect laminate flooring",
  "Emulsioned magnolia walls", not "wooden floor".
- Only report items actually visible in the supplied photos.
"""


def _cleanliness_delta(change: dict) -> int:
    from ..schema import CLEANLINESS_GRADES

    ci = change.get("checkin_cleanliness")
    co = change.get("checkout_cleanliness")
    if ci not in CLEANLINESS_GRADES or co not in CLEANLINESS_GRADES:
        return 0
    return CLEANLINESS_GRADES.index(co) - CLEANLINESS_GRADES.index(ci)


def needs_classification(change: dict) -> bool:
    if change.get("new_defects") or change.get("resolved_defects"):
        return True
    if (change.get("grade_delta") or 0) != 0:
        return True
    if _cleanliness_delta(change) != 0:
        return True
    return False


def deepclean_summary_rows(inv: Inventory) -> list[dict]:
    from ..report import _aggregate_cleanliness, sort_rooms

    rows = []
    for i, room in enumerate(sort_rooms(inv.rooms), start=1):
        items = [it for it in room.items if not it.rejected]
        rows.append({
            "ref": f"1.{i}",
            "name": room.name,
            "condition": _aggregate_cleanliness(items),
        })
    return rows


_DECLARATION = (
    "This cleaning condition report was prepared with AI assistance and has "
    "been reviewed for accuracy by the undersigned. It provides a fair record "
    "of the property's cleanliness and condition on the dates stated."
)

_PER_ROOM_SHOTS = (
    {"label": "Wide shot of each wall, floor-to-ceiling", "count": "4 photos"},
    {"label": "Floor coverage + close-up of any marks or residue", "count": "2-3"},
    {"label": "Ceiling and light fittings", "count": "1-2"},
    {"label": "Door (both sides), window(s) incl. frames/sills", "count": "2-4"},
    {"label": "Each appliance: front + inside + behind if movable", "count": "2-3 each"},
    {"label": "Each large furniture item: front + wear points", "count": "1-2 each"},
    {"label": "EVERY soiled or damaged area close-up, with context shot", "count": "as needed"},
)

_WHOLE_PROPERTY_SHOTS = (
    "Overall property condition from the entrance",
    "Kitchen and bathroom overview shots",
    "Any areas outside the agreed cleaning scope",
)

DEEP_CLEAN = UseCase(
    key="deepclean",
    display_name="Deep clean",
    description="Before/after cleaning condition report for domestic and commercial cleans.",
    system_prompt=SYSTEM_PROMPT,
    value_bands=None,
    report_type="Cleaning Condition Report",
    report_kicker="Cleaning condition report",
    summary_section_title="Cleanliness Summary",
    summary_rows=deepclean_summary_rows,
    declaration_text=_DECLARATION,
    initials_note=None,
    cover_fields=(
        CoverField("property_address", "Property address", "--address",
                   "e.g. Flat 2, 14 High Street, London SW1A 1AA"),
        CoverField("customer_name", "Customer", "--customer", "Customer name"),
        CoverField("cleaner_name", "Cleaner / company", "--cleaner", "Cleaning company or operative"),
        CoverField("property_type", "Property type", "--property-type",
                   "e.g. 2 bed end-of-terrace"),
        CoverField("report_ref", "Report reference", "--report-ref", "Reference number"),
    ),
    owner_role=Role("customer", "Customer"),
    agent_role=None,
    counterparty_role=Role("cleaner", "Cleaner"),
    signing_role_keys=("customer", "cleaner"),
    share_page=SharePageSpec(
        link_noun="customer",
        kicker="Cleaning condition report — customer review",
        howto=(
            "Walk each room with this page open. If something was missed or "
            "damaged during cleaning, add a comment on that item. When you "
            "have checked the whole property, acknowledge below."
        ),
        sign_bar=(
            "Walked the property and checked this report? "
            "Acknowledging records your sign-off next to the cleaner's signature."
        ),
        placeholder="Your full name",
    ),
    per_room_shots=_PER_ROOM_SHOTS,
    whole_property_shots=_WHOLE_PROPERTY_SHOTS,
    sessions=(
        SessionSpec("before", "Before"),
        SessionSpec("after", "After"),
    ),
    comparison=ComparisonSpec(
        title="Cleaning comparison",
        baseline="Before",
        followup="After",
        classes=tuple(CLASSIFICATION_CLASSES),
        class_labels=CLASS_LABELS,
        class_tones=CLASS_TONES,
        rubric_prompt=RUBRIC_PROMPT,
        gate=needs_classification,
        context_params=(
            ContextParam("scope", "Cleaning scope", "e.g. full deep clean / kitchen only"),
            ContextParam("clean_date", "Clean date", "e.g. 2026-07-04"),
        ),
        intro_note=(
            "This is a discussion sheet: it identifies and classifies changes "
            "between the before and after reports. It does not price anything."
        ),
    ),
)
