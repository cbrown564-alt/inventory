# Canonical item ontology — correspondence programme

**Status:** ontology and constrained-generation contract implemented on PR #24. Complete the repository-only programme first. Resume credentialled/local-media work next week.

## Research question

Phase 0 measured only 34.6% exact schedule agreement (37.3% under the product's lexical normaliser) when the same frames were described twice. The working hypothesis is narrower than “make the VLM better”:

> A material share of correspondence noise is caused by asking the model to invent the vocabulary that downstream code must later interpret.

The intervention separates **machine identity** from **report prose**. `item_type` is a bounded canonical concept; `name` and `description` remain natural. Material, colour, mounting and style should not normally create a new identity. Concepts remain separate when confusing them would materially change a tenancy inventory (door vs door handle, bed vs mattress, waste bin vs bread bin).

## Current implementation

`homeinventory/ontology.py` is the registry for `tenancy-items-v1`, with roughly 100 canonical concepts across structure, fixtures, sanitary ware, appliances, furniture, soft furnishings, decor, electronics, kitchenware, safety and meters. `other` is the explicit open-world escape hatch.

`Item` has optional `item_type`, `subtype`, `attributes`, `instance_key` and `ontology_version`. Existing JSON remains readable. Legacy names are canonicalised only where the registry has a safe mapping; unknowns abstain rather than being guessed. When a canonical identity exists it owns the broad category, removing category drift as a second source of instability.

The production model-facing schema now supports the constrained-generation arm: `item_type` is selected from the ontology, report prose remains separate, and the system prompt carries explicit decomposition rules. Independently conditionable concepts must be split (`door` / `door_frame` / `door_handle`, `window` / `window_sill`, `bed` / `mattress`, etc.); stylistic refinements remain subtype/attributes. Legacy and compact cached outputs retain their historical parser semantics.

---

# Work order

The programme is deliberately split into **remote/repository-only work** and **local/credentialled work**. Finish the first block before spending new model tokens or collecting new property evidence.

## Phase R0 — freeze inputs and measurement contract — REMOTE

**Needs:** repository only. No secrets, local media or new inference.

1. Identify the exact frozen Phase-0 T0/R2 repeat records and the cached delta outputs used by the published diagnostics.
2. Record their model, prompt/schema hashes, evidence hashes and exclusions so later comparisons cannot silently change the sample.
3. Preserve the existing exact-name and lexical-normalised metrics as immutable baselines.
4. Version the new canonical scorer separately from the legacy scorer.
5. Add regression tests for scorer behaviour before interpreting any new metric.

**Deliverable:** a manifest plus reproducible command producing the Phase-0 baseline and identifying every included pair.

## Phase R1 — post-hoc canonical correspondence — REMOTE

**Needs:** cached model outputs already committed to the repository.

Run every cached item name through `canonicalize_name` without changing the underlying VLM output. Report, per room and overall:

- canonical multiset agreement;
- canonical membership churn;
- mapping coverage and unknown rate;
- raw-name versus canonical-name agreement;
- quantity disagreement;
- every many-surface-name collapse;
- every unresolved name;
- candidate false merges, especially repeated objects and functionally distinct nouns.

This is the counterfactual representation experiment:

`free-form generation -> canonical ontology -> canonical correspondence`

It isolates how much instability is vocabulary-induced without confounding the result with a new model call.

**Primary decision:** does canonical representation materially improve repeat correspondence while preserving distinctions?

## Phase R2 — adjudicate every residual repeat mismatch — REMOTE

**Needs:** cached outputs and, where committed, their synthetic source evidence/reference metadata. No secrets.

Classify each residual disagreement into one primary cause:

- `model_omission`;
- `ontology_gap`;
- `wrong_canonical_label`;
- `bad_decomposition`;
- `instance_ambiguity`;
- `quantity_disagreement`;
- `visual_ambiguity`;
- `reference_or_scorer_issue`.

Do not treat every unmatched string as hallucination/omission. Record concrete examples and the minimum correction implied by each class.

**Deliverable:** machine-readable adjudication plus a concise failure-analysis report.

## Phase R3 — refine and freeze ontology v1.1 — REMOTE

**Needs:** R1/R2 results only.

Change the ontology only in response to observed failures. For each proposed change record whether it is:

- alias addition;
- canonical merge;
- canonical split;
- subtype/attribute migration;
- decomposition-rule clarification;
- explicit decision to leave a concept open-world.

Pay particular attention to doors/windows and components, fitted cabinetry, lighting, floor coverings, bathroom components and repeated furniture.

Re-run R1 after every ontology revision. Reject revisions that improve agreement by collapsing materially different concepts.

**Deliverable:** frozen `tenancy-items-v1.1` (or a documented decision that v1 needs no revision), migration notes and updated tests.

## Phase R4 — ontology-first correspondence implementation — REMOTE

**Needs:** accepted ontology from R3.

Change comparison correspondence so canonical inventories prefer:

`room -> item_type -> instance_key / quantity -> supporting attributes/evidence`

The existing lexical matcher remains a compatibility fallback for legacy or unresolved items; it is no longer the primary identity mechanism for canonical records.

Required tests include:

- canonical synonyms match without lexical heuristics;
- materially distinct concepts never match merely because prose overlaps;
- repeated grouped items respect quantity;
- repeated independently tracked items use `instance_key`;
- missing/unknown canonical identity falls back safely;
- mixed legacy/canonical inventories remain comparable.

**Deliverable:** ontology-first `compare.py` with regression coverage, without deleting the fallback yet.

## Phase R5 — counterfactual delta re-score — REMOTE

**Needs:** existing cached 27 delta-pair outputs. No new inference.

Apply the accepted ontology/correspondence layer to the same cached before/after descriptions and compare with the current diagnostics. Report:

- false additions;
- false removals;
- true item-added recall;
- true item-removed recall;
- condition-change recall;
- cleanliness-change recall;
- new-defect recall where the existing evidence permits it;
- total reported false changes;
- false merges that suppress genuine change;
- proportion of the old false-change burden attributable specifically to vocabulary/correspondence.

This is not evidence for constrained generation; it measures how much downstream noise can be removed from the outputs we already possess.

**Primary decision:** does canonical identity materially reduce the previously recorded false-change problem without hiding real additions/removals?

## Phase R6 — instance-key design — REMOTE

**Needs:** failure cases from R2/R5.

Canonical type alone cannot distinguish two bedside lamps, multiple doors or other repeated independently conditionable objects. Define a deliberately bounded instance policy:

1. prefer `quantity` for genuinely interchangeable grouped items;
2. require instance-level records only when objects need independent condition/change tracking;
3. prefer stable room-relative discriminators over arbitrary numbering;
4. do not allow unconstrained prose in `instance_key` to become a second hidden identity system;
5. abstain when the evidence cannot reliably distinguish instances.

Evaluate whether a small controlled discriminator vocabulary (`left_of_bed`, `right_of_bed`, `entrance`, `internal`, etc.) is sufficient before expanding it.

**Deliverable:** instance correspondence specification, schema constraints and tests. Do not yet claim cross-session visual re-identification.

## Phase R7 — design the finding/defect ontology — REMOTE

**Needs:** existing prompts, defect outputs and failure analysis. Implementation can be deferred until item identity evidence is strong.

The current prompt already elicits structured concepts and then collapses them into `list[str]`. Design a future finding representation such as:

- `finding_type` (`scuff`, `scratch`, `chip`, `crack`, `stain`, `dent`, `wear`, `discolouration`, `limescale`, `dirt`, `mould`, `loose`, `missing`, `broken`, `burn`, `hole`, `water_mark`, `other`);
- severity where visually supportable;
- component/feature;
- bounded vertical/side location;
- evidence photo/region references;
- optional human-readable note.

Keep this as a separate ontology from item identity. Do not let finding work delay the item-correspondence decision.

**Deliverable:** proposal + migration/experiment plan, optionally schema scaffolding behind an experiment boundary.

## Phase R8 — remote checkpoint and hand-off — REMOTE

Before local work resumes, produce one short checkpoint containing:

- baseline versus post-hoc canonical repeat metrics;
- residual mismatch taxonomy;
- accepted ontology version and change log;
- baseline versus ontology-first cached delta metrics;
- known limitations that only new inference can answer;
- exact commands/configuration for the local experiment;
- required secrets/models/media checklist.

At this point remote work should stop rather than expanding the ontology speculatively.

---

# Next week: local / credentialled thread

These phases require API/CLI credentials, uncommitted source media, physical capture, or some combination. Secrets must remain outside the repository.

## Phase L1 — constrained-generation repeat experiment — LOCAL / CREDENTIALLED

**Needs:** authorised Gemini/OpenRouter/Anthropic (or other selected backend) access and the frozen repeat images if they are not fully available in the working checkout.

Compare three representations on identical evidence:

- **A — Phase-0 baseline:** free-form generation + existing lexical correspondence;
- **B — counterfactual:** cached free-form generation + accepted post-hoc ontology;
- **C — intervention:** ontology-constrained generation + canonical correspondence.

For C, preserve the accepted evidence set, model family/version, decoding controls and preprocessing wherever the provider permits. Record new prompt/schema hashes and run fingerprints; do not overwrite baseline records.

Measure:

- canonical item agreement;
- canonical precision/recall against intended concepts where references permit;
- intended-item/raw visual coverage;
- `other` rate;
- invalid identity/category combinations;
- quantity agreement;
- instance collisions;
- condition and cleanliness agreement after canonical correspondence;
- output/token/cost differences.

**Primary decision:** does constraining decomposition improve stability/coverage beyond what post-hoc canonicalisation alone achieves?

## Phase L2 — constrained-generation delta experiment — LOCAL / CREDENTIALLED

**Needs:** same authorised model environment plus frozen delta images.

Rerun the accepted delta sample using the constrained contract and ontology-first correspondence. Compare against both the original Phase-0 result and the R5 counterfactual re-score.

This separates:

1. benefit from a better representation/matcher; from
2. benefit from changing how the VLM decomposes the scene.

Measure genuine additions/removals, false additions/removals, condition/cleanliness changes, defect changes, false merges and unresolved correspondence.

## Phase L3 — native-resolution real-property validation — LOCAL DATA + CREDENTIALS

**Needs:** original high-resolution property photographs/video that are intentionally not committed, model credentials, and an independently reviewed reference.

Track each material finding through the pipeline:

`visible in original -> survives preprocessing/evidence selection -> extracted -> correctly represented -> correctly compared`

Keep native-photo component results distinct from end-to-end walkthrough results. The existing bounded gate (at least two properties, 100 notable facts and 20 visible defects) remains a pilot threshold, not evidence of broad generalisation.

## Phase L4 — capture-strategy experiment — PHYSICAL / LOCAL

**Needs:** access to a property and new capture.

Complete the planned capture arms (ordinary video, narrated video, light photography, heavier photography as retained by the current experiment plan). Measure untouched automated output separately from human repair burden and test finalists on a contrasting second property.

The product decision is based on total capture + processing + review effort while preserving material findings, not model accuracy in isolation.

## Phase L5 — selective verification / omission search — LOCAL / CREDENTIALLED

Only after identity/decomposition is stable, test separately:

- verification of emitted claims;
- search for omitted material items/findings;
- selective release/abstention;
- targeted whole-image versus detail-crop inspection.

Do not conflate these into one multi-agent architecture. Each stage needs an independently measurable purpose.

---

# Acceptance criteria

Do not adopt the ontology merely because agreement rises. Adoption requires all of the following:

1. canonical agreement materially exceeds the 37.3% current normalised baseline;
2. membership churn falls without a material fall in intended-item coverage;
3. human audit finds no systematic collapsing of materially different concepts;
4. `other`/unknown remains low enough for useful coverage while preserving an honest open-world escape;
5. on delta pairs, false additions/removals fall while true addition/removal recall does not regress materially;
6. repeated-instance handling does not manufacture correspondence where the evidence cannot support it.

A provisional useful-effect threshold remains **+20 percentage points canonical agreement** on the repeat control and **>=30% reduction in membership churn**, with intended-item coverage no more than 2 percentage points below baseline. These are engineering decision thresholds, not statistical-significance claims.

# What this programme does not solve

Canonical identity cannot recover an item omitted by both descriptions, make a small defect visible, establish that a defect is real, or prove that two visually similar repeated objects are the same physical instance. Those remain coverage, evidence and instance-correspondence problems. The ontology succeeds if it removes vocabulary/decomposition-induced noise without concealing those harder failures.

# Cleanup only after acceptance

Once R5 + L1/L2 establish that canonical identity is the preferred path:

1. generate detector query aliases from the ontology registry and retire duplicated synonym tables gradually;
2. remove descriptor/head-noun/special-case lexical machinery that is demonstrably superseded, while retaining an explicit legacy adapter;
3. version ontology migrations and persist the version on every canonical item;
4. move typed findings into production only after their own evaluation;
5. consolidate experiment documentation so historical Phase-0 behaviour is not confused with the current product contract.
