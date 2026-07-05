#!/usr/bin/env python3
"""Lightweight CLI to label room boundary timestamps on walkthrough video (docs/19).

Samples a thumbnail strip (same cadence as docs/11 / homeinventory.segment), writes
an editable boundaries JSON, and can compile it into segments.json for ingest and
ML-E1 eval. Optional HTML contact sheet for scrubbing by eye.

Usage:
    uv run python evals/label_segments.py strip VIDEO -o /tmp/seg-label \\
        --html /tmp/seg-label/scrub.html
    # edit boundaries.json: ordered {t_s, room} cuts from t=0
    uv run python evals/label_segments.py build /tmp/seg-label/boundaries.json \\
        -o /tmp/seg-label/segments.json
    uv run python evals/label_segments.py validate /tmp/seg-label/segments.json

Boundaries format (exported by ``strip``):

    {
      "video": "IMG_5512.MOV",
      "duration_s": 804.0,
      "every_s": 5.0,
      "boundaries": [
        {"t_s": 0.0, "room": "Hallway"},
        {"t_s": 42.5, "room": "Living Room"}
      ]
    }

Compiled segments match homeinventory.segment / docs/11:

    {"video": "...", "duration_s": ..., "source": "manual",
     "segments": [{"room": "...", "start_s": 0, "end_s": 42.5}, ...]}
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def clock(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def boundaries_to_segments(boundaries: list[dict], duration_s: float) -> list[dict]:
    """Convert ordered boundary list to contiguous segments."""
    if not boundaries:
        raise ValueError("boundaries list is empty")
    sorted_b = sorted(boundaries, key=lambda b: b["t_s"])
    if sorted_b[0]["t_s"] != 0.0:
        raise ValueError("first boundary must start at t_s=0.0")
    for i in range(1, len(sorted_b)):
        if sorted_b[i]["t_s"] <= sorted_b[i - 1]["t_s"]:
            raise ValueError("boundary timestamps must strictly increase")
    segments: list[dict] = []
    for i, b in enumerate(sorted_b):
        start = float(b["t_s"])
        end = float(duration_s if i + 1 == len(sorted_b)
                    else sorted_b[i + 1]["t_s"])
        room = str(b["room"]).strip()
        if not room:
            raise ValueError(f"empty room name at t_s={start}")
        segments.append({
            "room": room,
            "start_s": round(start, 3),
            "end_s": round(end, 3),
        })
    return segments


def validate_segments(data: dict) -> list[str]:
    """Return list of validation errors (empty if ok)."""
    errs: list[str] = []
    segs = data.get("segments")
    if not isinstance(segs, list) or not segs:
        return ["missing or empty 'segments' array"]
    duration = data.get("duration_s")
    if duration is None:
        errs.append("missing duration_s")
        duration = segs[-1].get("end_s", 0)
    prev_end = None
    for i, s in enumerate(segs):
        for key in ("room", "start_s", "end_s"):
            if key not in s:
                errs.append(f"segment[{i}] missing {key}")
        if "room" in s and not str(s["room"]).strip():
            errs.append(f"segment[{i}] empty room name")
        try:
            start, end = float(s["start_s"]), float(s["end_s"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            errs.append(f"segment[{i}] end_s must exceed start_s")
        if prev_end is not None and abs(start - prev_end) > 0.05:
            errs.append(f"segment[{i}] gap/overlap at {start}s (prev end {prev_end}s)")
        prev_end = end
    if prev_end is not None and duration is not None:
        if abs(float(prev_end) - float(duration)) > 0.05:
            errs.append(f"last segment end {prev_end}s != duration {duration}s")
    return errs


def assign_segment(t_s: float, segments: list[dict]) -> str | None:
    for s in segments:
        if s["start_s"] <= t_s < s["end_s"]:
            return s["room"]
    if segments and abs(t_s - segments[-1]["end_s"]) < 0.01:
        return segments[-1]["room"]
    return None


def render_scrub_html(
        *,
        html_path: Path,
        video_name: str,
        duration_s: float,
        every_s: float,
        frame_entries: list[tuple[float, Path]],
        segments: list[dict] | None,
        boundaries_path: Path | None,
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_ts = {s["start_s"] for s in (segments or [])}

    parts = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        f"<title>Segment scrub — {html.escape(video_name)}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:1rem;background:#111;color:#eee}",
        "h1,h2{margin:0.5rem 0}",
        ".meta{color:#aaa;font-size:14px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}",
        ".cell{background:#222;border-radius:6px;overflow:hidden;border:2px solid #333}",
        ".cell.boundary{border-color:#f55}",
        ".cell img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover}",
        ".cap{padding:6px;font-size:11px;line-height:1.3}",
        ".room{color:#8cf}",
        "pre{background:#222;padding:12px;border-radius:8px;overflow:auto;font-size:12px}",
        "</style></head><body>",
        f"<h1>Segment labelling — {html.escape(video_name)}</h1>",
        f"<p class='meta'>{duration_s:.0f}s total · sampled every {every_s:.0f}s · "
        f"{len(frame_entries)} frames</p>",
    ]
    if boundaries_path:
        parts.append(
            f"<p class='meta'>Edit boundaries: "
            f"<code>{html.escape(str(boundaries_path))}</code> "
            f"then run <code>label_segments.py build</code>.</p>"
        )
    parts.append("<h2>Instructions</h2><ol>"
                 "<li>Scrub frames below; note timestamps at each room change.</li>"
                 "<li>Add <code>{\"t_s\": seconds, \"room\": \"Kitchen\"}</code> "
                 "entries to <code>boundaries</code> in sorted order; first must be "
                 "<code>t_s: 0.0</code>.</li>"
                 "<li>Run <code>build</code> to emit segments.json compatible with "
                 "docs/11 / ingest.</li></ol>")

    if segments:
        parts.append("<h2>Current segments</h2><pre>")
        for s in segments:
            parts.append(html.escape(
                f"{clock(s['start_s']):>6}–{clock(s['end_s']):<6} {s['room']}"))
        parts.append("</pre>")

    parts.append("<h2>Frame strip</h2><div class='grid'>")
    for t_s, img_path in frame_entries:
        is_boundary = t_s in boundary_ts or (t_s == 0.0)
        room = assign_segment(t_s, segments) if segments else None
        try:
            href = html.escape(str(img_path.relative_to(html_path.parent)))
        except ValueError:
            href = html.escape(str(img_path))
        cls = " cell boundary" if is_boundary else " cell"
        room_txt = f"<span class='room'>{html.escape(room)}</span><br>" if room else ""
        parts.extend([
            f"<div class='{cls.strip()}'>",
            f"<img src='{href}' alt='t={t_s:.0f}s' loading='lazy'>",
            f"<div class='cap'>{room_txt}t={t_s:.1f}s ({clock(t_s)})</div>",
            "</div>",
        ])
    parts.append("</div></body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def cmd_strip(args: argparse.Namespace) -> int:
    video = args.video.resolve()
    if not video.is_file():
        print(f"video not found: {video}", file=sys.stderr)
        return 1

    try:
        from homeinventory.segment import sample_strip, video_duration_s
    except ImportError as e:
        print("opencv required: uv pip install opencv-python-headless", file=sys.stderr)
        print(e, file=sys.stderr)
        return 1

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    strip_dir = out_dir / "strip"
    strip_dir.mkdir(parents=True, exist_ok=True)

    duration = video_duration_s(video)
    frames = sample_strip(video, every_s=args.every, width=args.width)
    if not frames:
        print("no frames sampled", file=sys.stderr)
        return 1

    frame_entries: list[tuple[float, Path]] = []
    for f in frames:
        p = strip_dir / f"t{int(round(f.t_s)):05d}.jpg"
        p.write_bytes(f.jpeg)
        frame_entries.append((f.t_s, p))

    boundaries_path = out_dir / "boundaries.json"
    if boundaries_path.exists() and not args.force:
        data = load_json(boundaries_path)
    else:
        data = {
            "video": video.name,
            "duration_s": round(duration, 3),
            "every_s": args.every,
            "source": "manual",
            "boundaries": [
                {"t_s": 0.0, "room": "CHANGE ME — first room name"},
            ],
            "notes": "Add one entry per room segment start (sorted by t_s). "
                     "Last segment runs until duration_s.",
        }
        save_json(boundaries_path, data)

    segments = None
    if args.boundaries:
        bdata = load_json(args.boundaries.resolve())
        segments = boundaries_to_segments(bdata["boundaries"], float(bdata["duration_s"]))

    html_path = (args.html or out_dir / "scrub.html").resolve()
    render_scrub_html(
        html_path=html_path,
        video_name=video.name,
        duration_s=duration,
        every_s=args.every,
        frame_entries=frame_entries,
        segments=segments,
        boundaries_path=boundaries_path,
    )

    print(f"sampled {len(frames)} frames over {duration:.0f}s")
    print(f"  strip     {strip_dir}/")
    print(f"  boundaries {boundaries_path}")
    print(f"  html      {html_path}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    bpath = args.boundaries.resolve()
    data = load_json(bpath)
    duration = float(data["duration_s"])
    segments = boundaries_to_segments(data["boundaries"], duration)
    out = {
        "video": data.get("video", ""),
        "duration_s": round(duration, 3),
        "every_s": data.get("every_s"),
        "source": data.get("source", "manual"),
        "labeler": data.get("labeler"),
        "notes": data.get("notes"),
        "segments": segments,
    }
    errs = validate_segments(out)
    if errs:
        for e in errs:
            print(f"warning: {e}", file=sys.stderr)
    out_path = args.output.resolve()
    save_json(out_path, out)
    print(f"wrote {len(segments)} segments → {out_path}")
    for s in segments:
        print(f"  {clock(s['start_s']):>6}–{clock(s['end_s']):<6} {s['room']}")
    return 0 if not errs else 1


def cmd_validate(args: argparse.Namespace) -> int:
    data = load_json(args.segments.resolve())
    errs = validate_segments(data)
    if errs:
        for e in errs:
            print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"ok — {len(data['segments'])} segments, "
          f"duration {data.get('duration_s')}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    strip = sub.add_parser("strip", help="sample video strip + boundaries template")
    strip.add_argument("video", type=Path, help="walkthrough video file")
    strip.add_argument("-o", "--output", type=Path, default=Path("segment-label"),
                       help="output directory (default: segment-label/)")
    strip.add_argument("--every", type=float, default=5.0,
                       help="sample interval in seconds (default: 5)")
    strip.add_argument("--width", type=int, default=448,
                       help="thumbnail width px (default: 448)")
    strip.add_argument("--html", type=Path, default=None,
                       help="HTML scrub sheet path (default: OUTPUT/scrub.html)")
    strip.add_argument("--boundaries", type=Path, default=None,
                       help="optional boundaries JSON to preview segments in HTML")
    strip.add_argument("--force", action="store_true",
                       help="overwrite existing boundaries.json template")
    strip.set_defaults(func=cmd_strip)

    build = sub.add_parser("build", help="compile boundaries.json → segments.json")
    build.add_argument("boundaries", type=Path, help="boundaries.json from strip")
    build.add_argument("-o", "--output", type=Path, default=None,
                       help="segments.json path (default: same dir as boundaries)")
    build.set_defaults(func=cmd_build)

    val = sub.add_parser("validate", help="validate segments.json")
    val.add_argument("segments", type=Path, help="segments.json")
    val.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    if args.cmd == "build" and args.output is None:
        args.output = args.boundaries.parent / "segments.json"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
