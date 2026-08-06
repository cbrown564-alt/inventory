# 35 — Describe stability: the same room, described twice

*5 Aug 2026. Scoped off the Phase 3.5 delta scoring (docs/31). Phase 0 measured
6 Aug 2026: **the floor is 91.3% of the 368**. Gate passed; phases proceed.*

## Decision

Two independent describe runs of the same room disagree about what is in it,
and that disagreement — not the compare aligner, and not the model's ability to
see change — is the dominant term in the compare surface's error. Attack it
next.

The claim is measured, not inferred. Scoring the 27 accepted delta pairs put
`compare_inventories` against known ground truth for the first time
(`reports/phase35-delta-score-2026-08-05.json`):

| | |
|---|---:|
| Reported changes | 407 |
| With no counterpart in gold | **368 (90.4%)** |
| Material gold changes | 139 |
| Detected | **37 (26.6%)** |

Nine in ten reported changes are invented. docs/31 calls that the failure that
matters most, because a compare feature that invents change converts the
landlord's evidence into the tenant's.

## What the 368 false changes actually are

The aligner was the first suspect and has been dealt with: `match_score` gained
a positional-modifier tier on 5 Aug (docs/08 §1 update), worth 17 fewer false
changes at no cost to recall. What remains is not an alignment problem.

| Bucket | Count | What it is |
|---|---:|---|
| Rename pairs | 138 | One object reported twice, the two runs naming it differently (69 pairs) |
| Unpaired additions | 86 | T1 listed an item T0 never mentioned |
| Unpaired removals | 71 | T0 listed an item T1 never mentioned |
| Reported as changed | 73 | Aligned, but graded differently across the two runs |

Every one of these is the *description* moving, not the room. Those 138 entries
are 69 rename pairs: tier 1 resolved 8 of the 77 these fixtures carry, and what
survives is true synonymy that no token rule reaches — `Heated towel rail`
against `Towel radiator`, `Framed picture` against `Framed artwork`,
`Decorative dish` against `Decorative bowl`, `TV stand` against `TV cabinet`,
`Media devices` against `Media equipment`.

The same instability explains the recall side. Of the 77 missed condition
changes:

| Fate | Count |
|---|---:|
| Neither run ever named the object | **43** |
| The aligner split the object | 17 |
| Tracked correctly, change unreported | 17 |

An object absent from the schedule cannot carry a delta. The single largest
cause of missed condition changes is that the item was never listed at all.

## The three faces, and why they are one problem

1. **Coverage** — the item is not listed. 43 missed condition changes.
2. **Membership stability** — the item is listed in one run and not the other.
   157 unpaired entries.
3. **Naming stability** — the item is listed in both runs under names that do
   not align. 138 entries.

All three are the describe step producing a different schedule from the same
evidence. Fixing compare cannot reach any of them.

## What we do not know yet, and must measure first

**The delta pairs cannot separate noise from signal.** T0 and T1 are
*different photographs* — a different render of the same room. When T1 omits
the toaster T0 listed, three explanations are live and the current data cannot
distinguish them:

- the describe run is non-deterministic and simply missed it;
- the T1 framing genuinely does not show it;
- the generator drifted and the toaster is really gone (which the Amendment C
  review would have recorded as incidental drift, not always as gold).

Every number above is therefore an **upper bound on instability**, inflated by
an unknown amount of legitimate difference. Building interventions before
separating these would be optimising against a number nobody can interpret.

### Instrument 0 — the repeat-describe control (gate)

Describe **the identical frame set twice** and compare the two runs with
`compare_inventories`. There is no room change, no framing change and no
generator drift: every reported change is pure non-determinism. That is the
noise floor, and it is the denominator every later claim needs.

- Reuse `run_delta_eval.py`'s machinery with both sides pointed at the same
  frames. No new generation, no new fixtures.
- 27 pairs × 1 extra call ≈ 27 describe calls, subscription-backed Antigravity,
  no metered endpoint.
- Report the same decomposition: rename pairs, unpaired additions, unpaired
  removals, changed-bucket disagreement.

**Gate.** If the floor is near zero, the 368 is dominated by real perceptual
difference between two renders and this whole document is mis-aimed — stop and
re-scope. If the floor is a substantial fraction of 368, the problem is
confirmed as non-determinism and the phases below proceed. State the fraction
before proposing any fix.

A second control worth the same run: describe one frame set twice **with the
schema's `quantity` and `photo_ids` fields compared too**, because a schedule
that is stable in names and unstable in counts is a different defect with a
different fix.

