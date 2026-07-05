# 19 — ML/DL exploration plan

*5 Jul 2026. Plan of record for traditional machine learning and deep
learning work across the pipeline — classification, segmentation,
pre/post-processing for quality and relevance. VLM describe and VLM room
segmentation remain the quality ceiling we have already benchmarked
(docs/04, docs/11); this doc covers everything we have **not** explored
enough: classical CV, learned IQA, room-change detection, detection
fine-tuning, semantic relevance, and lightweight learned rerankers.*

## Why this matters

Most effort to date has gone into **VLM interpretation** (describe) and
**VLM room boundaries** (segment), plus hand-crafted heuristics for
keyframes and hero selection. That was correct prioritisation: the
schedule-of-condition language is the product, and a wrong item or invented
defect loses an adjudication.

But several product surfaces still depend on **non-VLM signal** that we
have only scratched:

| Surface | Current approach | Risk if we stop here |
|---|---|---|
| Room boundaries | VLM thumbnail strip (docs/11) | API cost, latency, open-plan bleed, no offline path |
| Frame pool purity | 2 s segment trim (docs/18 E3) | Wrong-room frames before describe |
| Hero / cover rank-1 | Classical PIL heuristics (docs/18 E5) | 77.8% top-1; texture bias on close-ups |
| Hero set (filmstrip) | MMR on sharpness (docs/15) | Redundant angles; no semantic "establishing" |
| Keyframe density | Laplacian + frame-diff windows | Motion blur kept for coverage; no relevance filter |
| Object proposals | Off-the-shelf YOLOE text vocab (docs/13) | 58.7% notable recall; AGPL licence |
| Check-in/out change | Text LLM on item names (docs/08) | No vision-level damage / wear classifier |

Traditional ML and small learned models can **reduce cost**, **improve
offline capability**, **filter bad frames before expensive VLM calls**, and
**augment** (not replace) the describe step. This doc maps the option
space, data we have, and a phased experiment programme.

## Scope

| In scope | Out of scope (other docs / v1) |
|---|---|
| Pre-VLM: segmentation, keyframes, quality, relevance | Custom VLM training or fine-tuning |
| Post-ingest: curation, cover selection, frame gating | End-to-end report generation without human review |
| Detection / segmentation for inventory items | Mobile capture app (docs/09) |
| Learned rerankers and small classifiers | C2PA provenance (docs/02 §5) |
| Fine-tuning / distillation on our fixtures | Replacing claude describe for signed output (docs/04) |
| Evaluation harness extensions | Hosted multi-tenant labelling platform |

**Quality bar** unchanged: docs/10. **Architecture** unchanged:
`inventory.json` remains canonical; ML modules are pluggable filters and
scorers, not silent deleters of evidence (docs/15 constraint).

## Current baseline (what exists today)

```text
video / folders
  → [segment] VLM strip → room time ranges          (segment.py)
  → [ingest]  OpenCV keyframes per segment          (ingest.py)
  → [curate]  PIL sharpness + MMR + cover_score     (curate.py)
  → [detect]  YOLOE text vocab, no fine-tune        (detect.py)
  → [describe] pluggable VLM                        (describe.py)
  → [merge]   name de-dup + crop attach             (merge.py)
```

| Task | Method | Eval fixture | Key metric |
|---|---|---|---|
| Room segmentation | VLM (gemini-3.5-flash default) | IMG_5512 manual cut | Qualitative; 2 known merges vs sonnet |
| Describe | VLM (claude opus default) | InventoryFlex 116 items | halluc ≤5%, cond-exact ≥70% |
| Detection | YOLOE text, 48 terms | InventoryFlex notable recall | 58.7% |
| Hero rank-1 | E5 classical cover_score | own-property hero-gold | 77.8% top-1 (7/9) |
| Within-room IQA order | MUSIQ oracle (eval only) | iqa-comparison-mps.json | ρ ≈ 0.66 vs classical |
| Compare rubric | Text LLM on item JSON | docs/08 | wear vs damage classification |

**Training infrastructure:** none. No labelling UI beyond JSON schemas, no
train/val splits, no exported weights, no ONNX deployment path.

---

## 1. Problem areas and candidate techniques

Each subsection lists **techniques**, **pros/cons**, **data needs**, and
**recommended pathway**. Experiment IDs (`ML-E0`…) are assigned in §4.

### 1.1 Room segmentation and room-change detection

**Goal:** Place room boundaries without a VLM call, or refine VLM boundaries
to ±1 s; detect when the filmer enters a new room.

| Approach | Description | Pros | Cons | Licence |
|---|---|---|---|---|
| **A. Optical flow / motion magnitude** | Frame-to-frame flow peaks at doorway transitions | £0, local, fast | Fails on pans, open-plan, stationary filming | — |
| **B. Embedding distance spike** | CLIP / DINOv2 frame embeddings; changepoint on cosine distance | No labels for zero-shot; works offline | Needs threshold tuning per camera; open-plan bleed | Apache-2.0 encoders |
| **C. Supervised room-change classifier** | Binary or multi-class: same room vs transition vs new room | Can learn property-specific cues | Needs labelled transitions; generalisation unknown | Depends on backbone |
| **D. Audio cue (door, footsteps)** | VAD + classifier on mic track from phone video | Cheap signal at doorways | Many walkthroughs mute audio; privacy | — |
| **E. SLAM / layout (overkill)** | Monocular depth + layout estimation | Rich spatial model | Heavy; phone video quality varies | Mixed |
| **F. VLM boundary refinement** | 1 s re-sample strip around each VLM seam only | Best accuracy/cost tradeoff already identified (docs/11) | Still API spend | API |
| **G. Hybrid: cheap detector + VLM verify** | B/C propose cuts; VLM names rooms on 10 s windows | Cuts VLM input frames | Two-stage complexity | Mixed |

