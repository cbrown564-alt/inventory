# 30 — Phase 4 native-resolution quality gate

*11 Jul 2026. Repository-controlled Phase 4 implementation record.*

The production path now contains the four accuracy cascades required by
docs/00: bounded semantic cover reranking (E8), bounded seam refinement (E2),
Grounding DINO plus proposal verification (E10), and tiered Gemini-to-Opus item
description. Local generation already applies a repeat penalty and a
temperature-jittered retry to break malformed repetition loops.

The remaining gate is data, not implementation. The committed InventoryFlex
capture is 192 images at about 0.48 MP median, so it cannot support a truthful
native-resolution defect-recall claim. A replacement capture must retain the
original image resolution and be scored into a JSON object with rates in 0..1:

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
cannot accidentally be reported as native resolution. Recapturing the source
pages and adjudicating the metrics remain external evidence work.