## Phase 0 result, 6 Aug 2026 — the floor is nearly the whole number

Instrument 0 ran on all 27 accepted pairs: the cached T0 describe as one run
and one more call against byte-identical frames, hashes checked equal on both
sides (`reports/phase0-describe-stability-2026-08-06.json`).

**Describing the same photographs twice reported 336 changes. The delta pairs'
false changes number 368. The floor is 91.3% of them.**

The gate above asked for the fraction before any fix is proposed. That is the
fraction, and it is not close to the boundary. But the fraction is only the
headline; the decomposition is the part that decides what to build.

| | Repeat-describe control | Delta pairs |
|---|---:|---:|
| Schedule agreement, exact names | 34.6% | 32.4% |
| Schedule agreement, normalised | 37.3% | 35.2% |
| Membership churn per room | 10.7 | 12.0 |
| Naming churn per room | 4.26 | 4.22 |
| Condition agreement | 81.7% | 74.3% |
| Cleanliness agreement | 80.7% | 70.1% |
| Quantity agreement | 96.1% | 94.4% |
| Coverage against scene specs | 58.5% / 57.7% | 58.5% / 56.4% |
| Coverage stability | 77.8% | 77.0% |

**The two columns are almost the same column.** That is the finding, and it is
stronger than the 91.3%. Two describes of one photograph disagree about the
room's contents very nearly as much as two describes of *different
photographs of a changed room*. Going from "the same frames" to "a different
render, months later, with five enumerated changes in it" adds 1.3 unpaired
items per room and takes naming churn slightly *down*. The delta signal this
dataset was built to measure is inside the noise, not above it.

Two things this control moves from suspicion to evidence:

**Synonymy is the mechanism, and it is not the aligner's fault.** The 115
renames the control's aligner still caught are `Electric oven`/`Oven`,
`Pedestal wash basin`/`Pedestal basin`, `Vinyl flooring`/`Flooring`,
`Walls (painted areas)`/`Walls`. The 289 it did not catch are the same
phenomenon past the point `match_score` can reach — `Extractor hood`/`Cooker
hood`, `Trash bin`/`Waste bin`, `Paper towel holder`/`Kitchen Roll Holder`,
`Backsplash tiling`/`Wall tiles`, `Washing-up rack`/`Dish Drainer and Washing
Up Items`. Every one of those pairs is one object, in one photograph, named
twice. docs/08's no-synonyms premise was falsified on the delta pairs; this
removes the last defence that some of it was real change.

**Coverage is a flat gap, not an instability.** 81 of 234
`intended_visible_items` were named by *neither* run — carpets, WCs, base
units, French doors, sofas. Coverage stability is 77.8%, so the runs mostly
agree about what they omit. That third of the problem is not noise and no
sampling control will touch it; it is arms C and D.

### What the headline number leaves out

336 counts only what a reader is shown, and `needs_classification` shows an
item only when it got **worse** or gained a defect. 116 of 389 aligned items
were graded differently by the two runs and **76 of those were never
reported**: a second run that grades the room *better* passes through compare
in silence. P35-002 does this wholesale — 14 of 17 aligned items move
`good`→`excellent` and `cleaned to domestic standard`→`professionally
cleaned`, and compare reports one change.

So the floor is itself a floor. This is not an argument for widening the gate
— an improvement is rarely what a deposit turns on, and reporting every one
would bury the report. It is a reason the compare surface cannot be used to
measure describe stability, which is why the metric list above does not
depend on it.

### Gate decision

**Proceed.** The floor is a substantial fraction of the 368 by any reading, so
the stopping rule "the floor turns out to be small" does not fire and the
problem is confirmed as description instability rather than perceptual
difference between two renders.

Two honest limits on that decision:

- 336 against 368 is a comparison of *magnitudes*, not an attribution. It does
  not establish that the control's 336 are among the delta pairs' 368. Phase 1
  is what establishes that, and it is now better motivated, not skippable.
- The near-identity of the two columns is the load-bearing evidence, and it
  rests on 27 pairs from one generator. It is directional. Real transfer
  (Phase 5) is unchanged and still binding.

One consequence for the running order. **Arm E stops being a formality.** If
two calls with identical inputs disagree this much, sampling is a first-order
suspect rather than a cheap thing to rule out, and the roadmap has been
ordering arms A–D on the assumption that it is not. Antigravity still does not
expose temperature, so it is still not testable on this path — that now needs
recording as a *blocking* gap in the evidence rather than a checkbox, because
every other arm here is being designed against a cause nobody has excluded.

## Metrics

