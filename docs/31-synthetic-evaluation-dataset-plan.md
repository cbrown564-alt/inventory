# 31 — Synthetic room evaluation dataset

*Updated 3 Aug 2026. Implementation plan for a public, independently
AI-reviewed synthetic room dataset with human escalation, used to develop
prompts and compare off-the-shelf VLM pipelines. This document owns the
synthetic evaluation dataset. It does not change the real-property v1 quality
gate in docs/00 or the ML training programme in docs/19.*

## Decision

Build a **200-image pilot** as 25 four-view room specifications rendered
through a Google generation arm and Codex's GPT Image 2 generator. The Google
arm may contain images from Antigravity and Gemini Omni, which are separate
Google services and must be reported separately. Use it to find prompt and
pipeline failures quickly. Do not train or fine-tune model weights on the
images.

Vision-description *evaluation* is unchanged and still includes the Google
path through subscription-backed Antigravity CLI, because `gemini-3.5-flash`
is the production describe default in docs/00 and cannot be evaluated by
proxy. Never use Gemini API credentials or a metered Gemini endpoint. This is
narrower than the production backend policy in docs/00.

Completing and using the 200-image pilot is next-phase v1 evidence work.
Publishing the dataset is post-v1 and requires a separate review of provider
terms, provenance, metadata removal and dataset licensing.

Synthetic results are development evidence, not product accuracy evidence.
All product claims and promotion decisions remain gated on held-out,
native-resolution photographs from real properties.

The generation prompt states what an image is intended to contain. It becomes
gold only after an independent AI review checks what is actually visible and
records observed labels. Clear cases do not require routine human review.
Ambiguity, disagreement and material evidential risk are escalated to the
project owner. Rejected generations remain in the audit log but never enter
the scored set.

The project owner reviewed the first generated batches and reported that they
were correct. On 29 Jul 2026 the owner therefore replaced blanket human review
with the AI-first, exception-based review policy below. Those reviewed batches
are calibration evidence for the policy, not automatic acceptance of later
images.

### Amendment, 3 Aug 2026 — restore the 200-image arm, delta pairs, prompt routing

Three changes follow from what Phases 1–3 actually produced.

**0. Restore the 200-image generation arm.** The 100-image reduction was a
quota response to the Antigravity service, not a decision that the Google arm
was unnecessary. Gemini Omni is now the Google service for the previously
missing Google images, and the project owner reports that the complete Gemini
Omni batch has been reviewed and passes. The pilot therefore returns to
**25 specifications × 4 views × 2 arms = 200 images**: 100 Google-arm images
(Antigravity and Gemini Omni, reported by service) and 100 GPT Image 2 images.

- The 200-task queue and pair-balance gate are restored.
- Gemini Omni candidates must be imported into the task ledger with hashes and
  service provenance; owner review is recorded separately from independent AI
  Pass A/B review.
- The 20 previously untouched GPT Image 2 rows have now been generated and
  are `review_pending`; they still require the normal independent review path.
- Google and Gemini Omni are the same image provider, so this is a service
  comparison, not an independent-provider comparison. Report that limitation
  explicitly and retain the real-transfer gate.

The dated Phase 3 execution record below is history and is left unedited.

### Amendment B, 3 Aug 2026 — delta pairs become the ambition; Google demoted

*Supersedes parts of Amendment A above, which was written the same day before
the ledger was read against the plan. Where the two conflict, B governs.*

Amendment A restored a 200-image target that the ledger cannot reach: 39 tasks
are terminally `generator_failed` under a two-attempt cap, and Google
generation is retired. It also left the programme's ambition at "pick a
prompt", which is below what the apparatus can produce. Eight decisions
follow.

**B1. The dataset is an evaluation instrument, not a training corpus.** The
Out-of-scope ban on weight training stands. A permissive-licence GPT-only
slice makes tuning *legal*, not *useful*, at n=100 images — two orders of
magnitude short. If a training corpus is wanted later it is a separate,
high-volume, low-rigour GPT-only generation arm, sourced and reported
independently of this dataset, and it belongs to docs/19. The unique
contribution here is enumerated ground truth — negatives and delta pairs —
which is what you need to *measure* whether a tuned model helped.

**B2. Splits stay frozen; the attempt cap is amended once.** Re-splitting
around whichever packets happen to be complete would select on generation
success, which correlates with scene difficulty, and would quietly load the
sealed split with easy rooms. That is irreversible and is permanently off the
table. Instead the attempt cap moves 2 → 3 for a **single recorded GPT-only
repair pass** over every incomplete packet, at the same Pass A bar with no
scene-specification weakening. The cap exists to stop a spec being softened
until the generator complies; a third attempt against the unchanged frozen
prompt does not do that. Record generation yield before and after, and state
the amended cap in every report.

**B3. Partial packets are first-class.** Frame-level metrics are computed on
all accepted views; room-level metrics only on complete four-view packets. The
two are reported as separate tables with `n` stated. Packet completeness stops
being a single point of failure for the whole programme.

**B4. Validation grows the only legitimate way.** Validation currently holds
two complete GPT packets, which cannot freeze a prompt. Author approximately
five **new** specifications and assign them to the validation split *before*
generating them. Existing split membership does not move.

**B5. Pass B is tiered by split.** Development labels steer iteration;
validation and sealed labels make decisions.

- *Validation + sealed* (10 existing specs plus the new ones from B4): the
  full protocol, no shortcuts. These records carry every Phase 4–5 decision.
- *Development* (15 specs): primary Pass B only, with the blind second check
  retained on 100% of defects and negatives — the metrics where a single label
  error is most visible and counts are smallest. Ordinary item labels run
  single-pass. These records are marked `provisional_development` and are
  never gold.
- The Pass B promotion guard must **refuse** to mark a validation or sealed
  record gold without the full protocol present. This is enforced in tooling,
  not by discipline.

**B6. Reviewer identity is pinned, and independence is by model family.**
Existing records name the reviewer as "Cursor visual review" with no model id
or version, which does not meet this document's own requirement.

- The Pass B primary reviewer must be **non-OpenAI-family**, because all
  imagery is now GPT Image 2 and a same-family reviewer judges what is visible
  in its own family's output. A biased backend shows up as a score; a biased
  label silently corrupts every score.
- The blind second check must be a **different family again** from the
  primary, so the two cannot share a blind spot.
- `validate_dataset.py` rejects any review record missing reviewer model id
  and version.
- Validation and sealed Pass B runs through a **pinned, scriptable path** with
  a hashed review prompt and cached raw output, so those 15-odd records are
  re-runnable. Development Pass B may remain in-session and is recorded as
  **attested**, never described as reproducible.

**B7. Delta pairs are the ambition; the prompt winner is a by-product.**
Phase 3.5 is promoted from optional extension to the programme's centre.
Comparison is the decisive artefact in docs/00; that surface has no ground
truth in these fixtures or in any public dataset; it cannot be obtained from a
real property without waiting out a 12-month tenancy; and docs/22 records
ML-E14 as blocked precisely because "no paired check-in/out fixture exists".
The headline metric — **false-change rate** — decides whether compare can ship
at all, and is currently unmeasured. The probe runs first (see B8). The
docs/00 wall is unchanged: delta pairs remain development evidence and promote
nothing.

**B8. Two additional avenues adopted; sequencing and a WIP limit.**

Adopted now:

- **Degradation ladder.** The production journey is video-first, but this set
  is clean, well-framed stills, so every synthetic number likely overstates
  real performance by an unmeasured margin. Apply a deterministic ladder to
  already-accepted images — motion blur, downscale-and-reupscale, JPEG
  compression, off-axis crop — and re-run the same pipeline. Labels are
  inherited unchanged: no new generation, no quota, no Pass B, no provider
  terms question. This converts the static set into a sensitivity instrument.
- **CI regression suite.** `gemini-3.5-flash` will change without notice. A
  scheduled sealed-slice run makes the dataset a permanent tripwire rather
  than a one-shot comparison. Added once a sealed run exists to regress
  against.

