# Canonical generation correspondence experiment

**Status:** implementation-ready experimental arm on `feat/canonical-item-ontology`.

## Question

Does moving canonical identity and decomposition into the model's structured-output contract reduce repeat-description membership churn and downstream false changes, without hiding genuine additions/removals or forcing unknown objects into wrong classes?

This is deliberately separate from the production `describe.py` contract until the intervention passes the gates below.

## Hypothesis

The current system asks the VLM to invent a natural-language item name, then reconstructs identity from that prose. Existing repeat runs show two distinct instability modes:

1. **Vocabulary drift** — e.g. pedestal basin vs wash basin; cooker hood vs extractor hood; recessed spotlight vs ceiling spotlight.
2. **Decomposition drift** — e.g. `window and sill` vs separate window/sill records; `door and handle` vs separate records; patio doors and windows combined in one record.

Post-hoc aliases can address (1), but cannot reliably recover (2). The constrained arm therefore makes `item_type` mandatory and gives explicit split/group rules.

## Frozen intervention

Use `homeinventory.canonical_contract`:

- ontology: `tenancy-items-v1`;
- strict `item_type` enum from `homeinventory.ontology.ITEM_TYPE_KEYS`;
- free `display_name` retained for report prose;
- optional `subtype`, `attributes`, and `instance_key` carry non-identity detail;
- explicit decomposition rules prevent combining independently conditionable concepts;
- `other` remains an open-world escape hatch.

Do **not** change image evidence, model, effort, temperature, defect instructions, grading labels, cleanliness labels, value bands, or photo-ID instructions between baseline and constrained arms.

## Arms

### A. Frozen baseline

Existing `production-v1` T0 and repeat R2 outputs. No new model calls are required.

### B. Post-hoc ontology

Apply the conservative legacy-name mapper to A. Unknown/ambiguous names abstain. This estimates how much churn is merely vocabulary drift.

### C. Constrained generation

Re-run the exact T0 evidence and exact repeat evidence using the same model/settings as A, replacing only the response schema and adding `DECOMPOSITION_RULES`. The model must emit `item_type` directly.

Run the full frozen repeat set. Do not cherry-pick rooms where the ontology appears favourable.

### D. Delta transfer

Only if C passes the repeat gates, run the corresponding frozen T0/T1 delta set under the constrained contract. Score genuine additions/removals and false additions/removals separately.

## Primary metrics

For every same-evidence T0/R2 pair report:

- raw display-name agreement (diagnostic only);
- canonical membership precision/recall/F1 in each direction;
- symmetric canonical membership agreement;
- unmatched canonical identities per run;
- unknown/`other` rate;
- decomposition violations;
- repeated-type ambiguity rate (same `item_type` with no usable `instance_key` where independent tracking is required).

Aggregate both micro and macro-by-room. Preserve room-level rows so gains cannot be driven by one easy room type.

## Safety / anti-collapse metrics

A stable but over-collapsed inventory is a failure. Manually adjudicate every newly matched pair that was unmatched under the baseline matcher and classify it as:

- correct canonical collapse;
- incorrect semantic collapse;
- component collapse (e.g. door vs handle);
- repeated-instance collapse;
- ambiguous.

Report the denominator and examples. Do not call unmatched names hallucinations without source adjudication.

## Delta metrics

On D report:

- true item-addition recall;
- true item-removal recall;
- false item additions;
- false item removals;
- condition-change recall among correctly corresponding entities;
- defect-change recall among correctly corresponding entities;
- `insufficiently comparable` / unresolved correspondence count where applicable.

The ontology intervention must not receive credit for suppressing a genuine addition/removal by collapsing two materially different concepts.

## Acceptance gates

Proceed toward production integration only if all are true:

1. canonical same-evidence membership agreement materially exceeds the frozen baseline and post-hoc arm;
2. manual audit finds no systematic component or repeated-instance collapse;
3. `other`/unknown remains low enough that the ontology is actually covering the task, with all misses enumerated for ontology revision;
4. genuine addition/removal recall on D is not worse than baseline beyond ordinary run variation;
5. false additions/removals fall materially on D;
6. output remains valid under the strict schema without a material rise in failed/truncated calls.

Do not set a retrospective numeric threshold after seeing results. Before running C, record the exact minimum improvement considered product-relevant and the maximum tolerated collapse/error rate in the run manifest.

## Run identity

Every C/D record must persist:

- ontology version;
- ontology file SHA;
- canonical-contract file SHA;
- response-schema SHA;
- decomposition-rules SHA;
- model/provider/effort/sampling settings;
- ordered evidence hashes;
- base production prompt SHA.

This prevents an ontology edit or prompt tweak being silently mixed into the same experimental arm.

## Analysis order

1. Validate every output structurally with `validate_decomposition`.
2. Score baseline A unchanged.
3. Score B without model calls.
4. Score C on same-evidence repeats.
5. Audit every B/C newly created correspondence.
6. Decide whether C passes before looking at D outcomes.
7. If passed, run and score D.
8. Update the ontology only in a new version/arm; never mutate `tenancy-items-v1` mid-experiment.

## Production decision

If C and D pass, integrate the canonical contract into `build_item_schema()` and `_parse_items()` so `Item.item_type` comes directly from the model and `name` becomes presentation-only. Until then the production describe path remains unchanged, while `Item.normalise()` continues to provide conservative backward-compatible canonicalisation for legacy inventories.
