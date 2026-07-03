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

- [x] Run `guide`, capture own property (~15–25 photos/room), run `build --backend claude`
      — done 3 Jul 2026, with a deviation from the plan's wording: capture was a
      single 13-minute 1080p walkthrough **video** split into 10 per-room segments,
      not 15–25 photos/room (the `guide` checklist was consulted, not followed
      shot-by-shot). Raw output frozen at `report/pristine/` before review edits;
      boundary-bleed scan of all 10 rooms, reviewed-copy cleanup, `--trim-lead`
      ingest fix and derived run cost (~$3.30–3.90) in
      [`docs/07`](07-own-property-run.md)
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
- [x] Optional GPU path; YOLOE prompt-free mode evaluation vs text-prompt vocabulary
      (`evals/eval_detect.py`, `--detect-mode`, `--device`; see `evals/README.md`)

## Milestone 4 — Comparison reports (v2 feature)

- [x] `compare`: align items across two `inventory.json` files (room + name embedding
      match), produce paired-photo delta report — done 3 Jul 2026 with a deviation
      from the plan's wording: alignment is room match + **lexical head-noun
      matching** (reusing `merge.py`'s `_head_nouns`/containment, zero API calls);
      the embedding match was **not built** — no fixture showed the synonym-rename
      failure embeddings would solve, while descriptor renames are handled
      lexically (see [`docs/08`](08-compare.md) §1). Numbering drift: docs/05
      calls this comparison milestone "M3" — docs/05 "M3" = this docs/03 "M4".
- [x] Wear-and-tear vs damage classification (prompted rubric, cites TDS guidance)
      — text-only rubric (gpt-5.4-mini via the openai backend; offline →
      `unclassified`), `--tenancy-months`/`--occupancy`/per-item age inputs;
      per-class agreement vs the IMS sample clerk: cleaning 90.0, damage 100.0,
      fair wear and tear 55.6, landlord 85.7 (overall 78.6, n=28, one rubric
      iteration after v1's below-coin-flip FWT class — [`docs/08`](08-compare.md) §4)
- [x] Grade-delta summary table → suggested deduction discussion sheet — item /
      grades / Δ / classification / evidence refs; deliberately **no £ amounts**
      (monetary valuation stays a non-goal; test-enforced — [`docs/08`](08-compare.md) §5)

## Milestone 5 — Productisation (only if wanted)

> **Scope decision, recorded 3 Jul 2026** — user's answer: *"yes you should
> build the web UI and mobile guided capture for now."* Web UI and mobile
> guided capture enter planning (acceptance criteria settled the same day,
> implementer/adversarial-reviewer debate); C2PA/e-signature and
> multi-property management stay deferred — unchecked, reopenable on request.

- [x] Web UI (upload, review/edit items inline, export PDF) — done 3 Jul 2026:
      review/edit inline pre-existed (docs/05 Levels 1–3); M5a added upload
      (`POST /api/photos`, magic-byte-sniffed extensions, 64 MiB cap),
      build-from-browser (`POST /api/build`, `{"confirm": backend}` spend
      guard), PDF export (`/api/pdf` + `/pdf`, 503 hint without WeasyPrint),
      and the redescribe spend-guard retrofit — see
      [`docs/09`](09-web-ui-and-capture.md)
- [ ] Mobile guided capture (per-room shot list with live checklist) —
      **implementation complete 3 Jul 2026, box stays open until the
      real-device smoke is executed and recorded** (`homeinventory capture`:
      token-gated LAN page, camera via plain file input, shot list from
      `guide.py`, uploads into `capture/<Room>/`); **live checklist =
      shot-list tally + local detector coverage check; live AI capture
      guidance remains parked (docs/05 Level 4)**. Real-device smoke
      checklist in [`docs/09`](09-web-ui-and-capture.md) §M5b
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
