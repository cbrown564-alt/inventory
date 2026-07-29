# 31 — Synthetic room evaluation dataset

*Updated 29 Jul 2026. Implementation plan for a public, independently
AI-reviewed synthetic room dataset with human escalation, used to develop
prompts and compare off-the-shelf VLM pipelines. This document owns the
synthetic evaluation dataset. It does not change the real-property v1 quality
gate in docs/00 or the ML training programme in docs/19.*

## Decision

Build a **200-image pilot** as 25 matched four-view room specifications
rendered once through Antigravity CLI's built-in Google image generator and
once through Codex's GPT Image 2 generator. Use it to find prompt and pipeline
failures quickly. Do not train or fine-tune model weights on the images.

For this synthetic programme, both Google image generation and Google
vision-description evaluation use the subscription-backed Antigravity CLI.
Never use Gemini API credentials or a metered Gemini endpoint. GPT Image 2
generation uses only Codex's built-in `imagegen` path. This is narrower than
the production backend policy in docs/00.

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

## Current execution status — 29 Jul 2026

| Phase | Status | Evidence |
|---|---|---|
| 1 — representative slice | **Complete** | Four immutable Antigravity CLI vision runs compared the two frozen prompts. The candidate improved defect recall from 50% to 100% and removed one unsupported defect, but item recall fell 6.2 percentage points, so no prompt winner was frozen. |
| 2 — extract the pattern | **Complete** | 25 scenarios, the 200-task queue, review templates, static review page, generator slices and hashed development/validation/sealed splits are implemented. |
| 3 — development and validation | **Paused** | Across the 160 development/validation tasks, 8 previously accepted GPT images remain accepted, 146 generated images await independent AI Pass A, 4 Google tasks are terminal generator failures and 2 Google tasks remain pending. The GPT Image 2 development/validation cohort is complete through `RP-020`; only the `C-inventory` and `D-condition` Google views of `RP-016` remain to generate. |
| 4 — sealed comparison | **Dependency-blocked** | No validation winner exists, so opening the sealed model comparison would violate the frozen order. |
| 5 — real transfer | **Dependency-blocked** | There is no selected winner to run on real fixtures. The separate native-resolution evidence gate also remains open. |

The quota responses are provider-internal limits reached through Antigravity
CLI; they are not metered image API calls made by this project. Resume Phase 3
from `generation_runs/antigravity/pause-2026-07-29-1320.json`, complete the
pending generation tasks, then run the independent AI reviews and send only
the required exceptions to the project owner. Do not mark generated files
accepted or gold without the recorded review path.

The existing review schema and templates predate the AI-first decision: they
have free-text reviewer fields but do not yet pin reviewer model/version and
review-prompt hashes or record an escalation decision. Update them before
starting the 146-image review run. The policy is decided; its metadata support
is a Phase 3 implementation task.

## The question this dataset answers

> Given controlled room evidence with known visible items, conditions and
> defects, which prompt and VLM pipeline most reliably produces a
> review-ready inventory without omissions or invented claims?

The pilot should distinguish four failure sources:

1. image evidence is insufficient or ambiguous;
2. the VLM misses or invents visible facts;
3. the prompt asks for the wrong output or encourages overclaiming;
4. the multi-image merge loses, duplicates or strengthens claims.

## Scope and boundaries

### In scope

- still-image description using the approved Antigravity CLI model path;
- single-image and room-level multi-image pipelines;
- prompt, schema, frame-selection, merge, verification and retry changes;
- items, condition, cleanliness and visible defects;
- exact negatives and near-negatives that test hallucination;
- paired comparison across image generators;
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
- a 200-image continuous virtual home with perfect object permanence.

## Terms gate

Generation must pause for a provider if its applicable terms do not clearly
permit this use.

