# 36 — Synthetic programme review: what the apparatus bought

> **Status: active (review).** This document reviews docs/31, docs/34 and
> docs/35 as one programme and re-scopes them. It owns the **verdict** on the
> synthetic evaluation programme's phases; docs/31 remains the canonical owner
> of the dataset itself, its gold contract and its terms. Where this document
> and docs/31's phase table conflict on *status*, this one governs.

*6 Aug 2026. Written the day docs/35 Phase 0 landed, because that measurement
reprices everything upstream of it. The programme ran 15 Jul – 6 Aug 2026,
48 commits, and produced one change to product code. This is not an argument
that it was wasted — the finding it ended on is worth more than the prompt
decision it set out to make — but the finding was reachable on day one for
about 27 API calls, and the reason it took nine days of building to reach is
structural and will recur.*

---

## Decision

**Phases 1–3 of docs/31 are superseded, not blocked.** They are recorded as
"in progress" and "review-blocked" against a Pass B backlog. That framing says
the work is one push from useful. It is not. The measurement those phases feed
— one describe run compared against reviewed gold — has a run-to-run noise band
that was never measured until 6 Aug, and it is wider than any effect the phases
were designed to detect. Completing them does not produce a prompt decision.

Four consequences, in the order they should be acted on:

1. **The sampling question (docs/35 arm E) moves in front of arms A–D.** It is
   blocked only on the Antigravity path, not on the question.
2. **The Pass B backlog is cut, not cleared**, unless a decision that needs
   those labels can be named.
3. **The video probe (docs/34) is closed one way or the other** — regenerated
   against its now-accepted references, or suspended in writing.
4. **The 27 delta pairs are wired into `evals/ci_gate.py`.** docs/35 calls them
   a regression baseline; nothing re-runs them, so they are a report.

---

## 1. What was built

15 Jul – 6 Aug 2026. 48 commits touching `evals/synthetic`,
`evals/fixtures/synthetic-room-eval`, docs/31, docs/34, docs/35 and their tests.

| Asset | Size |
|---|---:|
| `evals/synthetic/` tooling | 48 scripts, 13,007 lines |
| Tests | 3,193 lines across 4 files |
| Generated stills | 304 files, 438 MB, 300 ledger rows |
| Generated video | 8 clips, 30 MB |
| Packet review records | 77 |
| Report artefacts | 40+ under `reports/` |
| Delta specifications | 33 authored, 30 generated, 27 accepted and scored |
| Planning | 1,718 lines (docs/31) + 342 (docs/34) + 394 (docs/35) |

The tooling is good. The gold contract — frozen `changes`, post-hoc
`observed_changes` and `retracted_changes`, each naming the review that found
it, with prompt hashes re-derived so no correction can orphan a frame — is the
most careful thing in this repository. None of what follows is a criticism of
how the apparatus was built. It is about what it was pointed at.

## 2. Phase by phase: expected against returned

| Phase | Expected | Returned |
|---|---|---|
| 1 — representative slice | Freeze a prompt winner | Defect recall 50%→100%, item recall −6.2pp, **no winner frozen**. The only prompt comparison the programme has ever run. |
| 2 — tooling | The apparatus | The apparatus, in full. Delivered exactly what it promised. |
| 3 — dev + validation sets | Enough reviewed gold for a prompt decision | 143 `pass_a_accepted`, 39 `generator_failed`, 43 `not_generated`, 60 in some pending state. **4 of 77 packet records are `verified_synthetic_gold`; 73 are `provisional`.** |
| 3.5 — delta pairs | A false-change rate worth quoting | Delivered. 27 scored pairs, **delta recall 26.6%, false-change rate 90.4%**. |
| 3.6 — video (docs/34) | Five clips answering "can Omni hold a room through motion" | 9 queued, 8 delivered, **8 rejected**, batch void on a fixture bug. Repaired 4 Aug; **regeneration never run**. |
| 4 — sealed comparison | The decision the programme exists for | Not started. |
| 5 — real transfer | The only thing that could promote anything | Not started. |
| docs/35 Phase 0 | A denominator | The finding in §3. |

Phase 3.5 is the genuine achievement and stands on its own. Its per-kind result
is the programme's most useful single output:

