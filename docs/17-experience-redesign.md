# 17 — Experience redesign: one journey, grounded at every step

*5 Jul 2026. Deeper UX review of the live app at `http://127.0.0.1:8484/`,
driven against the own-property build (10 rooms, 289 items, 260 frames).
Predecessors: docs/12 (journey plan), docs/14 (design language), docs/15
(curation + one shell), docs/16 (report catalogue). Quality bar stays
docs/10 ("Linear, not toy"). This doc is the product-design handoff for
the next frontend pass — not a bug list, a re-evaluation of what the user
is trying to do and how every surface should serve that.*

---

## The competition is peace of mind

The product owner named the real alternative: *"otherwise they'll just pay
the £165 for peace of mind."* InventoryBase and human clerks sell three
things we must match in the browser:

1. **Comprehensiveness** — "they saw the whole property."
2. **Credibility** — "every claim is backed by evidence I can check."
3. **Closure** — "I signed something complete; I can send it."

Today's app delivers (2) in the evidence room and (3) in the declaration
flow, but **fails (1) at the front door of review**. Opening `/` after a
build lands on item 1 of 289 in the Living Room queue — a microscope with
no map. The report cover lists ten rooms in a contents table, but the
*working* surface never shows that same mental model until you collapse
and expand rail sections one by one.

The fix is not more features. It is **a coherent narrative arc** across
surfaces: orient → verify → repair → finalize → share. Each screen should
answer one question, emphasize one detail, and hand off cleanly to the
next.

---

## Who is doing what

| Actor | Primary goal | Success feeling |
|---|---|---|
| **Owner / clerk** (primary) | Turn one walkthrough video into a signed, sendable inventory | "I checked what mattered; nothing important was missed; the PDF is ready." |
| **Tenant** (secondary) | Walk the rooms, comment, countersign | "I know what I'm agreeing to; my objections are on record." |
| **Deep-clean user** (variant) | Before + after evidence, then comparison | "The clean is documented; any dispute has paired photos." |

Everything below is written for the owner/clerk path first. Tenant and
compare inherit the same principles: **ground before detail**.

---

## The journey we should ship

```text
  CREATE          WAIT              ORIENT           VERIFY           REPAIR           FINALIZE         SHARE
  ──────          ────              ──────           ──────           ──────           ────────         ─────
  pick type   →   build runs   →   room gallery →   item queue   →   room tools   →   details/sign →   issue / tenant
  drop video      staged progress   big picture       cadence          boundaries       checklist        clean copy
  film guide      plain language    comprehensiveness confidence-first coverage         one finish line  PDF
```

**Today:** CREATE and WAIT exist on the start page; VERIFY is the entire
review app; REPAIR is tucked inside room view (reachable only by clicking
a room header in the rail); ORIENT and FINALIZE are fragments (report
cover, Details modal, Sign modal) with no through-line.

**Target:** each phase gets a **named mode** the header reflects. The user
always knows which question they are answering.

---

## Design principles (restated for this pass)

These synthesise docs/14–16 and the product-owner brief
(*elegance, simplicity, comprehensiveness*):

1. **Ground before detail.** Show the whole property (or whole comparison,
   or whole report scope) before asking for item 1. The room gallery is
   the canonical example; the same rule applies to build progress, the
   finish checklist, and the tenant walkthrough.
2. **One primary action per screen.** Each view has a single obvious next
   step. Secondary tools recede. If everything is bold, nothing is.
3. **Comprehensiveness as a number, not a wall** (docs/15). *"10 rooms ·
   289 items · 260 frames analysed · 60 shown"* beats 260 thumbnails.
   Elegance is restraint with depth one click away.
4. **Evidence stays one click deep.** Hero frame → all frames → video at
   timestamp. Never bury the walkthrough spine (docs/14); it is the product's
   signature element and should be visible wherever evidence is judged.
5. **One product, two moods** (docs/14–15). Dark evidence room / warm
   paper document — but **one shell, one nav order, same-tab round-trip**.
   Mood changes; structure does not.
6. **Finish is a phase, not a button.** Details, review completeness,
   PDF readiness, and signature belong in one intentional "close the
   file" flow — not scattered across header chips and modals.
