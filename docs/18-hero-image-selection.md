# 18 — Room hero image selection

*5 Jul 2026. Spun out from the overview-gallery work after heuristic
iterations regressed cover quality on the own-property walkthrough
(`examples/videos/IMG_5512.MOV`). Quality bar stays docs/10; curation
architecture stays docs/15; this doc owns **rank-1 room cover** selection
only — not the full hero set, not item crops, not segmentation.*

## Why this matters

The overview gallery is the product's first comprehensiveness check: *did
it get the whole property?* Room cards with wrong, blurry, or object
close-up thumbnails undermine trust before the user reads a single item.
The same rank-1 frame heads each report room section and the tenant room
gallery. **High-quality, well-selected imagery is not polish — it is the
proof that the walkthrough was understood.**

Success looks like: every room card shows a recognisable establishing
view — walls, floor, ceiling or doorway context — sharp enough to stand
on a brochure cover. Failure looks like: hobs, wardrobes, shower fittings,
motion-blurred passes, or frames from the wrong room.

## Scope

| In scope | Out of scope (other docs / modules) |
|---|---|
| **Rank-1 cover** per room (overview thumbnail, report room header) | MMR hero-set election for the filmstrip (docs/15) |
| Scoring / ranking candidates within a room's frame pool | Item-description backend choice |
| Cover-oriented candidate acquisition at segment boundaries | General segmentation model selection (docs/11) |
| Evaluation harness + gold rankings on the own-property build | Segment boundary placement (docs/11) — though bleed affects pool purity |
| Reviewer promote/demote persistence (docs/15 M3) | Item-level YOLOE crops (docs/15 M4) |
| Experiment log and adoption criteria | Learned describe backend choice |

**Constraint (unchanged from docs/15):** nothing deletes frames. A bad
cover candidate stays in the disclosed tier; we only change what is shown
by default at rank 1.

## Where rank 1 is consumed

```text
build → curate.py → Photo.hero = 1 per room
                         ↓
          review overview  report cover  tenant gallery
          (roomHeroSrc)  (section.cover)  (heroThumb)
```

All three sort heroes by ascending `hero` and take the first available
thumbnail. **Only rank 1 needs to be an establishing shot.** Ranks 2–6
can remain detail frames useful for the filmstrip.

## Own-property fixture

| Field | Value |
|---|---|
| Video | `examples/videos/IMG_5512.MOV` (~13.4 min, 803 s) |
| Segments | reviewed `report/work/segments/IMG_5512.json` (13 segments, 10 room names after repeated-room merge) |
| Frames | 145 keyframes: 12/minute (max 24/segment) plus a 2 s boundary anchor |
| Active fixture | `hero-gold-dense-anchor.json` + `hero-candidates-dense-anchor.json` |
| Manual reference | Pre-M2 per-room clips + `report/inventory.json` from folder capture (10 rooms); use for eyeball gold, not automatic labels |

Rebuild command (reuse cached segments):

```bash
uv run python -m homeinventory.cli build capture-walkthrough -o report \
  --segments-json report/work/segments/IMG_5512.json \
  --progress-file report/build-progress.json
```

Re-curate only (no describe cost):

```bash
uv run python -m homeinventory.cli curate-only capture-walkthrough -o report \
  --detect --no-pdf
```

Reloads `report/inventory.json`, re-scores frame paths, optionally reruns the
local detector-assisted semantic pass (`--detect`), writes `inventory.json`,
and re-renders `inventory.html` without ingest or describe API spend. Use after
changing scorer logic or reviewer overrides.

## Failure modes (catalogue)

Observed on IMG_5512, Jul 2026 sessions:

