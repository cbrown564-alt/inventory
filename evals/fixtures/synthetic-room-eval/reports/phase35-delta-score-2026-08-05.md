# Phase 3.5 delta scoring

27 of 27 review-accepted pairs scored.

| Slice | Pairs | Delta recall | False change | Unchanged stability |
|---|---:|---:|---:|---:|
| Clean | 18 | 34.4% | 88.0% | 40.9% |
| Thin signal | 6 | 10.0% | 96.4% | 49.0% |
| Cross-view conflict | 3 | 12.5% | 96.5% | 39.6% |
| All pairs | 27 | 26.6% | 90.8% | 42.6% |

## What the false changes are

154 of 385 (40.0%) are one object reported twice because the two runs named it differently and `match_score` did not align them.

- alignment churn (rename pairs): 154
- unpaired removals — T1 omitted what T0 listed: 72
- unpaired additions — T1 listed what T0 omitted: 87
- reported in the changed bucket: 72

Diagnostic: with renames aligned the rate would be 85.6%. false_change_rate_if_renames_aligned is a diagnostic, not a corrected metric. The reported rate stands as measured: a landlord reading the report sees both halves of a rename as real changes.

## Why a condition change went unreported

| Fate | Count | Fix |
|---|---:|---|
| Object split by the aligner | 18 | `match_score` — the delta was never compared |
| Tracked but silent | 17 | a genuine detection miss |
| Never named by either run | 42 | description coverage; no aligner change recovers it |

## Recall by change kind

| Kind | Gold | Detected | Recall |
|---|---:|---:|---:|
| cleanliness | 26 | 1 | 3.8% |
| item_added | 35 | 19 | 54.3% |
| item_removed | 18 | 9 | 50.0% |
| new_defect | 33 | 4 | 12.1% |
| worsened | 27 | 4 | 14.8% |

## By pair class

| Class | Pairs | Delta recall | False change |
|---|---:|---:|---:|
| counterfactual | 9 | 24.0% | 91.3% |
| temporal | 18 | 28.1% | 90.6% |

Synthetic development evidence. Delta pairs cannot promote compare behaviour; that is gated on real check-in/check-out evidence (docs/08). Never present a synthetic delta pair as a real tenancy comparison.
