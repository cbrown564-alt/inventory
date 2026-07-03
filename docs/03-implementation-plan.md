# Implementation Plan

## Milestone 0 — Prototype (this repo, "80% for a fraction of the cost")

Deliverable: CLI that turns a folder of room photos (or videos) into a professional
HTML/PDF inventory report with per-item condition grades, photo evidence, and a hash
manifest.

- [x] Package skeleton (`homeinventory/`), `pyproject.toml`
- [x] `schema.py` — dataclasses + JSON (Item, Room, Inventory, grades enums)
- [x] `ingest.py` — folder walk, video keyframe extraction (OpenCV; sharpness +
      frame-difference), EXIF capture-time extraction
- [x] `integrity.py` — SHA-256 manifest of originals
- [x] `detect.py` — YOLOE open-vocab backend (ultralytics), household vocabulary,
      graceful fallback to whole-image mode when weights/torch unavailable
- [x] `describe.py` — backend interface; `claude` (Anthropic vision, structured JSON
      output), `offline` (detector classes + heuristics); `local` stub documented
- [x] `merge.py` — within-room item de-duplication
- [x] `report.py` + `templates/report.html.j2` — print-ready HTML, WeasyPrint PDF
- [x] `cli.py` — `guide`, `build`, `compare` (compare = v2 stub)
- [x] `evals/` — fixtures format, scoring harness (recall / hallucination / naming /
      condition agreement), runs against any backend
- [x] Example end-to-end run committed under `examples/`

## Milestone 1 — Benchmark against published example reports

Find high-quality real-world example inventory reports (professional clerk samples with
photos, item labels and condition descriptions), run their photos through our pipeline,
and compare our output against the human-written report.

- [x] Online research: collect 1–3 published sample inventory/check-in reports
      (UK clerk companies, AIIC/ARLA samples) that include photos + labelled items +
      condition descriptions — 4 collected in `benchmarks/samples/`; InventoryFlex
      sample (35pp, 192 photos, ~80 itemised entries) selected
- [x] Extract photos from the sample report(s) into a fixture folder
      (`benchmarks/extract_inventoryflex.py` → `benchmarks/inventoryflex/capture/`)
- [x] Run `build` on the extracted photos (claude + gpt-5.4-mini)
- [x] Compare our report vs the professional one on: **accuracy** (items + conditions
      correct), **depth** (level of detail per item, defect localisation), **reliability**
      (hallucinations, misses, grade consistency)
- [x] Write up findings in `docs/06-professional-report-benchmark.md`; gold labels in
      `benchmarks/inventoryflex/labels.json` (first real-footage eval fixture)
- [ ] Follow-ups surfaced: defect-depth prompt work (partially addressed in
      prompt v2–v4), standard-items checklist (landed in prompt v2)
- [x] Eval matcher granularity fix — many-to-one coverage + gold `components`;
      opus v4 hallucination 37.3% → 2.8% on InventoryFlex (see `evals/README.md`)

## Milestone 2 — First real property run (the user's own tenancy)

- [ ] Run `guide`, capture own property (~15–25 photos/room), run `build --backend claude`
- [x] Review-loop ergonomics: `--room` partial rebuild, `inventory.json` hand-edits
      preserved on rebuild (`--from-json`)
- [ ] Tune the describe prompt on real failures (materials, defect localisation) —
      first pass done on the docs/06 benchmark: mini defect recall 46.9→64.8,
      notable recall 90.4 (target met); opus defect recall plateaus ~68% on the
      800×600 fixture (resolution-bound) — re-measure on own-property native-res
      capture before further prompt surgery
- [ ] Build first real eval fixture from this property (label 3 rooms by hand)
- [x] PDF polish: cover page, page numbers, agent-style layout parity check against a
      sample £165 report — clerk-style template landed (Schedule of Condition, hierarchical
      refs, 4-column print layout, TOC, page numbers + tenant initials, Appendix B photo
      grid); polished opus output at `benchmarks/inventoryflex/report-claude-v4-polished/`
      (45pp PDF from existing `report-claude-v4` inventory.json, no re-run)

