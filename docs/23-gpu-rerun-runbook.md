# 23 — GPU re-run runbook

*6 Jul 2026. Execution runbook for re-running the ML/DL spikes **properly** on
a CUDA GPU, and for the native-resolution capture workstream. Companion to the
post-mortem docs/22, which argued most of the 16 "failures" were un-run,
under-powered (smallest encoder on CPU), or mis-evaluated — not evidence the
technology is wrong. This doc is what you run on the GPU box to find out for
real.*

**Target machine:** Windows laptop · NVIDIA GPU **8 GB VRAM** · CUDA · ample
disk. Everything below is sized to fit 8 GB (inference and light fine-tunes fit;
the one heavy pretrain — E18 GDINO — is flagged and batch-limited).

---

## 0. One-time setup

```powershell
# from the repo root, after: git pull
uv sync
uv pip install -e ".[ml,detect]"

# CUDA torch build (the .[ml] extra pulls a default torch — replace with cu128):
uv pip install --reinstall-package torch --reinstall-package torchvision `
  torch torchvision --index-url https://download.pytorch.org/whl/cu128

# verify the GPU is visible
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Then pull the datasets (cross-platform downloader — replaces the bash heredocs):

```powershell
uv run python evals/external/scripts/download_datasets.py --list
uv run python evals/external/scripts/download_datasets.py indoor67      # ML-E16, ~150 MB
uv run python evals/external/scripts/download_datasets.py film-shots    # ML-E19, <100 MB
uv run python evals/external/scripts/download_datasets.py koniq         # ML-E17, prints manual steps (~2 GB)
uv run python evals/external/scripts/download_datasets.py open-images --max-samples 30000  # ML-E18, ~5–15 GB
```

**Video for report-based evals (E3, E4, E5, E7, E13, E19):** those score frames
under a built `report/` from `examples/videos/IMG_5512.MOV` (~1.3 GB, not in
git). Copy the video to the box and rebuild once:

```powershell
uv run python -m homeinventory.cli build capture-walkthrough -o report `
  --segments-json segment-spike-multi/gemini-3.5-flash/segments.json --no-pdf
```

---

## 1. How to read the status tiers

docs/22 re-triaged the 20 spikes by *why* they didn't pass. This runbook groups
them by **what it takes to run them fairly** now:

| Tier | Meaning | Experiments |
|---|---|---|
| **T1 — turnkey** | Real eval already; only needed a fair encoder + CUDA. One flag fixes it (repo prep done). | E4, E7, E19 |
| **T2 — real trainer added** | Was a stub; a real training path shipped in this prep. Download + run. | E16 |
| **T3 — real code, data-limited** | Real train/eval code; failed on data volume, not model. Needs more labels / the full video. | E12, E3 |
| **T4 — frontier** | Needs a heavy pretrain or a dataset + fine-tune that doesn't exist yet. | E18, E17, E20 |
| **RETIRE — genuine negative** | The signal isn't in the data or the eval is structurally broken. Do **not** re-run as-is. | E1, E9, E15 |

---

## 2. T1 — turnkey fair-encoder re-runs

The repo prep threaded an encoder override through the relevance/shot-scale
harnesses. The old runs used `ViT-B-32`/`siglip-base-224` on **CPU** — the
weakest common variants — which is why ρ came out negative/zero (docs/22 §3.2).
Re-run with a real encoder on CUDA. All three fit in 8 GB (ViT-L-14 ≈ 1.7 GB).

**ML-E4 — SigLIP/OpenCLIP relevance margin** *(pass bar: mean ρ ≥ 0.66)*

```powershell
uv run python evals/eval_relevance_siglip.py report `
  --relevance-backend siglip --relevance-model google/siglip-large-patch16-384 `
  --device cuda --gold evals/fixtures/own-property/hero-gold.json
# OpenCLIP ViT-L-14 alternative:
uv run python evals/eval_relevance_siglip.py report `
  --relevance-backend openclip --relevance-model ViT-L-14 `
  --relevance-pretrained laion2b_s32b_b82k --device cuda
```

**ML-E7 — CLIP establishing prompt pairs** *(bar: top-1 ≥ 7/9, <100 ms/frame)*
Same harness, same encoder override — plus latency is now GPU-bound (the old
589 ms/frame was CPU). Compare `--scorer clip-establishing` vs `siglip`.

**ML-E19 — shot-scale (long vs close-up)** *(bar: ρ ≥ classical ~0.44)*

```powershell
uv run python evals/eval_shot_scale.py report --backend open_clip `
  --model ViT-L-14 --pretrained laion2b_s32b_b82k --device cuda `
  --gold evals/fixtures/own-property/hero-gold.json
