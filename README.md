# homeinventory

AI-assisted **property inventory & schedule of condition** reports — the ~£165
document letting agents sell, built from your own phone footage for pennies.

Film one walkthrough of the property, upload it in the browser, and get a
professional, TDS-style report: rooms segmented automatically, item schedule
with condition and cleanliness grades, localized defect notes, embedded dated
photographs with **timecodes back to the source video**, and a SHA-256 evidence
manifest. The output is a draft for **you** to review and attest — the AI does
the looking and writing, a human signs.

## Quick start

The web app is the product; the CLI is plumbing for power users and automation.

```sh
uv venv
uv pip install -e ".[all,dev]"    # or pick extras: [claude], [detect], [pdf]
# then swap in the right torch build — AFTER the project install, which pulls
# the default build via ultralytics. CUDA on NVIDIA boxes:
uv pip install --reinstall-package torch --reinstall-package torchvision \
    torch torchvision --index-url https://download.pytorch.org/whl/cu128
# CPU-only machines: same command with .../whl/cpu
source .venv/bin/activate         # .venv\Scripts\activate on Windows

# Credentials once — the journey never mentions backends or keys again
cat > .env <<'EOF'
ANTHROPIC_API_KEY=...
# GEMINI_API_KEY=...   # walkthrough segmentation (default gemini-3.5-flash)
EOF

mkdir -p capture report
homeinventory review capture/ -o report/
# → open http://127.0.0.1:8484/
# New report → drop one walkthrough video → confirm the rough cost → wait
# (rooms segmented, items drafted, PDF built — all invisible) → review, sign
```

No API key? Start the review server with `--backend offline` (YOLOE detection
only) or `--backend local` (open-weight VLM via Ollama: `ollama pull qwen3.5:9b`).
Spend confirms in the browser are plain language with a cost estimate, not
backend jargon.

### CLI path (folder of photos or a root walkthrough video)

```sh
homeinventory guide               # what to photograph, room by room

# capture/  Living Room/  Kitchen/  …   — or one video at capture/walkthrough.mp4

homeinventory build capture/ -o report/ \
    --address "Flat 2, 1 Example Street, London" \
    --inspector "Your Name"

open report/inventory.html        # or inventory.pdf
```

Root-level walkthrough videos are segmented into rooms automatically
(`--segment-model gemini-3.5-flash` by default; `--no-segment` to skip).
Cheaper API runs: `--model claude-haiku-4-5`, or `--backend openai` with
`gpt-4.1-mini` / `gemini-3.1-flash-lite`.

## Reviewing — where the report earns its evidential weight

The AI drafts; a human confirms and signs. Three ways in, lightest first
(design rationale in [`docs/05-review-experience.md`](docs/05-review-experience.md)):

1. **The report reviews itself.** `inventory.html` carries a built-in review
   mode: toggle it, click any item to see its claims next to the evidence
   photos, fix grades from dropdowns, strike false defects (kept as
   "reviewer rejected", never silently deleted), confirm items with the
   keyboard (`j`/`k`/`space`/`1–5`), sign, then *Download review file* and
   drop the `inventory.json` in the report folder. Works from a file share
   or phone browser, no server.

2. **The local review app (primary).** `homeinventory review` is the
   video-first product surface — upload, build, review, sign, export, all
   in one browser session:

   ```sh
   homeinventory review capture/ -o report/
   ```

   **Start page** — *New report → type → drop walkthrough video* with filming
   guidance; staged build progress (watching → rooms → drafting → report);
   spend confirms in plain language; PDF produced automatically at build
   completion. Also works **before** the first build: drag-and-drop uploads of
   photos **and walkthrough videos** (streamed `POST /api/upload`, extensions
   from magic bytes, up to 2 GiB).

   **Evidence-room review** — media-first dark stage with the walkthrough as
   the organising spine: chaptered scrub bar (room segments), keyframe ticks,
   *Play this moment* (seeks the source video to the second a frame was
   extracted), filmstrip of cited frames, deep-zoom lightbox with timecodes,
   confidence-sorted queue with text search (`/` or ⌘K) and bulk-accept,
   autosave with undo (⌘Z), per-room coverage panel, add-missed-item with
   photo upload, segment corrections (rename, merge neighbour), report-details
   editor (address, names, reference — they land on the PDF cover), one-click
   *Export PDF* (background job), a *Final issue* link (the report with the
   review instrument stripped, for sending), and *Re-describe room* for after
   you fix a capture problem (hand-edits in that room preserved via
   `--from-json`).

   **Deep-clean projects** — pick "before & after clean" at creation; project
   home has before/after video drop slots; the comparison sheet auto-starts when
   the second session build lands (`--use-case deepclean`).

   **Tenant countersign** (`--share`): prints a token-protected link to open
   on the tenant's phone — they walk the rooms, comment per item, and
   countersign. Comments, signatures (each pinning a SHA-256 of the content
   signed) and a hash-chained `acknowledgements.jsonl` trail are stored with
   the report.

   See [`docs/09-web-ui-and-capture.md`](docs/09-web-ui-and-capture.md),
   [`docs/12-video-first-journey.md`](docs/12-video-first-journey.md), and
   [`docs/14-frontend-craft.md`](docs/14-frontend-craft.md).

