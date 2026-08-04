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

## Two gates from docs/31 Amendment B

Amendment B landed the same day as this document and governs where the two
conflict. It changes two things here, and neither is cosmetic.

**1. The reference frames have no recorded provenance.** The 57 Gemini Omni
stills are not in the parent `tasks.csv` at all — zero rows. They have owner
review, which Amendment B states plainly "is not the recorded protocol". Their
Pass A import is **item 6 of the B work order, named there in advance as the
droppable item** if the schedule slips.

So this probe is gated on the one piece of work most likely to be cut, and
every clip generated before that import rests its ground truth on an unrecorded
protocol — the exact thing docs/31 forbids. `build_video_tasks.py` therefore
refuses to write the queue unless `--allow-unimported-reference` is passed, and
stamps `reference_provenance` on every row so an ungated queue cannot be
mistaken for a gated one later.

The honest options are: run the Omni Pass A import first, or run day 1 as an
explicitly ungated **feasibility** probe whose only question is "can Omni hold a
room through motion at all" — a question that does not need gold, because its
answers are "yes" and "no". Day 2 onward produces numbers, and numbers need the
import. Recommendation: day 1 ungated, everything after it gated.

**2. The whole thing is unpublishable.** B9 excludes the entire Google arm from
publication and from any future training corpus on terms grounds — UK Google
consumer terms prohibit using output to develop "machine-learning models or
related AI technology". Gemini Omni video inherits that without exception. This
probe can inform internal design decisions and nothing else.

**Related: VU-4 has a cheaper competitor.** Amendment B already adopts a
deterministic **degradation ladder** — motion blur, downscale-and-reupscale,
JPEG compression, off-axis crop applied to already-accepted stills, with labels
inherited unchanged, no quota, no Pass B, no terms question. That is strictly
cheaper than VU-4 and should run first. VU-4's remaining justification is
narrow but real: the ladder degrades frames *independently*, whereas rendered
camera motion produces blur that is temporally coherent across a sequence — and
a sequence is what `curate.py` actually chooses among. Run the free ladder
first; run VU-4 only if the ladder's answer looks like it depends on that
difference.

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

**Every clip is conditioned on one still, pinned by SHA-256.** Room
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

**Day 2 — scale (conditional, and gated).** `VU-1.RP-024` and the `VU-5`
scale-up onto RP-023, only for use cases whose day-1 clip was accepted. A use
case that failed day 1 is recorded as a negative result and not retried into
existence. Day 2 produces numbers rather than yes/no answers, so it does not
start until the Omni Pass A import has landed.

The three `VU-4` rungs are **not** on day 2. They sit behind Amendment B's free
degradation ladder, for the reason given above.

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
- It does not touch training, and cannot. The parent out-of-scope rule stands,
  and B9 adds a terms-grounds prohibition on top of it.
- It does not produce anything publishable. See gate 2.
- It does not unblock Phase 4 or Phase 5. Those remain dependency-blocked on a
  validation winner in the image arm.

## Day 1 result — 4 Aug 2026

*The batch was generated on the owner's Omni subscription surface, staged,
hashed, sampled and reviewed. Machine-readable record:
`video/reports/phase36-video-pass-a-review-2026-08-04.json`. Nothing below
promotes a capture-strategy claim; the wall above is unchanged.*

Nine clips were queued and eight delivered. `VU-4.RP-022-hurried` was rejected
on sight for unstable scene physics and hallucinated content and was never
downloaded. **All eight delivered clips were rejected at Pass A**, by two
independent reviewers.

### The batch is void, and not because of the generator

Every clip is conditioned on the still named `<scenario>-A-wide.jpeg`, which
the scene specifications define as a *wide establishing view*. None of them is
one. `RP-003-A-wide.jpeg` is a close shot of a worktop and splashback,
`RP-024-A-wide.jpeg` a desk corner, `RP-014-A-wide.jpeg` the foot of a front
door, `RP-022-A-wide.jpeg` the base of a WC.

The cause is `stage_gemini_omni_prior_batches.py`, which assigns
`A-wide, B-reverse, C-inventory, D-condition` **positionally**, in whatever
order the operator supplied four files, and never checks that position 0 holds
a wide view. The supplied order was the reverse. Gemini names its downloads
from the prompt, so the files state their own contents:

- Four filenames name a view id outright. All four contradict the id they were
  filed under, all four fit an exactly reversed order, none contradicts it.
  Two of them literally read `View_D-condition…` and are filed as `A-wide`.
- Across all nine packets, the file filed as `A-wide` describes a condition
  detail — a splashback edge, a door's lower panel, a stair tread edge, a WC
  base, a desk surface, a floor. Five say "condition" in the filename.

`evals/synthetic/audit_gemini_omni_views.py` reports this mechanically and
scopes it: the 36 stills staged through the positional route are suspect; the
21 staged through `import_gemini_omni_batch.py`, which names a view per file,
show no contradiction. Every Phase 3.6 reference frame comes from the affected
route.

So each prompt carried an instruction pair it could not satisfy — *"the
supplied reference image is the opening frame: match it exactly, then move
from it"* alongside *"start on the reference framing at the doorway and pivot
across the whole cloakroom"*. Given a floor-level close-up and told to open at
a doorway, the generator invented a wide opening, and both reviewers recorded
that the opening frame does not match the reference. That is the most common
hard failure in the run, and it is an artefact of the fixture, not a
measurement of the model.