**Training data available:**

| Asset | Labels | Count |
|---|---|---|
| IMG_5512 manual 10-room cut | Room boundaries to ±1 s | 1 video (~13.4 min) |
| gemini / sonnet segment JSON | Model boundaries, not gold | 6 model runs in spike |
| InventoryFlex | Folder-per-room only (no video) | 6 rooms, 192 photos |
| M2 boundary-bleed audit | 35 items flagged wrong-room | `ownproperty-bleed-exclusions.json` |

**Gap:** No multi-property video corpus; segmentation eval is qualitative.
**Minimum viable labels:** boundary timestamps for 3–5 walkthrough videos
(≈30 min labelling each with contact-sheet UI).

**Recommended pathway:**

1. **ML-E1** — Spike B (embedding changepoint) on IMG_5512; compare cuts to
   manual + gemini segments; contact sheet like docs/11.
2. **ML-E2** — Spike F (VLM refine ±30 s windows) if bleed persists in
   production schedules.
3. If B reaches ≤2 s mean boundary error: **optional VLM naming-only**
   (send 3 frames per segment, not full strip) — large cost reduction.
4. Defer supervised C until ≥3 labelled videos exist.

---

### 1.2 Keyframe extraction and pre-processing

**Goal:** Keep coverage for describe while dropping frames that hurt humans
and waste VLM tokens (blur, wrong room, duplicate, extreme exposure).

| Approach | Description | Pros | Cons |
|---|---|---|---|
| **A. Hard quality gates** | Reject below room p25 sharpness, >15% clipped (docs/18 E4) | Instant | Regressed cover selection; too aggressive for describe pool |
| **B. Two-tier pools** | *Describe pool* (current density) vs *presentation pool* (curated) | Already architected (docs/15) | Describe still pays for bad frames |
| **C. Blur classifier** | Small CNN or hand-crafted + learned threshold on Laplacian at multi-scale | Fast; can run per-frame at capture | Needs blur labels |
| **D. Motion blur vs defocus** | Directional gradient / frequency analysis | Separates pan blur from focus | More CPU |
| **E. Semantic relevance score** | CLIP margin: "room interior" vs "object close-up" | Directly targets failure modes (docs/18) | Encoder licence + latency |
| **F. Temporal pooling** | Keep best frame per 2 s window by composite score | Reduces tokens ~3× | May drop rare defect frame |
| **G. VLM pre-filter** | Cheap VLM: "usable for inventory?" yes/no | High accuracy | API cost on every frame |

**Training data:**

| Asset | Use |
|---|---|
| hero-gold top/bottom rankings | Proxy for relevance + quality |
| 260 own-property frames with scores | Unlabelled except hero gold |
| InventoryFlex photos | Sharp, deliberate capture — poor blur-negative set |

**Recommended pathway:**

1. **ML-E3** — Implement **two-tier scoring** explicitly: `describe_eligible`
   (permissive) vs `presentation_eligible` (strict). Measure describe token
   savings if we drop bottom decile by composite score.
2. **ML-E4** — CLIP margin (docs/18 E) with **Apache-2.0** encoder
   (e.g. OpenCLIP ViT-B/32 or SigLIP) for relevance; benchmark on hero-gold.
3. **ML-E5** — Multi-scale Laplacian ratio (docs/18 D) + optional linear
   weights trained to predict MUSIQ order (docs/18 F) — licence-clean deploy.
4. Do **not** apply hard gates to describe pool until recall regression on
   InventoryFlex is measured.

---

### 1.3 Image quality assessment (IQA) and hero selection

**Goal:** Rank frames within a room for human-facing surfaces; especially
rank-1 **establishing** cover (docs/18).

| Approach | Description | Pros | Cons | Licence |
|---|---|---|---|---|
| **A. Classical PIL** (shipped E5) | Sharpness × exposure × establishing geometry | <50 ms/frame; no deps | 77.8% top-1; texture bias | — |
| **B. MUSIQ / CLIP-IQA** (eval oracle) | Pretrained no-reference IQA | Best ρ vs human in-room | NC licence; ~100× slower | CC BY-NC-SA |
| **C. MUSIQ-distilled linear model** | Regress MUSIQ rank from classical features | Deployable, fast | Needs per-room fit or global weights | MIT (our weights) |
| **D. NIMA / HyperIQA / LoDA** | Other NR-IQA architectures | Variety of inductive biases | Same licence research needed | Often NC |
| **E. CLIP aesthetic / prompt pairs** | Zero-shot "wide interior" vs "close-up" | No training | Prompt sensitivity | Encoder-dependent |
| **F. Composition classifier** | Room-type-specific: kitchen needs hob+cabinets visible | Matches gold rationales | Needs room-type labels on frames | — |
| **G. VLM rerank top-k** | 10 candidates → pick 1 (docs/18 G) | Highest ceiling | ~9 calls/build | API |
| **H. Human override** (shipped M3) | Reviewer sets cover | 100% when used | Not zero-touch | — |
| **I. Capture pause detection** | Low optical flow windows = intentional hold | Best long-term | Requires capture guidance | — |

