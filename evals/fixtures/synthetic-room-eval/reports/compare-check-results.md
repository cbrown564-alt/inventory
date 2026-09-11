# Compare check results

Recorded 2026-08-08T06:50:25.047353+00:00.

## Set

Twenty-seven review-accepted GPT Image 2 delta pairs (Phase 3.5), scored against committed describe records. No new generation or describe.

## Method

- Instrument: product `compare_inventories` on cached T0/T1 describes (gemini-3.5-flash-low / production-v1).
- Noise floor: Phase 0 repeat-describe control (same frames twice).
- Headline: aligned-item state signal (condition / cleanliness / items reported changed) versus that floor — not `false_change_rate` alone.
- Readout: diagnostics only — no pass bar. Promotes nothing (docs/08).

## Signal versus noise

| Quantity | Control | Delta | Ratio |
|---|---:|---:|---:|
| Naming churn | 115 | 114 | 0.99× |
| Unpaired removals | 138 | 149 | 1.08× |
| Membership churn | 289 | 323 | 1.12× |
| Unpaired additions | 151 | 174 | 1.15× |
| Condition disagreements | 71 | 97 | 1.37× ← signal |
| Cleanliness disagreements | 75 | 113 | 1.51× ← signal |
| Items reported changed | 47 | 84 | 1.79× ← signal |

Schedule membership (naming / unpaired / membership churn) sits at ~1× the control. Aligned-item state does not: items reported changed **1.79×**, cleanliness disagreements **1.51×**, condition disagreements **1.37×**.

## Scored gold changes

- Delta recall: **26.6%** (37 / 139)
- False-change rate (membership-dominated): **90.4%**
- Of 368 false changes: 138 alignment churn, 71 unpaired removals, 86 unpaired additions, 73 in the changed bucket

| Kind | Gold | Detected | Recall |
|---|---:|---:|---:|
| cleanliness | 26 | 1 | 3.8% |
| item_added | 35 | 19 | 54.3% |
| item_removed | 18 | 9 | 50.0% |
| new_defect | 33 | 4 | 12.1% |
| worsened | 27 | 4 | 14.8% |

## Cleanliness gate (product diagnostic)

Cached records re-compared under three gates. No new describes.

| Gate | Cleanliness recall | Worsened | Delta recall | False-change rate |
|---|---:|---:|---:|---:|
| as_shipped | 3.8% | 14.8% | 26.6% | 90.4% |
| cleanliness_worsening | 11.5% | 14.8% | 28.1% | 90.5% |
| any_grade_or_cleanliness | 15.4% | 18.5% | 29.5% | 90.9% |

The shipped tenancy gate ignores cleanliness-only worsenings. Widening it is a product decision (deposit cleaning claims), not an eval one.

## Stop

Compare check measurement is complete. The instrument works on aligned-item state; schedule-membership noise dominates `false_change_rate`. Further synthetic compare work is backlog (naming alignment, cleanliness gate product decision, real check-in/out transfer) — see the synthetic backlog plan.

## Artifacts

- Score JSON: `reports/compare-check-score-2026-08-06.json`
- Sources: `phase0-describe-stability-2026-08-06.json`, `phase35-delta-score-2026-08-05.json`
