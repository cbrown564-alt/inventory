# The Review Experience — Design Space

*10 June 2026. Exploration doc: how interactive should this tool be, where,
and at what cost? See Recommendation at the end for the suggested sequence,
and "Implementation status" below it for what got built (Levels 1–3 landed
the same day; Level 4 stays parked).*

## Why review is the stage worth investing in

Two converging arguments:

1. **Legal**: the report's value is *human-attested* evidence. The AI drafts;
   a person confirms and signs. Review is where the product's entire
   evidential weight is created.
2. **Empirical**: in our first real-footage run (04-backend-comparison.md),
   gemini reported a "surface scratch to top right corner" of the TV unit.
   It was a "2021 new" sticker. A human looking at the claim *next to the
   evidence crop* dismisses it in one second. A human re-reading a flat JSON
   file may never check. The UX of review directly determines whether false
   claims survive into signed reports.

Capture should stay dumb and cheap (photos/video into folders). Inference
should stay batch. The interactivity budget belongs at review.

## The interactivity spectrum

### Level 0 — today: edit `inventory.json`, re-render
Works, testable, zero dependencies. Unusable for non-technical users; no
side-by-side evidence; verification friction so high it won't happen for a
200-item property.

### Level 1 — the report *is* the review tool (self-contained interactive HTML)
The HTML report already embeds every photo and item. Add a vanilla-JS layer
(no build chain, no server) so the same file becomes an editor:

- **Review mode toggle**: every grade becomes a dropdown, every defect a
  deletable chip, every item card gets accept / edit / delete.
- **Claim-next-to-evidence**: clicking an item scrolls/zooms its evidence
  photos; clicking a defect highlights the photo it cites. The TV-sticker
  test: one glance, one click to strike the false defect.
- **Review state**: each item carries `reviewed: true/false`; a progress bar
  ("31 of 47 items confirmed") gamifies completeness; unreviewed items are
  visually distinct in any subsequent print/PDF.
- **Export**: "Download reviewed inventory.json" (Blob download) → user drops
  it in the report dir → `homeinventory render` produces the final attested
  report. No server round-trip; works on a phone browser from a file share.

Cost: one template + ~300 lines of JS. Risk: low (degrades to plain report
with JS off). This is the highest leverage-per-effort option on the list.

### Level 2 — local review server (`homeinventory review`)
A `--review` web app served locally (FastAPI or stdlib http.server + the same
Jinja templates). Unlocks what static HTML can't:

- **Write-back without download/move**: edits save straight to
  `inventory.json`; re-render on save.
- **Defect annotation on photos**: draw a box on the photo → stored as a
  region on the defect. Gives adjudicator-grade specificity ("scuff *here*"),
  and becomes the alignment anchor for M3 check-in/check-out comparison.
- **Confidence-sorted review queue**: review the low-confidence items first;
  bulk-accept the rest. Turns 200 items into a 10-minute task.
- **Re-describe this room** button (with `--resume` semantics) after fixing
  capture problems.
- **Add missing item** with camera/file picker (the AI will always miss
  things; adding must be effortless or recall complaints become support
  tickets).

Cost: a real (if small) app; state management; a dependency or two. Still
fully local — no accounts, no hosting, nothing leaves the machine.

### Level 3 — hosted multi-party app
Tenant receives a link, walks the rooms, comments per item ("the carpet stain
was already there"), acknowledges receipt; both parties countersign; the
acknowledgement trail is stored with the manifest. This is the single
highest-value *evidential* feature (mydeposits: an inventory carries maximum
weight when signed by both parties) — but it drags in hosting, auth,
retention policy, and GDPR. M4 territory; design Level 1/2 data structures
(per-item comments, review state, signature blocks) so they serialize
cleanly into whatever this becomes.

### Level 4 — live capture-time AI (explicitly deferred)
Real-time guidance while filming ("you haven't covered the ceiling";
"hold still, that frame was blurry"; live item callouts). Agreed assessment:
**too expensive and error-prone today**:

- Continuous VLM calls during a walkthrough = hundreds of calls per property,
  latency that fights the camera, battery drain.
- On-device models small enough to run live are below the quality bar we
  measured for *batch* 9B models — guidance would be confidently wrong.
- Worst failure mode: the assistant talks the user into worse coverage.

**The cheap middle ground worth keeping**: *post-room coverage feedback*, no
AI in the loop — after a room's photos land, run the local detector (free,
fast) against a per-room expectation list (window, ceiling, radiator, door…)
and flag gaps: "No radiator seen in Bedroom 2 — photograph it or mark N/A."
That's a checklist diff, not a conversation; it can't hallucinate items, only
prompt a second look. Fits CLI (`homeinventory check capture/`) or Level 2 UI
equally well.

