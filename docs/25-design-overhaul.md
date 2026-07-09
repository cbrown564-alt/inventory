# 25 — Design overhaul: scope and plan

*8 Jul 2026. A visual-first real-estate product is judged on its first
screen. This doc scopes the design work to make the product look like the
thing a landlord would choose over £165 — not the thing an engineer would
call "functional." Authority: tier 5 (research/scoping) rising to tier 2
on adoption. Feeds docs/00 Pillar 1.*

## The problem, in one paragraph

The start page is light, airy, serif, generous. The review page is dark,
dense, near-black, with 9px type and a 180px-card overview grid. The
report PDF carries a *third*, fully independent palette. A landlord
moves through three unrelated design languages in one product, and the
first window into what the AI produced — the overview — is cramped and
unpolished. For a product whose value is visual trust, this is the core
defect, not a cosmetic one. (Evidence: first-tester screenshot, 8 Jul
2026; template audit below.)

## What the code currently looks like

Findings from a template/CSS audit (8 Jul 2026):

| Surface | Template | Theme | Override CSS |
|---|---|---|---|
| Start / landing | `start.html.j2` | **Light** (paper) | ~174 lines |
| Review / overview | `review.html.j2` (`body.stage`) | **Dark** (stage) | **~770 lines** |
| Report / PDF | `report.html.j2` | **Third palette** (own, no shared theme) | ~460 lines |
| Project, tenant, compare | respective `.html.j2` | Light (paper) | 66–132 lines each |

- The "two worlds" split (paper vs stage) is **intentional**
  (`_theme.css.j2:1-6`) but **half-applied**: `docs/14:68-77` says the
  dark evidence room should cover review *+ tenant + project*, yet tenant
  and project are light in code. The philosophy was never finished.
- `review.html.j2` layers ~770 lines of `body.stage .X` overrides on the
  shared theme — type sizes from 9–11px, a `272px 1fr` fixed grid, near-black
  `#05070b` media surfaces, minimal hover affordance.
- `report.html.j2` does not include `_theme.css.j2` at all; it is a
  separate design system living inside the product.
- Hover behaviour is inconsistent: start cards lift (`translateY(-2px)` +
  shadow); review cards only change border colour.

**Root cause:** a design system that was specified (`docs/14`) but only
partially implemented, then grown with page-local overrides rather than
extended components. The result reads as three products.

## The decision: keep "two worlds," or unify to one?

`docs/14` argues the dark stage is justified — "every serious footage tool
is dark" because dark surrounds improve perceived contrast for evidence
inspection. That argument holds for the **evidence lightbox / player**,
where a landlord is judging a specific frame. It does **not** hold for the
**overview gallery**, which is a navigation/comprehensiveness surface —
exactly where the first-tester screenshot showed the problem.

This scoping recommends:

- **Unify to one light "paper" system** for all navigation, overview, and
  document surfaces (start, review chrome, overview, tenant, project,
  report, PDF).
- **Keep dark only for the media-inspection surface** — the lightbox and
  the "play this moment" video player — where the contrast argument is
  genuine and matches every reference product (Frame.io, etc.).
- This removes the jarring light→dark transition the tester saw, keeps the
  evidential benefit of dark where it earns its place, and ends the
  "third palette" report problem by folding the report into the shared
  system.

This is a reversal of the current `body.stage` default for review. It is
flagged as the key design decision for sign-off in §6.

## Scope of work

### Workstream A — One design system (the foundation)

- **Consolidate `_theme.css.j2` into a real token + component system.**
  Tokens: colour (one paper palette, one dark-for-media), type scale
  (a defined scale, not 9/10/11px ad-hoc), spacing scale, radius,
  elevation/shadow. Components: header/shell, buttons, cards, chips/badges,
  modals, toasts, inputs — each defined once.
- **Fold `report.html.j2` into the shared system.** The report stops being
  a separate design; it uses the paper tokens + serif display type as the
  "document world" expression of the same system.
- **Define the dark media surface** (lightbox, video player) as a scoped
  mode, not a body-wide theme.
- **Output:** a shared component library every surface consumes; no
  page-local `<style>` override blocks larger than page-specific layout.

### Workstream B — Review surface rebuild

The review page is ~770 lines of overrides fighting the theme. Rebuild it
on the new system:

- **Overview gallery** — the trust-critical first screen. Generous cards
  (larger floor than 180px), hero images that breathe, clear room names,
  review-progress affordance. This is where "I'd send this to a landlord"
  is won or lost.
- **Review queue + claim detail** — keep the cadence (j/k/space, least-
  confident first — docs/14 §5) but at a readable type scale with real
  spacing, not 9px density.
- **Evidence stage** — the media region stays dark (scoped), media stays
  largest/brightest, walkthrough spine preserved.
- **Finish flow** — address → sign → issue as a calm, legible sequence.
- **Hover/affordance parity** with the start page: lift, shadow, focus
  states, consistent across cards and buttons.

### Workstream C — Craft pass (docs/14's six principles)

Apply the bar already written but not yet met:

1. Evidence is the interface — media gets the largest region (kept).
2. Every claim links to a moment — timecodes, "seen at 04:12" (kept).
3. Time is the organising spine — walkthrough filmstrip (kept).
4. Inspection means pixels — deep zoom, defect pins (kept).
5. Review is a cadence — keyboard conveyor (kept, de-densified).
6. Evidential gravity — IDs/hashes/timecodes set like exhibit labels.

The principles are largely built; the overhaul is making them *look* like
they're met, not just behave like it.

## What is explicitly out of scope

- **No new frameworks, fonts, or CDNs.** The system-fonts-only,
  stdlib-server, vanilla-JS policy holds (docs/12, docs/14). This is a
  CSS/architecture rebuild, not a stack change.
- **No capture-strategy UX work here.** The start page's capture flow may
  change based on docs/26's outcome; the overhaul designs the *shell and
  system*, not a capture flow that might move.
- **No PDF rendering engine change.** F1 (WeasyPrint on Windows) is a
  docs/00 Pillar 4 item, separate from this design work — though the
  report's *visual* design is in scope (Workstream A).

## Sequencing

```text
Phase 0 — SIGN-OFF on the "one light system + dark media" direction (§6)
Phase 1 — Workstream A: shared system + report folded in
          → every surface on one palette; report no longer third theme
Phase 2 — Workstream B: review surface rebuild on the new system
          → overview gallery first (trust-critical); queue/detail next
Phase 3 — Workstream C: craft pass + accessibility (focus, semantics)
Phase 4 — First-screen trust sign-off against docs/00 Pillar 1
```

Workstream A must land before B — rebuilding the review page on a system
that doesn't exist yet is the mistake that created the current overrides.

## How we know it's done (docs/00 Pillar 1)

- [ ] One shared design system; every surface consumes it; no surface
      defines its own palette.
- [ ] The light→dark jarring transition is gone from the review journey;
      dark survives only in the scoped media-inspection surface.
- [ ] Review overview rebuilt: generous cards, readable type, hero images
      given room, hover/affordance parity with start.
- [ ] Report/PDF uses the shared system (no third palette).
- [ ] **First-screen trust sign-off:** owner looks at a fresh-build
      overview and says *"I'd send this to a landlord"* without
      qualification.

The last checkbox is the gate. Everything else serves it.

## Sign-off and status (8 Jul 2026)

**Phase 0 — SIGNED OFF.** Both open questions resolved:

1. **One light "paper" system + scoped dark media** — *chosen* (the
   recommendation). Not the full dark evidence room.
2. **Serif display + sans UI** — *chosen*, as docs/14 specifies. The
   New York/Iowan display stack carries headings, room names and the
   document title; the sans `--ui` stack carries controls and dense text.

Progress since sign-off:

- **Phase 1 (Workstream A — landed).** `_theme.css.j2` extended with an
  explicit token system — type scale (`--fs-*`, retiring the 9/10/11px
  ad-hoc sizes), spacing (`--sp-*`), radius (`--r-*`) and elevation
  (`--e-1/--e-2`). The header comment now states the one-palette philosophy;
  the dark scope is documented as *media-only*, not a page theme. Shared
  **`.card` / `.badge` / `.chip`** components are now defined once in the
  theme; review consumes the shared `.badge`/`.chip`, report consumes
  `.chip`/`.btn`/`.ui-modal`/`.ui-field`, and start rebases `.card` on the
  shared base — the per-surface duplicates are gone.