```

> **Note on the eval set:** hero-gold is **9 rooms of one property** (docs/22
> §3.3). Even a fair encoder is measured against n=9 with an 8/9 bar. Treat T1
> results as *directional*; a real ship decision needs the expanded gold set
> (§6). If a fair encoder still gives ρ near 0, that is a real negative for
> zero-shot relevance and we stop pursuing it.

---

## 3. T2 — E16 room classifier (real trainer shipped)

The old `eval_room_classifier.py` never trained a model — it counted labels and
fell back to zero-shot ViT-B-32 (true-room top-1 **8.6%**). This prep adds
`evals/train_room_classifier.py`: it embeds Indoor67 with a fair encoder and
trains an actual linear softmax head over the ~10 inventory rooms.

```powershell
# train the head (ViT-L-14 embeddings; fits 8 GB at batch 64)
uv run python evals/train_room_classifier.py `
  --encoder-model ViT-L-14 --pretrained laion2b_s32b_b82k `
  --device cuda --epochs 60 --max-per-class 400

# evaluate on the wrong-room bleed audit (resolves frames from report/)
uv run python evals/train_room_classifier.py report --eval-only --device cuda
```

**Pass bar (ML-E16):** would-reject on the 35-item bleed audit ↑ **and**
true-room top-1 well above the stub's 8.6% (target ≥60%). Writes
`room-clf-weights.json` (MIT head) + `room-clf-eval.json`. Sanity check without
any download: `--self-test`.

---

## 4. T3 — real code, data-limited

**ML-E12 — detector fine-tune.** `eval_finetune_detect.py` already runs a real
ultralytics YOLOE-seg fine-tune; it regressed only because it trained on **37
pseudo-boxes** from rooms lacking the val classes (docs/21). The fix is *data*,
not code:

1. Scale bbox labels beyond E11's 101 (the `label_boxes.py` bootstrap→trim→
   review loop) — aim for ≥300 across ≥4 rooms incl. Kitchen + Bathroom.
2. Re-run on CUDA with more epochs:

```powershell
uv run python evals/eval_finetune_detect.py benchmarks/inventoryflex/capture `
  evals/fixtures/inventoryflex/labels.json --device cuda --epochs 50
```

VRAM: YOLOE-11s-seg fine-tunes inside 8 GB at batch 4–8 / 640 px. **Licence:**
YOLOE is AGPL — probe/eval only; the Apache path is E18 (below) or GDINO+verify
(docs/22 §5.1). Pass bar: +10 pp recall @0.5 IoU on the val boxes.

**ML-E3 — describe-pool reduction.** Re-run on the **full** IMG_5512 `report/`
(the old run used a 19-frame proxy), and report tokens/$ saved with notable
recall held on InventoryFlex:

```powershell
uv run python evals/eval_describe_pool.py report
```

Pass bar (G4): ≥15% frames dropped with zero notable-recall loss.

---

## 5. T4 — frontier (heavy or mis-targeted)

**ML-E18 — Open Images V7 → Grounding DINO household pretrain.** This is the
Apache-licence detection path and the only genuinely heavy job. On 8 GB VRAM,
GDINO (Swin-T) *inference* is fine, but *fine-tuning* must run at **batch 1–2
with gradient checkpointing** and will be slow — treat as an overnight run.

1. `download_datasets.py open-images --max-samples 30000` (already above).
2. Fine-tune GDINO on the 42-class household subset → save to
   `evals/external/data/open-images-v7/weights/gdino-oi-household.pt`
   (path expected by `evals/oi_vocab.DEFAULT_OI_WEIGHTS`). The GDINO training
   loop is **not** yet in-repo — use the official `Open-GroundingDino` finetune
   config against the FiftyOne export; this is the one item that needs code
   written on-box.
3. Eval vs the E10 GDINO baseline:

```powershell
uv run python evals/eval_detect_oi_pretrain.py benchmarks/inventoryflex/capture `
  evals/fixtures/inventoryflex/labels.json --device cuda
