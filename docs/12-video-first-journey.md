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
- **Describe backend: `gemini-3.5-flash` default** via `--backend openai`;
  `claude-opus-4-8` is the expensive backup for complex items (docs/00).
  Tiered routing (gemini draft → opus on hard tail) is Phase 2.
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

## Done (video-first follow-up, Jul 2026)

1. **`segments → rooms` in the pipeline** — `ingest()` segments root
   walkthrough videos (cached `work/segments/<video>.json`), extracts
   time-bounded keyframes with per-segment frame budgets, merges
   multi-visit room names. CLI: `--segment-model`, `--segment-every`,
   `--segments-json`, `--no-segment`, `--progress-file`. 161 tests green.
2. **App shell — upload-first journey** — start page is *New report → type
   → drop walkthrough video* with filming guidance; staged build progress
   via `build-progress.json`; spend confirms use plain language
   (`{"confirm":"yes"}`); auto-PDF at build completion; jargon purged from
   header/copy; segment corrections (rename, merge neighbour) in review.
3. **Deep-clean project flow** — project home has before/after video drop
   slots; compare auto-starts when the second session build lands.
4. **`.env` at app entry** — `load_dotenv()` in CLI and review server.

## Still open

1. **First-tester run** — owner drives real tenancy + cleaning jobs;
   friction log. Blocked on owner time, not code. Success criteria: docs/00.

## Closed since this doc was written

- **gemini-3.5-flash describe eval** — done; recorded in docs/04 (July 2026).
  Gemini is now the **default describe backend**; opus is the expensive backup
  for complex items (docs/00).

## Deferred (unchanged decisions)

Hosted login/auth/retention (design the local app so its surfaces
serialise into it), C2PA/e-signature, multi-property management, 1 s
boundary-refinement pass (parked until built schedules show bleed),
capture-time live guidance (dead — docs/05 Level 4).
