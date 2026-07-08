# Home Inventory AI — Scope, Architecture, UX and Evals

> **Status: active (architecture reference).** Capture UX in §3.3 and §4 is
> **superseded** by the video-first pivot — see
> [`12-video-first-journey.md`](12-video-first-journey.md) and
> [`00-north-star.md`](00-north-star.md). Backend policy: gemini-3.5-flash
> default; opus backup for complex items.

## 1. Problem statement

Letting agents charge ~£165 for a professional inventory / schedule-of-condition report
(~30+ page PDF, room-by-room, dated photos, condition grades). Without one, a landlord or
tenant cannot win a Tenancy Deposit Scheme (TDS) dispute. We want a tool where the user
walks the property with a phone (photos or video), and AI produces a report of equal or
better quality for a fraction of the cost.

**Primary feature (v1):** exhaustive current-condition report from photos/video.
**Secondary feature (v2):** check-in vs check-out comparison report.

## 2. What a TDS-credible report must contain

Derived from industry practice (AIIC / TDS guidance — see `02-research.md`):

- **Room-by-room schedule of condition**, each room covering the fixed fabric
  (ceiling, walls, woodwork, doors, windows, flooring, light fittings, sockets,
  radiators) *and* contents (furniture, appliances, soft furnishings).
- **Per item**: name, material/colour description, **condition grade**, **cleanliness
  grade**, and specific defects ("scuff 10cm left of door handle"), not just "good".
- **Standard vocabulary**: condition `New / Excellent / Good / Fair / Poor`;
  cleanliness `Professionally cleaned / Cleaned to domestic standard / Requires cleaning`.
- **Dated, attributable photographs** linked to the items they evidence.
- **Meter readings, keys, smoke/CO alarms** — adjudicators check these explicitly.
- **Declaration & signature block**, date of inspection, property address.
- **Evidential integrity**: original-file timestamps; we add SHA-256 hashes of every
  source image in an appendix so the photo set is tamper-evident.

Adjudicators weigh *specificity* heavily: "Walls: good, two scuff marks above skirting
left of window" beats a generic grade. This drives the architecture: we need rich
language about condition, not just object labels.

## 3. Architecture

### 3.1 Key design decision: detector + describer, pluggable backends

Object detectors (YOLOE) tell you *what* is present; they cannot grade condition or
write "oak-effect laminate worktop, light scratching near hob". Vision-language models
(VLMs) can. So the pipeline separates two concerns:

- **Detect** (open source, free, local): YOLOE open-vocabulary detection finds and
  crops items of worth → guarantees nothing visible is silently skipped, provides
  evidence crops for the report.
- **Describe** (pluggable): a VLM turns each *photo* (whole scene, with the detection
  list as a hint) into a structured schedule: items, materials, condition grade,
  cleanliness, defects. Backends:
  - `claude` — Claude vision API. Highest accuracy. Cost for a 100-photo flat:
    **well under £1 with Haiku, a few £ with Sonnet** (vs £165 baseline).
  - `local` — an open VLM (Qwen2.5-VL etc. via Ollama/transformers) for the
    fully-open-source scenario. Same prompt contract, zero marginal cost, needs a GPU
    for acceptable speed.
  - `offline` — no VLM at all: YOLOE classes + heuristics only. Degraded descriptions,
    still produces a structurally complete report. Useful for tests/evals/CI.

This satisfies "exclusively open source" as a configuration (`yoloe + local VLM`)
while letting the first user get maximum quality today (`yoloe + claude`).

### 3.2 Pipeline

```
photos / video
   │
   ▼
[1] INGEST      room assignment (folder = room), video → keyframes
   │            (Laplacian sharpness + frame-difference sampling, OpenCV)
   ▼
[2] INTEGRITY   SHA-256 each original, extract EXIF capture time → manifest.json
   │
   ▼
[3] DETECT      YOLOE open-vocab (household vocabulary prompt) → boxes, crops
   │            fallback: whole-image mode if detector unavailable
   ▼
[4] DESCRIBE    VLM per photo (scene + detection hints) → structured JSON:
   │            items[{name, category, description, condition, cleanliness,
   │            defects[], est_value_band}], room-level notes
   ▼
[5] MERGE       de-duplicate items seen in multiple photos of one room
   │            (same room + same name/category → merge, keep best photo)
   ▼
[6] REPORT      inventory.json (canonical data) →
                Jinja2 HTML (print-ready, professional) → PDF (WeasyPrint)
                + appendices: photo schedule, hash manifest, declaration
```

Canonical intermediate: **`inventory.json`** — everything downstream (report,
comparison, evals) consumes this. The v2 comparison feature is `compare(baseline.json,
checkout.json)` plus photo pairs; no pipeline changes needed.

### 3.3 Photos vs video

Both supported at the pipeline level. **Product policy (Jul 2026): one walkthrough
video uploaded in the browser** is the primary capture path — see docs/12. Folder
per-room photos remain supported for benchmarks, CLI power users, and the
InventoryFlex fixture. Video is segmented into rooms automatically; keyframes are
extracted per segment.

## 4. UX

The **web app is the product**; the CLI is plumbing (docs/12). Primary journey:

1. Open `homeinventory review capture/ -o report/` — upload one walkthrough video
2. Confirm spend — build runs invisibly (segment → describe → curate → PDF)
3. Review room-by-room in the browser, fix grades/defects, sign
4. Download the attested PDF

CLI equivalents (`homeinventory build`, folder capture, `--backend openai
--model gemini-3.5-flash`) remain for automation and benchmarks. Human-in-the-loop
review is what makes the report defensible — the tool drafts, the person attests.

Check-in vs check-out comparison is shipped (`homeinventory compare`; docs/08).

## 5. Evals

Quality is the product (an inaccurate report loses an adjudication), so evals are
first-class: `evals/run_eval.py` scores any pipeline configuration against
human-labelled fixtures (`evals/fixtures/<case>/labels.json`).

| Metric | Definition | Target (v1) |
|---|---|---|
| Item recall | % of gold items found (name fuzzy-match within room) | ≥ 90% notable items |
| Hallucination rate | % reported items not in gold | ≤ 5% |
| Naming accuracy | fuzzy/LLM-judge match of item names | ≥ 85% |
| Condition agreement | exact match on 5-point grade | ≥ 70% |
| Condition ±1 | within one grade | ≥ 95% |
| Defect recall | % of gold defects mentioned | ≥ 75% |

Ordinal grades use exact + within-one because human inventory clerks themselves
disagree by one grade routinely. The harness runs identically against `claude`,
`local`, and `offline` backends, so the open-source-only configuration's quality gap
is measured, not guessed. Regression gate: evals run on fixtures in CI (offline
backend deterministic path) + manual full runs before releases.

## 6. Cost model vs the £165 baseline

| | Agent report | This tool (claude backend) | This tool (open source) |
|---|---|---|---|
| Marginal cost | £165 per visit | ≈ £0.30–£3 API spend | £0 |
| User time | hosting the clerk ~1–2h | 30–45 min capture + 20 min review | same |
| Re-runs (checkout) | £165 again | pennies | £0 |

## 7. Out of scope (v1)

- Mobile app / guided in-camera capture (CLI + folder convention instead).
- Automatic room classification (folder names instead).
- Valuation for insurance (we emit a coarse `est_value_band` only).
- Legally binding signatures (report includes a declaration block to sign on paper
  or via any e-sign tool).