7. **Optimise the cadence, hide the machinery.** j/k/space, confidence
   sort, bulk accept — power tools for the verify phase. Do not show
   keyboard hints on touchscreens (docs/10).

---

## Coherence gaps (structural)

### 1. No orient phase

After build, `/` opens the item queue with `All` filter and sort-by-room.
The user sees `0 of 289 items confirmed` and a single item card. They
have no immediate answer to:

- Did segmentation find every room I said on camera?
- Does each room *look* like my property?
- Where are the defects concentrated?
- How long will review take?

**Room view** (`renderRoom` in `review.html.j2`) already has hero frames,
coverage panel, rename/merge, re-describe — but it is a **hidden mode**
behind a rail header click. It should be the **default landing**, not a
side quest.

### 2. Two review surfaces

The report ships a full **review docket** (j/k/space, progress bar, sign)
while the review app is a separate, richer queue. A user can review in
either place; neither tells them which is canonical. That splits attention
and duplicates the "289 items" problem.

**Resolution:** the report is for **reading and spot-checking**; the review
app is for **working the queue**. Report docket becomes read-only with one
link: *Open in Review*. Keyboard grading stays in the evidence room only.

### 3. Finalize is fragmented

- Address empty on report cover → small link to Details in review header.
- Sign in header opens a modal while 289 items unreviewed — warning is
  good, but there is no **finish checklist**: address ✓, rooms ✓, items ✓,
  PDF ✓, sign.
- Export PDF competes with Sign for header space; both are "done" actions
  with different prerequisites.

**Resolution:** a **Finish** mode (or panel) that sequentialises: complete
details → review progress → export PDF → sign → copy issue link / tenant
URL.

### 4. Start page sells upload, not outcome

The hero copy is strong ("Walk the property once. Leave with evidence.")
but the page shows a drop zone, not **what you get back**: room count,
sample room card, example PDF page, time-to-review estimate. After upload,
"1 walkthrough video ready to build" gives no filename, duration, or
segment preview.

Build progress (`build-progress.json`) is staged on the server; the UI
shows a status string, not a **story**: *Finding rooms → Drafting items →
Writing report → Ready*.

### 5. Navigation vocabulary drifts

| Surface | Nav labels |
|---|---|
| Start (no inventory) | New report |
| Start (has inventory) | New report · Review · Report |
| Review / Report shell | Review · Report · Final issue |
| Review header extras | Details · Export PDF · Sign |

"New report" vs "Review", missing Final issue on start, Details only in
review — small inconsistencies that add cognitive load. One vocabulary:
**New · Review · Report · Issue · Finish** (Finish only when inventory
exists).

### 6. Mobile narrative breaks

At 390px the review header wraps into four nav tabs plus three action
buttons plus progress. The item list becomes a drawer — good — but the
**first screen is still one item**, not a room grid. Report/issue content
 sits in a narrow column with empty margin; the finish docket covers
content. Phone use is plausible (film on phone, review on phone); the
layout should assume it.

---

## Screen-by-screen re-evaluation

Each section: **user intent** → **what must be emphasised** → **what to
change**.

### A. Use-case picker (`/` first visit, `show_picker`)

**Intent:** "Is this the right kind of report for my job?"

**Emphasise:** The fork between tenancy inventory and deep-clean project;
who signs; what deliverables differ.

**Changes:**

- One-line outcome under each card: *"Signed inventory + tenant link"* vs
  *"Before/after reports + comparison sheet"*.
- Do not ask again after choice; show the label as a quiet chip everywhere
  (start, project home, report kicker).
- Optional: "See an example" opens Final issue from a fixture — show
  don't tell.

### B. Start / New report (`/`, `/start`)

**Intent:** "I have a video; make it a report."

**Emphasise:** (1) filming guidance before upload, (2) trust/privacy, (3)
plain-language cost confirm, (4) **preview of the deliverable**.

**Changes:**

- **Upload row:** filename, duration, file size, remove/replace — not
  only a count.
- **Build story:** vertical stepper tied to `BuildProgress` stages; cancel
  only where safe; on completion auto-navigate to **Review → Overview**
  (room gallery), not item 1.