Queued behind the delta probe: a **defect-visibility threshold curve** —
render the same defect at controlled apparent sizes to find where recall
collapses, characterising the resolution-bound 64–71% defect-recall ceiling in
docs/04. Its output is a capture instruction feeding docs/26 and docs/33, not
a score. Parked: the docs/22 §1 distillation flywheel, per B1.

Order of work, with a **WIP limit of two active lanes** — one generation, one
review:

1. Delta-pair feasibility probe (6 generations). *Stop rule: fails the
   ≥2-of-3 bar → record the negative result, abandon the extension, ambition
   reverts to the prompt winner.*
2. Repair generation at cap 3 — validation and sealed holes first, development
   second; author and generate the B4 validation specs in the same pass.
3. Full-protocol Pass B on validation + sealed (review lane, concurrent
   with 2).
4. Degradation ladder (no quota; slots in whenever compute is free).
5. Development Pass B, primary-only.
6. Gemini Omni Pass A import — **last, and named in advance as the droppable
   item** if the schedule slips.
7. CI regression harness.

> **Correction, 4 Aug 2026 — item 6 was not droppable.** Phase 3.6 conditioned
> its clips on these stills and found that within every prior-batch packet the
> four view ids were exactly inverted: the file named `A-wide` was the packet's
> condition detail. Nine packets, 36 stills. Nothing caught it because the
> images had **zero rows in `tasks.csv`**, and Pass A is where "is this the view
> it claims to be" is caught. The item that was named in advance as expendable
> was the only control that would have found the defect, and skipping it cost a
> nine-clip video batch. Both are now done: `repair_gemini_omni_views.py`
> re-filed the stills and `import_gemini_omni_pass_a.py` gave all 57 ledger
> rows. Ordering rule to carry forward: **an arm with no ledger rows has no
> provenance, whatever else has been done to it** — so importing it is not the
> last step of the work, it is the first.

**B9. The Google arm is demoted, not deleted.** It has 27 terminal failures,
5 complete packets, `backend_model: unknown` throughout, three packets with no
proved generation origin, and UK terms that prohibit using output to develop
"machine-learning models or related AI technology" — so it is unpublishable
and unusable for any future training corpus. Its one remaining value is as the
only cross-generator control against the GPT Image 2 house-style confound,
which the degradation ladder does not address.

- "Exactly 200 accepted images" is **removed** from the definition of done. A
  gate that cannot be passed is not a gate.
- The 57 Gemini Omni candidates are imported through the **normal Pass A
  path** — owner review alone is not the recorded protocol — but as a
  bias-check slice with **no completeness obligation**. *Done 4 Aug 2026. The
  slice is declared in `dataset.json` with `role: bias_check_slice`, which
  `validate_dataset` excludes from the matched-design counts; the matched
  design is still 200 tasks. Its 100 rows carry
  `provenance: candidate_only_prompt_not_recorded`, because these images came
  off the owner's subscription surface and the prompt actually used was never
  recorded — so `exact_prompt` is the specification a row is judged against,
  not a transcript of what made the image. 57 rows are `review_pending`; the
  43 views with no candidate are `not_generated`, terminal rather than queued,
  since generation is retired and this arm owes no completeness.*
- The entire Google arm is **excluded from publication and from any future
  training corpus**, on terms grounds.
- The **real-transfer gate remains the primary house-style control**. The
  cross-generator slice is opportunistic and unbalanced and cannot carry a
  conclusion alone; that is the only claim to be made for it.

**1. Stop searching for a single prompt winner.** Phase 1's frozen four-run
comparison did not stall by accident. The evidence-bounded prompt took defect
recall from 50% to 100% and removed an unsupported defect while item recall
fell 6.2 percentage points. The pass bar requires one metric to improve while
"the other metric non-regress[es]", so a genuine trade-off can never clear it,
and Phase 4 stays dependency-blocked indefinitely. The product already routes
work by task through `TieredBackend`. The comparison order below is amended so
a per-task assignment — coverage prompt on the defect pass, production prompt
on the inventory pass — is an admissible outcome alongside a single winner.

**2. Extend the generator to delta pairs.** The scene specifications already
carry `continuity_requirements` that hold one room identity across four
viewpoints. That capability is currently spent on four views of a *static*
room. The same mechanism can render a room twice with an enumerated change
between renders, which produces the one class of evidence no real fixture can
supply on any useful timescale:

- **Temporal deltas** — the same room at check-in and at check-out. docs/00
  records that comparison is "the decisive artefact", because adjudicators
  decide by comparing the two. There is no ground-truthed check-out set today
  (`evals/fixtures/own-property/siamese-compare-demo.json` is a demo), and
  obtaining one from a real property means waiting out a 12-month tenancy.
- **Counterfactual deltas** — the same room with a defect present and absent.
  Real fixtures can only be annotated for what happens to be in them; a
  matched pair isolates whether the pipeline sees the defect that exists and
  stays silent about the one that does not.

This is a bounded extension, not a virtual home: continuity is required within
a room packet and within one matched pair, never across the dataset. It is
gated behind a three-scenario feasibility probe (Phase 3.5) because unenumerated
drift between renders would silently poison the gold, and the 36% first-attempt
rejection rate in Phase 3 shows continuity is already the hard part. If the
probe fails, the extension is abandoned and recorded as a negative result.

The docs/00 wall stands unchanged. Delta pairs are development evidence. No
synthetic result promotes a compare claim; that remains gated on real
check-in/check-out evidence.

## Current execution status — 3 Aug 2026 (Amendment B)

Read against the ledger, not against the narrative. `tasks.csv` currently
holds **126 `pass_a_accepted`** (85 OpenAI, 41 Google), **39
`generator_failed`** (12 OpenAI, 27 Google), **13 `retry_pending`** and
**22 `pending`**. No rows remain `review_pending`.

Complete four-view packets, which is the number room-level scoring depends on:

| Split | Specs | GPT Image 2 complete | Google complete |
|---|---:|---:|---:|
| Development | 15 | 8 | 4 |
| Validation | 5 | **2** | 1 |
| Sealed | 5 | 3 | 0 |

| Phase | Status | Evidence |
|---|---|---|
| 1 — representative slice | **Complete** | Four immutable Antigravity CLI vision runs compared the two frozen prompts. The candidate improved defect recall from 50% to 100% and removed one unsupported defect, but item recall fell 6.2 percentage points, so no prompt winner was frozen. |
| 2 — extract the pattern | **Complete** | 25 scenarios, the 200-task queue, review templates, static review page, generator slices and hashed development/validation/sealed splits are implemented. |
| 3 — development and validation | **In progress; blocked on Pass B, not on generation** | 46 of 50 packet review records are `provisional`. Only the four Phase-1 records are `verified_synthetic_gold`. Every remaining generation task could complete tomorrow and Phase 4 would still be blocked. Amendment B repairs generation (B2–B4) and tiers Pass B (B5–B6). |
| 3.5 — delta pairs | **Next; runs first** | Promoted to the programme's centre by B7. Three-scenario feasibility probe gates an 8-pair temporal and 4-pair counterfactual set. |
| 4 — sealed comparison | **Not started** | Downstream of a validation prompt decision that has not been made. Validation holds two complete GPT packets, so no decision is currently possible on it; B4 addresses that. The amended order admits a per-task prompt assignment as a winner. |
| 5 — real transfer | **Not started** | Downstream of Phase 4. The separate native-resolution evidence gate also remains open. |

Phases 4 and 5 are recorded as *not started* rather than *dependency-blocked*.
They are downstream of work that has not been done, which is a schedule fact
rather than an external obstruction.

**Status after the 3 Aug 200-image amendment:** Phase 3 is review-blocked.
The 57 Gemini Omni candidates have an owner-reported passing review but are
not yet promoted into the task ledger. The 20 newly generated GPT Image 2
rows and the two earlier `RP-019` replacements remain `review_pending`. The
historical retry decisions and their atomic application remain part of the
review record.

