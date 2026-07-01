# Benchmark vs a professional clerk's report (Milestone 1)

**Date:** 11 June 2026
**Verdict:** On real clerk photography our pipeline recovers ~85% of the items a
professional records, agrees with the clerk's condition grade within one step 100% of
the time, and reads appliance model numbers the clerk transcribed by hand — but it
captures only **half the defect detail** that justifies a £165 report, and the
room-level merge granularity differs enough from clerk convention that raw eval
numbers under-credit both backends.

## The benchmark

Searched for published sample inventory reports with photos + labelled items +
condition descriptions. Candidates downloaded to `benchmarks/samples/`:

| Sample | Verdict |
|---|---|
| [InventoryFlex Inventory Report](https://inventoryflex.co.uk/sample-of-report) | **Used.** 35pp, 6 rooms, ~80 itemised entries with rich descriptions, 192 embedded 800×600 timestamped photos |
| [The Inventory Manager sample](https://theinventorymanager.co.uk/wp-content/uploads/2019/12/Sample-TIM-report.pdf) | Held in reserve (smaller, lower photo density) |
| [IMS Check-Out sample](https://inventory-managementsolutions.co.uk/wp-content/uploads/2013/07/Check-Out-Report-IMS-sample.pdf) | Check-out format — useful later for Milestone 4 (compare) |

The InventoryFlex sample is a genuinely professional artefact: per-item
Name/Description/Condition tables ("Brass finished Yale lock", "Miele oven model
H2860B"), defect localisation ("Noticeable angle chip low level leading edge to
exterior door"), and per-room photo grids.

`benchmarks/extract_inventoryflex.py` pulls the 192 photos into
`benchmarks/inventoryflex/capture/<Room>/` and the clerk's tables into
`ground-truth.txt`. The tables were hand-converted into eval gold labels
(`benchmarks/inventoryflex/labels.json`, 112 items, 78 defects) using the existing
`evals/run_eval.py` schema — this is now our first real-footage eval fixture.

## Results (whole-image mode, no detector)

| Metric (target) | claude (opus-4-8) | gpt-5.4-mini |
|---|---|---|
| item_recall_notable (≥90) | **84.9** | 83.6 |
| item_recall_all | 72.3 | 68.8 |
| hallucination_rate (≤5) | 38.2 * | 37.9 * |
| naming_accuracy (≥85) | **91.4** | 89.6 |
| condition_exact (≥70) | **84.2** | 41.9 |
| condition_within_one (≥95) | **100.0** | 100.0 |
| defect_recall (≥75) | **55.1** | 40.5 |

\* see "headline numbers mislead" below.

Both runs: 192 photos, 6 rooms, ~130 (claude) / ~110 (gpt) predicted items. The
gpt-5.4-mini run needed one `--resume` after a transient 520 on Walk In Wardrobe;
the claude run was clean.

### Accuracy

- **Condition grading is the clearest separation.** Claude matched the clerk's grade
  exactly 84% of the time; gpt-5.4-mini only 42% (it grades conservatively — lots of
  "fair" where the clerk and claude say "good"). Both are *always* within one grade,
  which matches human inter-clerk variability.
- **Claude reads what the clerk reads.** It extracted Miele model numbers H2860B
  (oven) and M7244 (microwave) from the photos — same numbers the clerk recorded — and
  identified the "washing machine" (clerk's words, model WTD160WCS) as the
  **washer-dryer that model number actually denotes**. It also named the Nuaire MRXBOX
  ventilation unit and Danfoss heating control in the utility cupboard, which the
  clerk recorded generically.

### Depth

- **Defect capture is where the professional still wins.** The clerk records 78
  localised defects ("angle chip knee level left hand side exterior", "cord attached
  with black rope and not attached to cleat"). Claude caught 55%, gpt 41% — and what
  they catch is usually less precisely localised. This is the single biggest gap and
  the prompt-tuning target for Milestone 2.
- Roughly a third of the 192 photos are near-featureless wall/corner close-ups (clerk
  evidence shots). These contribute little without the room context — per-photo
  defect attention on close-ups is a plausible depth lever.

### Reliability — why the headline hallucination numbers mislead

The eval's greedy fuzzy matcher charges anything unmatched as a hallucination, but
auditing (`benchmarks/audit_matches.py`) shows most "hallucinations" are
**granularity differences, not invention**:

- The clerk records *one* "Bath" entry covering taps, hose, screen and panel; the
  models emit 3–4 separate items (bath, mixer controls, hand shower, screen).
- "Sideboard / credenza" (claude) *is* the clerk's "TV Unit"; "Dining/bar chairs"
  merged two gold entries; "Miele washer-dryer" is the clerk's "washing machine".
- Real candidate inventions are rare and small: gpt's "boiling water/filtered tap
  unit", claude's "coffee machine" — each needs manual photo verification, but the
  count is ~2–5 per run out of ~120 items, i.e. a true hallucination rate plausibly
  under 5%, not 38%.

Both backends genuinely missed the same cluster of small wall-mounted items:
**smoke alarms, thermostats, the entryphone, doorstops, air vents** — items a clerk
records by convention but which occupy a few hundred pixels in wide shots. A
checklist-style prompt hint ("always look for: smoke alarm, thermostat, …") is the
obvious cheap fix.

## Cost

Reconstructed with `benchmarks/cost_estimate.py` — exact claude input tokens via the
free `count_tokens` endpoint replaying the identical requests; gpt-5.4-mini calibrated
by replaying one room and reading the real `usage` block (~624 input tokens per
800×600 image, zero reasoning tokens). June 2026 pricing: opus-4-8 $5/$25 per M,
gpt-5.4-mini $0.75/$4.50 per M.

| Run (192 photos, 6 rooms) | Input tokens | Output tokens | Cost |
|---|---|---|---|
| claude (opus-4-8) | 127,356 (exact) | ~13,500 | **$1.17 actual billed** ($0.97 est.) |
| gpt-5.4-mini | ~122,000 | ~11,300 | **~$0.14** |

The reconstruction undershot the billed figure by ~17% — the chars/4 output
estimate and the structured-output schema injection (not counted by the
`count_tokens` replay) account for the difference; treat script output as a floor.

Opus is ~8× the price but both are noise against the £165 professional fee
(0.7% and 0.07% respectively).

**Decision (11 Jun 2026):** $1.17/property is acceptable *if defect recall
improves substantially* — that is the bar for the Milestone 2 prompt work.
Iterate prompts and eval sweeps on gpt-5.4-mini (~$0.14/run); validate
candidates and produce final reports on opus.

## Conclusions

1. **The 80% claim holds on professional footage.** Item coverage, naming and grading
   are already adjudication-credible; claude is the quality pick, consistent with
   docs/04.
2. **Defect depth (~55%) is the gap to close** — prompt work: ask for per-photo defect
   sweeps on close-up shots, demand location phrases (level + side + edge), and feed
   the clerk's standard vocabulary as few-shot examples.
3. **The eval matcher needs work before the numbers can be trusted unaudited**:
   greedy matching + granularity mismatch produces ~33-point hallucination inflation.
   Either add part-of relations to gold labels or score with optimal assignment +
   item grouping.
4. **Standard-items checklist** in the prompt to fix the smoke alarm/thermostat/
   doorstop miss cluster.
5. The clerk's report remains better at *systematic coverage discipline* (every door
   frame, every switch plate); ours is better at *identification* (model numbers,
   actual appliance types). These are complementary — the review loop (docs/05) is
   where a human adds the former.

## Prompt iteration + scorer fixes (11 Jun 2026, same day)

Acting on conclusions 2–4: the eval matcher was fixed first (score-ordered
one-to-one assignment instead of gold-order greedy; substring matches graded by
length ratio so "bed" can't steal "Bedside table"; part-split defect credit when
the model splits an item the clerk merged, e.g. mattress out of "Bed & Mattress").
Re-scoring under the fixed scorer showed the opus baseline defect recall was
actually **67.9**, not 55.1 — about a third of the reported gap was metric error.

Then the system prompt was iterated on gpt-5.4-mini (~$0.14/run), one change per run:

| Run (fixed scorer) | defect recall | notable recall | cond. exact | naming | halluc.* |
|---|---|---|---|---|---|
| opus, v1 prompt | 67.9 | 86.3 | 84.2 | 95.1 | 38.2 |
| mini, v1 prompt | 46.9 | 84.9 | 41.3 | 92.3 | 37.1 |
| mini, v2: + standard-items checklist, clerk localisation vocabulary, close-up-shot instruction, good-vs-excellent calibration | 55.7 | 86.3 | 89.3 | 97.8 | 40.7 |
| mini, v3: + cleanliness findings recorded as defects | 58.1 | **90.4** | 68.7 ⚠ | 95.3 | 39.7 |
| mini, v4: + condition measures wear not dirt | **64.8** | **90.4** | 83.7 | 96.7 | 40.0 |
| **opus, v4 prompt** | 67.8 | 87.7 | **92.7** | 94.4 | 37.3 |

\* still granularity-dominated before the M1 matcher fix; re-scored with
many-to-one coverage + gold `components` the opus v4 run reports **2.8%**
hallucination (4 genuine unmatched items) and **29.6%** granularity splits.

Findings:

1. **The prompt closed mini's gap, not opus's ceiling.** Mini gained +18 points
   of defect recall and hit the ≥90 notable-recall target; opus was flat on
   defects (67.9 → 67.8) — it already did the prompted behaviours. Opus still
   leads where it always led: grading agreement (92.7 exact).
2. **The v3 lesson:** asking for cleanliness findings as defects dragged grades
   down ("good" → "fair" for dirty-but-sound items) until v4 stated explicitly
   that condition measures wear, not dirt. Rubric clauses interact; change one
   thing per run.
3. **~68% defect recall looks resolution-bound on this fixture.** The photos are
   800×600 PDF extractions; the clerk worked from life and full-res originals.
   The misses that remain (faint scuffs on white walls, grout discolouration,
   hairline cracks) are at or below what 800×600 resolves. Expect this ceiling
   to lift on M2's own-property capture at native resolution — measure there
   before more prompt surgery.
4. **Mini v4 ≈ opus v1 on defects at 8× less.** The iterate-on-mini /
   validate-on-opus split is confirmed working practice.

## Artefacts

- `benchmarks/samples/` — downloaded sample PDFs (4)
- `benchmarks/extract_inventoryflex.py` — photo/ground-truth extraction
- `benchmarks/inventoryflex/capture/` — 192 photos in 6 rooms
- `benchmarks/inventoryflex/labels.json` — 112-item gold fixture (eval-schema)
- `benchmarks/inventoryflex/report-claude/`, `report-gpt54mini/` — v1-prompt outputs;
  `report-gpt54mini-v2/…-v4/`, `report-claude-v4/` — prompt-iteration outputs
- `benchmarks/audit_matches.py` — per-room missed/unmatched audit
- `benchmarks/audit_defects.py` — per-item missed-defect audit
