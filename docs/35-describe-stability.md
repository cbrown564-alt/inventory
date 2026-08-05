# 35 — Describe stability: the same room, described twice

*5 Aug 2026. Scoped off the Phase 3.5 delta scoring (docs/31). Not started.*

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

### E. Sampling controls (cheapest to test, possibly already exhausted)

Antigravity does not expose temperature (`run_eval.py` records it as "not
exposed by Antigravity CLI"), so this arm may be untestable on the current
path and would need the product's own metered backend to explore — which the
synthetic dataset's terms forbid. Record as blocked rather than untried if so,
and do not quietly skip it: if the instability is largely sampling, every other
arm here is over-engineering.

## Phases

- **Phase 0 — the floor.** Instrument 0 above. Exit: a measured
  non-determinism floor, and the gate decision recorded either way.
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

## Related

- `docs/31-synthetic-evaluation-dataset-plan.md` — the delta pairs, the gold
  contract, and the scored result this is scoped from.
- `docs/08-compare.md` — the compare surface, the alignment tiers, and the
  5 Aug note recording that its no-synonyms premise is falsified.
- `docs/22-ml-programme-review-and-roadmap.md` — §5.2 attacks the describe step
  on *cost*; this attacks it on *stability*, which that roadmap does not cover.
  §5.3's native-resolution work bears on the coverage third of the problem.
- `docs/04-backend-comparison.md` — the recall-vs-trust split by tier.