- **OpenAI:** [current UK consumer terms](https://openai.com/policies/eu-terms-of-use/)
  assign output rights to the user and
  prohibit developing models that compete with OpenAI. This project does not
  change model weights, but the planned public/commercial dataset use should
  still be recorded with the terms version and, before scaling, confirmed in
  writing if there is doubt.
- **Google consumer services:** [current UK terms](https://policies.google.com/terms?gl=GB&hl=en)
  prohibit using generated
  content to develop machine-learning models or related AI technology. Merely
  avoiding weight tuning may not resolve the broader "related AI technology"
  wording. Re-check the terms due to take effect on 30 Jul 2026 or obtain
  written confirmation before accepting Google-generated images into the
  dataset.
- Subscription interfaces must be used interactively. Do not automate
  extraction, bypass limits, rotate accounts or use API credentials for image
  generation.

Record `provider`, `product`, `model_display_name`, `terms_url`,
`terms_checked_at`, generation timestamp and the human operator for every
accepted image.

## Pilot design

### Matched-pair structure

Create 25 room specifications. Each becomes one four-view Antigravity packet
and one four-view GPT Image 2 packet. This yields 50 generated rooms and
200 images:

| Provider | Model assignment | Images |
|---|---|---:|
| Google | Antigravity CLI built-in `generate_image`; successful records keep `backend_model: unknown` | 100 |
| OpenAI | GPT Image 2 through Codex `imagegen` | 100 |
| **Total** |  | **200** |

Antigravity does not expose a selectable image backend in successful run
records. A provider failure message named `gemini-3.1-flash-image`, but that
diagnostic does not pin the successful cohort. Do not relabel these images as
one of the older Nano Banana assignments. Every Google result has an OpenAI
result with the same intended evidence.

### Generation assignments

| Room type | Antigravity packets | GPT Image 2 packets |
|---|---:|---:|
| Kitchen | 4 | 4 |
| Bathroom / shower room | 3 | 3 |
| Bedroom | 3 | 3 |
| Living room | 3 | 3 |
| Entrance hall | 2 | 2 |
| Dining room | 2 | 2 |
| Utility room / cupboard | 2 | 2 |
| Stairs / landing | 2 | 2 |
| WC / cloakroom | 1 | 1 |
| Storage / wardrobe | 1 | 1 |
| Home office | 1 | 1 |
| Balcony / patio | 1 | 1 |
| **Total packets** | **25** | **25** |
| **Total images** | **100** | **100** |

This paired design supports:

- aggregate VLM accuracy by image generator;
- paired failure analysis on the same intended scene;
- self-family checks, such as the Antigravity Google VLM path on
  Antigravity-generated imagery;
- image-model comparison without changing the content mix.

### Room packets

| Room type | Matched specifications | Frames per provider packet | Images per provider |
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

Each provider packet requests:

1. doorway establishing view;
2. opposite-corner establishing view;
3. fixtures and safety-item view;
4. controlled condition/defect detail or deliberate clean near-negative.

Use the first accepted frame as a reference for later angles when the product
supports image editing or conversational continuity. Consistency is a scored
property, not an assumption. If an item changes between angles, label the
visible result and record the continuity failure.

### Content balance

Across the 25 matched room specifications:

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

Split by room packet so related angles and the matched provider pair never
cross a boundary:

| Split | Matched room specifications | Images | Use |
|---|---:|---:|---|
| Development | 15 | 120 | Prompt and architecture iteration |
| Validation | 5 | 40 | Choose among named candidates |
| Sealed synthetic test | 5 | 40 | One final synthetic comparison |

Stratify room types, defects, near-negatives and generator models across the
three splits. Publish split hashes before running the sealed comparison.

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

- Compare the Antigravity VLM path on Google and OpenAI imagery.
- Compare any approved OpenAI backend on Google and OpenAI imagery.
- Flag a self-generator advantage when a backend improves materially only on
  imagery from its own provider.
- Compare synthetic rankings with real-fixture rankings. A candidate that wins
  synthetically but regresses on real photographs does not ship.

## Pass bars

The pilot is useful if it produces a stable, inspectable development signal;
it is not required to clear the v1 product gate.

| Gate | Requirement |
|---|---|
| Initial generation yield | At least 150/200 first or second attempts accepted (75%); retain and exclude failed outputs rather than stopping prompt/VLM work |
| Label quality | 100% defects/negatives double-checked; ≥25% ordinary labels double-checked |
| Pair balance | All 25 matched specifications have complete four-view Antigravity and GPT Image 2 packets |
| Prompt win | Validation notable recall improves ≥5 pp or hallucination falls ≥2 pp with the other metric non-regressing |
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
3. freeze the winning prompt;
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

**Permanent project rule, 28 Jul 2026:** image-generation API calls are never
permitted. Nano Banana images may be generated only through Antigravity CLI;
GPT Image 2 images may be generated only through Codex's `imagegen` skill.
Configured API credentials do not change this boundary. Vision-description
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
- [ ] Extend the review schema and templates with AI reviewer provenance,
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
| `evals/synthetic/generate_antigravity.py` | Generate Google packets through Antigravity CLI without image API credentials |
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
| Generator style makes evaluation artificially easy | Paired providers, difficult phone-like framing, real transfer gate |
| Same-family VLM advantage | Report provider × backend matrix |
| Multi-angle item drift | Record continuity failure; never silently reconcile contradictions |
| Defects look decorative or physically impossible | Double-check all defects; reject implausible examples |
| Dataset rewards exhaustive hallucination | Explicit negatives and unsupported-defect metric |
| Manual generation becomes too slow | Prove 20-image slice; stop if median operator time exceeds 8 minutes per accepted image |
| Provider limits or model names change | Pin displayed model name and date; never silently substitute |
| Terms do not permit the use | Stop that provider before accepting images |
| Synthetic ranking does not transfer to real photos | Do not promote; retain only as diagnostic material |

## Definition of done

- [x] 25 matched four-view specifications and immutable packet splits implemented.
- [ ] Exactly 100 accepted Antigravity and 100 accepted GPT Image 2 images, or
  an explicit terms/tooling decision explaining why the design changed.
- [ ] Every accepted image has exact prompt, provenance, AI-observed labels
  and any required human adjudication.
- [ ] Defects and negatives are all double-checked by an independent AI, with
  disagreements and ambiguity resolved by the project owner.
- [ ] Baseline and candidate results are reported by provider and on matched
  pairs.
- [ ] A sealed synthetic comparison is complete.
- [ ] The winning change passes held-out real-property regression gates.
- [ ] Public dataset card and customer-facing synthetic disclosure are ready.

## Related owners

- `docs/00-north-star.md` — real-property v1 success criteria.
- `docs/04-backend-comparison.md` — backend benchmark evidence.
- `docs/19-ml-dl-exploration-plan.md` — weight-training and classical ML work.
- `docs/21-ml-dl-experiment-log.md` — ML experiment results.
- `docs/26-capture-strategy-experiment.md` — real photo/video capture evidence.
- `evals/README.md` — current fixture schema and scoring commands.
