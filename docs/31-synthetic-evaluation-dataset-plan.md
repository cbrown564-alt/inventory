# 31 — Synthetic room evaluation dataset

*15 Jul 2026. Implementation plan for a public, human-verified synthetic
room dataset used to develop prompts and compare off-the-shelf VLM pipelines.
This document owns the synthetic evaluation dataset. It does not change the
real-property v1 quality gate in docs/00 or the ML training programme in
docs/19.*

## Decision

Build a **200-image pilot** as 25 matched four-view room specifications
rendered once by Gemini and once by ChatGPT Image 2. Use it to find prompt and pipeline
failures quickly. Do not train or fine-tune model weights on the images.

Synthetic results are development evidence, not product accuracy evidence.
All product claims and promotion decisions remain gated on held-out,
native-resolution photographs from real properties.

The generation prompt states what an image is intended to contain. It becomes
gold only after a human checks what is actually visible and corrects the
labels. Rejected generations remain in the audit log but never enter the
scored set.

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

- still-image description using off-the-shelf VLM APIs;
- single-image and room-level multi-image pipelines;
- prompt, schema, frame-selection, merge, verification and retry changes;
- items, condition, cleanliness and visible defects;
- exact negatives and near-negatives that test hallucination;
- paired comparison across image generators;
- a public dataset with prompts, provenance and human-reviewed labels.

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
  written confirmation before accepting Gemini images into the dataset.
- Subscription interfaces must be used interactively. Do not automate
  extraction, bypass limits, rotate accounts or use API credentials for image
  generation.

Record `provider`, `product`, `model_display_name`, `terms_url`,
`terms_checked_at`, generation timestamp and the human operator for every
accepted image.

## Pilot design

### Matched-pair structure

Create 25 room specifications. Each becomes one four-view Gemini packet and
one four-view ChatGPT packet. This yields 50 generated rooms and 200 images:

| Provider | Model assignment | Images |
|---|---|---:|
| Gemini | Gemini 3.1 Flash-Lite Image / Nano Banana 2 Lite | 36 (9 packets) |
| Gemini | Gemini 3.1 Flash Image / Nano Banana 2 | 32 (8 packets) |
| Gemini | Gemini 3 Pro Image / Nano Banana Pro | 32 (8 packets) |
| ChatGPT | ChatGPT Image 2 | 100 |
| **Total** |  | **200** |

The three Gemini assignments rotate through room types and frame roles rather
than giving one model only easy or difficult images. Every Gemini result has a
ChatGPT result with the same intended evidence.

### Generation assignments

| Room type | Gemini Lite packets | Gemini Flash packets | Gemini Pro packets | ChatGPT Image 2 packets |
|---|---:|---:|---:|---:|
| Kitchen | 2 | 1 | 1 | 4 |
| Bathroom / shower room | 1 | 1 | 1 | 3 |
| Bedroom | 1 | 1 | 1 | 3 |
| Living room | 1 | 1 | 1 | 3 |
| Entrance hall | 1 | 1 | 0 | 2 |
| Dining room | 1 | 0 | 1 | 2 |
| Utility room / cupboard | 0 | 1 | 1 | 2 |
| Stairs / landing | 1 | 1 | 0 | 2 |
| WC / cloakroom | 0 | 1 | 0 | 1 |
| Storage / wardrobe | 1 | 0 | 0 | 1 |
| Home office | 0 | 0 | 1 | 1 |
| Balcony / patio | 0 | 0 | 1 | 1 |
| **Total packets** | **9** | **8** | **8** | **25** |
| **Total images** | **36** | **32** | **32** | **100** |

This paired design supports:

- aggregate VLM accuracy by image generator;
- paired failure analysis on the same intended scene;
- self-family checks, such as Gemini VLMs on Gemini-generated imagery;
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
    gemini/
      flash-lite/
      flash/
      pro/
    chatgpt/
      image-2/
  reviews/
    RP-001.gemini.json
    RP-001.chatgpt.json
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

## Human verification and gold labels

Use two passes.

### Pass A — generation acceptance

The operator marks each requested item as clearly visible, ambiguous, absent
or malformed. Reject an image when:

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

A reviewer labels only what is actually visible. Each claim records:

- canonical name and accepted aliases;
- frame IDs that support it;
- visibility: clear, partial or ambiguous;
- condition only when visually supportable;
- defect wording, location and severity without causal inference;
- `not_visible` rather than an assumed absence;
- generator deviations from the intended scene.

A second reviewer checks every defect, every negative and a stratified 25% of
ordinary item labels. Disagreements are resolved before the sealed split is
used.

Labels are **verified synthetic gold** only after both passes. Until then they
are generation manifests or provisional labels.

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
Cache raw API responses so scoring never requires a second nondeterministic
call.

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

- Compare Gemini backends on Gemini and ChatGPT imagery.
- Compare OpenAI backends on Gemini and ChatGPT imagery.
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
| Pair balance | All 25 matched specifications have complete four-view Gemini and ChatGPT packets |
| Prompt win | Validation notable recall improves ≥5 pp or hallucination falls ≥2 pp with the other metric non-regressing |
| Architecture win | Validation quality improves and per-property projected cost remains ≤ docs/00 budget |
| Sealed confirmation | Named winner retains the direction of improvement on sealed synthetic packets |
| Real transfer | Winner does not regress real notable recall, hallucination or defect recall |

Synthetic metrics may reject a weak approach early. Only the real-transfer
gate can promote a change to the product path.

## Generation workflow without image APIs

