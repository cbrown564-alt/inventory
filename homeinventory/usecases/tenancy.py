"""Tenancy deposit inventory use-case profile."""

from __future__ import annotations

from ..schema import Inventory
from .base import (ComparisonSpec, ContextParam, CoverField, Role, SessionSpec,
                   SharePageSpec, UseCase)

VALUE_BANDS = ["<£50", "£50-250", "£250-1000", ">£1000"]

SYSTEM_PROMPT = """\
You are a professional property inventory clerk preparing a Tenancy Deposit
Scheme (TDS) compliant Inventory & Schedule of Condition. You are exhaustive,
precise, and evidence-based.

Rules:
- List EVERY distinct item of note visible in the photos: structural elements
  (ceiling, walls, woodwork, doors, windows, flooring), fixtures (lights,
  sockets, radiators, blinds), appliances, furniture, soft furnishings,
  electronics, and notable contents. Group identical small items (e.g.
  "Dining chairs x4").
- Each room's structural elements (walls, ceiling, flooring, door, window)
  should each appear as their own item with their own grade.
- ALWAYS check for, and record when visible, the small wall- and ceiling-
  mounted items every clerk records by convention: smoke alarm, heat alarm,
  thermostat, entryphone/intercom, light switches, sockets, air vents,
  door frame, skirting boards, doorstop, threshold strip. They are easy to
  miss in wide shots — scan for them deliberately.
- Condition grades: new / excellent / good / fair / poor. "Good" means sound
  with light wear; reserve "fair" for visible wear/marks and "poor" for damage.
  When torn between "excellent" and "good", clerks record "good" and note any
  blemish in defects — "excellent" implies near-new with no marks at all.

Defects — this is where reports win or lose adjudications:
- Capture footage alternates wide context shots with deliberate CLOSE-UP
  evidence shots (a wall corner, a door edge, a worktop surface). Every
  close-up was taken to document something: examine each one and ask what
  mark, chip, scuff or wear it records, and attach that defect to the item
  it belongs to. A close-up with genuinely nothing visible supports the
  item's clean condition — do not invent a defect for it.
- Localise every defect the way a clerk does — height + side + feature:
  heights are "high level" / "eye level" / "chest level" / "mid level" /
  "knee level" / "low level"; sides are "left hand side" / "right hand side";
  features are "leading edge", "to interior/exterior", "to joins", "behind
  door". Example phrasing: "angle chip knee level left hand side exterior",
  "scuffs mid to low level to walls", "light scale to plastic trim".
- Sweep each item's full surface for the standard defect inventory: scuffs,
  rub marks, angle chips, cracks to joins, scratches, stains/shade marks,
  scale/limescale, tarnish, discoloured grouting, loose fittings, drip marks,
  wear marks, indentations.
- Cleanliness findings are ALSO defects: when glazing is not clean, chrome
  ware carries limescale, grouting is discoloured, a hob or sink shows
  cleaning scratches, frames hold dust, or a surface is smeared or water
  marked, record it as a localised defect on that item — not only in the
  cleanliness grade. Inspect tile grout lines, glass, mirrors and polished
  metal close-ups specifically for these.
- Cleanliness defects do NOT lower the condition grade: condition measures
  wear and damage to the item itself, dirt is removable. An unclean window
  with sound frames and glass is condition "good", cleanliness "requires
  cleaning", defect "glazing not clean".
- Never invent defects you cannot see; if the photo is ambiguous, omit rather
  than guess.

- Describe materials and colours like a clerk: "Oak-effect laminate flooring",
  "Emulsioned magnolia walls", not "wooden floor".
- Only report items actually visible in the supplied photos.
"""

CLASSIFICATION_CLASSES = [
    "fair_wear_and_tear",
    "damage",
    "cleaning",
    "landlord_responsibility",
]
CLASS_LABELS = {
    "fair_wear_and_tear": "Fair wear and tear",
    "damage": "Damage (tenant)",
    "cleaning": "Cleaning (tenant)",
    "landlord_responsibility": "Landlord responsibility",
    "unclassified": "Unclassified",
}
CLASS_TONES = {
    "fair_wear_and_tear": "confirm",
    "damage": "reject",
    "cleaning": "reject",
    "landlord_responsibility": "pend",
    "unclassified": "muted",
}

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


def tenancy_schedule_summary(inv: Inventory) -> list[dict]:
    """Build section 1 rows when none were supplied manually."""
    # lazy import: report.py imports this package at module level
    from ..report import _aggregate_cleanliness, _aggregate_condition

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


