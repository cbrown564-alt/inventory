# 16 — The report reads like a catalogue, not a spreadsheet

*5 Jul 2026. The report visual redesign deferred from docs/15. Quality bar
stays docs/10 ("Linear, not toy"); design language stays docs/14 (the warm
paper world); curation and the one-app shell are docs/15 and are assumed.
The brief is unchanged: elegance, simplicity, comprehensiveness.*

## The critique — where the paper world breaks

Screenshots of the own-property build say it plainly. The cover, the room
cover photos and the exhibit captions already speak docs/14's language;
then the schedule begins and the document turns into a data grid.

1. **The schedule is a spreadsheet wearing a serif.** Seven columns force
   prose into twelve-character ribbons — "White front-loading washing
   machine with chrome/silver door trim…" wraps eight lines deep in a
   finger-width column while the Cleanliness column beside it holds five
   repeated words. The eye is made to travel *down columns of boilerplate*
   instead of *across entries of substance*.
2. **Boilerplate outweighs signal.** "cleaned to domestic standard" thirty
   times a room, "None noted" forty — the two rare defects that justify
   the document drown in the words that say nothing happened.
3. **Defects shout.** Every finding is a bright-red bullet in its own
   column. A schedule of condition notes damage gravely; it does not
   hyperventilate. docs/14 called this register *evidential gravity*.
4. **Uniform weight.** Ref, name, description, grade all set at the same
   size in the same places; category bands are grey table rows. Nothing
   guides the eye, so everything competes.

## The reference — what a £165 document does

The InventoryFlex sample (docs/06) — the genuinely professional artefact
we benchmark against — reads as *entries*: a bold name, a paragraph of
description at readable measure, the grade set apart. And the older model
it descends from is the **auction catalogue**: lot number in the margin,
title bold, description at full measure, estimate right-aligned — a form
built for hundreds of short entries that must each be findable, readable
and quietly authoritative. That is exactly our shape: mono ref in the
margin, item name, prose description, grade cluster right, evidence refs
as exhibit marks.

## The design — entries, not rows

Each item becomes a typeset **catalogue entry**:

- **Margin:** `4.11` over `KIT-009` — clerk ref and internal id, mono,
  muted, the deep link into review kept (docs/15 M1).
- **Entry line:** item name in semibold serif; the YOLOE close-up
  (docs/15 M4) sits at the line's right end as a small square vignette.
- **Grade cluster, right-set:** condition in small caps, cleanliness in
  small muted type beneath it — one glanceable column of judgement,
  separate from the reading column of description.
- **Description at full measure** (~65ch) beneath the name.
- **Defects as a grave note:** sentence-case lines behind a thin red
  rule — not bullets, no red column. *Absence says "none noted"* on
  screen; the printed schedule keeps the explicit words for the record.
- **Evidence line:** `Evidence P125, P126` in mono, last, quiet.
- **Category headings** become small-caps run-ins over a hairline — the
  auction catalogue's section marks — not banded table rows.
- **Room heads carry the comprehensiveness numbers** (docs/15): "35 items
  · 24 frames analysed, 6 shown · footage living.mov" under the h2, so
  thoroughness is a stated figure, not a wall of images.
- The room summary sheds its grey band and becomes a serif lead
  paragraph behind a brass hairline — the clerk's opening remark.

## The constraint — one markup, three renderings

The schedule markup cannot be rebuilt as `<div>`s, because two other
renderings graft onto it:

- The **Level-1 review layer** (`report.html.j2` JS) addresses
  `.ref-cell/.name-cell/.desc-cell/…` by class and inserts drawer rows
  (`tr.rv-evidence`) between item rows.
- **WeasyPrint** renders the clerk PDF from the same DOM through
  `@media print`, which needs real table semantics and the merged
  `.print-only` cells.

So the table stays. The redesign is a *screen-media stylesheet*: under
`@media screen`, room item tables drop their `thead`, and each
`tr.item-row` becomes a CSS grid that places its existing cells into the
entry layout (`ref | name/desc | grade`, defects and evidence full-width
beneath). Print CSS is untouched; the review layer keeps every hook, with
its active-row and drawer styles restated for the grid. The
schedule-summary table (section 1) and the appendix manifest remain true
tables — they really are tabular.

One narrow-viewport rule stacks the grade cluster under the name below
640px (the docs/10 phone pass).

## Milestones

- **R1 — the entry layout.** Screen-media grid over the existing table,
  category run-ins, grade cluster, quiet boilerplate, grave defects,
  evidence line. Done = a room section reads top-to-bottom like a
  catalogue page; review mode still confirms/rejects/grades on the same
  rows; the drawer still opens.
- **R2 — the frame.** Room-head meta numbers, summary as lead paragraph,
  photograph strip heading as run-in. Done = a room is scannable in one
  screen: head, numbers, cover, remark, entries.
- **R3 — verification.** Browser round-trip (shell nav, review mode,
  drawer, deep links) at desktop and 390px; WeasyPrint PDF byte-compared
  against pre-redesign output for layout-affecting regressions (the PDF
  should be *unchanged* apart from build metadata).

Definition of done stays docs/10's: reachable from the UI, product-grade.

## Shipped — 5 Jul 2026 (same day)

All three milestones, verified against the own-property build in a real
browser (playwright, 1280px and 500px) and in the PDF:

- **R1/R2:** the Living Room and Loft sections read as catalogue pages —
  margin refs, right-set grade clusters, defects behind the red hairline,
  `Evidence P125, P126` lines, small-caps category run-ins, the room head
  numbers ("38 items recorded · 24 frames analysed, 6 shown · footage
  living.mov"), the summary as an italic lead behind a brass rule.
  "None noted" and its forty repetitions are gone from the screen; the
  printed schedule still records the words.
- **R3:** review mode grafts cleanly onto the grid — drawer opens with
  the evidence strip (7 thumbs on LIV-001), space confirms and the
  docket ticks, grade selects render; the active row wears a ring
  instead of per-cell rims. At 500px the entry stacks with ~0 horizontal
  overflow. WeasyPrint output is *identical* to the pre-redesign
  template: same 75 pages, sampled page text byte-equal (the 72→75
  drift against the committed PDF was yesterday's docs/15 M-work).
  Full suite: 186 passed.
- One pre-existing quirk kept, not caused by the grid: in review mode a
  click landing on the contenteditable description doesn't open the
  drawer (the editor stops propagation) — click anywhere else on the
  entry, or j/k.
