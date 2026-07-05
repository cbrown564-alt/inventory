# 21 — ML/DL experiment log

*5 Jul 2026. Status tracker for ML-E1–E20 in docs/19. Each spike must
produce inspectable artifacts (contact sheets or JSON metrics) before
adoption. Hero heuristic experiments (E0–E5) stay in docs/18.*

## Summary

| ID | Status | Pass bar | Actual (committed) | Artifact |
|---|---|---|---|---|
| **ML-E1** | fail | ≤3 s mean boundary error | 291.2 s mean (399 frames @ 2 s; DINOv2; 9/9 cuts) | `evals/fixtures/own-property/segment-embed.html` |
| **ML-E2** | not started | Bleed items ↓ vs baseline | — | — |
| **ML-E3** | harness ready | Describe recall unchanged; tokens ↓ | — | `evals/eval_describe_pool.py` |
| **ML-E4** | fail | mean Spearman ρ ≥ 0.66 (E5) | ρ −0.21 (SigLIP); top-3 22% (9 rooms, 93 frames) | `hero-contact-siglip.html` |
| **ML-E5** | fail | top-3 hit ≥ 100% (E5) | top-3 56%; top-1 33%; ρ 0.41 (9 rooms) | `hero-contact-mslap.html` |
| **ML-E6** | fail | top-1 ≥ 8/9 on hero-gold | top-1 4/9; top-3 67%; train ρ vs MUSIQ 0.74 (260 frames) | `iqa-linear-weights.json`, `hero-contact-linear-musiq.html` |
| **ML-E7** | fail | top-1 ≥ 7/9; <100 ms/frame | top-1 2/9; top-3 56%; 589 ms/frame (OpenCLIP CPU) | `hero-contact-clip-establishing.html` |
| **ML-E8** | not started | top-1 = 9/9 or unanimous eyeball | — | — |
| **ML-E9** | not started | Pause frames in gold top-3 ≥80% | — | — |
| **ML-E10** | fail | Recall ↑, noise ≤ YOLOE text | Notable recall +17.3 pp (76.0%); unmatched +13.8 pp (79.6%) | `evals/fixtures/inventoryflex/detect-comparison-gdino.json` |
| **ML-E11** | pass | 50–100 verified boxes, 2 rooms | **101 verified** (19 Bath, 82 Kitchen); bootstrap v2 + agent trim + human review | `labels_boxes.json`, `bbox-review/` |
| **ML-E12** | not started | +10 pp recall @0.5 IoU | — | — |
| **ML-E13** | not started | ρ with establishing gold | — | — |
| **ML-E14** | not started | — (exploratory) | — | — |
| **ML-E15** | not started | FP rate <10% on IFlex | — | — |
| **ML-E16** | not started | Wrong-room bleed ↓ on audit | — | — |
| **ML-E17** | not started | top-1 ≥ ML-E6 on hero-gold | — | — |
| **ML-E18** | not started | Recall ↑ vs ML-E10 baseline | — | — |
| **ML-E19** | fail | mean Spearman ρ ≥ E5 classical | ρ 0.07 vs cover 0.44 (9 rooms); 579 ms/frame (OpenCLIP CPU) | `hero-contact-shotscale.html` |
| **ML-E20** | not started | FP <10% on IFlex | — | — |

**Counts (5 Jul 2026):** 7 fail · 1 pass · 1 harness ready · 11 not started.

## Global blockers

| Blocker | Affects |
|---|---|
| **`examples/videos/IMG_5512.MOV` not in repo** (~1.3 GB) | CI / fresh clones only — local runs OK |
| **`torch` / encoder deps** | Install with `uv pip install open-clip-torch`; SigLIP needs transformers API fix in `ml_scorers.py` |
| **External datasets not downloaded** (`evals/external/data/`) | ML-E16–E18, ML-E20 |
| **No paired check-in/out fixture** | ML-E14 |

Rebuild own-property fixture (when video present):

```bash
uv run python -m homeinventory.cli build capture-walkthrough -o report \
  --segments-json segment-spike-multi/gemini-3.5-flash/segments.json
```

---

## Per-experiment notes

### ML-E1 — embedding changepoint segmentation

- **Harness:** `evals/eval_segment_embed.py` (+ `evals/ml_scorers.py` encoders)
- **Gold:** `evals/fixtures/own-property/segment-gold.json` (10-room manual cut; timestamps approximate)
- **Run (5 Jul 2026):** `IMG_5512.MOV --encoder dinov2 --every 2` — 399 frames, 28 detected peaks
- **Result:** mean boundary error **291.2 s** vs 9 manual cuts; **pass: false** (bar ≤3 s)
- **Note:** DINOv2 transform must use timm `resolve_model_data_config` (518×518, not 224)

### ML-E2 — VLM refine ±30 s windows

- **Status:** not started — no harness or artifact
- **Depends on:** production bleed audit after ML-E1 baseline

### ML-E3 — two-tier describe vs presentation pools

- **Harness:** `evals/eval_describe_pool.py`
- **Implementation:** `tier_eligibility()` in `homeinventory/curate.py`
- **Blocked:** needs `report/inventory.json` with video-sourced frames

### ML-E4 — SigLIP / OpenCLIP relevance margin

- **Harness:** `evals/eval_relevance_siglip.py` → `eval_hero_cover.py --scorer siglip`
- **Run (5 Jul 2026):** full `report/` — 9 rooms, 93 video frames, SigLIP CPU
- **Result:** mean Spearman **−0.21** (bar ≥0.66); top-1 **11%**, top-3 **22%**; **pass: false**
- **Artifact:** `evals/fixtures/own-property/hero-contact-siglip.html`