1. Generate `tasks.csv` and exact prompts locally from the scenario manifests.
2. An operator claims one task and records provider/model/session start.
3. Submit the prompt through the subscribed product interface.
4. Save the original output without editing it.
5. Record exact prompt, output filename, timestamp and any provider warning.
6. Run Pass A acceptance and either accept, retry or reject.
7. Complete Pass B labels after the four-view packet is present.
8. Run local schema, duplicate, resolution and provenance checks.

Antigravity CLI may be used only if it exposes the named subscription-backed
image model and returns the original image through a supported command. If its
model list contains only reasoning models or image output is unavailable, use
the Gemini web app manually. Do not substitute a similarly named text model.

The 15 Jul probe found that Antigravity 1.1.2 can call a built-in
`generate_image` tool through the authenticated Google account, but its model
list does not expose any of the three requested image models and the image
tool has no backend-model argument. Antigravity output must therefore be
recorded as `antigravity_builtin / backend_model: unknown`; it cannot fill the
named Gemini cohorts. Use a consumer interface with an explicit selector for
those tasks.

ChatGPT generation uses ChatGPT Image 2. Keep one conversation per room packet
when continuity is needed. The operator must still save and log each image;
do not scrape conversation output.

## Implementation phases

### Phase 0 — terms and tooling proof

- [x] Record applicable OpenAI and Google terms with access dates.
- [x] Resolve the Google consumer-terms ambiguity before dataset acceptance —
      project owner approved the bounded evaluation use on 15 Jul 2026 because
      it uses provider AI systems for an inventory task and does not train,
      fine-tune, distil or otherwise develop model weights. Re-check if the use
      or publication scope changes; this is an owner decision, not external
      legal confirmation.
- [x] Probe Antigravity for the three named image models — named image models
      are not exposed; built-in backend is unknown.
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
- [ ] Complete independent Pass B checks for all three defect claims, every
      negative and the preselected 25% ordinary-label sample.
- [ ] Run the current production backend and one prompt candidate.

Exit: all 16 generations attempted, at least 12 accepted images, labels resolve
without ad hoc fields, and at least one real model failure is traceable from
output to evidence. Failed generations remain excluded from scoring but do not
block the phase when accepted yield is at least 75%.

**15 Jul 2026 status:** the reversible engineering slice is implemented and
verified: two four-view specifications produce a deterministic 16-row task
queue; scene and observed-label schemas, provisional review records, strict
and work-in-progress validation, and a static contact sheet are present.
Generation has now attempted all 16 canonical tasks and Pass A accepted 14
(87.5%). Primary Pass B review is complete. Phase 1 remains open for the
independent Pass B checks and the production-baseline/prompt-candidate
comparison. No model accuracy claim exists yet.

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
packet are preselected. The records remain provisional until an independent
reviewer checks all three defect claims, every negative and those ordinary-label
samples. Only then may the production backend and prompt candidate score
against them as verified synthetic gold.

### Phase 2 — extract the pattern

- [ ] Freeze schemas and naming vocabulary.
- [ ] Add a static review page with image/manifest/label comparison.
- [ ] Add generator-sliced scoring and paired comparisons.
- [ ] Freeze room-packet split assignment before the remaining generation.

Exit: another operator can generate and review a task using only the repo
instructions.

### Phase 3 — complete development and validation sets

- [ ] Generate the remaining development and validation packets.
- [ ] Review and repair labels; never repair image pixels.
- [ ] Run named prompt and architecture candidates.
- [ ] Select one candidate using the validation split and cost constraint.

Exit: 160 accepted development and validation images or a documented
generator failure rate that stops the programme.

### Phase 4 — sealed synthetic comparison

- [ ] Hash prompts, labels and selected candidate configuration.
- [ ] Generate/review the five matched sealed specifications if they were not
  generated earlier; do not inspect model outputs while labelling.
- [ ] Run the selected candidate and current production baseline once.
- [ ] Publish paired results and row-level failure analysis.

Exit: the direction of improvement holds or the candidate is rejected.

### Phase 5 — real transfer and publication

- [ ] Run the winner on InventoryFlex and native-resolution real fixtures.
- [ ] Reject any change that improves synthetic results but regresses real
  evidence.
- [ ] Publish dataset card, generation/review method, terms record, limitations,
  splits, prompts and verified labels.
- [ ] Show generated examples on the customer website only with unmistakable
  synthetic disclosure and no implication that they are tenancy evidence.

Exit: synthetic development evidence and real product evidence are published
as separate tables.

## Files to implement

| File | Purpose |
|---|---|
| `evals/synthetic/build_tasks.py` | Deterministically turn scene specs into prompts and `tasks.csv` |
| `evals/synthetic/validate_dataset.py` | Schema, file, dimensions, pair and provenance checks |
| `evals/synthetic/build_review.py` | Static human-review/contact-sheet artifact |
| `evals/synthetic/run_eval.py` | Run named off-the-shelf VLM configurations and cache raw output |
| `evals/synthetic/score.py` | Existing metric contract plus slices and paired comparisons |
| `evals/fixtures/synthetic-room-eval/README.md` | Dataset card and operator instructions |

Use the existing `evals/run_eval.py` scoring semantics where possible. Add a
new metric only when the current schema cannot express the decision.

## Risks and stopping rules

| Risk | Control / stopping rule |
|---|---|
| Prompt manifest is mistaken for observed truth | Two-pass review; labels cite visible frames |
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

- [ ] 25 matched four-view specifications and immutable packet splits committed.
- [ ] Exactly 100 accepted Gemini and 100 accepted ChatGPT Image 2 images, or
  an explicit terms/tooling decision explaining why the design changed.
- [ ] Every accepted image has exact prompt, provenance and human-observed
  labels.
- [ ] Defects and negatives are all double-checked.
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