**Training data:**

| Asset | Rooms | Labels |
|---|---|---|
| `hero-gold.json` | 9 | top-3 + bottom-2 per room + notes |
| `iqa-comparison-mps.json` | 9 | MUSIQ vs classical ranks |
| E5 contact sheets | 9 | Scorer overlays |

**Recommended pathway:**

1. **Near term (heuristic):** docs/18 sequence — C temporal midpoint, D
   downscale ratio (cheap, no training).
2. **ML-E6** — Train **global linear reranker** on classical features →
   MUSIQ rank (F from docs/18); evaluate top-1 on hero-gold; export ONNX if
   gain ≥2 rooms vs E5.
3. **ML-E7** — CLIP zero-shot establishing margin (E); compare latency and
   licence on same gold.
4. **ML-E8** — VLM rerank spike only if ML-E6/E7 stay <7/9 top-1.
5. **ML-E9** — Pause detection (I) when capture UX adds "hold 2 s per room".

**Pass bar:** ≥7/9 top-1 on hero-gold **and** no room worse than E5 on
pairwise contact sheet (docs/18).

---

### 1.4 Object detection and instance segmentation

**Goal:** Propose inventory items with crops and prompt hints; improve
58.7% notable recall without prompt_free noise (docs/13).

| Approach | Description | Pros | Cons | Licence |
|---|---|---|---|---|
| **A. YOLOE text (current)** | 48-term household vocab | Fast, integrated | 58.7% recall; AGPL | AGPL-3.0 |
| **B. YOLOE prompt_free** | 1200 LVIS classes | 76% recall | Unusable labels | AGPL |
| **C. Grounding DINO + SAM2** | Text phrases → box → mask | Apache-2.0; strong on rare | Slower than YOLOE | Apache-2.0 |
| **D. OWLv2** | Open-vocab, Google | Good rare classes | Heavier | Apache-2.0 |
| **E. Fine-tune YOLOE / YOLO-World** | Linear probe on inventory crops | Big recall lift possible | Needs bbox labels; AGPL | AGPL |
| **F. Weak labels from VLM** | VLM item list → pseudo-boxes from saliency | Cheap scale | Noisy; circular if same VLM describes | — |
| **G. SAM2 video propagate** | Segment tracked objects across frames | Fewer duplicate dets | Compute; needs seed prompts | Apache-2.0 |

**Training data:**

| Asset | Items | Bbox labels |
|---|---|---|
| InventoryFlex | 116 items, 75 notable | **None** — names only |
| YOLOE crops from benchmark runs | ~315 crops | Implicit from detector |
| Professional report PDF | Reference text | No geometry |

**Gap:** Gold fixture has **no bounding boxes**. Detection eval is
label-match only, not localisation mAP.

**Recommended pathway:**

1. **ML-E10** — Benchmark **Grounding DINO** (Apache-2.0) on InventoryFlex
   with inventory phrase list; compare recall/noise to YOLOE text.
2. **ML-E11** — Label **bbox subset**: 50–100 notable items across 2 rooms
   (Kitchen + Bathroom — best/worst YOLOE rooms). Enables proper detection
   metrics and fine-tune feasibility study.
3. **ML-E12** — If AGPL blocks product: migrate default detector to
   Grounding DINO or OWLv2; keep YOLOE for dev/compare.
4. Fine-tune (E) only after ML-E11 shows >15 pp recall headroom on labelled
   subset.

---

### 1.5 Semantic segmentation and scene understanding

**Goal:** Support open-plan boundaries, floor/wall context, defect
localisation — optional enrichment, not v1 blocker.

| Approach | Use case | Pros | Cons |
|---|---|---|---|
| **ADE20K / SegFormer** | Indoor scene parse (wall, floor, ceiling) | Pretrained on scenes | Not item-level |
| **SAM2** | Promptable masks for defects or fixtures | Flexible | Needs prompts; compute |
| **Depth (MiDaS, Depth Anything)** | Layout / distance — prefer central wide views | Cheap relevance signal | Monocular error on texture |
| **Room type classifier** | Kitchen vs bathroom vs bedroom from one frame | Could validate segment names | 10+ classes; UK layout diversity |

**Training data:** Essentially none for segmentation masks. ADE20K transfer
only unless we label masks on InventoryFlex subset.

**Recommended pathway:** **Defer** until detection path (§1.4) and cover
selection (§1.3) pass bars. **ML-E13** optional spike: SegFormer on hero
candidates — fraction with >30% floor+wall visible correlates with gold
establishing shots?

---

### 1.6 Post-describe classification and comparison

**Goal:** Check-in vs check-out — vision-level change detection, wear vs
damage (docs/08). Currently **text-only** LLM on item JSON.