3. Prefer raw JSON? Edit `report/inventory.json` directly and re-render without
   re-running the AI:

   ```sh
   homeinventory render capture/ -o report/
   ```

Re-describe one room after fixing photos while keeping review work elsewhere
(and attested items in the rebuilt room):

```sh
homeinventory build capture/ -o report/ --room "Kitchen" --from-json
# or point at a downloaded reviewed copy:
homeinventory build capture/ -o report/ --room "Kitchen" --from-json reviewed.json
```

Before spending API money, `homeinventory check capture/` runs the free local
detector against a per-room checklist ("no radiator seen in Bedroom 2") to
catch coverage gaps while you're still at the property.

## Check-out comparison

At the end of the tenancy, build a check-out report the same way, then
compare it against the check-in:

```sh
homeinventory compare checkin-report/ checkout-report/ -o compare/ \
    --tenancy-months 18 --occupancy "2 adults"
```

`compare/compare.html` (+ `.pdf`) is a **discussion sheet**: a grade-delta
summary (item / check-in grade / check-out grade / Δ / classification /
evidence refs), side-by-side check-in vs check-out photos per changed item
(review-drawn defect boxes overlaid), and explicit "not located" / "new at
check-out" tables. It deliberately contains **no £ amounts** — it frames the
deduction conversation, it doesn't price it.

Items are aligned lexically (room + head-noun match — zero API calls).
Changed items are classified **fair wear and tear / damage / cleaning /
landlord responsibility** by a text-only rubric grounded in TDS guidance
(burden of proof on the landlord, damage must exceed fair wear and tear, no
betterment, condition ≠ cleanliness). The rubric cites only the tenancy
length / occupancy / item age you provide — anything else is "not provided".
Costs well under 1p per compare with gpt-5.4-mini; `--backend offline` skips
classification entirely (changes stay "unclassified"). Rubric agreement with
a professional clerk's published check-out calls is measured per class in
[`docs/08-compare.md`](docs/08-compare.md).

Use-case profiles drive cover copy, comparison rubrics, and report shape:
`tenancy` (check-in/check-out) and `deepclean` (before/after cleaning —
comparison auto-starts from the project home when both videos are built).

## How it works

```
walkthrough video → VLM room segmentation → per-room keyframes
              → SHA-256 manifest → YOLOE open-vocab detection
              → VLM schedule (items, condition, cleanliness, defects, per room)
              → de-dup merge → inventory.json → HTML/PDF report
              → human review (evidence-room or in-report)
              → signatures + acknowledgement trail → attested report
```

- **Segmentation** (API, pennies): thumbnail strip → VLM boundary pass →
  contiguous named room segments. Default `gemini-3.5-flash`; `claude-sonnet-5`
  is the quality alternative. See [`docs/11-video-segmentation.md`](docs/11-video-segmentation.md).
