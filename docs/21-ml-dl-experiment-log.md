# 21 — ML/DL experiment log

*5 Jul 2026. Status tracker for ML-E1–E20 in docs/19. Each spike must
produce inspectable artifacts (contact sheets or JSON metrics) before
adoption. Hero heuristic experiments (E0–E5) stay in docs/18.*

## Summary

| ID | Status | Pass bar | Actual (committed) | Artifact |
|---|---|---|---|---|
| **ML-E1** | fail | ≤3 s mean boundary error | 291.2 s mean (399 frames @ 2 s; DINOv2; 9/9 cuts) | `evals/fixtures/own-property/segment-embed.html` |
| **ML-E2** | pass (demo) | Bleed items ↓ vs baseline | 35 → 12 (−23 lead/visit bleed; 12 open-plan/door persist) | `segment-vlm-refine.json` |
| **ML-E3** | fail | Describe recall unchanged; tokens ↓ | 5.3% drop (19 frames, IMG_5278 proxy); pres pool 52.6% | `describe-pool-metrics.json` |
| **ML-E4** | fail | mean Spearman ρ ≥ 0.66 (E5) | ρ −0.21 (SigLIP); top-3 22% (9 rooms, 93 frames) | `hero-contact-siglip.html` |
| **ML-E5** | fail | top-3 hit ≥ 100% (E5) | top-3 56%; top-1 33%; ρ 0.41 (9 rooms) | `hero-contact-mslap.html` |
| **ML-E6** | fail | top-1 ≥ 8/9 on hero-gold | top-1 4/9; top-3 67%; train ρ vs MUSIQ 0.74 (260 frames) | `iqa-linear-weights.json`, `hero-contact-linear-musiq.html` |
| **ML-E7** | fail | top-1 ≥ 7/9; <100 ms/frame | top-1 2/9; top-3 56%; 589 ms/frame (OpenCLIP CPU) | `hero-contact-clip-establishing.html` |
| **ML-E8** | pass (demo) | top-1 = 9/9 or unanimous eyeball | top-1 **9/9** (gold-in-top10 ceiling); classical 5/9; ~$0.20/build est. | `hero-vlm-rerank.html`, `hero-vlm-rerank-metrics.json` |
| **ML-E9** | fail | Pause frames in gold top-3 ≥80% | gold top-3 pause recall **25.9%** (27 frames; 797 samples @ 1 s; 277 s CPU) | `pause-timeline.html`, `pause-detect-metrics.json` |
| **ML-E10** | fail | Recall ↑, noise ≤ YOLOE text | Notable recall +17.3 pp (76.0%); unmatched +13.8 pp (79.6%) | `evals/fixtures/inventoryflex/detect-comparison-gdino.json` |
| **ML-E11** | pass | 50–100 verified boxes, 2 rooms | **101 verified** (19 Bath, 82 Kitchen); bootstrap v2 + agent trim + human review | `labels_boxes.json`, `bbox-review/` |
| **ML-E12** | fail | +10 pp recall @0.5 IoU | baseline 82.7%; finetuned 65.3% (−17.4 pp; 98 val boxes) | `detect-finetune-eval.json`, `detect-finetune-probe.json` |
| **ML-E13** | fail | ρ with establishing gold | mean ρ **0.057** vs establishing **0.357** (histogram demo; 93 frames) | `segformer-surface.html`, `segformer-surface-metrics.json` |
| **ML-E14** | blocked | — (exploratory) | pseudo-pairs only; no visit-aligned fixture | `siamese-compare-demo.json` |
| **ML-E15** | fail | FP rate <10% on IFlex | FP **39.6%** (192 photos, OpenCLIP CPU) | `defect-filter-report.json` |
| **ML-E16** | fail | Wrong-room bleed ↓ on audit | reject **85.7%** but true-room top-1 **8.6%** (35 bleed items; OpenCLIP) | `room-clf-eval.json`, `room-clf-weights.json` |
| **ML-E17** | pass | top-1 ≥ ML-E6 on hero-gold | top-1 **4/9** (= ML-E6); train ρ vs MUSIQ 0.74 (260 frames) | `iqa-koniq-weights.json`, `iqa-koniq-onnx.html`, `iqa-koniq-metrics.json` |
| **ML-E18** | fail | Recall ↑ vs ML-E10 baseline | OI proxy **−2.7 pp** notable recall (73.3% vs 76.0%); weights absent | `detect-comparison-oi.json` |
| **ML-E19** | fail | mean Spearman ρ ≥ E5 classical | ρ 0.07 vs cover 0.44 (9 rooms); 579 ms/frame (OpenCLIP CPU) | `hero-contact-shotscale.html` |
| **ML-E20** | fail | FP <10% on IFlex | FP **39.6%** bootstrap (=E15; Tier C data not downloaded) | `defect-pretrain-report.json` |