Reported per run-pair and pooled, on the repeat-describe control and on the
delta pairs separately — the two mean different things and must never be
averaged together.

- **schedule agreement** — items reported by both runs over items reported by
  either. The headline. Independent of any aligner, computed on normalised
  names *and* on exact names, so naming instability is visible separately from
  membership instability.
- **membership churn** — unpaired additions plus unpaired removals per room.
- **naming churn** — aligned items whose names differ.
- **grade agreement** — condition and cleanliness identical across runs for
  aligned items; and within-one, since the grade scale is ordinal.
- **coverage against scene specs** — items in `intended_visible_items` that the
  schedule names. The synthetic scenarios carry this per view already and it is
  currently unexploited for delta work.
- **quantity agreement** — same item, same count.

Existing metrics that must not regress: `score.py`'s item recall against
reviewed gold, defect recall, and the Phase 3.5 delta recall by kind.

## Interventions, in the order they should be tried

Ordered by expected leverage per unit of risk, not by novelty. Each is a
separate arm and each is measured on the same 27 pairs *and* the repeat-
describe control.

### A. Name normalisation against a controlled vocabulary (cheap, low risk)

Describe freely, then map every name onto a household lexicon before the
schedule is written. Attacks naming churn at its source rather than asking the
aligner to be cleverer — `Towel radiator` and `Heated towel rail` both resolve
to one entry. This is the intervention the aligner fix could not reach, and it
is the one docs/08 has been implicitly deferring by treating synonymy as an
alignment problem.

Phase 0 promoted this from the most likely explanation to the measured one.
The synonym pairs listed above are drawn from the *control*, where both runs
read the same photograph, so there is no longer any reading in which
`Extractor hood` and `Cooker hood` are two objects. It also sized the arm: 115
renames the aligner catches and 289 unpaired entries it does not, across 27
rooms.

Risks: a lexicon is a maintenance surface, and an aggressive mapping merges
genuinely distinct items. Guard with the delta gold — `item_added` and
`item_removed` recall must not fall.

### B. Check-in-conditioned check-out describe (high leverage, highest risk)

Give the T1 describe the T0 schedule as a checklist to confirm, deny or amend,
instead of describing from scratch. This collapses naming churn to zero by
construction — the same names are reused — and directly targets membership
churn, because the model is asked about each prior item rather than
re-enumerating freely.

**This changes the architecture**, from "describe twice independently, then
align" to "describe once, then verify against the prior". docs/08's alignment
section and the `merge_room_with_prior` path both bear on it; note that the
existing prior-merge is for re-describing the *same* capture while preserving
reviewer edits, and is not this.

**The anchoring trap, which is why this is not tried first.** A model handed a
list of items and asked "are these still here" will confirm items that are
gone. That failure is *worse* than the one it fixes: it converts an invented
change into a suppressed one, and a check-out report that silently confirms a
missing item is evidence a landlord would rely on and lose with. It is also
exactly the trap the aligner fix fell into at first pass — head-noun matching
removed 80 false changes and silently cost four real ones.

It is directly measurable and must be gated on the measurement: **`item_removed`
recall must not fall**, and the counterfactual pairs (defect absent → defect
present) are the sharpest instrument, because a conditioned run that reports the
prior's defect on a frame that does not show it is anchoring by definition. Run
this arm blind against the same gold, and reject it on that metric alone
regardless of how good the false-change rate looks.

### C. Per-frame extraction with deterministic merge (medium)

docs/31's VLM matrix item 3, unrun. One call per frame, then merge by rule. May
raise coverage — each frame gets dedicated attention instead of competing for
one call's budget — and makes the merge step inspectable rather than implicit
in the model's head. Costs more calls per room. Interacts with A: the merge
needs stable names to work on.

### D. Detector-grounded item sets (medium, infrastructure exists)

The build path already runs Grounding DINO / YOLOE (`ML-E10`, +17.3pp per
docs/22) and `attach_detector_crops` already binds detections to items. Pin the
candidate object set from detections so both runs start from the same
inventory of things-in-the-room, and the VLM names and grades rather than
enumerates. Attacks coverage and membership churn together, and the detector is
deterministic on identical pixels — which is the property the whole document is
short of.

### E. Sampling controls (promoted 6 Aug 2026 — blocked, and that now matters)

