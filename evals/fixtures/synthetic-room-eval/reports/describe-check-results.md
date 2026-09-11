# Describe check results

Recorded 2026-08-06T20:55:06.186273+00:00.

## Set

Twelve complete GPT Image 2 packets:

- `RP-001` — Kitchen
- `RP-002` — Bathroom
- `RP-004` — Kitchen
- `RP-006` — Bathroom
- `RP-007` — Shower room
- `RP-009` — Bedroom
- `RP-011` — Living room
- `RP-013` — Living room
- `RP-015` — Entrance hall
- `RP-016` — Dining room
- `RP-021` — Stairs and landing
- `RP-024` — Home office

## Method

- Gold: spec-seeded from `intended_visible_items` / `intended_defects`, filled by Gemini 3.5 Flash (cross-family to GPT Image 2).
- Spot-check: owner accepted all seven defect claims on 2026-08-06.
- Describe: production `homeinventory build --photo-mode --no-detect` via `openai` / `gemini-3.5-flash`.
- Readout: invent/omit diagnostics only — no pass bar.

## Invent / omit

| Claim type | Omit rate | Invent rate | Notes |
|---|---:|---:|---|
| Identity | 0.4076 | 0.3472 | omit 97 / 238; invent 75 / 216 |
| Condition | 0.0355 | 0.0355 | grade disagreements on 5 / 141 aligned items |
| Cleanliness | 0.2411 | 0.2411 | grade disagreements on 34 / 141 aligned items |
| Defects | 0.0 | 0.75 | omit 0; invent 42 |

Identity rates are dominated by naming/alignment (e.g. gold `wash basin` vs describe `Pedestal Basin`, gold `base unit door` vs `Kitchen Base Cabinets`). Several real defect hits are therefore counted under defect *invent* on the describe side rather than as aligned defect recall. Condition grades on aligned items are mostly stable; cleanliness moves more.

## Defects for owner spot-check

| Packet | Item | Defect |
|---|---|---|
| RP-001 | base unit door | one small chip on the lower edge of a base unit door |
| RP-002 | bath panel | short shallow scuff on the lower bath panel |
| RP-004 | patterned vinyl floor | small triangular tear in the vinyl floor beside the cooker |
| RP-006 | vanity drawer | small chip on the upper corner of the vanity drawer front |
| RP-009 | drawer front | two short scratches beside the top drawer handle |
| RP-011 | sofa arm | small frayed patch on the outer sofa arm |
| RP-021 | tread edge | frayed strip along the front edge of one stair tread |

## Stop

Describe check measurement is complete. Owner spot-check of defects accepted 2026-08-06. Compare check remains deferred. Prompt tournament, Pass B backlog, video arm, and further generation stay closed.

## Artifacts

- Gold: `outputs/describe-check/gold/`
- Describes: `outputs/describe-check/captures/RP-*/report/inventory.json`
- Score JSON: `reports/describe-check-score-2026-08-06.json`
