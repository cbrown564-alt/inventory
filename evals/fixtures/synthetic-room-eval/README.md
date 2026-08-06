# Synthetic room evaluation fixture

This directory is the working data for
`docs/31-synthetic-evaluation-dataset-plan.md`. The immutable pilot queue
contains 25 matched room specifications, two provider packets per room and
four views per packet: 200 tasks in total. The earlier 16-image representative
slice remains as audit and prompt-development evidence. Intended prompt
content is never scored as observed truth. Only a completed independent
AI-first two-pass review, including any required owner adjudication, may use
`verified_synthetic_gold`.

## Terms decision

On 15 Jul 2026 the project owner approved Google generation and dataset
acceptance for this bounded evaluation use: the project is using provider AI
systems for an inventory task and does not train, fine-tune, distil or otherwise
develop model weights. This is an owner decision, not external legal advice.
Re-check before training use or a change in publication scope. The six
accepted legacy Google images retain their recorded Nano Banana 2 Lite label
but sit outside the new 200-task queue. Antigravity CLI 1.1.8 does not expose
a selectable backend image model in successful run records, so the current
Google cohort is `antigravity-builtin / backend_model: unknown`. Preserve the
CLI version, exact prompt and output hash for every task.

## Permanent generation boundary

Never call an image-generation API for this project. Generate Google images
only through Antigravity CLI and GPT Image 2 images only through Codex's
`imagegen` skill. Google vision-description evaluation for this synthetic
programme also uses subscription-backed Antigravity CLI, never a metered
Gemini endpoint. This rule applies even when an API key is configured.

## Phase 1 generation result

Antigravity CLI 1.1.2 produced the eight Nano Banana 2 Lite first attempts.
Pass A accepted six (75%). Two second attempts copied existing fixture images;
the duplicate check caught them and the tasks are terminal `generator_failed`.
Both attempts are retained under `rejected/` with hashes and reasons. Do not
make a third Antigravity attempt from the same specification. GPT Image 2 now
supplies the other eight images. All eight GPT first attempts passed the visual
screen and have distinct hashes; the reference-copy symptom did not recur.
There was no failed GPT first attempt, so correction-retry behaviour remains
untested. Overall Pass A yield is 14/16 (87.5%). Failed generations stay out of
scoring but a yield of at least 75% does not block Phase 1.

The project owner approved and signed off Pass A on 15 Jul 2026. Primary Pass B
review is complete for the 14 accepted images: all claims link to accepted
frames, negative controls are structured, and generator deviations are
recorded. On 28 Jul 2026 Conor Brown independently checked all three defect
claims, every negative control and the preselected ordinary-label samples: all
37 required decisions agreed with the primary review. The four records are now
`verified_synthetic_gold` and may be used for the production-backend and
prompt-candidate comparison.

Four immutable Antigravity CLI vision runs completed on 28 Jul 2026. The
evidence-bounded prompt improved defect recall from 50% to 100% and removed
one unsupported defect, while item recall fell from 78.1% to 71.9%. The result
is directional, so no prompt winner is frozen.

## Current pilot status

Phase 2 is complete. In Phase 3, the complete 146-frame Pass A plus owner
adjudication has been applied: 93 frames were accepted and 53 failed first
attempts were archived. The queue now contains 101 `pass_a_accepted`, 39
`review_pending`, 14 `retry_pending`, 4 `generator_failed` and 42 `pending`
tasks; the last 40 pending tasks are the untouched sealed split. Eighteen GPT
Image 2 retries and 21 Google retries are ready for dual independent retry
Pass A. Fourteen Google retry files and Google `RP-016 C-inventory` and
`D-condition` remain missing.

Resume from `generation_runs/antigravity/pause-2026-07-30-0156.json` after
the reported quota reset. The Google generation provenance audit in
`reports/` records that Google RP-009 and RP-012 lack successful raw
generation records and RP-018 has only an integrity recovery ledger. Those
packets remain provisional and are excluded from Pass B. Do not start prompt
or architecture selection until the required reviews are complete.

The review path is AI-first. An AI reviewer independent of the generation
call completes Pass A and Pass B. A second independent AI checks every defect,
every negative and the defined ordinary-label sample. Send only ambiguity,
reviewer disagreement, material continuity or condition concerns, validation
failures and periodic drift-audit samples to the project owner. See
`docs/31-synthetic-evaluation-dataset-plan.md` for the binding escalation
rules.

## Commands

