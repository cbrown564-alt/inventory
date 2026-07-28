# Phase 1 synthetic prompt comparison

Complete verified four-view packets evaluated through the pinned subscription-backed Antigravity CLI model/mode. No Gemini API endpoint is used.

| Prompt | Item recall | Defect recall | Unsupported defects | Input tokens | Output tokens | Cost (USD) | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| production-v1 | 78.1% | 50.0% | 1 | 172306 | 37250 | $0.000000 | 84.583s |
| evidence-bounded-coverage-v1 | 71.9% | 100.0% | 0 | 157577 | 34500 | $0.000000 | 80.103s |

## Paired direction

- Item recall: -6.2 percentage points.
- Defect recall: +50.0 percentage points.
- Unsupported defects: -1.
- Estimated cost: $+0.000000.
- Material-claim guardrail passed: yes.

## Limits


## Generator slices

### GPT Image 2

- production-v1: item recall 78.1%, defect recall 50.0%, unsupported defects 1.
- evidence-bounded-coverage-v1: item recall 71.9%, defect recall 100.0%, unsupported defects 0.
- The reviewed claims do not mark a notable subset, so notable recall is not reported.
- Unmatched predicted items require human review; the fixture records generator deviations but is not exhaustive enough for a public hallucination claim.
- Condition labels are descriptive rather than ordinal grades, so condition agreement is not reported.
- This synthetic slice is development evidence, not real-property accuracy evidence.

## Row-level failures

### RP-001.GPT Image 2.gemini-3.5-flash-low.evidence-bounded-coverage-v1

- Missed reviewed claims: induction hob, base unit door, plinth
- Missed reviewed defects: none
- Defects without reviewed support: none
- Evidence-link failures: none
- Unmatched predicted items needing review: Walls, Ceiling, Window, Internal door, Door frame, Wall cabinets, Fridge-freezer, Microwave oven, Kettle, Toaster, Air fryer, Ceiling light fixture, Light switch, Double wall sockets, Windowsill plant, Dish drying rack, Knife block and knives, Utensil holder and utensils, Chopping board, Storage canisters, Condiment and oil bottles, Fruit bowl, Washing-up liquid and hand soap, Refrigerator magnets, Threshold strip

### RP-002.GPT Image 2.gemini-3.5-flash-low.evidence-bounded-coverage-v1

- Missed reviewed claims: grey wall tiles, mixer taps, bath panel, silicone seal, vinyl floor, lower wall tiles
- Missed reviewed defects: none
- Defects without reviewed support: none
- Evidence-link failures: none
- Unmatched predicted items needing review: Tiled walls, Painted walls, Ceiling, Floor tiling, Door frame and architrave, Window, Recessed spotlights, Shaver socket, Pedestal wash hand basin, Toilet brush and holder, Charcoal towel, Pedestal mirror, Window sill toiletries, Bath toiletries

### RP-001.GPT Image 2.gemini-3.5-flash-low.production-v1

- Missed reviewed claims: base unit door, plinth
- Missed reviewed defects: none
- Defects without reviewed support: none
- Evidence-link failures: none
- Unmatched predicted items needing review: Ceiling, Walls, Door frame, Threshold strip, Window (sink area), Window (side wall), Roller blind, Fridge freezer, Microwave, Kettle, Toaster, Air fryer, Ceiling light fitting, Light switch, Dish drying rack, Knife block, Utensil holder and utensils, Chopping board, Kitchen canisters, Cooking oil and condiments, Fruit bowl, Potted plants, Dish soap and soap dispenser

### RP-002.GPT Image 2.gemini-3.5-flash-low.production-v1

- Missed reviewed claims: grey wall tiles, mixer taps, shower handset, silicone seal, lower wall tiles
- Missed reviewed defects: bath panel: Short shallow scuff
- Defects without reviewed support: Bath: horizontal scratch mark approx. 8cm long at knee level on the lower-left section of the front bath panel
- Evidence-link failures: none
- Unmatched predicted items needing review: Ceiling, Walls, Door frame, Window, Recessed spotlights, Shaver socket, Toilet brush and holder, Cosmetic mirror, Toiletries

Phase 1 comparison complete. Treat the result as directional; freeze no product prompt until the development and validation sets are complete. Antigravity wrapper results are development evidence and do not claim raw production-API equivalence.