| Change kind | Gold | Detected | Recall |
|---|---:|---:|---:|
| `item_added` | 35 | 19 | 54.3% |
| `item_removed` | 18 | 9 | 50.0% |
| `worsened` | 27 | 4 | 14.8% |
| `new_defect` | 33 | 4 | 12.1% |
| `cleanliness` | 26 | 1 | **3.8%** |

Presence is seen. Condition is not. For a deposit product whose disputes turn
on condition, that ordering is the finding, and it did not need the 200-image
arm to produce it.

## 3. The measurement that reprices the programme

docs/35 Phase 0 describes the **same frames twice** and compares the runs. Every
reported difference is non-determinism. The headline is that the floor is 336
against the delta pairs' 368 false changes — 91.3%. The stronger half is the
decomposition:

| | Same photograph, twice | Different render, changed room |
|---|---:|---:|
| Schedule agreement, exact names | 34.6% | 32.4% |
| Membership churn per room | 10.7 | 12.0 |
| Naming churn per room | 4.26 | 4.22 |
| Cleanliness agreement | 80.7% | 70.1% |

Going from *the same pixels* to *a different render of a changed room carrying
five enumerated changes* moves schedule agreement by 2.2 points and takes naming
churn slightly down. **The two columns are the same column.**

That is a statement about the instrument, and it propagates backwards:

- **Phase 1's −6.2pp was never a null result about two prompts.** It was an
  unrecognised noise reading. Four runs, no repeat control, an effect an order
  of magnitude inside the churn now measured — that design could not have
  returned anything else. "No winner was frozen" has been carried in docs/00
  and docs/31 as a finding about the prompts. It is a finding about the method.
- **The Pass B backlog feeds a metric whose variance was unknown.** 73
  provisional records exist to sharpen item recall against gold. Item recall is
  computed from one describe run. The run reproduces a third of its own
  schedule on identical input.
- **Amendment C is the sharpest case.** Re-adjudicating 30 pairs on room
  identity, 24 retractions, 12 observed changes, gold moving 173 → 153 scorable
  changes — that removed perhaps 20 units of gold error from the same 27 pairs
  the describe step was adding 336 units of noise to. The work was correct. It
  was second-order against an uncontrolled first-order term.

The programme spent nine days making the ground truth exact and one day
measuring the instrument reading it.

## 4. What reached the product

One function. `homeinventory/compare.py` — `match_score` tier 1, positional
modifiers, worth 17 fewer false changes at no cost to recall, and correctly
gated on recall not falling (docs/08 §1 update, 5 Aug).

That is the complete product yield of 13,007 lines of tooling and 468 MB of
generated evidence. It is a real improvement and it was found by having gold to
check against, which is the apparatus doing its job. It is also, at this date,
the whole list.

## 5. Three mechanisms, because they will recur

**5.1 The plan amended faster than it executed.** docs/31 took Amendments A, B
and C in three days, with **B superseding A on the same day A was written** —
explicitly, because A was authored before the ledger was read against the plan.
Each amendment was locally correct. The cumulative effect is that no phase
reached its own stated conclusion before its terms of reference moved.

**5.2 Three arms are open at once and none is closed.** Image pilot:
review-blocked. Video probe: void batch, fixture repaired, regeneration
unstarted. Describe stability: Phase 0 done, Phases 1–5 unstarted. Nothing has
been declared finished or abandoned, so every reading of the programme carries
three live fronts. docs/34's arm is in its most expensive possible state:
repaired but unrun.

**5.3 Rigour went where it was verifiable, not where it was load-bearing.**
Provenance hashes, dual independent review, retraction ledgers, prompt-hash
re-derivation, the positional-view audit — these are things you can verify you
did, and the programme is exceptionally strong at them. *"Is my measurement
above the noise floor?"* is a thing you have to think to ask. It was asked on
day nine, by accident, as a scoping question for a follow-on document.

The generalisable rule: **before building an instrument to compare two arms,
run one arm twice.** The repeat-describe control cost 27 calls and no new
fixtures. It belonged in Phase 1.

## 6. Work order

### 6.1 Sampling first — and it is not blocked

