# Synthetic room evaluation fixture

This directory is the working data for `docs/31-synthetic-evaluation-dataset-plan.md`.
Phase 1 is a 16-image representative slice: two room specifications, four views
and a 50/50 split between Nano Banana 2 Lite through Antigravity CLI and GPT
Image 2 through Codex built-in generation. Intended prompt content is never
scored as observed truth. Only a completed two-pass review may use
`verified_synthetic_gold`.

## Terms decision

On 15 Jul 2026 the project owner approved Google generation and dataset
acceptance for this bounded evaluation use: the project is using provider AI
systems for an inventory task and does not train, fine-tune, distil or otherwise
develop model weights. This is an owner decision, not external legal advice.
Re-check before training use or a change in publication scope. For Phase 1 the
project owner confirms the Antigravity `generate_image` backend is Nano Banana
2 Lite. Preserve the CLI version, exact prompt and output hash for every task.

## Permanent generation boundary

Never call an image-generation API for this project. Generate Nano Banana
images only through Antigravity CLI and GPT Image 2 images only through Codex's
`imagegen` skill. This rule applies even when an API key is configured. It does
not authorise a later vision-description evaluation call; that remains a
separate, task-specific permission decision.

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

## Commands

```sh
uv run python -m evals.synthetic.build_tasks
uv run python -m evals.synthetic.validate_dataset
uv run python -m evals.synthetic.build_review
uv run python -m evals.synthetic.run_eval --dry-run
# Explicit approval for metered Gemini inference is required before:
uv run python -m evals.synthetic.run_eval
uv run python -m evals.synthetic.score
```

Use `--require-complete` only after all 16 task rows say `accepted`, all image
files exist, and both provider reviews for each packet are complete. The normal
validator accepts a not-yet-generated slice but reports every pending task.

## Operator sequence

1. Confirm the provider's `acceptance_permitted` terms record is true.
2. Claim a row in `tasks.csv`; add your name and retain its exact prompt.
3. Generate interactively with the displayed product/model in that row.
4. Save the original output at `output_path`; do not edit pixels.
5. Record `attempts`, `generated_at`, and set status to `review_pending`.
6. Copy the review template for the matching packet/provider and complete Pass A.
7. Reject or accept each frame. Never weaken a scenario after two failures.
8. Complete Pass B from visible evidence only, including deviations.
9. Obtain the required second checks, then mark gold only after disagreements resolve.
10. Rebuild the contact sheet and run the strict validator.

The Phase 1 prompt comparison is frozen in `dataset.json`. Its runner sends the
two complete GPT Image 2 packets to the production `gemini-3.5-flash` backend
once per prompt, caches the raw provider responses, and refuses to overwrite
them. An interrupted run resumes by skipping immutable cached responses. The
scorer writes `reports/phase1-prompt-comparison.{json,md}`. The two
incomplete Nano Banana packets remain useful for single-image work but are
excluded from this whole-room production-architecture comparison.

Rejected attempts are append-only JSON lines in `rejected/manifest.jsonl` with
task ID, attempt, output hash/path, timestamp, operator and rejection reasons.
Do not commit account IDs, conversations, session exports, or unrelated metadata.
