# Property reconstruction from IMG_5677.MOV

**Status:** exploratory Blender reconstruction, 8 September 2026. This document
owns the reconstruction's outcome, evidence limits and handoff. It does not add
3D reconstruction to the inventory product's v1 scope in `docs/00`.

## Outcome

An editable interior model represents the main level and loft: hall/storage,
living/dining, kitchen, lower study, main bathroom, lower bedroom and en-suite,
stairs, loft landing, loft office, loft bedroom and loft shower room. The model
includes openings, doors, floors, sloped ceilings, rooflights, fitted cabinets,
major furniture, sanitaryware and approximate materials.

The model is **reference-based and unmeasured**. The video supports room contents
and some connections, but does not establish the dimensions or global layout.
No floor plan or measured distance was supplied. Nominal dimensions, room offsets,
wall thicknesses, stairs, eaves and camera positions remain editable assumptions.
The exterior, concealed structure and services are omitted. The bay window and
curved shower enclosure are simplified. Decorative patterns, furniture details,
cupboard contents and condition defects are not reproduced faithfully.

## Local deliverables

Generated property media are local and ignored by Git under
`output/reconstruction/IMG_5677/`. No source or generated property media were
uploaded or published.

| File | Purpose |
| --- | --- |
| `deliverables/IMG_5677_property.blend` | Editable model, animated camera, reference boards and separate sparse-reconstruction scenes |
| `deliverables/IMG_5677_property.glb` | Architectural mesh interchange; source boards and sparse fragments remain in Blender |
| `deliverables/walkthrough.mp4` | 22-second animated-camera preview, with cuts between rooms; 720 × 520 at 6 fps |
| `deliverables/review.html` | Local source/render comparison report, assumptions, fitted view and reconstruction metrics |
| `deliverables/overview.jpg` | Labelled main/loft cutaways and room previews |
| `deliverables/editable_dimensions.json` | Convenience copy of the nominal room specification |
| `deliverables/reference_manifest.json` | Source hash, reference image hashes and timestamps |
| `deliverables/verification.json` | Reopened Blender artifact checks |
| `pilot/manifest.json`, `pilot/result.json` | Frame preparation provenance and actual COLMAP results |
| `final_renders/` | Room views, floor cutaways and fitted kitchen view |

Source scripts and the canonical editable specification live in
[`scripts/reconstruction/`](../scripts/reconstruction/README.md). Modify
`scripts/reconstruction/IMG_5677.scene.json` to regenerate; editing the convenience
copy alone does not change the source specification. Blender objects also expose
room roots, object names and source timestamps for direct corrections. Save hand
edits as a separate working copy. Regeneration writes a new file and does not
merge manual changes.

## Evidence and method

The original video is 1,280.013 seconds long, HEVC, about 30 fps, 1920 × 1080 in
encoded orientation with portrait rotation metadata and HLG/BT.2020 color tags.
The earlier `IMG_5512.MOV` segmentation in the repository describes another
recording and was not reused as truth for this video.

The footage was inspected through 20-second contact sheets, denser transition
references and larger selected views. Much of the kitchen and bathrooms consists
of close-up inspection. Frames include camera roll, reflective surfaces and
changes in apparent field of view. Source timestamps remain attached to rooms and
meshes. Display-oriented reference images are separate from the encoded-orientation
images used for geometric reconstruction. The latter use the explicit HDR viewing
transform recorded in the extraction manifest; neither is a colorimetric material
measurement.

The representative trial covered 00:30–02:35. It extracted 125 frames at 1 fps,
withheld 14 from COLMAP, and selected 108 after the sharpness filter. CPU SIFT,
sequential matching and incremental mapping recovered 85 unique registered views
in five overlapping fragments:

| Fragment | Registered views | Points | Mean reprojection error |
| --- | ---: | ---: | ---: |
| 0 | 30 | 4,818 | 1.06 px |
| 1 | 24 | 4,019 | 0.66 px |
| 2 | 21 | 2,542 | 1.07 px |
| 3 | 8 | 316 | 0.61 px |
| 4 | 23 | 3,738 | 0.89 px |

Registered counts overlap. Focal estimates differed substantially (about
585–1,200 px at the processed resolution). These results did not justify a single
property scan. The fragments, undistorted camera backgrounds and colored sparse
points are retained in separate Blender scenes. **They are not globally aligned,
metrically scaled or registered to the architectural model.** No dense mesh or
whole-property photogrammetric accuracy is claimed.

One architectural camera was fitted to eight manually placed washer/oven
landmarks at 03:05, using nominal appliance dimensions and an assumed 900 px focal
length. Its 8.78 px RMS is an in-sample fitting residual, not independent geometric
accuracy. The review report exposes this view beside its source. Other rendered
room views use approximate editorial camera positions. Nearby withheld video
frames are development references, not representative independent validation.

## Verification and limits

Blender 5.2.0 LTS and an isolated PyCOLMAP 4.2.0 environment were used locally.
The inventory product's dependencies were not changed. No paid inference or
image-generation service was run.

The packaged file contains 1,276 architectural mesh objects, 124 packed reference
images and seven scenes. Checks after reopening cover finite coordinates,
positive signed volume for 1,035 solid boxes, source references on every
architectural mesh, missing image files and reference viewpoints inside solid
boxes. Visual iteration corrected overlapping openings, a stair/office overlap,
roof-side placement, inward mesh normals and obstructed room views.

Repository verification passed: **576 tests passed, 1 skipped** with
`.venv/bin/python -m pytest -q`; `.venv/bin/python evals/ci_gate.py` also passed.
These protect the existing product and do not establish reconstruction accuracy.
All room renders and source comparisons were visually inspected. The final file
was opened in Blender's desktop UI, and the HTML report was inspected in the
browser. The 22-second preview played through to its end without a media error;
all 132 encoded frames decoded, all report asset paths resolved, and the original
MOV's SHA-256 still matched the extraction manifest.

The work is **implemented** as an approximate prototype. It is not a validated
survey, an authoritative floor plan, a condition report, or a promoted product
feature. A reliable measured length, then additional checks across rooms and
levels, would be needed to replace nominal scale and resolve the layout. A more
complete scan would also need footage with sustained parallax and overlap, or a
new capture designed for reconstruction.

## Primary technical references

- [OpenAI Astra guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [Blender scripting workflow](https://docs.blender.org/api/main/info_tips_and_tricks.html)
- [COLMAP capture and reconstruction guidance](https://colmap.github.io/tutorial.html)
- [PyCOLMAP installation and API](https://colmap.github.io/pycolmap/index.html)
