# M5 — Web UI and guided capture

Scope decision recorded in `docs/03` (3 Jul 2026): web UI + mobile guided
capture were requested; C2PA/e-signature and multi-property stay deferred.
§M5a covers the web UI; §M5b the phone guided-capture server.

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

Related semantic (M5a audit note): `acknowledgements.jsonl` records made
**before the first build** pin an empty `inventory_sha256` — the empty
string means "no inventory existed yet to pin", not a hashing failure;
upload/build acks on a fresh capture are the only records that carry it.

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

### Executed results — 3 Jul 2026, Chromium via Playwright automation

Environment: fresh scratch capture/report dirs; server started exactly as
scripted above; four generated 640×480 JPEGs as test photos.

| # | Observed | Pass |
|---|---|---|
| 1 | Start page rendered: "No photos yet" empty-state block with the one-folder-per-room instructions and `homeinventory guide` pointer; header + build control both show "backend: offline (no AI)" | ✓ |
| 2 | 2 files → Kitchen, 2 → Living Room via room-name + file picker; page refreshed to the room table (Kitchen 2/0, Living Room 2/0); **sha256 of all 4 files on disk byte-identical to the originals**, correct room folders | ✓ |
| 3 | Native `confirm` dialog: "Run a full build with backend offline (no AI)? Paid backends spend API money." — accepted; `GET /api/build` reached `done` with the spawned command carrying `--backend offline --no-pdf --no-detect`; page flipped to the review app. **Caveat:** offline + `--no-detect` yields 0 items by design ("0 items across 2 rooms, 4 photos"), so two items were seeded via the documented `inventory.json` hand-edit path before steps 4–5 | ✓ |
| 4 | LIV-001 condition dropdown fair→good, Save; `inventory.json` on disk carries `"condition": "good"` on reload | ✓ |
| 5 | Struck "wear to seat cushions" chip, Save & re-render; JSON: defect moved to `rejected_defects` (not deleted); re-rendered HTML keeps it visible struck-through with "reviewer rejected" styling | ✓ |
| 6 | `POST /api/pdf` → `{"ok": true, "pdf": "/pdf"}`; `GET /pdf` → 200, `application/pdf`, 226,176 bytes, body starts `%PDF-1.7` | ✓ |

Notes: one benign console error (`favicon.ico` 404) on first load — cosmetic,
no favicon route exists. The step-3 caveat is inherent to the £0 smoke
configuration, not a defect: any detector-enabled or AI-backend build
produces items directly.

## §M5b — phone guided capture (3 Jul 2026)

`homeinventory capture CAPTURE_DIR [--port] [--session KEY] [--use-case …]`
serves one mobile page for walking the property with a phone. Design constraints,
all deliberate:

- **Trust model = the review server's Level 3 `--share`**: binds 0.0.0.0;
  every route — page and API — is gated by a random token minted at
  startup and printed once with the LAN IP
  (`http://<lan-ip>:8485/c/<token>`); wrong token → 403; the link dies
  with the process. There are no ungated pages.
- **No TLS, so no secure-context APIs are load-bearing**: the camera is a
  plain `<input type="file" accept="image/*" capture="environment">` —
  explicitly NOT getUserMedia and NOT a PWA, both of which require a
  secure context a LAN token server cannot honestly provide.
- **Photos only** (per-room shot list): keeps evidence per-item and avoids
  the video-walkthrough problems M2 hit — a 1.3 GB source file and
  keyframe extraction; stills also carry EXIF timestamps directly.
- **One guide, two surfaces**: the shot list lives on each use-case profile
  (`per_room_shots` / `whole_property_shots`); `homeinventory guide
  [--use-case]` prints from it and the phone page renders the same categories.
  A pytest asserts every category label appears on both surfaces for the
  default tenancy profile, and `--use-case deepclean` switches both surfaces
  to the cleaning shot list.
- **`--session KEY`**: optional session subfolder — uploads land in
  `CAPTURE_DIR/<session>/<Room>/` (e.g. `before` / `after` for deep-clean
  workflows). Room scan, creation, and coverage check operate within that
  subfolder only.
- **Same upload contract as M5a, same code**: the magic-byte
  sniff / 64 MiB cap / traversal-400 / never-clobber logic was extracted
  to `homeinventory/webbase.py` and is shared by both servers (review's
  behaviour and tests unchanged). Upload responses additionally carry
  the per-room photo tally for the phone UI.
