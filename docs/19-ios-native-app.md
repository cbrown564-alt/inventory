# 19 — Pragmatic iOS path: native capture, hybrid intelligence

*5 Jul 2026. Architecture plan for a native iOS companion to the
video-first web product. Predecessors: docs/01 (pipeline), docs/04
(describe quality bar), docs/05 (Level 4 deferred), docs/09 (guided capture
retired), docs/11 (segmentation spike), docs/12 (plan of record),
docs/15 (on-device curation). This doc does **not** supersede docs/12 — it
records how an iOS app fits the existing journey without pretending
phone-only VLMs are ready for signed output.*

## The question this answers

Apple and Android already demonstrate strong on-device computer vision.
Apple's 2025–2026 stack (Foundation Models framework, Core AI, multimodal
prompts, SAM3, Private Cloud Compute) makes on-device AI integration
dramatically easier than rolling your own. **What stops us doing
everything on device?**

Not object detection. The blocker is **clerk-grade vision-language
reasoning over hundreds of walkthrough frames** — condition grades, defect
localisation, low hallucination — at the quality bar measured in
docs/04. Even a 26B MoE open-weight model on a desktop (gemma4:26b)
hallucinates at 23.8% vs claude's 2.8%. Phone-viable models are far
smaller.

The pragmatic path is therefore **tiered intelligence**: native iOS owns
capture, evidence custody, detector coverage, and review; cloud or Apple
PCC owns describe/segment until on-device VLMs pass the same eval gate.

## Product goal

A native iOS app that makes the primary journey in docs/12 **faster and
more trustworthy on a phone** than the mobile browser:

1. Film one continuous walkthrough with guided shot-list feedback.
2. Build a draft report (segment → describe → merge) with plain-language
   cost consent — no backend jargon exposed to the user.
3. Review, sign, and export the same artefacts the Python pipeline
   produces today: `inventory.json`, `manifest.json`, HTML/PDF.

The web review server (`homeinventory review`) remains the reference
implementation for review UX (docs/14) until the native review surface
reaches parity. The CLI stays plumbing.

## Design principles

| Principle | Rationale |
|---|---|
| **`inventory.json` is the contract** | Every surface — web, iOS, CLI, evals — reads/writes the same canonical schema (`schema.py`). No iOS-specific report format. |
| **Evidence never silently leaves the device without consent** | SHA-256 at capture; upload is explicit; hashes verifiable end-to-end (docs/10). |
| **On-device by default for narrow, low-risk tasks** | Detection, blur scoring, coverage checklist, OCR — fast, private, no hallucinated inventory items. |
| **Escalate for VLM quality, not convenience** | Segmentation and describe use API or Apple PCC until InventoryFlex eval clears them for signed output. |
| **Human attestation is non-negotiable** | AI drafts; reviewer signs. Provenance badges record which backend produced each item. |
| **Offline-capable capture, online-capable build** | Film and evidence vault work offline; build queues until connectivity (or user opts into on-device draft mode). |

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        iOS app (SwiftUI)                        │
├─────────────────────────────────────────────────────────────────┤
│  CAPTURE          │  EVIDENCE         │  BUILD              │ REVIEW │
│  · guided filming │  · SHA-256 vault  │  · job queue        │ · evidence │
│  · shot checklist │  · EXIF/timecode  │  · cost confirm     │   room UI  │
│  · coverage check │  · local cache    │  · progress         │ · sign     │
│    (detector)     │                   │                     │ · export   │
├───────────────────┴───────────────────┴─────────────────────┴────────┤
│                     ON-DEVICE (always)                              │
│  Vision · AVFoundation · Core ML detector · blur/IQA · OCR          │
├─────────────────────────────────────────────────────────────────────┤
│                     HYBRID (when quality requires)                  │
│  Segmentation ──► API (gemini-3.5-flash) or future on-device spike│
│  Describe     ──► API (claude) or Apple PCC / local draft tier      │
├─────────────────────────────────────────────────────────────────────┤
│                     SHARED BACKEND (phase 1)                          │
│  Optional: thin API wrapping existing Python pipeline               │
│  Alternative: iOS orchestrates cloud APIs directly (segment/describe)│
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              inventory.json + manifest.json + media
              (identical to `homeinventory build` output)
