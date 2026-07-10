# 22 — ML/DL programme review and roadmap

> **Status: active (strategy).** §2 scoreboard categorisation is **pre-GPU**
> (5 Jul 2026). Authoritative pass/fail status is
> [`21-ml-dl-experiment-log.md`](21-ml-dl-experiment-log.md) after the 6 Jul
> GPU re-run (docs/23). E4/E7/E19 flipped from "under-powered" to confirmed
> real negatives; E16 partial pass. v1 scope and sequencing: docs/00.

*5 Jul 2026. A post-mortem of ML-E1–E20 (docs/21) and a roadmap forward.
16 of 20 spikes did not pass. This document argues that the headline
number is **misleading** — most "failures" are un-run or under-powered
spikes, not evidence that the technology is wrong — and lays out a path to
the real goal: the **fastest, cheapest, most accurate** end-to-end
pipeline. Current state (heuristics + closed VLMs → ~80%) is the fall-back
we improve on, not the target.*

---

## 1. TL;DR

- The "16 fails" are **not** 16 verdicts that ML doesn't work here. When you
  sort them by *why* they failed, only **~3** are genuine "the signal isn't
  in the data" findings. The rest are **un-run** (dataset never downloaded),
  **under-powered** (smallest model, on CPU, zero-shot), **mis-evaluated**
  (9-room eval with a near-ceiling bar), or **mis-targeted** (optimising the
  wrong quantity). The programme's *design* guaranteed uninformative results.
- The two things that **did** work — ML-E2 (VLM boundary refine) and ML-E8
  (VLM cover rerank, 9/9) — share one shape: **cheap stage proposes, VLM
  disposes.** That is the architecture to generalise, not abandon.
- ML-E10 is a **win misfiled as a fail**: Grounding DINO gave **+17.3 pp**
  notable recall *and* is Apache-2.0 (kills the YOLOE AGPL problem). It only
  "failed" on an unmatched-label noise bar — precisely what a cheap verify
  stage removes.
- The programme spent ~12 of 20 spikes on the parts of the pipeline that are
  **already cheap and adequate** (cover selection, relevance filtering,
  segment boundaries) and almost none on where cost and the 20% error
  actually live: the **describe VLM** (≈$1.17/property on opus) and the
  **defect/condition ceiling** (64–71% defect recall across *all* backends,
  resolution-bound per docs/04).
- The path to *fast + cheap + accurate at once* is a **cascade + distillation
  flywheel**: high-recall cheap stage → VLM precision stage → log VLM outputs
  as in-domain labels → train small models that early-exit the easy cases →
  VLM spend falls over time while accuracy stays pinned by the VLM fallback.
  Everything else in this roadmap serves that structure.

---

## 2. The honest scoreboard

docs/21 reports 15 fail · 4 pass · 1 blocked. Re-categorised by **root
cause** rather than pass/fail:

| ID | Reported | Real category | One-line reason |
|---|---|---|---|
| E1 | fail | **genuine negative** (as designed) | Global-embedding changepoint has no spike for a slow handheld doorway pass; open-plan has no boundary at all |
| E2 | pass (demo) | **win** (cascade) | VLM refine of cheap seams — never run live, but the shape works |
| E3 | fail | **un-run** | Ran on a 19-frame proxy video (IMG_5278), not the real report |
| E4 | fail | **under-powered** | `siglip-base-224`, CPU, zero-shot prompt-pairs; ρ −0.21 |
| E5 | fail | **mis-evaluated** | Multi-scale Laplacian judged by top-3=100% on n=9 |
| E6 | fail | **mis-targeted** | Distilled MUSIQ rank — the wrong quantity (see §3.4) |
| E7 | fail | **under-powered** | `ViT-B-32` OpenAI, CPU, 589 ms/frame; top-1 2/9 |
| E8 | pass (demo) | **win** (cascade) | VLM top-10 rerank 9/9, ~$0.20/build — never run live |
| E9 | fail | **genuine negative** | Walkthroughs are continuous motion; pauses don't exist to detect |
| E10 | fail | **win, wrong metric** | +17.3 pp recall, Apache licence; failed only an unmatched-label noise bar |
| E11 | pass | **productive data work** | 101 verified boxes — the *right* kind of investment |
| E12 | fail | **un-run / under-powered** | Fine-tuned on 37 pseudo-boxes from rooms lacking the val classes |
| E13 | fail | **un-run + weak hypothesis** | Histogram proxy, real SegFormer never ran; floor/wall≈cover is a weak prior |
| E14 | blocked | **no data** | No paired check-in/out fixture exists |
| E15 | fail | **broken eval** (as designed) | FP-rate on deliberately-clean photos with zero defect positives present |
| E16 | fail | **un-run** | "Documented-stub" weights; Indoor67 never downloaded/fine-tuned |
| E17 | pass | **un-run + illusory pass** | KonIQ-10k absent; "pass" = tied ML-E6's *failing* 4/9 |
| E18 | fail | **un-run** | OI V7 weights absent; ran an expanded-phrase proxy |
| E19 | fail | **under-powered + weak hypothesis** | `ViT-B-32` CPU shot-scale; ρ 0.07 |
| E20 | fail | **un-run** | Tier-C data never downloaded; identical to E15 bootstrap |

