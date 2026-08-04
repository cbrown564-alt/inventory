#!/usr/bin/env python3
"""Sample a staged clip into the strip Pass A is judged on.

``video/dataset.json`` review_policy: "Pass A samples frames at a fixed cadence
(1 fps) plus every declared gold timestamp. Continuity is judged across the
sampled strip, not on a single frame. Any accepted clip records the sampled
strip's hash alongside the clip hash."

Three things here are deliberate.

**The strip hash is over decoded pixels, not encoded files.** H.264 decoding is
standardised and deterministic; JPEG *encoding* is not stable across ffmpeg
builds. Hashing the JPEGs would tie the ledger to whichever ffmpeg happened to
be installed the day the strip was built, and a later reader could not tell a
re-encode from a substituted frame. Hashing the raw RGB24 buffer makes the
strip reproducible anywhere, which is why the rendered frames are a viewing aid
and are not committed.

**Three acceptance criteria are decided here, not by the reviewer.** A vision
model cannot hear, and asking one whether a take is unbroken invites it to
narrate rather than measure. Cuts, audio mode and container facts are measured
with ffmpeg and carried into the review as findings the reviewer is told not to
re-litigate.

**Requested timing is never treated as delivered timing.** A clip's declared
cue or boundary time is a *request*. Frames sampled at those times are marked
``declared_gold_timestamp`` so nobody later reads the sampling grid as gold
(docs/34, "Gold timestamps ... are read from the delivered file").
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from evals.synthetic.build_video_tasks import DEFAULT_DATASET

#: Bumped whenever the sampling rule changes. A strip hash is only comparable
#: against another strip built by the same sampler.
SAMPLER_VERSION = 2

#: Contact-sheet layout. Continuity, geometry and occlusion are properties of
#: the sequence, and a reviewer holding one frame at a time has to remember the
#: previous ten to see any of them. Tiled side by side, a room that changes
#: shape is obvious at a glance. Four columns keeps each tile large enough to
#: read at 1280x720 source.
SHEET_COLUMNS = 4
SHEET_TILE_WIDTH = 640

#: Cadence from the dataset's review policy.
CADENCE_FPS = 1.0

#: A scene score this high inside a take that was specified as "one unbroken
#: take" is a cut. Gemini Omni renders continuous motion, so ordinary
#: frame-to-frame change sits far below this; the threshold is set to catch a
#: hard discontinuity, not a fast pan.
SCENE_CUT_THRESHOLD = 0.35

#: Peak level below which an audio track is inaudible at ordinary playback
#: gain. A clip generated with "no speech, no music, no sound effects, no room
#: tone" should sit under this or carry no audio stream at all.
SILENT_MAX_DBFS = -50.0

#: Level and minimum duration for splitting a track into non-silent runs. The
#: *structure* of those runs is the cheap discriminator this module can honestly
#: offer: stationary room tone is one run spanning the clip, while speech,
#: footsteps and music arrive as separate bursts.
SILENCE_FLOOR_DBFS = -45.0
SILENCE_MIN_S = 0.15


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True)


def _ffmpeg_version() -> str:
    result = _run(["ffmpeg", "-hide_banner", "-version"])
    return result.stdout.splitlines()[0].strip()


def probe_container(clip: Path) -> dict[str, Any]:
    result = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(clip),
    ])
    data = json.loads(result.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    numerator, _, denominator = video["r_frame_rate"].partition("/")
    fps = float(numerator) / float(denominator or 1)
    return {
        "duration_s": round(float(data["format"]["duration"]), 3),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "frame_count": int(video.get("nb_frames") or 0),
        "video_codec": video["codec_name"],
        "audio_streams": len(audio),
        "audio_codec": audio[0]["codec_name"] if audio else None,
    }


def sample_indices(container: dict[str, Any],
                   gold_timestamps: list[float]) -> list[dict[str, Any]]:
    """Frame indices for the strip: 1 fps, the last frame, and declared golds.

    The last frame is always included because several clips are specified as
    "come to rest facing X", and whether they did is only visible at the end.
    A cadence that stops at the last whole second can miss it entirely.
    """
    fps = container["fps"]
    total = container["frame_count"]
    if total <= 0:
        raise ValueError("clip reports no frame count; cannot sample a strip")
    step = max(1, round(fps / CADENCE_FPS))
    sources: dict[int, str] = {}
    for index in range(0, total, step):
        sources[index] = "cadence"
    sources.setdefault(total - 1, "final_frame")
    for timestamp in gold_timestamps:
        index = min(total - 1, max(0, round(timestamp * fps)))
        # A declared gold time that lands on the cadence grid keeps the more
        # specific label: it is why that frame must be present.
        sources[index] = "declared_gold_timestamp"
    return [
        {"index": index, "timestamp_s": round(index / fps, 3),
         "source": sources[index]}
        for index in sorted(sources)
    ]


def _select_expression(indices: list[int]) -> str:
    return "+".join(f"eq(n\\,{index})" for index in indices)


def extract_pixels(clip: Path, indices: list[int],
                   container: dict[str, Any]) -> list[bytes]:
    """Return the raw RGB24 buffer for each requested frame index."""
    frame_bytes = container["width"] * container["height"] * 3
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error",
         "-i", str(clip),
         "-vf", f"select='{_select_expression(indices)}'",
         "-fps_mode", "passthrough", "-an",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    )
    payload = result.stdout
    if len(payload) != frame_bytes * len(indices):
        raise ValueError(
            f"expected {len(indices)} raw frames, got "
            f"{len(payload) / frame_bytes:.2f}"
        )
    return [payload[offset * frame_bytes:(offset + 1) * frame_bytes]
            for offset in range(len(indices))]


def render_frames(clip: Path, frames: list[dict[str, Any]],
                  target_dir: Path) -> None:
    """Write the viewing copies the reviewer actually opens."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for existing in target_dir.glob("frame-*.jpg"):
        existing.unlink()
    indices = [frame["index"] for frame in frames]
    _run([
        "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y",
        "-i", str(clip),
        "-vf", f"select='{_select_expression(indices)}'",
        "-fps_mode", "passthrough", "-an", "-q:v", "2",
        str(target_dir / "frame-%02d.jpg"),
    ])
    # ffmpeg numbers its output from 1; the manifest carries the real indices.
    for ordinal, frame in enumerate(frames, start=1):
        rendered = target_dir / f"frame-{ordinal:02d}.jpg"
        final = target_dir / f"frame-{ordinal - 1:02d}-t{frame['timestamp_s']:06.3f}.jpg"
        rendered.rename(final)
        frame["file"] = final.name