| Approach | Description | Pros | Cons |
|---|---|---|---|
| **A. Text rubric (current)** | LLM on names, grades, defects | Cheap; TDS-grounded | No pixel evidence of new damage |
| **B. Siamese / diff embedding** | Embed before/after crop; distance → change | Pairs with report structure | Lighting angle breaks naive diff |
| **C. Change detection networks** | CD models (BIT, ChangeFormer) | Literature for aerial; adaptable | Needs aligned pairs — rare in inventory |
| **D. VLM pairwise** | "What changed?" on two crops | Accurate | 2× describe cost per item |
| **E. Defect detector fine-tune** | Scratch, stain, chip classes | Direct evidence | Large labelled set |

**Training data:** No paired check-in/check-out fixture in repo. v2 feature.

**Recommended pathway:** Stay on **A** for v1. **ML-E14** — when a paired
fixture exists (same property, two visits), spike B on 20 item pairs with
human change labels. Do not invest in C/E until paired data ≥1 property.

---

### 1.7 Defect and condition classification (vision)

**Goal:** Calibrated condition grades and defect recall (docs/04 plateau
~64–71% defect recall). VLMs dominate; ML role is **assist**, not replace.

| Approach | Role | Pros | Cons |
|---|---|---|---|
| **A. VLM + rubric (current)** | Primary grader | Best ceiling (claude 71.3%) | Hallucination risk |
| **B. Defect presence classifier** | Binary on crops: visible damage? | Gates VLM defect claims | Needs defect bbox labels |
| **C. Multi-label surface defects** | Crack, stain, chip, mould | Interpretable | Long-tail |
| **D. Grade regression from IQA + damage** | Predict ordinal grade | Weak alone | Correlation not causation |
| **E. Human-in-loop (docs/05)** | Review claims next to evidence | Adjudication-safe | Labour |

**Training data:** Gold defects in InventoryFlex are **text lists**, not
localised boxes. Resolution 800×600 may bound defect recall (docs/04).

**Recommended pathway:** **Do not** train condition classifiers before
native-resolution fixture and localised defect labels exist. **ML-E15** —
optional: train binary "visible anomaly" on public datasets (e.g. crack/
stain) as **pre-filter only**; measure false positive rate on InventoryFlex
photos.

---

## 2. Training data inventory and gaps

### 2.1 Committed fixtures (usable now)

| Path | Modality | Labels | ML use |
|---|---|---|---|
| `evals/fixtures/inventoryflex/labels.json` | Photos, 6 rooms | 116 items, grades, defects | Detection match, describe eval; **no geometry** |
| `evals/fixtures/own-property/hero-gold.json` | Video frames, 9 rooms | top-3/bottom-2 cover ranks | IQA, relevance, cover ML |
| `evals/fixtures/own-property/iqa-comparison-mps.json` | Same frames | MUSIQ vs classical ranks | Distillation target for ML-E6 |
| `evals/fixtures/ownproperty-bleed-exclusions.json` | Items | Wrong-room flags | Segmentation / pool purity |
| `evals/fixtures/thresholds.json` | — | CI floors | Regression gates |
| `benchmarks/inventoryflex/report-*/` | Full pipeline outputs | Scored runs | Pseudo-labels, error mining |
| IMG_5512 + segment JSON | Video | Manual 10-room cut (reference) | Segmentation ML-E1 |

### 2.2 Available but not committed (policy / size)

| Path | Notes |
|---|---|
| `examples/videos/IMG_5512.MOV` | 1.3 GB; personal; primary video gold |
| `benchmarks/inventoryflex/capture/` | 192 photos; regeneratable |
| `segment-spike-multi/` | Multi-model segment outputs |

### 2.3 Critical gaps

| Gap | Blocks | Remediation |
|---|---|---|
| **No bbox labels** | Detection fine-tune, mAP | ML-E11: 50–100 boxes, 2 rooms |
| **Single video gold for segmentation** | Supervised room-change | Label 2–4 more walkthroughs |
| **No paired check-in/out images** | Vision compare | Capture second visit or synthetic pair |
| **Low-res InventoryFlex** | Defect ML | Native-res benchmark branch |
| **No train/val split convention** | All ML experiments | Add `evals/splits/` with room-held-out protocol |
| **NC-licensed IQA in product** | MUSIQ deploy | Distillation (ML-E6) or Apache encoder only |

### 2.4 Adjacent open datasets (Jul 2026 research)

There is **no public dataset** for UK tenancy inventory reports, check-in/out
schedules, or clerk-style condition grading. What exists is **adjacent**:
real-estate listing photos, indoor scene recognition, residential layout,
building-surface defects, egocentric home video, and generic household object
detection. Most are useful for **pretraining, transfer learning, and eval
oracles** — not as a drop-in substitute for our gold fixtures.

**Important caveats across the board:**

- **Domain gap:** Listing photos are staged wide shots; our walkthrough frames
  include motion blur, close-ups, and mixed room bleed. Defect datasets are
  mostly **exterior / structural** (cracks in concrete) not **interior fair
  wear** (scuff on skirting). Expect transfer, not plug-and-play.
- **Licence:** Several of the best real-estate sets are **academic-only** or
  **not redistributable** (ZInD, ScanNet, Matterport3D). Check before training
  anything we might ship.
