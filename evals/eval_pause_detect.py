#!/usr/bin/env python3
"""ML-E9: optical-flow pause detection vs hero-gold (docs/19 §1.3 I).

Samples a walkthrough video, computes frame-to-frame optical-flow magnitude,
and flags low-motion *pause* windows. Scores whether hero-gold top-3
establishing frames fall in pause regions (proxy for intentional holds).

Pass bar: ≥80% of gold top-3 frames classified as pause (low flow in segment).

Outputs:
  evals/fixtures/own-property/pause-timeline.html
  evals/fixtures/own-property/pause-detect-metrics.json

Usage:
    uv run python evals/eval_pause_detect.py
    uv run python evals/eval_pause_detect.py examples/videos/IMG_5512.MOV report
    uv run python evals/eval_pause_detect.py --demo
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_hero_cover import (  # noqa: E402
    load_gold,
    load_rooms,
)

DEFAULT_VIDEO = ROOT / "examples/videos/IMG_5512.MOV"
DEFAULT_GOLD = ROOT / "evals/fixtures/own-property/hero-gold.json"
DEFAULT_SEGMENT_GOLD = ROOT / "evals/fixtures/own-property/segment-gold.json"
DEFAULT_HTML = ROOT / "evals/fixtures/own-property/pause-timeline.html"
DEFAULT_JSON = ROOT / "evals/fixtures/own-property/pause-detect-metrics.json"
PASS_BAR = 0.80
FRAME_RE = re.compile(r"_f(\d{6})\.jpe?g$", re.IGNORECASE)


@dataclass
class FlowSample:
    t_s: float
    frame_idx: int
    magnitude: float


def parse_frame_index(name: str) -> int | None:
    m = FRAME_RE.search(name)
    return int(m.group(1)) if m else None


def frame_index_to_t(frame_idx: int, fps: float) -> float:
    return round(frame_idx / fps, 3)


def load_segment_ranges(path: Path) -> list[tuple[str, float, float]]:
    """[(room, start_s, end_s)] from segment-gold.json."""
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rooms = data.get("rooms") or []
    duration = float(data.get("duration_s") or 0)
    out: list[tuple[str, float, float]] = []
    for i, room in enumerate(rooms):
        start = float(room.get("start_s", 0))
        end = (
            float(rooms[i + 1]["start_s"])
            if i + 1 < len(rooms)
            else duration or start + 60
        )
        out.append((room.get("room", f"seg_{i}"), start, end))
    return out


def segment_for_time(ranges: list[tuple[str, float, float]], t_s: float) -> str | None:
    for name, start, end in ranges:
        if start <= t_s < end:
            return name
    return ranges[-1][0] if ranges else None


def compute_flow_timeline(
        video: Path,
        *,
        every_s: float = 0.5,
        width: int = 320,
) -> tuple[list[FlowSample], float]:
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(every_s * fps)))
        samples: list[FlowSample] = []
        prev_gray: np.ndarray | None = None
        fidx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if fidx % step != 0:
                fidx += 1
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, int(h * width / w)))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            t_s = round(fidx / fps, 3)
            if prev_gray is not None and prev_gray.shape == gray.shape:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, gray, None,
                    pyr_scale=0.5, levels=3, winsize=15,
                    iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
                )
                mag = float(np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2).mean())
            else:
                mag = float("nan")
            samples.append(FlowSample(t_s=t_s, frame_idx=fidx, magnitude=mag))
            prev_gray = gray
            fidx += 1
    finally:
        cap.release()
    return samples, fps


def synthetic_flow_timeline(n: int = 120, every_s: float = 0.5) -> tuple[list[FlowSample], float]:
    """Demo timeline with pause valleys at ~25%, 50%, 75%."""
    fps = 30.0
    pause_centers = [n // 4, n // 2, 3 * n // 4]
    samples: list[FlowSample] = []
    for i in range(n):
        base = 4.0 + 2.0 * math.sin(i / 8.0)
        for c in pause_centers:
            base += 6.0 * math.exp(-((i - c) ** 2) / 18.0)
        mag = max(0.05, base)
        fidx = i * int(every_s * fps)
        samples.append(FlowSample(t_s=round(i * every_s, 3), frame_idx=fidx, magnitude=mag))
    return samples, fps


def nearest_sample(samples: list[FlowSample], t_s: float) -> FlowSample | None:
    if not samples:
        return None
    return min(samples, key=lambda s: abs(s.t_s - t_s))


def pause_threshold_for_segment(
        samples: list[FlowSample],
        seg_ranges: list[tuple[str, float, float]],
        seg_name: str,
        percentile: float = 0.30,
) -> float:
    mags = [
        s.magnitude for s in samples
        if not math.isnan(s.magnitude)
        and segment_for_time(seg_ranges, s.t_s) == seg_name
    ]
    if not mags:
        mags = [s.magnitude for s in samples if not math.isnan(s.magnitude)]
    if not mags:
        return 0.0
    mags_sorted = sorted(mags)
    idx = max(0, min(len(mags_sorted) - 1, int(percentile * len(mags_sorted))))
    return mags_sorted[idx]


def collect_gold_frames(
        gold: dict[str, dict],
        rooms: list[tuple[str, list[dict]]],
        fps: float,
) -> list[dict]:
    """Gold top-3 frames with timestamps and room."""
    room_map = {name: frames for name, frames in rooms}
    out: list[dict] = []
    for room_name, gold_room in gold.items():
        frames = room_map.get(room_name, [])
        names = {Path(f["path"]).name for f in frames}
        for rank, fname in enumerate(gold_room.get("top", [])[:3], start=1):
            if fname not in names:
                continue
            fidx = parse_frame_index(fname)
            if fidx is None:
                continue
            out.append({
                "room": room_name,
                "name": fname,
                "gold_rank": rank,
                "frame_idx": fidx,
                "t_s": frame_index_to_t(fidx, fps),
            })
    return out


def evaluate_pause_detection(
        *,
        samples: list[FlowSample],
        gold_frames: list[dict],
        seg_ranges: list[tuple[str, float, float]],
        rooms: list[tuple[str, list[dict]]],
        fps: float,
) -> dict:
    valid = [s for s in samples if not math.isnan(s.magnitude)]
    if not valid:
        return {"error": "no flow samples"}

    per_room_ranked: dict[str, list[tuple[str, float]]] = {}
    for room_name, frames in rooms:
        scored: list[tuple[str, float]] = []
        for fr in frames:
            fname = Path(fr["path"]).name
            fidx = parse_frame_index(fname)
            if fidx is None:
                continue
            t_s = frame_index_to_t(fidx, fps)
            samp = nearest_sample(valid, t_s)
            mag = samp.magnitude if samp else float("nan")
            scored.append((fname, mag))
        scored.sort(key=lambda x: (math.isnan(x[1]), x[1]))
        per_room_ranked[room_name] = scored

    pause_hits = 0
    flow_top3_hits = 0
    gold_evaluated = 0
    gold_details: list[dict] = []

    for gf in gold_frames:
        room = gf["room"]
        fname = gf["name"]
        t_s = gf["t_s"]
        samp = nearest_sample(valid, t_s)
        mag = samp.magnitude if samp else float("nan")
        seg = segment_for_time(seg_ranges, t_s) if seg_ranges else room
        thresh = pause_threshold_for_segment(valid, seg_ranges, seg or room)
        is_pause = not math.isnan(mag) and mag <= thresh
        ranked = per_room_ranked.get(room, [])
        flow_top3 = {n for n, _ in ranked[:3]}
        in_flow_top3 = fname in flow_top3
        gold_evaluated += 1
        pause_hits += int(is_pause)
        flow_top3_hits += int(in_flow_top3)
        gold_details.append({
            "room": room,
            "name": fname,
            "gold_rank": gf["gold_rank"],
            "t_s": t_s,
            "flow_magnitude": round(mag, 4) if not math.isnan(mag) else None,
            "pause_threshold": round(thresh, 4),
            "is_pause": is_pause,
            "in_flow_top3": in_flow_top3,
        })

    recall = pause_hits / gold_evaluated if gold_evaluated else 0.0
    top3_rate = flow_top3_hits / gold_evaluated if gold_evaluated else 0.0

    return {
        "n_flow_samples": len(valid),
        "n_gold_top3_evaluated": gold_evaluated,
        "gold_top3_pause_recall": round(recall, 3),
        "gold_top3_in_flow_top3_rate": round(top3_rate, 3),
        "pass_bar_gold_top3_pause_recall": PASS_BAR,
        "pass": recall >= PASS_BAR,
        "gold_details": gold_details,
        "per_room_flow_top3": {
            room: [n for n, _ in ranked[:3]]
            for room, ranked in per_room_ranked.items()
        },
    }


def render_timeline_html(
        *,
        html_path: Path,
        samples: list[FlowSample],
        metrics: dict,
        gold_frames: list[dict],
        video: Path | None,
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    valid = [s for s in samples if not math.isnan(s.magnitude)]
    max_mag = max((s.magnitude for s in valid), default=1.0)
    gold_by_t = {gf["t_s"]: gf for gf in gold_frames}

    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>ML-E9 pause detection timeline</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:1rem;background:#111;color:#eee}",
        ".summary{background:#222;padding:1rem;border-radius:8px;margin-bottom:1.5rem}",
        ".chart{display:flex;align-items:flex-end;gap:1px;height:120px;margin:1rem 0}",
        ".bar{background:#4a9;min-width:2px;flex:1}",
        ".bar.pause{background:#f5c518}",
        ".bar.gold{outline:2px solid #fff}",
        "table{border-collapse:collapse;width:100%}",
        "td,th{border:1px solid #444;padding:6px;text-align:left;font-size:13px}",
        "</style></head><body>",
        "<h1>ML-E9 — optical-flow pause detection</h1>",
    ]
    if video:
        parts.append(f"<p>Video: {html.escape(str(video))}</p>")
    parts.extend([
        "<div class='summary'><h2>Metrics</h2><pre>",
        html.escape(json.dumps(
            {k: v for k, v in metrics.items() if k != "gold_details"},
            indent=2,
        )),
        "</pre></div>",
        "<h2>Motion magnitude (low = pause)</h2>",
        "<div class='chart'>",
    ])

    pause_thresh = 0.0
    if metrics.get("eval", {}).get("gold_details"):
        th = [d["pause_threshold"] for d in metrics["eval"]["gold_details"]
              if d.get("pause_threshold") is not None]
        pause_thresh = sum(th) / len(th) if th else 0.0

    for s in valid:
        h = int(100 * s.magnitude / max_mag) + 4
        cls = "bar"
        if s.magnitude <= pause_thresh:
            cls += " pause"
        for gf in gold_frames:
            if abs(gf["t_s"] - s.t_s) < 0.6:
                cls += " gold"
                break
        parts.append(
            f"<div class='{cls}' style='height:{h}px' "
            f"title='t={s.t_s:.1f}s mag={s.magnitude:.3f}'></div>"
        )
    parts.append("</div>")

    parts.append("<h2>Gold top-3 vs pause</h2><table>")
    parts.append("<tr><th>Room</th><th>Frame</th><th>t (s)</th>"
                 "<th>Flow</th><th>Pause?</th><th>Flow top-3?</th></tr>")
    for d in metrics.get("eval", {}).get("gold_details", []):
        parts.append(
            f"<tr><td>{html.escape(d['room'])}</td>"
            f"<td>{html.escape(d['name'])}</td>"
            f"<td>{d['t_s']:.1f}</td>"
            f"<td>{d.get('flow_magnitude', '—')}</td>"
            f"<td>{'yes' if d.get('is_pause') else 'no'}</td>"
            f"<td>{'yes' if d.get('in_flow_top3') else 'no'}</td></tr>"
        )
    parts.append("</table></body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    t0 = time.perf_counter()
    gold = load_gold(args.gold)
    seg_ranges = load_segment_ranges(args.segment_gold)
    rooms: list[tuple[str, list[dict]]] = []
    if args.report_dir and (args.report_dir / "inventory.json").is_file():
        rooms = load_rooms(args.report_dir.resolve())

    mode = "demo"
    video_path: Path | None = None
    samples: list[FlowSample] = []
    fps = 30.0

    if args.demo:
        samples, fps = synthetic_flow_timeline(n=120, every_s=args.every)
        mode = "synthetic"
    else:
        video_path = Path(args.video) if args.video else DEFAULT_VIDEO
        if video_path.is_file():
            try:
                samples, fps = compute_flow_timeline(
                    video_path, every_s=args.every, width=args.width,
                )
                mode = "video"
            except ImportError as exc:
                print(str(exc), file=sys.stderr)
                samples, fps = synthetic_flow_timeline(n=120, every_s=args.every)
                mode = "synthetic-fallback"
        else:
            print(f"video not found: {video_path} — synthetic demo", file=sys.stderr)
            samples, fps = synthetic_flow_timeline(n=120, every_s=args.every)
            mode = "synthetic-fallback"

    gold_frames = collect_gold_frames(gold, rooms, fps) if gold and rooms else []
    if args.demo and not gold_frames:
        # synthetic gold aligned with pause valleys
        for i, center in enumerate([30, 60, 90]):
            gold_frames.append({
                "room": f"Demo_{i}",
                "name": f"demo_f{center:06d}.jpg",
                "gold_rank": 1,
                "frame_idx": center * int(fps * args.every),
                "t_s": center * args.every,
            })

    eval_metrics = evaluate_pause_detection(
        samples=samples,
        gold_frames=gold_frames,
        seg_ranges=seg_ranges,
        rooms=rooms,
        fps=fps,
    ) if gold_frames else {"n_gold_top3_evaluated": 0, "pass": None}

    elapsed = round(time.perf_counter() - t0, 2)
    metrics: dict = {
        "experiment": "ML-E9",
        "mode": mode,
        "every_s": args.every,
        "fps": round(fps, 2),
        "n_flow_samples": len(samples),
        "timing_s": elapsed,
        "eval": eval_metrics,
        "pass_bar_gold_top3_pause_recall": PASS_BAR,
        "pass": eval_metrics.get("pass"),
    }
    if video_path:
        metrics["video"] = str(video_path)
    if args.report_dir:
        metrics["report_dir"] = str(args.report_dir)

    args.html_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    render_timeline_html(
        html_path=args.html_output,
        samples=samples,
        metrics=metrics,
        gold_frames=gold_frames,
        video=video_path,
    )
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video", nargs="?", default=None,
                    help="walkthrough video (default: examples/videos/IMG_5512.MOV)")
    ap.add_argument("report_dir", nargs="?", type=Path, default=Path("report"),
                    help="build output for hero-gold frame names")
    ap.add_argument("--demo", action="store_true",
                    help="synthetic motion timeline (no video)")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--segment-gold", type=Path, default=DEFAULT_SEGMENT_GOLD)
    ap.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--every", type=float, default=0.5,
                    help="sample interval in seconds")
    ap.add_argument("--width", type=int, default=320,
                    help="resize width for optical flow")
    args = ap.parse_args()
    metrics = run(args)
    summary = {k: v for k, v in metrics.items() if k != "eval"}
    if metrics.get("eval"):
        summary.update({
            k: metrics["eval"][k]
            for k in ("gold_top3_pause_recall", "pass", "n_gold_top3_evaluated")
            if k in metrics["eval"]
        })
    print(json.dumps(summary, indent=2))
    print(f"wrote {args.html_output.resolve()}")
    print(f"wrote {args.json_output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