- **Detection** (open source, local): [YOLOE](https://docs.ultralytics.com/models/yoloe/)
  with a household-vocabulary text prompt; provides crops and "don't miss this"
  hints. Optional — the pipeline degrades gracefully without it. Evaluated on the
  InventoryFlex fixture in [`docs/13-yoloe-detection.md`](docs/13-yoloe-detection.md).
  (Note: Ultralytics is AGPL-3.0 — fine for personal use; needs a licence if
  commercialised.)
- **Description** (pluggable): `claude` (Claude vision, structured JSON output,
  well under £1 per property with Haiku), `openai` (OpenAI or any
  OpenAI-compatible API — `--model gemini-3.1-flash-lite` routes to Google
  automatically), `local` (open-weight VLM via Ollama, default qwen3.5:9b,
  £0 per run), or `offline` (detector only).
- **Evidence**: EXIF capture times + SHA-256 of every original in
  `manifest.json` and the report appendix; extracted frames carry
  `seen at m:ss in <video>` provenance back to the walkthrough.

## Cost vs the agent

| | Agent report | homeinventory (claude) | homeinventory (open source) |
|---|---|---|---|
| Marginal cost | £165/visit | ~£0.30–£3 API spend | £0 |
| Re-run at checkout | £165 again | pennies | £0 |

## Docs

- [`docs/01-scope-and-architecture.md`](docs/01-scope-and-architecture.md) — scope, architecture, UX, evals
- [`docs/02-research.md`](docs/02-research.md) — TDS/AIIC standards, YOLOE, VLM condition-grading, competitor gaps
- [`docs/03-implementation-plan.md`](docs/03-implementation-plan.md) — milestones M0 (this prototype) → M5
- [`docs/04-backend-comparison.md`](docs/04-backend-comparison.md) — describe backends on first real footage
- [`docs/05-review-experience.md`](docs/05-review-experience.md) — review UX design space (Levels 0–4) and what's built
- [`docs/06-professional-report-benchmark.md`](docs/06-professional-report-benchmark.md) — pipeline vs a professional clerk's published report (M1)
- [`docs/07-own-property-run.md`](docs/07-own-property-run.md) — first full own-property run (M2)
- [`docs/08-compare.md`](docs/08-compare.md) — check-in vs check-out comparison: alignment, wear-vs-damage rubric, IMS agreement (M4)
- [`docs/09-web-ui-and-capture.md`](docs/09-web-ui-and-capture.md) — web UI delta (M5a); guided capture retired (M5b)
- [`docs/10-product-quality-review.md`](docs/10-product-quality-review.md) — product-quality pass: PDF evidence chain, unified web app
- [`docs/11-video-segmentation.md`](docs/11-video-segmentation.md) — room segmentation from one walkthrough video: six-model benchmark
- [`docs/12-video-first-journey.md`](docs/12-video-first-journey.md) — **plan of record**: video-first journey pivot, done/remaining/acceptance criteria
- [`docs/13-yoloe-detection.md`](docs/13-yoloe-detection.md) — YOLOE detection eval on InventoryFlex; impact on describe scores
- [`docs/14-frontend-craft.md`](docs/14-frontend-craft.md) — evidence-room review design principles (Frame.io, player craft, InventoryBase)
- [`evals/README.md`](evals/README.md) — fixture format and quality metrics

## Status

M0 prototype, plus the full review stack from
[`docs/05`](docs/05-review-experience.md): in-report review mode, local
review server (`homeinventory review`), tenant comment-and-countersign
(`--share`), and the pre-build coverage check (`homeinventory check`).
M1 (benchmark against a professional clerk's published report) is done —
see [`docs/06`](docs/06-professional-report-benchmark.md). **M3 (open-source
parity) is closed** — all three backends are scored against the gold fixture
in [`docs/04`](docs/04-backend-comparison.md): `claude` is the quality
ceiling (hallucination 2.8%, condition-exact 93%), `openai` gpt-5.4-mini is
the cheap-iteration pick (recall 90.7% but ~5× claude's hallucination), and
the `local` backend has two viable £0 paths: `qwen3.5:9b` (lighter), or the
**MoE `gemma4:26b`** — naming 97.4% and grading 91.7% (best of any backend
including claude), ~23 tok/s on an 8 GB GPU + 32 GB RAM box, a genuine
**draft for review** rather than an unreviewed report. Dense models ≤4B fit
the card but are too weak; MoE sidesteps that by riding system RAM for the
weights. **`gemini-3.5-flash` describe eval is recorded** (July 2026): clears
the hallucination ceiling but sits ~21 pts below claude on condition-exact —
so it is the **segmentation default**, not the signed-output describe default.
**M4 (check-in vs check-out comparison) is shipped** — `homeinventory
compare` aligns the two reports lexically, classifies deteriorations with a
TDS-grounded wear-vs-damage rubric (per-class agreement vs a professional
clerk's published check-out in [`docs/08`](docs/08-compare.md)), and renders
a paired-photo grade-delta discussion sheet; the defect-region annotations
captured at review are its evidence anchors. Use-case profiles (`tenancy`,
`deepclean`) drive cover copy, rubrics, and the deep-clean project home.
**M2 (first real property) ran 3 Jul 2026** — a 13-minute walkthrough video
through the full pipeline (10 rooms, 322 raw items, ≈$3.3 of opus), with the
raw output frozen for evals, an all-room boundary-bleed audit, and the
`--trim-lead` ingest fix that came out of it ([`docs/07`](docs/07-own-property-run.md));
the own-property eval fixture and native-res prompt-tuning gate remain open
pending hand labelling.
**M5 (video-first product) shipped 4–5 Jul 2026** — product pivot recorded
in [`docs/12`](docs/12-video-first-journey.md): phone guided capture (M5b)
was tried on a real device, killed, and removed; the web app is the product.
Landed: walkthrough upload → VLM segmentation → staged build → auto-PDF;
deep-clean before/after project flow; `.env` credential loading; plain-language
spend confirms; segment corrections in review. **Evidence-room review**
([`docs/14`](docs/14-frontend-craft.md)): video-native stage, walkthrough
spine with chaptered scrub bar, *Play this moment* seeking, timecoded exhibits
in report/PDF/manifest. **Paper-world surfaces** (5 Jul 2026): start hero,
project home, report identity pass, exhibit timecodes throughout. **YOLOE
detection eval** documented in [`docs/13`](docs/13-yoloe-detection.md).
C2PA/e-signature, hosted login, and multi-property stay deferred
([`docs/03`](docs/03-implementation-plan.md)). **Still open:** first-tester
run (owner drives real tenancy + cleaning jobs; friction log).

**Product-quality pass, 3 Jul 2026** ([`docs/10`](docs/10-product-quality-review.md)):
the PDF's evidence chain now closes end-to-end (item → photo refs → Appendix
B IDs → Appendix A hashes, defect pins printed, no machine paths), the web
surfaces share one design system with autosave/undo, a lightbox, working
mobile layout and video upload — and template autoescaping, silently off
since M0, is on.

## Disclaimer

This tool drafts inventory reports; it is not legal advice. TDS adjudicators weigh
signed, dated, specific evidence — review every AI-generated entry before signing,
and have all parties sign at check-in.
