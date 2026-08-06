# Phase 0 — the describe-stability floor

27 pairs, gemini-3.5-flash-low / production-v1. The two instruments measure different things and are never averaged.

| Metric | Repeat-describe control | Delta pairs |
|---|---:|---:|
| Schedule agreement, exact names | 34.6% | 32.4% |
| Schedule agreement, normalised | 37.3% | 35.2% |
| Membership churn per room | 10.7 | 11.96 |
| Naming churn per room | 4.26 | 4.22 |
| Condition agreement | 81.7% | 74.3% |
| Condition agreement, within one | 100.0% | 99.5% |
| Cleanliness agreement | 80.7% | 70.1% |
| Cleanliness agreement, within one | 100.0% | 99.7% |
| Quantity agreement | 96.1% | 94.4% |
| Photo-view agreement | 64.8% | 62.2% |
| Coverage, run A | 58.5% | 58.5% |
| Coverage, run B | 57.7% | 56.4% |
| Coverage stability | 77.8% | 77.0% |

The control's two runs read the same frames, so every change it reports is non-determinism. The delta pairs' two runs read different photographs, so theirs is non-determinism plus real difference.

## The gate

| | |
|---|---:|
| Changes reported by the control (all spurious) | **336** |
| Changes reported on the delta pairs | 407 |
| Delta-pair false changes (scored) | 368 |
| Floor as a share of them | **91.3%** |

Not decided here. docs/35 Phase 0 exits on a measurement, and the decision is recorded against the number by a person.

## What the control's churn is

- unpaired removals: 138
- unpaired additions: 151
- aligned but renamed: 115
- aligned and reported as changed: 47

## The floor is itself a floor

116 of 389 aligned items were graded differently by the two runs, and **76** of those never reached the reader: the tenancy gate reports an item only when it got *worse* or gained a defect, so a second run that grades the room better passes through compare in silence. The headline floor does not contain them.

Synthetic development evidence. This measures describe stability on one generator's images and promotes nothing (docs/00, docs/35).