- **"Live checklist" = shot-list tally + local detector coverage check.**
  Category tick-off is client-side localStorage, per room, on the phone.
  `POST /api/c/<token>/check {room}` runs the free YOLOE pass over that
  room's photos and returns the gaps ("no radiator seen…"); a missing
  detector stack is reported as `unavailable` — never a silent pass.
  Live AI capture guidance stays parked (docs/05 Level 4).

Server-side state lives only under the capture folder; the server writes
nothing anywhere else.

### Verification

`tests/test_capture_server.py`: token gate mirroring the tenant-link test
(page + 4 API routes, plus `/` is 404), room creation + 6 traversal
rejections, guide-on-both-surfaces (tenancy default + `--use-case deepclean`),
`--session` upload path, template hooks
(`capture="environment"`, tick/tally/localStorage, no getUserMedia),
sha256 round-trip upload with per-room tally, HEIC-lands-as-`.heic`,
no-clobber, unsniffable/traversal 400s, 64 MiB 413, progress counts,
coverage check with a monkeypatched detector (real gaps result asserted;
unavailable detector reported as such), and the £0 e2e: uploads into two
rooms (one newly created) then
`build … --backend offline --no-detect --no-pdf` succeeds with both rooms
in `inventory.json`. Suite after M5b: 114 passed, 1 skipped (the M5a
`%PDF` test without the DYLD variable).

### Manual smoke checklist (real device — the user's phone)

On the computer (this machine needs `prompt_free`: the YOLOE CLIP
text-mode is permission-blocked, see docs/07):

```sh
mkdir -p capture-smoke
.venv/bin/homeinventory capture capture-smoke/ --detect-mode prompt_free
```

| # | Step | Expected observable |
|---|---|---|
| 1 | Start the server (command above) | Terminal prints `Phone capture link: http://<lan-ip>:8485/c/<token>` and the anyone-with-the-link warning |
| 2 | On the phone (same Wi-Fi), open the printed URL; then try it once with one token character changed | Capture page renders (header "Homeinventory · Capture", photo total 0); the altered-token request shows a 403 error body |
| 3 | Add room `Kitchen`, then add room `Study` (Add room input) | Both room buttons appear with `(0)` counts; on the computer `capture-smoke/Kitchen/` and `capture-smoke/Study/` folders now exist |
| 4 | Select `Kitchen`; tap *Take / add photos*; capture 2 photos with the rear camera. Repeat for `Study` | Camera opens from the file input; per-photo `ok Kitchen/….jpg (n in this room)` lines; header total and room counts tick up to Kitchen (2), Study (2) |
| 5 | Tick 2–3 shot-list categories for Kitchen, reload the page, reselect Kitchen | Tally shows "n of 7 categories ticked"; ticks survive the reload (localStorage) and are per-room (Study's ticks are independent) |
| 6 | Tap *Check this room* on Kitchen | First run loads the model (seconds), then either `GAP no <item> seen — photograph it or mark N/A` lines or "expected items all covered"; if the detector stack is missing the page must say "detector unavailable … NOT checked" — a pass is never shown silently |
| 7 | On the computer: `ls capture-smoke/Kitchen capture-smoke/Study` | The captured files, extensions matching their actual bytes (iPhone camera uploads commonly land as `.heic` or `.jpg`); byte sizes plausible for camera photos |
| 8 | Offline build with the £0 local detector: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/homeinventory build capture-smoke/ -o report-smoke/ --backend offline --detect-mode prompt_free --no-pdf` | Build succeeds; `report-smoke/inventory.json` has rooms Kitchen and Study with the captured photos and detector-labelled draft items (if YOLOE cannot load, rerun with `--no-detect` and expect the honest "0 items across 2 rooms" instead — that is the documented detector-free result, not a failure) |

Steps were designed against starvation: rooms are created in step 3
before anything needs them, the coverage check runs on a machine-valid
detector mode, and the build step uses the detector-enabled offline path
so items exist to look at (with the detector-free fallback's expected
output stated explicitly).

**Execution: PENDING (requires the user's phone).** Do not treat the
table above as an executed record — it is the script plus expected
observables only; the real-device run and its observed-results table
will be committed separately.
