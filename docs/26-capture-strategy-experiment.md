# 26 — Capture-strategy experiment: photo vs video vs hybrid

*8 Jul 2026. The load-bearing open question for v1. The entire product is
built on "one continuous walkthrough video," and that assumption has never
been tested against the alternative (staged photos) on the axes that decide
the product's shape: accuracy, image quality, capture time, and user effort.
This doc designs the experiment that resolves it. Authority: tier 5 (research
/ spike). Feeds docs/00 Pillar 2 and the pipeline work in docs/22, docs/18.*

## Why this is the most important open question

The current pipeline's hardest failures trace back to a single untested
decision — **video is the capture format.** Consider what each pipeline
problem looks like under a different capture strategy:

| Pipeline problem (video today) | Does it survive if capture = staged photos? |
|---|---|
| Room segmentation boundaries bleed (Kitchen shows a staircase) | **Dissolves.** The user *names* each capture set. No VLM boundary guess. |
| Hero frame is a close-up of a hand on a curtain | **Dissolves.** The user frames every photo deliberately. |
| Choose smallest high-quality frame set for coverage | **Dissolves.** The set *is* the photos; curation is dedup + ordering, not extraction. |
| Motion-blurred frames from a moving camera | **Dissolves.** No motion. |
| Hallucinated room items from low-res extracted frames | **Softens.** Photos are full-resolution, well-lit, static. |

This is not an argument *for* photos. It's an argument that **we don't
know**, and the answer restructures everything downstream — segmentation,
frame selection, curation, even the review UX. Building v1 on an untested
capture assumption is the highest-leverage risk in the project. We resolve
it before investing further in video-specific pipeline work.

### Market evidence for the photo arms (Jul 2026)

Two findings from [`market-research-2026-07.md`](market-research-2026-07.md)
raise the prior on P1/P2 — they are not strawmen for video to beat:

- **RentCheck**, the only consumer-validated product in the category
  (4.8★ from ~18k App Store ratings), is a guided room-by-room **photo**
  checklist. No video, no AI. The most successful consumer capture UX in
  this space is essentially P1/P2's protocol, resident-led.
- **The deposit-scheme evidential spec privileges photos.** The core
  adjudication artefact is a written report with embedded dated
  photographs; raw video is supplementary and must be time-referenced to
  be usable at all. Native photos carry capture timestamps in file
  metadata (which DPS checks); frames extracted from video do not unless
  we write them in.

M5b (phone guided capture) was killed as a capture-*UX* failure on a real
device — that verdict does not transfer to the photo *format* itself.
Sunk cost already doesn't count here; neither does the M5b scar tissue.

## The more precise video question

"One continuous video" is too vague to test. A casual, portrait, silent
walkthrough is a different product input from a deliberate inspection video.
The phone-first rebuild treats this as a concrete hypothesis:

> If the landlord films landscape, says each room name at its doorway, takes
> a stable establishing hold, and pauses on material defects, can one
> continuous video produce the right room boundaries and heroes **without**
> creating enough report errors and review repairs to erase its capture-time
> advantage?

Video is viable only if all four parts are true:

1. **Room identity:** the system assigns the right name to the right run of
   footage; boundary bleed is low enough that it does not contaminate the
   room schedule.
2. **Establishing evidence:** each room has an on-room, usable wide image
   without a manual hunt through frames.
3. **Report quality:** item, condition, cleanliness and defect scores remain
   at the same signed-report standard as the photo alternatives.
4. **Whole-journey effort:** lower capture effort is not simply repaid as
   more reviewer edits, rejects, missing-item additions, recaptures and time
   to issue.

The experiment therefore measures *review burden* as an outcome, not merely
model accuracy. A video arm that is pleasant to film but leaves a landlord
with 40 repairs is not the low-friction product it appears to be.

## The decision this experiment must make

One product question, with a clear answer shape:

> **What capture instruction do we give a landlord on the start page?**

