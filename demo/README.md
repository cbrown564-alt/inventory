# Public-safe evidence-room demo

This is a dependency-free, read-only browser slice for portfolio review. It
uses the committed, public-safe `RP-001` GPT Image 2 synthetic packet under
`evals/fixtures/synthetic-room-eval/` and its recorded review data. The four
original 1448×1086 PNGs are served unchanged. The page does not upload, call
AI services, persist edits, expose owner/tenant links, or contain real property
data.

From the repository root, serve the repository directory and open `/demo/`:

```sh
python -m http.server 8000
open http://127.0.0.1:8000/demo/
```

The HTTP server is needed because browsers block some relative asset requests
when `index.html` is opened directly from disk. The demo loop is:

1. Select a recorded Kitchen observation.
2. Inspect its cited original frame, the Pass A acceptance, recorded
   observation, review status, and SHA-256 hash.
3. Switch among the cited A-wide, B-reverse, C-inventory, and D-condition
   views, then open **See the final issue** for the report handoff and the
   observed-claim → original-frame → view-ID → hash explanation.

The displayed packet details, observations, Pass A decisions, Pass B labels,
and second-review statuses are taken from the committed RP-001 scenario and
`RP-001.gpt-image-2.json`. This page is not a real-property accuracy
benchmark, legal advice, or a hosted upload service.