docs/35 records arm E as blocked because Antigravity does not expose
temperature, then proceeds down arms A–D while stating the risk in its own
words: *"if the instability is largely sampling, every other arm here is
over-engineering."* That risk sits unresolved under every remaining phase of
that document.

It is blocked on the *production describe path*, not on the question.
`homeinventory/describe.py:366` — `LocalBackend` — accepts `temperature`,
defaults to `0.0`, and runs through Ollama: free, unmetered, no image
generation, and outside docs/31's terms rule, which binds *"every vision run
for this dataset"* to Antigravity. A local run over the same 27 frame sets is
not a vision run for the dataset's gold; it is an instrument check, and it
produces no labels that enter the scored set.

Run the repeat-describe control on `LocalBackend` at `temperature=0` and at
`0.7`, same frames, same schema.

- **If temperature-0 still churns ~10 items per room**, sampling is excluded as
  the mechanism and arms A–D are correctly aimed. Proceed with docs/35 Phase 1
  as written, with the risk closed rather than hedged.
- **If temperature-0 is stable and 0.7 churns**, docs/35 is largely chasing a
  decode setting, arms A–D shrink to a lexicon question, and the finding is
  about how the production path is configured.

**Limit, stated plainly.** A local model's variance is not
`gemini-3.5-flash-low`'s variance, and this cannot produce a magnitude for the
production path. It answers a *mechanism* question — does greedy decoding
produce a stable schedule at all — and that is the question standing in front
of a multi-week roadmap. Nothing here promotes anything; docs/00's wall is
unchanged.

### 6.2 Cut the Pass B backlog rather than clearing it

73 provisional records feed Phase 4. Phase 4 needs a prompt decision that
§3 says cannot be made at n=25 with one run per arm. Either name the decision
that needs those labels and state the run count that would make it readable, or
close the backlog out and record the four `verified_synthetic_gold` packets as
what Phase 3 produced. Do not clear it by default.

The 43 `not_generated` and 39 `generator_failed` rows follow the same rule:
generation yield stops being a programme metric the moment the metric it feeds
is known to be under-powered.

### 6.3 Close the video arm

docs/34's five day-1 clips now have accepted, correctly-filed reference stills
and an enforceable rule that a clip may only be conditioned on a
`pass_a_accepted` still. Either regenerate those five, or record docs/34 as
suspended with the fixture repair as its terminal state. Its two findings that
survive the void batch — readable brands in 6 of 8 clips, and geometry drifting
mid-take with no cut — are worth carrying into docs/26 either way, as leads.

### 6.4 Make the delta pairs an actual baseline

docs/35 states the 27 pairs "are a regression baseline now that they are
scored", and that their value dies if the pairs are regenerated or the gold
edited to suit a result. Both halves need enforcement they do not have:
`evals/ci_gate.py` does not run them, and nothing pins the gold's hash. Wire the
scored run in with its numbers pinned, so an arm that moves `false_change_rate`
without moving `item_removed` recall is caught by the harness rather than by
somebody remembering to look.

## 7. What this review does not do

- It does not retract any measurement. Every number in docs/31 and docs/35
  stands as measured; this document changes what they are evidence *for*.
- It does not touch the gold contract, the terms position, the splits, or the
  publication ban. docs/31 owns those and they are unchanged.
- It does not promote or demote any product behaviour. The `match_score` tier 1
  change was landed on its own evidence and is unaffected.
- It does not claim the programme should not have been run. The delta pairs and
  the stability floor are real, reusable instruments that did not exist on
  15 Jul, and ML-E14's "blocked | no data" is answered.

## Related

- `docs/31-synthetic-evaluation-dataset-plan.md` — canonical owner of the
  dataset, gold contract and terms. Its phase table now points here for status.
- `docs/34-synthetic-video-probe.md` — the video arm awaiting §6.3.
- `docs/35-describe-stability.md` — the Phase 0 measurement this is written
  from, and the arm ordering §6.1 changes.
- `docs/08-compare.md` — the one product surface the programme moved.
- `docs/00-north-star.md` — the promotion wall, unchanged and binding.
- `docs/22-ml-programme-review-and-roadmap.md` — the prior review of the same
  shape. Its §1 finding, that a programme's *design* can guarantee
  uninformative results, is the finding here as well.
