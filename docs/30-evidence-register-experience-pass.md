# 30 — Evidence register experience pass

*12 Jul 2026. Implementation record following the evidence-led report rail in
commits `2566815` and `e176753`.*

## Outcome

The report's strongest interaction is now the product-wide grammar: a claim is
paired with one scannable visual and an honest provenance state — **Close-up**,
**Proposed**, **Context**, or **Missing**. The primary owner workspace remains
exception-first; routine claims become visible and inspectable without turning
the workflow into a mandatory item-by-item clerking exercise.

## Surface changes

- **Capture / workspace:** the active room now includes an image-led claim
  register and coverage summary. Item review no longer labels a room hero as
  direct item evidence.
- **Specialist evidence desk:** the 300px queue is hidden in Overview, Rooms,
  and Finish so those phases use the full canvas. Item review gains lazy-loaded
  close-up/context thumbnails and keyboard-operable queue entries.
- **Tenant / shared review:** repeated evidence strips collapse to one
  conditioned rail image per item; all cited views remain in the lightbox.
  Opening a room no longer marks it complete. A deliberate “Mark checked”
  action advances progress. Signatures count as complete only when their hash
  matches the current record; older signatures remain visible as history.
- **Before / after project:** the After visit is now the current step as soon
  as Before is ready, and session workspaces expose a route back to the project.
- **Comparison:** rationale is adjacent to the mobile change card, the redundant
  photo appendix is removed on mobile, removed/new items no longer disappear,
  and shared links return to the token-scoped review instead of a forbidden
  owner route.
- **Report:** re-rendering keeps an already-exported exhibit when its original
  source path has moved, instead of failing the report route.

The deep-clean role contract was also corrected: the cleaner owns/prepares the
record and the customer is the shared reviewer/countersigner, matching the
existing share-page language.

## Measured impact

| Surface / measure | Before | After |
|---|---:|---:|
| Workspace item evidence rows in active Hallway | 0 | 18 |
| Workspace visually represented Hallway claims | 0 / 18 | 18 / 18 |
| Workspace coverage language | none | 3 close-up · 15 context · 0 missing |
| Specialist Overview width at 1440px | 1140px + competing rail | full 1440px canvas |
| Tenant Hallway visible evidence images | 49 | 18 |
| Tenant Hallway mobile document height | 9,198px | 5,568px (−39.5%) |
| Room progress credited on open | yes | no; explicit completion |
| Stale tenant signature presented as current | 1 observed | 0 |
| Mobile removed/new comparison entries visible | 0 / 4 | 4 / 4 |
| Mobile orphan paired-evidence section | visible | removed |
| Correct current step after Before is built | none | After |

## Verification

- Full suite: **267 passed**, with the same pre-existing fixture failure as the
  baseline (`test_rank1_matches_hero_gold_when_fixture_present`: 2/9 hero-gold
  matches in the mutable `report/` fixture).
- Focused changed-surface checks: **20 passed**, followed by four new contract
  tests passing independently.
- Playwright checks at 1440×900 and 390×844 covered workspace, specialist
  review, tenant gallery, tenant room, report, and comparison.
- Browser console errors: **0** on all successfully loaded surfaces.
- The report route changed from HTTP 500 on the moved-source fixture to a
  successfully rendered report.

## Visual evidence

- `output/playwright/before-workspace-desktop.png`
- `output/playwright/after-workspace-desktop.png`
- `output/playwright/after-workspace-ledger-mobile.png`
- `output/playwright/before-review-desktop.png`
- `output/playwright/after-review-desktop.png`
- `output/playwright/after-tenant-gallery-mobile.png`
- `output/playwright/after-tenant-room-mobile.png`
- `output/playwright/after-compare-mobile.png`
- `output/playwright/after-report-mobile.png`

## Deliberate boundaries

The old `start.html.j2` path remains dead code and should be removed in a
separate cleanup change. The specialist evidence desk remains available for
crop approval, annotations, timeline inspection, and room correction; it does
not compete with the default exception-first workspace. Comparison still uses
its existing desktop index plus evidence appendix; the mobile path is the first
fully integrated ledger and can be used to judge a later desktop consolidation.
