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

## Milestone 1 — First real property run (the user's own tenancy)

- [ ] Run `guide`, capture own property (~15–25 photos/room), run `build --backend claude`
- [ ] Review-loop ergonomics: `--room` partial rebuild, `inventory.json` hand-edits
      preserved on rebuild (`--from-json`)
- [ ] Tune the describe prompt on real failures (materials, defect localisation)
- [ ] Build first real eval fixture from this property (label 3 rooms by hand)
- [ ] PDF polish: cover page, page numbers, agent-style layout parity check against a
      sample £165 report

## Milestone 2 — Open-source-only parity

- [ ] `local` describe backend via Ollama (Qwen2.5-VL or best current open VLM)
- [ ] Eval: quantify gap vs `claude` backend on fixtures; document in README
- [ ] Optional GPU path; YOLOE prompt-free mode evaluation vs text-prompt vocabulary

## Milestone 3 — Comparison reports (v2 feature)

- [ ] `compare`: align items across two `inventory.json` files (room + name embedding
      match), produce paired-photo delta report
- [ ] Wear-and-tear vs damage classification (prompted rubric, cites TDS guidance)
- [ ] Grade-delta summary table → suggested deduction discussion sheet

## Milestone 4 — Productisation (only if wanted)

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