Candidate answers (the experiment's arms):

1. **V0 — Ordinary continuous walkthrough**: the current baseline, with no
   required narration or establishing hold.
2. **V1 — Narrated continuous walkthrough**: landscape; room name spoken at
   every doorway; a three-second establishing hold; deliberate defect pauses.
3. **V2 — One video per room** (segmentation becomes trivial; effort rises).
4. **P1 — Staged photos, light volume** (~3–4 per room, ~30 property-wide).
5. **P2 — Staged photos, heavy volume** (~8–10 per room, ~80 property-wide).
6. **H1 — Hybrid**: one walkthrough video for coverage/comprehensiveness +
   optional staged photos for detail rooms. (Exploratory — only if V/P
   arms show a clear split in what each is good at.)

V0 establishes whether deliberate filming instruction actually earns its
place; V1 is the product hypothesis. P1/P2 prevent us from assuming that
video wins merely because it is easier to explain. V2 and H1 are diagnostic
arms, used if their additional effort is needed to explain a split.

## Axes of evaluation

Every arm is measured on the same five axes. **No arm wins on a single
axis** — the decision is a trade-off, and we report it as one.

| Axis | Definition | How measured |
|---|---|---|
| **Accuracy** | Correctness of the final report (items present, grades right, defects caught) | Held-out gold report per fixture room; recall / precision / hallucination per docs/10 |
| **Image quality** | Are the representative images (heroes, evidence) clear, well-framed, usable in a PDF? | Human rating 1–5 per image; hero-gold methodology from docs/18 |
| **Capture time** | Wall-clock minutes the landlord spends *capturing* (not reviewing) | Timed capture sessions |
| **Effort / friction** | Cognitive + physical load: decisions, retakes, navigation, holding steady | Observer notes + NASA-TLX-style self-report (low/med/high) |
| **Cost** | Build token/spend per property | Build confirms (token usage + $) |
| **Review burden** | Work needed to turn the draft into a defensible issued record | Minutes to issue; items accepted unchanged; material edits; rejected claims/defects; missing-item additions; `not visible`; re-captures |
| **Room/hero correctness** | Whether the capture strategy gives the pipeline usable room structure and a representative cover | Room-name accuracy; boundary-bleed audit; human pass/fail for each rank-1 hero: recognisable, establishing and in the named room |

**The critical trade-off we are explicitly looking for:** does staged
photography buy enough accuracy + image-quality improvement to justify the
extra capture time/effort? Or does video's low effort win despite lower
per-frame quality, because the review step can repair the rest?

## Fixture matrix

One property is not enough — capture difficulty varies with property type.
Minimum: **two properties** of different character. Ideal: three.

| Property | Why | Rooms |
|---|---|---|
| **A — Own property** (`IMG_5512.MOV` flat) | Existing gold segments, frame pool, manual reference (docs/18). Cheapest to start. | 10 |
| **B — Contrasting property** | Different layout/size than A (e.g. a house with stairs, or a studio). Surfaces capture-difficulty variance. | 8–12 |
| **C — Third property** (stretch) | Confirms A/B findings generalise; prevents a one-property artefact. | any |

**Per property, per arm:** capture the property using that arm's protocol,
build, review to a gold report, score all five axes. The gold report is
**property-level** (the canonical item/grade/defect list for that property)
and shared across arms — so arms are compared against the same truth.

### Capture protocols (so arms are comparable)

| Arm | Protocol |
|---|---|
| **V0** | One continuous video, phone held steadily, pause at each doorway (existing runbook, docs/24). No required narration, orientation or establishing hold. |
| **V1** | One continuous **landscape** video. At each doorway: say the room name, hold a wide establishing view for three seconds, then sweep the room; hold again on defects, meters and safety items. |
| **V2** | One video per room, ~30–60 s each, named at capture (e.g. file or prompt per room). |
| **P1** | 3–4 photos per room: one doorway establishing, two detail angles. ~30 total. |
| **P2** | 8–10 photos per room: establishing + corners + key fittings + defects. ~80 total. |
| **H1** *(conditional)* | V1 walkthrough + P1 photos added only for rooms V1 scored poorly on. |

The protocols are fixed before capture so effort/time comparisons are honest.

## What we need to build first

The pipeline currently assumes video. Two gaps block the photo arms:

1. **Photo-mode ingest** — `ingest.py` must accept a folder/drop of photos
   grouped by room (room from prompt, folder name, or a lightweight
   "which room is this?" step), skip segmentation + keyframe extraction,
   and hand the photos directly to describe + curate. This is the only
   new code the experiment requires; describe/curate/report are
   capture-agnostic already.
2. **Capture-time room naming for V2/P1/P2** — minimal UX: at upload, the
   user tags each photo-group or per-room video with a room name. No model
   inference. (This *is* one of the things we're measuring the effort cost
   of — so it must exist to measure it.)

Both are scoped as experiment scaffolding, not product features. They live
behind a flag until the decision is made.

## Metrics & decision rules

### Per-arm scorecard (filled per property, then averaged)

For each arm × property, record:

```
accuracy:    recall / precision / hallucination (vs property gold)
image_qual:  mean hero rating (1–5), % heroes "establishing & on-room"
capture_min: minutes from "start filming" to "done capturing"
effort:      TLX band (low/med/high) + observer friction notes
cost:        tokens + $ for the build
review:      minutes to issue; accepts unchanged / edits / rejects / additions /
             not-visible marks / re-captures
structure:   room-name correctness, boundary-bleed count, hero pass rate
```

### Decision criteria

We are **not** looking for a single winner on accuracy. The decision rule:

- **If a photo arm matches video accuracy AND clearly wins image quality
  at acceptable effort** → photos become the default capture; video
  becomes secondary. Pipeline simplifies dramatically (segmentation
  problem dissolves).
- **If V1 matches the photo arms on signed-report quality, room/hero
  correctness, and *total* capture-plus-review time** → the narrated
  continuous walkthrough stays the default; photo-mode is a first-class
  alternative, not a buried power-user option.
- **If V1 is materially better than V0 but still loses the review-burden
  comparison** → the filming protocol is useful evidence, but not enough to
  justify video as the default. Test V2/H1 to locate the break-even point.
- **If the split is conditional** (e.g. photos better for detail/defects,
  video better for coverage) → H1 hybrid becomes the product; design the
  start page around it.
- **If no arm meets the accuracy bar on any property** → the capture
  strategy is not the bottleneck; refocus on describe/detect quality.

**Explicitly not a decision rule:** "video is what we already built."
Sunk cost does not count. The whole point is to test whether the thing we
built is built on the right assumption.

## Sequencing

```text
Step 0 — Build photo-mode ingest + capture-time room naming (scaffolding)
Step 1 — Capture Property A under V0, V1, P1 and P2 (reuse the existing
         footage only for V0 when it truly matches the baseline protocol)
Step 2 — Build + review each to A's gold; score the scorecard
Step 3 — Decision checkpoint on A alone: is the signal strong enough to
         call it, or do we need B?
Step 4 — If needed: capture Property B under the leading 2–3 arms only
Step 5 — Decision recorded in docs/00 Pillar 2 + this doc's outcome section
```

Property A first because the gold work is partly done (docs/18 fixture).
A *may* be enough if the signal is decisive — e.g. if photos are dramatically
better on image quality at low effort on A, we don't need B to confirm the
direction, only to stress-test it.

## What this experiment is NOT

- **Not a segmentation-model bake-off.** That's docs/11. Here segmentation
  is only measured insofar as V-arms need it and P-arms bypass it.
- **Not a hero-scorer bake-off.** That's docs/18. Here image quality is
  measured at the *outcome* level (is the hero good?) regardless of which
  scorer produced it.
- **Not a describe-backend comparison.** That's docs/04. All arms use the
  same describe backend (gemini default) so the capture variable is isolated.

## Risks to validity

| Risk | Mitigation |
|---|---|
| One property is a fluke | Minimum two properties; A+B before shipping a decision |
| Capture effort rated by the builder, not a real landlord | Acknowledged limitation; record observer notes honestly, flag for a real-tester run post-decision |
| Photo-mode ingest is throwaway if video wins | Scoped as minimal scaffolding; the room-grouping concept is reusable regardless |
| Gold report is subjective | One curator builds gold; a second spot-checks a sample; disagreements logged |
| "Cost" favours whichever uses fewer frames, biasing toward low coverage | Cost is reported alongside accuracy — a cheap-but-inaccurate arm is not a winner |

## Outcome *(filled when the experiment runs)*

| Arm | Property A | Property B | Decision |
|---|---|---|---|
| V0 (ordinary continuous video) | | | |
| V1 (narrated continuous video) | | | |
| V2 (video per room) | | | |
| P1 (light photos) | | | |
| P2 (heavy photos) | | | |
| H1 (hybrid) | | | |

**Decision recorded:** *(pending)*
**Implication for pipeline:** *(pending)*
**Implication for start page UX:** *(pending)*

## Related

- North star: [`00-north-star.md`](00-north-star.md) Pillar 2
- Market research (RentCheck precedent, evidential spec): [`market-research-2026-07.md`](market-research-2026-07.md)
- Hero selection (image-quality methodology): [`18-hero-image-selection.md`](18-hero-image-selection.md)
- Segmentation (the problem photos bypass): [`11-video-segmentation.md`](11-video-segmentation.md)
- Product plan of record: [`12-video-first-journey.md`](12-video-first-journey.md)
- ML programme / pipeline roadmap: [`22-ml-programme-review-and-roadmap.md`](22-ml-programme-review-and-roadmap.md)
