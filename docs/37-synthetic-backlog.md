# Synthetic backlog — after the two checks

*Status: active. Owns what remains after the describe check and compare check
closed on 6 Aug 2026. Supersedes open next-work framing in docs/36 for the
synthetic programme; does not amend docs/31·34·35 mid-flight.*

## Closed

| Check | Result home |
|---|---|
| **Describe check** | `evals/fixtures/synthetic-room-eval/reports/describe-check-results.md` |
| **Compare check** | `evals/fixtures/synthetic-room-eval/reports/compare-check-results.md` |

Both are diagnostic stop/go measurements on controlled GPT Image 2 evidence.
Neither promotes product behaviour (docs/00 / docs/08). Language: `CONTEXT.md`.

## Next — product decisions (no new synthetic generation)

Ordered by leverage on what the two checks already measured.

1. **Naming / alignment** — Describe-check identity invent/omit and compare-check
   `false_change_rate` are both dominated by schedule membership and rename
   churn. Decide whether further `match_score` work (or report copy that
   collapses renames) is worth a product change; measure against the committed
   delta pairs and describe-check inventories.
2. **Cleanliness gate** — Tenancy compare ignores cleanliness-only worsenings.
   Compare check: widening the gate triples cleanliness recall (3.8% → 11.5%)
   for ~0.1pp false-change rate. Decide whether a deposit report should flag
   cleaning-only change; if yes, land one clause mirroring deep-clean.
3. **Formal close of the old arms** — Record in one place (this doc is enough)
   that the prompt tournament / Phase 4, empty Pass B provisional backlog,
   second-generator matched set, and mid-flight docs/31 amendments are **not
   live**. Optional: collapse docs/31·34·35·36 into a historical appendix later;
   do not reopen them as status channels.

## Later — transfer and sensitivity (still cheap, still not promotion)

4. **Degradation ladder** — `degrade.py` on already-accepted stills (blur,
   downscale, JPEG, crop); labels inherited. First signal on whether describe-
   check numbers survive video-like frames. No generation, no Pass B.
5. **Video arm** — Only after (4), and only if the ladder says transfer is
   worth another look. Do not regenerate clips while the ladder is unwritten.
6. **Real check-in / check-out** — The only path that can promote compare
   behaviour. Synthetic delta pairs stay development evidence until then.

## Explicitly not next

- Growing the 200-image still pilot or clearing the Pass B ledger
- New delta-pair generation before (1) and (2)
- Sealed prompt/VLM tournament
- Treating `false_change_rate` as the compare headline without the aligned-
  state ratios in the compare-check results note

## Commands

```sh
python -m evals.synthetic.describe_check score   # re-read describe check
python -m evals.synthetic.compare_check          # re-derive compare check (offline)
```