- **UK / TDS vocabulary:** No dataset uses our condition/cleanliness ordinals
  or item naming register. Labels must stay internal.

#### By pipeline task

| Our task | Best open datasets | Scale | Labels | Licence / access | Fit |
|---|---|---|---|---|---|
| **Room type classifier** | [MIT Indoor 67](https://web.mit.edu/torralba/www/indoor.html), [HF indoor-scene-classification](https://huggingface.co/datasets/keremberke/indoor-scene-classification) (15.7k / 67 classes), [Places205](http://places.csail.mit.edu/) (2.4M / 205 scenes) | 15k–2.4M | Scene class | Research / CC BY (Places) | **High** for kitchen/bathroom/bedroom/hallway; many classes irrelevant (airport, casino) |
| **Real-estate room tagger** | [REI / WACV 2017](https://doi.org/10.1109/wacv.2017.48) (7 classes from Zillow crawl), [RE-Tagger paper](https://arxiv.org/abs/2207.05696) (3.1M **internal** — not public) | REI: small; RE-Tagger: closed | bedroom, bath, kitchen, hall, exterior, docs, other | REI: paper + DB request | **Medium** — closest semantic match to listing photos; RE-Tagger weights/data unavailable |
| **Room layout / doors** | [ZInD](https://github.com/zillow/zind) (67k 360° panos, 1.5k **unfurnished US** homes, room type + W/D/O + floor plans) | 67k panos | Layout, room name | **Academic only** — [Bridge registration](https://bridgedataoutput.com/register/zgindoor) | **High** for layout/doorway cues; 360° not phone walkthrough; commercial use blocked |
| **3D indoor + objects** | [ScanNet](http://www.scan-net.org/) (1.5k scans, instance seg), [Matterport3D](https://niessner.github.io/Matterport/) (2k rooms, 40 object classes), [ARKitScenes](https://github.com/apple/ARKitScenes) (mobile RGB-D) | 1.5k–2k scenes | 3D bbox, semantic | Academic TOS (email request) | **Medium** for detector pretrain; furnished US homes; heavy 3D pipeline |
| **Video room change** | [Ego4D](https://ego4d-data.org/) (3.6k h egocentric, household scenarios), [EPIC-Kitchens-100](https://epic-kitchens.github.io/) (100 h, 45 kitchens, narrated segments) | 100–3600 h | Activity segments, some room context | Ego4D / EPIC research licence | **Medium** for changepoint / motion; kitchen-heavy; not inventory-specific |
| **Cover / establishing shot** | [CineScale](https://cinescale.github.io/shotscale/) (792k frames, LS/MS/CU/ECU), [types-of-film-shots HF](https://huggingface.co/datasets/szymonrucinski/types-of-film-shots) (~925 images, CC BY 4.0) | 925–792k | Shot scale | Research / CC BY 4.0 (small set) | **Medium** — "long shot" ≈ establishing; film domain not interiors |
| **Image quality (NR-IQA)** | [KonIQ-10k](https://database.mmsp-kn.de/koniq-10k-database.html) (10k images, MOS scores), LIVE-in-the-Wild | 10k | Quality score | Research download | **High** for blur/exposure ranker pretrain; not room-semantics-aware |
| **Scene parsing (wall/floor)** | [ADE20K](https://github.com/CSAILVision/ADE20K) (25k images, 150-class seg subset), LSUN scenes (bedroom/kitchen/living/dining millions) | 25k–3M+ | Pixel / scene | MIT (ADE20K code); LSUN MIT | **Medium** for establishing-score features (floor+wall fraction) |
| **Household object detection** | [Open Images V7](https://storage.googleapis.com/openimages/web/index.html) (600 box classes; bathtub, stove, washer, furniture…), ScanNet/Matterport | 16M boxes (full); filter subset | Bbox + mask | Apache 2.0 (OI) | **High** for detector pretrain / vocab expansion; long-tail ≠ inventory terms |
| **Interior surface defects** | [RBDID](https://doi.org/10.57760/sciencedb.28941) (26k images, 17 defect cats, **residential**), [BD3](https://github.com/Praveenkottari/BD3-Dataset) (4k, stain/peel/spall/crack), [StructDamage](https://arxiv.org/abs/2603.10484) (78k aggregated, CC BY 4.0), [MBDD2025](https://zenodo.org/records/15622584) (14k UAV building) | 4k–78k | Bbox or class | Mostly open; RBDID via ScienceDB | **Medium–low** for tenancy scuffs/stains; **high** for "damage present?" binary pre-filter (ML-E15) |
| **Check-in/out change** | xBD, [DamageTriage-Bench](https://huggingface.co/datasets/Ymx1025/DamageTriage-Bench) (satellite post-disaster) | varies | Damage typology | HF / research | **Low** — disaster/aerial, not room-item pairs |

#### Tier list — what to actually download first

**Tier A — download for immediate spikes (licence-safe, direct task match):**

1. **KonIQ-10k** — pretrain or distil NR-IQA ranker (ML-E6); complements MUSIQ
   oracle without NC licence in product weights.
2. **MIT Indoor 67 / HF indoor-scene-classification** — room-type head for
   segment validation and wrong-room frame rejection; small enough to fine-tune
   on laptop; map 67 → our ~10 room names.
3. **Open Images V7 (filtered)** — ~30 household classes matching
   `HOUSEHOLD_VOCAB`; pretrain Grounding DINO / YOLO before ML-E10/ML-E12.
   Use FiftyOne class filter — full set is ~561 GB.
4. **types-of-film-shots** (925 img, CC BY 4.0) — quick shot-scale baseline for
   establishing vs close-up before CLIP prompts (ML-E4/E7).

**Tier B — worth requesting / academic use only:**

5. **ZInD** — best real-estate-native room layout + type + door/window labels;
   extract perspective crops from panoramas for room classifier; **cannot ship
   commercial model trained solely on ZInD** without Zillow licence.
6. **ScanNet / Matterport3D** — object instance pretrain if Open Images insufficient;
   3D bbox → 2D crop pipeline is extra work.
7. **REI database (WACV 2017)** — contact authors; 7-class real-estate tags from
   Zillow crawl; small but on-domain.

**Tier C — defect / change (assistive pre-filter only):**

8. **BD3 + StructDamage** — binary "surface anomaly" pre-filter; expect false
   positives on intentional patina, wood grain, shadows.
9. **RBDID** — closest to **residential interior** defect bbox (74k instances,
   17 categories); China housing stock; still not UK tenancy scuffs.

**Tier D — large but weak transfer (defer):**

10. **LSUN** bedroom/kitchen (millions) — generative / GAN era; unlabelled beyond
    scene; use only if training room classifier from scratch.
11. **Ego4D / EPIC-Kitchens** — only if ML-E1 embedding changepoint fails; heavy
    download and licence; kitchen-centric.
12. **CineScale** — 792k film frames; use if Tier A shot-scale too small.

#### What does *not* exist (gaps no public set fills)

| Need | Closest public proxy | Gap |
|---|---|---|
| Phone walkthrough → room boundaries | Ego4D room tours + our IMG_5512 | No timestamped room-boundary labels on egocentric video |
| Inventory item + UK condition grade | Open Images objects + VLM | No ordinal condition/cleanliness on household items |
| Establishing cover for property overview | REI wide rooms + CineScale LS | No "brochure cover" labels on walkthrough frames |
| Check-in vs check-out same item | — | No paired tenancy photo datasets found |
| Smoke alarm / towel rail / skirting board | Partial in OI / ScanNet | Inventory-specific long-tail still needs our labels |

#### Recommended incorporation (updates ML programme)

| ID | Action | Dataset |
|---|---|---|
| **ML-E16** | Fine-tune room-type classifier (67→10 classes); eval wrong-room rejection on bleed audit | MIT Indoor / HF indoor-scene |
| **ML-E17** | Pretrain KonCept512-style tiny IQA on KonIQ-10k; distill to ONNX; compare hero-gold | KonIQ-10k |
| **ML-E18** | Filter OI V7 to ~40 household classes; pretrain detector; eval on InventoryFlex | Open Images V7 |
| **ML-E19** | Zero-shot shot-scale (LS vs CU) on hero-gold before SigLIP | types-of-film-shots + CineScale |
| **ML-E20** | Binary defect pre-filter FP rate on InventoryFlex photos | BD3 or StructDamage |

Add **`evals/external/`** README listing download URLs, licences, and which
ML-E spike consumed each set — do not commit multi-GB archives to git.

**No UK tenancy inventory dataset was found.** The viable strategy is:
**public pretrain → our fixtures fine-tune/eval** (InventoryFlex, hero-gold,
eventual bbox labels), same pattern as docs/04 VLM benchmarks.

### 2.5 Labelling effort estimates (not calendar time)

| Task | Effort | Yield |
|---|---|---|
| Hero gold (done) | 9 rooms × 5 ranks | Cover ML benchmark |
| Segment boundaries ×3 videos | ~90 timestamps | Room-change supervised set |
| Bbox 100 items | ~3–4 h with tooling | Detection fine-tune feasibility |
| Room-type tag per segment | 1 label/segment | Room classifier |
| Defect bbox 50 instances | ~2 h | Defect presence classifier |

**Tooling needed (minimal):**

- Reuse `evals/eval_hero_cover.py` pattern — contact-sheet HTML with
  click-to-export labels.
- New: `evals/label_segments.py` — scrub video, mark boundaries, write JSON.
- New: `evals/label_boxes.py` — lightweight bbox on crops (or CVAT export).

---

## 3. Technique selection matrix

Summary for prioritisation. **Priority** = impact on product trust × data
readiness × licence safety.

| Task | Best first bet | Fallback | Avoid for product |
|---|---|---|---|
| Room boundaries | Embedding changepoint (ML-E1) | VLM refine windows | Full SLAM |
| Frame relevance | CLIP margin (ML-E4) | Linear on classical (ML-E6) | Hard gate on describe pool |
| Cover rank-1 | Linear MUSIQ-distill (ML-E6) | VLM rerank (ML-E8) | pyiqa MUSIQ runtime |
| Detection | Grounding DINO eval (ML-E10) | YOLOE + Enterprise licence | prompt_free labels |
| Hero distinctness | CLIP embeddings in MMR | pHash | — |
| Compare | Text rubric (keep) | Siamese pairs (ML-E14) | Pixel diff without alignment |
| Condition | VLM + review (keep) | Anomaly pre-filter (ML-E15) | End-to-end grade CNN |

### Licence constraints (productisation)

| Component | Licence | Product note |
|---|---|---|
| YOLOE / Ultralytics | AGPL-3.0 | Enterprise licence or replace (docs/02) |
| pyiqa / MUSIQ | CC BY-NC-SA | **Eval oracle only** — never ship |
| Grounding DINO, SAM2, OWLv2 | Apache-2.0 | Preferred for commercial path |
| OpenCLIP / SigLIP | Apache-2.0 / MIT | Preferred encoders for ML-E4/E7 |
| Our linear / ONNX heads | MIT (repo default) | Ship freely |

---

## 4. Experiment programme

Experiments use prefix **ML-E*** to distinguish from hero heuristics (E0–E5
in docs/18). Each must produce **contact sheets or JSON metrics** — same
standard as docs/11 and docs/18.

| ID | Task | Method | Pass bar | Artifact |
|---|---|---|---|---|
| **ML-E1** | Segmentation | DINOv2/CLIP embedding changepoint | ≤3 s mean error vs manual on IMG_5512 | `evals/fixtures/own-property/segment-embed.html` |
| **ML-E2** | Segmentation | VLM refine ±30 s windows | Bleed items ↓ vs baseline | segment JSON + bleed recount |
| **ML-E3** | Pre-process | Two-tier describe vs presentation pools | Describe recall unchanged; token count ↓ | InventoryFlex eval |
| **ML-E4** | Relevance | SigLIP margin establishing vs close-up | ρ vs hero-gold ≥ E5 | hero-contact-siglip.html |
| **ML-E5** | Pre-process | Multi-scale Laplacian ratio | top-3 hit ≥ E5 | hero-contact-mslap.html |
| **ML-E6** | IQA | Linear model → MUSIQ rank | top-1 ≥ 8/9 | weights.json + contact sheet |
| **ML-E7** | IQA | CLIP prompt pairs (licence-clean) | top-1 ≥ 7/9, latency <100 ms/frame | hero-contact-clip.html |
| **ML-E8** | Cover | VLM top-10 rerank | top-1 = 9/9 or unanimous eyeball | cost log + contact sheet |
| **ML-E9** | Capture | Optical-flow pause detection | Pause frames in gold top-3 ≥80% | timeline HTML |
| **ML-E10** | Detection | Grounding DINO vs YOLOE text | Recall ↑ with noise ≤ text mode | detect-comparison-gdino.json |
| **ML-E11** | Data | 100 bbox labels, 2 rooms | JSON in evals/fixtures | labels_boxes.json |
| **ML-E12** | Detection | Fine-tune probe on ML-E11 subset | +10 pp recall @0.5 IoU | weights + eval |
| **ML-E13** | Segmentation | SegFormer floor+wall fraction | ρ with establishing gold | scatter plot |
| **ML-E14** | Compare | Siamese embedding on pairs | — (exploratory) | paired fixture only |
| **ML-E15** | Defect | Anomaly pre-filter zero-shot | FP rate <10% on IFlex | defect-filter-report.json |
| **ML-E16** | Room type | Fine-tune Indoor67→10 classes | Wrong-room bleed ↓ on audit | room-clf-eval.json |
| **ML-E17** | IQA | KonIQ-10k pretrain → ONNX distill | top-1 ≥ ML-E6 on hero-gold | iqa-koniq-onnx.html |
| **ML-E18** | Detection | OI V7 household subset pretrain | Recall ↑ vs ML-E10 baseline | detect-comparison-oi.json |
| **ML-E19** | Cover | Shot-scale classifier transfer | ρ vs hero-gold ≥ classical | hero-contact-shotscale.html |
| **ML-E20** | Defect | StructDamage/BD3 pretrain pre-filter | FP <10% on IFlex | defect-pretrain-report.json |

### Recommended sequence

```text
Phase 0 — Data (parallel)
  ML-E11 bbox subset
  segment labels for 2 additional videos (when available)
  evals/splits/ room-held-out protocol

Phase 1 — Cheap local signal (no training)
  ML-E1, ML-E4, ML-E5, ML-E10, ML-E19
  → decision: embedding segmentation + SigLIP relevance + Apache detector?

Phase 1b — Public dataset pretrain (Tier A)
  ML-E16, ML-E17, ML-E18 in parallel with Phase 1
  → decision: room clf + KonIQ ONNX + OI-pretrained detector?

Phase 2 — Small learned models
  ML-E6, ML-E7, ML-E3
  → decision: ship ONNX reranker? two-tier pools?

Phase 3 — API-augmented ceiling
  ML-E2, ML-E8 only if Phase 1–2 miss pass bars

Phase 4 — v2 / when paired data exists
  ML-E14, ML-E12 fine-tune, ML-E15, ML-E20
```

---

## 5. Decision gates

| Gate | Condition | Action |
|---|---|---|
| **G1 — Cover ML ships** | ML-E6 or ML-E7 beats E5 on gold + runtime budget | Replace rank-1 scorer in `curate.py`; keep E5 as fallback flag |
| **G2 — Segmentation hybrid** | ML-E1 ≤3 s error AND naming-only VLM ≤£0.05/property | Optional `--segment-backend classical` |
| **G3 — Detector swap** | ML-E10 recall ≥ text + 5 pp at ≤2× latency, Apache licence | Add `detect.py` backend switch; document in docs/13 |
| **G4 — Describe pool trim** | ML-E3 cuts ≥15% frames with zero notable recall loss | Enable `--describe-pool strict` |
| **G5 — No product NC models** | Any experiment | pyiqa stays in `evals/` only; CI may run it, build must not |
| **G6 — VLM rerank** | ML-E8 only after G1 candidates fail | Disclosed cost in build confirm (docs/12) |

---

## 6. Infrastructure to add (minimal)

| Component | Purpose |
|---|---|
| `evals/splits/inventoryflex.json` | Train/val by room |
| `homeinventory/ml/` or `homeinventory/scorers/` | Optional ONNX/torch scorers behind same interface as `curate.py` |
| `evals/eval_segment_embed.py` | ML-E1 harness |
| `evals/eval_detect_gdino.py` | ML-E10 harness |
| `--scorer` flags on `curate-only` | Already partially exist via eval_hero_cover |
| ONNX export for linear/ small CNN | Laptop inference <50 ms/frame (docs/18 budget) |

**Non-goals for infrastructure v1:** Kubeflow, labelling SaaS, auto-annotation
pipeline, GPU training cluster. Train on laptop or one cloud GPU session;
commit weights ≤10 MB or document download script.

---

## 7. Non-goals

- **Custom VLM training** — cost, data, and claude ceiling (docs/04) make this
  low ROI until we have 50+ labelled properties.
- **Replacing human review** — ML may rank and filter; attestations stay human
  (docs/05, docs/10).
- **Silent frame deletion** — rejected frames stay in manifest tier (docs/15).
- **Shipping AGPL or NC weights** without explicit licence decision.
- **Room classification without segment context** — folder names and VLM
  segments remain primary; classifiers assist validation only.

---

## 8. Success metrics (ML programme)

| Area | Current | Target (ML-augmented) |
|---|---|---|
| Cover top-1 (hero-gold) | 77.8% (7/9) | ≥89% (8/9) or 9/9 |
| Segment boundary error | ~5 s sampling + qualitative | ≤2 s mean on 3-video set |
| Detection notable recall | 58.7% (YOLOE text) | ≥70% Apache path |
| Describe tokens / property | baseline | −15% via relevance pool with recall held |
| Offline build path | YOLOE + local VLM | + classical segment + ONNX cover without API |
| Build step 2b latency | 3.1 s / 260 frames (PIL) | <10 s with learned tier |

Product metrics (hallucination, condition-exact) must **not regress** when
ML pre-filters are enabled — gate on InventoryFlex before ship.

---

## 9. Open questions

1. **Enterprise YOLOE licence vs Apache stack** — legal decision before
   ML-E12 fine-tune investment.
2. **How many walkthrough videos** can we label under personal-data policy?
   Segmentation ML depends on this.
3. **Is 8/9 top-1 sufficient** if the miss is always Kitchen (hob close-up)?
   Room-specific scorers (ML-E6 per room type) vs global model.
4. **Native-resolution eval** — when does defect ML become meaningful?
5. **Distillation from VLM** — use claude item lists as pseudo-labels for
   detection (ML-E11 extension) — acceptable circularity for proposals only?

---

## 10. Related files and docs

| Path | Role |
|---|---|
| `docs/02-research.md` | YOLOE, Apache alternatives, VLM landscape |
| `docs/11-video-segmentation.md` | VLM segmentation spike |
| `docs/13-yoloe-detection.md` | Detection benchmark |
| `docs/15-curation-and-one-app.md` | Two-tier frame architecture |
| `docs/18-hero-image-selection.md` | Cover experiment log E0–E5, backlog A–I |
| `homeinventory/segment.py` | VLM segmentation |
| `homeinventory/ingest.py` | Keyframe extraction |
| `homeinventory/curate.py` | Scoring + MMR + cover |
| `homeinventory/detect.py` | YOLOE integration |
| `evals/eval_hero_cover.py` | Cover contact sheets |
| `evals/eval_iqa.py` | MUSIQ oracle (eval only) |
| `evals/eval_detect.py` | Detection comparison |

---

## Definition of done (this doc)

- [x] Problem areas mapped to techniques with pros/cons
- [x] Training data inventory and gaps documented
- [x] Experiment backlog (ML-E1–E15) with pass bars
- [x] Decision gates and non-goals stated
- [x] Recommended phased sequence
- [x] Adjacent open datasets surveyed (§2.4)
- [x] Phase 0 data labelling started (ML-E11) — `evals/label_segments.py`,
  `evals/label_boxes.py`, `labels_boxes.json` template, `evals/splits/`
- [ ] Tier A external datasets downloaded to `evals/external/data/` (ML-E16–E20)
  — download URLs documented in `evals/external/README.md`

This document is the **plan**; individual spikes update their experiment
rows and may spawn focused docs (e.g. `20-segment-embedding-spike.md`) when
a technique graduates from exploration to adoption.
