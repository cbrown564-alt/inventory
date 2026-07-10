# Documentation index

*Start here. For v1 scope and the singular path forward, read
[`00-north-star.md`](00-north-star.md) first.*

## Authority tiers

| Tier | Docs | When to read |
|---|---|---|
| **North star** | [00](00-north-star.md) | Always — end goal, v1 scope, deferred list |
| **Product plan** | [12](12-video-first-journey.md) | Building or changing the user journey |
| **Quality bar** | [10](10-product-quality-review.md), [04](04-backend-comparison.md) | UI/PDF polish; backend benchmarks |
| **Milestone ledger** | [03](03-implementation-plan.md) | Historical — what shipped when (frozen) |
| **Feature records** | [06](06-professional-report-benchmark.md)–[09](09-web-ui-and-capture.md), [15](15-curation-and-one-app.md)–[16](16-report-redesign.md) | Deep dive on a shipped milestone |
| **Design reference** | [05](05-review-experience.md), [14](14-frontend-craft.md), [17](17-experience-redesign.md) | Review UX principles and next work |
| **Technical spikes** | [02](02-research.md), [11](11-video-segmentation.md), [13](13-yoloe-detection.md), [18](18-hero-image-selection.md), [26](26-capture-strategy-experiment.md), [market-research](market-research-2026-07.md) | Background research and eval methodology |
| **ML programme** | [19](19-ml-dl-exploration-plan.md), [21](21-ml-dl-experiment-log.md), [22](22-ml-programme-review-and-roadmap.md), [23](23-gpu-rerun-runbook.md) | ML experiments — subordinate to docs/00 |
| **Future** | [20](20-ios-native-app.md) | Post-v1 iOS track |

## Reading paths

**Product today**

1. [00](00-north-star.md) → [12](12-video-first-journey.md) → [10](10-product-quality-review.md) → [04](04-backend-comparison.md)

**Phase 1 — first-tester exit**

1. [24](24-first-tester-runbook.md) → run on a real property → commit friction log

**UX next work**

1. [17](17-experience-redesign.md) with [14](14-frontend-craft.md), [15](15-curation-and-one-app.md), [16](16-report-redesign.md) as context

**ML next work**

1. [00](00-north-star.md) §Phase 2 → [21](21-ml-dl-experiment-log.md) (status) → [23](23-gpu-rerun-runbook.md) (commands) → [22](22-ml-programme-review-and-roadmap.md) (strategy)

**Historical / debug**

- [07](07-own-property-run.md) — boundary bleed, own-property run
- [06](06-professional-report-benchmark.md) — M1 benchmark (pre-v4 scores; see [04](04-backend-comparison.md) for current)
- [archive/09-m5b-guided-capture-retired.md](archive/09-m5b-guided-capture-retired.md) — why phone capture was killed

## Doc status key

| Status | Meaning |
|---|---|
| **active** | Current plan or living reference |
| **record** | Shipped milestone write-up; frozen |
| **archived** | Historical; kept for audit trail |
| **deferred** | Explicitly post-v1 |

## All docs

| # | File | Status | Summary |
|---|---|---|---|
| 00 | [north-star](00-north-star.md) | active | End goal, v1 scope, singular path |
| 24 | [first-tester-runbook](24-first-tester-runbook.md) | active | Phase 1 exit gate script + friction log |
| 01 | [scope-and-architecture](01-scope-and-architecture.md) | active* | Pipeline architecture (*§3.3/§4 superseded by 12) |
| 02 | [research](02-research.md) | active | TDS/AIIC standards, YOLOE, VLM landscape |
| 03 | [implementation-plan](03-implementation-plan.md) | record | Milestones M0→M5 (frozen ledger) |
| 04 | [backend-comparison](04-backend-comparison.md) | active | Describe backend benchmarks |
| 05 | [review-experience](05-review-experience.md) | record | Review UX Levels 0–4 |
| 06 | [professional-report-benchmark](06-professional-report-benchmark.md) | record | M1 vs clerk report |
| 07 | [own-property-run](07-own-property-run.md) | record | M2 real property run |
| 08 | [compare](08-compare.md) | record | M4 check-in vs check-out |
| 09 | [web-ui-and-capture](09-web-ui-and-capture.md) | record | M5a web UI; M5b archived |
| 10 | [product-quality-review](10-product-quality-review.md) | active | Quality bar ("Linear, not toy") |
| 11 | [video-segmentation](11-video-segmentation.md) | record | Segmentation spike (completed) |
| 12 | [video-first-journey](12-video-first-journey.md) | active | **Product plan of record** |
| 13 | [yoloe-detection](13-yoloe-detection.md) | record | YOLOE eval on InventoryFlex |
| 14 | [frontend-craft](14-frontend-craft.md) | active | Design principles |
| 15 | [curation-and-one-app](15-curation-and-one-app.md) | record | Hero curation + one-app shell |
| 16 | [report-redesign](16-report-redesign.md) | record | Report catalogue layout |
| 17 | [experience-redesign](17-experience-redesign.md) | active | Orient→finish UX plan |
| 18 | [hero-image-selection](18-hero-image-selection.md) | record | Cover scorer experiments |
| 19 | [ml-dl-exploration-plan](19-ml-dl-exploration-plan.md) | active | ML-E1–E20 plan |
| 20 | [ios-native-app](20-ios-native-app.md) | deferred | Post-v1 iOS architecture |
| 21 | [ml-dl-experiment-log](21-ml-dl-experiment-log.md) | active | ML status tracker (authoritative) |
| 22 | [ml-programme-review-and-roadmap](22-ml-programme-review-and-roadmap.md) | active* | ML strategy (*§2 pre-GPU; see 21) |
| 23 | [gpu-rerun-runbook](23-gpu-rerun-runbook.md) | active | GPU execution runbook |
| 24 | [friction-log-2026-07-08](24-friction-log-2026-07-08.md) | record | First-tester run friction log |
| 25 | [design-overhaul](25-design-overhaul.md) | active | One design system across all surfaces |
| 26 | [capture-strategy-experiment](26-capture-strategy-experiment.md) | active | Photo vs video capture experiment design |
| 27 | [mobile-owner-pairing-friction-log](27-mobile-owner-pairing-friction-log-2026-07-10.md) | active | QR owner-pairing incident and LAN reliability gate |
| — | [market-research-2026-07](market-research-2026-07.md) | active | Competitive map, evidential spec, pricing anchors |
