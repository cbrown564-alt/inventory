# 30 — Phase 4 native-resolution quality gate

*11 Jul 2026. Repository-controlled Phase 4 implementation record.*

The production path contains bounded semantic cover reranking (E8), bounded
seam refinement (E2), and Grounding DINO plus proposal verification (E10).
The tiered Gemini-to-Opus backend is implemented and tested, but the current
CLI and web defaults still select the Gemini/OpenAI-compatible backend
directly. Tiered routing remains a promotion candidate, not shipped default
behaviour. Local generation applies a repeat penalty and a
temperature-jittered retry to break malformed repetition loops.

The remaining gate is data, not implementation. The committed InventoryFlex
capture is 192 images at about 0.48 MP median, so it cannot support a truthful
native-resolution defect-recall claim. Its public sample exposes only the
compiled report: no original photographs or usable interactive gallery could
be found. Other public professional samples investigated on 11 July 2026 had
the same limitation, broken high-resolution links, or inaccessible galleries.
InventoryFlex therefore remains a professional **report-format and low-resolution
regression fixture**, not the native-resolution gold standard.

The only native-resolution evidence currently available is the owner's local
photography. It may be used for development and regression work, but must not
be described as an external benchmark or gold standard. A replacement external
fixture must retain original image resolution and independent annotations. In
the interim, a frozen subset of the local originals may provide a useful
internal evaluation if the untouched files and metadata are retained, the
answers are fixed before the scored run, and the provenance and annotator are
reported. Results must be labelled according to their evidence:

- owner/self annotated: **development evaluation**;
- independently annotated local capture: **internal held-out evaluation**;
- independently annotated external source: **external benchmark**.

## External component-benchmark minimum

The v1 native-photo gate must be frozen before the scored run and contain:

- two materially different external properties;
- at least 100 independently annotated notable inventory facts;
- at least 20 material visible defects, so one miss changes defect recall by
  no more than five percentage points;
- clean and ambiguous near-negatives for unsupported-defect testing; and
- original images meeting the existing median-resolution threshold of 8 MP.

If this evidence cannot be sourced, the gate remains blocked; do not reduce
the denominators to manufacture a pass.

This is a component benchmark for description accuracy from native-resolution
photographs. It does not measure walkthrough segmentation, frame selection,
boundary bleed or evidence lost during capture processing. Property A/B
capture results provide separate acquisition evidence. Public wording must
keep those sources separate: an end-to-end claim such as “90% recall from
your walkthrough” requires a later evaluation of untouched drafts produced
through the selected capture path.

Metrics are scored into a JSON object with rates in 0..1:

```json
{
  "notable_recall": 0.90,
  "hallucination": 0.05,
  "defect_recall": 0.75
}
```

Run the fail-closed gate:

```sh
python benchmarks/quality_gate.py \
  benchmarks/inventoryflex-native/capture \
  benchmarks/inventoryflex-native/metrics.json \
  -o benchmarks/inventoryflex-native/quality-gate.json
```

The command exits non-zero unless median source resolution is at least 8 MP
and all three docs/00 thresholds pass. The current 0.48 MP fixture therefore
cannot accidentally be reported as native resolution.

## Current disposition

- E2/E8/E10 production engineering: **complete**.
- Tiered describe implementation: **complete but not promoted to the product
  default**; clear the synthetic and real-fixture comparison first.
- Native-resolution development/regression: may proceed on frozen local
  originals with appropriately bounded claims.
- Native-resolution component gate: **pending external benchmark data** that
  meets the minimum above, not an implementation failure.
- Native-photo component quality claim: **not yet supported**.
- End-to-end walkthrough percentages: **not measured by this gate**.
- Next evidence task: source a professional report with its original images,
  or obtain permission and originals directly from a report provider; freeze
  and independently annotate the fixture before evaluating the unchanged
  pipeline.