### ML-E5 — multi-scale Laplacian ratio

- **Harness:** `evals/eval_mslap_cover.py` → `eval_hero_cover.py --scorer mslap`
- **Run (5 Jul 2026):** full `report/` — 9 rooms, 93 frames
- **Result:** top-3 **56%**, top-1 **33%**, mean Spearman **0.41**; **pass: false** (bar top-3 100%)
- **Artifact:** `evals/fixtures/own-property/hero-contact-mslap.html`

### ML-E6 — linear model → MUSIQ rank

- **Harness:** `evals/train_iqa_linear.py`; scorer via `eval_hero_cover.py --scorer linear-musiq`
- **Run (5 Jul 2026):** ridge on 260 resolved frames (`mode: features`); hero-gold eval on full `report/`
- **Training:** Spearman pred vs MUSIQ **0.74**
- **Hero-gold:** top-1 **4/9**, top-3 **6/9**, mean Spearman **0.39**; **pass: false** (bar ≥8/9)
- **Artifacts:** `iqa-linear-weights.json`, `hero-contact-linear-musiq.html`

### ML-E7 — CLIP prompt pairs

- **Harness:** `eval_hero_cover.py --scorer clip-establishing` (OpenCLIP ViT-B/32, Apache-2.0)
- **Run (5 Jul 2026):** full `report/` — 9 rooms, 93 frames, CPU
- **Result:** top-1 **2/9**, top-3 **56%**, mean Spearman **0.19**, **589 ms/frame**; **pass: false**
- **Artifact:** `evals/fixtures/own-property/hero-contact-clip-establishing.html`

### ML-E8 — VLM top-10 rerank

- **Status:** not started — Phase 3 gate (docs/19 G6)

### ML-E9 — optical-flow pause detection

- **Status:** not started — depends on capture UX guidance (docs/18 I)

### ML-E10 — Grounding DINO vs YOLOE text

- **Harness:** `evals/eval_detect_gdino.py` (+ `evals/gdino_detect.py`)
- **Fixture:** InventoryFlex capture present; committed CPU run 2026-07-05
- **YOLOE text:** notable recall **58.7%**, unmatched **65.8%**
- **Grounding DINO:** notable recall **76.0%** (+17.3 pp), unmatched **79.6%** (+13.8 pp)
- **Verdict:** **fail** pass bar — recall gain but noise exceeds text mode; keep YOLOE default (G3 not met)
- **Reference:** `detect-comparison.json` (YOLOE-only baseline)

### ML-E11 — bbox gold subset

- **Harness:** `evals/label_boxes.py` (bootstrap, trim-consensus, carousel, validate)
- **Run (5 Jul 2026):** bootstrap v2 (`det_match.py` routing) → agent consensus trim → 60-box human carousel review
- **Result:** **101 verified boxes** (19 Bathroom, 82 Kitchen); **pass: true**
- **Artifacts:** `labels_boxes.json`, `bbox-review/` (agent + human review JSON, carousel HTML)
- **Note:** Generic `ceiling`/flooring skipped; `ceiling light` routes to spotlights/pendants; ML-E12 unblocked

### ML-E12 — fine-tune probe

- **Status:** not started — ML-E11 gold committed; ready to run

### ML-E13 — SegFormer floor+wall fraction

- **Status:** not started — deferred until cover/detection pass bars (docs/19 §1.5)

### ML-E14 — Siamese pairs (compare)

- **Status:** not started — no paired visit fixture

### ML-E15 — anomaly pre-filter (zero-shot)

- **Status:** not started

### ML-E16 — room-type classifier (Indoor67 → 10)

- **Status:** not started
- **Data:** download per `evals/external/README.md` (HF indoor-scene-classification)

### ML-E17 — KonIQ-10k → ONNX distill

- **Status:** not started
- **Data:** KonIQ-10k registration download; `evals/export_onnx.py` stub only

### ML-E18 — Open Images V7 household pretrain

- **Status:** not started
- **Data:** filtered OI download per `evals/external/README.md`

### ML-E19 — shot-scale (long vs close-up)

- **Harness:** `evals/eval_shot_scale.py`
- **Run (5 Jul 2026):** full `report/` — **9/9 hero-gold rooms**, 93 frames, OpenCLIP CPU
- **Result:** mean Spearman shot-scale **0.07** vs cover **0.44**; **pass: false**; **579 ms/frame**
- **Artifact:** `evals/fixtures/own-property/hero-contact-shotscale.html`

### ML-E20 — StructDamage/BD3 defect pre-filter

- **Status:** not started
- **Data:** BD3 / StructDamage per docs/19 §2.4 Tier C

---

## Related files

| Path | Role |
|---|---|
| `docs/19-ml-dl-exploration-plan.md` | Plan, pass bars, phased sequence |
| `docs/18-hero-image-selection.md` | Product cover scorer (E5) and hero-gold |
| `evals/README.md` | How to run every eval script |
| `evals/external/README.md` | Tier A dataset downloads (ML-E16–E20) |
| `evals/splits/inventoryflex.json` | Room-held-out protocol |

## Definition of done (this doc)

- [x] ML-E1–E20 status row with pass bar and committed result where known
- [x] Blockers documented (video, report, torch, external data, ML-E11)
- [x] Re-run ML-E1, ML-E4–E7, ML-E19 on full IMG_5512 `report/` when video available
- [x] ML-E6 hero-gold top-1 after `train_iqa_linear.py --report report`
- [x] ML-E11 ≥50 verified boxes committed