```powershell
$fixture = "evals/fixtures/synthetic-room-eval"
.\.venv\Scripts\python.exe -m evals.synthetic.build_tasks
.\.venv\Scripts\python.exe -m evals.synthetic.validate_dataset
.\.venv\Scripts\python.exe -m evals.synthetic.build_review
.\.venv\Scripts\python.exe -m evals.synthetic.generate_antigravity --workers 1
.\.venv\Scripts\python.exe -m evals.synthetic.record_outputs --provider Google --operator "Antigravity operator name" --cli-version "Antigravity CLI 1.1.8"
.\.venv\Scripts\python.exe -m evals.synthetic.build_pass_a_gallery --review "$fixture/reports/phase3-pass-a-review-2026-07-29.json"
.\.venv\Scripts\python.exe -m evals.synthetic.apply_owner_adjudications "$fixture/reports/phase3-pass-a-review-2026-07-29.json" owner-adjudications.json --corrections "$fixture/reports/pass-a-protocol-corrections-2026-07-30.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_owner_adjudications "$fixture/reports/phase3-pass-a-review-2026-07-29.json" owner-adjudications.json --corrections "$fixture/reports/pass-a-protocol-corrections-2026-07-30.json" --prepare-retries
.\.venv\Scripts\python.exe -m evals.synthetic.record_imagegen_retries
.\.venv\Scripts\python.exe -m evals.synthetic.audit_google_provenance
.\.venv\Scripts\python.exe -m evals.synthetic.review_pass_a --output "$fixture/reports/phase3-retry-pass-a-review-2026-07-30.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.review_pass_a --output "$fixture/reports/phase3-retry-pass-a-review-2026-07-30.json"
.\.venv\Scripts\python.exe -m evals.synthetic.build_pass_a_gallery --review "$fixture/reports/phase3-retry-pass-a-review-2026-07-30.json"
.\.venv\Scripts\python.exe -m evals.synthetic.apply_retry_pass_a "$fixture/reports/phase3-retry-pass-a-review-2026-07-30.json" --adjudications owner-adjudications.json --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_retry_pass_a "$fixture/reports/phase3-retry-pass-a-review-2026-07-30.json" --adjudications owner-adjudications.json
.\.venv\Scripts\python.exe -m evals.synthetic.review_pass_b --output "$fixture/reports/phase3-pass-b-review-2026-07-30.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.review_pass_b --output "$fixture/reports/phase3-pass-b-review-2026-07-30.json"
.\.venv\Scripts\python.exe -m evals.synthetic.apply_pass_b "$fixture/reports/phase3-pass-b-review-2026-07-30.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_pass_b "$fixture/reports/phase3-pass-b-review-2026-07-30.json"
.\.venv\Scripts\python.exe -m evals.synthetic.run_eval --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.run_eval
.\.venv\Scripts\python.exe -m evals.synthetic.score
```

## Phase 3.5 delta pairs

The probe is gated: it must pass before any pilot pair is authored. Generation
is Codex built-in `imagegen` only, as everywhere else in this dataset, and the
T0 side is always an already-accepted frame reused as the visual reference.

```powershell
.\.venv\Scripts\python.exe -m evals.synthetic.build_delta_tasks --print-prompts
.\.venv\Scripts\python.exe -m evals.synthetic.generate_delta_codex --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.generate_delta_codex --log-dir <dir>
.\.venv\Scripts\python.exe -m evals.synthetic.record_delta_outputs --operator "Codex GPT Image 2 built-in imagegen" --cli-version "Codex built-in imagegen / GPT Image 2" --report "$fixture/reports/phase35-delta-generation-2026-08-04.json"
.\.venv\Scripts\python.exe -m evals.synthetic.review_delta_pair --output "$fixture/reports/phase35-delta-review-2026-08-04.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.review_delta_pair --output "$fixture/reports/phase35-delta-review-2026-08-04.json"
.\.venv\Scripts\python.exe -m evals.synthetic.review_delta_pair --output "$fixture/reports/phase35-delta-review-2026-08-04.json" --probe
.\.venv\Scripts\python.exe -m evals.synthetic.build_delta_gallery --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --reviewed-only --output "$fixture/reports/phase35-pilot-gallery-2026-08-05.html"
.\.venv\Scripts\python.exe -m evals.synthetic.apply_delta_gold_corrections "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_delta_gold_corrections "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --report "$fixture/reports/phase35-gold-corrections-applied-2026-08-05.json"
.\.venv\Scripts\python.exe -m evals.synthetic.run_delta_eval --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.run_delta_eval --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --resume
.\.venv\Scripts\python.exe -m evals.synthetic.aggregate_delta_scores "$fixture/reports/delta-compare/gemini-3-5-flash-low-production-v1" --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --summary "$fixture/reports/phase35-pilot-summary-2026-08-05.json" --out "$fixture/reports/phase35-delta-score-2026-08-05.json"
```