def needs_classification(change: dict) -> bool:
    return (change["grade_delta"] or 0) > 0 or bool(change["new_defects"])


_DECLARATION = (
    "This inventory was prepared with AI assistance and has been reviewed for "
    "accuracy by the undersigned. It provides a fair and accurate record of the "
    "contents and internal condition of the property on the date stated. Unless "
    "amendments are notified in writing within 7 days of receipt, this inventory "
    "will be deemed accepted by all parties."
)

_PER_ROOM_SHOTS = (
    {"label": "Wide shot of each wall, floor-to-ceiling", "count": "4 photos"},
    {"label": "Floor coverage + close-up of any marks", "count": "2-3"},
    {"label": "Ceiling and light fittings", "count": "1-2"},
    {"label": "Door (both sides), window(s) incl. frames/sills", "count": "2-4"},
    {"label": "Each appliance: front + inside + behind if movable", "count": "2-3 each"},
    {"label": "Each large furniture item: front + wear points", "count": "1-2 each"},
    {"label": "EVERY existing defect close-up, with context shot", "count": "as needed"},
)

_WHOLE_PROPERTY_SHOTS = (
    "All meters (close enough to read the numbers)",
    "Smoke / CO alarms (one photo each, press test button)",
    "Keys handed over, laid out on a plain surface",
    "Boiler, stopcock, fuse box",
)

TENANCY = UseCase(
    key="tenancy",
    display_name="Inventory",
    description="TDS-compliant inventory and schedule of condition for deposit disputes.",
    system_prompt=SYSTEM_PROMPT,
    value_bands=tuple(VALUE_BANDS),
    report_type="Inventory & Schedule of Condition",
    report_kicker="Inventory & schedule of condition",
    summary_section_title="Schedule of Condition",
    summary_rows=tenancy_schedule_summary,
    declaration_text=_DECLARATION,
    initials_note="Tenant: please initial each page to confirm you have read this report.",
    cover_fields=(
        CoverField("property_address", "Property address", "--address",
                   "e.g. Flat 2, 14 High Street, London SW1A 1AA"),
        CoverField("landlord_name", "Landlord", "--landlord", "Landlord or agent name"),
        CoverField("tenant_name", "Tenant(s)", "--tenant", "Tenant name(s)"),
        CoverField("agent_name", "Clerk / agent", "--agent-name", "Letting agent or inventory clerk"),
        CoverField("agent_phone", "Agent phone", "--agent-phone", "Contact phone"),
        CoverField("property_type", "Property type", "--property-type",
                   "e.g. 1 Bedroom furnished apartment"),
        CoverField("report_ref", "Report reference", "--report-ref", "Reference number"),
    ),
    owner_role=Role("landlord", "Landlord"),
    agent_role=Role("agent", "Agent"),
    counterparty_role=Role("tenant", "Tenant"),
    signing_role_keys=("landlord", "agent", "tenant"),
    share_page=SharePageSpec(
        link_noun="tenant",
        kicker="Inventory & schedule of condition — tenant review",
        howto=(
            "Walk each room with this page open. If something was already "
            "wrong at check-in, add a comment on that item. When you have "
            "walked the whole property, countersign below."
        ),
        sign_bar=(
            "Walked the property and checked this inventory? "
            "Countersigning records your acknowledgement next to the landlord's "
            "signature."
        ),
        placeholder="Your full name",
    ),
    per_room_shots=_PER_ROOM_SHOTS,
    whole_property_shots=_WHOLE_PROPERTY_SHOTS,
    sessions=(SessionSpec("checkin", "Check-in"),),
    comparison=ComparisonSpec(
        title="Check-out comparison",
        baseline="Check-in",
        followup="Check-out",
        classes=tuple(CLASSIFICATION_CLASSES),
        class_labels=CLASS_LABELS,
        class_tones=CLASS_TONES,
        rubric_prompt=RUBRIC_PROMPT,
        gate=needs_classification,
        context_params=(
            ContextParam("tenancy_months", "Tenancy length (months)", "e.g. 12"),
            ContextParam("occupancy", "Occupancy", "e.g. single / couple / family"),
        ),
        item_age_label="Item age at check-in",
        intro_note=(
            "This is a discussion sheet: it identifies, evidences and classifies "
            "changes between the two reports. It does not price anything — "
            "deduction amounts are for the parties (and, failing agreement, the "
            "deposit scheme) to settle."
        ),
    ),
)


def __getattr__(name: str):
    if name == "ITEM_SCHEMA":
        from ..describe import build_item_schema
        return build_item_schema(TENANCY)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
