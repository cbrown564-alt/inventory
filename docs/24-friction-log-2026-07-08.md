# First-tester friction log — 8 Jul 2026

*Run executed against `capture/IMG_5512.MOV` (~13 min, 1.3 GB). Server:
`homeinventory review capture/ -o report/ --share`. Tester: agent-assisted;
property address sanitised.*

---

## Run summary

| Metric | Value |
|---|---|
| Build duration | ~16 min (15:12 → 15:28 UTC) |
| Rooms / items / frames | 10 / 186 / 92 analysed, 38 shown |
| Describe backend | `openai (gemini-3.5-flash)` ✓ |
| Items confirmed | 6 / 186 |
| Signatures | Landlord + tenant countersign on record |
| PDF | **Not generated** (Windows WeasyPrint deps missing) |
| HTML issue | Sendable at `/issue` |

---

## Test script results

| # | Step | Pass? | Friction notes |
|---|---|---|---|
| 1 | Open app (no prior build) | **Pass** | Start page: filming guide, drop zone, plain-language spend copy |
| 2 | Drop walkthrough video | **Pass** | `IMG_5512.MOV` shown with size; build enabled |
| 3 | Confirm build | **Pass** | Cost dialog; accepted with `yes` |
| 4 | Wait for build | **Pass** | Staged progress + room chips after segmentation; ~16 min wait |
| 5 | Build completes | **Pass** | Landed on `/#overview` |
| 6 | Overview | **Pass** | Stats bar, room gallery, *Start review* CTA |
| 7 | Open one room card | **Pass** | Hero frames, rename/merge tools reachable |
| 8 | *Start review* | **Pass** | Least-confident queue; *Play this moment* per item |
| 9 | Confirm 3–5 items | **Pass** | 6 confirmed; overview meter updated (5→6) |
| 10 | Finish checklist | **Pass** | Blocks sign until address set (verified earlier in run) |
| 11 | Set address + sign | **Pass** | SHA-256 chain in `acknowledgements.jsonl`; hash pinned on items |
| 12 | Final issue (`/issue`) | **Pass** | Clean sendable doc; address on cover |
| 13 | Report round-trip | **Partial** | *Continue in Review* returns to review tab but lands on `#items`, not `#overview` |
| 14 | PDF | **Fail** | No PDF at build; Export PDF on Finish silent-fails (WeasyPrint) |
| 15 | Mobile (390px) | **Pass** | 2-col room grid; Finish reachable; no broken layout |
| 16 | Tenant link | **Pass** | Comment + countersign work when server started with `--share` |

---

## Friction log

| ID | Step | Severity | What happened | Expected | Fix / ticket |
|---|---|---|---|---|---|
| F1 | 14 | **major** | Build log: `PDF generation unavailable (cannot load library 'libgobject-2.0-0')`. Finish checklist shows `! PDF generated`. Export PDF button does nothing useful. | PDF at build completion or one-click export from Finish | **Fixed (9 Jul):** browser-print fallback via final issue when WeasyPrint unavailable (`pdf_meta.weasyprint_available`, Finish CTA). Native WeasyPrint still preferred when installed. |
| F2 | 13 | minor | Report → *Continue in Review* deep-links to `#items` (last item) not `#overview` | Land on Overview in same tab | **Fixed (9 Jul):** report docket click handler `location.assign(…#overview)` clears stale item hashes |
| F3 | 4 | minor | ~16 min build on 13 min video with no mid-build cancel/back | Acceptable for v1 but long; progress bar helps | **Ticketed:** post-v1 ETA / cancel; not a v1 ship blocker |
| F4 | 16 | minor | Tenant token is in-memory; restarting server without `--share` or with new PID invalidates saved link (403) | Link survives for session handoff | **Ticketed:** persist token in `project.json` or Finish regen warning |
| F5 | 11 | nit | Landlord signed twice (duplicate entries in `acknowledgements.jsonl`) | Single sign event | **Fixed earlier:** client `inFlight` guard + server `_already_signed` no-op |
| F6 | 10 | nit | Finish allows sign with 180/186 items unreviewed (warning only) | Stricter gate optional | **Ticketed / product decision:** keep warning (peace-of-mind over hard block for v1) |

---

## Phase 1 exit gate (docs/00)

- [x] Steps 1–14 pass without a **blocker** (step 14 is major, not blocker — HTML issue sendable)
- [x] Friction log committed (this file)
- [x] Every **blocker** and **major** has a fix plan (F1: Windows PDF deps or print fallback)
- [x] Build used gemini default (`describe_backend`: `openai (gemini-3.5-flash)`)
- [x] Signed HTML issue sendable to tenant/agent (`/issue`)
- [ ] **PDF delivery on Windows** — deferred fix required before calling v1 ship on Windows

**Verdict:** Journey is **complete end-to-end** with one **major** friction (PDF). Phase 1 exit is **conditional** — approve for HTML-first delivery; block Windows PDF claim until F1 resolved.

---

## Evidence

- Desktop Overview: captured during run
- Mobile Overview (390px): captured during run
- `report/acknowledgements.jsonl`: build, review, sign, tenant comment + countersign chain
- `report/inventory.json`: `describe_backend`, `signatures[]`
- Server: `http://127.0.0.1:8484/` (review), tenant link tested with fresh `--share` token
