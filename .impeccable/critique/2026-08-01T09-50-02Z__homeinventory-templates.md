---
target: current web app design
total_score: 26
p0_count: 0
p1_count: 5
timestamp: 2026-08-01T09-50-02Z
slug: homeinventory-templates
---
Method: dual-agent (A: design_assessment · B: detector_assessment)

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 3 | Build, save, review and PDF states are strong; mobile hides some persistent status. |
| 2 | Match system / real world | 2 | “Orient,” “Claims,” “Issue,” “register,” “plate” and “seal” require translation. |
| 3 | User control and freedom | 3 | Undo, cancel and back paths exist; custom dialog focus management is incomplete. |
| 4 | Consistency and standards | 3 | The visual system is coherent, but navigation uses three vocabularies. |
| 5 | Error prevention | 3 | Strong rebuild/signing safeguards; tenant completion is only a local room-view marker. |
| 6 | Recognition rather than recall | 2 | Two navigation layers, hidden mobile tools and specialist labels increase recall. |
| 7 | Flexibility and efficiency | 3 | Search, sorting, bulk review, undo and keyboard cadence are excellent. |
| 8 | Aesthetic and minimalist design | 2 | The overview stacks too many modules before the room gallery. |
| 9 | Error recovery | 3 | Retry and preserved edits are good; some errors remain transient toasts. |
| 10 | Help and documentation | 2 | Guidance exists, but specialist decisions lack persistent contextual help. |
| **Total** | | **26/40** | **Acceptable — significant improvement needed.** |

## Anti-Patterns Verdict

The app does not look like generic AI SaaS. It has a coherent paper-and-brass identity and a product-specific evidence inspector. The static Impeccable detector returned zero findings across `homeinventory/templates`.

The risk is a second-order AI tell: the interface avoids generic SaaS by overcommitting to editorial/legal styling. “TDS · credible,” “Inventory register,” numbered room plates, exhibit seals, hashes and a closing ceremony can feel like institutional cosplay. The product should earn authority from inspectable evidence, not announce it through decoration or elevated language.

Browser automation was callable but no browser instance was available, so no reliable viewport screenshots or user-visible overlays exist. Fallback inspection used live HTTP routes and rendered DOM evidence for `/start`, `/`, `/report` and `/issue`, all returning 200.

## Overall Impression

The strongest part is the claim-review workbench: evidence, timestamps, video, zoom, pins, keyboard cadence and undo form a real product advantage. The weakest part is everything around it. The overview tries to be a property map, trust dashboard, sharing hub, provenance ledger and workflow launcher at once. The biggest opportunity is to let property photography and the room sequence carry the experience, while moving procedural controls into the moment they are needed.

## What's Working

1. Evidence is genuinely the interface: claims connect to cited frames, timestamps, playback, zoom and annotations.
2. The review cadence supports both novices and experts through confidence ordering, search, bulk acceptance, autosave and undo.
3. Cross-surface visual coherence has improved: paper surfaces, restrained brass and scoped dark media form a recognisable family.

## Priority Issues

### [P1] The overview is a dossier dashboard

The first screen presents metadata, seals, up to five CTAs, a trust meter, triage, a decision band, a video spine, a property strip and finally the room plates. Users need one answer first: did the app capture the whole property, and what needs attention?

**Fix:** Make the first viewport one photographic property header, one plain completeness sentence, one next action and the room sequence. Put warnings on the affected room. Move previews and phone pairing into Share. Reveal triage after review begins; reveal the spine when the user plays the walkthrough.

**Suggested command:** `$impeccable distill`

### [P1] Seriousness is signalled through legal/editorial theatre

“TDS · credible,” “register,” “plate,” “seal” and “attested” can imply authority beyond the evidence and conflict with the plain-speaking brand.

**Fix:** Recast the interface as a calm contemporary property file. Use ordinary nouns: Property overview, Rooms, Review items, Finish, Final copy. Remove the Roman-date nameplate, plate numbering and decorative SHA seals. Keep hashes and timestamps next to the exact source they verify.

**Suggested command:** `$impeccable clarify`

### [P1] Navigation requires three mental models

The app alternates between New report/Review/Report, Capture/Check/Report/Issue, and Orient/Claims/Rooms/Finalize.

**Fix:** Standardise the whole journey to **New report → Overview → Review items → Finish**. Place Report, tenant handoff and Final copy inside Finish/Share unless persistent global access is proven necessary. Use the same nouns in URLs, headings, buttons and help.

**Suggested command:** `$impeccable shape`

### [P1] Decisive interactions are not fully accessible

The custom lightbox does not reliably take, trap and return focus; queue names omit review status; several phase/filter controls miss the 44px coarse-pointer target; mobile hides the save status.

**Fix:** Use a shared native-dialog-based overlay primitive, add state to accessible queue names, apply a universal interactive-size token, and keep compact save/progress feedback visible on mobile.

**Suggested command:** `$impeccable audit`

### [P1] Tenant completion records navigation, not informed agreement

Room “checked” state is stored locally and is set by reaching a button, not by resolving the room's material claims. It gates countersigning without producing durable evidence of what was agreed or disputed.

**Fix:** End each room with a short summary of defects, comments and missing evidence, then ask “Does this room match your understanding?” with **Agree** or **Add objection**. Persist the decision with the content hash. Before signing, show agreed rooms and unresolved objections.

**Suggested command:** `$impeccable harden`

## Persona Red Flags

**Jordan, first-timer:** specialist labels are unexplained; the room gallery is buried under several status systems; “Preview as landlord” is ambiguous for a landlord; “TDS · credible” may read as endorsement.

**Sam, accessibility-dependent:** lightbox focus can remain behind the overlay; queue rows omit state in accessible names; multiple mobile controls are too small; the mobile header hides save state.

**Casey, distracted mobile user:** the header spans multiple control rows; stacked evidence and claim form force context switching; tenant rooms can require long scrolling before completion; the fixed action area reduces the evidence viewport.

## Minor Observations

- New-tab previews create tab sprawl and weaken the same-task journey.
- Operational labels still use 10–11px type.
- “9 rooms confident” assigns confidence to a room rather than to the cover evidence.
- The start page is strongest when it says “Add property evidence” and “Build the report,” and weakest when it performs institutional authority.

## Questions to Consider

- If every word that tries to signal seriousness disappeared, would the evidence itself still earn trust?
- Is the overview's first job room completeness or claim triage?
- Should tenant countersigning prove pages were visited, or that exceptions were understood and recorded?
- What would the product feel like if property photography, not dossier styling, carried the brand?