def render_contact_sheet(clip: Path, frames: list[dict[str, Any]],
                         target_dir: Path) -> dict[str, Any]:
    """Tile the whole strip into one image for judging the sequence.

    Frames are not captioned: this ffmpeg build has no ``drawtext`` filter, so
    a caption would need a second dependency to say what reading order already
    says. The layout is recorded in the manifest and stated to the reviewer
    instead.
    """
    indices = [frame["index"] for frame in frames]
    columns = SHEET_COLUMNS
    rows = -(-len(indices) // columns)
    sheet = target_dir / "contact-sheet.jpg"
    _run([
        "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y",
        "-i", str(clip),
        "-vf", (
            f"select='{_select_expression(indices)}',"
            f"scale={SHEET_TILE_WIDTH}:-2,"
            f"tile={columns}x{rows}:padding=6:margin=6:color=0x202020"
        ),
        "-fps_mode", "passthrough", "-an", "-frames:v", "1", "-q:v", "3",
        str(sheet),
    ])
    return {
        "file": sheet.name,
        "columns": columns,
        "rows": rows,
        "order": "left to right, then top to bottom; frame 0 is top left",
        "tile_width": SHEET_TILE_WIDTH,
    }


def detect_scene_cuts(clip: Path) -> list[dict[str, float]]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info",
         "-i", str(clip),
         "-vf", f"select='gt(scene,{SCENE_CUT_THRESHOLD})',metadata=print",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    cuts: list[dict[str, float]] = []
    pending: float | None = None
    for line in result.stderr.splitlines():
        timestamp = re.search(r"pts_time:([0-9.]+)", line)
        if timestamp:
            pending = float(timestamp.group(1))
        score = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if score and pending is not None:
            cuts.append({"timestamp_s": pending, "score": float(score.group(1))})
            pending = None
    return cuts


def _volume(clip: Path) -> dict[str, float | None]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    levels: dict[str, float | None] = {"max_dbfs": None, "mean_dbfs": None}
    for key, pattern in (("max_dbfs", "max_volume"), ("mean_dbfs", "mean_volume")):
        found = re.search(rf"{pattern}:\s*(-?[0-9.]+) dB", result.stderr)
        if found:
            levels[key] = float(found.group(1))
    return levels


def _sound_runs(clip: Path, duration: float) -> list[dict[str, float]]:
    """Invert silencedetect into the runs where the track is audible."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(clip),
         "-af", f"silencedetect=n={SILENCE_FLOOR_DBFS}dB:d={SILENCE_MIN_S}",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in result.stderr.splitlines():
        opened = re.search(r"silence_start:\s*(-?[0-9.]+)", line)
        if opened:
            start = max(0.0, float(opened.group(1)))
        closed = re.search(r"silence_end:\s*([0-9.]+)", line)
        if closed and start is not None:
            silences.append((start, float(closed.group(1))))
            start = None
    if start is not None:
        silences.append((start, duration))
    runs: list[dict[str, float]] = []
    cursor = 0.0
    for silence_start, silence_end in silences:
        if silence_start - cursor > 1e-3:
            runs.append({"start_s": round(cursor, 3),
                         "end_s": round(silence_start, 3)})
        cursor = max(cursor, silence_end)
    if duration - cursor > 1e-3:
        runs.append({"start_s": round(cursor, 3), "end_s": round(duration, 3)})
    return runs


def probe_audio(clip: Path, container: dict[str, Any]) -> dict[str, Any]:
    if not container["audio_streams"]:
        return {"stream_present": False, "max_dbfs": None, "mean_dbfs": None,
                "sound_runs": [], "first_sound_at_s": None}
    levels = _volume(clip)
    runs = _sound_runs(clip, container["duration_s"])
    return {
        "stream_present": True,
        **levels,
        "sound_runs": runs,
        "first_sound_at_s": runs[0]["start_s"] if runs else None,
    }


def mechanical_checks(clip_spec: dict[str, Any], container: dict[str, Any],
                      audio: dict[str, Any],
                      cuts: list[dict[str, float]]) -> list[dict[str, Any]]:
    """Decide the acceptance criteria that measurement settles better than sight."""
    checks: list[dict[str, Any]] = []

    checks.append({
        "criterion": "one_unbroken_take",
        "status": "fail" if cuts else "pass",
        "detail": (
            f"{len(cuts)} frame(s) score above {SCENE_CUT_THRESHOLD} on scene "
            f"change at {[cut['timestamp_s'] for cut in cuts]}"
            if cuts else
            f"no frame scores above {SCENE_CUT_THRESHOLD} on scene change"
        ),
    })

    mode = clip_spec["audio_mode"]
    if mode == "silent":
        peak = audio["max_dbfs"]
        if not audio["stream_present"] or peak is None:
            status, detail = "pass", "no audio stream"
        elif peak <= SILENT_MAX_DBFS:
            status = "pass"
            detail = f"peak {peak} dBFS is below the {SILENT_MAX_DBFS} dBFS floor"
        else:
            status = "fail"
            detail = (
                f"declared silent, but the track peaks at {peak} dBFS in "
                f"{len(audio['sound_runs'])} audible run(s). The generation "
                "prompt asked for no speech, no music, no sound effects and no "
                "room tone."
            )
        checks.append({"criterion": "audio_mode_silent", "status": status,
                       "detail": detail})
    elif mode == "narrated":
        if not audio["stream_present"] or not audio["sound_runs"]:
            checks.append({
                "criterion": "audio_mode_narrated", "status": "fail",
                "detail": "declared narrated, but the track carries no audible run",
            })
        else:
            checks.append({
                "criterion": "audio_mode_narrated", "status": "indeterminate",
                "detail": (
                    f"{len(audio['sound_runs'])} audible run(s); first begins at "
                    f"{audio['first_sound_at_s']} s. Whether the words match the "
                    "declared cue is not decidable by measurement and is not "
                    "claimed here."
                ),
            })

    checks.append({
        "criterion": "container_facts",
        "status": "pass",
        "detail": (
            f"{container['width']}x{container['height']} "
            f"{container['fps']:g} fps, {container['duration_s']} s, "
            f"{container['frame_count']} frames"
        ),
    })
    return checks


def declared_gold_timestamps(clip_spec: dict[str, Any]) -> list[float]:
    """Requested cue and boundary times, which are sampling hints only."""
    timestamps: list[float] = []
    audio = clip_spec.get("audio") or {}
    if audio.get("cue_at_s") is not None:
        timestamps.append(float(audio["cue_at_s"]))
    gold = clip_spec.get("gold") or {}
    if gold.get("boundary_at_s") is not None:
        timestamps.append(float(gold["boundary_at_s"]))
    return timestamps


def load_clip_specs(dataset_dir: Path) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for path in sorted((dataset_dir / "video" / "clips").glob("VU-*.json")):
        use_case = json.loads(path.read_text(encoding="utf-8"))
        for clip in use_case["clips"]:
            specs[clip["id"]] = {**clip, "use_case": use_case}
    return specs


def build(dataset_dir: Path, row: dict[str, str],
          clip_spec: dict[str, Any]) -> dict[str, Any]:
    clip = dataset_dir / row["output_path"]
    if not clip.is_file():
        raise FileNotFoundError(f"{row['clip_id']}: {clip} is not staged")
    clip_sha256 = hashlib.sha256(clip.read_bytes()).hexdigest()
    if row.get("output_sha256") and row["output_sha256"] != clip_sha256:
        raise ValueError(
            f"{row['clip_id']}: staged clip no longer matches its ledger hash"
        )

    container = probe_container(clip)
    frames = sample_indices(container, declared_gold_timestamps(clip_spec))
    pixels = extract_pixels(clip, [frame["index"] for frame in frames], container)
    for frame, buffer in zip(frames, pixels):
        frame["pixel_sha256"] = hashlib.sha256(buffer).hexdigest()

    strip_dir = dataset_dir / "video" / "strips" / row["clip_id"]
    render_frames(clip, frames, strip_dir)
    sheet = render_contact_sheet(clip, frames, strip_dir)

    audio = probe_audio(clip, container)
    cuts = detect_scene_cuts(clip)
    fingerprint = json.dumps(
        [[frame["index"], frame["timestamp_s"], frame["pixel_sha256"]]
         for frame in frames],
        separators=(",", ":"),
    )
    manifest = {
        "clip_id": row["clip_id"],
        "task_id": row["task_id"],
        "clip_sha256": clip_sha256,
        "strip_sha256": hashlib.sha256(fingerprint.encode()).hexdigest(),
        "sampler": {
            "version": SAMPLER_VERSION,
            "cadence_fps": CADENCE_FPS,
            "rule": "every whole second, the final frame, and every declared "
                    "gold timestamp",
            "hashed": "decoded RGB24 pixels, not the rendered JPEG files",
            "ffmpeg": _ffmpeg_version(),
        },
        "container": container,
        "contact_sheet": sheet,
        "audio": audio,
        "scene_cuts": cuts,
        "mechanical_checks": mechanical_checks(clip_spec, container, audio, cuts),
        "frames": frames,
    }
    (strip_dir / "strip.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def build_all(dataset_dir: Path,
              clip_ids: set[str] | None = None) -> list[dict[str, Any]]:
    with (dataset_dir / "video" / "tasks.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    specs = load_clip_specs(dataset_dir)
    manifests = []
    for row in rows:
        if clip_ids is not None and row["clip_id"] not in clip_ids:
            continue
        if not (dataset_dir / row["output_path"]).is_file():
            continue
        manifests.append(build(dataset_dir, row, specs[row["clip_id"]]))
    return manifests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--clip", action="append", dest="clips")
    args = parser.parse_args()
    manifests = build_all(args.dataset_dir,
                          set(args.clips) if args.clips else None)
    for manifest in manifests:
        failed = [check["criterion"] for check in manifest["mechanical_checks"]
                  if check["status"] == "fail"]
        print(f"{manifest['clip_id']:24} {len(manifest['frames']):2d} frames  "
              f"strip {manifest['strip_sha256'][:12]}  "
              f"{'mechanical fail: ' + ', '.join(failed) if failed else 'mechanical pass'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
