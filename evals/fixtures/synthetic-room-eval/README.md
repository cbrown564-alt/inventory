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
.\.venv\Scripts\python.exe -m evals.synthetic.build_tasks
.\.venv\Scripts\python.exe -m evals.synthetic.validate_dataset
.\.venv\Scripts\python.exe -m evals.synthetic.build_review
.\.venv\Scripts\python.exe -m evals.synthetic.generate_antigravity --workers 1
.\.venv\Scripts\python.exe -m evals.synthetic.record_outputs --provider Google --operator "Antigravity operator name" --cli-version "Antigravity CLI 1.1.8"
.\.venv\Scripts\python.exe -m evals.synthetic.build_pass_a_gallery
.\.venv\Scripts\python.exe -m evals.synthetic.apply_owner_adjudications reports/phase3-pass-a-review-2026-07-29.json owner-adjudications.json --corrections reports/pass-a-protocol-corrections-2026-07-30.json --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_owner_adjudications reports/phase3-pass-a-review-2026-07-29.json owner-adjudications.json --corrections reports/pass-a-protocol-corrections-2026-07-30.json --prepare-retries
.\.venv\Scripts\python.exe -m evals.synthetic.record_imagegen_retries
.\.venv\Scripts\python.exe -m evals.synthetic.audit_google_provenance
.\.venv\Scripts\python.exe -m evals.synthetic.review_pass_a --output reports/phase3-retry-pass-a-review-2026-07-30.json
.\.venv\Scripts\python.exe -m evals.synthetic.apply_retry_pass_a reports/phase3-retry-pass-a-review-2026-07-30.json --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_retry_pass_a reports/phase3-retry-pass-a-review-2026-07-30.json
.\.venv\Scripts\python.exe -m evals.synthetic.review_pass_b --output reports/phase3-pass-b-review-2026-07-30.json
.\.venv\Scripts\python.exe -m evals.synthetic.apply_pass_b reports/phase3-pass-b-review-2026-07-30.json --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.apply_pass_b reports/phase3-pass-b-review-2026-07-30.json
.\.venv\Scripts\python.exe -m evals.synthetic.run_eval --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.run_eval
.\.venv\Scripts\python.exe -m evals.synthetic.score
```

`build_pass_a_gallery` writes `reports/pass-a-owner-gallery.html` from the latest
`phase3-pass-a-review-*.json`. Serve the dataset root so image paths resolve:

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
