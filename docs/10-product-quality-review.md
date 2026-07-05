# 10 — Product-quality review: web app & PDF report flow

*3 Jul 2026. A fresh, adversarial look at the two surfaces docs/03 marked
"done" — the web UI (M5a) and the PDF report flow (M2 polish + M5a export) —
measured against a "feels like Linear, not a toy report builder" bar. Evidence
below comes from the committed own-property artefacts (`report/inventory.pdf`,
74 pp) and from driving the live server (headless-Chrome screenshots at 1440px
and 390px).*

**Verdict.** The bones are genuinely good — the spend-guard confirm contract,
the hash-chained acknowledgement trail, magic-byte upload sniffing, the
keyboard-first review queue. But both surfaces failed the product bar on three
axes: the **evidential chain in the deliverable was broken end-to-end**, the
**web app dead-ended its own core flows**, and the surfaces didn't cohere into
one product. The "done" boxes described wired-up endpoints, not a finished
product. §§1–5 record the findings as found; §6 records the remediation
shipped with this document.

---

## 1. The headline: the PDF's evidence chain was broken

The PDF is the thing a tenant signs and an adjudicator reads. In the actual
74-page own-property PDF:

- **No item cited any photo.** The Photos column was `screen-only`; the
  print condition cell carried no refs. A print reader could not trace
  "2.15 alarm head removed" to any evidence.
- **Appendix B captions were useless.** All ~260 photos were captioned
  `Ref #<room number>` plus the same date — no photo IDs, so images could not
  be tied back to Appendix A's hashes or to the items citing them.
- **Defect-region annotations never printed.** The pins dragged in the review
  app rendered only in screen-only photo strips; the deliverable omitted the
  product's own annotation feature entirely.
- **Appendix A leaked absolute local paths**
  (`/Users/cobro/code/inventory/report/work/frames/…`) into a tenant-facing
  legal document, truncated hashes to 32 chars while the preamble promised
  re-computable checksums, and showed `—` for every capture time.
- **The cover shipped empty states** — "Address not specified",
  "Prepared by —", ISO dates in a UK document — and the product offered no
  way to fix them: address/inspector/tenant/landlord were CLI-only build
  flags.

## 2. Web app: dead ends and missing core flows

- **PDF export had no button.** `/api/pdf` + `/pdf` existed; no template
  referenced them. The M5a "PDF export" milestone was unreachable plumbing.
  It also ran WeasyPrint synchronously in the request thread *holding the
  state lock* (every save blocked), unlike build/redescribe which correctly
  got a job model.
- **No path from review to the report.** The review header offered
  Sign / Save / Save & re-render and nothing else — no `/report` link. You
  could review for an hour and never see the deliverable.
- **No autosave, no undo.** Manual Save button, 8-px dirty dot, beforeunload
  prompt. The *static* report's Level-1 layer had localStorage draft recovery;
  the real app had nothing.
- **Mobile was broken** (390px screenshot): the sticky action bar overlapped
  the Condition select, header buttons clipped off-screen, and
  "space / j / k" keyboard hints rendered on a touchscreen — while the
  add-item form used `capture="environment"`, implying phone use.
- **Long operations showed raw CLI output.** Build/redescribe status = last
  2000 chars of subprocess stdout in mono text. A multi-minute build showed a
  static "building…" string.
- **Upload couldn't take the product's own primary capture format.** M2's
  real run was a walkthrough *video*; the upload contract was JPEG/PNG/HEIC
  only, one file at a time, as base64 JSON (a 64 MiB file → ~85 MB body), no
  drag-and-drop, no per-file progress.
- **Native `prompt()`/`confirm()` dialogs** drove the signing flow — a legal
  attestation via `window.prompt`, twice.

## 3. Product coherence

Three consecutive surfaces had three unrelated design languages: start page
(navy, Segoe), review app (green, Outfit via Google Fonts CDN), report
(Georgia serif, a different navy). Different wordmarks, no shared nav, no
brand. CLI jargon leaked into user-facing copy (`--from-json`,
"backend: claude (claude-opus-4-8)", a toast telling reviewers to
"run: homeinventory render"). A product pitched as "nothing leaves the
machine" loaded fonts from `fonts.googleapis.com`.