`run_delta_eval` describes each timepoint through Antigravity and never tells
the backend it is looking at a delta. Cached describe records are immutable;
`--resume` continues an interrupted run instead of failing on them.

### Scored result, 5 Aug 2026

All 27 accepted pairs scored: **delta recall 26.6%, false-change rate 90.4%**
(`reports/phase35-delta-score-2026-08-05.json`, Markdown alongside it).

Presence changes are caught about half the time — item added 54.3%, item
removed 50.0% — and changes of state are not: worsened 14.8%, new defect
12.1%, cleanliness 3.8%. Of the 77 missed condition changes, 43 involve an
object neither describe run ever named, 17 an object the aligner split across
`removed` and `added`, and 17 an object tracked correctly whose change went
unreported.

Some of the false changes were one untouched object reported twice because the
runs named it differently and `compare.match_score` did not align them
(`Recessed spotlight` / `Ceiling spotlight`). That defect is fixed — see
docs/31 — worth 17 fewer false changes at no cost to recall. The remaining
churn is synonymy (`Heated towel rail` / `Towel radiator`), which no token
rule reaches.

This is development evidence. It cannot promote compare behaviour, and one
describe call (`P35-028-CF` T0) was re-run after returning an empty response
under a SUCCESS status.

## Phase 0 — the describe-stability floor (docs/35)

The delta scoring found that nine in ten reported changes had no gold
counterpart, and that the bulk of them were the *description* moving rather
than the room. The delta pairs cannot prove that, because T0 and T1 are
different photographs. This control removes the difference: it describes the
**T0 frames a second time** and compares the two runs, so every change reported
has no possible cause but non-determinism.

```powershell
.\.venv\Scripts\python.exe -m evals.synthetic.run_repeat_describe --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.run_repeat_describe --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --resume
.\.venv\Scripts\python.exe -m evals.synthetic.score_stability --review "$fixture/reports/phase35-pilot-review-recut-2026-08-05.json" --delta-score "$fixture/reports/phase35-delta-score-2026-08-05.json" --out "$fixture/reports/phase0-describe-stability-2026-08-06.json"
```

`run_repeat_describe` reuses the cached T0 describe as the first run and makes
one more call per pair — 27 calls, subscription-backed, no image generation. It
goes through `run_delta_eval.describe_side` rather than a copy of it, and
refuses any pair whose two runs differ in instruction, prompt, schema, model or
frame hashes: a floor confounded with a prompt difference is worse than no
floor.

`score_stability` scores **both** instruments — the control and the delta pairs
— from the cached describe records and reports them side by side, never
averaged. Their difference is the finding.

### Measured result, 6 Aug 2026

**Describing the same photographs twice reported 336 changes — 91.3% of the
delta pairs' 368 false changes** (`reports/phase0-describe-stability-2026-08-06.json`).

The two instruments decompose almost identically: schedule agreement 34.6%
(control) against 32.4% (delta), membership churn 10.7 per room against 12.0,
naming churn 4.26 against 4.22. Two describes of one photograph disagree about
the room nearly as much as two describes of different photographs of a changed
room.

The mechanism is synonymy, now visible where no real change is possible:
`Extractor hood`/`Cooker hood`, `Trash bin`/`Waste bin`, `Paper towel
holder`/`Kitchen Roll Holder`, `Electric oven`/`Oven`. Separately, 81 of 234
`intended_visible_items` were named by neither run — a flat coverage gap, not
an instability.

The 336 understates it. The tenancy gate reports an item only when it got
worse, so of 116 aligned items graded differently by the two runs, 76 were
never shown at all.

### What rejects a delta pair (docs/31 Amendment C, 5 Aug 2026)

A pair fails when the room stops being the same room: geometry, walls, floors,
finishes, windows, doors, fitted units, appliances, sanitaryware, radiators,
fixed lighting or large defining furniture moving, resizing, changing model or
disappearing — or the two views of one timepoint contradicting each other about
any of it. A pair also fails when no enumerated material change is observable,
because then it is not a delta pair.

Movable clutter — towels, toiletries, worktop items, cushions, shoes, books —
is **recorded and never rejects**. It goes to `observed_changes` so that a
compare run that correctly reports it is not scored as inventing a change. An
enumerated change that did not render is a gold correction, not a reason to
discard the frames.

