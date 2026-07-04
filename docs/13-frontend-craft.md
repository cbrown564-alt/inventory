# 13 — Frontend craft: what great looks like for video-evidence review

*4 Jul 2026. Research pass before the frontend rebuild. The brief: the
frontend experience is poor and needs radical upgrades; this is a deeply
visual task — video evidence, annotated stills, poring over minor details
in scenes — and the UI should leverage that, not fight it. Quality bar
stays docs/10 ("Linear, not toy"). Plan of record stays docs/12.*

## The barometer — top-tier implementations studied

**Frame.io (Adobe) — footage review.** The industry reference for
reviewing video with other people. What it gets right: the media is the
biggest, brightest thing on a dark stage; every comment is *timecoded* and
appears as a bubble on the scrubber; clicking a comment seeks the player
to that exact frame; annotations (boxes, arrows) live on frames and appear
when their comment is selected; ranges are set with I/O keys like an NLE.
Feedback and footage are one surface, joined by time.

**Encord / CVAT / Labelbox — frame-accurate annotation.** Tools whose
whole economics depend on reviewer throughput. Frame-by-frame navigation,
persistent object identity across frames, timeline scrubbing with dense
keyboard control, and review queues ordered by uncertainty. The lesson:
when a human must judge hundreds of small claims, the tool optimises for
*cadence* — one claim, one glance at evidence, one keystroke.

**YouTube / Netflix / Mux — player craft.** Chapters on the scrub bar,
filmstrip hover-previews (storyboard sprites), auto-hiding controls,
double-tap seeks, keyboard everywhere. The lesson for us is chapters:
a walkthrough video is *naturally chaptered by room*, and we already
compute those boundaries.

**InventoryBase — the direct competitor.** The incumbent's reports now
embed HD video with thumbnails playable from the PDF/share link, plus an
interactive gallery and tenant commenting with photo upload. The £165
human product already treats video as first-class evidence; a video-first
product that reduces its own video to static JPEGs is behind the thing it
wants to replace.

**Linear — product feel (docs/10's bar).** Keyboard-first queue, quiet
chrome, instant feedback, nothing that looks like a wireframe.

## What makes a great UX for *this* task — six principles

1. **The evidence is the interface.** The reviewer's job is looking.
   Media gets the largest, brightest region of the screen on a dark
   stage (dark surrounds improve perceived contrast — every serious
   footage tool is dark for this reason). Chrome recedes; pixels win.
2. **Every claim links to a moment.** Items cite keyframes; keyframes
   encode their frame index; frame index ÷ fps = a timestamp in the
   walkthrough. A claim you can *play* is more credible than a claim you
   can only read. Trust comes from traceability — show "seen at 04:12".
3. **Time is the organising spine.** The walk through the property is the
   native order of the evidence. Room segments are chapters; keyframes
   are ticks; defects are markers. One filmstrip timeline ties the whole
   inventory to the footage that proves it.
4. **Inspection means pixels.** Zoom must be deep and instant; defect
   pins live on the image; and when a still is ambiguous, the fix is to
   scrub the footage around that moment — the next half-second often
   shows the corner the keyframe missed.
5. **Review is a cadence, not a form.** j/k/space/1–5 conveyor, least
   confident first, progress always visible, undo everywhere. (Largely
   built already — keep it, make it feel precise.)
6. **Evidential gravity.** This document may be exhibits in a deposit
   dispute. IDs, timecodes, hashes and provenance are set like exhibit
   labels — tabular, monospace, quietly serious. The report reads as a
   legal document; the app reads as the evidence room behind it.

## The design language (two worlds, one product)

- **The evidence room (review, tenant, project):** deep blue-charcoal
  stage, media glowing, brass identity accent (playhead, wordmark,
  active states), semantic confirm-green / reject-red, neutral slate for
  "unreviewed". Type: Avenir Next / Segoe UI for UI, monospace timecodes.
- **The document (start page, report, PDF):** warm paper, serif display
  (New York/Iowan/Charter/Georgia stack), hairline rules, exhibit-style
  figure captions. You enter the dark room to inspect; you leave with a
  paper document.
- **The signature element: the walkthrough spine.** A room-chaptered
  filmstrip timeline of the actual footage, present wherever evidence is
  judged. Selecting an item slides the brass playhead to the moment the
  camera saw it; pressing play shows the room moving around that frame.
- No external fonts, no CDNs, no frameworks — nothing leaves the machine
  (docs/12 policy). System faces only, stdlib server, vanilla JS.

## What this unlocked in implementation

- `/video/<name>` route with HTTP Range support (seekable `<video>`).
- Payload gains `videos` (src, fps, duration, room segments) and
  `photo_time` (photo id → timestamp in its source video), derived from
  the frame-index filenames that ingest already writes.
- Review: evidence stage + filmstrip + "play this moment"; lightbox and
  report keep parity ("seen at 04:12 · Kitchen" exhibit captions).

Sources: Frame.io V4 docs & release notes (help.frame.io,
blog.frame.io), Encord/CVAT video-annotation guides, Mux timeline
hover-preview guide, Eleken video-player UI patterns, InventoryBase
HD-video release notes (inventorybase.co.uk).
