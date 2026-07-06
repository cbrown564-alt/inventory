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
- [ ] gemma4:26b follow-up — recover defect recall lost to repetition-loop
      batch skips. Defect recall (57.7 vs claude's 71.3) is gemma4's weakest
      metric. The InventoryFlex run (`report-gemma4-26b.log`) skipped **8 of
      34 batches**, all failing `unterminated JSON object` after the temp-0.3
      retry. A direct probe of the deterministically-failing Bathroom batch
      (`p14_i00..02`) against gemma4:26b found the true cause: **`done_reason:
      length`, `eval_count: 12288`, content tail `panel-st/panel-st/panel-st/…`**
      — at temperature 0 the model falls into a token repetition loop and emits
      garbage until the `num_predict` ceiling force-stops it, so the JSON is
      never closed. (The `HI_REPEAT_PENALTY` comment in `describe.py` documents
      this exact failure mode for qwen2.5vl:3b; gemma4:26b hits a stubborn
      variant of it.) This is **not** a socket timeout (zero `timed out` in the
      run; ~76s/batch at 23 tok/s) and **not** healthy-output truncation.
      Empirically falsified levers: (a) `HI_BATCH_SIZE=3` — the same Bathroom
      batch fails deterministically at bs3 too (probe + an attempted bs3 run,
      log kept at `report-gemma4-26b-bs3-incomplete.log`, never completed);
      (b) `HI_TIMEOUT` — nothing timed out. The real lever is sampling: a
      higher `HI_REPEAT_PENALTY` and/or non-zero `HI_TEMPERATURE` to break the
      loop, with `done_reason` checked in code (a `length` stop with a repeated
      token tail should be retried at higher penalty rather than skipped). The
      skipped batches drop items outright (Reception lost 3/15, Entrance Hall
      1/5), which mechanically depresses both item and defect recall, so
      recovering them is the cheapest available win.
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

- [x] Web UI (upload, review/edit items inline, export PDF) — M5a landed
      3 Jul 2026 (see [`docs/09`](09-web-ui-and-capture.md)): upload
      (`POST /api/photos`, magic-byte-sniffed extensions, 64 MiB cap),
      build-from-browser (`POST /api/build`, `{"confirm": backend}` spend
      guard), PDF export routes, redescribe spend-guard retrofit.
      **Re-opened and re-closed the same day by the product-quality pass
      ([`docs/10`](10-product-quality-review.md))** — the original box shipped
      `/api/pdf` with no UI control reaching it and a PDF whose evidence
      chain was broken; definition-of-done lesson recorded in docs/10 §6
- [x] Product-quality pass on web UI + PDF flow, 3 Jul 2026
      ([`docs/10`](10-product-quality-review.md)) — evidence chain repaired in
      print (item→photo refs, Appendix B photo IDs, printed defect pins,
      relative paths + full hashes); report-details editor + report/PDF
      navigation; one design system (shared `_theme.css.j2`/`_ui.js.j2`, no
      CDN fonts, real modals, de-jargoned copy); autosave + undo; PDF export
      as a background job with a visible button; evidence lightbox with
      zoom + full-res pinning; mobile layout fix; drag-and-drop parallel
      uploads incl. **video** (`POST /api/upload`, streamed, 2 GiB cap);
      Jinja autoescape enabled everywhere (was silently off — `.html.j2`
      never matched `select_autoescape(["html"])`)
- [x] ~~Mobile guided capture (per-room shot list with live checklist)~~ —
      **closed as REMOVED, 4 Jul 2026.** Implementation completed 3 Jul; the
      real-device test happened and the user killed the feature: the guided
      per-room photo flow was a bad experience on a phone. Product pivot
      recorded the same day: the primary capture path is **one walkthrough
      video uploaded in the browser**, with room segmentation handled by the
      pipeline. Retirement note in [`docs/09`](09-web-ui-and-capture.md) §M5b
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
