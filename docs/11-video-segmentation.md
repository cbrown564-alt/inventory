# 11 — Room segmentation from one walkthrough video

*4 Jul 2026. Spike record. The product pivot (see docs/09 §M5b retirement
note and docs/10's quality bar) makes one continuous phone video the primary
capture path; nothing in the pipeline could turn one video into rooms — the
folder-per-room convention made the **user** do the segmentation (M2's
13-minute video was cut into ten per-room clips by hand). This spike answers:
can a VLM place and name the room boundaries well enough to carry the
primary journey?*

## Method

`homeinventory/segment.py`: sample a timestamped thumbnail strip (448 px,
~26 KB JPEG, one frame per 5 s → 161 frames for the 13.4-min own-property
video), send it to a VLM in chunks under the 100-image request cap (each
continuation chunk is told the rooms named so far and the room the previous
chunk ended in), with a strict JSON schema for `{room, start_s, end_s}`
segments and clerk-style naming rules. Normalisation forces contiguity
(midpoint seams, no gaps — a gap would silently drop footage from the
schedule) and merges same-room neighbours.

Validation: the M2 own-property video, judged two ways — (a) against the
10-room manual cut frozen in `report/inventory.json` (Hallway, Living Room,
Kitchen, Bedroom 1, Loft Bedroom, Bathroom, En-suite Shower Room, Loft
Office, Loft Shower Room, Stairs and Landing); (b) by eyeballing the strip
frames at every disputed boundary (the spike writes a per-model
`contact_sheet.html` grouped by assigned room with boundary frames flagged).

## Results (same 161-frame strip for every model)

| Model | Segments | Verdict against footage |
|---|---|---|
| **claude-sonnet-5** | 15 | **Best.** Matches the manual cut's structure and refines it: separates Loft Office from Loft Bedroom, finds the storage cupboard (5:36–5:51, frame-verified real), all three wet rooms placed correctly (Bathroom / En-suite off Bedroom 1 / Loft Shower Room) |
| **gemini-3.5-flash** | 12 | **Very close second.** Boundary-for-boundary with sonnet except two merges: loft office folded into Loft Bedroom, storage cupboard folded into Hallway. No invented rooms |
| gpt-4.1-mini | 13 | Mixed: loft structure right, but a 70 s "Bathroom" that spans the real Bedroom 1 + En-suite, and the final Loft Shower Room misnamed "Bathroom" |
| gpt-5.4-mini | 13 | Poor: merged the entire kitchen (frame-verified close-up sequence, 0:10–4:20) into "Living Room"; one giant undifferentiated "Loft Room" |
| claude-haiku-4-5 | 20 | Poor: 5 s segment flicker, called the hallway "Bedroom 2", called Bedroom 1 "Bathroom" for 75 s, invented a Utility Room |
| gemini-3.1-flash-lite | 18 | Worst: invented Bedroom 2 and Bedroom 3, En-suite appears three times, stairs called Hallway |

Frame-verified spot checks that decided the ranking: t=265 (haiku's
"Utility Room" is the kitchen-diner's dining end), t=331 (haiku's
"Bedroom 2" is the hallway looking into the bathroom), t=376 (haiku's and
gpt-4.1-mini's long "Bathroom" is a double bedroom), t=341 (sonnet's
Storage Cupboard is a real coat cupboard), t=561 (desk + monitor + Mac
mini: the Loft Office sonnet separates and gemini merges).

Measured tokens per full-video run: sonnet 78k in / 8.9k out (≈ £0.30 at
list price, most of the output being reasoning tokens); gemini-3.5-flash
179k in / 0.5k out (Google tokenises images ~2.3× heavier, but list price
per token is far lower — pennies per run); haiku 78k in (≈ 8p, quality
disqualifying). Opus was not run: sonnet already matches the human ground
truth, so there is no headroom a 4× price buys.

## Decision

- **Default segmentation model: `claude-sonnet-5`** — the property owner
  already has an Anthropic key for the describe step ("configure once");
  ~£0.30 per property is well inside the cost story; and it was the only
  model to match the manual cut outright.
- **`gemini-3.5-flash` is the documented cheap alternative** (needs a
  `GEMINI_API_KEY`): its two merges are exactly the kind of error the
  review app's rename/re-describe affordances repair in seconds.
- Boundary precision at 5 s sampling was within one frame of the eyeballed
  transitions everywhere it was checked; a 1 s refinement pass around
  boundaries stays **parked** until real use shows boundary bleed in built
  schedules (the normaliser's midpoint seams and describe's tolerance make
  ±2 s harmless).

## Open for integration (app shell work)

- `segments → rooms`: feed segment time ranges into keyframe extraction
  (per-segment frame budgets scaled by duration; exact cut points replace
  the `--trim-lead` heuristic — the M2 boundary-bleed fix becomes
  structural).
- Segment corrections in review: rename room, merge segment into
  neighbour, re-describe after correction (existing `--room --from-json`
  machinery preserves hand-edits).
- Multi-visit rooms (sonnet found Bedroom 1 twice, correctly): segments
  grouped by name into one room's photo set.
