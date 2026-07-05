# 15 — Fewer, better frames; one app

*5 Jul 2026. Product-owner critique of the rebuilt frontend, recorded with
the design that answers it. The brief: the app must communicate three
things — **elegance, simplicity, comprehensiveness** — and today it fails
on two structural counts. Quality bar stays docs/10 ("Linear, not toy");
plan of record stays docs/12; design language stays docs/14. Report visual
redesign is explicitly a follow-up, not this doc.*

## The two flaws

**1. Review and report are two apps wearing one wordmark.** The review
app's only path to the report is a `target="_blank"` link
(`review.html.j2`); the report has *no* link back — its nav is purely
internal anchors. docs/14's "two worlds" (dark evidence room / warm paper
document) was an aesthetic contrast that shipped as a navigational wall.
Once you click Report you have left the product.

**2. Too many images, and blurry ones are guaranteed.** `extract_keyframes`
(`ingest.py`) deliberately keeps the sharpest frame *per time window* —
never rejecting a window outright — so the describe backend gets gap-free
coverage (~6 frames/min, 4–24 per segment). That is correct for the AI and
wrong for the human: "best of a blurry window" frames, and near-identical
views of the same corner, are presented in the report and review as if
they were photographs. Every extracted frame is currently shown.

## The insight: two populations of frames

The frames the AI needs and the frames a human should see are different
populations, and we conflate them. The describe backend wants dense,
coverage-guaranteed frames — **do not touch extraction**. What is missing
is a *curation pass* between ingest and presentation: score every frame,
suppress near-duplicates, elect a small **hero set** per room (3–6). The
rest stays in the manifest as machine evidence behind progressive
disclosure:

> **hero frames** → (disclose) **filmstrip of all frames** → (disclose)
> **the video, seeked to that moment**

One decoupling fixes report clutter, review clutter and the blur problem
at once. "Fewest frames to demonstrate the property in sufficient detail,
all of the highest quality" falls out by default. The walkthrough video —
already routed with Range support — remains the deepest layer everywhere,
one click behind a calm surface.

## The curation pass (new module: `curate.py`)

**Scoring — two tiers, all local (docs/12: nothing leaves the machine).**

- *Cheap gate:* Laplacian variance (already computed at extraction) plus
  exposure-histogram clipping — the fraction of pixels crushed to black or
  blown to white. Blur and bad exposure are the two dominant failure modes
  of hand-held walkthrough frames; neither alone catches the other.
- *Learned tier:* `pyiqa` (IQA-PyTorch), pretrained no-reference quality
  models, pure local PyTorch — torch is already a dependency via the
  YOLOE `detect` extra. First candidates: **MUSIQ** (musiq-koniq) and
  **CLIP-IQA** (zero-shot, prompt-pair "sharp photo / blurry photo", no
  training). Benchmark both on the own-property walkthrough frames against
  eyeballed rankings before committing (same method as docs/11/13);
  check per-model weight licences. New optional extra: `curate`.

**Distinctness — quality filtering alone won't fix redundancy.** "Same
room from slightly different angles" frames can all be sharp. Election is
greedy maximal-marginal-relevance: repeatedly pick the frame maximising
`quality − λ · max_similarity_to_already_selected` until the room budget
is met or marginal gain collapses. Similarity options, cheapest first:
the 160×90 grey thumbnails ingest already makes (free, weak), perceptual
hash (near-dupes only), CLIP image embeddings (semantic — best fit for
"same corner, new angle"; CLIP-IQA already loads a CLIP image encoder, so
scoring and embedding can share one model). Note: the repo's
`mobileclip_blt.ts` is YOLOE's *text* encoder for prompts — it does not
give us image embeddings for free.

**The hard constraint: evidence beats aesthetics.** A frame cited by an
item or defect must never be silently curated away. If a citing frame is
ugly, substitute the nearest high-quality frame at a similar timestamp
where possible; otherwise it simply lives in the disclosed tier — the
hero set stays clean, the evidence stays reachable, nothing is deleted.