## 4. Interaction quality vs the Linear bar

- Evidence photos could not be inspected: ~260-px thumbnails, no lightbox, no
  zoom — and drag-to-annotate as the *only* interaction, so precise defect
  pins were impossible.
- No text search across 289 items; four canned filters; truncated names
  without tooltips.
- Confidence percentages on every queue row: noise pretending to be signal.
- The queue rail did a full `innerHTML` rebuild on every `j`/`k` keystroke.
- Accessibility: clickable `<div>`s, no focus management, no list semantics.

## 5. PDF pipeline robustness

- WeasyPrint was **broken on the dev machine at review time** (libgobject
  dlopen failure) — `/api/pdf` would have 503'd. The committed PDF predates
  the breakage. The suggested fallback (browser print-to-PDF) silently loses
  TOC page numbers and the "Tenant initials" margin boxes (Chrome supports
  neither `target-counter` nor `@page` margin boxes).
- Every Save & re-render re-encoded all 260 photos from scratch (6.4 s
  measured, lock held) — no mtime cache.
- 74 pages / 32 MB for one flat; ~36 pages were near-duplicate video frames
  at 12/page with meaningless captions. Too big to email.
- Reader-facing polish debts: category headers repeated mid-table
  (FIXTURES & FITTINGS three times in one room — grouping was
  contiguous-run; items were never sorted by category); entire condition
  cells rendered in small-caps *including long defect sentences*; TOC page
  numbers existed only for rooms; the HTML view's cover/TOC sat outside
  `<main>` and rendered full-bleed.

---

## 6. Remediation shipped with this review

Six steps, implemented in this change set (details in the diff):

1. **Evidence chain repaired in print.** Appendix B captions now carry photo
   IDs + capture times; every item's print cell cites its evidence photos;
   defect-region overlays render in Appendix B; Appendix A shows
   capture-root-relative paths and full (wrappable) hashes, and names the
   source video for extracted frames. Plus: items sorted by category before
   grouping (one heading per category per room), defects in sentence case
   (small-caps reserved for grades), TOC page numbers for every section,
   cover/TOC moved inside `<main>`, dates formatted "3 July 2026".
2. **Report-details editor + navigation.** A Details modal in the review app
   edits address / prepared-by / agent / landlord / tenant / reference /
   property type; the header links to the HTML report (re-rendered on demand
   when stale) and to PDF export.
3. **One design system.** Shared `_theme.css.j2` + `_ui.js.j2` partials
   (palette, type, buttons, header, modal, toast) across start / review /
   tenant; system font stacks only — the Google Fonts CDN dependency is gone;
   `prompt()`/`confirm()` replaced by real modals; CLI jargon removed from
   user-facing copy.
4. **Autosave + undo + real PDF export.** Edits autosave (debounced) with a
   header save-state indicator; the acknowledgement trail rate-limits
   autosave records (a record when review counts change, else at most one per
   5 minutes). Cmd/Ctrl+Z undoes the last edits (up to 50). PDF export is a
   visible header button backed by a background job (WeasyPrint runs outside
   the state lock) with status polling and an honest 503 + browser-print
   fallback hint when WeasyPrint can't load. `_export_photos` now skips
   unchanged photos by mtime (measured 6.4 s → ~0.2 s warm).
5. **Evidence lightbox.** Click any evidence photo: full-screen viewer with
   wheel/button zoom, drag pan, arrow-key prev/next, and a pin-defect mode
   that hosts the marquee annotation at full resolution (annotation no longer
   fights scrolling on thumbnails).
6. **Mobile + upload.** ≤900 px the queue becomes a slide-over drawer, the
   action bar is a fixed opaque bottom bar, keyboard hints hide on touch
   devices; the start page gains drag-and-drop upload with per-file progress,
   three-way parallelism, and a new streaming binary endpoint
   (`POST /api/upload`) that accepts **videos** (MP4/MOV/MKV/AVI/WebM by
   magic bytes, 2 GiB cap) as well as photos — the base64 `/api/photos`
   contract is unchanged for the phone capture server.