**Day 1 therefore does not answer "can Omni hold a room through motion".** It
is not a negative result about the generator and must not be recorded as one.

**This is exactly the harm the provenance gate named in advance.** The gate is
open because the Omni stills have no recorded Pass A — and Pass A is precisely
where "is this the view it claims to be" is caught. docs/31 Amendment B lists
that import as work order item 6, "named there in advance as the droppable
item". It is not droppable. It is the prerequisite, and the recommendation in
this document's gate 1 — "day 1 ungated, everything after it gated" — was
wrong: ungated day-1 generation bought nothing and cost nine clips.

### What the run found anyway

These do not depend on which frame was the reference:

- **Readable brands in 6 of 8 clips** — Apple, Samsung, Beko, Fairy, and
  legible cleaning-product labels — against an avoid list that names logos and
  readable text explicitly. On the product's own evidence rules a readable
  brand in a walkthrough frame is a problem in its own right.
- **Geometry breaks mid-take with no cut.** `VU-1.RP-003`'s floor changes from
  wood-plank LVT to stone-look tile between sampled frames 4 and 7 and its
  cabinetry morphs between frames 3 and 4; `VU-1.RP-024`'s desk moves from the
  left wall to the window wall between frames 7 and 8; `VU-2`'s closed door
  becomes an open doorway between frames 4 and 5. The unbroken-take check
  passes mechanically on every clip, so these are drift, not edits. This is the
  failure mode a still-image dataset cannot see, and it is the one thing here
  worth carrying forward — though a contradictory prompt is itself a plausible
  cause of instability, so it is a lead, not a measurement.
- **`VU-5.RP-019-hold` breaches its own must-never-be-visible list.** The
  primary reviewer places the rear floor and lower rear wall in frames 7, 9 and
  10; the second recorded no breach; independent inspection agrees with the
  primary, since the camera plainly advances past the doorway it was told to
  hold. The counterfactual pair has no valid control arm, which is day 1's
  slot-5 failure as written.
- **6 of 7 silent clips carry audible audio**, peaking between −41 and
  −22 dBFS in discrete bursts rather than stationary room tone, against a
  prompt asking for no speech, music, sound effects or room tone.
- **`VU-4.RP-022-slow` ends on an almost entirely black frame.**

One partial positive: `VU-2` room naming worked — both reviewers named
Entrance hall then Kitchen. Their boundary brackets disagree by two seconds
(frame 7 versus 9), which is the resolution limit of a 1 fps strip rather than
a segmentation result.

### What has to happen next

1. ~~**Correct the Omni view assignment and run the Pass A import**~~ —
   **done, 4 Aug 2026.** `repair_gemini_omni_views.py` re-filed the 36
   prior-batch stills under their true view ids (a rename; the manifest carries
   the same digest on both sides), and `import_gemini_omni_pass_a.py` gave all
   57 candidates ledger rows. The audit now reports zero contradictions where
   it reported four, and the `A-wide` slot reads
   `Kitchen_photograph_refurbished`, `WC_in_small_cloakroom`,
   `Home_office_in_UK_flat`. The eight rejected clips are archived through
   `reject_video_clip.py` with their Pass A reasons, so the queue is
   `retry_pending` against corrected references and the artefacts and verdicts
   both survive.
2. ~~**Adjudicate three reference frames.**~~ **Done, 4 Aug 2026.** `RP-003`,
   `RP-019` and `RP-024` `A-wide` are accepted by owner adjudication
   (`reports/omni-reference-frame-adjudications-2026-08-04.json`), joining
   `RP-014` and `RP-021`. The reasoning: each frame is used *alone* to pin room
   identity for one clip, not as part of a scored four-view packet, so the
   packet-continuity objection that split the reviewers does not bear on this
   use. **Six of nine clips now hold an accepted reference and are clear to
   regenerate**; `build_video_tasks` reports which, and refuses the rest by
   name.
3. **`VU-4` is dead on `RP-022`.** Both reviewers rejected that `A-wide`: the
   scenario requires a *corner* basin and the candidate has a flat wall-hung
   one, so the still contradicts the specification it was generated from. There
   is no usable reference frame, and no amount of regeneration fixes a
   reference. Either re-specify the use case onto another WC scenario or drop
   it — and it was already behind Amendment B's free degradation ladder, which
   remains the cheaper answer to the same question.
4. **Regenerate day 1 against accepted references only**, and keep it to the
   five specified clips. The rule is now enforceable: a clip may only be
   conditioned on a still whose ledger row is `pass_a_accepted`.
5. **Strip audio from silent-mode clips at staging**, or accept the deviation
   explicitly. It is free to fix with `ffmpeg -an` and it is currently an
   automatic escalation on every silent clip.

## Related

- `docs/31-synthetic-evaluation-dataset-plan.md` — parent dataset, Phase 3.5
  delta pairs, the review and gold contract this inherits.
- `docs/26-capture-strategy-experiment.md` — the real photo-vs-video experiment
  this informs and does not replace.
- `docs/11-video-segmentation.md` — segmentation and the S0/S1 audio ablation.
- `docs/18-hero-image-selection.md` — hero selection and IQA, VU-4's consumer.
- `docs/33-speaking-capture-guide.md` — the guide with no product surface; VU-5
  bounds what one could ever be worth.
