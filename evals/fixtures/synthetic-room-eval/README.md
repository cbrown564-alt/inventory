# Synthetic room evaluation fixture

This directory is the working data for
`docs/31-synthetic-evaluation-dataset-plan.md`. The immutable pilot queue
contains 25 matched room specifications, two provider packets per room and
four views per packet: 200 tasks in total. The earlier 16-image representative
slice remains as audit and prompt-development evidence. Intended prompt
content is never scored as observed truth. Only a completed two-pass review
may use `verified_synthetic_gold`.

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

Phase 2 is complete: all 25 scenarios, 200 tasks, review templates and hashed
development/validation/sealed splits exist. Phase 3 is paused at the 29 Jul
operator checkpoint. Across the full queue there are 8 `pass_a_accepted`, 93
`review_pending`, 4 `generator_failed` and 95 `pending` tasks; the last 40
pending tasks are the untouched sealed split. Within development/validation,
55 tasks remain pending.

The GPT cohort is complete through RP-010. Google has 15 complete provisional
packets, one partial packet (`RP-016`, A-wide only), the earlier terminal
RP-003 failure, and pending work at RP-010, RP-011, RP-016 B–D and RP-020.
Complete file packets RP-009, RP-012 and RP-018 came from wrapper-error runs
and need provenance review as well as Pass A. Resume from
`generation_runs/antigravity/pause-2026-07-29.json`, keep the two-attempt rule,
and do not start prompt or architecture selection until the required reviews
are complete. Generated files remain provisional until independent review.

## Commands

```powershell
.\.venv\Scripts\python.exe -m evals.synthetic.build_tasks
.\.venv\Scripts\python.exe -m evals.synthetic.validate_dataset
.\.venv\Scripts\python.exe -m evals.synthetic.build_review
.\.venv\Scripts\python.exe -m evals.synthetic.generate_antigravity --workers 1
.\.venv\Scripts\python.exe -m evals.synthetic.record_outputs --provider Google --operator "Antigravity operator name" --cli-version "Antigravity CLI 1.1.8"
.\.venv\Scripts\python.exe -m evals.synthetic.run_eval --dry-run
.\.venv\Scripts\python.exe -m evals.synthetic.run_eval
.\.venv\Scripts\python.exe -m evals.synthetic.score
```

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
6. Copy the review template for the matching packet/provider and complete Pass A.
7. Reject or accept each frame. Never weaken a scenario after two failures.
8. Complete Pass B from visible evidence only, including deviations.
9. Obtain the required second checks, then mark gold only after disagreements resolve.
10. Rebuild the contact sheet and run the strict validator.

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