| Failure | Example | Typical cause |
|---|---|---|
| **Object close-up** | Kitchen hobs, Loft wardrobe, shower door | Laplacian / smooth heuristics reward textured surfaces |
| **Wrong room** | Kitchen card showing hallway | Segment boundary bleed into first keyframes (partially fixed: `SEGMENT_BOUNDARY_TRIM_S`) |
| **Motion blur** | Smear across frame | Sharpness gate ranks "best of a bad window" (extract_keyframes design) |
| **Partial / odd framing** | Floor clutter, ceiling-only, door edge | Cover picked from full pool without composition semantics |
| **Regression via proxy metrics** | v2 smooth-fraction picks early blurry hallway pass | Single-number scores don't encode "recognisable room" |

## What we tried (experiment log)

### E0 — Baseline (docs/15 M2)

- **Method:** Laplacian sharpness × exposure → MMR elects 3–6 heroes; rank 1 = first elected.
- **Result:** Texture bias documented in docs/15 IQA benchmark (wallpaper, oven racks, clutter).
- **Verdict:** ❌ Not acceptable for covers; acceptable starting point for filmstrip set.

### E1 — Quadrant + vertical-band balance

- **Method:** `establishing_score` penalises edge concentration in one quadrant; rewards top/middle/bottom band balance. Rank 1 promoted among elected heroes only.
- **Change:** `0.4 + 0.6 × establishing` quality multiplier.
- **Result (Jul 5):** User: *"certainly better"* — Hallway, Living Room mostly OK; Kitchen hobs, Loft wardrobe, Loft shower still wrong.
- **Verdict:** ⚠️ Partial improvement; rank-1 pool too narrow (only MMR winners).

### E2 — Smooth fraction + centre/border ratio + full-pool rank 1

- **Method:** Add smooth-pixel fraction and centre-vs-border Laplacian ratio; pick rank 1 from **all** frames above 2.5% of room max sharpness; stronger establishing weight (`0.25 + 0.75 × establishing`).
- **Result (Jul 5):** User: *"significant regression across the board"* — blurry passes, floor clutter, fixture close-ups, early-segment frames.
- **Verdict:** ❌ **Reject.** Smoothness proxy confuses *empty blur* with *wide wall area*; full-pool search amplifies mistakes.
- **Action:** Revert E2 before the next build; keep E1 or E0 until a validated replacement ships.

### E3 — Segment boundary trim (ingest)

- **Method:** `SEGMENT_BOUNDARY_TRIM_S = 2.0` on segment starts after the first.
- **Result:** Reduces wrong-room frames in pool; does not fix close-up selection within the correct room.
- **Verdict:** ✅ Keep — orthogonal hygiene, tests in `tests/test_ingest_segment.py`.

### E4 — Hard gates before ranking (curate)

- **Date:** 5 Jul 2026
- **Method:** Approach A — reject candidates below room-median sharpness, above 15% clipped exposure, empty blur (smooth fraction > 0.97 and sharpness < room p25), or centre/border Laplacian ratio > 3.0; rank survivors by establishing score within the MMR hero pool.
- **Result:** top-1 hit **44.4%** (4/9) on IMG_5512 gold — regressed vs E1; Loft Bedroom and Loft Shower re-picked wardrobe/shower close-ups.
- **Verdict:** ❌ **Reject for product.** Gates kept in `eval_hero_cover.py --scorer hard-gates` for offline comparison only.
- **Artifacts:** `evals/fixtures/own-property/hero-contact-hard-gates.html`

### E5 — Cover score + establishing slot + adaptive sharpness (curate)

- **Date:** 5 Jul 2026
- **Method:** After MMR, admit one **cover slot** hero (best `cover_score = establishing × min(1, 2.5/cbr)` among frames with quality ≥ 12% of room max). Rank 1 = max cover_score among heroes; reject a low-quality winner (< 25% of room max) when a sharper alternative scores within 8%. Pool stays narrow (heroes + slot — not full frame pool).
- **Result:** top-1 hit **77.8%** (7/9), top-3 hit **100%** (9/9) on IMG_5512 gold. Kitchen and En-suite pick gold #3 frames (still top-3 hits). The v2 regression contract separately requires every rank 1 to belong to the human-approved `acceptable` set and locks exact curator preference at ≥ 7/9.
- **Verdict:** ✅ **Adopted** as product rank-1 scorer (E1 MMR + E3 boundary trim unchanged).
- **Artifacts:** `evals/fixtures/own-property/hero-contact-cover.html`, `report/inventory.html` after `curate-only`

