"""Use-case profile dataclasses and shared prompt fragments."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..schema import Inventory

LOCALISATION_RULES = """\
- Localise every defect the way a clerk does — height + side + feature:
  heights are "high level" / "eye level" / "chest level" / "mid level" /
  "knee level" / "low level"; sides are "left hand side" / "right hand side";
  features are "leading edge", "to interior/exterior", "to joins", "behind
  door". Example phrasing: "angle chip knee level left hand side exterior",
  "scuffs mid to low level to walls", "light scale to plastic trim"."""

DEFECT_SWEEP = """\
- Capture footage alternates wide context shots with deliberate CLOSE-UP
  evidence shots (a wall corner, a door edge, a worktop surface). Every
  close-up was taken to document something: examine each one and ask what
  mark, chip, scuff or wear it records, and attach that defect to the item
  it belongs to. A close-up with genuinely nothing visible supports the
  item's clean condition — do not invent a defect for it.
- Sweep each item's full surface for the standard defect inventory: scuffs,
  rub marks, angle chips, cracks to joins, scratches, stains/shade marks,
  scale/limescale, tarnish, discoloured grouting, loose fittings, drip marks,
  wear marks, indentations."""


@dataclass(frozen=True)
class Role:
    key: str
    label: str


@dataclass(frozen=True)
class CoverField:
    name: str
    label: str
    cli_flag: str
    placeholder: str


@dataclass(frozen=True)
class SessionSpec:
    key: str
    label: str


@dataclass(frozen=True)
class ContextParam:
    key: str
    label: str
    placeholder: str


@dataclass(frozen=True)
class ComparisonSpec:
    title: str
    baseline: str
    followup: str
    classes: tuple[str, ...]
    class_labels: dict[str, str]
    class_tones: dict[str, str]
    rubric_prompt: str
    gate: Callable[[dict], bool]
    context_params: tuple[ContextParam, ...]
    intro_note: str


@dataclass(frozen=True)
class SharePageSpec:
    link_noun: str
    kicker: str
    howto: str
    sign_bar: str
    placeholder: str


@dataclass(frozen=True)
class UseCase:
    key: str
    display_name: str
    description: str
    system_prompt: str
    value_bands: tuple[str, ...] | None
    report_type: str
    report_kicker: str
    summary_section_title: str | None
    summary_rows: Callable[[Inventory], list[dict]] | None
    declaration_text: str
    initials_note: str | None
    cover_fields: tuple[CoverField, ...]
    owner_role: Role
    agent_role: Role | None
    counterparty_role: Role
    signing_role_keys: tuple[str, ...]
    share_page: SharePageSpec
    per_room_shots: tuple[dict, ...]
    whole_property_shots: tuple[str, ...]
    sessions: tuple[SessionSpec, ...]
    comparison: ComparisonSpec | None
