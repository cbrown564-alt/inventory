# 30 — Phase 4 native-resolution quality gate

*11 Jul 2026. Repository-controlled Phase 4 implementation record.*

The production path now contains the four accuracy cascades required by
docs/00: bounded semantic cover reranking (E8), bounded seam refinement (E2),
Grounding DINO plus proposal verification (E10), and tiered Gemini-to-Opus item
description. Local generation already applies a repeat penalty and a
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

- Phase 4 production engineering: **complete**.
- Native-resolution development/regression: may proceed on frozen local
  originals with appropriately bounded claims.
- Native-resolution quality gate: **pending external benchmark data**, not an
  implementation failure.
- Public quality claim: **not yet supported**.
- Next evidence task: source a professional report with its original images,
  or obtain permission and originals directly from a report provider; freeze
  and independently annotate the fixture before evaluating the unchanged
  pipeline.