Antigravity does not expose temperature (`run_eval.py` records it as "not
exposed by Antigravity CLI"), so this arm is untestable on the current path and
would need the product's own metered backend to explore — which the synthetic
dataset's terms forbid. **Recorded as blocked, not untried.**

Phase 0 changed this arm's standing. Two calls with byte-identical inputs
disagreeing about a third of the schedule is exactly the signature sampling
would produce, and nothing in the evidence excludes it. The original wording —
"possibly already exhausted" — assumed the instability was mostly perceptual;
it is not. So the caveat at the end of this entry is now the live risk rather
than a hedge: **if the instability is largely sampling, every other arm here is
over-engineering.** Arms A–D proceed because they are what this path can
measure, not because sampling has been ruled out, and that distinction belongs
in any report of their results.

## Phases

- **Phase 0 — the floor.** ✅ Done 6 Aug 2026. Floor 336 reported changes,
  91.3% of the 368; the control and the delta pairs decompose almost
  identically. Gate passed, decision recorded above.
- **Phase 1 — attribute the 368.** With the floor known, split the delta-pair
  false changes into non-determinism, legitimate framing difference, and
  generator drift. The Amendment C reviews already name incidental drift per
  pair and can be read as evidence rather than re-adjudicated.
- **Phase 2 — arm A**, measured on both instruments.
- **Phase 3 — arms C and D**, whichever Phase 1 implicates.
- **Phase 4 — arm B**, last, and gated on the anchoring metric.
- **Phase 5 — real transfer.** Any winner is re-run on InventoryFlex and the
  native-resolution real fixtures. docs/31's rule is unchanged and binding: a
  candidate that improves synthetic results but regresses real evidence is
  rejected.

## Pass bars

- Phase 0 exits on a *measurement*, not a threshold — there is no pass or fail,
  only a number and a decision recorded against it.
- An arm passes when schedule agreement rises on the repeat-describe control
  **and** false-change rate falls on the delta pairs **and** no delta recall
  figure falls, per kind, outside noise.
- An arm that trades recall for false-change rate is rejected, not tuned. That
  trade is how a compare surface becomes quietly useless, and it is the
  specific mistake already made once in this programme and caught by having
  gold to check against.

## Risks and stopping rules

- **Overfitting to 27 synthetic pairs.** They are one generator, one house
  style, two frames per timepoint, and 30 pairs was sized for per-kind
  direction, not for tuning. Treat every result as directional, keep the
  sealed split sealed, and require real transfer before shipping. docs/00
  forbids promoting from synthetic data and that is not relaxed here.
- **The floor turns out to be small.** Then instability is not the story, the
  368 is mostly legitimate difference between two renders, and the right next
  move is a capture-side or resolution question (docs/22 §5.3), not a describe
  one. Stop and re-scope rather than proceeding down these phases.
- **Anchoring passes the false-change metric and fails the product.** Guarded
  by making `item_removed` recall a rejection criterion rather than one number
  among several.
- **Terms.** Every vision run for this dataset goes through subscription-backed
  Antigravity CLI. No metered endpoint, no image generation, no training on any
  of it. Unchanged from docs/31.

## Boundaries

- This is development evidence. Nothing here promotes compare or describe
  behaviour to production on its own; real check-in/check-out evidence does
  that, and docs/08 owns the product surface.
- The delta pairs are a regression baseline now that they are scored. Their
  value is comparative — re-running an arm against the same 27 pairs and the
  same cached gold — and that value dies if the pairs are regenerated or the
  gold is edited to suit a result.

## Scripts

| Script | Job |
|---|---|
| `evals/synthetic/run_repeat_describe.py` | Instrument 0: reuse the cached T0 describe and call it once more on byte-identical frames; refuses any pair whose two runs differ in instruction, prompt, schema, model or frame hashes |
| `evals/synthetic/score_stability.py` | The metrics above, on both instruments, pooled from summed counts and reported side by side; states the gate fraction and decides nothing |
| `tests/test_describe_stability.py` | The control's refusals, and each metric against a single named perturbation |

Both read only review-accepted pairs, and the runner goes through
`run_delta_eval.describe_side` rather than a copy of it — a control whose call
path had drifted from the runs it is the floor for would measure the drift.

## Related

- `docs/31-synthetic-evaluation-dataset-plan.md` — the delta pairs, the gold
  contract, and the scored result this is scoped from.
- `docs/08-compare.md` — the compare surface, the alignment tiers, and the
  5 Aug note recording that its no-synonyms premise is falsified.
- `docs/22-ml-programme-review-and-roadmap.md` — §5.2 attacks the describe step
  on *cost*; this attacks it on *stability*, which that roadmap does not cover.
  §5.3's native-resolution work bears on the coverage third of the problem.
- `docs/04-backend-comparison.md` — the recall-vs-trust split by tier.