The quota responses are provider-internal limits reached through Antigravity
CLI; they are not metered image API calls made by this project. Resume Phase 3
from `generation_runs/antigravity/pause-2026-07-30-0156.json`. The review
tooling now pins reviewer model mode, CLI version, prompt and image hashes,
sanitised raw wrappers, blind second checks and owner resolutions. Do not mark
retry outputs accepted or any packet gold without that recorded path.

The special Google provenance audit separates intact files from proved
generation origin. `RP-009` and `RP-012` have no successful raw generation
record, while `RP-018` has only an integrity recovery ledger. All three remain
provisional and are automatically excluded from Pass B.

## The question this dataset answers

> Given controlled room evidence with known visible items, conditions and
> defects, which prompt and VLM pipeline most reliably produces a
> review-ready inventory without omissions or invented claims?

From Phase 3.5 the dataset answers a second question, on the artefact
adjudicators actually decide on:

> Given two controlled renders of one room separated by an enumerated set of
> changes, does the pipeline report every real change, and does it stay silent
> about everything that did not change?

The pilot should distinguish four failure sources:

1. image evidence is insufficient or ambiguous;
2. the VLM misses or invents visible facts;
3. the prompt asks for the wrong output or encourages overclaiming;
4. the multi-image merge loses, duplicates or strengthens claims.

## Scope and boundaries

### In scope

- still-image description using the approved evaluation model paths;
- single-image and room-level multi-image pipelines;
- prompt, schema, frame-selection, merge, verification and retry changes;
- items, condition, cleanliness and visible defects;
- exact negatives and near-negatives that test hallucination;
- paired comparison across image generators;
- matched delta pairs of one room — temporal (check-in/check-out) and
  counterfactual (defect present/absent) — with an enumerated change list,
  subject to the Phase 3.5 feasibility gate;
- a deterministic degradation ladder applied to accepted images — motion blur,
  downscale-and-reupscale, JPEG compression, off-axis crop — with labels
  inherited unchanged, measuring sensitivity toward video-frame conditions;
- a scheduled CI regression run of a sealed slice, to detect backend drift;
- an internal dataset with prompts, provenance, independent AI-reviewed labels
  and human adjudication records where required;
- a later public release only after the separate terms, provenance, metadata
  and licensing review.

### Out of scope

- weight training, fine-tuning or distillation;
- using synthetic scores as the v1 accuracy benchmark;
- room-boundary or camera-motion evaluation;
- proving real-world defect recall;
- generating evidence for an actual tenancy report;
- claiming that a generated image depicts a real property;
- a 200-image continuous virtual home with perfect object permanence — the
  Phase 3.5 delta pairs require continuity only within one room packet and
  within one matched pair, never across the dataset;
- proving real-world change detection, or promoting any compare behaviour on
  synthetic deltas alone.

## Terms gate

Generation must pause for a provider if its applicable terms do not clearly
permit this use.