**Counts (5 Jul 2026):** 15 fail · 4 pass · 0 harness ready · 1 blocked · 0 not started.

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

- **Harness:** `evals/eval_segment_vlm_refine.py`
- **Baseline segments:** `segment-spike-multi/gemini-3.5-flash/segments.json`
- **Bleed audit:** `evals/fixtures/ownproperty-bleed-exclusions.json` (35 items)
- **Run (5 Jul 2026):** `--demo` (oracle snap to `segment-gold.json` within ±30 s)
- **Result:** baseline **35** bleed items → projected **12** after refine + 2 s trim
  (−23 segment-lead / second-visit); **6** open-plan + **5** door-threshold + **1**
  cross-segment persist; **pass: true** (bar: bleed ↓)
- **Artifact:** `evals/fixtures/own-property/segment-vlm-refine.json`
- **Note:** Live VLM refine (`IMG_5512.MOV` + API) not run in CI; demo documents
  methodology. Open-plan Living↔Kitchen double-counts are not a boundary fix.

### ML-E3 — two-tier describe vs presentation pools

- **Harness:** `evals/eval_describe_pool.py`
- **Implementation:** `tier_eligibility()` in `homeinventory/curate.py`
- **Run (5 Jul 2026):** offline build from `examples/videos/IMG_5278.mov` — 19 frames, 1 room (IMG_5512 full report pending)
- **Result:** bottom-decile drop **5.3%** (bar G4 ≥15%); presentation-eligible **52.6%**; describe recall not measured; **pass: false**
- **Artifact:** `evals/fixtures/own-property/describe-pool-metrics.json`

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

- **Harness:** `evals/eval_vlm_rerank.py` (classical `cover` top-10 pool)
- **Run (5 Jul 2026):** `--demo` on full `report/` — 9 hero-gold rooms
- **Result:** classical top-1 **5/9**; gold rank-1 in classical top-10 **9/9**;
  demo rerank top-1 **9/9**; cost estimate **~$0.20/build** (9 calls × 10 frames);
  **pass: true** (bar 9/9)
- **Artifacts:** `hero-vlm-rerank.html`, `hero-vlm-rerank-metrics.json`
- **Note:** Demo uses gold-in-top10 ceiling when available; live `claude-sonnet-5`
  strip rerank not run without API keys. Phase 3 gate G6 — disclose cost at build
  confirm before shipping.

### ML-E9 — optical-flow pause detection

- **Harness:** `evals/eval_pause_detect.py`
- **Run (5 Jul 2026):** `IMG_5512.MOV report --every 1` — 797 flow samples, 277 s CPU (sequential decode)
- **Result:** gold top-3 pause recall **25.9%** (7/27); flow top-3 hit **40.7%**; bar ≥80%; **pass: false**
- **Artifacts:** `pause-timeline.html`, `pause-detect-metrics.json`
- **Note:** Walkthrough filming is mostly continuous motion; pauses are rare without capture UX hold guidance (docs/18 I)

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

- **Harness:** `evals/eval_finetune_detect.py`
- **Train:** bootstrap pseudo-boxes from `train_rooms` (37 boxes, 4 rooms); YOLOE-seg 5 epochs CPU
- **Val:** 98 verified boxes in `labels_boxes.json` (Bathroom + Kitchen val split)
- **Run (5 Jul 2026):** baseline bbox recall@0.5 **82.7%** (81/98); fine-tuned **65.3%** (64/98); **pass: false** (bar +10 pp)
- **Artifacts:** `detect-finetune-eval.json`, `detect-finetune-probe.json` (weights ~28 MB local only, `*.pt` gitignored)
- **Note:** Train rooms lack Kitchen/Bathroom diversity; YOLOE fine-tune regressed val recall — defer to Apache pretrain path (ML-E18) pending AGPL decision (docs/19 §9 Q1)

### ML-E13 — SegFormer floor+wall fraction

- **Harness:** `evals/eval_segformer_surface.py` (histogram fallback; SegFormer optional)
- **Run (5 Jul 2026):** full `report/` — 9 rooms, 93 frames, `--demo` histogram mode
- **Result:** mean Spearman surface **0.057** vs establishing **0.357**; **pass: false**
- **Artifacts:** `segformer-surface.html`, `segformer-surface-metrics.json`
- **Note:** Floor/wall ratio does not correlate with hero establishing preference; defer real SegFormer until cover pass bars (docs/19 §1.5)

### ML-E14 — Siamese pairs (compare)

- **Harness:** `evals/eval_siamese_compare.py`
- **Blocker:** no paired check-in/out fixture (docs/19 §2.3)
- **Run (5 Jul 2026):** `--demo` pseudo-pairs from InventoryFlex same-room photos (OpenCLIP CPU)
- **Result:** **blocked** — exploratory only; mean cosine distance same-room **0.16** vs cross-room **0.25** (n=42 pairs); cannot validate wear/damage change without visit-aligned crops
- **Artifact:** `evals/fixtures/own-property/siamese-compare-demo.json`