### Explicitly not done here (follow-ups)

*(All five completed 4 Jul 2026 — see §7.)*

- Queue virtualisation (fine at ~300 items; revisit at 1,000+).
- Text search / command palette over items.
- Tenant-page lightbox (view-only) and capture-page theme adoption — the
  capture server is frozen pending the M5b real-device smoke.
- A "final issue" export that strips the review docket from the HTML
  artefact for sending to tenants.
- PDF size budget (image quality tiering, near-duplicate frame pruning in
  Appendix B).

### Milestone bookkeeping

docs/03's M5a box now points here: the original checkbox described endpoint
wiring ("PDF export (`/api/pdf` + `/pdf`)") that no UI reached — worth
remembering as a definition-of-done lesson: **a milestone that ships a route
without a control that reaches it is not done.**

---

## 7. Follow-ups completed (4 Jul 2026)

All five §6 follow-ups shipped in a second change set. Verified end-to-end
by driving the live servers (Playwright/Chromium against the own-property
data, 289 items / 260 photos) plus 12 new unit tests.

1. **Queue virtualisation.** The rail renders in 120-row chunks: first
   paint is constant-size regardless of item count, an IntersectionObserver
   sentinel renders more as the rail scrolls, and any selection (keyboard
   step, search jump) renders up to the selected row first. Measured: 120
   rows in the DOM at load for 289 items; full list only if you actually
   scroll it. Falls back to full render where IntersectionObserver is
   missing.
2. **Text search.** A search field above the queue filters live on
   all-words match over name / id / description / room / defects, and
   composes with the canned filters. `/` or ⌘K focuses it from anywhere
   (opening the drawer on mobile), Enter jumps to the first match, Esc
   clears. The empty state names the query.
3. **Tenant lightbox + capture theme.** A shared view-only viewer
   (`ui.photoViewer`: fit/zoom/pan, arrow-key prev/next, defect-region
   overlays with labels) replaces the tenant page's bare
   `<a target="_blank">` thumbnails. The capture page now uses the shared
   theme partials (`_theme.css.j2` header/buttons/chips) and `ui.toast`
   instead of native `alert()`; found while restyling: the add-room button
   built HTML from the server-echoed room name, so a slash-free name like
   `<img src=x onerror=…>` injected markup (`</b>`-style payloads were
   caught by the path-component check, but a lone open tag was not) — now
   built as text nodes, verified in-browser. **The capture-page change
   invalidates the pending M5b real-device smoke: re-run the docs/09
   checklist on a real phone before flipping that box.**
4. **Final issue.** `render()` now always writes `inventory-issue.html`
   next to the artefact — the same document minus the docket, the embedded
   payload/scripts and the reviewed/unreviewed chips. Rejected entries stay,
   struck through (the preamble's transparency promise). Served at `/issue`
   (stale-aware re-render, like `/report`) and linked from the review
   header nav, per the §6 definition-of-done lesson.
5. **PDF size budget.** Appendix B now embeds a 900-px / q72 print tier
   (`photos/print/`, mtime-cached like the full tier) instead of the
   1400-px / q88 screen exports, and prunes uncited, unannotated
   walkthrough-video frames that are near-duplicates (dHash Hamming ≤ 8) of
   the last kept frame of the same video, with an honest per-room note;
   Appendix A always lists every file. Own-property PDF:
   **32 MB / 74 pp → 9.3 MB / 72 pp** — under mail-attachment caps.
   Honest footnote: the pruner found *zero* safe prunes on the own-property
   data — 245 of 260 frames are cited evidence (never prunable: the printed
   "Evidence: Pnnn" refs must resolve in Appendix B), and the 15 uncited
   frames are genuinely distinct (dHash 12–42). The near-duplicate *pages*
   §5 complained about are cited frames the evidence chain must keep, so
   the size lever was the tier, not the prune; the prune earns its keep on
   raw video captures with default frame extraction.