- **Outcome preview:** beside the drop slate, a static mock or last-run
  stats: *"Typical 3-bed: ~8 rooms, ~200 items, ~15 min review."*
- **Rebuild banner:** when inventory exists, primary CTA = *Continue
  review*; rebuild is secondary/destructive with explicit consequence
  copy (already partially there — invert the hierarchy).
- **Filming guide:** keep the numbered list; add optional 15s silent
  loop (local asset) showing slow pan + room name spoken.

### C. Build in progress (overlay or dedicated state)

**Intent:** "Something is happening; I didn't break it."

**Emphasise:** Stage name, elapsed time, rooms found so far (when
available), rough remaining time.

**Changes:**

- Full-viewport **progress card** on the start page — not `#build-status`
  mono text. Stages: *Watching footage → Finding rooms → Extracting
  frames → Drafting items → Rendering report*.
- When segmentation completes, show **room names as chips** before describe
  finishes — early comprehensiveness win.
- Failure: plain sentence + one recovery action (retry / check video /
  contact log path). Never raw subprocess tail (docs/10 finding).

### D. Review — Overview (NEW default landing)

**Intent:** "Did it get the whole property? Where should I look first?"

**Emphasise:** **Comprehensiveness** — the product-owner's missing piece.
Room gallery as the hero; stats bar; sensible next action.

**Proposed layout:**

```text
┌─────────────────────────────────────────────────────────────┐
│  Review · Overview · Items · Rooms · Finish     0/289  [···] │
├─────────────────────────────────────────────────────────────┤
│  10 rooms · 289 items · 260 frames analysed · 60 shown      │
│  Walkthrough: living.mov · 13:42                             │
│  [ Start review (least confident first) ]  [ Watch walkthrough]│
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ [hero]   │ │ [hero]   │ │ [hero]   │ │ [hero]   │  ...  │
│  │ Hallway  │ │ Living   │ │ Kitchen  │ │ Bed 1    │       │
│  │ 30 items │ │ 38 · 3⚠ │ │ 35 items │ │ 28 items │       │
│  │ ████░░   │ │ ██░░░░   │ │ ░░░░░░   │ │ ░░░░░░   │       │
│  └──────────┘ └──────────▘ └──────────┘ └──────────┘       │
│  ⚠ = unreviewed defects or low-confidence cluster           │
└─────────────────────────────────────────────────────────────┘
```

**Interactions:**

- Card click → **Room view** for that room (existing `renderRoom`).
- *Start review* → item queue, sort confidence, filter unreviewed.
- Optional map/list toggle; optional **filmstrip spine** across the full
  walkthrough under the grid (docs/14 signature element at overview scale).
- First visit: one-time coach mark — *"This is every room the walkthrough
  found. Open one to fix names; Start review when it looks right."*

**Implementation note:** mostly composition of existing data (`rooms`,
hero frames, review counts, defect flags) — new route fragment or tab, not
new backend.

### E. Review — Item queue (existing, refined)

**Intent:** "Check each claim against evidence; confirm or fix fast."

**Emphasise:** Current item evidence (stage), confidence when low, confirm/
reject, next item. **De-emphasise:** room admin, bulk tools, keyboard
legend until requested.

**Changes:**

- Default sort: **least confident first** (docs/05 recommendation).
- **Walkthrough spine always visible** under the stage — not inside
  collapsed "Evidence trail". Time is the organising spine (docs/14).
- Reduce letterboxing: cap stage height, `object-fit`, optional side-by-side
  layout on wide screens (media | claim form).
- Rail: show **overview link** at top; room groups collapsed by default
  with progress meters (already partially there).
- *Accept remaining* → confirm dialog with counts by confidence band.
- Search: show `⌘K` / `/` hint in field; filters get **numeric badges**
  (e.g. *Unreviewed 289 · Defects 42 · No evidence 3*).
- Remove duplicate grading UX from report docket (see coherence §2).

### F. Review — Room view (existing, promoted)

**Intent:** "Fix segmentation, scan coverage, add missed items, re-describe."

**Emphasise:** Room name + hero gallery + coverage status + boundary tools.
This is **repair**, not cadence — different primary action (*Back to
overview* / *Review items in this room*).

**Changes:**

