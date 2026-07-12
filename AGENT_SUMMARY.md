# Stamp EXIF DateTimeOriginal on extracted video keyframes

Extracted keyframes now get wall-clock capture time from
`video_recorded_epoch + frame_index/fps` (MP4/MOV mvhd.creation_time, else
video mtime). Footage position stays `frame_index/fps` via videometa.photo_time.

## Files
- `homeinventory/ingest.py` — stamp at extract; helpers for epoch and EXIF
- `homeinventory/report.py` — preserve stamped EXIF on exported JPEGs
- `homeinventory/schema.py` — docstring for captured_at on keyframes
- `tests/test_ingest_exif.py` — 7 tests (all pass)
- `docs/29-evidential-spec-audit.md` — provenance rule + audit table
- `docs/00-north-star.md` — frame-metadata gap marked closed

## Provenance rule
```
video_start    := mvhd.creation_time(video) OR video.stat().st_mtime
frame_wall     := video_start + (frame_index / fps) -> EXIF DateTimeOriginal, Photo.captured_at
frame_in_video := frame_index / fps                 -> report timecode, videometa.photo_time
```

## Tests
`python -m pytest tests/test_ingest_exif.py tests/test_pipeline.py tests/test_report_quality.py`
