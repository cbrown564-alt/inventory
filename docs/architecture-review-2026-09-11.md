# Home Inventory: architecture, documentation and product review

11 September 2026 · Reviewed main at `1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b`

> Status: dated architecture review and recommendations, not an adopted implementation plan. Findings refer to the commit above; subsequent repository changes have not been re-reviewed here. Existing canonical documents remain authoritative until proposals are adopted.

The project has a valuable core, but its active surface is much larger than its primary job. Simplification should preserve evidence and correction semantics while reducing product commitments, implicit model behaviour, and overlapping documentation.

This review inspected the repository tree and 31 selected source, documentation, configuration and test files. It includes a local reproduction of an evaluation defect. It is a static architecture review, not a full test run, security audit or visual usability assessment. No repository files were changed and no model inference was run. Historical results below are repository records, not newly reproduced model benchmarks.

## 1. The product decision that should lead the architecture

The proposed purpose is: **turn a person's property photos or video into an understandable, evidence-backed condition record with as little capture and review effort as possible.**

The first useful result should arrive before the user agrees to work through a queue. Upload, receive a readable result, inspect issues, optionally correct or provide missing evidence, export or share. The existing signing and tenant workflows can remain available without defining every session.

There are two costs to minimise: the effort required to create the record and the effort required to understand or rely on it. A cheaper model that creates more corrections may be the more expensive product. A shorter report that hides omissions may be faster to read but less useful.

Use total active human time as the primary operational measure: capture + upload interaction + corrections + recapture + recipient comprehension. Track elapsed processing time and monetary cost separately. Pair time with material-defect recall, unsupported claims, missing coverage and evidence correctness; speed alone cannot establish success.

### Demo and service are different delivery modes

| Mode | Intended behaviour |
|---|---|
| Public demonstration | A curated example with precomputed outputs and inspectable evidence; no installation required. |
| Developer tool | CLI/local server for replay, debugging, tests, private experiments and reproducible model runs. |
| Customer service | Mobile-friendly upload, durable processing, return later, results, optional correction, download/share. |

Cloud processing is the practical proposed direction. A phone can capture and display evidence without running the VLM locally. Native capture assistance may eventually help, but a native application is not a prerequisite for the core service.

Do not simply expose the current local server to the internet. Its loopback/owner-pairing access model, directory state and daemon-thread jobs serve the local demo assumptions. A hosted version needs authenticated project ownership, private asset access, durable job status and restartable execution, plus explicit retention/deletion behaviour. Keep this as one application and one worker sharing the same Python package; no microservice programme is needed. See [review.py](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/review.py) and [webbase.py](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/webbase.py).

## 2. What deserves preservation

| Existing element | Why it is useful | Recommended treatment |
|---|---|---|
| `Inventory → Room → Item / Photo` | Common representation for reports and evaluation | Preserve, then add explicit schema/version and finding types incrementally. |
| `run_build(BuildOptions)` | CLI and web already share orchestration | Keep as the application entry point; separate stage configuration from CLI argument parsing. |
| `DescribeBackend` protocol | Small, useful room-description contract | Preserve, split providers from task prompts and routing policy. |
| Evidence hashes, source-video references, rejected claims, human edits | Support traceability and safe regeneration | Treat as invariants during every refactor. |
| Description versus presentation image pools | Models need broad evidence; readers need selective views | Preserve this distinction, particularly for compact reporting. |
| Optional detection/ML dependencies | Keeps the base installation relatively light | Preserve; a detector should earn inclusion through measured benefit. |
| Use-case profiles | Useful separation of tenancy vocabulary and presentation rules | Keep the abstraction, reduce exposed scope to the primary inventory task. |
| Offline regression fixtures and tests | Enable change without paid inference | Keep small replayable fixtures in core CI. |

Sources: [schema](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/schema.py), [pipeline](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/pipeline.py), [backend interface](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/describe.py), [use-case profile](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/usecases/base.py), [dependencies](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/pyproject.toml).

The problem is not an absence of abstractions. It is that the project has accumulated too many active concerns around them. The tree contains 33 Python files under homeinventory, 85 under evals, 39 under tests, and 41 top-level Markdown documents under docs. All 2,026 tracked blobs total approximately 1.19 GB by tree-reported size; this is not a measured clone/download size. Research data is a substantial part of the repository surface.

## 3. Concrete architecture findings

### A. The review module owns too much

