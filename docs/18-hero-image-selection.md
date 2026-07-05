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
| Scoring / ranking candidates within a room's frame pool | Keyframe extraction density (`ingest.extract_keyframes`) |
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
| Segments | `segment-spike-multi/gemini-3.5-flash/segments.json` (12 segments, 9 room names after alias merge) |
| Frames | ~93 per-segment keyframes under `report/work/frames/` |
| Manual reference | Pre-M2 per-room clips + `report/inventory.json` from folder capture (10 rooms); use for eyeball gold, not automatic labels |

Rebuild command (reuse cached segments):

```bash
uv run python -m homeinventory.cli build capture-walkthrough -o report \
  --segments-json segment-spike-multi/gemini-3.5-flash/segments.json \
  --progress-file report/build-progress.json
```

Re-curate only (no describe cost):

```python
# reload inventory.json → curate(rooms, work, work) → save → render
```

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
evals/fixtures/own-property/hero-gold.json
```

Suggested schema:

```json
{
  "video": "IMG_5512.MOV",
  "rooms": {
    "Kitchen": {
      "top": ["IMG_5512_f00….jpg", "…"],
      "bottom": ["…"],
      "notes": "Need hob + cabinets visible, not hob surface fill"
    }
  }
}
```

Until gold exists, use ** pairwise eyeball** on contact sheets (below).

### 2. Contact sheet per scorer

New harness: `evals/eval_hero_cover.py`

- Input: build output dir or frame directory + room assignment
- Per room: grid of all frames with overlay: sharpness, each scorer's rank, gold rank if present, **★** on current pick
- Output: `evals/fixtures/own-property/hero-contact-<scorer>.html`
- Sort rooms in walkthrough order

### 3. Metrics (per room, then mean)

| Metric | Definition |
|---|---|
| **top-1 hit** | Gold #1 == scorer #1 |
| **top-3 hit** | Gold #1 in scorer top 3 |
| **ρ (Spearman)** | Rank correlation vs gold (needs ≥5 ranked frames) |
| **blur reject rate** | Fraction of picks where Laplacian < room median |
| **regression vs prior** | Side-by-side HTML of E(n) vs E(n−1) picks |

**Pass bar for adoption:** top-1 hit ≥ 7/9 rooms on IMG_5512 gold (or
unanimous eyeball approval on contact sheet), **and** no room worse than
baseline on pairwise compare.

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

One batched call per room: send top-10 classical candidates as a strip;
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
2. Write hero-gold.json for IMG_5512 (9 rooms × top3/bottom2)
3. Ship eval_hero_cover.py contact sheets
4. Run A (hard gates) + B (narrow pool) — compare on contact sheet
5. If still < pass bar: try C, D, then F (MUSIQ-weight learning)
6. If still stuck: spike G (VLM rerank) with cost disclosure
7. Parallel: H for review UX safety net
```

## Open questions

1. **Should rank 1 ever differ from the "best" hero by sharpness?** Product
   says yes (establishing > texture); engineering must enforce minimum
   sharpness floor.
2. **Loft Office missing from gemini-3.5-flash segments** — merged into
   Loft Bedroom. Accept for benchmark or re-segment with sonnet-5?
3. **Licence-clean learned model** — is a small ONNX mobile-grade IQA
   model worth training on gold + MUSIQ labels?
4. **Rebuild cost** — is a `--curate-only` CLI command worth shipping so
   experiments don't require describe API spend?

## Related files

| Path | Role |
|---|---|
| `homeinventory/curate.py` | Scoring, MMR, rank-1 promotion |
| `homeinventory/ingest.py` | Frame pool + boundary trim |
| `homeinventory/templates/review.html.j2` | `roomHeroSrc()` |
| `homeinventory/report.py` | `prepare_room_sections()` → `cover` |
| `evals/eval_iqa.py` | Within-room rank benchmark (oracle) |
| `docs/15-curation-and-one-app.md` | Hero set + MMR architecture |
| `docs/17-experience-redesign.md` | Overview gallery UX |

## Definition of done (this doc's feature)

- [ ] Gold rankings for IMG_5512 committed under `evals/fixtures/own-property/`
- [ ] `evals/eval_hero_cover.py` produces per-room contact sheets
- [ ] Adopted scorer hits pass bar on gold; regression test locks rank-1 for fixture hashes
- [ ] Overview on own-property build: user eyeball approval — *"I'd show this to a landlord"*
- [ ] Documented experiment ID in this file with date, verdict, and link to artifact

Until then, treat hero cover selection as **research in progress**, not
shipped quality.
