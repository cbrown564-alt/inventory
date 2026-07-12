# 00 — North star

*8 Jul 2026. Single source of truth for v1 scope, success criteria, and what
is explicitly deferred. Supersedes scattered open items in docs/03, docs/12,
and docs/22 when they conflict. Read this first; everything else is detail.*

---

## End goal

**A landlord films one walkthrough on their phone, uploads it in the browser,
reviews a TDS-credible inventory report, signs it, and downloads a professional
PDF — for pennies, not £165.**

The competition is not other tools; it is not bothering.

---

## Market position (July 2026)

*From [`market-research-2026-07.md`](market-research-2026-07.md). Reshapes
emphasis, not direction.*

- **The consumer lane is open.** Every AI-native video-first entrant
  (iListingAI, Amnis, KapturAI, Inspecto, Paraspot) targets professionals
  — clerks, agents, portfolio managers. Nobody serves the self-managing
  landlord, which is exactly our target. RentCheck (4.8★, ~18k App Store
  ratings; US, photo-only, no AI) proves the consumer demand exists.
- **"Video → AI report" is not a moat** — at least five UK players ship
  it, and speed messaging is commoditised ("90% faster", "under 5
  minutes"). We differentiate on trust/evidence quality (Pillars 1–2),
  consumer accessibility, and report design — not speed, not the pipeline.
- **The trust bar is the scheme evidential spec** (TDS/DPS/mydeposits):
  timestamps in file metadata, written report with embedded photos,
  time-referenced video, both-party signatures, tamper evidence. The four
  independence-discount mitigations the schemes imply — tenant
  countersign, embedded dated photos, tamper-evident audit trail, frames
  linked to the unedited source video — are all shipped. They are the
  headline claim; price is the supporting act.
- **Comparison is the decisive artefact.** Adjudicators decide by
  comparing check-in vs check-out; without both, landlord claims are
  "highly likely to be rejected". The check-in report is the baseline for
  a future comparison and should be framed and sold that way — think
  per-tenancy (check-in + check-out + compare), not per-report
  (competitors anchor PAYG at £9–10/report; free floor exists).
- **Retention is a free differentiator.** iListingAI's £9 tier deletes
  reports after 7 days; a tenancy matures at 12+ months. Local-first means
  the landlord keeps their evidence forever. If a hosted version ever
  ships, retention-until-dispute-window is a commitment, not a paid tier.

---

## v1 success criteria

| Dimension | Target | Measured on |
|---|---|---|
| **Journey** | Upload one video → auto build → review → sign → PDF. No CLI required. | First-tester friction log (docs/12) |
| **Quality** | Notable recall ≥90%, hallucination ≤5%, defect recall ≥75% | Native-res InventoryFlex benchmark (Phase 3) |
| **Cost** | ≤£3 per property at signed-report quality | Build token usage + spend confirms |
| **Trust** | Human attestation, SHA-256 manifest, timecodes back to source video | Report template + review loop |
| **Latency** | Build completes without user intervention; progress visible in browser | Web UI build flow |

---

## Primary journey

1. Open the web app (`homeinventory review capture/ -o report/`)
2. Drop one walkthrough video
3. Confirm spend in plain language
4. Wait (segment → describe → curate → PDF — all invisible)
5. Review room-by-room, fix grades/defects, sign
6. Send the tenant link to review, comment, and countersign
   (Finish mints the link; `--share` pre-enables it and phone pairing —
   mydeposits gives max weight only when both parties sign)
7. Download the attested PDF

Deep-clean and check-in/check-out are **secondary journeys** on the same
shape (docs/12) — secondary in *sequence*, not importance: the check-in vs
check-out comparison is the artefact adjudicators actually decide on, so
the check-in journey must frame itself as the baseline for that future
compare. The CLI remains plumbing for power users and CI.

---

## Backend policy

| Task | Default | Backup |
|---|---|---|
| **Walkthrough segmentation** | `gemini-3.5-flash` | `claude-sonnet-5` (quality alternative) |
| **Item describe (most rooms/items)** | `gemini-3.5-flash` via `--backend openai` | — |
| **Hard items** (low confidence, defect claims, ambiguous grades) | Route to **`claude-opus-4-8`** | Human review loop always available |
| **Local £0 draft** | `gemma4:26b` via `--backend local` | `qwen3.5:9b` (lighter) |
| **CI / offline** | `--backend offline` | — |

Gemini is the **default** describe backend — cheap, fast, clears the
hallucination ceiling. Opus is the **expensive backup** for complex tasks,
not the default for every item. Tiered routing (cheap draft → opus on hard
tail) is Phase 2 work (docs/22 §5.2).

Credentials live in a gitignored `.env`; the journey never mentions backends
or model names (docs/12).

---

## Authority hierarchy

| Tier | Doc | Role |
|---|---|---|
| **0** | **This doc** | End goal, v1 scope, deferred list |
| **1** | [`12-video-first-journey.md`](12-video-first-journey.md) | Product plan of record |
| **2** | [`10-product-quality-review.md`](10-product-quality-review.md) + [`04-backend-comparison.md`](04-backend-comparison.md) | Quality bar + benchmark scores |
| **3** | [`03-implementation-plan.md`](03-implementation-plan.md) | Milestone ledger (frozen; no new open items) |
| **4** | 06–09, 15–16 | Shipped feature records |
| **5** | 02, 11, 13, 18, 21, market-research-2026-07 | Research / spike reference |
| **6** | 19, 21, 22, 23 | ML programme (subordinate to v1) |
| **7** | [`20-ios-native-app.md`](20-ios-native-app.md) | Post-v1 |

---

## The singular path (sequenced)

```text
Phase 0 — CONSOLIDATE ✓ (Jul 2026)
  docs/00 + doc index + pipeline.run_build()
  → one doc to read, one code path to build

Phase 1 — SHIP THE JOURNEY (in progress)
  Video upload → segment → build → review → sign → PDF
  → first-tester run with friction log (docs/24)

Phase 2 — SHIP PROVEN QUALITY WINS
  E8 VLM cover rerank, E2 seam refine, E10 GDINO + verify
  gemma4 repetition-loop fix; tiered describe routing (gemini → opus)

Phase 3 — FIX THE ACCURACY CEILING
  Native-res InventoryFlex re-capture
  Re-measure defect recall (currently resolution-bound at 64–71%)
  Scale bbox gold if detector fine-tune still wanted

Phase 4 — COST REDUCTION (post-v1, only if Phase 1–3 pass)
  E3 describe pool, distillation flywheel (docs/22 §5.4)
```

---

## Explicitly deferred (not v1 blockers)

| Item | Reason | Doc |
|---|---|---|
| iOS native app | Post-v1; web app is the product | docs/20 |
| ML-E18 full GDINO pretrain | No demonstrated upside vs E10 zero-shot | docs/23 §5 |
| C2PA / e-signature | Policy work; human attestation sufficient for v1 | docs/03 M5 |
| Multi-property management | Scope creep | docs/03 M5 |
| Zero-shot relevance/shot-scale (E4/E7/E19) | Confirmed real negatives post-GPU | docs/21 |
| Embedding changepoint segmentation (E1) | Wrong signal model | docs/22 §5.5 |
| Pause detection (E9) | Walkthroughs are continuous motion | docs/22 |
| Phone guided capture (M5b) | Tried and killed | docs/archive/09-m5b |

---

## Definition of done (v1)

*The test is not "did the steps execute" — the first-tester run proved
they do. The test is: **would a landlord who can afford £165 for peace
of mind choose this instead?** That is a visual-trust and completeness
bar, not a plumbing checklist. The criteria below encode it directly.*

### Pillar 1 — The product earns trust at first glance

The first thing a landlord sees is the overview — room cards with hero
images. If those images are bad (wrong room, object close-up, motion
blur), no amount of correct text recovers. Visual polish is not
decoration; for a real-estate product it *is* the value proposition.

- [x] **One design system across every surface** — start, review,
      tenant, report, PDF share one palette, type scale, spacing
      grammar, and component library. No third theme. Scoping doc:
      [`25-design-overhaul.md`](25-design-overhaul.md).
- [x] **The review surface is rebuilt to the craft bar** (docs/14) —
      light/airy consistency with the landing page (the "two worlds"
      split is re-evaluated), generous type and spacing, hover/affordance
      polish matching the start page, no 9px density. Craft C1+C2 landed.
- [ ] **First-screen trust sign-off** — owner looks at the overview on
      a fresh build and says *"I'd send this to a landlord"* without
      qualification. This is the gate the old DoD lacked.

### Pillar 2 — The evidence is trustworthy by construction

Heroes must depict the right room, well-framed, because the user chose
the right capture strategy and the pipeline selects representative
frames — not because a heuristic picked the least-bad option from a
pool that may contain the wrong room entirely.

- [ ] **Capture strategy validated** (photo vs video, at multiple
      volumes, measured on accuracy / image quality / time / effort) —
      the deepest open question and the one that determines the
      pipeline's shape. Experiment design:
      [`26-capture-strategy-experiment.md`](26-capture-strategy-experiment.md).
- [x] **Heroes depict the named room** — E7 detector-assisted semantic rank 1
      plus E7b ``cover_status`` validation flag unsupported or weak-identity
      covers for review rather than silent ship. Stairs/landing remain classical
      until broader detector evidence exists (docs/18). Dense-anchor benchmark:
      10/10 acceptable, 7/10 preferred on frozen fixtures.
- [x] **Pipeline can flag a bad segment**, not silently pick the
      least-bad frame — ``review_required`` / ``cover_status`` on room and
      ``curation.json`` when rank 1 fails classical or semantic confidence;
      rank 1 stays visible in the overview with an explicit flag.
- [x] **Report meets the deposit-scheme evidential spec point-by-point**
      ([`market-research-2026-07.md`](market-research-2026-07.md),
      audit: [`29-evidential-spec-audit.md`](29-evidential-spec-audit.md)):
      capture timestamps in the *file metadata* of every embedded image
      (DPS checks metadata, not printed dates — extracted video frames get
      ``DateTimeOriginal`` at ingest; wall-clock provenance rule in docs/29;
      footage timecode retained via ``videometa.photo_time``), written report
      with embedded photos, video referenced by exact timecodes, both-party
      signatures, tamper-evident trail. Frame-metadata gap closed; tenant
      countersign ships as a default Finish step (Pillar 4).

### Pillar 3 — The report is accurate and complete

The existing quality bar — kept, because a beautiful report that is
wrong is still worthless.

- [ ] Native-res benchmark shows notable recall ≥90%, hallucination
      ≤5%, defect recall ≥75% (docs/10; currently resolution-bound at
      64–71% defect recall). Gate harness: `evals/verify_v1_accuracy.py`.
- [x] E8 + E2 + E10 wired into the production build path — ML-E8 VLM cover
      rerank (default ON when API keys exist; `--no-vlm-cover` keeps E5+E7),
      ML-E2 seam refine on fresh segmentations (`--no-seam-refine` to skip),
      ML-E10 Grounding DINO stage-1 with cheap vocab verify
      (`--detect-backend auto|gdino|yoloe`). Graceful fallbacks mandatory.

### Pillar 4 — The journey is low-friction end-to-end

The first-tester run (8 Jul 2026) proved the journey executes. These
are the remaining frictions that erode trust enough to send someone
back to the £165 option.

- [x] First-tester completes one real tenancy end-to-end in the browser
      — runbook: [`24-first-tester-runbook.md`](24-first-tester-runbook.md);
      log: [`24-friction-log-2026-07-08.md`](24-friction-log-2026-07-08.md)
- [x] Default build uses gemini-3.5-flash; opus available for hard items
- [x] All user-facing flows reachable from the UI (docs/10 bar; X1–X6
      shipped)
- [x] F1 Windows PDF resolved (WeasyPrint deps or browser-print fallback)
      — Finish offers Print → Save as PDF via final issue when WeasyPrint
      is missing (9 Jul craft N)
- [x] F2–F6 frictions addressed or explicitly ticketed with a reason
      (F2/F5 fixed; F3/F4/F6 ticketed in docs/24)
- [x] **Tenant countersign is a default journey step, not a flag** — the
      review flow ends with "send to tenant to countersign"; Finish mints
      the link via **Create tenant link**; `--share` pre-enables it and
      phone pairing. Independence is the credibility test a DIY inventory
      must pass, and both-party signatures are the max-weight condition
      (market-research-2026-07).

### Distance summary (honest)

| Pillar | Status |
|---|---|
| **1 — Trust at first glance** | **Mostly met.** Design system + review craft landed; first-screen owner sign-off remains. |
| **2 — Trustworthy by construction** | **Mostly met.** Capture scaffolding ready (experiment unrun). Hero no-confident-cover + EXIF frame metadata shipped. |
| **3 — Accurate & complete** | **Partially met.** E2/E8/E10 wired with fallbacks; defect recall still resolution-bound pending native-res fixture. |
| **4 — Low-friction journey** | **Met.** Finish mints tenant countersign link by default; `--share` is optional pre-enable. |

**v1 ships when every box is checked.** The old DoD was 4/6 done because
it measured the journey mechanically; the real bar — Pillars 1 and 2 —
is the bulk of the remaining work and is what "for pennies, not £165"
actually requires. Everything not listed here is v2.
