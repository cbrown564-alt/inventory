# Home Inventory

Evidence-led inventory and schedule-of-condition reports for residential property, from capture through review, correction, and comparison.

## Language

### Synthetic evaluation

**Describe check**:
A stop/go measurement of whether the live production describe invents or omits gold claims on controlled room evidence. Sized at twelve complete GPT Image 2 packets (RP-001, RP-002, RP-004, RP-006, RP-007, RP-009, RP-011, RP-013, RP-015, RP-016, RP-021, RP-024 — RP-018 dropped after diversity-patch reject; RP-006 substituted); it does not pick a prompt or VLM winner. It reports invent and omit rates per claim type (identity, condition, cleanliness, defects) as diagnostics — not a pass bar inside the synthetic programme.
_Avoid_: Phase 4, sealed comparison, prompt tournament, synthetic programme (when meaning this check alone), 200-image pilot, false_change_rate (as a describe-check headline)

**Compare check**:
A measurement of whether check-in → check-out comparison finds known room changes on the 27 scored delta pairs, read primarily as aligned-item state signal versus the repeat-describe noise floor. Diagnostic only; does not promote compare behaviour.
_Avoid_: Delta programme (as an open ambition), Phase 3.5 (as current centre), false_change_rate (as the sole headline)

**Synthetic backlog**:
What remains after both checks: naming/alignment product work, cleanliness-gate product decision, formal close of the old arms, then degradation ladder → video only if warranted, then real check-in/out for promotion. Owner: `docs/37-synthetic-backlog.md`.
_Avoid_: Treating prompt tournament, Pass B backlog, or further delta generation as the next move

**Compare-check results note**:
The single home for the compare-check answer: signal-vs-noise ratios, scored gold recall by kind, cleanliness-gate sensitivity, and stop. Machine artifact: `reports/compare-check-score-2026-08-06.json`.
_Avoid_: Amending docs/36 as the live status channel

**Diversity patch**:
The only new still generation allowed before the describe check: one missing GPT Image 2 view each for RP-011, RP-013, RP-021, and RP-018 (four images). No other regeneration.
_Avoid_: Filling the full incomplete ledger, second-generator retries

**Describe-check results note**:
The single home for the describe-check answer when finished: set used, gold method, invent/omit table by claim type, and stop. Score JSON under the synthetic fixtures reports directory is the machine artifact. docs/31·34·35·36 are not amended mid-flight for programme status.
_Avoid_: Amending docs/36 as the live status channel

**Gold claim**:
A schedule-of-condition assertion the tenancy report may show a reader — item identity plus the condition, cleanliness, and defect fields that report surfaces. Not a free-text room essay and not a “notable contents only” subset that excludes fabric the product lists.
_Avoid_: Notable contents (as the gold definition), Pass B claim (as synonymous with gold), provisional record

**Gold draft**:
A spec-seeded proposal of gold claims — `intended_visible_items` and `intended_defects` from the scenario — completed by a single cross-family AI pass for report fields the spec does not state (surfaces, grades). Owner spot-check is authority; dual-AI Pass B and second-review ledgers are not part of the describe check. Spot-check is risk-weighted: every defect claim, every post-score invent/omit disagreement, plus a small random sample of the rest.
_Avoid_: Pass B, verified_synthetic_gold (as the describe-check label state), provisional backlog, same-family GPT labelling of GPT frames as sole draft truth

**Image accept (diversity patch)**:
Owner eyeball only — intended evidence visible and continuous with the packet’s other views. Pass A runners are not a gate for these four views.
_Avoid_: Pass A ledger (as a describe-check gate)