`review.py` is 1,883 lines. It combines project/session persistence, sharing and pairing tokens, room/item edits, evidence attachment, build orchestration, PDF generation, subprocess-based comparison and HTTP routing. The review template is about 213 KB. Size alone is not the fault; these responsibilities change for different reasons.

Extract a small application service for create/upload/build/correct/render; move storage behind explicit methods; leave HTTP handlers translating requests and responses. Separate browser behaviour, styling and markup where the template actually mixes responsibilities. Reuse the existing design rather than rewriting the frontend merely to adopt a new framework.

### B. Model configuration exists, but is dispersed and implicit

`describe.py` contains several providers, encoding, output parsing, schema construction and a tiered policy. The UI mirrors provider defaults in `_BACKEND_DEFAULT_MODEL`. Segmentation, cover reranking and description make their own model choices. The backend named `openai` defaults to Gemini.

Introduce one model registry with provider, endpoint, credential environment-variable name, model identifier, supported modalities, output mode, limits, timeout and dated prices. Use explicit task profiles for description, segmentation and optional verification. A transport protocol is not a provider identity.

Keep one internal validated result contract while allowing providers to implement different wire formats. JSON-object support must not be assumed equivalent to strict JSON-schema support.

### C. Cache identity is insufficient for experiments

Room checkpoints bind evidence hashes, backend, model and use case, but not prompt/schema versions or all relevant inference/preprocessing settings. Cover-cache keys bind room and image hashes but omit model/prompt identity and sort image hashes, losing order.

Changing a prompt or model policy can therefore reuse an older result when resuming. Use a fingerprint over the effective task, provider/model, prompt, schema, inference settings and ordered evidence/derivation inputs. Record that same fingerprint with evaluation results. See [checkpoint identity](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/pipeline.py) and [cover cache](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/ml_cover.py).

### D. Tiered verification cannot establish completeness

The implemented tiered backend escalates existing draft items when confidence is low, grades are missing or defects are present. It instructs the expert to return only those named items. An item missed by the draft cannot be recovered by this verification route. When the expert is unavailable, draft items are retained.

This may reduce errors on proposed items; it is not a completeness check. Evaluate it as a distinct policy. For autonomous delivery, expose skipped verification and missing coverage as structured status, rather than relying on logs. Avoid using model-reported confidence as if it were a calibrated probability. See [TieredBackend](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/describe.py).

### E. Schema tolerance can conceal incompatible data

`Inventory.from_json` silently drops unknown fields and normalises grades. This is convenient for development but risks losing newly introduced evidence or review fields on load/save. There is a tool version, but no explicit schema migration path in the inspected model.

Add a schema version and deliberate migrations. Validate provider results at the boundary. Evolve material findings into typed records with stable IDs, item/room association, evidence references, observation text, uncertainty and review state. Preserve existing JSON through migration; avoid a wholesale domain rewrite.

## 4. Evaluation: repair this before choosing the next default

The existing scorer has issues beyond low image resolution.

| Finding in evals/run_eval.py | Consequence | Required change |
|---|---|---|
| Gold defects are counted only after the parent item matches | Defects on missed items disappear from the denominator | Count every eligible gold defect, including those whose item is missed. |
| Any one gold word longer than three characters appearing in description/defect text can earn credit | “Clean tabletop” can match “scratch on tabletop” | Match defect identity, location and polarity; adjudicate ambiguous matches. |
| Predictions are counted only while iterating gold rooms | Extra predicted rooms escape the hallucination count | Score unmatched rooms and their predictions explicitly. |
| Unmatched names stand in for hallucination | Incomplete labels or naming/granularity differences can look like invented content | Call it unmatched-prediction rate until evidence adjudication establishes falsity. |
| Condition agreement is measured only on matched, graded pairs | Strong conditional grading can coexist with poor completeness | Publish denominators, grading coverage and end-to-end quality together. |

**Executed reproduction:** two gold items, one missed entirely; both have defects. The sole prediction says “Clean tabletop” and reports no defects. The current scorer returned **50% item recall and 100% defect recall**. This is direct evidence that the defect score does not represent the intended end-to-end measure.

Keep the old scorer version and old results for reproducibility. Create corrected metrics, regression cases for these failure modes, then rescore saved outputs. Do not silently overwrite historical tables. Existing CI scores stored reference outputs and exercises an offline build; that is useful software regression coverage, not fresh model validation. Sources: [scorer](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/evals/run_eval.py), [CI gate](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/evals/ci_gate.py).

### What the stored model comparisons actually say

