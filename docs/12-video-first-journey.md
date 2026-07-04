# 12 — The video-first journey: plan of record

*4 Jul 2026. Product pivot recorded and committed. This document is the
handoff for the follow-up session: the redesigned end-to-end journey, what
is already done, what remains, and what "good enough" means for each piece.
Predecessors: docs/09 §M5b (guided capture retired), docs/10 (quality bar),
docs/11 (segmentation spike).*

## The pivot, in one paragraph

The folder-per-room, five-subcommand, CLI-first design was rejected by the
product owner: *"for people to do this, it needs to be quick, easy, clear —
otherwise they'll just pay the £165 for peace of mind."* The competition is
not other tools; it is not bothering. Phone guided capture was tried on a
real device and killed. The web app is the product; the CLI is plumbing.

## The journeys

1. **Primary** — walk the property filming one continuous video on a phone
   → open the app → upload the video → a polished report is produced
   (rooms segmented, items drafted, PDF built — all invisible) → review,
   sign, send. No folders, no backend names, no flags.
2. **Secondary** — same, minus upload: open the app and a finished report
   is waiting to review (builds are async; closing the tab loses nothing).
3. **Deep clean** — pick "before & after clean" at creation, upload two
   videos (before/after), and when both are built the comparison sheet
   appears alongside the two reports. Same journey shape for
   check-in/check-out.

## Policy decisions (all recorded 4 Jul 2026)

- **Phone guided capture is dead.** Do not resurrect it (memory + docs/09).
- **Segmentation model: `gemini-3.5-flash` preferred** (owner's call —
  pennies, zero invented rooms; errors are review-repairable);
  `claude-sonnet-5` is the quality alternative. See docs/11.
- **Credentials configured once** in a gitignored `.env`
  (`homeinventory/dotenv.py`); the journey never mentions keys, backends
  or models. Spend confirms become plain language with a rough cost
  estimate, not backend names.
- **Local-first now, hosted login later**: the app runs on the owner's
  machine but must be indistinguishable from a hosted product in the
  browser. Auth/hosting/GDPR is a later milestone with its own policy work.
- **The PDF is produced at build completion**, not behind an export button.
- **Definition of done** stays docs/10's: reachable from the UI,
  product-grade — a wired endpoint with no control is not done.

## Done so far (this session, commits c01e14b → 6a98b77)

- **Guided capture removed**: `capture.py`, its template/tests/subcommand
  and the base64 `/api/photos` route deleted; the streamed `/api/upload`
  (photos + videos to 2 GiB, magic-byte sniffed) is the single upload
  path; its tests absorbed the b64 contract suite. 154 tests green.
- **Segmentation solved** (`homeinventory/segment.py`, docs/11): thumbnail
  strip → VLM boundary pass → contiguous named segments. Six models
  benchmarked on the real own-property walkthrough against the M2 manual
  cut plus frame-level eyeballing; gemini-3.5-flash chosen, sonnet-5 the
  quality alternative. Spike artifacts: `segments.json` + a per-model
  `contact_sheet.html` (strip grouped by room, boundaries flagged).
- **`.env` loading** wired into the segment CLI (and ready for the app).

## To do (ordered), with "good enough" criteria

1. **`segments → rooms` in the pipeline.** A video at the capture root
   triggers segmentation; each segment gets keyframe extraction with a
   frame budget scaled to its duration (today a root video collapses to
   one "General" room capped at 24 frames); segments grouped by room name
   (multi-visit rooms merge); exact cut points replace the `--trim-lead`
   heuristic, making the M2 boundary-bleed fix structural.
   *Good enough:* `build` on a folder containing only IMG_5512.MOV
   produces ≥ the M2 room structure with no hand-made folders, and a
   spot-check of two adjacent rooms shows no cross-room items;
   `--room --from-json` rebuilds still preserve hand edits.
2. **Evaluate gemini-3.5-flash on the core describe task** (owner's
   hypothesis: near-opus quality at a fraction of the price). Run the
   existing harness — build with `--backend openai --model
   gemini-3.5-flash`, score with `python evals/run_eval.py <run>/inventory.json
   evals/fixtures/inventoryflex/labels.json` — and compare against the
   docs/04 backend table (opus: hallucination 2.8%, condition-exact 93%).
   *Good enough:* within a few points of opus on hallucination,
   condition-exact and notable-item recall → it becomes the default
   describe model and the cost story collapses to "pennies, one Google
   key"; materially worse → record the frontier in docs/04 and keep
   claude as quality default. Either way the numbers land in docs/04.
3. **App shell — the upload-first journey.** One entry point; home screen
   is "New report → type (Inventory / Before & after clean) → drop your
   video"; a persistent job model drives staged progress (*uploading →
   watching your video → found 10 rooms → drafting Kitchen 3/10 →
   building your report*), not subprocess stdout; auto-PDF at completion;
   filming guidance (slow pans, name rooms aloud, close-ups of defects)
   lives on the upload screen; segment corrections (rename room, merge
   into neighbour, re-describe) reachable from review; jargon purge.
   *Good enough:* the docs/09-style scripted smoke, driven in a real
   browser: video in → review → signed PDF with no terminal, no folder
   name, no backend name anywhere in the UI; mid-build refresh shows
   progress; process restart after completion shows the finished report.
4. **Deep-clean project flow.** Type picker at creation; two upload slots
   on the existing multi-session machinery (`project.json`, `/s/<key>/`);
   compare runs automatically when the second build lands.
   *Good enough:* the owner's real before/after pair yields the
   comparison sheet without touching the CLI.
5. **First-tester run.** The owner drives both real jobs end-to-end:
   the tenancy video → reviewed, signed PDF; the cleaning pair →
   comparison sheet. Friction log kept; fixes filed before any further
   feature work. *Good enough:* the owner says so.

## Deferred (unchanged decisions)

Hosted login/auth/retention (design the local app so its surfaces
serialise into it), C2PA/e-signature, multi-property management, 1 s
boundary-refinement pass (parked until built schedules show bleed),
capture-time live guidance (dead — docs/05 Level 4).