- **OpenAI:** [current UK consumer terms](https://openai.com/policies/eu-terms-of-use/)
  assign output rights to the user and
  prohibit developing models that compete with OpenAI. This project does not
  change model weights, but the planned public/commercial dataset use should
  still be recorded with the terms version and, before scaling, confirmed in
  writing if there is doubt.
- **Google consumer services:** moot for new generation from 3 Aug 2026 —
  Google/Antigravity generation is retired, so no further Google images are
  accepted. The open question is recorded because it applies to the retained
  slice: [current UK terms](https://policies.google.com/terms?gl=GB&hl=en)
  prohibit using generated content to develop machine-learning models or
  related AI technology, and merely avoiding weight tuning may not resolve the
  broader "related AI technology" wording. Resolve it before the retained
  Google images appear in any published dataset; until then they stay internal
  and are excluded from publication.
- Subscription interfaces must be used interactively. Do not automate
  extraction, bypass limits, rotate accounts or use API credentials for image
  generation.

Record `provider`, `product`, `model_display_name`, `terms_url`,
`terms_checked_at`, generation timestamp and the human operator for every
accepted image.

## Pilot design

### Single-provider structure

*Superseded the two-provider matched-pair design on 3 Aug 2026.*

Create 25 room specifications. Each becomes one four-view GPT Image 2 packet.
This yields 25 generated rooms and 100 images:

| Provider | Model assignment | Images |
|---|---|---:|
| OpenAI | GPT Image 2 through Codex `imagegen` | 100 |
| **Total** |  | **100** |

Google/Antigravity images already accepted are retained as a secondary
cross-generator slice and reported separately wherever a complete four-view
packet exists. They are not completed, not regenerated, and not required by
any gate. Antigravity did not expose a selectable image backend in successful
run records, so those retained records keep `backend_model: unknown`; a
provider failure message named `gemini-3.1-flash-image`, but that diagnostic
does not pin the cohort. Do not relabel them as one of the older Nano Banana
assignments.

### Generation assignments

| Room type | GPT Image 2 packets |
|---|---:|
| Kitchen | 4 |
| Bathroom / shower room | 3 |
| Bedroom | 3 |
| Living room | 3 |
| Entrance hall | 2 |
| Dining room | 2 |
| Utility room / cupboard | 2 |
| Stairs / landing | 2 |
| WC / cloakroom | 1 |
| Storage / wardrobe | 1 |
| Home office | 1 |
| Balcony / patio | 1 |
| **Total packets** | **25** |
| **Total images** | **100** |

This design supports:

- aggregate VLM accuracy on a consistent generator;
- failure analysis on a known intended scene;
- architecture comparison without changing the content mix;
- an opportunistic cross-generator check against the retained Google slice.

### Room packets

| Room type | Specifications | Frames per packet | Images |
|---|---:|---:|---:|
| Kitchen | 4 | 4 | 16 |
| Bathroom / shower room | 3 | 4 | 12 |
| Bedroom | 3 | 4 | 12 |
| Living room | 3 | 4 | 12 |
| Entrance hall | 2 | 4 | 8 |
| Dining room | 2 | 4 | 8 |
| Utility room / cupboard | 2 | 4 | 8 |
| Stairs / landing | 2 | 4 | 8 |
| WC / cloakroom | 1 | 4 | 4 |
| Storage / wardrobe | 1 | 4 | 4 |
| Home office | 1 | 4 | 4 |
| Balcony / patio | 1 | 4 | 4 |
| **Total** | **25** |  | **100** |

### Four-view pattern

Each packet requests:

1. doorway establishing view;
2. opposite-corner establishing view;
3. fixtures and safety-item view;
4. controlled condition/defect detail or deliberate clean near-negative.

Use the first accepted frame as a reference for later angles when the product
supports image editing or conversational continuity. Consistency is a scored
property, not an assumption. If an item changes between angles, label the
visible result and record the continuity failure.

### Content balance

Across the 25 room specifications:

- 6 clean and tidy;
- 9 ordinarily occupied or mildly cluttered;
- 7 noticeably cluttered but inspectable;
- 3 partially obscured, deliberately difficult rooms;
- 10 with one material defect;
- 5 with ambiguous wear or a benign texture that resembles damage;
- 10 with no material defect in any view.

Lighting must cover daylight, warm artificial light, mixed colour temperature,
underexposure, window backlight and flash-like phone illumination. Include
modern, dated, inexpensive and recently refurbished UK interiors.

The target object list prioritises inventory-specific and historically missed
items: smoke and heat alarms, extractor hoods, induction hobs, fuse boxes,
entryphones, heated towel rails, shower screens, air vents, thermostats,
skirting boards, blinds, integrated appliances and door furniture.

Near-negative examples include wood grain that is not mould, a tile joint that
is not a crack, a clean reflection that is not a stain, deliberate distressed
paint, ordinary shadow, condensation without proven damp, and an empty mount
where the missing item cannot be identified.

## Dataset layout

```text
evals/fixtures/synthetic-room-eval/
  README.md
  dataset.json
  tasks.csv
  schemas/
    scene-spec.schema.json
    verified-labels.schema.json
  scenarios/
    RP-001.json
    ...
    RP-025.json
  images/
    antigravity/
      builtin/
    openai/
      gpt-image-2/
  reviews/
    RP-001.antigravity-builtin.json
    RP-001.gpt-image-2.json
  generation_runs/
    antigravity/
  rejected/
    manifest.jsonl
  splits/
    development.json
    validation.json
    sealed.json
  outputs/
    <backend>/<prompt-version>/
  reports/
```

Do not commit conversational exports, account identifiers or provider session
data. Strip unrelated metadata while retaining generator provenance and
content-authenticity metadata.

## Scene specification

The scene specification owns intended content and prompt construction. It does
not own observed truth.

```json
{
  "id": "RP-001",
  "room_type": "Kitchen",
  "property_profile": "modest 1990s UK flat",
  "camera": {
    "device_style": "ordinary smartphone",
    "orientation": "landscape",
    "viewpoint": "standing at doorway",
    "shot_scale": "wide"
  },
  "intended_visible_items": [
    "extractor hood",
    "induction hob",
    "oven",
    "sink",
    "smoke alarm",
    "kitchen units",
    "worktop"
  ],
  "intended_defects": [],
  "intended_negatives": ["no mould", "no cracked tiles"],
  "cleanliness": "mildly cluttered but clean",
  "lighting": "overcast daylight plus warm ceiling lights",
  "views": ["A-wide", "B-reverse", "C-inventory", "D-condition"],
  "continuity_requirements": ["same units and appliance positions across all views"],
  "avoid": ["people", "logos", "readable text", "watermark", "impossible geometry"]
}
```

Prompt builders may add provider-specific syntax, but they may not change the
intended facts. Store the exact submitted prompt and any reference-image IDs.

## Independent AI verification and human escalation

Use two passes.

### Pass A — generation acceptance

An AI reviewer, independent of the image-generation call and conversation,
marks each requested item as clearly visible, ambiguous, absent or malformed.
The review record must pin the reviewer model and version, review prompt hash,
timestamp and immutable image hash. The reviewer may use the frozen scene
specification to locate requested evidence, but must treat every intended fact
as a hypothesis rather than truth.

Reject an image without human review when the failure is clear. Escalate
uncertain cases rather than forcing an accept or reject decision. Rejection
criteria are:

- the named room is not recognisable;
- a required anchor object is absent or malformed;
- geometry makes the evidence unreliable;
- a person, logo or readable brand appears;
- an unintended defect would make the intended label false;
- the image is obviously illustrative rather than photographic;
- it differs so much from its room packet that multi-image evaluation would be
  meaningless.

Regenerate at most twice from the same specification. After two failures,
record the specification as a generator failure; do not silently weaken it.

### Pass B — observed evidence labels

An independent AI reviewer labels only what is actually visible. Each claim
records:

- canonical name and accepted aliases;
- frame IDs that support it;
- visibility: clear, partial or ambiguous;
- condition only when visually supportable;
- defect wording, location and severity without causal inference;
- `not_visible` rather than an assumed absence;
- generator deviations from the intended scene.

A second independent AI review checks every defect, every negative and a
stratified 25% of ordinary item labels. It must run in a separate context and
make its judgment before seeing the first reviewer's conclusion.

Escalate a packet to the project owner when:

- either AI reports ambiguity or low confidence that affects a scored label;
- the two AI reviews disagree;
- a suspected defect or near-negative cannot be distinguished reliably;
- views conflict about object identity, condition, geometry or continuity;
- an unintended visible issue would materially change the intended label;
- validation detects missing evidence, invalid provenance or an unexplained
  duplicate; or
- a periodic stratified audit sample is due to check for reviewer drift.

The owner adjudicates only the disputed fields or packet. A clear packet may
become **verified synthetic gold** after both AI passes and deterministic
validation without routine owner review. Until that point, labels are
generation manifests or provisional labels. Record AI decisions, owner
escalations and resolutions so the review path remains inspectable.

## Development and sealed splits

Split by room packet so related angles never cross a boundary. Where a
retained Google packet exists for a specification, it stays in that
specification's split:

| Split | Matched room specifications | Images | Use |
|---|---:|---:|---|
| Development | 15 | 60 | Prompt and architecture iteration |
| Validation | 5 | 20 | Choose among named candidates |
| Sealed synthetic test | 5 | 20 | One final synthetic comparison |

Stratify room types, defects and near-negatives across the three splits. Publish split hashes before running the sealed comparison.

The real-property fixtures remain separate. No synthetic result can satisfy
the native-resolution accuracy criterion in docs/00.

## VLM evaluation matrix

Run every candidate backend against both providers' images and report the
generator slices separately. At minimum compare:

1. current production prompt and architecture;
2. revised evidence-bounded prompt;
3. per-frame extraction followed by deterministic merge;
4. per-frame extraction followed by VLM adjudication;
5. cheap primary model with an expensive verifier on ambiguous or material
   claims.

For each architecture, pin the backend model version, prompt version, image
order, temperature or equivalent sampling controls, retry policy and schema.
Cache sanitised raw CLI responses so scoring never requires a second
nondeterministic call. Remove conversation IDs and other provider session
data before committing records.

Report:

- notable and all-item recall;
- hallucination rate;
- naming accuracy and granularity splits;
- condition exact and within-one;
- defect recall and unsupported-defect rate;
- negative-control false-positive rate;
- duplicate rate after room merge;
- evidence-link accuracy;
- invalid-schema and retry rate;
- token cost, money and latency;
- every metric by generator, room type, frame role, visibility and defect
  status.

### Bias checks

Single-provider generation weakens these checks; say so in every report
rather than implying a control that no longer exists.

- Where a complete retained Google packet exists, compare each backend on
  Google and GPT Image 2 imagery for that specification. This slice is
  opportunistic and unbalanced — it cannot carry a conclusion on its own.
- Flag a self-generator advantage when an OpenAI-family backend improves
  materially on GPT Image 2 imagery but not on the retained Google slice.
- Treat "GPT Image 2 house style" as an unmeasured confound on every synthetic
  result. The control that decides is real transfer, not the slice.
- Compare synthetic rankings with real-fixture rankings. A candidate that wins
  synthetically but regresses on real photographs does not ship.

## Pass bars

The pilot is useful if it produces a stable, inspectable development signal;
it is not required to clear the v1 product gate.

| Gate | Requirement |
|---|---|
| Initial generation yield | At least 150/200 first or second attempts accepted (75%); retain and exclude failed outputs rather than stopping prompt/VLM work |
| Label quality | 100% defects/negatives double-checked; ≥25% ordinary labels double-checked |
| Packet completeness | All 25 specifications have complete four-view Google and GPT Image 2 packets |
| Delta probe (Phase 3.5) | ≥2 of 3 probe scenarios yield an acceptable pair within 2 attempts, with zero unenumerated material changes |
| Prompt win | Either a single prompt improves validation notable recall ≥5 pp or drops hallucination ≥2 pp with the other metric non-regressing, **or** a per-task assignment beats the production prompt on both passes with no metric regressing on the pass it is assigned to |
| Architecture win | Validation quality improves and per-property projected cost remains ≤ docs/00 budget |
| Sealed confirmation | Named winner retains the direction of improvement on sealed synthetic packets |
| Real transfer | Winner does not regress real notable recall, hallucination or defect recall |

Synthetic metrics may reject a weak approach early. Only the real-transfer
gate can promote a change to the product path.

### Frozen comparison order

The programme changes one decision class at a time:

1. hold the production backend and architecture fixed;
2. compare the production prompt with the named
   **evidence-bounded coverage prompt**;
3. freeze the winning prompt **or**, when the comparison shows a genuine
   trade-off rather than a dominant candidate, freeze a per-task assignment
   (named prompt per pass) and carry that assignment forward as the unit;
4. compare merge and verifier architectures using that prompt;
5. run the selected configuration once on the sealed synthetic split; and
6. require non-regression on real fixtures before changing production.

The evidence-bounded coverage prompt must systematically enumerate visible
notable items and material defects, cite the supporting frame for each
material claim, use `ambiguous` or `not_visible` instead of inferred absence,
avoid causal claims about visible damage, and avoid strengthening partial
evidence during multi-image consolidation. Its primary objective is improved
notable-item and defect recall.

Material claims are hard guardrails throughout validation and the sealed run.
A candidate is rejected if it introduces an additional unsupported material
defect, misses a material defect found by the baseline, or weakens a material
claim's evidence link, even when an aggregate prompt metric improves.

## Generation workflow without image APIs

**Permanent project rule, 28 Jul 2026, amended 3 Aug 2026:** image-generation
API calls are never permitted. GPT Image 2 images may be generated only
through Codex's `imagegen` skill, which is the sole generation route from
3 Aug 2026. Configured API credentials do not change this boundary. The
retired Antigravity route was likewise subscription-only; do not reinstate it
without an explicit decision recorded here. Vision-description
evaluation is a separate action and still requires task-specific approval.

1. Generate `tasks.csv` and exact prompts locally from the scenario manifests.
2. An operator claims one task and records provider/model/session start.
3. Submit the prompt through the subscribed product interface.
4. Save the original output without editing it.
5. Record exact prompt, output filename, timestamp and any provider warning.
6. Run independent AI Pass A and either accept, retry or escalate uncertainty.
7. Complete independent AI Pass B after the four-view packet is present.
8. Run the required separate AI checks and obtain owner adjudication only for
   defined exceptions or drift-audit samples.
9. Run local schema, duplicate, resolution and provenance checks.

Antigravity CLI 1.1.8 can call its built-in `generate_image` tool through the
authenticated subscription, save original JPEG outputs and return hashes. It
does not expose a selectable image backend in successful run records. Record
successful outputs as `antigravity-builtin / backend_model: unknown` unless a
specific successful response exposes the backend. Do not infer the cohort from
the Antigravity reasoning-model selector. Do not fall back to a Gemini web app
or API.

The current built-in image tool did not reliably accept an existing first view
as a visual reference. Treat continuity as a Pass A decision. A packet that
fails continuity twice is a terminal generator failure; do not weaken its
scene specification.

GPT Image 2 generation uses Codex's built-in `imagegen` tool, one tool call per
image. Use the accepted first view as the reference for later views when
continuity is needed. The operator must still save and log each image; do not
commit conversation or provider session identifiers.

## Implementation phases

### Phase 0 — terms and tooling proof

- [x] Record applicable OpenAI and Google terms with access dates.
- [x] Resolve the Google consumer-terms ambiguity before dataset acceptance —
      project owner approved the bounded evaluation use on 15 Jul 2026 because
      it uses provider AI systems for an inventory task and does not train,
      fine-tune, distil or otherwise develop model weights. Re-check if the use
      or publication scope changes; this is an owner decision, not external
      legal confirmation.
- [x] Probe Antigravity CLI 1.1.8 — the built-in image tool works, but the
      successful response does not expose a selectable image backend; record
      the cohort as `antigravity-builtin`.
- [x] Generate one non-scored image per available provider path.
- [x] Confirm original-resolution save, hashes and available provenance for
      the two pilots in `evals/fixtures/synthetic-room-eval/pilots/`.

Exit: both chosen paths are permitted, repeatable and auditable. A provider
that fails this gate is replaced by another permitted path; the dataset does
not pretend to be 50/50.

### Phase 1 — representative slice

- [x] Implement schemas, prompt builder, task queue and validator.
- [x] Author two complete room packets: one Kitchen and one Bathroom.
- [x] Attempt both room specifications through both providers: 16 images total; at least 12 accepted.
- [x] Complete Pass A visual screening and generate the 16-card contact sheet.
- [x] Complete primary Pass B observed-label review for the 14 accepted images.
- [x] Complete independent Pass B checks for all three defect claims, every
      negative and the preselected 25% ordinary-label sample.
- [x] Run the production prompt and frozen evidence-bounded coverage prompt
      through the same Antigravity whole-room adapter. Do not revise either
      after outputs are visible.

Exit: all 16 generations attempted, at least 12 accepted images, labels resolve
without ad hoc fields, and at least one real model failure is traceable from
output to evidence. Failed generations remain excluded from scoring but do not
block the phase when accepted yield is at least 75%.

**15 Jul 2026 status:** the reversible engineering slice is implemented and
verified: two four-view specifications produce a deterministic 16-row task
queue; scene and observed-label schemas, provisional review records, strict
and work-in-progress validation, and a static contact sheet are present.
Generation attempted all 16 original representative tasks and Pass A accepted
14 (87.5%). Both Pass B reviews and the frozen prompt comparison are complete.
The comparison is directional development evidence, not a product-accuracy
claim.

**Generation-path clarification, 15 Jul 2026:** Antigravity CLI supplies the
Nano Banana 2 Lite half only. GPT Image 2 supplies the other half, preserving
the intended 50/50 generator comparison. Record the product path, exact prompt,
generation time and hash for every output.

**Nano Banana Phase 1 result, 15 Jul 2026:** Antigravity CLI 1.1.2 attempted
eight canonical Nano Banana 2 Lite images. Pass A accepted six (75%). Two
specifications exhausted the two-attempt limit; the failed originals and copied
retry outputs remain hashed in the rejection audit. This meets the revised
generation-yield bar and does not block the GPT Image 2 half or single-image VLM
evaluation. Incomplete Google packets are excluded from room-level multi-image
scoring rather than silently repaired.

**GPT Image 2 Phase 1 result, 15 Jul 2026:** the Codex built-in image generator
produced eight distinct first-attempt images and Pass A accepted all eight.
Every output has a distinct SHA-256 hash, including the six views generated
with a same-room reference, so the Antigravity copy symptom did not recur in
this batch. Because no GPT first attempt failed, this result does not test the
narrower question of whether a GPT correction retry could copy an earlier
output.

**Pass A sign-off, 15 Jul 2026:** the project owner reviewed and approved the
representative generation slice in full. Pass A is closed at 14/16 accepted
(87.5%), above the agreed 75% threshold. The two terminal generation failures
remain excluded and preserved in the rejection audit.

**Primary Pass B review, 15 Jul 2026:** all 14 accepted images now have
evidence-linked observed claims, structured negative controls and recorded
generator deviations. The intended kitchen cabinet chip and both generated
bath-panel scuffs were recorded as minor defects; rejected Google frames do not
support any claim. Four ordinary-label samples of at least 25% per provider
packet were preselected, and the records were held provisional pending the
independent checks completed below.

**Independent Pass B review, 28 Jul 2026:** Conor Brown reviewed the three
defect claims, every negative control and the four preselected ordinary-label
samples through the phone review protocol. All 37 required decisions agreed
with the primary observed-evidence review. All four provider/packet records are
now `verified_synthetic_gold` and were eligible for the frozen comparison
below.

**Prompt comparison, 28 Jul 2026:** the production prompt and evidence-bounded
coverage prompt are frozen by SHA-256 in `dataset.json`. Four immutable runs
completed through Antigravity CLI 1.1.8 using the pinned
`gemini-3.5-flash-low` operator mode, the same schema and the same whole-room
architecture. No Gemini API credential or metered endpoint was used. The
evidence-bounded prompt raised defect recall from 50% to 100% and removed one
unsupported defect, but item recall fell from 78.1% to 71.9%. The material
guardrail passed; the prompt-win bar did not. Freeze no winner until the
development and validation sets are complete. Wrapper token counts are logged
for reproducibility but are not raw API billing units.

### Phase 2 — extract the pattern

- [x] Freeze schemas and naming vocabulary.
- [x] Add a static review page with image/manifest/label comparison.
- [x] Add generator-sliced scoring and paired comparisons.
- [x] Freeze room-packet split assignment before the remaining generation.

Exit: another operator can generate and review a task using only the repo
instructions.

**28 Jul 2026 status:** Phase 2 is complete. The queue contains 25 matched
scenario manifests and 200 immutable tasks. Development, validation and sealed
packet assignments are frozen in `splits/` and recorded by SHA-256 in
`dataset.json`.

### Phase 3 — complete development and validation sets

- [ ] Generate the remaining development and validation packets.
- [x] Extend the review schema and templates with AI reviewer provenance,
      review-prompt hashes and escalation outcomes.
- [ ] Run independent AI Pass A and Pass B, escalate only the defined
      exceptions, and repair labels without repairing image pixels.
- [ ] Run the production and evidence-bounded coverage prompts with the
      production backend and architecture fixed.
- [ ] Freeze the winning prompt using the validation split, cost constraint
      and material-claim guardrails.
- [ ] Only then run named architecture candidates with that prompt fixed.
- [ ] Select one architecture using the same validation and cost constraints.

Exit: 160 accepted development and validation images or a documented
generator failure rate that stops the programme.

**28 Jul 2026 stop:** the scale run through Antigravity CLI hit
`RESOURCE_EXHAUSTED`/429 before the Google cohort was complete. The immutable
queue currently contains 8 Pass A accepted images, 23 images awaiting Pass A,
4 terminal Google generator failures and 165 pending tasks. Four complete
Google packets and two partial packets await review. The stop record is
`generation_runs/antigravity/quota-stop-2026-07-28.json`. Resume after the
reported reset, but do not start prompt/architecture selection until the
required development and validation packets have passed both reviews.

**29 Jul 2026 pause:** generation resumed after the recorded reset and is now
paused at a clean operator checkpoint. The development/validation queue has
8 `pass_a_accepted`, 93 `review_pending`, 4 `generator_failed` and 55
`pending` tasks. The GPT cohort is complete through RP-010: 28 new images were
generated in this session, expanding the pilot-task cohort from 12 to 40
files. Google gained 42 files and now has 15 complete
four-view packets awaiting Pass A, one partial packet (`RP-016`, A-wide only),
two quota-stopped packets (`RP-010`, `RP-011`) and one unstarted packet
(`RP-020`) in the development/validation splits. Three complete Google packets
(`RP-009`, `RP-012`, `RP-018`) have files and hashes but no successful wrapper
record; they remain provisional and need Pass A plus provenance review.
No prompt or architecture evaluation was started. The sanitised resume record
is `generation_runs/antigravity/pause-2026-07-29.json`; raw temporary wrapper
logs containing provider conversation identifiers were removed.

**29 Jul 2026 11:21 checkpoint:** the four-view GPT Image 2 packet for
`RP-011` was generated through Codex `imagegen`, copied unedited to the
frozen output paths and recorded with distinct SHA-256 hashes. All four
images remain `review_pending`; none is accepted or gold. A sandboxed
Antigravity attempt failed before provider access, and the authorised retry
reached the provider but returned `RESOURCE_EXHAUSTED`/429 on the first
`RP-010` image call. No Google output file was created, so no task attempt was
consumed. The development/validation queue is now 8 `pass_a_accepted`,
97 `review_pending`, 4 `generator_failed` and 51 `pending`. The sanitised
checkpoint is
`generation_runs/antigravity/pause-2026-07-29-1121.json`. Dataset validation
reports zero errors and the 12 focused synthetic-evaluation tests pass with a
workspace-local pytest temp directory. No prompt or architecture evaluation
has started.

**29 Jul 2026 12:05 checkpoint:** after the provider quota reset,
Antigravity CLI generated all four frozen `RP-010` Google tasks successfully
in one packet. The original JPEGs are recorded at 1376×768 with distinct
SHA-256 hashes and status `review_pending`. Direct visual inspection found a
coherent child's-bedroom packet suitable for Pass A, but did not accept any
frame or verify its requested evidence. The development/validation queue is
now 8 `pass_a_accepted`, 101 `review_pending`, 4 `generator_failed` and 47
`pending`. Dataset validation reports zero errors and the 12 focused
synthetic-evaluation tests pass. The sanitised resume record is
`generation_runs/antigravity/resume-2026-07-29-1205.json`.

**29 Jul 2026 12:25 checkpoint:** Antigravity completed the four-view Google
packets for `RP-011` and `RP-020`. The partial `RP-016` packet gained
`B-reverse`, but generation stopped before `C-inventory` and `D-condition`;
an immediate missing-view retry returned `RESOURCE_EXHAUSTED` with an
estimated reset of about four and a half hours and created no file. The
existing `A-wide` and new `B-reverse` files remain immutable and
`review_pending`. Codex `imagegen` completed all four GPT Image 2 views for
`RP-012`; Pass A must specifically check that `B-reverse` contains the
requested bay-window evidence. Direct visual inspection found the other new
packets coherent enough to enter Pass A, but accepted no image. The
development/validation queue is now 8 `pass_a_accepted`, 114
`review_pending`, 4 `generator_failed` and 34 `pending`. The sanitised
checkpoint is
`generation_runs/antigravity/pause-2026-07-29-1225.json`.

**29 Jul 2026 13:20 checkpoint:** Codex `imagegen` completed every remaining
GPT Image 2 development/validation packet, `RP-013` through `RP-020`, using
one call per frozen task and each packet's `A-wide` image as the continuity
reference for later views. All 32 new files were copied unedited to their
frozen output paths, hashed and recorded as `review_pending`; none was
accepted or marked gold. Pass A must inspect several visible concerns:
`RP-013 C-inventory` obscures the requested socket evidence, `RP-014
D-condition` appears to show more than the intended three scuffs, `RP-019
D-condition` does not clearly show all requested low-level evidence, and
`RP-020 D-condition` omits the requested carpet rods. The
development/validation queue is now 8 `pass_a_accepted`, 146
`review_pending`, 4 `generator_failed` and 2 `pending`. The two pending tasks
are Google `RP-016 C-inventory` and `D-condition`. Dataset validation reports
zero errors and the 12 focused synthetic-evaluation tests pass. The sanitised
checkpoint is
`generation_runs/antigravity/pause-2026-07-29-1320.json`.

**30 Jul 2026 01:56 checkpoint:** the complete 146-frame AI Pass A and 89
owner exceptions were imported atomically. The final result was 93 accepted
and 53 rejected first attempts. Nine owner accepts that contradicted hard
Pass A criteria were retained in the audit trail and corrected by a separate
protocol record; the raw owner export was not rewritten. All 53 rejected
files were hash-checked and archived before retry. Codex `imagegen` produced
and recorded all 18 required GPT Image 2 retries with exact prompt, output and
same-packet A-wide reference hashes. Antigravity produced 21 of 35 required
Google retries; 14 remain missing. Its isolated attempt to complete Google
`RP-016 C-inventory` and `D-condition` returned a zero-token individual-quota
error with a reported reset in `4h11m4s`, so those two first attempts remain
pending. The full queue is now 101 `pass_a_accepted`, 39 `review_pending`, 14
`retry_pending`, 4 `generator_failed` and 42 `pending`; 40 pending tasks are
the untouched sealed split.

Dual independent retry Pass A, its atomic applicator, observed-evidence Pass B
with blind risk-label checks, Pass B promotion guards, GPT retry provenance
and the special Google provenance audit are implemented. On 30 Jul 2026 the
39 available retry outputs completed two blind Pass A reviews: 5 were
accepted, 28 rejected and 6 escalated. The six owner decisions and atomic
application remain; no retry outcome has been promoted from this report yet.
Seven complete, provenance-eligible packets are currently ready for Pass B.
No development/validation scoring, prompt selection, sealed work or real
transfer has started. Dataset validation reports zero errors and the focused
synthetic suite has 24 passing tests.

**3 Aug 2026 session:** quota had reset, so generation resumed for the missing
Google views. Two things must be read together with the results.

*CLI version incident.* `agy.exe` self-updated from 1.1.8 to 1.1.10 during the
first run, and its two `RP-016` outputs were generated on the unsanctioned
version. Those outputs were discarded, 1.1.8 was restored from the retained
`.old` binary and marked read-only, and `RP-016` was regenerated on 1.1.8. The
read-only lock held for the remainder of the session; every run record from
3 Aug is stamped 1.1.8. Clear the lock deliberately when moving the programme
to a new pinned version — an unnoticed update would otherwise split a cohort
across two generator versions.

*Generation outcome.* `RP-016` C-inventory and D-condition were generated, and
6 of the 14 missing retry views completed with successful run records
(`RP-007` C-inventory, `RP-011` C-inventory and all four `RP-014` views).
Where a packet reused accepted views as continuity references, those files
were verified byte-identical to `tasks.csv` afterwards. Generation then hit
`RESOURCE_EXHAUSTED`/429 again.

*`RP-015` terminal generator failure.* Attempt 2 wrote A-wide, B-reverse and
C-inventory and then hit the 429 before D-condition, and the CLI wrapper
returned ERROR — so no successful raw run record exists for those three views,
the same absent-provenance condition that blocks `RP-009`, `RP-012` and
`RP-018`. Regenerating them would have been a third attempt, exceeding the
two-attempt cap, so the project owner declared the scenario a terminal
generator failure on 3 Aug 2026. The three views are archived at
`rejected/RP-015.antigravity-builtin.<view>-attempt-2.jpg`. D-condition stays
at `attempts=1` because its second attempt never executed; it is terminal by
owner decision, not by the stopping rule. The scene specification was not
weakened.

*`RP-019`* was blocked before writing any output, so it has no orphaned files
and no partial provenance. Its four views remain `retry_pending` at
`attempts=1` and are still eligible for a second attempt after the reset.

The 429 text named the underlying image model as `gemini-3.1-flash-image`.
Because that appeared only in a failed response, every `backend_model` remains
`unknown`; the naming is recorded as an observation in
`generation_runs/antigravity/pause-2026-08-03-1733.json`, not promoted to
provenance.

**3 Aug 2026 GPT Image 2 generation disposition:** Codex-run new generation
uses GPT Image 2 through the built-in `imagegen` path. The 20 previously
untouched GPT rows (`RP-021` through `RP-025`, four views each) were generated
on 3 Aug 2026 using each packet's A-wide frame as the local continuity
reference for B/C/D. Their exact prompts, hashes and reference hashes are in
`reports/gpt-image-2-generation-2026-08-03.json`; all remain `review_pending`.
The two earlier `RP-019` replacements remain `review_pending` as well.

**3 Aug 2026 Gemini Omni candidate cohort:** the project owner supplied a
second batch of images generated with Gemini Omni, using the frozen prompts and
the stated attachment order. These are staged as candidate evidence only; no
`tasks.csv` row or approved image was overwritten. The staged material is:

- 21 isolated candidates in
  `reports/gemini-omni-user-batch-2026-08-03.json`.
- 36 candidates in nine four-view batches: `RP-003`, `RP-014`, `RP-015`,
  `RP-019`, `RP-021`, `RP-022`, `RP-023`, `RP-024` and `RP-025`, recorded in
  `reports/gemini-omni-prior-batches-2026-08-03.json`.

The candidates are stored under
`images/google/gemini-omni/` with SHA-256 hashes and source filenames. `RP-021`
is the stairs-and-landing batch; `RP-020` was not supplied. The project owner
has reviewed the 57 candidates and reports that they pass. They still need to
be imported into the 200-row task ledger and run through the normal
independent Pass A/B recording path before promotion.

After the owner review note and GPT Image 2 generation recording, the task
ledger contains 108 `pass_a_accepted`, 22 `review_pending`, 10
`retry_pending`, 38 `generator_failed` and 22 `pending` rows. Dataset
validation reports zero errors (92 existing warnings). The 57 Gemini Omni
files remain separate candidate artifacts until their ledger import is
applied.

**Next actions:** review the 57 Gemini Omni candidates against their frozen
view prompts; record accepted/rejected decisions and provenance in the task
ledger; then rebuild the static review gallery and rerun dataset validation.

### Phase 3.5 — delta pairs (check-in/check-out and counterfactual)

*Added 3 Aug 2026. Gated: the probe must pass before the pilot runs.*

The compare surface is the artefact adjudicators decide on, and it has no
ground truth. This phase manufactures it. A **delta pair** is two renders of
one room specification with an enumerated `changes` list between them and an
explicit assertion that nothing else material changed.

Two classes:

| Class | Pair | Question it answers |
|---|---|---|
| Temporal | T0 check-in → T1 check-out | Does compare report every real change and stay silent on everything else? |
| Counterfactual | defect absent → defect present, same timepoint | Does describe see the defect that exists and not the one that does not? |

#### Scene specification extension

Delta specifications reuse the existing scene schema and add:

```json
{
  "delta_of": "RP-004",
  "timepoint": "T1",
  "reference_image": "RP-004.gpt-image-2.A-wide.jpg",
  "changes": [
    {"id": "D1", "kind": "new_defect", "target": "carpet by the radiator",
     "description": "dark stain roughly 15cm across", "material": true},
    {"id": "D2", "kind": "item_removed", "target": "floor lamp",
     "description": "lamp present at T0 is absent at T1", "material": true},
    {"id": "D3", "kind": "worsened", "target": "chip on base unit door",
     "description": "chip widened and paint lifted at the edge", "material": true}
  ],
  "unchanged_assertions": [
    "same units, worktop, flooring, window and appliance positions",
    "no change to the splashback or skirting"
  ]
}
```

`changes` is the delta gold. `unchanged_assertions` is what makes the pair
scorable at all: without it, an unenumerated drift is indistinguishable from a
true change, and a false-change metric is meaningless.

#### Views

Delta pairs render **two views per timepoint**, not four: `A-wide` (the
establishing view compare works from) and `D-condition` (where defects live).
Four views per timepoint doubles the drift surface for no extra signal at
probe scale.

Each `change` may carry an optional `views` list naming the views that can
actually show it; unscoped changes apply to both. Without this, a close
condition detail is requested in a wide establishing shot that cannot resolve
it, and the render comes back "missing" a change it was never able to
display — recorded as a generator failure that did not happen. Tooling
enforces the other side of the same rule: every rendered view must receive at
least one *material* change, because a render with nothing to show carries no
delta signal and its half of the pair cannot be scored.

#### Feasibility probe (gate)

Three scenarios only, one provider (GPT Image 2 via Codex `imagegen`), reusing
already-accepted T0 packets as the reference so the probe pays only for T1:

- [x] Pick 3 accepted development-split specifications spanning a kitchen, a
      soft-furnished room and a bathroom. *RP-004 (kitchen), RP-011 (living
      room), RP-002 (bathroom) — all four GPT Image 2 views `pass_a_accepted`,
      all in the development split, so no pair crosses a split boundary.*
- [x] Author a T1 delta spec for each with 2–3 enumerated material changes.
      *`deltas/RP-004-T1.json`, `deltas/RP-011-T1.json`,
      `deltas/RP-002-T1.json`; the 6-generation queue is `delta_tasks.csv`.*
- [ ] Render `A-wide` and `D-condition` at T1 with the T0 frame as reference.
- [ ] Independent AI review of each pair records, per pair: (a) is this the
      same room, (b) is each enumerated change visible, (c) list every
      *unenumerated* material difference observed.
- [ ] Owner adjudicates all three pairs. Probe images are calibration
      evidence, not scored data.

**Pass:** ≥2 of 3 scenarios yield an acceptable pair within 2 attempts each,
with zero unenumerated material changes in an accepted pair, and median
operator time within the existing 8-minute-per-accepted-image bar.

**Fail:** record the drift modes observed, abandon the extension, and keep
this section as a negative result. Do not retry with a looser bar — a delta
set that cannot hold identity produces confidently wrong gold, which is worse
than no gold.

#### Pilot, if the probe passes

- [ ] 8 temporal pairs and 4 counterfactual pairs, drawn from accepted
      development and validation specifications, stratified across room types
      and change kinds (new defect, worsened defect, item removed, item added,
      cleanliness change, and at least 2 pairs whose only changes are
      immaterial).
- [ ] Every pair passes the same Pass A / Pass B review path as the main
      dataset, plus the unenumerated-change check.
- [ ] Delta pairs inherit the split of the specification they derive from.
      A delta pair never crosses into a different split from its T0 parent.

#### Metrics

Reported separately from the static-image metrics; these are compare metrics,
not description metrics:

- **delta recall** — enumerated material changes correctly reported;
- **false-change rate** — reported changes with no enumerated counterpart.
  This is the headline: a compare feature that invents change is worse than
  useless in an adjudication, because it converts the landlord's evidence into
  the tenant's;
- **unchanged stability** — items correctly reported as unchanged;
- **severity direction** — worsened/improved called in the right direction;
- **evidence-link accuracy** across both timepoints.

#### Boundaries

- Delta pairs are development evidence. They cannot promote compare behaviour;
  that needs real check-in/check-out evidence, and docs/08 owns the product
  surface.
- Do not train on delta pairs. The Out-of-scope rule is unchanged.
- Never present a synthetic delta pair as a real tenancy comparison.

Exit: either a scored delta set with the metrics above, or a recorded negative
result explaining which drift mode defeated it.

### Phase 4 — sealed synthetic comparison

- [ ] Hash prompts, labels and selected candidate configuration.
- [ ] Generate/review the five matched sealed specifications if they were not
  generated earlier; do not inspect model outputs while labelling.
- [ ] Run the selected candidate and current production baseline once.
- [ ] Publish paired results and row-level failure analysis.

Exit: the direction of improvement holds or the candidate is rejected.

### Phase 5 — real transfer

- [ ] Run the winner on InventoryFlex and native-resolution real fixtures.
- [ ] Reject any change that improves synthetic results but regresses real
  evidence.
- [ ] Prepare an internal dataset card with generation/review method, terms
  record, limitations, splits, prompts and verified labels.

Exit: synthetic development evidence and real product evidence are recorded
as separate tables. Public release and customer-site examples are post-v1
actions requiring a separate provider-terms, provenance, metadata and
licensing review; publication does not turn synthetic evidence into a product
claim.

## Files to implement

| File | Purpose |
|---|---|
| `evals/synthetic/build_tasks.py` | Deterministically turn scene specs into prompts and `tasks.csv` |
| `evals/synthetic/validate_dataset.py` | Schema, file, dimensions, pair and provenance checks |
| `evals/synthetic/build_review.py` | Static AI-review and human-escalation/contact-sheet artifact |
| `evals/synthetic/generate_antigravity.py` | Retired for generation on 3 Aug 2026; retained to read existing Google run records |
| `evals/synthetic/build_delta_tasks.py` | Turn `delta_of` specs into T1/counterfactual generation tasks with reference frames |
| `evals/synthetic/review_delta_pair.py` | Pair review: same-room identity, enumerated-change visibility, unenumerated-change detection |
| `evals/synthetic/score_delta.py` | Delta recall, false-change rate, unchanged stability, severity direction |
| `evals/synthetic/degrade.py` | Deterministic degradation ladder over accepted images; labels inherited unchanged |
| `evals/synthetic/review_pass_b.py` | Pinned, scriptable Pass B for validation and sealed records: hashed review prompt, cached raw output, reviewer model id and version |
| `evals/synthetic/run_eval.py` | Run named off-the-shelf VLM configurations and cache raw output |
| `evals/synthetic/score.py` | Existing metric contract plus slices and paired comparisons |
| `evals/fixtures/synthetic-room-eval/README.md` | Dataset card and operator instructions |

Use the existing `evals/run_eval.py` scoring semantics where possible. Add a
new metric only when the current schema cannot express the decision.

## Risks and stopping rules

| Risk | Control / stopping rule |
|---|---|
| Prompt manifest is mistaken for observed truth | Independent AI reviews treat intended facts as hypotheses; observed labels cite visible frames |
| AI review silently misses a repeated error | Separate second checks, owner escalation triggers and periodic stratified human audit |
| Generator style makes evaluation artificially easy | Single-provider from 3 Aug 2026, so this is now an unmeasured confound: difficult phone-like framing, the retained Google slice and the real-transfer gate are the remaining controls; state the limitation in every report |
| Delta pair drifts in unenumerated ways | Pair review lists every unenumerated material difference; any such difference rejects the pair; probe fails the whole extension rather than loosening the bar |
| Delta gold is mistaken for real compare evidence | Delta metrics reported in a separate table; compare promotion gated on real check-in/check-out evidence (docs/08) |
| Single-generator dependence on one provider | Accept the concentration risk deliberately; if Codex `imagegen` becomes unavailable, stop and re-decide rather than silently reinstating Google |
| Same-family VLM advantage | Report provider × backend matrix |
| Multi-angle item drift | Record continuity failure; never silently reconcile contradictions |
| Defects look decorative or physically impossible | Double-check all defects; reject implausible examples |
| Dataset rewards exhaustive hallucination | Explicit negatives and unsupported-defect metric |
| Manual generation becomes too slow | Prove 20-image slice; stop if median operator time exceeds 8 minutes per accepted image |
| Provider limits or model names change | Pin displayed model name and date; never silently substitute |
| Terms do not permit the use | Stop that provider before accepting images |
| Synthetic ranking does not transfer to real photos | Do not promote; retain only as diagnostic material |

## Definition of done

*Revised by Amendment B, 3 Aug 2026. The "exactly 200 accepted images" clause
is removed: 39 tasks are terminally failed and Google generation is retired,
so it was unreachable.*

- [x] 25 matched four-view specifications and immutable packet splits implemented.
- [ ] Every validation and sealed specification has a complete four-view GPT
  Image 2 packet after the cap-3 repair pass, or a recorded terminal failure.
- [ ] The Google slice is reported at whatever size it lands, excluded from
  publication and from any training corpus, and described only as an
  opportunistic cross-generator check.
- [ ] Every accepted image has exact prompt, provenance, AI-observed labels
  and any required human adjudication.
- [ ] Defects and negatives are all double-checked by an independent AI of a
  different model family from both the generator and the primary reviewer,
  with disagreements and ambiguity resolved by the project owner.
- [ ] Validation and sealed Pass B records are re-runnable through the pinned
  scriptable path; development records are marked attested and
  `provisional_development`.
- [ ] Baseline and candidate results are reported at both frame level and
  room level with `n` stated, with Antigravity and Gemini Omni service slices
  broken out separately.
- [ ] Phase 3.5 has either a scored delta set or a recorded negative result.
- [ ] Degradation-ladder sensitivity results are reported alongside the clean
  synthetic numbers.
- [ ] A sealed synthetic comparison is complete.
- [ ] The winning change passes held-out real-property regression gates.
- [ ] Public dataset card and customer-facing synthetic disclosure are ready.

## Related owners

- `docs/00-north-star.md` — real-property v1 success criteria.
- `docs/04-backend-comparison.md` — backend benchmark evidence.
- `docs/19-ml-dl-exploration-plan.md` — weight-training and classical ML work.
- `docs/21-ml-dl-experiment-log.md` — ML experiment results.
- `docs/08-compare.md` — check-in/check-out comparison product surface.
- `docs/26-capture-strategy-experiment.md` — real photo/video capture evidence.
- `evals/README.md` — current fixture schema and scoring commands.
