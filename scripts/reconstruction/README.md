# Video-to-Blender reconstruction experiment

This workflow creates an approximate editable interior and preserves the video
references and local camera-reconstruction results. It does not create a survey.
The canonical outcome, uncertainty and verification record is
[`docs/38-property-reconstruction.md`](../../docs/38-property-reconstruction.md).

The source MOV and all generated media stay local under the existing ignored
`output/` directory. Nothing is uploaded. The project Python environment is not
modified; reconstruction tools live in `.tools/reconstruction/venv`.

## Reproduce

Run from the repository root. FFmpeg and Blender 5.2.0 LTS must be installed.
The Python pins record the environment used for this run.

```sh
uv venv .tools/reconstruction/venv --python 3.11
uv pip install --python .tools/reconstruction/venv/bin/python -r scripts/reconstruction/requirements.txt
.tools/reconstruction/venv/bin/python scripts/reconstruction/prepare.py examples/videos/IMG_5677.MOV output/reconstruction/NEW_RUN/pilot --start 30 --end 155 --fps 1
.tools/reconstruction/venv/bin/python scripts/reconstruction/sfm.py output/reconstruction/NEW_RUN/pilot
.tools/reconstruction/venv/bin/python scripts/reconstruction/export_evidence.py output/reconstruction/NEW_RUN/pilot
.tools/reconstruction/venv/bin/python scripts/reconstruction/package_review.py --root output/reconstruction/NEW_RUN --extract-reference-views --references-only
.tools/reconstruction/venv/bin/python scripts/reconstruction/fit_reference_camera.py --root output/reconstruction/NEW_RUN
blender --background --factory-startup --python-exit-code 1 --python scripts/reconstruction/build_blender.py -- --spec scripts/reconstruction/IMG_5677.scene.json --output output/reconstruction/NEW_RUN/model --render
blender --background output/reconstruction/NEW_RUN/model/property.blend --threads 4 --python-exit-code 1 --python scripts/reconstruction/render_tour.py -- --output output/reconstruction/NEW_RUN/tour --save-only
blender --background output/reconstruction/NEW_RUN/tour/property_animated.blend --threads 3 --python-exit-code 1 --python scripts/reconstruction/render_preview.py -- --output output/reconstruction/NEW_RUN/tour_preview
```

`IMG_5677.scene.json` owns the editable room sizes, positions, openings and evidence
anchors. Dimensions are nominal metres. Change that file deliberately and build
into a **new** output directory. Builders refuse to replace an existing `.blend`.
Save hand edits to a separate working copy; regeneration does not import them.

`prepare.py` preserves encoded camera orientation and records source/frame hashes,
nominal sample times, extraction commands, metadata and sharpness. Its HDR viewing
transform is documented in the manifest. Camera-roll corrections used for human
reference boards are separate from the COLMAP inputs. The original video is never
rewritten. One in nine extracted frames is withheld from the COLMAP trial. These
nearby frames are a development check, not an independent evaluation dataset.

`sfm.py` runs CPU SIFT extraction, sequential matching and incremental mapping. It
keeps all recovered fragments and their metrics; it does not manufacture a merge
or metric scale. `export_evidence.py` undistorts their image backgrounds and
exports the recovered cameras and points for Blender.

The view-reference extraction and kitchen camera fit use hand-selected anchors
from this video. `fit_reference_camera.py` documents the nominal appliance
coordinates and image landmarks used to fit that view. The current package uses
a focal-length assumption; its pixel residual is not a metric accuracy result.
`package_review.py` regenerates source references and the review package for this
property. These property-specific inputs should not be reused for another video.

After the tour's animated blend is saved, package and verify it:

```sh
blender --background output/reconstruction/NEW_RUN/tour/property_animated.blend --python-exit-code 1 --python scripts/reconstruction/finalize_blender.py -- --root output/reconstruction/NEW_RUN
blender --background output/reconstruction/NEW_RUN/deliverables/IMG_5677_property.blend --python-exit-code 1 --python scripts/reconstruction/render_comparison.py -- --output output/reconstruction/NEW_RUN/final_renders
ffmpeg -framerate 6 -pattern_type glob -i 'output/reconstruction/NEW_RUN/tour_preview/frames/frame_*.png' -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart output/reconstruction/NEW_RUN/deliverables/walkthrough.mp4
.tools/reconstruction/venv/bin/python scripts/reconstruction/package_review.py --root output/reconstruction/NEW_RUN --model model
blender --background output/reconstruction/NEW_RUN/deliverables/IMG_5677_property.blend --python-exit-code 1 --python scripts/reconstruction/verify_blender.py -- --output output/reconstruction/NEW_RUN/deliverables/verification.json
```

The finalizer creates a new final file, embeds source images, adds independent
COLMAP scenes and exports the architectural mesh to GLB. It does not modify the
source or the intermediate model. The GLB contains the architectural scene;
Blender's reference boards and sparse scenes remain in the `.blend`.

Repository checks:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python evals/ci_gate.py
```

Inspect every final room render and the video. Automated mesh checks cover finite
coordinates, outward-facing solid boxes, provenance, viewpoints inside boxes,
packed images and reopening; they cannot establish the real floor plan.
