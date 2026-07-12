# Deposit-scheme evidential spec — audit checklist

Point-by-point status against the UK scheme guidance summarised in
[`market-research-2026-07.md`](market-research-2026-07.md) and Pillar 2 in
[`00-north-star.md`](00-north-star.md).

| Requirement | Status | Notes |
|---|---|---|
| Date/timestamps on all media (file metadata) | **Met** | Native photos: EXIF at capture. Extracted video keyframes: `DateTimeOriginal` written at ingest (`ingest.stamp_exif_capture_time`) and preserved on report export (`report._export_photos`). |
| Provenance rule for extracted frames | **Met** | Wall-clock = `video_recorded_epoch + (frame_index / fps)`. Epoch from MP4/MOV `mvhd.creation_time` when present, else video file mtime. Footage position (timecode) remains `frame_index / fps` via `videometa.photo_time` — not replaced by wall-clock alone. |
| `Photo.captured_at` populated | **Met** | Set from EXIF for all photos, including extracted keyframes. |
| Written report with embedded photos | **Met** | HTML/PDF report embeds downscaled JPEGs under `photos/`. |
| Video time-referenced (exact moment in source footage) | **Met** | Report captions and appendix show `seen at M:SS` from `photo_time`; review UI links frames to ranged video playback. |
| Tamper-evident photo set | **Met** | `integrity.build_manifest` SHA-256 over source videos and every photo file; appendix lists hashes + `captured_at`. |
| Both-party signatures | **Partial** | Signing flow exists; tenant countersign not yet the default journey step (Pillar 4). |
| Comparison artefact (check-in vs check-out) | **Met** | Compare mode ships (`compare.py`, tenant/compare templates). |
| Independent / credible inventory (tenant review) | **Partial** | Review + share path exists; countersign-as-default still open. |

## Frame-metadata provenance (implementation)

```
video_start  := mvhd.creation_time(video)  OR  video.stat().st_mtime
frame_wall   := video_start + (frame_index / fps)   → EXIF DateTimeOriginal, Photo.captured_at
frame_in_video := frame_index / fps                 → report timecode, videometa.photo_time
```

Code: `homeinventory/ingest.py` (`video_recorded_epoch`, `extract_keyframes`,
`stamp_exif_capture_time`), `homeinventory/videometa.py` (`photo_time`),
`homeinventory/report.py` (export preserves EXIF from `captured_at`).
