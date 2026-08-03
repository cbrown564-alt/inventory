# 34 — Synthetic video probe (Phase 3.6)

*3 Aug 2026. The image pilot in docs/31 built ground truth for a product whose
primary capture format is **video** (docs/12). Every scored artefact in it is a
still. Gemini Omni can now generate video at ten clips a day, and nine
scenarios already hold a complete four-view Omni packet whose contents are
enumerated and reviewed. That makes it possible to manufacture walkthrough
footage whose contents are known before the pipeline sees it. This document
specifies five use cases, their exact prompts, and the wall around what they
can conclude. Authority: tier 5 (research / spike). Extends docs/31; feeds
docs/26, docs/11, docs/18, docs/33.*

## What this probe is for

The pipeline's inputs are frames extracted from video. Its ground truth is
photographs. Everything the project knows about accuracy has been measured on
artefacts one step removed from what the product actually consumes, and every
video-specific failure docs/26 lists — boundary bleed, a hero that is a
close-up of a hand, motion blur, hallucination from low-resolution extracted
frames — is invisible to a still-image dataset by construction.

Synthetic video closes exactly one gap: it supplies footage with an enumerated
content list, a pinned room identity, and a known camera path. It does not
close the gap to real capture, and nothing here should be read as if it did.

## The wall

Unchanged from docs/00 and docs/31, restated because video makes it easier to
forget:

- Synthetic video is **development evidence**. No result promotes a
  capture-strategy claim, a compare claim, or a product accuracy number.
- docs/26 still resolves photo-vs-video **on real capture**. This probe informs
  that experiment's design; it does not pre-empt its verdict.
- Gemini Omni is the same provider as the parent dataset's Google image arm.
  Any comparison across them is a **service** comparison inside one provider.
- Never present a synthetic clip as a real walkthrough.

### One-way tests

Four of the five use cases are **falsification-only**, and the specs say so in
a machine-readable field. The footage is clean, evenly lit, correctly framed
and moves at whatever speed it was told to. That is a best case. A failure on
a best case transfers to real capture; a pass does not.

VU-5 is the exception. It scores two clips of the *same room under the same
light* where the only difference is whether the occluded rear was ever in
frame. A claim about the rear in the clip that never saw it is a hallucination
by construction — no resemblance to real footage is required for that to hold.
It is the only use case here that can produce a positive finding, which is why
it is in the first day's batch.

## The five use cases

Specs live in `evals/fixtures/synthetic-room-eval/video/clips/VU-*.json`.
Prompts are composed by `evals/synthetic/build_video_tasks.py` from the parent
scenario plus the clip, so the video arm inherits the image arm's
evidence/defect/negative-control clauses verbatim, and each prompt is
content-addressed the same way an image task's is.

| ID | Use case | Question | Clips | Feeds |
|---|---|---|---|---|
| VU-1 | Extraction fidelity | Does the video path recover what the still path recovers, on footage whose contents are known exactly? | RP-003 kitchen (pivot), RP-024 office (dolly-in) | docs/26, docs/18 |
| VU-2 | Room boundary | Can the segmenter place a boundary whose true frame is known? | RP-014 hall → kitchen transit | docs/11 |
| VU-3 | Narrated cue | Does one spoken room-name cue move any metric? | RP-021 stairs, narrated | docs/11, docs/33 |
| VU-4 | Motion-quality ladder | Where does sweep speed break hero selection and item recall? | RP-022 WC × slow / ordinary / hurried | docs/18, docs/22 |
| VU-5 | Occlusion counterfactual | Does the describer confine claims to what the camera saw? | RP-019 cupboard × push-in / hold | docs/00, docs/29 |

Design decisions worth stating:

**Every clip is conditioned on an accepted still, pinned by SHA-256.** Room
identity is what drifts. The parent pilot rejected 36% of first attempts across
four *static* views; a moving camera has strictly more drift surface. Identity
is anchored to an artefact, never to prose.

**VU-1 runs two camera paths, not one.** A standing pivot and a forward walk
degrade extraction differently, and the pair isolates which. Both are scored
against the union of their scenario's four accepted stills, under the same
Pass B labels — so the still arm is the baseline, not an external number.