```

Pass bar: notable recall ↑ vs E10's 76.0%. **Recommended alternative** (docs/22
§5.1): skip the pretrain and run GDINO **stage-1 high-recall + cheap verify** —
E10 already gave +17.3 pp at Apache licence; the "noise" that failed it is what
a verifier removes. That is likely the better ROI than an 8 GB GDINO pretrain.

**ML-E17 — KonIQ-10k IQA.** Download works (`download_datasets.py koniq`), but
be aware: `train_iqa_koniq.py` fits a **linear head on hand-crafted PIL
features** — real KonIQ MOS only changes the training *target*, not the model
class, and the eval scores through those same PIL features. So a KonIQ download
alone will not make this a real learned-IQA test. Worse, it is **mis-targeted**
(docs/22 §3.4): MUSIQ/KonIQ measure technical quality, not the *semantic*
"establishing room" the cover task needs. **Recommendation:** deprioritise for
cover (use E8 VLM rerank). If you want a licence-clean *within-room quality*
ranker, reuse the embedding-head engine in `train_room_classifier.py` in
regression mode on KonIQ — that is the correct E17, and needs the eval scoring
path updated to consume embeddings.

**ML-E20 — defect pre-filter pretrain.** Needs Tier-C data (BD3 / StructDamage,
docs/19 §2.4) *and* is evaluated on the broken clean-only fixture (see RETIRE).
Do this only after native-res + localized defect labels exist (§6).

---

## 6. Native-resolution capture workstream

docs/04 pins defect recall (64–71% across **all** backends) and small
wall-mounted-item recall to **capture resolution** — the InventoryFlex fixture
is 800×600. No defect model (E15/E20) can clear the ≥75% bar until this is
fixed. This is the highest-leverage single change for the accuracy ceiling and
it is a *data* task.

**Plan:**

1. **Native-res source.** Re-capture (or source the originals of) the benchmark
   property at full phone resolution — photos and/or a native-res walkthrough.
   Keep the same room set so the 116-item gold still applies.
2. **Rebuild the fixture** at native res under a new dir
   (`benchmarks/inventoryflex-nativeres/`) so the 800×600 baseline stays for
   regression comparison.
3. **Re-run describe eval** on each backend; measure the defect-recall lift vs
   the 800×600 baseline. This alone tests the docs/04 hypothesis.
4. **Localized defect labels.** Extend the E11 `label_boxes.py` loop to draw
   **defect** boxes (scratch/stain/chip) on ≥50 instances. This unblocks proper
   defect *recall* metrics (not just the FP rate that broke E15/E20) and any
   defect-presence classifier.

**Definition of done:** a native-res benchmark with a measured defect-recall
delta, and ≥50 localized defect boxes committed as gold.

---

## 7. Do NOT re-run as-is (genuine negatives)

Re-running these unchanged wastes GPU time — the finding is real (docs/22 §3.5):

- **ML-E1 (embedding changepoint):** a slow handheld doorway pass produces a
  smooth embedding drift, not a spike; open-plan has no boundary. Wrong signal
  model. Cheap segmentation should instead be VLM naming-only on a coarse strip,
  or audio/motion cues (docs/22 §5.5) — not a bigger encoder.
- **ML-E9 (optical-flow pause):** walkthroughs are continuous motion; there are
  no pauses to detect. Fix is capture UX ("hold 2 s"), not a model.
- **ML-E15 (defect zero-shot):** evaluated for FP rate on deliberately-clean
  photos with **zero defect positives** — structurally can't validate recall.
  Redo only after §6 gives real defect positives.

---

## 8. Per-experiment quick reference

| ID | Tier | Command (abbrev.) | 8 GB VRAM | Pass bar |
|---|---|---|---|---|
| E4 | T1 | `eval_relevance_siglip … --relevance-model siglip-large-384 --device cuda` | ✅ ~2 GB | ρ ≥ 0.66 |
| E7 | T1 | `eval_hero_cover --scorer clip-establishing --relevance-model ViT-L-14 --device cuda` | ✅ | top-1 ≥7/9, <100 ms |
| E19 | T1 | `eval_shot_scale --model ViT-L-14 --pretrained laion2b_s32b_b82k --device cuda` | ✅ | ρ ≥ 0.44 |
| E16 | T2 | `train_room_classifier --device cuda` then `--eval-only report` | ✅ ~2 GB | reject ↑ & true-room ≥60% |
| E12 | T3 | `eval_finetune_detect … --device cuda --epochs 50` (needs more boxes) | ✅ batch 4–8 | +10 pp recall@0.5 |
| E3 | T3 | `eval_describe_pool report` (full video) | n/a | −15% frames, recall held |
| E18 | T4 | OI download → GDINO finetune (on-box) → `eval_detect_oi_pretrain --device cuda` | ⚠️ batch 1–2 | recall ↑ vs 76% |
| E17 | T4 | `download_datasets.py koniq` → embedding-head regressor | ✅ | ≥ E6, but mis-targeted |
| E20 | T4 | needs §6 defect labels first | — | FP <10% w/ real positives |
| E1/E9/E15 | RETIRE | — | — | do not re-run as-is |

---

## 9. Logging results back

For each run, append to `evals/external/README.md`'s experiment-log table
(date · ML-E · dataset path · notes), update the status row in
**docs/21-ml-dl-experiment-log.md**, and commit the artifact JSON/HTML. Keep
`.pt` weights out of git (gitignored); commit small JSON heads (≤10 MB) or a
download/train command. If a T1 fair-encoder run still fails, that flips it from
"under-powered" to a **real negative** in docs/22 — record which.

## 10. What this prep changed in the repo

| Change | File | Enables |
|---|---|---|
| Encoder override flags | `ml_scorers.py`, `eval_hero_cover.py`, `eval_relevance_siglip.py`, `eval_shot_scale.py` | Fair E4/E7/E19 on CUDA |
| Real E16 trainer | `evals/train_room_classifier.py` | E16 stub → real linear head |
| Cross-platform downloader | `evals/external/scripts/download_datasets.py` | Windows-safe Tier-A pulls |
| `[ml]` dependency extra | `pyproject.toml` | `uv pip install -e .[ml]` |
| This runbook | `docs/23` | The plan you're reading |

Related: docs/22 (post-mortem + roadmap), docs/19 (original plan/pass bars),
docs/21 (status log), docs/04 (backend cost/accuracy, resolution ceiling).