### E6 — Dense extraction + boundary cover anchors (ingest)

- **Date:** 12 Jul 2026
- **Method:** Increase the duration-scaled budget from 6 to 12 frames/minute
  (cap 24), and preserve one sharp frame from the first 2 seconds after every
  detected room boundary before applying the existing 2-second bleed trim.
  Persist `Photo.cover_anchor` so downstream ranking can use acquisition
  provenance. An explicit `--trim-lead` still suppresses anchors.
- **Visual result:** acceptable candidates are available in **10/10 rooms**.
  The pool recovered the living-room sofa view, kitchen-wide view, both bed-led
  bedroom views, loft sofa overview, and loft-shower doorway view.
- **Verdict:** ✅ **Adopted.** The old trim removed useful entry views while the
  old sparse windows missed brief wide pans.
- **Fixture:** `hero-candidates-dense-anchor.json` freezes all 145 frames plus
  density, cap, trim, anchor duration, and reviewed-segment hash.

### E7 — Detector-assisted semantic rank 1 (curate/pipeline)

- **Date:** 12 Jul 2026
- **Method:** Keep E5 as fallback, then use normal YOLOE results for narrowly
  defined room identity: sofa/TV for living rooms; cabinets/appliances/sink for
  kitchens; bed/wardrobe for bedrooms; suite fixtures for wet rooms; sofa/desk
  for the loft room. Repetition is capped, wrong-room objects are penalised,
  anchors receive a small provenance prior, and promotion requires a defining
  detection at confidence ≥0.30. Human-hidden frames are excluded.
- **Result:** first full build: **9/10 acceptable, 7/10 preferred**. The only
  miss was a false-positive `handrail` on a partial landing. Removing stair
  semantic ranking—because true stair views were not detected reliably—and
  retaining the correct E5 fallback gives **10/10 acceptable, 7/10 preferred**.
- **Verdict:** ✅ **Adopted.** No new API call; when detection is disabled or
  unavailable, E5 remains unchanged. Stairs are deliberately unsupported until
  broader detector evidence exists.
- **Artifact:** `hero-dense-detect-metrics.json`.

### E7b — No-confident-cover handling (curate)

- **Date:** 12 Jul 2026
- **Method:** After E5 classical rank 1 and optional E7 semantic promotion,
  ``finalize_room_covers()`` assesses whether the rank-1 frame is a confident
  establishing cover. Classical checks: presentation eligibility, quality floor,
  establishing/cover score, object-fill ratio. When detections are available for
  supported room types, rank 1 must also pass room-identity evidence and must
  not show strong wrong-room labels. Unsupported types (e.g. stairs) stay on
  classical checks only.
- **Output:** ``Room.cover_status`` (`confident` | `review_required`) and
  ``Room.cover_review_reason`` in ``inventory.json``; the same map under
  ``curation.json`` → ``cover_status`` (schema v2). Rank 1 is **not** cleared —
  the review overview flags weak covers honestly.
- **Verdict:** ✅ **Adopted** — closes docs/00 Pillar 2 "flag bad segment"
  without re-adopting rejected E2 smoothness or local-Ollama E8.

### E8 — Multi-image local VLM rerank (not adopted)

- **Date:** 12 Jul 2026
- **Method:** Send six classical candidates plus boundary anchors, resized to
  384 px, to Ollama with a criteria-only prompt. Tested `qwen2.5vl:3b`; spot
  checked the living room with `gemma4:12b`.
- **Result:** Qwen exceeded its active vision context on several 7–8-image
  rooms and selected only **1/10 acceptable** overall; successful calls also
  confused image/index correspondence. Gemma selected the same bad
  window/light close-up and described features absent from it.
