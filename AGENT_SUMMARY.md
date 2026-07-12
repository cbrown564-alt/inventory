# Integration — evidence quality v1

Working branch: `integrate/evidence-quality-v1`

## Landed so far

1. **Evidential EXIF** — extracted keyframes get `DateTimeOriginal`; footage
   timecode retained (`docs/29-evidential-spec-audit.md`).
2. **Capture-strategy Step 0 scaffolding** — `--photo-mode`, room-folder
   ingest, layout validation (`homeinventory/capture_experiment.py`).

## Still in progress on this branch

- Hero contract close (semantic + no-confident-cover)
- Tenant countersign as default Finish step
- ML-E2 / ML-E8 / ML-E10 production wiring
- Native-res / v1 accuracy verification harness
- Repo hygiene (gitignore, dead `start.html.j2`, generated artifacts)