```

### Intelligence tiers

| Tier | Tasks | Platform / backend | Quality gate |
|---|---|---|---|
| **A — On-device, ship now** | Guided capture UI; per-room shot checklist; Laplacian blur gate; SHA-256 + EXIF; detector coverage diff (`check` equivalent); meter/OCR readout; hero-frame pre-filter (docs/15) | SwiftUI, AVFoundation, Vision, Core ML | No VLM — cannot hallucinate items |
| **B — On-device, spike first** | Room boundary hints from scene-change + IMU; SAM3 region proposals (Core AI); Foundation Models for text-only tasks (cover copy, compare summaries) | Core AI, Foundation Models | Measured against docs/11 segmentation fixture before replacing API |
| **C — Hybrid, production default** | Walkthrough segmentation; per-room describe | Cloud API (current defaults) or Apple Private Cloud Compute when available | docs/04: hallucination ≤5% for signed path; docs/11 for segmentation |
| **D — On-device describe, deferred** | Full VLM describe on phone | Core AI custom VLM (when phone-runnable models exist) | Must pass InventoryFlex eval at signed-report thresholds; same gate as docs/05 Level 4 |

## Mapping to the Python pipeline

| Python module | iOS equivalent | Tier | Notes |
|---|---|---|---|
| `ingest.py` | `CaptureKit` + `KeyframeExtractor` | A | AVAssetReader; reuse sharpness + frame-diff logic from docs/15; segment time bounds from `segments.json` |
| `integrity.py` | `EvidenceVault` | A | CryptoKit SHA-256; write `manifest.json` compatible with Python |
| `segment.py` | `SegmentationService` | C (B spike) | Phase 1: POST video/thumbnail strip to backend or call Gemini/Claude API from iOS with same prompt contract; cache `work/segments/<video>.json` |
| `detect.py` | `DetectorService` | A | Port YOLOE → Core ML **or** substitute Apple SAM3 + household prompt list; AGPL note if shipping YOLOE weights |
| `describe.py` | `DescribeService` | C | Same JSON schema + prompt v4 contract; claude default for signed; optional `draft` tier (gemini flash / local) with UI badge |
| `merge.py` | `MergeService` | C | Port de-dupe rules or run server-side in phase 1 |
| `curate.py` (planned) | `CurationService` | A | On-device IQA + MMR hero election; write `work/curation.json` |
| `report.py` | `ReportRenderer` | A/C | Phase 1: export bundle → open in web review or server-side PDF; phase 2: native PDF or WKWebView of generated HTML |
| `review` UI | `ReviewView` | A→B | Port evidence-room patterns from docs/14; share `inventory.json` review fields |

## Phased delivery

### Phase 0 — Spike & contract (1–2 weeks engineering time)

**Goal:** Prove the iOS app can produce byte-compatible evidence and call
one cloud describe path end-to-end.

- [ ] New Xcode project: SwiftUI, iOS 18+ (Foundation Models availability).
- [ ] Define `ProjectBundle` on-disk layout mirroring `capture/` +
  `report/work/` conventions so Python can consume iOS output and vice versa.
- [ ] `EvidenceVault`: record walkthrough to `.mov` (HEVC), compute SHA-256
  per file, extract capture timestamp, emit `manifest.json`.
- [ ] `KeyframeExtractor`: port ingest sharpness windowing; write frames to
  `work/frames/<Room>/` with `seen_at_s` provenance.
- [ ] Thin backend choice (pick one):
  - **0a.** iOS uploads bundle → existing Python `homeinventory build` on
    a linked server (fastest path to parity); or
  - **0b.** iOS calls segment + describe APIs directly with keys in
    Keychain (no server; user supplies API key once, docs/12 policy).
- [ ] Import resulting `inventory.json` into app; open web review via
  local network or Files export.
- [ ] **Acceptance:** one own-property walkthrough (docs/07 footage) builds
  a report indistinguishable from CLI output (same item count ± review
  noise, same manifest hashes, same segment boundaries within docs/11
  tolerance).

### Phase 1 — Native capture product (M6a)

**Goal:** Replace mobile-browser upload with a capture experience that
communicates elegance, simplicity, comprehensiveness (docs/15).

- [ ] **Filming guide** — room-by-room flow derived from `guide` checklist;
  spoken room names encouraged (helps segmentation); progress ring per room.
- [ ] **Shot-list checklist** — client-side tick tally (docs/09 pattern);
  no live VLM coach (docs/05 Level 4 stays parked).
- [ ] **Post-room coverage check** — on-device detector pass against
  expected categories (window, radiator, ceiling, …); surface gaps before
  the user leaves the room. Equivalent to `homeinventory check`.
- [ ] **Blur gate at capture** — warn on high motion / low Laplacian variance
  before ending a room clip (cheap, on-device).
- [ ] **Build queue** — plain-language cost confirm ("About 30p to draft
  this report"); staged progress matching docs/12 strings; background
  URLSession for upload + build.
- [ ] **Export** — share sheet with `inventory.pdf`, `inventory.json`,
  evidence manifest; AirDrop to Mac for `homeinventory review`.
- [ ] **Acceptance:** first-tester friction log (docs/03 open item) run
  entirely from iOS capture through signed PDF; no CLI required for the
  happy path.

### Phase 2 — On-device detection & curation (M6b)

**Goal:** Move tier-A ML onto the Neural Engine; reduce cloud payload.

- [ ] Core ML detector: convert or replace YOLOE; benchmark on InventoryFlex
  detect eval (`docs/13` metrics: recall on household items).
- [ ] SAM3 spike via Core AI: text-prompted regions for crops; compare crop
  quality vs YOLOE on own-property frames.
- [ ] Port `curate.py` scoring to Core ML / Accelerate (Laplacian + optional
  small IQA model); hero set 3–6 per room; cited frames immune (docs/15).
- [ ] Send detector hints + hero frames only to describe API (smaller
  uploads, same prompt contract).
- [ ] **Acceptance:** describe API cost per property drops measurably; detect
  recall within 5 pts of desktop YOLOE on fixture.

### Phase 3 — Native review & sign (M6c)

**Goal:** Evidence-room review on device (docs/14), no browser tab.

- [ ] Video-native stage: chaptered scrub bar from `segments.json`; *Play
  this moment* seeks AVPlayer to frame provenance timecode.
- [ ] Item queue: confidence-sorted, search, keyboard shortcuts on iPad,
  swipe actions on iPhone.
- [ ] Strike-through reject, defect boxes, add-missed-item, segment
  corrections (rename, merge neighbour) — same JSON fields as web.
- [ ] Sign: capture reviewer name + draw/sign; write `signatures` with
  `content_sha256()` matching `schema.py`.
- [ ] Tenant countersign via share link (opens web or universal link until
  native tenant app exists).
- [ ] **Acceptance:** review edits round-trip — iOS review → Python
  `render` → PDF matches web-reviewed output.

### Phase 4 — Hybrid intelligence experiments (M6d, ongoing)

**Goal:** Reduce cloud dependence where evals allow; do not regress quality.

- [ ] **Segmentation on-device spike:** scene-change + audio room-name
  hints + Foundation Models multimodal on thumbnail strip; score against
  docs/11 own-property fixture before any default switch.
- [ ] **Apple Foundation Models** for text-only tasks: compare-rubric
  summaries, cover-letter generation, reviewer note cleanup — no item
  invention.
- [ ] **Private Cloud Compute** path when Apple exposes inventory-scale
  multimodal describe with structured output; A/B vs claude on fixture.
- [ ] **Draft mode toggle:** "Quick draft (on-device / cheaper)" vs
  "Signed quality (cloud)" — explicit provenance badge per item.
- [ ] **Acceptance gate for promoting any on-device VLM to default:**
  InventoryFlex eval (`docs/04` table): hallucination ≤5%, notable recall
  ≥90%, condition-exact ≥70%, defect recall ≥75%.

## Data contract & sync

### On-disk bundle (compatible with Python)

```
Project/
  capture/
    walkthrough.mov          # or per-room clips if user re-records
  report/
    work/
      segments/walkthrough.json
      frames/<Room>/*.jpg
      crops/…
      curation.json          # when curate lands
    inventory.json           # canonical
    manifest.json
    inventory.html           # optional until native render
    inventory.pdf
```

### Review state

All review mutations (`reviewed`, `rejected`, `rejected_defects`,
`defect_regions`, `comments`, `signatures`) use the same schema as
`schema.py`. iOS writes JSON; Python `render` and `build --from-json`
consume it without migration.

### Sync options (phase 1 → later)

| Mode | When | Mechanism |
|---|---|---|
| **Export-only** | Phase 0–1 | Files / AirDrop / iCloud Drive; user opens on Mac |
| **Paired server** | Phase 1 | iOS uploads bundle to `homeinventory review` on LAN or hosted |
| **Cloud project** | Later milestone | Account-backed sync; out of scope until docs/12 hosted-login policy |

## Apple platform mapping (2026)

| Need | Apple API | Our use |
|---|---|---|
| Camera + stabilisation | AVFoundation, Cinematic mode optional | Walkthrough capture |
| On-device OCR | Vision `RecognizeTextRequest` | Meters, serial plates |
| Object / region detection | Core ML custom model; Core AI SAM3 | Detector tier A; crop proposals |
| Small language tasks | Foundation Models `LanguageModelSession` | Text-only helpers, not describe |
| Custom open models | Core AI `CoreAILanguageModel` + `coreai-build` | Spike Qwen/SAM3; future describe candidates |
| Structured generation | `@Generable` (Foundation Models) | Only for simple sub-schemas until describe eval passes |
| Larger reasoning | `PrivateCloudComputeLanguageModel` | Segmentation/describe fallback with privacy story |
| Secure credentials | Keychain + `.env` parity | API keys configured once (docs/12) |

**Not in scope for v1:** Image Playground, Live Translation, or general
chatbot UX — the inventory clerk task is structured extraction, not
conversation.

## Explicit non-goals (v1)

- **Full on-device describe at signed-report quality** — blocked by
  docs/04 numbers; revisit when tier D clears eval.
- **Live VLM filming coach (Level 4)** — parked in docs/05; on-device
  checklist + detector diff only.
- **Resurrecting phone guided capture (docs/09 M5b)** — the retired
  per-photo web page; native app replaces it with video-first flow.
- **Hosted multi-tenant auth** — docs/12 deferral; iOS v1 is
  local-first / export.
- **C2PA / qualified e-signature** — deferred; SHA-256 + acknowledgement
  trail remain the evidence story.

## Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| YOLOE AGPL if commercialised | Licence exposure | Core ML retrain on permissive data; or SAM3/Core AI path; legal review before App Store |
| On-device model overconfidence | Bad coverage / false items | Tier A checklist cannot invent items; describe stays tier C until eval passes |
| Thermal throttling during build | Slow or failed on-phone inference | Keep heavy VLM off-device in v1; detector runs are short bursts |
| Schema drift iOS ↔ Python | Broken rebuild | `inventory.json` contract tests in CI; golden fixtures |
| API cost surprise | User trust | Plain-language confirm before spend (docs/12); draft tier labelled |
| Segmentation errors (open plan) | Wrong room assignment | Review UI segment corrections already specced (docs/12) |

## Dependencies on existing repo work

| Dependency | Status | Blocks |
|---|---|---|
| Video-first pipeline + segmentation | Shipped (docs/12) | iOS build orchestration |
| Describe prompt v4 + eval harness | Shipped (docs/04, docs/06) | Quality bar for any backend swap |
| Evidence-room review UX spec | Shipped (docs/14) | Native review parity |
| `curate.py` hero selection | Open (docs/15, docs/18) | iOS curation should mirror Python, not fork logic |
| First-tester friction log | Open (docs/03) | Phase 1 acceptance |
| Gemini describe eval | Open (docs/12) | Informs draft-tier default |

## Open questions

1. **Standalone iOS vs companion to Mac server?** Phase 0 should run both
   spikes (0a server-backed, 0b direct API) and pick based on first-tester
   network reality (letting agents often have patchy upload on-site).
2. **Minimum iOS version?** Foundation Models requires Apple Intelligence
   devices; define graceful degradation (capture + export only) for older
   phones.
3. **Per-room vs single walkthrough capture?** Product default stays single
   video (docs/12); app may offer per-room re-record without folder UX.
4. **PDF on device?** WKWebView print-to-PDF vs server WeasyPrint — v1 can
   defer native PDF if export-to-web-review is fast enough.
5. **When to revisit tier D?** Trigger: any phone-runnable VLM clears
   InventoryFlex signed gate, or Apple ships multimodal FM with documented
   vision evals comparable to our fixture.

## Success criteria (M6 complete)

- [ ] Primary journey (docs/12) completable on iPhone without CLI.
- [ ] Capture + evidence + coverage check run offline; build requires
  network or explicit draft mode.
- [ ] Output artefacts pass Python `render` / `compare` unchanged.
- [ ] Signed report path uses tier-C describe at docs/04 quality defaults.
- [ ] Review parity with web evidence-room (docs/14) for sign/export.
- [ ] Friction log from first-tester run (docs/03) addressed or ticketed.

## References

- [Apple Foundation Models framework](https://developer.apple.com/documentation/foundationmodels) — on-device LLM, guided generation, tool calling.
- [Core AI (WWDC26)](https://developer.apple.com/videos/play/wwdc2026/326/) — custom model compilation, SAM3, Qwen on Apple silicon.
- [Apple on-device foundation models research](https://machinelearning.apple.com/research/apple-foundation-models-2025-updates) — ~3B model scope and limits.
- Internal: docs/04 (quality bar), docs/05 (Level 4), docs/11 (segmentation), docs/12 (journey), docs/13 (detection), docs/15 (curation).