- Entry from overview gallery (primary) and rail room header (secondary).
- Breadcrumb: *Overview → Living Room*.
- Coverage panel and rename/merge above the fold; re-describe behind
  confirm at bottom (destructive).
- **Play room chapter** — seek walkthrough to segment start, play through
  segment (segment boundaries already in payload).

### G. Review — Finish (NEW mode)

**Intent:** "Close the file professionally."

**Emphasise:** Checklist, blockers, single path to sign and send.

**Proposed checklist:**

| Step | Blocker if incomplete |
|---|---|
| Property details (address, parties, date) | Cover shows placeholder |
| All rooms named satisfactorily | — (warn only) |
| Items reviewed | Sign warns (existing) |
| PDF generated | Auto at build; re-export if stale |
| Your signature | — |
| Tenant link (optional) | — |

**UI:** Replace scattered Details / Export PDF / Sign header buttons with
one **Finish** entry that opens a panel or `/finish` route. Sign modal
content merges here. Successful sign → highlight *Open Final issue* +
*Copy tenant link*.

### H. Report (`/report`)

**Intent:** "Read what will be sent; spot-check tone and completeness."

**Emphasise:** Document typography (docs/16 catalogue entries), room
scannability, evidence captions. **De-emphasise:** editing chrome.

**Changes:**

- Sticky **contents nav** (room list + scroll spy) for long reports.
- Cover: inline *Add address* if missing (opens Finish/details), not
  passive italic placeholder.
- **Review docket:** read-only progress + *Continue in Review* — remove
  keyboard grading duplicate.
- Item evidence: thumbnail chips, not only `P134, P135` mono lists.
- Header: property address when set (shell already supports this in
  docs/15 M1 — ensure it surfaces).

### I. Final issue (`/issue`)

**Intent:** "Send this to the tenant or adjudicator."

**Emphasise:** Clean document, PDF download, trust (hashes in appendix).
**De-emphasise:** everything interactive except lightbox and PDF.

**Changes:**

- Top bar (localhost only): *Download PDF* primary; subtle *Back to
  editor*.
- One-line sender guidance: *"This copy has no review controls."*
- Block or warn on issue if address still placeholder (configurable —
  draft vs issue).
- Optional: *Copy link* for LAN share (future hosted).

### J. Tenant countersign (`/t/<token>`)

**Intent:** "See what I'm signing; record disagreements."

**Emphasise:** Scope (how many rooms/items), plain-language intro, room
navigation — **not** an infinite scroll of 289 cards.

**Changes:**

- **Room gallery landing** (same component as owner overview, read-only).
- Progress: *"Viewed 4 of 10 rooms · 2 comments"*.
- Per-room walkthrough, then sign bar — not fixed over content on mobile.
- Match owner evidence captions (*seen at 0:48*) for credibility.

### K. Project home (deep-clean)

**Intent:** "Manage before/after sessions."

**Emphasise:** Timeline *Before → After → Compare*; what's done and what's
missing.

**Changes:**

- Horizontal stepper, not two equal cards.
- Session cards show room/item counts when built.
- Compare card auto-scroll + toast when second build completes (docs/12).

### L. Compare sheet (`/compare/`)

**Intent:** "What changed between visits?"

**Emphasise:** Changed items first; classification (wear vs damage);
paired photos.

**Changes:**

- Filter tabs by classification; sticky table header on desktop.
- Mobile: card per changed item, swipe before/after — table is unusable
  on phone.
- Empty/half state: explicit *upload after video* CTA.

---

## Information architecture proposal

### Header modes (inventory exists)

```text
Homeinventory · [address or "Add address"]
Overview | Items | Rooms | Report | Issue | Finish
                              ↑ paper mood from Report onward, same order
```

- **Overview** — room gallery (default `/` or `/review`).
- **Items** — confidence queue (current main pane + rail).
- **Rooms** — list → room view; or merge Overview and Rooms if redundant.
- **Report / Issue** — unchanged routes, unified shell (docs/15 M1).
- **Finish** — checklist panel.

On **start** (no inventory): only *New report* in nav; after build, redirect
to Overview with the expanded nav.

### Default routes