**Re-tally by cause:**

- **Un-run / stub / no-data:** E3, E13, E16, E17, E18, E20, E14, and half of E12 — **~7–8 spikes**. `evals/external/data/` is **empty**; no Tier-A/B/C dataset (KonIQ-10k, Indoor67, Open Images V7, BD3/StructDamage) was ever downloaded. These are harnesses waiting for inputs, reported as fails.
- **Under-powered model on CPU:** E4, E7, E19 (+E12). Every learned-encoder spike used the *smallest* variant — `siglip-base-patch16-224`, `ViT-B-32` OpenAI, `vit_small_patch14_dinov2` — at `device="cpu"`, 500–600 ms/frame. Negative/zero correlations are the expected symptom, not a verdict on the method.
- **Mis-evaluated (n=9, near-ceiling bar):** contaminates E5, E6, E7, E19. See §3.3.
- **Mis-targeted:** E6, E13, E19. See §3.4.
- **Genuine negatives (retire, don't retry):** E1-as-designed, E9, E15/E20-as-designed. **~3.**
- **Wins misfiled or un-shipped:** E2, E8, E10.
- **Productive:** E11.

**The headline that matters:** genuine "this technology cannot do this task"
findings number **about three**. The other thirteen tell us about our
*process*, not about ML.

---

## 3. Root causes

### 3.1 Un-run experiments reported as failures *(the single biggest distortion)*

`find evals/external -type f` returns only a README. Every experiment that
depended on a public dataset ran on a stub and was logged "fail":

- E16 room classifier: stub weights → true-room top-1 **8.6%** (never saw Indoor67).
- E17 KonIQ→ONNX: trained on own-property features because KonIQ-10k absent; ONNX export still a stub; "passed" only by tying E6's failing 4/9.
- E18 OI pretrain: "OI weights absent," expanded-phrase proxy, −2.7 pp.
- E20 defect pretrain: "Tier-C data not downloaded," identical to E15.
- E3 describe pool: measured on a 19-frame, single-room proxy, not IMG_5512.
- E2, E8 (the "passes"): `--demo`/oracle only; live VLM never run (no API keys).

A log that mixes "we tried X and it doesn't work" with "we never set X up"
manufactures a false narrative that ML is a dead end here. **Fix the log
first** (§5.0) before drawing any strategic conclusion from it.

### 3.2 Under-powered models mistaken for the technique

`evals/ml_scorers.py` defaults: SigLIP = `siglip-base-patch16-224`,
OpenCLIP = `ViT-B-32/openai`, DINOv2 = `vit_small_patch14`. All CPU. These
are the weakest common variants of each family. Zero-shot prompt-pair
scoring ("wide interior" vs "close-up") with a base-224 encoder is known to
be unreliable for subtle discriminations. "SigLIP relevance failed" is
really "SigLIP-**base** zero-shot on CPU with two prompts failed" — a fair
test of neither SigLIP nor the relevance idea. The 500–600 ms/frame latency
that also fails the runtime bar is a CPU artefact, not a property of the model.

### 3.3 A 9-room, single-property eval with near-ceiling bars

`hero-gold.json` = **9 rooms of one video** (IMG_5512). The whole cover/IQA
family (E4, E5, E6, E7, E13, E17, E19) is scored on those 9 points, with bars
set at **8/9 or 9/9 top-1**. At n=9, one room flipping is 11 pp; Spearman on
5–9 frames/room is dominated by noise. You cannot reliably rank scorers or
clear an 8/9 bar at this n — the eval can't separate a good scorer from a
lucky one. Detection (E10, E18) had **no bbox gold at all** until E11, so
recall was measured by name-match, conflating detector recall with vocab and
describe coverage.

### 3.4 Chasing the wrong target signal

- **Cover (E6, E17)** trained models to predict **MUSIQ** rank. But MUSIQ
  measures *technical* quality (sharp/exposed), correlates only ρ≈0.66 with
  humans, and does **not** encode the product target — "establishing /
  recognisable room," a *semantic* property. They distilled a mediocre proxy
  of the wrong quantity, learned it well (train ρ 0.74), and hit 4/9 on the
  real goal. **The failure is target design, not model capacity.**
- **Cover (E13, E19)**: "more floor+wall ⇒ better cover" and "long-shot ⇒
  better cover" are weak priors — a tidy tight establishing shot and a hob
  close-up can both score low. Weak hypothesis, then never properly run.

### 3.5 Effort spent off the bottleneck *(the strategic error)*

Where do cost and the 20% error actually live? From docs/04:

- **Cost driver = the describe VLM.** opus-4-8 ≈ **$1.17/property**; gpt-5.4-mini ≈ $0.14 but 14.7% hallucination; gemini-3.5-flash cheap but −21 pts condition-exact. Segmentation is *pennies* (gemini-flash); cover/curate is *free* PIL.
- **Accuracy ceiling = describe condition/defect.** Defect recall is stuck **64–71% across every backend** and docs/04 attributes it to **capture resolution**, not model choice. Notable detection recall is 58.7% (YOLOE text).

Yet ~12 of 20 spikes targeted cover, relevance, and segment boundaries — the
cheap, already-adequate parts — while the describe cost/quality bottleneck
got almost no ML attention, and where it's bound it's bound by **capture
resolution and labelled data**, not model architecture. The programme
optimised what was already fine.

### 3.6 The two real, positive findings buried in the log

1. **"Cheap proposes, VLM disposes" is the only thing that worked.** E2 (VLM
   refine of cheap seams) and E8 (VLM rerank of a classical top-10, 9/9,
   ~$0.20/build) are both cheap, cacheable, per-seam/per-room VLM calls.
2. **E10 is the detection path, not a failure.** +17.3 pp recall at Apache-2.0
   licence. The `unmatched_label_rate` "noise" that failed it is exactly what
   a cheap second-stage verifier removes.

---

## 4. Design principles for what comes next

1. **Two stages beat one model.** High-recall cheap stage → high-precision
   VLM stage. Recall is easy and cheap; precision is where the VLM earns its
   cost; never ask one model to do both.
2. **The VLM is a label factory, not just a runtime cost.** Every describe /
   rerank / verify call is a free in-domain training label. Log them.
3. **Distil to shrink cost, don't hand-craft to beat the VLM.** Stop trying
   to out-engineer a VLM with a linear model on PIL features. Train small
   models *on the VLM's own outputs* and let them early-exit the easy cases.
4. **Give a technique a fair test or don't log it.** Real model size, GPU,
   real data, and an eval big enough to measure the effect. An un-run spike is
   not a negative result.
5. **Match the eval to the decision.** A ship/no-ship decision needs an eval
   where the bar sits above the noise floor. Grow the gold set before setting
   8/9 bars.
6. **Fix the data/capture problem in the cheapest place.** Some failures (E1,
   E9, defect ceiling) are software trying to recover what capture never
   recorded. A capture-side fix is cheaper and more accurate than any model.

---

## 5. Roadmap

Organised simple → ambitious. Each item names which of **fast / cheap /
accurate** it moves.

### 5.0 Housekeeping — do this first (days)

- **Re-triage docs/21** into `{genuine-negative, un-run, under-powered,
  mis-evaluated, mis-targeted, win}` using §2. Retire the three genuine
  negatives (E1-as-designed, E9, E15/E20-as-designed) — stop retrying them.
  Reclassify E10 as a **win**. *(Restores an honest baseline to plan from.)*
- **Decide the external-data question explicitly.** Either download Tier-A
  (KonIQ-10k, Indoor67, filtered OI V7) and actually run E16/E17/E18, or mark
  them **won't-run** with a reason. Un-run ≠ fail. *(Unblocks 4 spikes.)*
- **Get one GPU session** (cloud or local). Re-running E4/E7/E19 on CPU with
  base encoders will keep failing for reasons that have nothing to do with the
  idea. *(Prerequisite for a fair test of the relevance/shot-scale family.)*

### 5.1 Near-term wins — ship what already works (1–2 weeks)

**Production status (11 Jul 2026): shipped.** The build path now performs the
E8 bounded semantic cover rerank with evidence/model-bound caching, E2 bounded
seam refinement, and E10 Grounding DINO proposals followed by a cheap
cross-frame/high-confidence verification stage. GDINO is the default detector;
the optional ML dependency remains fail-soft when weights are unavailable.

- **Ship E8 (VLM cover rerank) behind the build-confirm.** 9/9 on gold at
  ~$0.20/build, cacheable by frame sha256. Cover is a per-room, ~9-call,
  *bounded* task — the VLM here is cheap **and** accurate. Stop trying to beat
  it with a linear model on 9 rooms. → **accurate** (77.8% → ~100% top-1),
  cost negligible and disclosed.
- **Ship E2 (VLM seam refine) on live seams** where built schedules show
  bleed; measure real cost. Keep gemini-flash naming. → **accurate**
  (open-plan/threshold bleed ↓), **cheap** (pennies).
- **Adopt Grounding DINO as the detection stage-1 (reframed E10).** Apache-2.0
  removes the YOLOE AGPL blocker *and* gives +17.3 pp recall. Kill the false
  "noise" gate: pair high-recall proposals with a **cheap verify** (crop →
  small classifier or one batched VLM call per room) to drop unmatched labels.
  → **accurate** (recall ↑), **cheap** (licence + no per-item VLM), unblocks
  the AGPL decision in docs/19 §9 Q1.

### 5.2 Attack the real bottleneck — the describe step (3–6 weeks)

**Production status (11 Jul 2026): tiered routing shipped.** Gemini drafts the
room; only low-confidence items, visible defect claims and missing/ambiguous
grades are sent to Opus. Expert output is name-bound to the routed draft set so
it cannot expand the report with unrelated items. If the optional expert stack
or credentials are unavailable, the draft survives and the human review queue
remains the final fallback.

This is where cost and the 20% error live, and it's the gap in the current
programme.

- **Frame-pool reduction, measured properly (E3 done right).** Run on the full
  IMG_5512 report, hold notable recall on InventoryFlex, and report **token /
  $ saved**, not a proxy decile. Target docs/19 G4: −15% describe tokens, zero
  recall loss. → **cheap**, **fast**.
- **Tiered VLM routing.** Cheap model (gemini-flash / haiku) drafts every item;
  route only *low-confidence / defect-claim / ambiguous-grade* items to opus.
  docs/04 already shows the recall-vs-trust split by tier — exploit it with a
  router instead of one model for everything. → **cheap** (most items leave the
  cheap tier), **accurate** (opus where it matters).
- **Distil a small open-weights VLM** (e.g. Qwen2.5-VL / InternVL class) on
  accumulated opus-labelled describe outputs. Once it matches the cheap tier on
  the common cases, it runs on our own GPU at ≈£0 marginal. → **cheap** at scale
  (removes per-token API spend), **fast** (local), accuracy pinned by opus
  fallback on the hard tail.

### 5.3 Fix the accuracy ceilings at their source (parallel, 3–8 weeks)

- **Native-resolution capture (M2).** docs/04 says defect recall (64–71%) and
  small wall-mounted-item recall are **resolution-bound**. No defect model
  (E15/E20) can clear this until the fixture is native-res. This is the highest-
  leverage single change for the defect ceiling and it's a *capture/data* task,
  not an ML task. → **accurate** (defect recall unblocked).
- **Grow the eval sets so results are trustworthy.** Expand hero-gold to
  ≥30–50 rooms across ≥5 properties (kills the n=9 problem, §3.3); label 3–5
  more walkthrough videos for segmentation boundaries; scale E11 bbox labels
  from 101 toward the fine-tune-feasible range. Use **VLM auto-label + human
  review** (active learning) to keep it cheap — E11's `label_boxes.py`
  bootstrap→trim→review loop is the right template. → enables *every* small-
  model experiment to have a fair test.

### 5.4 Ambitious — the distillation flywheel (quarter+)

The structure that improves all three dimensions at once and **compounds**:

```text
cheap high-recall stage  →  VLM precision stage  →  log (input, VLM output)
        ↑                                                     │
        └──────────  train in-domain small model  ←───────────┘
                     (early-exit easy cases; VLM handles the tail)
```

- **Detection:** Grounding DINO + VLM-verify labels (§5.1) become bbox training
  data → distil a fast Apache detector that inherits the recall without the
  per-image VLM verify. This is the *real* E12 — a fine-tune on hundreds of
  verified boxes, not 37 pseudo-boxes.
- **Cover / relevance:** E8's per-room VLM picks become "establishing vs not"
  labels → fine-tune a **small in-domain head** (the correct target signal from
  §3.4, replacing the MUSIQ distillation) that runs at <50 ms/frame and only
  defers ties to the VLM.
- **Describe:** §5.2's distilled VLM is the flagship of the flywheel — the
  cheap tier gets better every property, opus spend falls monotonically, and
  accuracy never drops below the opus fallback.

**Why this is the answer to "fast, cheap, accurate":** accuracy is bounded
below by the VLM at all times; cost falls as the distilled models take more
traffic; latency falls as work moves local. It's the only structure where the
three don't trade off against each other.

### 5.5 Capture-side bets that dissolve whole problem classes (opportunistic)

Some of the hardest software problems vanish if capture records the right
signal:

- **Segmentation & cover:** a "hold 2 s facing each room" capture cue + phone
  **IMU/motion metadata** makes room boundaries and establishing frames nearly
  free — dissolving E1 and E9 rather than modelling around them. (Guided
  capture UX was killed in docs/12; a *passive* motion-metadata read is not the
  same thing and worth revisiting.)
- **Audio:** door-latch / footstep VAD at doorways is an untapped, £0
  segmentation cue when audio is present (docs/19 §1.1 D) — never spiked.

---

## 6. What to stop, keep, and start

| Stop | Keep | Start |
|---|---|---|
| Logging un-run spikes as "fail" (§3.1) | E11-style VLM-assisted labelling | Downloading Tier-A data **or** marking won't-run |
| Zero-shot base encoders on CPU (§3.2) | "Cheap proposes, VLM disposes" (E2/E8) | Distillation flywheel (§5.4) |
| Distilling MUSIQ for cover (§3.4) | E5 classical cover as the free fallback | Tiered describe routing (§5.2) |
| 8/9 bars on a 9-room eval (§3.3) | gemini-flash segmentation naming | Native-res fixture for defect (§5.3) |
| Retrying E1/E9/E15-as-designed | Grounding DINO (Apache) for detection | Multi-property eval sets (§5.3) |
| Hand-crafting to beat the VLM | opus for the signed report | Grounding DINO + verify cascade (§5.1) |

---

## 7. Suggested revised sequence

```text
Now        Re-triage docs/21; GPU session; external-data decision  (§5.0)
Sprint 1   Ship E8 cover rerank + E2 seam refine; GDINO stage-1     (§5.1)  ← LANDED
Sprint 2   Describe: pool reduction (real) + tiered routing         (§5.2)
Parallel   Native-res fixture; grow hero-gold + bbox + seg labels   (§5.3)
Quarter    Distil describe VLM; distil detector; in-domain cover    (§5.4)
Opportun.  Motion-metadata / audio capture signals                 (§5.5)
```

**Production wiring (12 Jul 2026):** ML-E2 / ML-E8 / ML-E10 are on the build
path in `pipeline.py` / `ingest.py` / `detect.make_build_detector`, with
CLI opt-outs and graceful fallback when credentials or GDINO deps are absent.

## 8. Success metrics (revised from docs/19 §8)

| Dimension | Current | Target |
|---|---|---|
| **Accurate** — signed-report condition-exact | 93.2% (opus) | hold, at lower cost |
| **Accurate** — defect recall | 64–71% (all backends, res-bound) | ≥75% after native-res capture |
| **Accurate** — detection notable recall | 58.7% (YOLOE) | ≥73% (GDINO + verify), Apache |
| **Accurate** — cover top-1 | 77.8% | ~100% (E8) or ≥89% (distilled head) |
| **Cheap** — describe $/property | ~$1.17 (opus) | ≤$0.30 via routing + distillation, recall held |
| **Cheap** — licence | YOLOE AGPL | Apache stack end-to-end |
| **Fast** — describe latency | API-bound | local distilled tier on the common cases |

Product guardrails unchanged (docs/10): hallucination and condition-exact
must not regress when any cheaper tier is enabled; gate on InventoryFlex
before ship.

---

## 9. Related

| Path | Role |
|---|---|
| `docs/21-ml-dl-experiment-log.md` | The 20 spikes reviewed here |
| `docs/19-ml-dl-exploration-plan.md` | Original plan, pass bars, dataset tiers |
| `docs/18-hero-image-selection.md` | Cover scorer E0–E5, hero-gold |
| `docs/04-backend-comparison.md` | Describe cost/accuracy by backend (§3.5 numbers) |
| `docs/12-video-first-journey.md` | Product journey, cost policy |
| `evals/ml_scorers.py` | Encoder defaults (§3.2) |
| `evals/external/README.md` | Dataset downloads (never run — §3.1) |
```