**Persistence — the room-aliases lesson.** Rebuilds re-derive everything
from capture + caches, so curation must survive them the same way
review-time renames do (`room-aliases.json`). Scores and hero ranks are
written to `work_dir/curation.json`; reviewer overrides (promote/demote)
are recorded there too and re-applied at ingest. The manifest `Photo`
gains optional `quality: float` and `hero: int` (rank; absent = not a
hero) so templates need no side-lookups.

## One shell, two moods

- A shared slim header on review *and* report: wordmark, property
  address, `Review ⇄ Report` — one Jinja partial, styled per-world (dark
  in the evidence room, paper on the document). Same position, same
  structure; the mood changes, the product doesn't.
- Same-tab navigation (drop `target="_blank"`) so the back button works.
- Deep links both directions: a schedule row in the report links to that
  item in review (`/review#<item-id>`); review already cites "seen at
  04:12" timecodes — report captions get the same affordance, opening the
  player seeked to the moment.

## Presentation, once heroes exist

- **Room cover photo.** The top-ranked hero heads each report room
  section — brochure elegance, rooms scannable at a glance.
- **Heroes by default, everywhere.** Report room strips and the review
  evidence stage show heroes; "all N frames" is a disclosure, the video
  behind that. The PDF appendix keeps the *full* manifest — the audit
  trail is why the visible layer can be ruthless.
- **Comprehensiveness as a number, not a wall.** "142 frames analysed
  across 9 minutes of footage — 23 shown" says thorough better than
  showing 142 images.
- **Item close-up crops.** `Detector.detect()` already takes `crops_dir`:
  the best YOLOE box gives the schedule per-item thumbnails — more detail
  with *fewer* full frames.

## Milestones

- **M1 — one shell.** Shared header partial, same-tab nav, deep links
  both ways. Small, independent, lands first. Done = you can round-trip
  review ⇄ report ⇄ item without the URL bar.
- **M2 — curation core.** `curate.py` (gate + IQA + MMR), scores/ranks in
  `curation.json` + manifest, heroes rendered by default in report rooms
  and review stage with full-set disclosure, evidence-substitution rule.
  Done = both surfaces visibly quieter on the own-property build; no
  cited evidence lost (test).
- **M3 — reviewer control.** Promote/demote in review, persisted through
  rebuilds. Done = a demoted frame stays demoted after `--rebuild`.
- **M4 — item crops.** YOLOE crops in the schedule.
- **Follow-up (own doc):** report visual redesign.

Definition of done throughout stays docs/10's: reachable from the UI,
product-grade — a scoring module with no visible effect is not done.

## Shipped — 5 Jul 2026 (M1 `1b4c4da`, M2 `b7256f8`, M3 `b9b2187`, M4 `2c5ba20`)

All four milestones landed the day this doc was written, verified in a
real browser against the own-property build (playwright round-trip:
shell nav, deep links both ways, moment link playing the walkthrough,
highlight toggle persisting, back button crossing worlds).

- **Curation numbers on the real walkthrough:** 260 frames → 60 heroes
  (6 per room), scored + elected in 3.1 s, pure PIL. The learned IQA
  tier (pyiqa MUSIQ / CLIP-IQA) remains the planned upgrade; the
  classical gate + MMR already removes the blurred/duplicate frames the
  critique named. Quality is stored as a *ratio to the room's best
  frame* — min–max normalisation blew sensor noise into a full 0..1
  spread and drowned the distinctness term (found by test).
- **Override keys are content hashes** (photo sha256, frame-filename
  fallback), so identical bytes share one curation fate and rebuilds,
  renames and photo-id renumbering can't orphan a reviewer's decision.
- **Deliberate photo captures never compete** — only video frames enter
  the election; a person choosing to take a photo is the strongest
  quality signal we have.
- **M4 in practice:** the VLM backends never map items to boxes, so
  `merge.attach_detector_crops` lends items the best-confidence YOLOE
  crop whose label words all appear in the item name, only within the
  item's own cited photos (wrong close-up > no close-up). On the real
  Kitchen: 8 of 35 items picked up genuinely useful close-ups (sink,
  under-cabinet lighting, cabinet spotlights).
- **Leak fixed en route:** the report's embedded payload carried the
  build machine's absolute `crop_path`s; now sanitised like photo paths.