- **Report folded into the shared system.** `report.html.j2` now
  `{% include %}`s `_theme.css.j2` and keeps only a thin `:root` alias block
  that sources every colour (`--rule`, `--band`, `--accent`, `--reject`,
  `--pend`, `--serif`, document `--paper`) from the shared palette. All
  screen-chrome hexes retokenised; the "Continue in Review" docket CTA is
  now the shared brass primary. Verified on screen **and** through the
  WeasyPrint PDF path (renders clean; `var()` resolves in print CSS). The
  third palette is gone — docs/00 Pillar 1's "no third theme" is met.
- **Phase 2 (started, trust-critical screen done).** The review page is
  flipped to the light paper system: `body.stage` removed, so chrome, rail,
  claim card, overview, items, rooms and finish all render on paper. The
  media-inspection surfaces (`#stage`, `#lightbox`, `.wt-player`, HUD) stay
  dark via their own local values — the scoped dark island, verified in a
  fresh build. The **overview gallery is rebuilt** to the trust bar:
  generous cards (260px floor, no viewport force-fit), breathing 4:3 hero
  images, a serif document title + room names, light thumb placeholder, and
  hover lift + shadow + image-zoom parity with the start page.

Progress since Ledger commit (9 Jul 2026):

- **Review queue + claim detail de-densified** (Workstream B). Rail widened
  to 300px; queue/claim/finish/nav retokenised onto `--fs-*` / `--sp-*` /
  `--r-*`. Active queue row uses brass-soft fill (no side-stripe). Claim
  title is display serif; warnings and missing-evidence callouts use soft
  fills instead of left borders. Finish checklist is a calm document
  surface with larger type and elevation.
- **Tenant / project / compare audited.** Tenant room gallery matches the
  catalogue-plate grammar; howto/sig cards lose side-stripes; project drop
  zones are light paper (no dark slate); compare intro note uses the soft
  brass callout. Shared `.btn.primary` on tenant countersign.
- **Start picker** wrapped in the same ledger plate as the upload hero.

Remaining (not yet done):

- **First-screen trust sign-off** against docs/00 Pillar 1 (owner looks at
  a fresh-build overview and says *"I'd send this to a landlord"*).
- **Pipeline cover_confident** for product-grade bad-hero honesty (H) —
  interim UI uses `presentation_eligible` / low `quality` today.

Progress since Craft Sprint C1 (9 Jul 2026):

- **A — Overview as a deed.** Masthead with register kicker, address as
  display title, inspection date / room·item counts, SHA seal + confirmed
  meter, staggered plate entrance, single primary "Start review" CTA.
- **C — Exhibit caption system.** Shared `.exhibit` / `.exhibit-seal` in
  `_theme.css.j2`; `exhibitCaption()` used in stage provenance, lightbox,
  and walkthrough bar. Payload now includes `content_sha256`.
- **B — Claim conveyor.** Confirm/reject animates the claim out, advances,
  and offers Undo on the toast.
- **E+F — Evidence expand + ±1s scrub.** Video mode expands the stage
  (`evidence-focus`); HUD gains a ±1s control that seeks around the cited
  moment.
- **G — Finish as closing ceremony.** Finish opens with the same deed
  grammar (address, SHA seal, closing copy) and "Attested and ready"
  handoff.

Progress since Craft Sprint C2 (9 Jul 2026):

- **D — Overview spine.** Room-chaptered walkthrough spine on the overview;
  chapter/scrub seeks the inline player.
- **H — Bad-hero honesty (interim).** Room plates flag weak covers via
  `presentation_eligible === false` or `quality < 0.25`.
- **I — Pin exhibits.** Lightbox and report overlays number pins
  `Ex N · defect`.
- **J — Landlord preview.** Overview CTA + Finish handoff open `/issue`.
- **N / F1 — Browser-print PDF fallback.** `pdf_meta.weasyprint_available`;
  Finish offers Print → Save as PDF via final issue when WeasyPrint is
  missing. F2 continue-review forces `#overview`.

## Related

- North star (Pillar 1): [`00-north-star.md`](00-north-star.md)
- Craft bar / six principles: [`14-frontend-craft.md`](14-frontend-craft.md)
- Experience redesign (X1–X6, shipped): [`17-experience-redesign.md`](17-experience-redesign.md)
- Product plan of record: [`12-video-first-journey.md`](12-video-first-journey.md)
- Capture strategy (coupled start-page question): [`26-capture-strategy-experiment.md`](26-capture-strategy-experiment.md)