- **Verdict:** ❌ **Reject for product.** It was slower, weaker, and less
  auditable than the existing detector. `eval_vlm_rerank.py` remains an
  experiment harness with Ollama and Anthropic providers.

### docs/15 IQA benchmark (not adopted for product)

- MUSIQ ranked closer to human within-room order (ρ ≈ 0.66 vs classical) but CC BY-NC-SA blocks product use; ~100× slower.
- CLIP-IQA disqualified (overexposure bias).
- **Note:** MUSIQ still useful as an **offline evaluation oracle** in `evals/eval_iqa.py`.

## Evaluation methodology

Every experiment must produce **inspectable artifacts**, not just a
single accuracy number (same standard as docs/11 segmentation spike).

### 1. Gold rankings (human)

For each room in IMG_5512, curator ranks **top 3** and **bottom 2** frames
at full resolution with one-line rationale. Store in:

```text
evals/fixtures/own-property/hero-gold-dense-anchor.json
```

Schema v2 separates acceptable covers from ordered preference and binds the
labels to an immutable candidate manifest:

```json
{
  "schema_version": 2,
  "benchmark_id": "own-property-img5512-dense-anchor-v2",
  "candidate_manifest": "hero-candidates-dense-anchor.json",
  "video": "IMG_5512.MOV",
  "rooms": {
    "Kitchen": {
      "preferred": ["IMG_5512_f00….jpg", "…"],
      "acceptable": ["IMG_5512_f00….jpg", "…"],
      "rejected": ["…"],
      "review_required": [],
      "notes": "Need hob + cabinets visible, not hob surface fill"
    }
  }
}
```

Until gold exists, use ** pairwise eyeball** on contact sheets (below).

`hero-candidates-dense-anchor.json` freezes all 145 current room/frame
assignments and anchor identities. The original 93-frame contract remains in
`hero-gold.json` / `hero-candidates.json` for historical comparisons. Private
pixels remain untracked.
Evaluators refuse accuracy metrics when a report's rooms or filenames differ
from this manifest; `--allow-incompatible-gold` exists only for explicitly
labelled forensic comparisons. This prevents segmentation or keyframe drift
from masquerading as a cover-scoring regression.

### 2. Contact sheet per scorer

Harness: `evals/eval_hero_cover.py`

- Input: build output dir or frame directory + room assignment
- Per room: grid of all frames with overlay: sharpness, each scorer's rank, gold rank if present, **★** on current pick
- Output: `evals/fixtures/own-property/hero-contact-<scorer>.html`
- Sort rooms in walkthrough order

Usage (after a build or `curate-only` run):

```bash
# Contact sheet for the current curate scorer on the own-property build
uv run python evals/eval_hero_cover.py report

# Named scorer variant (e.g. hard-gates experiment E4)
uv run python evals/eval_hero_cover.py report --scorer hard-gates \
  -o evals/fixtures/own-property/hero-contact-hard-gates.html

# Gold metrics against the active dense-anchor contract
uv run python evals/eval_hero_cover.py report --gold \
  evals/fixtures/own-property/hero-gold-dense-anchor.json
```

Typical experiment loop: edit `curate.py` → `curate-only` → `eval_hero_cover.py`
→ eyeball contact sheet → log verdict here.

### CI regression pinning (mutable ``report/``)

Before the dense-anchor contract, ``tests/test_curate.py`` included
``test_rank1_matches_hero_gold_when_fixture_present``, which read rank 1 from
the local ``report/inventory.json`` tree. That directory is **gitignored** and
absent on CI, so the test silently returned when missing; locally, a stale or
partial re-curate could report **2/9** preferred hits while gold expected ≥7/9.

**Resolution:** rank-1 agreement is pinned to immutable fixtures only:

