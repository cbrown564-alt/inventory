# homeinventory

AI-assisted **property inventory & schedule of condition** reports — the ~£165
document letting agents sell, built from your own phone photos (or video) for
pennies.

Walk the property, drop photos into one folder per room, run one command, and get
a professional, TDS-style report: room-by-room item schedule with condition and
cleanliness grades, localized defect notes, embedded dated photographs, and a
SHA-256 evidence manifest. The output is a draft for **you** to review and attest —
the AI does the looking and writing, a human signs.

## Quick start

```sh
pip install -e ".[all]"           # or pick extras: [claude], [detect], [pdf]
homeinventory guide               # what to photograph, room by room

# capture/  Living Room/  Kitchen/  Bedroom 1/ ...   (photos and/or videos)

export ANTHROPIC_API_KEY=...      # for the best-quality describe backend
homeinventory build capture/ -o report/ \
    --address "Flat 2, 1 Example Street, London" \
    --inspector "Your Name"

open report/inventory.html        # or inventory.pdf
```

No API key? `--backend local` runs an open-weight VLM through Ollama
(`ollama pull qwen3.5:9b`), or `--backend offline` skips AI description
entirely (YOLOE detection only). Cheaper API runs: `--model claude-haiku-4-5`,
or `--backend openai` with `gpt-4.1-mini` / `gemini-3.1-flash-lite`.

## Reviewing — where the report earns its evidential weight

The AI drafts; a human confirms and signs. Three ways in, lightest first
(design rationale in [`docs/05-review-experience.md`](docs/05-review-experience.md)):

1. **The report reviews itself.** `inventory.html` carries a built-in review
   mode: toggle it, click any item to see its claims next to the evidence
   photos, fix grades from dropdowns, strike false defects (kept as
   "reviewer rejected", never silently deleted), confirm items with the
   keyboard (`j`/`k`/`space`/`1–5`), sign, then *Download reviewed
   inventory.json* and drop it in the report folder. Works from a file share
   or phone browser, no server.

2. **The local review app.** Saves straight back to `inventory.json` —
   no download/move loop — and adds what a static page can't:

   ```sh
   homeinventory review capture/ -o report/
   ```

   Confidence-sorted queue with bulk-accept, drag-a-box defect annotation on
   photos, per-room coverage panel (photos no item cites), add-missed-item
   with photo upload, and a *Re-describe room* button for after you fix a
   capture problem.

3. **The tenant countersigns** (`--share`): prints a token-protected link to
   open on the tenant's phone — they walk the rooms, comment per item
   ("the carpet stain was already there"), and countersign. Comments,
   signatures (each pinning a SHA-256 of the content signed) and a
   hash-chained `acknowledgements.jsonl` trail are stored with the report.
   An inventory signed by both parties carries maximum adjudication weight.

Prefer raw JSON? Edit `report/inventory.json` directly and re-render without
re-running the AI:

```sh
homeinventory render capture/ -o report/
```

Before spending API money, `homeinventory check capture/` runs the free local
detector against a per-room checklist ("no radiator seen in Bedroom 2") to
catch coverage gaps while you're still at the property.

## How it works

```
photos / video → keyframes → SHA-256 manifest → YOLOE open-vocab detection
              → VLM schedule (items, condition, cleanliness, defects, per room)
              → de-dup merge → inventory.json → HTML/PDF report
              → human review (in-report or `homeinventory review`)
              → signatures + acknowledgement trail → attested report
```

- **Detection** (open source, local): [YOLOE](https://docs.ultralytics.com/models/yoloe/)
  with a household-vocabulary text prompt; provides crops and "don't miss this"
  hints. Optional — the pipeline degrades gracefully without it. (Note: Ultralytics
  is AGPL-3.0 — fine for personal use; needs a licence if commercialised.)
- **Description** (pluggable): `claude` (Claude vision, structured JSON output,
  well under £1 per property with Haiku), `openai` (OpenAI or any
  OpenAI-compatible API — `--model gemini-3.1-flash-lite` routes to Google
  automatically), `local` (open-weight VLM via Ollama, default qwen3.5:9b,
  £0 per run), or `offline` (detector only).
- **Evidence**: EXIF capture times + SHA-256 of every original in
  `manifest.json` and the report appendix, so the photo set is tamper-evident.

## Cost vs the agent

| | Agent report | homeinventory (claude) | homeinventory (open source) |
|---|---|---|---|
| Marginal cost | £165/visit | ~£0.30–£3 API spend | £0 |
| Re-run at checkout | £165 again | pennies | £0 |

## Docs

- [`docs/01-scope-and-architecture.md`](docs/01-scope-and-architecture.md) — scope, architecture, UX, evals
- [`docs/02-research.md`](docs/02-research.md) — TDS/AIIC standards, YOLOE, VLM condition-grading, competitor gaps
- [`docs/03-implementation-plan.md`](docs/03-implementation-plan.md) — milestones M0 (this prototype) → M4
- [`docs/04-backend-comparison.md`](docs/04-backend-comparison.md) — describe backends on first real footage
- [`docs/05-review-experience.md`](docs/05-review-experience.md) — review UX design space (Levels 0–4) and what's built
- [`evals/README.md`](evals/README.md) — fixture format and quality metrics

## Status

M0 prototype, plus the full review stack from
[`docs/05`](docs/05-review-experience.md): in-report review mode, local
review server (`homeinventory review`), tenant comment-and-countersign
(`--share`), and the pre-build coverage check (`homeinventory check`).
The v2 feature — check-in vs check-out **comparison reports**
(`homeinventory compare`) — is scoped in the implementation plan,
milestone 3; the defect-region annotations captured at review are its
alignment anchors.

## Disclaimer

This tool drafts inventory reports; it is not legal advice. TDS adjudicators weigh
signed, dated, specific evidence — review every AI-generated entry before signing,
and have all parties sign at check-in.
