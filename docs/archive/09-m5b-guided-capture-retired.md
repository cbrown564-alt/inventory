# Archived — phone guided capture (M5b)

*Status: archived · Retired 4 Jul 2026 · Superseded by
[`../12-video-first-journey.md`](../12-video-first-journey.md)*

The real-device test happened and the user's verdict was that the
guided-capture experience was bad enough to kill the feature: the primary
capture path is now **one walkthrough video uploaded in the browser**, with
room segmentation handled by the pipeline. `capture.py`, its template, tests,
the `capture` subcommand and the base64 `/api/photos` route were deleted;
the streamed `/api/upload` contract (webbase.py) is the single upload path.

---

## §M5b — phone guided capture (3 Jul 2026)

`homeinventory capture CAPTURE_DIR [--port]` served one mobile page for
walking the property with a phone. Design constraints, all deliberate:

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
- **One guide, two surfaces**: the shot list lives as structured data in
  `homeinventory/guide.py`; `homeinventory guide` prints from it
  (stdout byte-identical to the previous hardcoded string) and the phone
  page renders the same categories. A pytest asserts every category
  label appears on both surfaces.
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
rejections, guide-on-both-surfaces, template hooks
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

*Note (4 Jul 2026): the capture page was restyled onto the shared theme
(docs/10 §7) — same IDs, routes and upload contract, but error messages are
now toasts rather than native `alert()` dialogs.*

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
| 8 | Offline build with the £0 local detector: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/homeinventory build capture-smoke/ -o report-smoke/ --backend offline --detect-mode prompt_free --no-pdf` | Build succeeds; `report-smoke/inventory.json` has rooms Kitchen and Study with the captured photos and detector-labelled draft items |

**Execution: PENDING (requires the user's phone).** The feature was killed
before this checklist was executed; it is kept as the record of what was
built and why it was removed.