| Artifact | Role |
|---|---|
| ``hero-gold-dense-anchor.json`` | Human acceptable/preferred labels (schema v2) |
| ``hero-candidates-dense-anchor.json`` | Frozen 145-frame room/frame identity |
| ``hero-dense-detect-metrics.json`` | Frozen E7 ``rank1`` map from the benchmark run |

``test_rank1_is_acceptable_on_compatible_hero_benchmark`` asserts 10/10
acceptable membership; ``test_rank1_matches_hero_preference_on_compatible_benchmark``
locks ≥7/10 exact preference. Neither reads ``report/``. Eval harnesses that
still accept a report path refuse incompatible gold with an explicit drift
diagnosis (``eval_hero_cover.py --gold``).

### 3. Metrics (per room, then mean)

| Metric | Definition |
|---|---|
| **top-1 hit** | Gold #1 == scorer #1 |
| **top-3 hit** | Gold #1 in scorer top 3 |
| **acceptable hit** | Scorer #1 belongs to the human-approved acceptable set |
| **candidate available** | At least one acceptable frame exists in the room pool |
| **ρ (Spearman)** | Rank correlation vs gold (needs ≥5 ranked frames) |
| **blur reject rate** | Fraction of picks where Laplacian < room median |
| **regression vs prior** | Side-by-side HTML of E(n) vs E(n−1) picks |

**Pass bar for adoption:** rank 1 is human-approved `acceptable` in **10/10**
rooms, exact preferred rank 1 in at least **7/10**, and no privacy/wrong-room
failure. Exact preference is secondary because several images validly satisfy
the criteria; acceptable membership is the strict product invariant.

### 4. Runtime budget

Cover selection runs at build step 2b for every room. Target: **< 50 ms
per frame** on laptop (≤ 5 s for 100 frames total property), unless
quality gain is decisive and disclosed to the user at build time.

## Candidate approaches (experiment backlog)

Ordered roughly cheap → expensive. Each gets an `E4`…`En` entry in the
log when run.

### A — Hard gates before ranking (cheap, PIL)

Combine existing signals with **minimum thresholds**:

- Reject if sharpness < room median (drops blur)
- Reject if clipped exposure > 15% (drops blown windows)
- Reject if smooth fraction > 0.97 **and** sharpness < room p25 (drops empty blur)
- Reject if centre/border Laplacian ratio > 3.0 (drops object fill)

Rank survivors by weighted establishing score or MUSIQ-oracle order.

**Hypothesis:** E2 failed because blur sailed through smoothness; gates
first, then rank.

### B — Rank 1 only from elected heroes (restore E1 pool)

Revert full-pool search; improve score within MMR set only. Optionally
add one **"establishing shot" slot** to hero budget (7th hero chosen
only by establishing score, not sharpness).

**Hypothesis:** MMR set already excludes most blur duplicates; safer
search space.

### C — Temporal midpoint bias

Within each segment, prefer frames from the **middle third** of the stay
(walkthrough often enters = doorway blur, exits = next room).

**Hypothesis:** Fixes early Hallway blur picks without vision models.

### D — Downscale sharpness ratio

Compare Laplacian variance at 640 px vs 160 px. Texture close-ups stay
sharp when downscaled; wide rooms lose high-frequency detail.

**Hypothesis:** Cheap proxy for "large structure vs fine texture" —
test on gold set before combining.

### E — CLIP-style zero-shot prompts (local, product-safe)

Use a **commercially licensed** vision encoder (not pyiqa CLIP-IQA) with
prompt pairs:

- *"a wide interior photograph of a room"* vs *"a close-up of an object"*
- *"a sharp photograph"* vs *"a blurry photograph"*

Score = cosine margin. Benchmark latency and licence before build integration.

### F — MUSIQ as offline trainer / reranker only

Use MUSIQ ranks from `eval_iqa.py` to learn weights on classical features
(linear model on smooth, cbr, quadrant, band, sharpness) that predict
MUSIQ order — deploy the linear model, not pyiqa at runtime.

**Hypothesis:** Capture MUSIQ's ranking without NC licence or 100× cost.