The 4 Aug pilot review applied the older rubric (any unenumerated difference is
fatal) and rejected 27 of 30 pairs on clutter. The re-adjudication is
`reports/phase35-pilot-review-recut-2026-08-05.json` with gallery
`reports/phase35-pilot-gallery-2026-08-05.html`: **27 accept, 3 reject**
(P35-001-T1 and P35-019-T1 — the oven moves in the run and the D-condition
frames show a different kitchen; P35-022-CF — the basin loses its mixer tap in
one view only). Both 4 Aug reports are retained unedited as evidence, and the
owner's 5 Aug decisions are in
`reports/phase35-pilot-owner-adjudication-2026-08-05.json`.

### Correcting gold without touching a frozen prompt

`changes` is the generation prompt as well as the gold, so once a frame exists
that list cannot be edited — its hash pins the frame's provenance. Corrections
go to two side lists that `build_prompt` never reads:

- `observed_changes` — real differences nobody enumerated. Without them a
  compare run that correctly reports one is scored as inventing a change.
- `retracted_changes` — enumerated changes the frames do not carry, either
  `not_rendered` or `t0_premise_wrong` (the spec asserted a T0 state the
  reference never showed). Each names an issue, a reason and the review that
  found it. Retracted changes leave the gold entirely, so they stop costing
  recall and start counting as invention if a model reports them anyway.

Applied on 5 Aug 2026: 24 retractions and 12 observed changes across 21 specs,
pilot gold from 173 to 153 scorable material changes, prompt hashes unchanged
(`reports/phase35-gold-corrections-applied-2026-08-05.json`). One fault cannot
be repaired this way — P35-018-T1's D2 removes the pendant light while its
unchanged assertions claim it — because both sides feed the frozen prompt.

`record_delta_outputs` refuses a T1 frame that is byte-identical to its own T0
reference. That is the delta-specific failure mode: it presents as the perfect
result — identity intact, nothing drifted — and fails only on the enumerated
changes being absent, which reads as an ordinary generator miss. It also
refuses a third attempt, because docs/31 caps the probe at two per scenario
and forbids retrying at a looser bar.

`build_pass_a_gallery` writes `reports/pass-a-owner-gallery.html` from the latest
initial or retry Pass A report. Serve the dataset root so image paths resolve:

```powershell
.\.venv\Scripts\python.exe -m http.server 8766 --directory evals/fixtures/synthetic-room-eval
```

Then open `http://127.0.0.1:8766/reports/pass-a-owner-gallery.html`. Export JSON
from the gallery. `apply_owner_adjudications` combines the complete AI review,
owner export and any explicit protocol-correction record. Always dry-run first;
`--prepare-retries` archives rejected originals and marks their tasks ready for
the final allowed attempt.

`generate_antigravity` invokes the subscription CLI; it does not use image API
credentials. Use `--require-complete` only after all 200 task rows say
`accepted` or `pass_a_accepted`, all image files exist, and both provider
reviews for each packet are complete. The normal validator accepts a
not-yet-generated pilot but reports every pending task.

## Operator sequence

1. Confirm the provider's `acceptance_permitted` terms record is true.
2. Claim a row in `tasks.csv`; add your name and retain its exact prompt.
3. Generate with the authorised path in that row: Antigravity CLI for Google
   or Codex `imagegen` for GPT Image 2.
4. Save the original output at `output_path`; do not edit pixels.
5. Record `attempts`, `generated_at`, and set status to `review_pending`.
6. Copy the review template for the matching packet/provider and run
   independent AI Pass A.
7. Reject or accept clear cases; escalate uncertainty. Never weaken a
   scenario after two failures.
8. Run independent AI Pass B from visible evidence only, including deviations.
9. Run the required separate AI checks and send only defined exceptions or
   drift-audit samples to the project owner.
10. Mark gold only after deterministic validation and any escalation resolves.
11. Rebuild the contact sheet and run the strict validator.

The Phase 1 prompt comparison is frozen in `dataset.json`. Its runner sends the
two complete GPT Image 2 packets through the pinned Antigravity CLI
`gemini-3.5-flash-low` mode once per prompt, caches sanitised raw responses,
and refuses to overwrite them. It never calls a Gemini API endpoint. An
interrupted run resumes by skipping immutable cached responses. The scorer
writes `reports/phase1-prompt-comparison.{json,md}`. The two incomplete legacy
Google packets remain useful for single-image work but are excluded from this
whole-room comparison.

Rejected attempts are append-only JSON lines in `rejected/manifest.jsonl` with
task ID, attempt, output hash/path, timestamp, operator and rejection reasons.
Do not commit account IDs, conversations, session exports, or unrelated metadata.
