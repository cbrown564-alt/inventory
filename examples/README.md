# Examples

`sample-report/` is a real end-to-end run of the pipeline over a synthetic
2-room fixture (3 generated photos + a 6-second pan video reduced to keyframes),
using the `offline` backend plus a hand-edited review pass on the Living Room —
i.e. exactly the human-in-the-loop workflow the tool is designed around:

1. `homeinventory build capture -o report --backend offline`
2. edit `report/inventory.json` (names, grades, defects)
3. `homeinventory render capture -o report`

Open `sample-report/inventory.html` in a browser. Note the structure that makes
the report TDS-credible: per-item condition *and* cleanliness grades, localized
defect notes, photo references on every row, and the SHA-256 evidence manifest
in Appendix A.

`sample-labels.json` is a minimal eval fixture in the format `evals/run_eval.py`
expects.

A run with `--backend claude` on real photos produces full clerk-style
descriptions and grades automatically; this sample only shows the report
machinery since CI has no photos of a real property (or an API key).