### G — VLM single-frame classify (API, build-time)

One batched call per room: send six classical candidates plus anchors;
ask VLM to pick the best establishing shot with one-sentence reason
(JSON schema). Cache by frame sha256.

**Hypothesis:** Highest accuracy; cost ~9 room calls per build — acceptable
if gated behind confirm (docs/12 plain-language spend).

### H — Human-in-the-loop default

Overview coach mark: *"Tap a room to set its cover photo."* Persist via
`curation.json` override on rank-1 frame; machine pick is merely initial.

**Hypothesis:** Correct covers with zero ML risk; fails "zero-touch brochure"
until user edits.

### I — Dedicated cover frame at capture (future)

Prompt filmer: *"pause 2 s facing each room"*. Detect pauses via optical
flow / low motion windows; prefer those frames for rank 1.

**Hypothesis:** Best long-term; requires capture guidance (docs/12 journey).

## Recommended sequence

```text
1. Revert E2 heuristics (restore E1 or E0 + boundary trim only)
2. Write versioned acceptable/preferred gold tied to a frozen candidate pool
3. Ship eval_hero_cover.py contact sheets
4. Run A (hard gates) + B (narrow pool) — compare on contact sheet
5. If still < pass bar: try C, D, then F (MUSIQ-weight learning)
6. Spike G (VLM rerank); reject if it cannot beat the deterministic baseline
7. Parallel: H for review UX safety net
```

## Open questions

1. **Should rank 1 ever differ from the "best" hero by sharpness?** Product
   says yes (establishing > texture); engineering must enforce minimum
   sharpness floor.
2. **Detector scope expansion** — stairs remain classical until staircase
   detections are reliable on a broader, non-private evaluation set.
3. **Licence-clean learned model** — is a small ONNX mobile-grade IQA
   model worth training on gold + MUSIQ labels?
4. **Rebuild cost** — shipped: `curate-only` CLI (see above) re-runs
   `curate()` + render without describe/detect spend.

## Related files

| Path | Role |
|---|---|
| `homeinventory/cli.py` | `build`, `curate-only`, `render` |
| `homeinventory/ingest.py` | Dense frame pool + boundary trim/anchor |
| `homeinventory/templates/review.html.j2` | `roomHeroSrc()` |
| `homeinventory/report.py` | `prepare_room_sections()` → `cover` |
| `homeinventory/curate.py` | Scoring, MMR, classical + semantic rank-1 promotion |
| `evals/eval_hero_cover.py` | Per-room contact sheets + gold metrics |
| `evals/eval_iqa.py` | Within-room rank benchmark (oracle) |
| `docs/15-curation-and-one-app.md` | Hero set + MMR architecture |
| `docs/17-experience-redesign.md` | Overview gallery UX |

## Definition of done (this doc's feature)

- [x] Historical 93-frame and active 145-frame gold/candidate contracts committed under `evals/fixtures/own-property/`
- [x] `evals/eval_hero_cover.py` produces per-room contact sheets
- [x] E6+E7 active pipeline hits pass bar on compatible dense gold (7/10 preferred, 10/10 acceptable); report-dependent tests refuse or skip incompatible mutable builds with explicit drift diagnosis
- [x] Rank-1 confidence contract: ``cover_status`` on each room plus ``curation.json`` ``cover_status`` map; semantic wrong-room / weak-identity frames surface as ``review_required`` instead of silent ship
- [ ] Overview on own-property build: user eyeball approval — *"I'd show this to a landlord"*
- [x] Documented E4/E8 rejects and E5/E6/E7 adoptions with verdicts and artifacts
- [x] `curate-only` CLI re-runs curation + render without describe/detect cost
- [x] Segment boundary trim (E3) with tests in `tests/test_ingest_segment.py`

E5 + E6 + E7 are **shipped** for rank-1 cover selection. Remaining gate: landlord eyeball on the
overview gallery (review app or `report/inventory.html`).
