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

Use `--share` to pre-enable the tenant link and phone pairing on startup.

---

## Test script

Run every step. For each step, note **Pass / Fail / N/A** and any friction
in the log table below.

| # | Step | Expected observable | Pass? | Friction notes |
|---|---|---|---|---|
| 1 | Open the app (no prior build) | Start page: filming guide + video drop zone; plain-language spend copy (not backend names) | **Pass** | 8 Jul 2026 run |
| 2 | Drop walkthrough video | Upload row shows filename, size; build button enables | **Pass** | `IMG_5512.MOV` |
| 3 | Confirm build | Dialog shows estimated cost in plain language; accept with `yes` | **Pass** | |
| 4 | Wait for build | Staged progress: watching footage → finding rooms → extracting frames → drafting items → rendering report; **room name chips** appear after segmentation | **Pass** | ~16 min; see F3 in friction log |
| 5 | Build completes | Browser lands on **Overview** (`/#overview`), not item 1 of N | **Pass** | |
| 6 | Overview | Stats bar (rooms · items · frames); room gallery with hero thumbs; *Start review* CTA visible | **Pass** | 10 rooms · 186 items · 92 frames |
| 7 | Open one room card | Room view: hero frames, rename/merge tools reachable | **Pass** | Hallway tested |
| 8 | *Start review* | Item queue opens; least-confident items first; walkthrough spine visible | **Pass** | *Play this moment* per item |
| 9 | Confirm 3–5 items | Overview meters update when returning to `#overview` | **Pass** | 6 confirmed |
| 10 | Finish checklist (`#finish`) | Blocks sign until **property address** set on cover | **Pass** | |
| 11 | Set address + sign | Signature recorded; hash pinned in inventory | **Pass** | `acknowledgements.jsonl` chain |
| 12 | Final issue (`/issue`) | Clean sendable document; address on cover | **Pass** | |
| 13 | Report round-trip | Report → *Continue in Review* → Overview (same tab) | **Pass** (fixed 9 Jul) | F2: docket forces `#overview` |
| 14 | PDF | PDF exists at build completion **or** exports from Finish without hunting | **Pass** (fallback) | F1: browser Print → Save as PDF via final issue when WeasyPrint missing |
| 15 | Mobile (390px) | Overview 2-col grid; Finish reachable; no broken layout | **Pass** | |
| 16 | Tenant link | Finish **Create tenant link** mints URL; tenant can comment; countersign works | **Pass** | Persisted in `share.json` (F4 fixed) |

*Full friction detail: [`24-friction-log-2026-07-08.md`](24-friction-log-2026-07-08.md)*

---

## Friction log (fill in during the run)

Use one row per issue — even small ones. Tag severity so Phase 2 can prioritise.

| ID | Step | Severity | What happened | Expected | Fix / ticket |
|---|---|---|---|---|---|
| F1 | 14 | major | WeasyPrint `libgobject-2.0-0` missing on Windows; no PDF at build or Finish | One-click PDF | Windows deps or browser-print fallback |
| F2 | 13 | minor | *Continue in Review* → `#items` not `#overview` | Overview round-trip | Fix deep-link in report template/JS |
| F3 | 4 | minor | ~16 min build on 13 min video | Acceptable latency | ETA in progress UI (Phase 2) |
| F4 | 16 | minor | Tenant token invalid after server restart | Stable share link | **Fixed:** token persisted in `share.json`; Finish mints link |
| F5 | 11 | nit | Duplicate landlord sign entries | Single sign | Debounce sign action |
| F6 | 10 | nit | Sign allowed with 180/186 unreviewed | Optional hard gate | Product decision |

**Severity guide:**

- **blocker** — cannot complete the journey
- **major** — completes with workaround; erodes trust (“I'd pay £165 instead”)
- **minor** — annoying but survivable
- **nit** — polish only

---

## Success criteria (Phase 1 exit)

From docs/00 — check when the run finishes:

- [x] Steps 1–14 pass without a **blocker** (step 14 major — HTML workaround OK)
- [x] Friction log committed ([`24-friction-log-2026-07-08.md`](24-friction-log-2026-07-08.md))
- [x] Every **blocker** and **major** has a fix plan or explicit deferral with reason (F1: Windows PDF)
- [x] Build used gemini default (`describe_backend`: `openai (gemini-3.5-flash)`)
- [x] Signed HTML issue sendable to a tenant/agent (`/issue`; PDF pending F1)

When all boxes are checked, Phase 1 is **done** and Phase 2 (E2/E8/E10 wiring)
starts.

**8 Jul 2026 run:** Journey complete; **conditional** Phase 1 exit — F1 (Windows PDF)
must be fixed before claiming PDF delivery on Windows. See friction log.

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
