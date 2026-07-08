# 24 — First-tester runbook

*8 Jul 2026. Operational script for the Phase 1 exit gate in
[`00-north-star.md`](00-north-star.md). The owner drives one real tenancy
end-to-end in the browser; this doc is what you run and what you record.*

**Status:** active · **Blocks:** v1 definition of done (docs/00)

---

## Prerequisites

1. **Machine:** laptop with network; phone on same Wi‑Fi if testing tenant link.
2. **Repo:** latest `main` (or the Phase 1 branch), `.venv` with `[all,dev]`.
3. **Credentials** in `.env` at repo root:

```sh
GEMINI_API_KEY=...          # required — default describe + segmentation
ANTHROPIC_API_KEY=...       # optional — opus backup for hard items (Phase 2 routing)
```

4. **Capture:** one real walkthrough video of the property (~5–15 min, phone
   held steadily, pause briefly at each room doorway). Keep the file — do not
   commit it (gitignored under `capture/`).

5. **Time budget:** ~45–90 minutes for first run (build wait + review + sign).

---

## Launch

```sh
mkdir -p capture report
homeinventory review capture/ -o report/
# → open http://127.0.0.1:8484/
```

Use `--share` if you will test the tenant countersign link on a phone.

---

## Test script

Run every step. For each step, note **Pass / Fail / N/A** and any friction
in the log table below.

| # | Step | Expected observable | Pass? | Friction notes |
|---|---|---|---|---|
| 1 | Open the app (no prior build) | Start page: filming guide + video drop zone; plain-language spend copy (not backend names) | | |
| 2 | Drop walkthrough video | Upload row shows filename, size; build button enables | | |
| 3 | Confirm build | Dialog shows estimated cost in plain language; accept with `yes` | | |
| 4 | Wait for build | Staged progress: watching footage → finding rooms → extracting frames → drafting items → rendering report; **room name chips** appear after segmentation | | |
| 5 | Build completes | Browser lands on **Overview** (`/#overview`), not item 1 of N | | |
| 6 | Overview | Stats bar (rooms · items · frames); room gallery with hero thumbs; *Start review* CTA visible | | |
| 7 | Open one room card | Room view: hero frames, rename/merge tools reachable | | |
| 8 | *Start review* | Item queue opens; least-confident items first; walkthrough spine visible | | |
| 9 | Confirm 3–5 items | Overview meters update when returning to `#overview` | | |
| 10 | Finish checklist (`#finish`) | Blocks sign until **property address** set on cover | | |
| 11 | Set address + sign | Signature recorded; hash pinned in inventory | | |
| 12 | Final issue (`/issue`) | Clean sendable document; address on cover | | |
| 13 | Report round-trip | Report → *Continue in Review* → Overview (same tab) | | |
| 14 | PDF | PDF exists at build completion **or** exports from Finish without hunting | | |
| 15 | Mobile (390px) | Overview 2-col grid; Finish reachable; no broken layout | | |
| 16 | Tenant link (optional) | `--share` link opens; tenant can comment; countersign works | | |

---

## Friction log (fill in during the run)

Use one row per issue — even small ones. Tag severity so Phase 2 can prioritise.

| ID | Step | Severity | What happened | Expected | Fix / ticket |
|---|---|---|---|---|---|
| F1 | | blocker / major / minor / nit | | | |
| F2 | | | | | |

**Severity guide:**

- **blocker** — cannot complete the journey
- **major** — completes with workaround; erodes trust (“I'd pay £165 instead”)
- **minor** — annoying but survivable
- **nit** — polish only

---

## Success criteria (Phase 1 exit)

From docs/00 — check when the run finishes:

- [ ] Steps 1–14 pass without a **blocker**
- [ ] Friction log committed (this file or `docs/24-friction-log-YYYY-MM-DD.md`)
- [ ] Every **blocker** and **major** has a fix plan or explicit deferral with reason
- [ ] Build used gemini default (check `inventory.json` → `describe_backend`)
- [ ] Signed PDF or HTML issue is sendable to a tenant/agent

When all boxes are checked, Phase 1 is **done** and Phase 2 (E2/E8/E10 wiring)
starts.

---

## Optional second journey (same session)

**Deep clean:** create project → upload before video → build → upload after
video → comparison sheet auto-appears. Record friction in the same log with
step prefix `DC-`.

---

## What to commit after the run

1. Friction log (sanitised — no API keys, no tenant PII)
2. Screenshots at 1440px and 390px for Overview, Items, Finish, Issue (optional
   but useful for regression)
3. Update docs/00 definition-of-done checkboxes

Do **not** commit the walkthrough video or signed report with real addresses
unless explicitly intended for the eval fixture.

---

## Related

- Journey design: [`17-experience-redesign.md`](17-experience-redesign.md) (X1–X6 shipped)
- Product plan: [`12-video-first-journey.md`](12-video-first-journey.md)
- Quality bar: [`10-product-quality-review.md`](10-product-quality-review.md)
