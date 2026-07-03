# Research Brief: AI-Powered Property Inventory Tool for UK Tenancy Deposits

> Compiled 2026-06-10 from web research (sources linked inline).
> §3 updated later the same day with the current VLM landscape and first
> empirical results from real footage (see docs 04 and 05).

---

## 1. UK Tenancy Inventory / Check-in Report Standards

### What a TDS-valid inventory contains

The primary reference is the TDS "Guide to check-in and check-out reports, inventories and schedules of condition" ([TDS guide page](https://www.tenancydepositscheme.com/guides/a-guide-to-check-incheck-out-reports-inventories-and-schedules-of-condition/tds-guide-to-inventories-check-in-and-check-out-reports/), [PDF](https://www.tenancydepositscheme.com/wp-content/uploads/2021/10/TDS_Guide_to_Inventories_Check_in_and_Check_out_Reports.pdf), [TDS NI version](https://www.tdsnorthernireland.com/article/A-Guide-to-check-in-check-out-reports-inventories-schedules-of-condition)). Core elements of a professional report:

- **Room-by-room schedule of condition**: every room covered systematically — walls/décor, ceilings, flooring, doors, windows, fixtures and fittings, all contents, plus garden and outbuildings ([AIIC](https://theaiic.co.uk/)).
- **Per-item entries** with description, **condition**, and **cleanliness** recorded separately. TDS stresses condition ≠ cleanliness: "a check-in report that only considers condition does not establish the standard of cleanliness," leaving adjudicators unable to determine deterioration ([TDS via Inventory Hive guide](https://www.inventoryhive.co.uk/documents/guides/tds/inventory-reports-a-focus-on-cleaning.pdf)). Over **60% of TDS disputes involve cleaning**, so cleanliness baselines matter most.
- **Embedded, date/time-stamped photographs** tied to each entry (not a separate photo dump).
- **Signatures**: signed by (or on behalf of) landlord and tenant at check-in, with a tenant declaration and an opportunity to amend within a set window (commonly 7 days). Signed inventories at start and end are "the single most important document" ([NRLA on TDS lessons](https://www.nrla.org.uk/news/what-2025-taught-us-about-deposit-disputes), [mydeposits evidence guide](https://www.mydeposits.co.uk/content-hub/evidence-for-deposit-dispute/)).
- **Check-out report in comparative format** — same structure, item-by-item against check-in, noting changes attributable to damage vs fair wear and tear.
- Meter readings, keys, alarms/safety compliance items are standard inclusions ([AIIC](https://theaiic.co.uk/), [No Letting Go](https://nolettinggo.co.uk/services/check-out-reports/)).

### Grading vocabularies in practice

- **Condition**: UK clerks use ordinal scales along the lines of *New / As new / Good / Fair / Poor / Damaged*, with free-text qualifiers ("scuff marks to lower left," "chip to front edge"). Professional clerks use **standardised, unambiguous language** so there's no ambiguity between "good" and "fair" in a dispute ([Assist Inventories](https://assistinventories.co.uk/2026/03/12/how-an-inventory-report-protects-landlords-in-deposit-disputes/)).
- **Cleanliness**: graded explicitly as **"cleaned to a professional standard" / "cleaned to a good domestic standard" / "not cleaned"** ([mydeposits on professional vs domestic cleaning](https://www.mydeposits.co.uk/content-hub/what-is-the-difference-between-professional-and-domestic-cleaning/), [Dock Inventories](https://dockinventories.co.uk/services-inventory-check-in/)). TDS prefers **specific factual description over labels**: "small crumbs to base, slight grease marks to back of oven" beats "not clean."
- **Factual, impartial tone**: AIIC guidance — "clear, factual wording, no assumptions or subjective commentary; date and time-stamped photographs" ([AIIC](https://theaiic.co.uk/), [AIIC training](https://theaiic.co.uk/training/)).

### What holds up in adjudication

Adjudicators decide **on documents alone** — no visits, no interviews; "evidence you cannot produce might as well not exist" ([NRLA](https://www.nrla.org.uk/news/what-2025-taught-us-about-deposit-disputes)). They look for three things: (1) evidence of condition at **start and end**, (2) proof damage exceeds **fair wear and tear**, (3) costs that are **fair and proportionate** with no "betterment" (landlord can't end up better off). Persuasive evidence: time-stamped photos at both check-in and check-out, signed/dated reports, contractor invoices and quotes ([NRLA on redecoration evidence](https://www.nrla.org.uk/news/what-evidence-do-landlords-need-to-justify-redecoration-costs-at-the-end-of-a-tenancy), [Propertymark dos and don'ts](https://www.propertymark.co.uk/resource/dos-and-don-ts-of-deposit-protection.html), [TDS/Letting Agent Today](https://www.lettingagenttoday.co.uk/sponsored-content/2022/06/the-dos-and-donts-of-deposit-disputes/)). Undated photos carry far less weight.

### Market price point

Professional inventory + check-in typically costs **£100–£300** depending on size/furnishing; e.g. Dexters quotes inventory from £144 and check-in from £156; budget independents from ~£75 ([Dexters](https://www.dexters.co.uk/landlords/fee-structure), [Landlord Studio](https://www.landlordstudio.com/uk-blog/letting-agents-fees), [Daley Property Inventory](https://propertyinventory.org.uk/property-inventory-services-prices/)). The ~£165 target price is squarely in-market. Note: the Tenant Fees Act 2019 means landlords/agents, not tenants, bear this cost in England — the buyer is the landlord/agent.

---

## 2. YOLOE and Open-Vocabulary Detection

Source: [Ultralytics YOLOE docs](https://docs.ultralytics.com/models/yoloe/); paper: [YOLOE: Real-Time Seeing Anything, Wang et al. 2025, arXiv:2503.07465](https://arxiv.org/abs/2503.07465).

- **What it is**: YOLO extended with open-vocabulary detection **and instance segmentation**, with three modes: (1) **text prompts** (`model.set_classes(["sofa", "table lamp", ...])`), (2) **visual prompts** (detect things similar to a reference image/box, one-shot), (3) **prompt-free** — built-in vocabulary of **1,200+ categories** from LVIS + Objects365.
- **Models**: text/visual-prompt variants `yoloe-11s/m/l-seg`, `yoloe-v8s/m/l-seg`, and newer `yoloe-26n/s/m/l/x-seg`; prompt-free counterparts add `-pf` (e.g. `yoloe-11l-seg-pf.pt`). Usage is just `pip install -U ultralytics`, then `YOLOE("yoloe-11l-seg.pt")`.
- **Performance**: YOLOE-L ≈ **35.2% LVIS mAP / 52.6% COCO mAP at ~6.2 ms on a T4** (26.2M params) — ~+10 AP over YOLO-World-L at similar speed. Runs on a laptop GPU or even CPU at modest FPS; fine-tunable on consumer hardware (linear probing supported for small datasets).
- **Limitations** (relevant for indoor inventory): exported models become static (prompts baked in); visual prompting is Python-API only; **prompt-free vocab is fixed to LVIS/Objects365** — fine-grained categories ("Le Creuset casserole dish") need text prompts or fine-tuning. Generic open-vocab weaknesses: small/cluttered objects need high input resolution; long-tail/rare classes are weak; fine-grained sibling categories get confused ([survey](https://www.emergentmind.com/topics/open-vocabulary-object-detection), [OWL-ST, NeurIPS 2023](https://papers.neurips.cc/paper_files/paper/2023/file/e6d58fc68c0f3c36ae6e0e64478a69c0-Paper-Conference.pdf)).
- **Licensing — important**: Ultralytics code/weights are **AGPL-3.0**; commercial closed-source use (including SaaS) requires an [Ultralytics Enterprise License](https://www.ultralytics.com/license) ([license discussion](https://github.com/orgs/ultralytics/discussions/1260)). Fine for personal use; budget for a licence (or swap detectors) if this is ever productised.

### Alternatives

| Model | Strength | License |
|---|---|---|
| [YOLO-World](https://openaccess.thecvf.com/content/CVPR2024/papers/Cheng_YOLO-World_Real-Time_Open-Vocabulary_Object_Detection_CVPR_2024_paper.pdf) (Tencent) | Real-time, offline vocab embedding | GPL-3.0 |
| [Grounding DINO](https://roboflow.com/compare/grounding-dino-vs-owlv2) (IDEA Research) | Best accuracy, free-text phrases | **Apache-2.0** |
| [OWLv2](https://roboflow.com/compare/grounding-dino-vs-owlv2) (Google) | Strong rare-class detection, slower | **Apache-2.0** |
| SAM2 / [Grounded-SAM](https://playground.roboflow.com/models/idea-research/grounded-sam) (Meta/IDEA) | Promptable segmentation/video tracking | **Apache-2.0** |

Practical takeaway: Grounding DINO + SAM2 is the permissively-licensed accuracy stack; YOLOE is the fastest integrated option but carries AGPL/Enterprise-licence implications for a commercial product.

---

## 3. VLMs for Item Description and Condition Assessment

- **Open VLMs**: [Qwen2.5-VL](https://arxiv.org/pdf/2502.13923) (3B/7B/72B, [HF](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)) is the strongest open option for this use case: native-resolution dynamic ViT enables **fine-grained recognition, OCR (brand/model labels, serial plates), grounding (it outputs bounding boxes), and structured JSON output**. LLaVA and InternVL are alternatives; LLaVA-1.5-7B has been studied for damage assessment under quantization for edge deployment ([arXiv:2603.26770](https://arxiv.org/html/2603.26770v1)).

### June 2026 update — local VLM landscape (what the `local` backend targets)

The Qwen2.5-VL recommendation above is superseded. Current open multimodal
models on [Ollama](https://ollama.com/search?c=vision), sized for consumer
GPUs (our reference machine: RTX 4070 Laptop, 8 GB VRAM):

| Model | Q4 size | Notes |
|---|---|---|
| **qwen3.5:9b** | 6.6 GB | Current Qwen generation, natively multimodal; fits 8 GB VRAM with KV-cache headroom — **our `local` backend default** |
| [minicpm-v4.5:8b](https://ollama.com/library/minicpm-v4.5) | 6.1 GB | Vision specialist; OpenCompass 77.2, claims parity with Qwen2.5-VL-72B; strong OCR |
| gemma-4-12b (Q4) | 6.7 GB | Credible rival; borderline fit once vision overhead + context are loaded |
| qwen3-vl 2B–235B | varies | Previous Qwen VL line, superseded by qwen3.5 |

Delivery notes: Ollama's structured-output mode enforces the JSON schema via
llama.cpp grammar (validity guaranteed, unlike prompt-begging); on 8 GB cards
photos must go in small batches (≈6) to keep the KV cache resident — the
pipeline's merge pass de-duplicates across batches.

*July 2026 addendum*: empirical runs (docs/04) superseded the dense-model
table above. On the 8 GB reference card every dense VLM fails this pipeline —
the ≥9B models spill weights to system RAM and become timeout-bound
(~15 tok/s), while the ≤4B models that fit are too weak for the strict
structured-output contract (repetition loops, near-empty output, schema
drift). **Mixture-of-Experts sidesteps the ceiling**: `gemma4:26b` (18 GB Q4,
25.8B params, 8-of-128 experts active ≈ ~1.6B dense compute per token) keeps
only the active-expert pathway + KV cache in VRAM, rides 32 GB system RAM for
the weights, and at ~23 tok/s posts the best naming (97.4) and grading
(91.7 exact) of any backend including claude — the recommended
`--backend local` model where system RAM allows. `qwen3.5:9b` remains the
lighter default where RAM is also constrained.

### June 2026 update — cheap closed VLMs and first empirical results

Pricing per 1M tokens in/out ([OpenAI](https://openai.com/api/pricing/),
[Gemini](https://ai.google.dev/gemini-api/docs/pricing)); a 19-frame room is
~25K input + 3–4K output tokens, so all of these cost pennies per property:

| Model | Price | First-footage result (docs/04) |
|---|---|---|
| gemini-3.1-flash-lite | $0.25/$1.50 | 10 items; differentiated grades; **its one defect claim was a hallucination** (sticker read as a scratch) |
| gpt-4.1-mini | $0.40/$1.60 | 17 items; flat grading — all "good", zero defects |
| gpt-5.4-mini | $0.75/$4.50 | 28 items; structural coverage, clerk register, real localized defect — **provisional pick** |
| claude-haiku-4-5 | $1.00/$5.00 | not yet run on this footage |

Empirical confirmations of this brief's predictions (single room, informal —
see docs/04 for caveats): **recall and grading discipline are independent
skills** (a model can list well and grade lazily); **defect hallucination is
real and the worst failure mode** for documents-only adjudication where the
landlord bears the burden of proof — confirming the "never let it invent
defects" design rule and motivating the claim-next-to-evidence review UX
(docs/05). One protocol covers all closed providers: the OpenAI-compatible
chat-completions API (OpenAI native, Gemini via its
[compatibility endpoint](https://ai.google.dev/gemini-api/docs/openai), and
Ollama locally), which is how the `openai` backend reaches them all.
- **Condition-assessment literature**: most academic work is infrastructure-flavoured but directly analogous — benchmarking VLMs on **distress identification, severity grading, and maintenance estimation** for pavements ([PLOS One benchmark](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0340380), [arXiv:2604.08212](https://arxiv.org/html/2604.08212)) and road damage ([RoadBench, arXiv:2507.17353](https://arxiv.org/pdf/2507.17353)). Consistent findings: VLMs describe visible defects and rank severity coarsely well, are weaker at calibrated fine-grained grading; explicit rubrics/few-shot exemplars materially help; hallucination of absent defects is a known risk.
- **Industry practice**: insurance claims is the mature commercial domain — CV/VLM damage triage from photos and walkaround videos ([Clarifai](https://www.clarifai.com/solutions/ai-in-insurance), [SOSA](https://www.sosa.co/blog/why-damage-assessment-is-the-choke-point-in-claims), vehicle grading e.g. Ravin AI ([overview](https://binariks.com/blog/ai-car-damage-detection/))). For general household goods there is **no dominant product** — a gap.
- **Design implication**: detector (crop/ground) → VLM (name, attributes, condition against an explicit written rubric) → constrained output in the UK grading vocabulary is the state of practice. Force the VLM to grade against the rubric; never let it invent defects.

---

## 4. Existing Products and Gaps

### Home-inventory apps (insurance-oriented)

- **[HomeZada](https://www.homezada.com/press/homezada-launches-home-inventory-video-recognition-ai)**: closest to "video walkthrough → items" — record 10–15 videos per room, **video-recognition AI detects furniture/electronics/appliances**, user confirms; from $9.99/mo. No condition grading, no tenancy/legal report output.
- **[Encircle](https://www.smarthomeadmin.com/blog/ai-home-inventory-apps/)**: professional claims/restoration documentation; AI for claims workflows, not consumer condition grading.
- **[Sortly](https://realestateledger.io/comparisons/best-home-inventory-app)** / **Itemtopia**: visual inventory + QR/barcode tracking; minimal AI detection ([roundup](https://homyscan.com/blog/best-home-inventory-apps/)).

### Lettings inspection tools (UK)

- **[Inventory Hive](https://www.inventoryhive.co.uk/)**: UK market leader (NRLA/Propertymark partner); paperless inventories, comparative check-outs, 360° tours. Its AI is limited (e.g. meter-reading image recognition) — item-by-item condition recording is still manual.
- **[RentCheck](https://www.getrentcheck.com/)** (US): resident-led guided inspections with time-stamped photos; "AI damage detection" only triages/prioritises review. US-market, room-level, not a TDS-style itemised schedule.
- **Google Video Intelligence**: generic label detection/object tracking at ~$0.10–$0.15/min after free tier ([pricing](https://cloud.google.com/video-intelligence/pricing)); vocabulary too coarse (no fine-grained household classes, no condition) — viable only as a cheap pre-pass, not as the core detector. This rules it out as the backbone for this project.

### Gaps (the opportunity)

1. **No product combines** auto item detection from photos/video + per-item **condition/cleanliness grading in UK inventory vocabulary** + TDS-format PDF output. HomeZada detects but doesn't grade or produce legal reports; Inventory Hive produces the right report but humans do the looking.
2. **Condition-assessment accuracy** is unsolved everywhere — no one ships calibrated good/fair/poor grading.
3. **Pre/post (check-in vs check-out) automated comparison** — nobody does AI image-to-image change detection per item.
4. **Evidential integrity** is weakly handled across the category — timestamps yes, cryptographic provenance essentially absent.

---

## 5. Evidential Integrity for Photo Evidence

- **Scheme guidance (the binding constraint)**: adjudicators want photos that are **date-stamped, embedded in the signed report, clear, well-lit, and showing context** ([mydeposits: photos and videos as evidence](https://www.mydeposits.co.uk/content-hub/using-photos-and-videos-as-evidence/), [NRLA](https://www.nrla.org.uk/news/using-photographs-and-videos-as-dispute-evidence)). If a visible stamp is missing, **EXIF metadata or a witness statement can establish date**. Undated photos are heavily discounted.
- **Practical product requirements**: preserve full EXIF; render capture dates with report images while retaining originals; compute **SHA-256 hashes** and record them in a report appendix; keep an audit log of edits; export originals on request.
- **C2PA / Content Credentials**: the emerging cryptographic provenance standard ([spec explainer](https://spec.c2pa.org/specifications/specifications/2.4/explainer/Explainer.html)). Courts treat it as supporting, not self-authenticating ([Magnet Forensics](https://www.magnetforensics.com/blog/c2pa-and-media-authentication-what-you-need-to-know/), [Truescreen](https://truescreen.io/articles/c2pa-standard-history-limitations/)). For TDS adjudication (documents-only ADR, balance of probabilities) C2PA is over-spec but a differentiator.
- **Adjudication ≠ court**: deposit ADR is evidence-on-paper, balance-of-probabilities; the decisive factors are *signed inventory + dated comparable photos* — hash + timestamp directly answers the "when was this taken" question adjudicators actually ask.

---

### Key product implications

Build the report to the TDS/AIIC template: room-by-room schedule, per-item description + condition (with factual qualifiers) + separate cleanliness grade, embedded date-stamped photos, sign-off flow with a 7-day amendment window, and a comparative check-out mode. Technically: open-vocab detector (YOLOE for speed — mind the AGPL licence — or Apache-2.0 Grounding DINO + SAM2) for item proposals, then a VLM prompted with the UK grading rubric for naming and condition, with human confirmation per item. Differentiate on what nobody does: calibrated condition grading, hash+timestamp evidential integrity, and automated check-in/check-out comparison.

*June 2026 addendum*: the describe step is now provider-agnostic (claude /
openai-compat / local Ollama behind one interface), with gpt-5.4-mini the
provisional cheap default pending eval-fixture numbers (docs/04). The first
verified hallucinated defect (sticker → "scratch") moved review UX from
nice-to-have to core evidential machinery (docs/05): human confirmation per
item is what converts AI drafts into adjudication-grade evidence.
