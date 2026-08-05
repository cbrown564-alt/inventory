# 35 — Gemini Omni creative exploration

*5 Aug 2026. Working note for product storytelling and social experiments
with Gemini Omni video. Not a product commitment, not an accuracy claim,
not a substitute for docs/34's video probe. Authority: tier 5 (research /
spike). Feeds later marketing/demo work; does not own v1 scope.*

## Why this note exists

The Phase 3.6 video probe (docs/34) asks Omni for photoreal handheld
walkthroughs with stable fixtures so the pipeline can be falsified. Early
creative runs confirmed the limit: **Omni struggles with realistic physics
and object permanence**, so its value for inventory *gold* is real but
narrow.

Separately, a free ~10 clips/day Omni budget was used to try **precision-
optional** ideas — comic beats, motion graphics, claymation, kinetic type —
where fixture drift does not kill the result. Several of those landed.
This document records what worked, which threads to keep, and how to
iterate without rediscovering the prompt rules.

## Wall (unchanged)

- Outputs are **development / demo / internal creative** evidence.
- Never present a synthetic clip as a real landlord walkthrough.
- Never strengthen a property claim beyond real capture evidence.
- Google consumer terms still exclude this arm from publication corpora and
  from training use (docs/31 Amendment B / B9; inherited by docs/34). Treat
  external posting as a separate legal/product decision, not assumed by
  this note.
- Generation stays on the **subscription surface**; no metered video API
  unless an owner explicitly authorises it (`AGENTS.md`).

## What we learned about prompting Omni

| Do | Don't |
|---|---|
| Image-to-video from named stills | Ask for complex edits *on* an existing MP4 |
| Describe layout, timing, and on-screen text verbatim | Use product jargon ("review spine", "compare surface") |
| Prefer stylized / comic / graphic jobs | Demand millimetre-stable cabinetry |
| One clear beat per ~6–8s clip | Pack a full ten-room journey into one generation |
| Attach Pass A–accepted stills when room identity matters | Condition on rejected or mislabelled views |

Machine-readable prompt pack:
[`evals/fixtures/synthetic-room-eval/video/exploratory/EX-R.json`](../evals/fixtures/synthetic-room-eval/video/exploratory/EX-R.json)
(and sibling `EX-1`…`EX-5.json` for earlier precision experiments).

Stills extracted for creative refs live under
`evals/fixtures/synthetic-room-eval/video/exploratory/refs/`.

## Session outcomes (5 Aug 2026)

Operator-generated clips (Downloads, same evening). Ranking after strip
inspection:

| Clip (operator filename stem) | EX-R id | Result |
|---|---|---|
| `Kinetic_type_video_displaying_words_*` | EX-R4 | **Strong** — literal word gags; lands *evidence beats vibes* |
| `Clay_smartphone_inspecting_flat_*` | EX-R3 | **Strong** — playful character + clipboard ticks; approachable |
| `Split_screen_hallway_video_layout_*` | EX-R5 | **Strong** — live walk + *Entrance hall* + ticking thumbnails |
| `Tenant_and_landlord_disputing_chip_*` | EX-R2 | **Good** — chip stays hero; caption scrap reads |
| `Ghost_appearing_in_hallway_*` | EX-R1 | **Amusing** — clerk ghost, £165 tag, *film it once* |
| `Camera_panning_across_kitchen_*` | EX-R6 | **Fine** — careful pan; least distinctive |

Photoreal "inventory gold" attempts earlier the same day were viable as
*source stills / mood*, not as Pass A geometry. That split is the strategic
finding: **use Omni for story and mood; keep evidence claims on real
capture and the still/video probe walls.**

## Threads to explore later

### 1. Product-demo angles (build on EX-R5)

**Job:** show what the app/service does in ~6–10s, without claiming real-
property accuracy.

EX-R5 already proved the shape: a **live phone walk on the left**, a
**simple UI column on the right** (room label, thumbnail strip, soft ticks).
Iterate as a series of angles, each one self-contained prompt + stills:

| Angle | What the viewer should understand | Visual sketch (prompt in picture language) |
|---|---|---|
| A. Orient | "The whole property, room by room" | Gallery of room tiles filling in; one tile expands to a short walk |
| B. Review spine | "You're not lost in item 1 of 289" | EX-R5 pattern: live walk + chapter label + ticking frames |
| C. Evidence moment | "Every claim has a photo/timecode" | Freeze on a defect; a small card shows a clock time and a tick |
| D. Sign / send | "Closure: signed and sendable" | Calm room still → signature line draws → simple "Ready to send" card |
| E. Before / after | "Deep clean or check-in/out comparison" | Split wipe or sparkle wipe between two moods of the same kitchen still |
| F. Capture coach | "Film slowly, say the room name" | Vertical careful pan; one spoken room name; optional silent ffmpeg sibling |

**Iteration rules for this thread**

- Always attach concrete stills (RP Omni accepts, or `refs/`).
- Name UI chrome in the prompt (colours, where text sits, exact strings).
- Never say "like our review UI" — describe the pixels.
- Keep each angle one job (docs/17: one primary action per screen, mirrored
  in the demo).

**Open questions**

