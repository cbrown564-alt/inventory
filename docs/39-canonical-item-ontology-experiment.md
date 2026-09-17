# Canonical item ontology — Phase 1 correspondence experiment

**Status:** implementation ready; model intervention deliberately not enabled by default.

## Question

Phase 0 measured only 34.6% exact schedule agreement (37.3% under the product's lexical normaliser) when the same frames were described twice. The hypothesis here is narrower than “make the VLM better”:

> A material share of correspondence noise is caused by asking the model to invent the vocabulary that downstream code must later interpret.

The intervention separates **machine identity** from **report prose**. `item_type` is a bounded canonical concept; `name` and `description` remain natural. Material, colour, mounting and style should not normally create a new identity. Concepts remain separate when confusing them would materially change a tenancy inventory (door vs door handle, bed vs mattress, waste bin vs bread bin).

## Implementation

`homeinventory/ontology.py` is the single registry for `tenancy-items-v1`, with roughly 100 canonical concepts across structure, fixtures, sanitary ware, appliances, furniture, soft furnishings, decor, electronics, kitchenware, safety and meters. `other` is the explicit open-world escape hatch.

`Item` gains optional `item_type`, `subtype`, `attributes`, `instance_key` and `ontology_version`. Existing JSON remains readable. Legacy names are canonicalised only where the registry has a safe mapping; unknowns abstain rather than being guessed. When a canonical identity exists it owns the broad category, removing category drift as a second source of instability.

The production describe contract is intentionally unchanged in Phase 1. This lets us measure the value and risks of the ontology on cached outputs before confounding the result with a new prompt/schema. A later arm can make `item_type` a model-selected enum.

## Full experiment

### Arm A — existing baseline

Use the frozen Phase-0 repeat-describe records and existing `score_stability.py` metrics. Preserve exact-name and current head-noun-normalised agreement as baselines.

### Arm B — post-hoc canonical identity

Run every cached item name through `canonicalize_name`. Report:

- canonical multiset agreement;
- canonical membership churn per room;
- mapping coverage / unknown rate;
- every many-surface-name collapse for human review;
- false merge audit, especially repeated items and functionally distinct nouns.

This arm is free and isolates whether vocabulary alone explains measured instability.

### Arm C — ontology-aware structured generation

Only if Arm B materially improves stability without unacceptable false merges, modify the VLM JSON schema so it must select `item_type` from the registry while retaining free-text `name`. Use identical frames, model, prompt content, decoding configuration and evidence preprocessing. Repeat every accepted Phase-0 room twice.

Measure the baseline metrics plus:

- canonical item agreement;
- canonical precision/recall against intended/gold concepts where available;
- `other` rate;
- invalid type/category combinations (must be zero after normalisation);
- instance collision rate for repeated same-type objects;
- raw visual coverage so improved stability cannot be purchased by emitting fewer items.

### Arm D — downstream compare

Run the 27 delta pairs through the same ontology-aware contract. Correspondence should prefer `(room, item_type, instance_key)` and fall back to the existing lexical matcher only for legacy/unknown items. Compare:

- false additions/removals;
- true item-added/item-removed recall;
- condition-change recall;
- total false changes;
- false merges that suppress a genuine change.

## Acceptance criteria

Do not adopt the ontology because agreement rises. Adopt only if all of these hold:

1. canonical agreement materially exceeds the 37.3% current normalised baseline;
2. membership churn falls without a material fall in intended-item coverage;
3. human audit finds no systematic collapsing of materially different concepts;
4. `other`/unknown is low enough that the vocabulary is useful but remains available for genuinely uncovered concepts;
5. on delta pairs, false additions/removals fall while true addition/removal recall does not regress materially.

A provisional useful-effect threshold is **+20 percentage points canonical agreement** on the repeat control and **>=30% reduction in membership churn**, with intended-item coverage no more than 2 percentage points below baseline. These are decision thresholds, not claims about statistical significance.

## Repeated instances

A controlled type does not solve two bedside lamps or four chairs by itself. `instance_key` exists only for independently tracked repeats and should use stable spatial/function discriminators (`left_of_bed`, `right_of_bed`, `desk`). Quantity remains preferable when identical small items are intentionally grouped. Arm C must audit instance collisions separately.

## What this experiment does not solve

Canonical identity cannot recover an item omitted by both descriptions, make a small defect visible, establish that a defect is real, or prove that two visually similar repeated objects are the same physical instance. Those remain coverage, evidence and instance-correspondence problems. The ontology is successful if it removes vocabulary-induced noise without concealing those harder failures.

## Follow-on if accepted

1. Generate model-facing JSON Schema enums from the ontology registry.
2. Generate detector query aliases from the same registry, retiring duplicated synonym tables gradually.
3. Prefer canonical identity in `compare.align_items`; retain lexical fallback for old inventories.
4. Move defect strings to a separate typed finding ontology only after item identity is validated.
5. Version ontology changes and store the version on every canonicalised item so longitudinal comparisons remain reproducible.
