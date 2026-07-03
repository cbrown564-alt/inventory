# M5 — Web UI and guided capture

Scope decision recorded in `docs/03` (3 Jul 2026): web UI + mobile guided
capture were requested; C2PA/e-signature and multi-property stay deferred.
This doc covers **M5a (web UI)**; M5b (mobile guided capture) gets its own
section when it lands.

## §M5a — the web UI delta (3 Jul 2026)

Everything evolved inside `review.py`'s stdlib server — no framework, no
npm, no websockets. Review/edit-inline already existed (docs/05 Levels
1–3); M5a added exactly four things:

1. **Start page.** `homeinventory review CAPTURE -o OUT` no longer dies
   with FileNotFoundError when `OUT/inventory.json` is absent. `/` serves a
   start page pre-build (and `/start` always): an empty capture folder gets
   an instruction block (one folder per room, `homeinventory guide`
   pointer); a populated one gets the room list with photo/video counts.
2. **Browser upload.** `POST /api/photos {room, filename, photo_b64}`
   (owner route, loopback-only) writes the bytes **unmodified** into
   `capture/<Room>/`. The stored extension comes from magic-byte sniffing
   only (`FF D8` → `.jpg`, `89 50` → `.png`, ISO-BMFF `ftyp` heic/heif
   brand → `.heic`) — the client's filename extension is never trusted.
   Unsniffable bytes → 400; path separators/`..`/hidden names in room or
   filename → 400; photos over 64 MiB → 413; existing files are never
   clobbered (suffix `-1`, `-2`, …). Upload is transport, not custody
   transfer: the pipeline stays folder-based, and the response returns the
   stored path + sha256 so the sender can verify byte-for-byte identity.
3. **Build from the browser.** `POST /api/build` requires
   `{"confirm": "<backend>"}` matching the server's configured backend —
   the spend guard: no paid backend runs without a request naming it.
   Mismatch/missing → 400; a second build (or a redescribe) while one runs
   → 409. The build is a background subprocess (same pattern as
   redescribe): `python -m homeinventory.cli build CAPTURE -o OUT
   --backend <backend> --no-pdf` plus `--no-detect`/`--model`/`--base-url`
   as the server was configured, plus `--from-json` when an inventory
   already exists (rebuilds keep reviewed/hand-added items). Progress at
   `GET /api/build`, which also reports the exact spawned command. The
   start page names backend+model beside the build button and in the
   confirm dialog.
4. **PDF export.** `POST /api/pdf` re-renders with `render(pdf=True)`;
   `GET /pdf` serves `inventory.pdf` as `application/pdf`. When WeasyPrint
   cannot be imported the endpoint answers **503** with the
   `pip install homeinventory[pdf]` hint — never a silent 200.

### Redescribe spend-guard retrofit (annotation)

The pre-existing `POST /api/redescribe` (docs/05 Level 2) originally ran
the configured backend with no per-request confirmation. M5a retrofits the
identical contract as `/api/build`: the body must carry
`{"room": ..., "confirm": "<backend>"}`; missing or mismatched confirm →
400; concurrent with any build/redescribe → 409. The room panel now names
the backend+model ("Uses backend: …") beside the Re-describe button and in
its confirm dialog. This is a deliberate behaviour change to an existing
endpoint: any script POSTing the old body shape gets a 400 with the new
contract spelled out.

### Verification

`tests/test_review.py` (M5a section): start page both states, sha256
round-trip upload (JPEG + PNG + HEIC-lands-as-`.heic`), unsniffable 400,
six traversal cases 400, no-clobber, 64 MiB 413, £0 build e2e with the
pinned command (server as `homeinventory review CAP -o OUT --backend
offline --no-detect`; spawned build asserted to carry `--backend offline
--no-detect --no-pdf`), confirm-guard 400s, cross 409s, redescribe
retrofit 400s + offline happy path, template assertions (backend+model
beside both controls), `%PDF` byte check (skip-with-reason where
WeasyPrint is not importable — on this machine it needs
`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`), and the monkeypatched
503. Plain `python -m pytest`: 98 passed, 1 skipped (the `%PDF` test);
with the DYLD variable all 31 review tests pass.

### Manual smoke checklist (browser)

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/homeinventory
review <empty-capture-dir> -o <empty-report-dir> --backend offline
--no-detect --no-open`, then open `http://127.0.0.1:8484/`.

| # | Step | Expected observable |
|---|---|---|
| 1 | Open `/` with an empty capture dir and no report | Start page, "No photos yet" empty-state block with the one-folder-per-room instructions; build button with "will run backend: offline (no AI)" beside it |
| 2 | Upload 2 photos into room "Kitchen", 2 more into "Living Room" (Upload section: type room name, pick files, Upload) | Per-file `ok Kitchen/<name>.jpg sha256 …` lines, then the page refreshes showing a room list: Kitchen 2 photos, Living Room 2 photos |
| 3 | Click *Build report* | Browser confirm dialog naming "offline (no AI)"; accept → "building…" status; on completion the page redirects to `/`, now the review app with both rooms |
| 4 | In the review app, edit one item's condition grade inline (review mode dropdown) and Save | Toast "Saved to inventory.json"; reloading `/` shows the changed grade; `inventory.json` on disk carries it |
| 5 | Strike one defect (click its chip) and Save & re-render | Defect shows struck-through, kept as "reviewer rejected" (never silently deleted) in `/report` |
| 6 | Export the PDF (`POST /api/pdf` via the UI/`curl`), then open `/pdf` | 200 with `{"ok": true, "pdf": "/pdf"}`; `/pdf` serves an `application/pdf` document that opens (starts `%PDF`) |

**Execution: PENDING.** This checklist has not yet been executed in a real
browser; the orchestrator will run it via browser automation and commit
the observed-results table separately. Do not treat the table above as an
executed record — it is the script plus expected observables only.
