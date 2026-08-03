---
target: current Home Inventory web app design
total_score: 25
p0_count: 0
p1_count: 4
timestamp: 2026-08-01T08-23-27Z
slug: homeinventory-templates
---
Method: dual-agent (A: /root/design_review_fast · B: /root/technical_evidence)

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 3 | Upload rows, build stages, autosave state, and retry paths are present, but the record has no single readiness model spanning capture, review, signatures, and issue. |
| 2 | Match system / real world | 3 | Rooms, claims, photos, and timestamps fit the task; “Full evidence desk” and “Final issue” describe product machinery rather than a landlord’s intent. |
| 3 | User control and freedom | 2 | Undo and correction exist, but essential corrections move the user into a separate specialist surface and the return path is weak. |
| 4 | Consistency and standards | 2 | The shared palette is coherent, but workspace, specialist review, tenant review, and report retain separate navigation and large page-local style systems. |
| 5 | Error prevention | 2 | Evidence states are honest, yet weak footage, incomplete rooms, stale signatures, and issue readiness are not combined into one preventive final check. |
| 6 | Recognition rather than recall | 2 | Users must learn which of Overview, Review, Finish, Full evidence desk, Report, and Final issue owns the action they need. |
| 7 | Flexibility and efficiency | 3 | Search, keyboard review, room-led browsing, and specialist tools are strong; their discoverability and contextual handoff lag behind their capability. |
| 8 | Aesthetic and minimalist design | 3 | The paper/brass documentary identity is restrained and relevant, but repeated kickers, oversized headings, numbered choices, and multiple destinations dilute the focus. |
| 9 | Error recovery | 2 | Some retries and resumable behaviour exist, but the user-facing recovery model for interrupted mobile uploads, weak footage, partial builds, and signing changes is not yet one coherent system. |
| 10 | Help and documentation | 3 | Capture guidance and evidence explanations are contextual, though consequential terms and the simple-to-specialist transition still need plainer help. |
| **Total** |  | **25/40** | **Acceptable — a strong concept with significant journey-level improvements needed.** |

## Anti-Patterns Verdict

**LLM assessment:** Low visual AI slop, moderate product-language slop. The paper/brass palette, Fraunces display type, room imagery, and documentary provenance form a recognisable product identity. The more generic tells are structural: repeated 11px uppercase kickers, numbered choice cards, very large editorial headings, and the familiar Overview / Review / Finish scaffold. The larger problem is not aesthetics but product language: “Full evidence desk,” “Final issue,” and several report destinations expose the internal architecture instead of reflecting the user’s question.

**Deterministic scan:** The direct detector attempt failed because the command’s trailing repository target included a 572 MB TypeScript file, and a target-only scan ignored `.j2` files. An extension-correct temporary scan of the same source produced **181 findings: 19 warnings and 162 advisories**. The dominant signals were 71 literal-colour, 67 radius, and 24 font-size deviations from the shared system. `review.html.j2` contributed 59 findings and `report.html.j2` 45, supporting the qualitative concern that these surfaces still behave as local design systems. It also found five layout-property transitions, five flat-type-hierarchy warnings, and one forbidden side accent at `report.html.j2:256`.

Several findings are false positives or low-value literalism: Fraunces is an intentional product font; “single-font” does not resolve Jinja theme includes; the lightbox image at `review.html.j2:1117` is populated dynamically; and many hard-coded values are deliberate print or media treatments. Even after those are discounted, the scale of token drift is material.

**Visual overlays:** No reliable user-visible overlay is available. Browser discovery returned `No browser is available` and `[]`, so mutation preflight, fresh owner/tenant tabs, console inspection, and overlay injection could not run. This critique is source- and documentation-grounded, not a rendered visual validation.

## Overall Impression

This is no longer a generic admin tool. The evidence-folio direction is credible, calm, and unusually well matched to the trust problem. But the interface still asks the user to understand the implementation: a simple workspace, an advanced evidence desk, a report, a final issue, and a tenant view. The single biggest opportunity is to turn these into one property record with contextual depth, one readiness model, and one authoritative act of issue.

## What’s Working

1. **The product has a real visual point of view.** Paper, brass, restrained serif moments, and dark media inspection support seriousness without becoming legal theatre or cold inspection software.
2. **Evidence is treated as inspectable, not magical.** Claims connect to rooms, photos, video moments, provenance states, and corrections. That is the right foundation for landlord and tenant trust.
3. **The simple and expert capabilities are both substantial.** A room-led default can serve novices, while search, keyboard cadence, annotations, timeline controls, and evidence inspection can serve difficult cases. The design problem is the seam between them, not a lack of capability.

## Priority Issues

### [P1] One record is presented as several products

**Why it matters:** Overview, Review, Finish, Full evidence desk, Report, and Final issue exceed a user’s working-memory budget and create uncertainty at the highest-stakes moment: which version is authoritative?

**Fix:** Make the property record the only top-level destination. Give it three plainly named phases—Capture, Check, Issue—and keep rooms persistent within them. “Report” becomes a preview inside Issue; “Final issue” becomes the result of a single explicit **Issue record** action. The tenant link, signatures, PDF/HTML, and version history all live in that closing phase.

**Suggested command:** `$impeccable shape`

### [P1] Truth-correction is hidden behind an expert-sounding escape hatch