| Recorded run | Notable recall | Reported hallucination | Condition exact |
|---|---:|---:|---:|
| Claude v4 prompt | 88.0% | 2.8% | 93.2% |
| GPT-5.4-mini v4 prompt | 90.7% | 14.7% | 83.1% |
| Gemini 3.5 Flash | 82.7% | 5.0% | 72.0% |
| Local Gemma4:26b | 72.0% | 23.8% | 91.7% |
| Local Qwen9b-v2 | 72.0% | 25.7% | 75.0% |

These are historical, scorer-dependent results on one low-resolution professional-report fixture. They do not establish general model rankings or readiness for autonomous output. The local findings answer the recollection question: local models were tested and produced useful content, but completeness and unsupported output remained significant problems. Other local probes encountered malformed output, repetition, insufficient schema performance or memory/latency limits. [Recorded comparison](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/docs/04-backend-comparison.md).

Retain three evidence tracks:

1. **Professional-PDF regression:** formatting familiarity, legacy comparisons and low-resolution robustness. External origin does not make it representative production validation.
2. **Original-media evaluation:** independently labelled native photos/video, assessed both after preprocessing and end to end. Keep unobserved physical defects distinct from defects visible in supplied evidence.
3. **Synthetic probes:** targeted clean/defect pairs, ambiguity, occlusion and known failure modes. Useful controlled tests, not a substitute for real-property validation.

The repository already acknowledges the PDF limitation and proposes a native-resolution gate. Preserve that reasoning. However, high-resolution source files alone are insufficient: inspect what resizing and selection actually send to the model. The current common encoder defaults to a maximum dimension of 1,568 pixels. [Quality gate](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/docs/30-phase4-quality-gate.md), [encoder](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/homeinventory/describe.py).

## 5. DeepSeek evaluation