| URL | Default view |
|---|---|
| `/` no inventory | Start |
| `/` inventory, first open | **Overview gallery** |
| `/` inventory, returning | Last mode or Overview if review incomplete |
| `/report` | Read-only document |
| `/issue` | Clean document + PDF |
| `/finish` | Checklist (optional dedicated route) |

### Deep links (preserve docs/15 M1)

- Report item row → `/review#ITEM-ID` (Items mode).
- Overview room card → `/review#room-Kitchen` (Room view).
- Finish address field → same Details form, inlined.

---

## Elegance and simplicity tactics

| Tactic | Application |
|---|---|
| **Progressive disclosure** | Heroes → all frames → video; overview → room → item |
| **Restraint in copy** | One kicker line per screen; remove duplicate stats |
| **Semantic colour** | Brass = navigation/active; green = confirmed; red = defect only |
| **Motion with purpose** | Playhead seeks on item change; gallery fade on room switch |
| **Empty states as guidance** | "No defects flagged" not blank; "Segmentation found 10 rooms" |
| **Kill noise** | Hide confidence % above 80%; hide keyboard hints on touch |
| **Typography hierarchy** | One h1 per view; mono only for refs and timecodes |

---

## What not to do

- **Do not add a dashboard** with charts — this is not analytics.
- **Do not merge report and review into one scroll** — moods differ
  (docs/14).
- **Do not show all 260 frames by default anywhere** — docs/15 curation
  stands.
- **Do not add onboarding tours with five modals** — one coach mark on
  overview, then get out of the way.
- **Do not expose backend/model names** — docs/12 policy.

---

## Milestones

Ordered for incremental delivery; each lands a user-visible phase.

**Status: X1–X6 shipped 5 Jul 2026 (PR #9).** Phase 1 exit is the
first-tester run — [`24-first-tester-runbook.md`](24-first-tester-runbook.md).

### X1 — Orient (highest leverage) ✓

Room gallery overview as default `/` landing; stats bar; Start review CTA;
breadcrumb into existing room view. Done = first open after build answers
"did it get everything?" in one screen.

### X2 — Finish flow ✓

Unified checklist replacing scattered Details / PDF / Sign; address
blocker on cover; post-sign handoff to Issue + tenant link. Done = a new
user can complete details and sign without hunting header buttons.

### X3 — Verify polish ✓

Spine always visible in Items mode; confidence-first default; report
docket read-only; search hint; accept-remaining guard. Done = item review
feels like Linear cadence (docs/14 bar).

### X4 — Start & wait story ✓

Upload metadata row; build stepper with room chips; auto-redirect to
Overview; rebuild hierarchy fix. Done = create phase matches polish of
review phase.

### X5 — Mobile pass ✓

Overview grid 2-col; header collapse; report/issue full-bleed; tenant sign
bar as final step. Done = 390px smoke pass on every route.

### X6 — Secondary journeys ✓

Project stepper; compare filters + mobile cards; tenant overview landing.
Done = deep-clean and share paths get the same orient-first rule.

Definition of done throughout stays docs/10's: reachable from the UI,
product-grade — a component with no default path is not done.

---

## Verification

When X1–X3 land, re-run this script against the own-property build:

1. Fresh browser → drop video → build → **lands on room gallery**, not
   item 1.
2. Gallery shows 10 cards with hero thumbs and item counts; one room opens
   room view; *Start review* opens least-confident item.
3. Confirm 5 items → Overview meters update.
4. Finish checklist blocks sign until address set; after sign, Issue opens
   with address on cover.
5. Report → *Continue in Review* → Overview; back button works (docs/15).
6. 390px: gallery 2-wide; no keyboard hints; Finish reachable.

Capture screenshots at 1440 and 390 for regression alongside docs/10's
method.

---

## Summary

The app already has the hard parts: video spine, curation, catalogue
report, review queue, signatures, tenant share. What it lacks is ** narrative
coherence** — a user dropped into item 1 of 289 cannot feel the
comprehensiveness a £165 clerk sells in the first thirty seconds.

The room gallery overview is the anchor fix: **ground → verify → repair →
finish**. Every other change in this doc hangs off that sequence. Ship X1
first; it transforms the product feel without waiting for a full rewrite.