**VU-2 cannot score kitchen items.** Omni takes one reference frame. The
hallway is pinned to RP-014; the kitchen beyond the door is an identity the
model invents and is *not* the RP-003 packet. Score room naming and boundary
timing only. The clip deliberately crosses a warm-ceiling-light hall into cool
daylight, which is the strongest boundary cue that exists: this is the easy
case, so a miss is decisive and a hit is weak.

**VU-3 needs one generation, not two.** Generate narrated, then strip the audio
track with `ffmpeg` to produce S0. The footage is byte-identical between arms —
a cleaner control than two renders could ever be. It costs one clip of the
daily budget, not two.

**VU-4 varies one thing.** Same scenario, reference frame, path, evidence,
lighting and duration; only speed changes. If a rung traverses less of the room
than its neighbours it is not a slower rung, it is a different clip, and the
ladder is void.

**VU-5 is a matched pair with unchanged-assertions**, borrowed directly from
the Phase 3.5 delta-pair contract. The pair is the evidence; a single surviving
clip is worth nothing on its own.

## Budget: 10 clips a day

Generation runs on the owner's Gemini Omni subscription surface. The parent
dataset's `api_calls_permitted: false` restriction is inherited and unchanged —
no metered endpoint. The daily ceiling includes retries.

**Day 1 — feasibility (5 clips + 5 retry slots).** The three failure modes that
would end this before any scoring are: identity drift under motion, geometry
incoherence through a doorway, and the model ignoring a negative camera
instruction. Day 1 generates only the clips that test those:

| Slot | Clip | What its failure would prove |
|---|---|---|
| 1 | `VU-1.RP-003` | Omni cannot hold a room's identity through a pivot → the whole probe is void |
| 2 | `VU-2.RP-014-transit` | Geometry breaks at a threshold → no boundary work is possible |
| 3 | `VU-3.RP-021-narrated` | Speech and camera cannot be controlled together → the audio ablation is dead |
| 4 | `VU-5.RP-019-push` | The reveal never happens → the counterfactual has no positive arm |
| 5 | `VU-5.RP-019-hold` | "Never visible in any frame" is not honoured → the counterfactual has no control arm |

Five retry slots is not generosity, it is the parent pilot's observed
first-attempt rejection rate applied honestly.

**Day 2 — scale (conditional).** `VU-1.RP-024`, the three `VU-4` rungs, and the
`VU-5` scale-up onto RP-023. Only for use cases whose day-1 clip was accepted.
A use case that failed day 1 is recorded as a negative result and not retried
into existence.

## Acceptance

Nine criteria in `video/dataset.json`, inheriting the parent's review policy.
The additions that only apply to video:

- Pass A samples frames at 1 fps **plus every declared gold timestamp**;
  continuity is judged across the strip, not on one frame.
- Geometry must stay coherent *through* motion — no furniture sliding, no
  doorway changing position, no room growing. This is the failure mode a static
  review cannot catch.
- Audio must match the declared mode exactly, **including the silent case**. A
  clip that invents music or footsteps is rejected.
- An accepted clip records the sampled strip's hash alongside the clip hash.

Gold timestamps — VU-2's boundary, VU-3's cue — are read **from the delivered
file**, never assumed from the requested duration. Requested and delivered
timing are different things and treating them as one would silently corrupt the
only metric those two clips have.

## What this does not do

- It does not produce a multi-room walkthrough. VU-2 crosses one threshold; a
  ten-room video is out of reach at this clip length and would compound drift
  past any usable gold.
- It does not test capture *UX*. Nobody is holding the phone.
- It does not touch training. The parent dataset's out-of-scope rule stands:
  no synthetic artefact trains, fine-tunes or distils weights.
- It does not unblock Phase 4 or Phase 5. Those remain dependency-blocked on a
  validation winner in the image arm.

## Related

- `docs/31-synthetic-evaluation-dataset-plan.md` — parent dataset, Phase 3.5
  delta pairs, the review and gold contract this inherits.
- `docs/26-capture-strategy-experiment.md` — the real photo-vs-video experiment
  this informs and does not replace.
- `docs/11-video-segmentation.md` — segmentation and the S0/S1 audio ablation.
- `docs/18-hero-image-selection.md` — hero selection and IQA, VU-4's consumer.
- `docs/33-speaking-capture-guide.md` — the guide with no product surface; VU-5
  bounds what one could ever be worth.
