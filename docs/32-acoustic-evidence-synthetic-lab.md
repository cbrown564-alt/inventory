# 32 — Acoustic evidence and the synthetic audiovisual lab

*Written 3 Aug 2026. Implementation plan for the acoustic axis of the
synthetic evaluation dataset: extracting timestamped acoustic observations
from walkthrough video, generating controlled acoustic variations, and
building matched audiovisual delta pairs. This document owns the acoustic
axis. It does not fork docs/31, which continues to own the image dataset,
the splits, the review policy and the visual delta pairs in Phase 3.5.*

## Decision

Build the acoustic axis in three gated stages, in this order:

1. **A demux path**, so an uploaded walkthrough video's audio track exists as
   an artefact at all. Today `homeinventory/ingest.py` decodes with cv2, which
   discards audio entirely, and `homeinventory/audio_cues.py` consumes only
   hand-authored frozen transcripts. There is no acoustic evidence today —
   only a schema that could carry it.
2. **Adversarial spoken-label fixtures**, which test an attack surface that is
   already live in the product.
3. **Acoustic delta pairs**, which are only worth generating once 1 and 2 have
   told us whether acoustic observations survive contact with the pipeline.

Stage 2 comes before stage 3 deliberately. The generation work is the
expensive part and the least certain to transfer; the robustness work is cheap
and tests something shipping today.

**The governing constraint, inherited and non-negotiable:** an acoustic
observation is a timestamped observation for a human to review. It is never a
diagnosis, never a defect, and never a claim in a signed report. A running tap
in the audio track is evidence that a sound occurred at 4:12, not evidence
that a tap was left running. This is the same discipline `audio_cues.py`
already applies to narration — the transcript is research evidence and the
item describer never sees narration prose — extended to non-speech sound.

Synthetic acoustic results are development evidence. No synthetic acoustic
result promotes any product behaviour or any claim in a report. The docs/00
wall stands unchanged.

## Why this is worth doing now

Three reasons, in descending order of strength.

**There is a live, untested vulnerability.** `homeinventory/segment.py:161`
feeds `segmentation_hint(audio_cues, ...)` into the describer prompt intro,
and `homeinventory/curate.py:603` lets establishing cues promote a hero image.
Both are narration-derived and neither is checked against what the frames
show. If a speaker says "this is the kitchen" while standing in a utility
room, the current path has nothing that catches it. We have never tested this,
because every audio cue artefact in the repo was authored to be correct. A
misleading-spoken-label fixture set is the cheapest evidence we can buy about
a path that already ships.

**The compare surface has no acoustic ground truth and never will.** docs/31
already argues this for images: a real check-out set means waiting out a
tenancy. It is worse for sound, because nobody records a property's acoustic
state at check-in with the intent of comparing it later. If acoustic evidence
is ever going to be scorable, the fixtures have to be manufactured.

**The audio track is already being paid for and thrown away.** Every
walkthrough video the product ingests carries an audio track. Whatever the
verdict on acoustic evidence, we should know what is in it.

## What an acoustic observation is

The schema extension, mirroring the existing cue lists in `audio_cues.py`:

```json
{
  "source": {"video": "walkthrough.mp4", "fps": 30.0,
             "audio_sha256": "…", "sample_rate": 48000},
  "room_cues": [ … ],
  "establishing_cues": [ … ],
  "acoustic_cues": [
    {"t_s": 252.4, "duration_s": 3.1, "kind": "running_water",
     "confidence": 0.72, "frame_idx": 7572,
     "label_source": "detector", "detector": "<name>@<version>"}
  ]
}
```

Four rules the schema enforces, not conventions we hope to remember:

- `kind` is drawn from a **closed vocabulary** of sounds, never free text. The
  starting set: `running_water`, `appliance_hum`, `door_squeak`, `rattle`,
  `knock`, `alarm_tone`, `extractor_fan`, `unclassified`. A closed vocabulary
  is what stops an acoustic cue from becoming a sentence, and a sentence is
  one short step from a diagnosis.
- Every cue carries `confidence` and is **surfaced with it**, in the same way
  the existing cue loader rejects a confidence outside 0..1.
- Every cue resolves to a `frame_idx` via the existing `videometa` contract
  (`idx / fps`), so an acoustic observation is anchored to the same walkthrough
  timeline as a visual one. An acoustic cue that cannot be anchored is dropped,
  not floated.
- **No `kind` maps to a defect type.** There is no table anywhere in this plan
  that turns `running_water` into "tap left running". If such a table is ever
  wanted, it is a separate decision with its own evidence, not an
  implementation detail of this one.

`acoustic_cues` are **not** passed to the describer. The describer contract in
`audio_cues.py` — production consumers receive only small typed cue lists —
holds. Acoustic cues go to the review surface and to scoring; nothing else
reads them in v1.

## Stage A — demux and observe (ungated, cheap)

The prerequisite. No delta pair means anything until an acoustic observation
can be produced from a real file.

