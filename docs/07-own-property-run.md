# M2 own-property run — first full build on the user's tenancy

**Date:** 3 July 2026
**Capture:** one continuous ~13-minute 1080p walkthrough video, split into 10
per-room segments (`capture/<Room>/<room>.mov`), two rooms visited twice
(Bedroom 1, Loft Bedroom — their segments are `_a`/`_b`).
**Build:** `--backend claude` (claude-opus-4-8), YOLOE in `prompt_free` mode —
the ultralytics CLIP text-mode dependency is permission-blocked in this
environment, so the text-vocabulary detector path is unavailable and every
own-property build runs prompt-free.
**Raw output frozen:** `report/pristine/inventory.raw.json`
(sha256 `60398db6ffedfd5917db3ee6bb6b038c8be3ae7eb9ae8f879475001708236bba`)
plus all 10 room checkpoints under `report/pristine/checkpoints/`, captured
before any review edit. Every eval scores the pristine copy; the shipped
report renders the reviewed `report/inventory.json`.

## The room-boundary bleed failure mode

The per-room segments were cut from the single walkthrough with stream copy,
which can only cut on keyframes: each segment starts up to ~2s **before** its
nominal room boundary, i.e. inside the previous room. The keyframe extractor
(`ingest.extract_keyframes`) faithfully keeps the sharpest frames from that
lead window, so the describe model receives — and itemises — the tail of the
previous room in the wrong room's schedule. The walkthrough also *started* in
the hallway before entering the first room, so even the first segment
(Kitchen) carries lead-frame bleed. A related, smaller effect: open-plan
sight lines (the kitchen zone visible from the living/dining area) let the
model re-itemise another room's fixtures without any lead frames at all.

## Boundary-bleed scan — all 10 rooms (3 Jul 2026)

Method: every room's item schedule read from the pristine checkpoints;
thematically inconsistent items flagged; each flag verified against the
extracted keyframes in `report/work/frames/<Room>/` (segment-start frames
first). Per-item dispositions with keyframe evidence are recorded in
[`evals/fixtures/ownproperty-bleed-exclusions.json`](../evals/fixtures/ownproperty-bleed-exclusions.json).

| Room | Verdict | Bleed items (source) |
|---|---|---|
| Kitchen | **AFFECTED** | 5 hallway/stairs items — walkthrough started in the hallway (`kitchen_f000009` is the hallway) |
| Living Room | **AFFECTED** | 6 kitchen items — lead frames + open-plan sight lines (`living_f000009` is the kitchen units) |
| Hallway | pass | — (its cupboard/console items are genuine) |
| Bathroom | **AFFECTED** | 5 hallway coat/boiler-cupboard items (`bathroom_f000027/45/90` are all the cupboard) |
| Bedroom 1 | **AFFECTED** | 8 en-suite items + 1 landing wallpaper (`bedroom1_b_f000000/27` are the en-suite) |
| En-suite Shower Room | pass | bleed frames present (`ensuite_f000000` is Bedroom 1) but no items misattributed |
| Stairs and Landing | pass | — |
| Loft Office | pass | — |
| Loft Bedroom | **AFFECTED** | 5 loft-shower items (`loft_bedroom_b_f000000` is the shower room) |
| Loft Shower Room | **AFFECTED** | 5 loft-bedroom items — chest of drawers, lamp, picture, bin, thermostat all on bedroom carpet in `loft_shower_f000090/162` |

**6 of 10 rooms affected → the DoD escalation rule fired** (threshold: >1
room). The ingest-level fix was promoted into this milestone: `build
--trim-lead SECONDS` (default 0.0, off) skips the lead window of each room
video at keyframe extraction (`ingest.extract_keyframes(lead_trim_s=…)`),
removing the bleed at the source. Unit test:
`tests/test_pipeline.py::test_extract_keyframes_lead_trim`. Use `--trim-lead
2.0` for the next build from stream-copy-split walkthrough segments. The
open-plan double-counting component (Living Room ↔ Kitchen) is *not* fixed by
trimming and remains review-loop work.

## Reviewed-copy cleanup

All 35 verified bleed entries were dispositioned in the reviewed
`report/inventory.json` via the review loop (hand-edit + `homeinventory
render`): 33 removed (every one already itemised in its true room's
schedule — nothing lost), 2 **moved** to their true rooms because the true
room had not itemised them (`LOF-033` en-suite extractor fan → `LOF3-026`
Loft Shower Room; `LOF3-016` chest of drawers → `LOF-037` Loft Bedroom).
Item count 322 → 289. The pristine copy is untouched (hash above). The
committed exclusion list is also the input for the fixture phase's
dual hallucination reporting: raw (drives ingest-escalation decisions) vs
bleed-excluded (gates the prompt-tuning exit).

## Run cost — derived estimate, method shown

The run pre-dates token-usage capture (landed for `claude` in this
milestone: `ClaudeBackend` now records `response.usage` input/output tokens
into each room checkpoint's `timing` field, mirroring `LocalBackend`), so
this figure is **reconstructed, not billed**:

- **Input:** 260 keyframes across 10 rooms × ~1,600 tokens per 1080p image
  (resized to 1568px max dim) + ~865 system-prompt tokens and ~250
  label/task tokens per room call ≈ **427k input tokens**.
- **Output:** per-room checkpoint JSON chars ÷ 4 ≈ **47k output tokens**.
- **Price:** opus-4-8 $5/$25 per M in/out (June 2026, docs/06).

Total ≈ **$3.32**; docs/06's identical reconstruction method undershot the
actual bill by ~17% (schema injection + output estimate), so treat
**~$3.30–3.90 (≈ £2.40–2.90)** as the range. Consistent with the £2–3/pass
planning estimate; the next run records actuals.

## Artefacts

- `report/pristine/` — frozen raw output (never edited; all evals score this)
- `report/inventory.json` + `.html` + `.pdf` + `manifest.json` — reviewed report (gitignored)
- `evals/fixtures/ownproperty-bleed-exclusions.json` — committed per-item bleed dispositions (names/ids only, no photos)
- `--trim-lead` on `homeinventory build` + `test_extract_keyframes_lead_trim` — the escalation fix