**Why it matters:** Rename room, merge rooms, inspect the cited frame, replace evidence, and annotate a defect are essential whenever the draft is wrong. Calling their home “Full evidence desk” makes a first-time landlord assume they are advanced or optional.

**Fix:** Put **Show source**, **Correct room**, **Change claim**, and **Add close photo** beside the claim that needs them. Open the existing specialist tooling as an in-context inspector that preserves room, item, and scroll position. Let “advanced controls” expand inside that inspector; do not make the user navigate to another product.

**Suggested command:** `$impeccable clarify`

### [P1] Readiness is a collection of counts instead of a confidence-building story

**Why it matters:** A landlord needs to know whether the property is safe to issue, not merely how many items exist. A tenant needs to know what was checked and what changed. The current system exposes several progress indicators but no single answer to “what still needs me?”

**Fix:** Create a property readiness view organised by exceptions, not volume: **3 claims need a decision · 1 room has weak coverage · address missing · tenant not invited**. Every line opens the exact repair. Routine claims stay inspectable without becoming mandatory clerking. At zero, the same component transforms into the closing ceremony and version summary.

**Suggested command:** `$impeccable onboard`

### [P1] The mobile journey needs a first-class failure and recovery design

**Why it matters:** Large video uploads happen in unreliable conditions. Permission denial, backgrounding, unsupported codecs, weak footage, and partial processing are not edge cases; they are the normal emotional valley of the product.

**Fix:** Before paid processing, show a quick local preflight: video length, orientation, audio present, obvious darkness/blur, and resumable upload status. Persist the draft visibly. On return, say exactly what is safe, what remains, and whether the user can continue elsewhere. Recovery actions should be **Resume upload**, **Choose another video**, **Use what uploaded**, or **Add one close photo**—never a generic retry.

**Suggested command:** `$impeccable harden`

### [P2] The visual system is coherent in theory but still drifts in implementation

**Why it matters:** 181 detector findings—especially in review and report—show that local templates can quietly reintroduce density, inconsistent hierarchy, hard-coded colours, and divergent radii. Frequent 11px uppercase text is especially risky for a phone-first product.

**Fix:** Extract semantic tokens for functional text, evidence captions, media controls, report typography, and status treatments. Raise small functional copy to a comfortable mobile size, reserve uppercase/mono for real provenance, remove the report side accent, and transition only transform/opacity/colour. Retire or clearly archive the unrouted legacy start template so it no longer distorts design maintenance.

**Suggested command:** `$impeccable typeset`

## Bold Product Direction

The ambitious version is a **living property record**, not a report builder.

- The home screen is the property itself: one strong room image, a chaptered walkthrough strip, and a short list of decisions that need the user. There is no dashboard of vanity counts.
- Every claim has one universal action: **Show source**. It opens the cited moment, nearby context, edit history, and correction tools without leaving the room.
- Review is exception-first. Confident routine claims remain visible and searchable, while weak, contradictory, missing, or consequential claims form the working queue.
- Issue is a single versioned act. The user sees exactly what will be sent, what changed since the last signature, who has agreed, and what remains disputed. The generated HTML, PDF, tenant link, and retained evidence are outputs of that act, not rival destinations.
- The tenant sees the same rooms and the same evidence order, with neutral actions: **Agree**, **Request a change**, **Add evidence**. A disagreement attaches to a claim, not to a free-floating comment thread.
- Over time, the product can become a property memory: check-in, repair evidence, interim inspection, and check-out compare against the same room history. That is a much larger and more defensible experience than “AI generates an inventory PDF.”

## Persona Red Flags

**First-time landlord:** The report-type choice arrives before the outcome is fully understood. “Full evidence desk” hides essential repair tools, and “Finish / Report / Final issue” makes the legal or practical consequence of each destination unclear.

**Time-pressed mobile user:** A sticky header, bottom action area, long upload, and desktop-only specialist links risk capability loss and viewport crowding. If the browser backgrounds or the connection drops, trust depends entirely on an explicit resumable state.

**Tenant or dispute reviewer:** A polished owner-created document can feel adversarial unless the tenant gets equally direct access to provenance, edits since signature, and a claim-level objection path. The final artefact must make unresolved disagreement visible without weakening or hiding it.

## Minor Observations

- Numbered report-type cards imply a sequence even though the choices are mutually exclusive.
- The unrouted `start.html.j2` and stale documentation can mislead contributors about the current first-run experience.
- The empty `alt` on the dynamically populated evidence lightbox deserves a manual accessibility decision even though the detector’s “broken image” label is wrong.
- Desktop-only links conflict with the stated principle that mobile is a complete field tool.
- Brass must remain an action/provenance accent and never become the sole status signal.
- The 74px prebuild heading and repeated kickers may make a utility flow feel staged; the property and next action should carry more hierarchy than the brand voice.

## Questions to Consider

1. Should the next redesign optimise first for **one unified owner journey**, **mobile upload resilience**, or **tenant/dispute fairness**?
2. For the specialist review tools, should they become an **inline claim inspector**, a **room-level inspection mode**, or remain a **separate desk with much better contextual handoff**?
3. Should the product’s visual tone move toward **quieter documentary utility**, **richer property-led imagery**, or keep the **current evidence-folio balance** while fixing hierarchy only?