- [ ] Add `homeinventory/audio_track.py`: demux the audio track from an
      ingested video to a canonical mono 16 kHz WAV, hash it, and record
      `audio_sha256` and `sample_rate` in the ingest manifest. Missing or
      silent track is a normal outcome and must not fail ingest.
- [ ] Decide the demux dependency deliberately. cv2 cannot do this. `ffmpeg`
      as a subprocess is the low-friction option and is already a de facto
      presence on dev machines; `av` is a heavier but declarable dependency.
      **Recommendation: `ffmpeg` subprocess, feature-detected, with the whole
      acoustic path disabled and reported as unavailable when it is missing.**
      Do not make ingest depend on it.
- [ ] Extend `audio_cues.py` with an `acoustic_cues` list, validated on the
      four rules above, defaulting to empty so every existing frozen artefact
      still loads unchanged.
- [ ] Run demux across the existing real fixtures (`own-property`,
      `weststand`) and record, per file: track present, duration, whether
      speech is audible, and a hand-listened inventory of what non-speech
      sound is actually there.

**Exit:** a one-page record of what is in the audio of the walkthroughs we
already have. This is a real decision point. If the honest answer is "wind,
handling noise and the operator's own footsteps", the acoustic evidence axis
should be recorded as a negative result here, at a cost of roughly a day, and
stages B and C should not run.

## Stage B — misleading spoken-label fixtures (gated on A)

The adversarial set. This is the highest-value stage and the cheapest.

Six fixtures, each a short authored cue artefact paired with an existing
accepted image packet from the docs/31 development split:

| # | Fixture | What it tests |
|---|---|---|
| B1 | Spoken room name contradicts the visible room | Does `segmentation_hint` override what the frames show? |
| B2 | Spoken room name for a room that is not in the walkthrough at all | Does an invented room appear in the report? |
| B3 | Two rooms named in the same cue window | Does segmentation split on the wrong boundary? |
| B4 | Establishing cue pointing at a blurred or occluded frame | Does `_promote_audio_establishing` promote a bad hero over a good one? |
| B5 | Spoken defect claim ("there's a crack here") with no visible defect | Does a spoken claim reach the report as a finding? |
| B6 | Correct labels throughout | Control. Confirms the fixtures measure interference, not noise. |

Method:

- [ ] Author the six cue artefacts by hand against packets whose visible
      content is already gold under docs/31's review policy. Hand-authored is
      correct here — these are adversarial constructions, not samples.
- [ ] Run each packet twice: once with `--audio-segment-cues` /
      `--audio-hero-cues` off, once on. The off-run is the control.
- [ ] Score the delta between runs, not the absolute output.

Metrics:

- **label capture rate** — fraction of fixtures where the misleading spoken
  label appears in the output as a room name, a hero choice or a finding.
  This is the headline number.
- **spoken-claim leakage** (B5) — whether a spoken defect claim reaches a
  report finding. This one has a hard bar: **any leakage at all is a defect
  to fix, not a metric to track.** The describer is contractually not supposed
  to see narration prose; if a spoken claim surfaces, the contract is broken
  somewhere.
- **control stability** (B6) — cue-on and cue-off agree.

**Exit:** a measured statement of how much a wrong voice can bend the output,
and a fix for anything B5 turns up. No generation credits are spent in this
stage.

## Stage C — acoustic and audiovisual delta pairs (gated on A and B)

Only run this if stage A found real acoustic content and stage B did not
uncover a structural problem that has to be fixed first.

This stage extends docs/31 Phase 3.5 rather than restating it. **Everything in
Phase 3.5 applies unchanged**: the `delta_of` / `changes` /
`unchanged_assertions` schema, two views per timepoint, split inheritance, the
Pass A / Pass B review path, and the rule that any unenumerated material
difference rejects the pair. Read that section first; this one only adds the
acoustic dimension.

### The acoustic delta schema extension

```json
{
  "delta_of": "RP-004",
  "timepoint": "T1",
  "changes": [
    {"id": "D1", "kind": "new_defect", "target": "carpet by the radiator",
     "description": "dark stain roughly 15cm across", "material": true,
     "modality": "visual"},
    {"id": "D2", "kind": "acoustic_present", "target": "extractor fan",
     "description": "rattling fan audible for ~4s from 0:12",
     "material": true, "modality": "acoustic",
     "acoustic_kind": "rattle", "t_s": 12.0, "duration_s": 4.0}
  ],
  "unchanged_assertions": [
    "same units, worktop, flooring and appliance positions",
    "no change to any other audible sound in the clip"
  ]
}
```

The last assertion is what makes the acoustic side scorable. Without an
explicit "nothing else audible changed", a generated background difference is
indistinguishable from a real acoustic change, and the false-change metric is
meaningless — exactly the argument docs/31 makes for the visual case.

### Pair composition

Five pairs, matching the concept's scope. Deliberately stratified so the
acoustic axis is isolated:

| Pair | Visual | Acoustic | Isolates |
|---|---|---|---|
| C1 | unchanged | one sound added | Acoustic sensitivity with no visual support |
| C2 | one defect added | unchanged | Acoustic false-alarm under visual change |
| C3 | one defect added | matching sound added | Do the two modalities corroborate or double-count? |
| C4 | one defect added | *contradicting* sound added | Which modality wins in a conflict |
| C5 | unchanged | unchanged | Control. Both channels should be silent. |

C4 is the interesting one and the reason this is research rather than
feature work. A pipeline that resolves modality conflict by quietly picking
one is worse than one that reports both, because in an adjudication the
disagreement *is* the evidence.

### Acoustic generation

- [ ] Generate acoustic variations as isolated sound events (ElevenLabs sound
      effects), then mix into the clip at a fixed, recorded gain and offset.
      **Generate the event, not the scene.** A generated full-room soundscape
      cannot be asserted unchanged between renders, which fails the
      `unchanged_assertions` requirement before scoring starts.
- [ ] Record for every mixed event: source asset hash, gain, offset, and the
      mix command. A pair is reproducible from its manifest or it is not gold.
- [ ] Quarantine every synthetic acoustic asset under
      `evals/fixtures/synthetic-room-eval/audio/`, with the same provenance
      discipline as generated images. No synthetic audio asset may reach a
      signed report path, ever.

### Feasibility probe (gate), mirroring Phase 3.5

- [ ] Build C1, C3 and C5 only.
- [ ] Independent review records, per pair: (a) is the enumerated sound
      audible, (b) is every other audible element unchanged, (c) does the
      mixed clip sound like a phone recording in a room or like a sound
      effect over silence.
- [ ] Owner adjudicates all three.

**Pass:** all three pairs hold their unchanged assertion, and the reviewer
does not identify the mixed event as obviously synthetic in ≥2 of 3.

**Fail:** record the drift or realism mode observed and abandon the acoustic
delta extension as a negative result. Do not loosen the realism bar — an
acoustic set that only works on obviously-synthetic sound measures the
detector's ability to spot sound effects, which is not a question anyone
asked.

### Metrics

Reported in their own table, never merged with image or visual-delta metrics:

- **acoustic recall** — enumerated acoustic changes observed;
- **acoustic false-change rate** — reported acoustic observations with no
  enumerated counterpart. Headline, for the same reason as the visual case;
- **modality conflict behaviour** (C4) — reports both / picks visual / picks
  acoustic / silent. Reported as a category, not a score. There is no correct
  answer yet, which is the point of measuring it;
- **anchor accuracy** — cue `t_s` within tolerance of the enumerated event.

## Boundaries

- Acoustic cues are observations. Nothing in this plan converts a sound into
  a defect, a severity or a report finding.
- Synthetic acoustic assets never leave the eval fixtures tree.
- Do not train on any of this. docs/31's out-of-scope rule is unchanged.
- Never present a synthetic acoustic delta as a real tenancy comparison.
- The describer contract holds: narration prose does not reach the item
  describer, and `acoustic_cues` do not either.

## Risks and stopping rules

| Risk | Control / stopping rule |
|---|---|
| Real walkthrough audio contains nothing but handling noise | Stage A exits with a negative result before any credits are spent |
| Synthetic sound does not transfer to phone-recorded room acoustics | Realism check in the probe; this is the headline transfer risk and must be stated in every report — a mixed event has no reverb, no AGC and no mic colouration |
| An acoustic cue is read as a diagnosis | Closed `kind` vocabulary, confidence always surfaced, no sound-to-defect mapping anywhere in the codebase |
| Spoken claims leak into report findings | Stage B5; any leakage is a bug with a fix, not a tracked metric |
| Acoustic delta gold mistaken for real compare evidence | Separate metric table; compare promotion stays gated on real check-in/check-out evidence (docs/08) |
| ffmpeg unavailable in an environment | Feature-detect; acoustic path reports unavailable and the rest of ingest is untouched |
| Scope creeps into a live speaking capture guide | That is docs/33, explicitly a research prototype, explicitly not on the v1 path |

## Definition of done

- [ ] Audio tracks demux, hash and anchor to the walkthrough timeline.
- [ ] `acoustic_cues` validated by `audio_cues.py` on the four schema rules.
- [ ] A recorded inventory of what is actually in existing fixture audio.
- [ ] Six adversarial spoken-label fixtures built and scored, with any B5
      leakage fixed.
- [ ] Either a scored five-pair audiovisual delta set with its own metric
      table, or a recorded negative result naming the mode that defeated it.
- [ ] Every synthetic acoustic asset reproducible from its manifest.

## Related owners

- `docs/31-synthetic-evaluation-dataset-plan.md` — owns the image dataset,
  splits, review policy and visual delta pairs. This document does not
  duplicate or override any of it.
- `docs/00-north-star.md` — real-property v1 success criteria; unchanged.
- `docs/08-compare.md` — the compare product surface.
- `docs/12-video-first-journey.md` — product plan of record.
- `docs/33-speaking-capture-guide.md` — the research prototype on the
  generative side of the same idea.
- `homeinventory/audio_cues.py` — existing cue contract and describer boundary.
