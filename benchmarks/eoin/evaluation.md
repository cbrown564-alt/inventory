# Weststand professional-report benchmark

**Source:** `18 Weststand Apartments - Highbury Stadium Square - N5 1FG - Inventory  Schedule of Condition - 2026-04-20 - FULL.pdf`  
**Run:** 12 July 2026  
**Pipeline:** tenancy v4 prompt, `claude-opus-4-8`, whole-image mode (`--no-detect`)  
**Evidence:** 257 PDF-extracted photos across 6 physical rooms, predominantly 450x600 pixels  
**Gold:** 93 items, 76 notable items, and 53 clerk-recorded defects

## Result

The established scorer reports:

| Metric | Target | Weststand Opus v4 | InventoryFlex Opus v4 | Result |
|---|---:|---:|---:|---|
| Notable-item recall | >=90 | **96.1** | 88.0 | pass; +8.1 pp |
| All-item recall | - | **95.7** | - | informational |
| Hallucination rate | <=5 | **16.5** | 2.8 | raw fail; audit required |
| Granularity-split rate | - | 27.2 | 29.6 | informational |
| Naming accuracy | >=85 | **94.4** | 94.8 | pass; -0.4 pp |
| Condition exact | >=70 | **75.9** | 93.2 | pass; -17.3 pp |
| Condition within one | >=95 | **94.3** | 100.0 | fail by 0.7 pp |
| Defect recall | >=75 | **75.0** | 71.3 | pass; +3.7 pp |

Counts behind the result: 89/93 gold items found, 73/76 notable items found,
158 predicted items, 26 raw unmatched predictions, 43 granularity splits, and
39/52 scored defects found.

The established defect metric only adds a gold item's defects to the denominator
after that item is name-matched. The missed Hotpoint oven has one gold defect, so
the conservative end-to-end figure is **39/53 = 73.6%**, not 75.0%.

## What worked

- The pipeline found all but three notable items: the Hotpoint oven, mezzanine
  balustrade, and mattress. The only additional missed gold item was the two
  pillows, marked non-notable.
- It reached the defect target despite the same low-resolution ceiling as
  InventoryFlex. This is the strongest evidence so far that the v4 defect sweep
  transfers to a second professional report.
- Naming transferred almost unchanged from InventoryFlex. Brand/model detail was
  recovered for Kuppersbusch, Teka, Zanussi, Hotpoint, Hisense, Schuco, Drayton,
  ProSafe, and ERA items.
- The generated report contains 158 item records with explicit photo references,
  a SHA-256 evidence manifest, and a 61-page signed-report PDF.

## How to read the raw hallucination rate

The 26 raw unmatched predictions are listed with their photo IDs and model
confidence in `report-claude-v4/audit-unmatched-grounding.txt`. They include
threshold strips, thermostats, fused spurs, sockets, a radiator, a handrail, a
smoke/heat alarm, air vents, a consumer unit, and other ordinary visible fixtures.
Every candidate has at least one cited photo. The name-level audit found no
obviously impossible object, but these have not been independently adjudicated
photo-by-photo, so 16.5% remains the official raw result rather than replacing it
with an optimistic adjusted figure.

This report is a useful test of "improve upon the clerk": many raw false positives
are plausible items the clerk omitted or nested inside a broader row. The current
scorer cannot distinguish an evidence-supported additional item from an invention.

## Condition-calibration finding

All five condition errors larger than one grade are `new`/`as new` in the clerk
report versus `good` from the image pipeline: the sofa, office carpet, bedroom
carpet, double bed, and duvet. That status is historical/semantic information, not
reliably visible wear. Native-resolution footage alone will not close this gap.
Fresh capture should carry a structured "new/as new" assertion or narrated age/
replacement context when known.

## Fixture construction

- `benchmarks/extract_weststand.py` extracts the PDF photos and source text.
- The report's separate Reception/Kitchen and Kitchen-and-appliances table sections
  are merged into one physical `Reception Kitchen` room, matching the established
  InventoryFlex convention.
- Cleanliness-only rows are excluded from item gold. Compound clerk rows are split
  where they contain independently inventory-worthy objects; aliases/components
  prevent legitimate finer-grained predictions being charged as inventions.
- Gold labels are at `evals/fixtures/weststand/labels.json`.

## Reproduce

```powershell
uv run --with pypdf python benchmarks\extract_weststand.py

uv run homeinventory build benchmarks\eoin\capture `
  -o benchmarks\eoin\report-claude-v4 `
  --backend claude --model claude-opus-4-8 --no-detect `
  --address "18 Weststand Apartments, Highbury Stadium Square, London, N5 1FG" `
  --inspector "Valeri Traykov" `
  --agent-name "Energy Reports London" `
  --agent-phone "020 3691 4156" `
  --property-type "One-bedroom apartment with office" `
  --report-ref "WESTSTAND-2026-04-20"

uv run python evals\run_eval.py `
  benchmarks\eoin\report-claude-v4\inventory.json `
  evals\fixtures\weststand\labels.json
```

The build CLI currently stamps the run date as `inspected_at`; this benchmark's
generated inventory was corrected to the source inspection date, 20 April 2026,
and re-rendered.

## Fresh-footage experiment

1. Keep this gold fixture fixed and replace the extracted capture with native
   frames from a new walk-through.
2. Record explicit age/newness metadata so the condition rubric can distinguish
   `new` from visually `good`.
3. Ensure direct coverage of the three missed notable items: oven, mezzanine
   balustrade, and mattress.
4. Run the exact no-detector configuration first for comparability, then an A/B
   detector/crop run. The current report has zero item-conditioned crops, so the
   second run measures whether native close-ups improve both defect finding and
   human-review evidence.
5. Independently adjudicate the raw unmatched list. Future scoring should separate
   supported additions from genuine inventions and count defects on missed gold
   items in the defect-recall denominator.