## Interaction ideas that apply at any level

| Idea | Why it earns its place |
|---|---|
| Evidence-first item cards (crop thumbnails inline, click → full frame) | The TV-sticker lesson: verification must be one glance, not a file hunt |
| Strike-through rather than delete for rejected AI claims | The report can honestly say "AI suggested, reviewer rejected" — stronger attestation story than silent deletion |
| Confidence-sorted queue + bulk accept | Makes 200-item review tractable; focuses human attention where the model is unsure |
| Keyboard-first flow (j/k next/prev, 1-5 grade, d defect, space accept) | Power users (landlords with portfolios) review at conversation speed |
| Per-item provenance badge (backend + model + reviewed-by) | Auditability; also lets mixed-backend reports be honest about sources |
| "Not tested / not visible" states (from the original assessment PDF) | An honest inventory distinguishes "good" from "couldn't check" |
| Coverage panel: photos that produced no items, items with weak evidence | Surfaces both wasted shots and under-evidenced claims before signing |

## Recommendation

1. **Build Level 1 now-ish** (interactive report): it converts the existing
   artifact into a real review experience for ~a template's worth of work,
   needs no new architecture, and directly addresses the observed
   false-defect failure mode. Design the JSON additions (`reviewed`,
   `rejected`, per-item comments) to be Level 2/3-compatible.
2. **Add the detector-only coverage check** as a cheap CLI command when M1's
   real-property run shows what users actually forget to photograph.
3. **Promote to Level 2** only when Level 1 friction is demonstrated (likely
   trigger: defect-region annotation for M3 comparison).
4. **Keep Level 4 parked** until on-device VLMs clear the quality bar batch
   models set in 04-backend-comparison.md — revisit when the local backend
   eval numbers stop embarrassing the idea.

## Implementation status (10 June 2026)

Levels 1–3 plus the detector-only coverage check are implemented; Level 4
remains parked per the recommendation.

**Shared data model** (`schema.py`). Items carry `reviewed`, `rejected`,
`rejected_defects`, `not_inspected` ("not tested"/"not visible"),
`added_by`, `defect_regions` (normalised photo boxes) and `comments`
(author/role/text/at); the inventory carries `signatures`, each pinning
`Inventory.content_sha256()` — a canonical hash that excludes the signatures
themselves so countersigning doesn't invalidate the first party. Parsing
ignores unknown keys, so older code reads newer files. Rejected claims are
struck through in every surface, never silently deleted — the report says
"AI suggested, reviewer rejected", the stronger attestation story.

**Level 1** — `report.html.j2` now embeds the inventory JSON and a
vanilla-JS "review docket" (zero dependencies, degrades to a plain document
with JS off, hidden in print). Review mode turns grades into dropdowns,
defects into strike/restore chips, names/descriptions inline-editable;
clicking an item opens an evidence drawer with its cited photos (the
TV-sticker test: one glance, one click). Progress bar, j/k/space/x/1–5
keyboard flow, localStorage persistence across accidental closes, signing,
and a Blob download of the reviewed `inventory.json` for
`homeinventory render`. Defect regions render as labelled overlays on the
photographs — including in print.

**Level 2** — `homeinventory review CAPTURE -o REPORT` (`review.py`,
stdlib http.server, no new dependencies; owner routes answer loopback
only). The owner app adds write-back-on-save (plus save-and-re-render),
a confidence-sorted queue with filters and bulk-accept, drag-a-box defect
annotation stored as `defect_regions` (the M3 alignment anchor), a per-room
coverage panel of photos no item cites, add-missed-item with photo upload
(saved into the capture folder, hashed, appended to the manifest), and a
re-describe-room button that shells out to `build --room`.

**Level 3** — enabled by default; mints a token and serves a tenant walk-through at
`/t/<token>`: per-item comments stored on the items (`role: "tenant"`),
acknowledge-and-countersign appending a tenant signature over the content
hash (which now includes their own comments). Every mutation — saves,
comments, signatures, added items — is appended to a hash-chained
`acknowledgements.jsonl`, tamper-evident in the same spirit as the photo
manifest. This is multi-party-on-LAN, not hosting: no accounts, no
retention, the link dies with the process. The data structures (comments,
signature blocks, ack trail) are what an eventual hosted M4 would
serialise.

**Coverage check** — `homeinventory check CAPTURE` runs YOLOE against a
per-room expectation list ("no radiator seen in Bedroom 2 — photograph it
or mark N/A"); exits 1 on gaps so it can gate a build script.

Not yet built: tenant-side photo upload, region annotation in Level 1
(view-only there; drawing is Level 2), and any hosted deployment story.