- Which three angles are enough for a landing-page loop vs a social series?
- Do we need a fixed fictional flat identity across angles (same stills) for
  recognition, or is variety better?
- How much UI chrome is "demo fantasy" vs confusingly fake product?

### 2. Claymation character (iterate on EX-R3)

**Job:** make a stressful legal-ish exercise feel approachable. A playful
character carries the explanation so the landlord is not the anxious
protagonist.

What already worked: clay smartphone on stubby legs, clay flat, clipboard
ticks, calm British voiceover about schedule of condition.

**Iteration directions**

| Beat | Idea |
|---|---|
| Origin | Character wakes up on a charging cable, "hired" for one inventory |
| Capture | Character teaches slow pan + saying the room name |
| Review | Character walks a clay contact sheet, ticking rooms |
| Dispute defused | Two clay speech bubbles ("was / wasn't") collapse when a dated clay photo appears |
| Payoff | Clipboard closes; text-free sigh of relief |

**Craft notes**

- Lean into wonky clay — it forgives Omni's physics limits.
- Keep voiceover continuous and scripted in the prompt (Omni speech adherence
  is a stated strength).
- Avoid on-screen legalese; one plain sentence per clip.
- Character bible (for later prompts): materials, eye style, colour of
  clipboard ticks, no brand logos on the phone face.

**Open questions**

- Is the protagonist a phone, a clipboard, or a small clay landlord?
- Series of shorts vs one longer edited string of 8s clips?
- Internal onboarding only, or eventual public explainer (terms permitting)?

### 3. Ghost clerk (£165) — creative concept

**Job:** comic personification of the expensive human alternative and the
north-star line *film it once*.

What worked: pale trench-coat clerk with clipboard in a real-ish hall,
yellow **£165** tag, end card **film it once.**

**Play space (not yet generated)**

- Ghost fades as the landlord's phone stays steady.
- Ghost keeps trying to stamp forms; ticks appear on the phone UI instead.
- Ghost and clay character cameo (cross-thread gag).
- Silent vertical loop for start-page atmosphere (no price tag if that feels
  too sales-led for in-product UI).

Treat as **optional spice**, not the core explainer. Tone risk: mockery of
clerks vs empathy for landlords paying £165 for peace of mind — keep the
joke aimed at *the cost of anxiety*, not at professionals.

### 4. Kinetic type — socials

**Job:** short, mute-friendly vertical clips that teach vocabulary and the
product's attitude (*evidence beats vibes*).

EX-R4 pattern: one defect word per second with a literal visual gag
(scuff / chip / watermark / burn / crack / dent), then a closer card.

**Series ideas**

- Defect dictionary (one word per post).
- "Not a claim" cards: *shadow ≠ damp*, *grain ≠ mould* (mirrors scenario
  negative controls, as education not gold).
- CTA variants: *film it once*, *evidence beats vibes*, *pause on the damage*.

**Craft notes**

- No real rooms required — abstract backgrounds avoid physics failure.
- Exact strings in the prompt; ask for marker-on-scrap-paper look.
- Export 9:16; assume sound optional (type should read silent).

## Relationship to docs/34 and the product

| Concern | Owner |
|---|---|
| Falsify video pipeline on known-content clips | docs/34 + `video/clips/VU-*.json` |
| Creative / social / demo storytelling | **this note** + `video/exploratory/EX-R.json` |
| Capture strategy on real property | docs/26 |
| In-product filming guide UX | docs/17, `start.html.j2` |

Do not mix walls: a charming clay clip does not move Phase 4; a failed
VU-5 hold still matters for hallucination discipline.

## Suggested next experiments (when quota allows)

Priority order if continuing the *liked* threads only:

1. **EX-R5-B / C** — two more product-demo angles (evidence moment; sign/send),
   same fictional hall/kitchen stills as EX-R5/EX-R6 for continuity.
2. **Clay v2** — same character bible; one new beat (capture coach *or*
   dispute defused); keep voiceover to one sentence.
3. **Kinetic mini-series** — three single-word posts (`chip`, `scuff`,
   `watermark`) plus shared end card, for a social test cut.
4. **Ghost v2** (optional) — softer gag; price tag optional; test without
   end-card sales line for in-app use.

After each batch: strip at 1 fps, keep a one-line verdict in this doc's
session log (append-only), archive keepers under
`evals/fixtures/synthetic-room-eval/video/exploratory/keepers/` if you want
them in-repo (optional; Downloads is fine until something is chosen for
product).

## Session log

| Date | Batch | Keepers / notes |
|---|---|---|
| 2026-08-05 | EX-R creative pack (image-to-video) | Keep: kinetic type, clay phone, split-screen hall, chip dispute. Spice: £165 ghost. Baseline: kitchen pan. Prompt lesson: self-contained, image-conditioned, no product jargon. |
| 2026-08-05 | Earlier photoreal / EX-1…5 style | Limited for gold; viable as still sources. Physics / permanence weak. |

## Non-goals

- Replacing docs/34 regeneration of cleared VU clips.
- Training or fine-tuning on Omni output.
- Shipping any clip into the signed PDF or tenant evidence trail.
- Claiming Omni demos prove capture-strategy or describe accuracy.