## Milestone 3 — Open-source-only parity

- [x] `local` describe backend via Ollama (qwen3.5:9b default; batched calls
      sized for consumer GPUs) — live validation on real footage pending
- [x] `openai` backend: any OpenAI-compatible API (OpenAI, Gemini via compat
      endpoint, custom --base-url) for cheap cross-provider comparison
- [x] Eval: quantify gap vs `claude` backend on fixtures; document in README
      — closed 2 Jul 2026. All three backends scored on the InventoryFlex
      fixture (`evals/score_benchmarks.py`); write-up in
      [`docs/04`](04-backend-comparison.md). Net: `claude` quality ceiling
      (hallucination 2.8), `gpt-5.4-mini` cheap-iteration (recall 90.7 but
      hallucination 14.7), `local` qwen9b the £0 path (naming/grading
      competitive; recall −16 pts, hallucination +23 pts vs claude — a draft
      for review, not an unreviewed report). Larger local models
      (gemma-3-12b, qwen3.5:27b, gemma-3-4e4b) produced 0–1 items and are not
      yet viable; their failed runs are kept under `benchmarks/inventoryflex/`
      as evidence.
- [x] Post-close follow-up (3 Jul 2026): **MoE breaks the dense-model
      ceiling.** On the 8 GB reference card every *dense* local VLM fails
      (≥9B spills and times out; ≤4B fits but is too weak), but the
      Mixture-of-Experts `gemma4:26b` (25.8B, 8-of-128 experts active,
      weights riding 32 GB system RAM) completes the full fixture at
      ~23 tok/s and posts naming 97.4 / condition-exact 91.7 — best of any
      backend including claude. Recall (72.0) and hallucination (23.8) remain
      review-loop territory. New local recommendation:
      `--backend local --model gemma4:26b` where system RAM allows;
      `qwen3.5:9b` stays the lighter default. Run committed at
      `benchmarks/inventoryflex/report-gemma4-26b/`; full analysis in
      [`docs/04`](04-backend-comparison.md).
- [ ] gemma4:26b follow-up — recover defect recall lost to batch timeouts.
      Defect recall (57.7 vs claude's 71.3) is gemma4's weakest metric and
      the one most sensitive to the 5 timeout-skipped batches: defect detail
      lives in the verbose tail of each batch, exactly what truncation cuts.
      The 900s socket timeout is a hardcoded `LocalBackend` default
      (`describe.py`, not passed by the CLI) — add an `HI_TIMEOUT` env knob
      alongside the existing `HI_*` overrides, raise it, and re-run the
      fixture; now that there's a local model worth waiting for, completing
      those batches should be worth several points of defect recall.
- [x] Optional GPU path; YOLOE prompt-free mode evaluation vs text-prompt vocabulary
      (`evals/eval_detect.py`, `--detect-mode`, `--device`; see `evals/README.md`)

## Milestone 4 — Comparison reports (v2 feature)

- [ ] `compare`: align items across two `inventory.json` files (room + name embedding
      match), produce paired-photo delta report
- [ ] Wear-and-tear vs damage classification (prompted rubric, cites TDS guidance)
- [ ] Grade-delta summary table → suggested deduction discussion sheet

## Milestone 5 — Productisation (only if wanted)

- [ ] Web UI (upload, review/edit items inline, export PDF)
- [ ] Mobile guided capture (per-room shot list with live checklist)
- [ ] C2PA / signed manifests; e-signature integration
- [ ] Multi-property management, tenancy metadata, scheme-specific templates

## Risks

| Risk | Mitigation |
|---|---|
| VLM hallucinates items/defects | whole-scene prompts grounded by detector hints; hallucination metric in evals; human review loop |
| Condition grades inconsistent across photos | single rubric in prompt, room-level merge pass, ordinal eval metric |
| CPU-only YOLOE slow on big sets | small seg model, batch, crops cached; detector optional |
| WeasyPrint system deps missing | HTML is the primary artifact; PDF optional, print-to-PDF fallback |
| Adjudicator scepticism of AI reports | report is human-attested: declaration block, reviewer edits, hash manifest of original photos |
