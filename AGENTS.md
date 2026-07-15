# Home Inventory

Build one trustworthy route from property capture to an evidence-led inventory and schedule-of-condition report. Every material claim must remain inspectable and correctable.

`docs/00-north-star.md` owns v1 scope. `docs/12-video-first-journey.md` owns the current journey, `docs/10-product-quality-review.md` the experience bar, `docs/04-backend-comparison.md` backend evidence, and `docs/21-ml-dl-experiment-log.md` ML experiment status. `docs/README.md` is the authority map. Do not turn exploratory ML, native-app, or capture work into a product commitment without updating its owner.

Keep capture, review, correction, reporting, and comparison traceable. Preserve provenance, uncertainty, timestamps, and human edits; never strengthen a property claim beyond its evidence. Separate representative evaluations from development examples, and keep optional ML dependencies outside the core product until evidence supports promotion.

Inspect the review UI and generated HTML or PDF after relevant changes. Use the environment and commands in `README.md`; focused checks include:

```sh
python -m pytest
homeinventory check <capture-directory>
homeinventory review <capture-directory> -o <report-directory>
```

Do not run paid or network-backed inference unless the task authorizes it.