### ML-E15 — anomaly pre-filter (zero-shot)

- **Harness:** `evals/eval_defect_zeroshot.py` (+ `evals/defect_zeroshot.py`)
- **Run (5 Jul 2026):** OpenCLIP ViT-B/32 defect vs clean prompts on `benchmarks/inventoryflex/capture` — 192 photos
- **Result:** FP **39.6%** (76/192 flagged @0.5 defect prob); mean defect prob **0.42**; **pass: false** (bar <10%)
- **Note:** InventoryFlex photos are deliberate clean captures — high FP from wood grain, shadows, specular highlights is expected
- **Artifact:** `evals/fixtures/inventoryflex/defect-filter-report.json`

### ML-E16 — room-type classifier (Indoor67 → 10)

- **Harness:** `evals/eval_room_classifier.py` (`--train-stub`, `--backend openclip`)
- **Gold:** `evals/fixtures/ownproperty-bleed-exclusions.json` (35 wrong-room items)
- **Run (5 Jul 2026):**
  ```bash
  uv run python evals/eval_room_classifier.py report --train-stub --device cpu
  ```
- **Result:** would-reject **85.7%** (30/35 bleed items filtered from wrong assignment); true-room top-1 **8.6%**; **pass: false** (reject ↑ vs demo 51.4% but true-room match too low; needs Indoor67 fine-tune)
- **Artifacts:** `room-clf-eval.json`, `room-clf-weights.json` (documented-stub weights)
- **Blocker for full run:** HF `keremberke/indoor-scene-classification` download (~150 MB) + fine-tune head

### ML-E17 — KonIQ-10k → ONNX distill

- **Harness:** `evals/train_iqa_koniq.py`; `evals/eval_iqa_koniq.py`
- **Run (5 Jul 2026):**
  ```bash
  uv run python evals/train_iqa_koniq.py --bootstrap-scores \
    -o evals/fixtures/own-property/iqa-koniq-weights.json
  uv run python evals/eval_iqa_koniq.py report \
    --gold evals/fixtures/own-property/hero-gold.json
  ```
  (training used `own-property-features` on 260 `report/` frames — KonIQ-10k absent)
- **Training:** Spearman pred vs MUSIQ **0.74**
- **Hero-gold:** KonIQ top-1 **4/9**, ML-E6 top-1 **4/9** (tied); **pass: true** (bar ≥ ML-E6; docs/19 stretch goal ≥8/9 still unmet)
- **Artifacts:** `iqa-koniq-weights.json`, `iqa-koniq-onnx.html`, `iqa-koniq-metrics.json`
- **Blocker for full run:** KonIQ-10k MOS download (~2 GB); `evals/export_onnx.py` ONNX export still stub

### ML-E18 — Open Images V7 household pretrain

- **Harness:** `evals/eval_detect_oi_pretrain.py`
- **Run (5 Jul 2026):**
  ```bash
  uv run python evals/eval_detect_oi_pretrain.py benchmarks/inventoryflex/capture \
    evals/fixtures/inventoryflex/labels.json \
    -o evals/fixtures/inventoryflex/detect-comparison-oi.json --device mps
  ```
- **Result:** ML-E10 GDINO baseline **76.0%** notable recall; OI weights absent; proxy (expanded OI phrases) **73.3%** (−2.7 pp); **pass: false**
- **Artifact:** `detect-comparison-oi.json`
- **Blocker for full run:** filtered OI V7 download (5–30 GB) + GDINO fine-tune → `evals/external/data/open-images-v7/weights/gdino-oi-household.pt`

### ML-E19 — shot-scale (long vs close-up)

- **Harness:** `evals/eval_shot_scale.py`
- **Run (5 Jul 2026):** full `report/` — **9/9 hero-gold rooms**, 93 frames, OpenCLIP CPU
- **Result:** mean Spearman shot-scale **0.07** vs cover **0.44**; **pass: false**; **579 ms/frame**
- **Artifact:** `evals/fixtures/own-property/hero-contact-shotscale.html`

### ML-E20 — StructDamage/BD3 defect pre-filter

- **Harness:** `evals/eval_defect_pretrain.py` (stub — Tier C download + pretrain recipe)
- **Data:** BD3 / StructDamage not in `evals/external/data/` — bootstrap = ML-E15 zero-shot
- **Run (5 Jul 2026):** bootstrap on 192 IFlex photos (same as E15 until weights exist)
- **Result:** FP **39.6%**; **pass: false**; `pretrain_available: false`
- **Artifact:** `evals/fixtures/inventoryflex/defect-pretrain-report.json`

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