Official documentation checked on 11 September 2026 identifies **DeepSeek-V4.1-Flash**, served as `deepseek-flash`, with vision support and an OpenAI-compatible endpoint. It lists peak uncached input/output prices of $0.30/$1.20 per million tokens and off-peak prices at half those rates. This establishes a reasonable candidate, not its performance on this task. [Official model/pricing page](https://api-docs.deepseek.com/quick_start/pricing/).

The existing adapter unconditionally sends strict `json_schema`. DeepSeek's JSON guide documents `json_object`; compatibility should be probed rather than assumed. Its dedicated vision-guide page could not be fetched during this review, so image limits and payload particulars remain to verify. [JSON guide](https://api-docs.deepseek.com/guides/json_mode/).

Recommended bounded sequence: register provider and credentials; check image input and output contract on a tiny non-private fixture; validate empty/truncated/malformed responses; run the corrected legacy and native-media suites; compare accuracy, unsupported defects, evidence grounding, latency, actual tokens/cost and human corrections with Gemini. Fix preprocessing and prompt versions for the comparison. Evaluate thinking settings separately if supported. No inference was executed during this review, so no DeepSeek quality result is claimed.

## 6. Photos and video should converge on evidence

The user should not choose a technical pipeline. Accept photos and videos in the same project. Photos enter as evidence assets; video yields derived frames with source timestamps. Both converge into room evidence bundles for description and reporting. Preserve every original and link selected views to it.

Do not silently discard a supplied modality. Ambiguous room assignment should generate a small confirmation request. Video-plus-detail-photos is a reasonable supported input, while the recommended capture instruction remains an experimental question.

The existing capture-strategy document already frames the right trade-off: capture time versus later repairs. Its six-arm design is more than needed for an initial decision. Start with ordinary video, light room photos and a mixed route on the same properties; expand only to explain a meaningful difference. Include first-time target users early for usability evidence, rather than validating only the owner's technique. [Capture experiment](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/docs/26-capture-strategy-experiment.md).

## 7. Reporting and autonomy

Generate three views from the same evidence and findings: the web overview, a compact visual PDF and the complete conventional schedule. Different views must agree on finding IDs, wording, evidence, uncertainty and review state.

A suggested compact PDF for an ordinary property is 6–10 pages: property/coverage summary; room map or room-card index; grouped issue galleries with wide context plus close-up; wear observations and coverage gaps; brief provenance/review-status information. Treat ten pages as a default design budget, not a reason to hide an eleventh page of material findings. Keep the full schedule as the comprehensive export.

For a reliable existing floor plan, overlay room-level counts and grounded findings. Without one, use an explicitly schematic room map or room cards. Do not invent geometry, room adjacency or exact defect coordinates from arbitrary photographs. Accurate reconstruction is a separate acquisition/computer-vision problem.

Use one overview with issue, wear and observed-no-issue filters rather than three repeated floor plans. Add a fourth state: **not observed or uncertain**. “No issue identified in supplied evidence” is different from “everything is fine.” Do not label uncertainty green. Keep visual wear observations separate from conclusions about responsibility.

Offer delivery/review choices without forking the pipeline:

| Mode | Experience | Status |
|---|---|---|
| Automatic | Immediate report; gaps and uncertain observations visible | AI-generated, unreviewed |
| Focused review | Only material issues, ambiguous evidence and gaps prioritised | Explicitly partially/human reviewed |
| Full review | Every entry inspectable and confirmable; existing formal workflow available | Review scope recorded |

Generate unreviewed outputs without pretending a human approved them. Autonomy can mean completing the report with uncertainty, not claiming certainty about everything. Operator-assisted review is a possible service tier whose labour must be counted, not hidden.

## 8. Documentation consolidation

There is already an authority map. Adding another permanent north-star document would repeat the problem. Replace the active owners in a coordinated change.

Concrete conflicts include: docs/04 says Claude remains the description default and lists gpt-4.1-mini for the compatible backend, while code, README and docs/00 select Gemini 3.5 Flash; docs/00's success table still names native-resolution InventoryFlex while docs/30 explains that originals are unavailable; the active video-first journey coexists with an unresolved capture-strategy decision. The index requires readers to navigate many active documents and partially superseded sections. [Index](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/docs/README.md), [north star](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/docs/00-north-star.md), [README](https://github.com/cbrown564-alt/inventory/blob/1f73dcadd80b220a6f8eb01c5cf6b532dd832f5b/README.md).

| Canonical document | Sole responsibility |
|---|---|
| README.md | Purpose, current status, example result, developer quick start, links |
| PRODUCT.md | User, desired journey, outputs, review choices, scope and open decisions |
| docs/architecture.md | Modules, data contract, runtime boundaries and invariants |
| docs/evaluation.md | Datasets, metrics, failure definitions, reproducible commands and evidence limits |
| docs/development.md | Setup, local demo, tests, adding providers and operational development |
| docs/decisions/ | Short dated decisions with supersession links |

Retain DESIGN.md as the design reference if it remains useful; it should not own roadmap or model policy. Put result tables in generated run summaries backed by manifests. Move old milestone narratives, abandoned capture/pairing work and broad ML plans into an indexed archive or research area. Keep only a short active research list tied to a current product decision. Bulk data belongs outside the default code checkout with small manifests and permitted reproducible fixtures retained.

Archive with redirects and preserved history; do not delete evidence merely to reduce file count. Update AGENTS.md and docs/README.md alongside renamed owners so future work follows the new map.

## 9. Proposed module boundaries and sequence

Use one repository, one product package and one evaluation entry point. Suggested responsibilities are domain; capture; providers; analysis; reporting; application services; web; and developer CLI. These are dependency boundaries, not instructions to create an enterprise folder hierarchy.

Evaluations may import product contracts and task services; the product should not import evaluation machinery. Experimental detectors, training, synthetic generation and acoustic/native-app research can remain in research with small documented promotion criteria.

**First change: restore trustworthy decisions.** Correct scorer semantics, add focused regression cases, version metrics, rescore saved outputs, reconcile actual defaults, and fingerprint cached computations. Exit: every displayed model result has a reproducible meaning and source.

**Second change: establish the product contract.** Update PRODUCT and the authority map around upload-to-useful-report; demote local installation to developer/demo packaging; keep capture modality and optional floor-plan support explicitly open. Exit: one coherent current story.

**Third change: simplify code without changing results.** Extract providers/configuration, thin HTTP handlers, centralise application operations and preserve the existing evidence schema through migrations. Verify human-edit preservation, evidence IDs, invalidated attestations after relevant edits, cache invalidation and equivalent exports. Exit: existing fixtures replay with intentional, explained differences only.

**Fourth change: demonstrate the intended experience.** Build one hosted upload→processing→visual report slice with durable jobs and optional focused review, using the existing build service. Produce compact and full exports from the same record. Exit: a first-time user can finish without CLI setup.

**Fifth change: measure what to promote.** Compare capture instructions, Gemini versus DeepSeek, direct versus tiered description, and compact versus full report comprehension. Exit: decisions reflect total human effort and trustworthy results, not model novelty or sunk development cost.

Do not make floor-plan reconstruction, detector fine-tuning, synthetic-data expansion or native mobile development prerequisites for the first useful service. Preserve these experiments as optional work, with a specific measurable product question required before reactivation.

