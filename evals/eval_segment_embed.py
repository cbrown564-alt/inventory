#!/usr/bin/env python3
"""ML-E1: embedding changepoint segmentation vs manual gold (docs/19).

DINOv2 (timm) or OpenCLIP frame embeddings; peak-pick on consecutive cosine
distance for room boundaries. Compares detected cuts to
evals/fixtures/own-property/segment-gold.json when present.

Outputs evals/fixtures/own-property/segment-embed.html (contact sheet) or
segment-embed-metrics.json when video/thumbnails unavailable.

Pass bar: mean boundary error ≤ 3 s vs manual cuts.

Usage:
    uv run python evals/eval_segment_embed.py
    uv run python evals/eval_segment_embed.py examples/videos/IMG_5512.MOV
    uv run python evals/eval_segment_embed.py --demo
    uv run python evals/eval_segment_embed.py VIDEO --encoder dinov2 --every 2
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_GOLD = ROOT / "evals/fixtures/own-property/segment-gold.json"
DEFAULT_VIDEO = ROOT / "examples/videos/IMG_5512.MOV"
DEFAULT_OUT_HTML = ROOT / "evals/fixtures/own-property/segment-embed.html"
DEFAULT_OUT_JSON = ROOT / "evals/fixtures/own-property/segment-embed-metrics.json"
PASS_BAR_S = 3.0


@dataclass
class SampledFrame:
    t_s: float
    jpeg: bytes


def load_segment_gold(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def gold_boundaries_s(gold: dict) -> list[float]:
    """Interior boundary timestamps (exclude 0 and final end)."""
    rooms = gold.get("rooms") or []
    starts = [float(r["start_s"]) for r in rooms if "start_s" in r]
    if len(starts) <= 1:
        return []
    return starts[1:]


def boundary_errors(detected: list[float], reference: list[float]) -> list[float]:
    """Greedy nearest-neighbour match errors (seconds)."""
    if not detected or not reference:
        return []
    ref = sorted(reference)
    det = sorted(detected)
    used: set[int] = set()
    errors: list[float] = []
    for d in det:
        best_i, best_err = None, math.inf
        for i, r in enumerate(ref):
            if i in used:
                continue
            err = abs(d - r)
            if err < best_err:
                best_i, best_err = i, err
        if best_i is not None:
            used.add(best_i)
            errors.append(best_err)
    for i, r in enumerate(ref):
        if i not in used:
            errors.append(min(abs(r - d) for d in det) if det else r)
    return errors


def try_sample_video(video: Path, every_s: float, width: int) -> list[SampledFrame]:
    try:
        import cv2
    except ImportError as e:
        raise ImportError(
            "opencv-python-headless required for video mode:\n"
            "  uv pip install opencv-python-headless"
        ) from e

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    frames: list[SampledFrame] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(every_s * fps)))
        for fidx in range(0, n, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, int(h * width / w)))
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                frames.append(SampledFrame(t_s=round(fidx / fps, 2),
                                           jpeg=bytes(buf)))
    finally:
        cap.release()
    return frames


def synthetic_frames(n: int = 32, every_s: float = 5.0) -> list[SampledFrame]:
    """Colour-shift JPEGs for demo mode without a video file."""
    from PIL import Image
    import io

    frames: list[SampledFrame] = []
    boundaries = [8, 18, 26]
    for i in range(n):
        hue = (i * 37) % 256
        if i in boundaries:
            hue = (hue + 120) % 256
        img = Image.new("RGB", (448, 252), color=(hue, 128, 255 - hue))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72)
        frames.append(SampledFrame(t_s=round(i * every_s, 2),
                                   jpeg=buf.getvalue()))
    return frames


def embed_strip(frames: list[SampledFrame], encoder: str, device: str):
    from evals.ml_scorers import FrameEmbedder, cosine_distance

    embedder = FrameEmbedder(backend=encoder, device=device)
    vecs = [embedder.embed_jpeg(f.jpeg) for f in frames]
    distances = [cosine_distance(vecs[i], vecs[i + 1])
                 for i in range(len(vecs) - 1)]
    return distances


def demo_distances(frames: list[SampledFrame]) -> list[float]:
    from evals.ml_scorers import synthetic_demo_distances

    n = len(frames)
    b = [max(1, n // 4), max(2, n // 2), max(3, 3 * n // 4)]
    return synthetic_demo_distances(n, boundaries=b)


def peaks_to_boundary_times(
        frames: list[SampledFrame],
        peaks: list[int],
        every_s: float,
) -> list[float]:
    """Convert distance peak indices to seconds (midpoint between frames)."""
    out: list[float] = []
    for p in peaks:
        if p + 1 >= len(frames):
            continue
        t = (frames[p].t_s + frames[p + 1].t_s) / 2.0
        out.append(round(t, 2))
    return out


def assign_segments(frames: list[SampledFrame],
                    boundary_times: list[float]) -> list[tuple[str, list[int]]]:
    cuts = sorted(boundary_times)
    labels: list[tuple[str, list[int]]] = []
    seg_idx = 0
    current: list[int] = []
    cut_ptr = 0
    for i, f in enumerate(frames):
        while cut_ptr < len(cuts) and f.t_s >= cuts[cut_ptr]:
            labels.append((f"segment_{seg_idx:02d}", current))
            current = []
            seg_idx += 1
            cut_ptr += 1
        current.append(i)
    labels.append((f"segment_{seg_idx:02d}", current))
    return labels


def clock(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def render_html(
        *,
        out_path: Path,
        frames: list[SampledFrame],
        segments: list[tuple[str, list[int]]],
        distances: list[float],
        peaks: list[int],
        metrics: dict,
        strip_dir: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    strip_dir.mkdir(parents=True, exist_ok=True)
    names: dict[int, str] = {}
    for i, f in enumerate(frames):
        p = strip_dir / f"t{int(round(f.t_s)):05d}.jpg"
        p.write_bytes(f.jpeg)
        names[i] = f"{strip_dir.name}/{p.name}"

    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>ML-E1 segment embed</title>",
        "<style>",
        "body{font:14px system-ui;margin:24px;background:#111;color:#eee}",
        ".summary{background:#222;padding:1rem;border-radius:8px;margin-bottom:1.5rem}",
        "h2{margin:28px 0 8px}.meta{color:#aaa}",
        ".row{display:flex;flex-wrap:wrap;gap:6px}",
        "figure{margin:0;width:150px}img{width:150px;border-radius:4px;display:block}",
        "figcaption{font-size:11px;color:#bbb;text-align:center}",
        ".boundary img{outline:3px solid #d33}",
        ".boundary figcaption{color:#f5c518;font-weight:600}",
        ".chart{margin:1rem 0;height:80px;display:flex;align-items:flex-end;gap:1px}",
        ".bar{background:#4a9;min-width:3px}",
        ".bar.peak{background:#d33}",
        "</style></head><body>",
        "<h1>ML-E1 — embedding changepoint segmentation</h1>",
        "<div class='summary'><h2>Metrics</h2><pre>",
        html.escape(json.dumps(metrics, indent=2)),
        "</pre></div>",
        "<h2>Distance strip</h2>",
        "<div class='chart'>",
    ]
    max_d = max(distances) if distances else 1.0
    for i, d in enumerate(distances):
        h = int(70 * d / max_d) + 4
        cls = "bar peak" if i in peaks else "bar"
        parts.append(f"<div class='{cls}' style='height:{h}px' "
                     f"title='t≈{frames[i].t_s:.0f}s d={d:.3f}'></div>")
    parts.append("</div>")

    for seg_name, idxs in segments:
        if not idxs:
            continue
        t0, t1 = frames[idxs[0]].t_s, frames[idxs[-1]].t_s
        parts.append(f"<h2>{html.escape(seg_name)}</h2>")
        parts.append(f"<p class='meta'>{clock(t0)}–{clock(t1)} "
                     f"({len(idxs)} frames)</p><div class='row'>")
        for j, i in enumerate(idxs):
            cls = " class='boundary'" if j == 0 else ""
            parts.append(
                f"<figure{cls}><img src='{html.escape(names[i])}' loading='lazy'>"
                f"<figcaption>{clock(frames[i].t_s)}</figcaption></figure>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    gold = load_segment_gold(args.gold)
    ref_bounds = gold_boundaries_s(gold) if gold else []

    mode = "demo"
    video_path: Path | None = None
    frames: list[SampledFrame] = []

    if args.demo:
        frames = synthetic_frames(n=32, every_s=args.every)
        mode = "synthetic"
    else:
        video_path = Path(args.video) if args.video else DEFAULT_VIDEO
        if video_path.is_file():
            try:
                frames = try_sample_video(video_path, args.every, args.width)
                mode = "video"
            except ImportError as e:
                print(str(e), file=sys.stderr)
                frames = synthetic_frames(n=32, every_s=args.every)
                mode = "synthetic-fallback"
        else:
            print(f"video not found: {video_path} — using synthetic demo mode",
                  file=sys.stderr)
            frames = synthetic_frames(n=32, every_s=args.every)
            mode = "synthetic-fallback"

    use_torch = not args.no_torch and mode != "demo"
    distances: list[float]
    encoder_used = args.encoder

    if use_torch:
        try:
            distances = embed_strip(frames, args.encoder, args.device)
        except ImportError as e:
            print(str(e), file=sys.stderr)
            distances = demo_distances(frames)
            encoder_used = "synthetic-distance"
            mode = f"{mode}+no-torch"
    else:
        distances = demo_distances(frames)
        encoder_used = "synthetic-distance"

    from evals.ml_scorers import detect_changepoints

    peaks = detect_changepoints(distances)
    detected = peaks_to_boundary_times(frames, peaks, args.every)
    segments = assign_segments(frames, detected)

    errors = boundary_errors(detected, ref_bounds) if ref_bounds else []
    mean_err = round(sum(errors) / len(errors), 2) if errors else None

    metrics: dict = {
        "experiment": "ML-E1",
        "mode": mode,
        "encoder": encoder_used,
        "n_frames": len(frames),
        "every_s": args.every,
        "n_detected_boundaries": len(detected),
        "detected_boundaries_s": detected,
        "pass_bar_mean_error_s": PASS_BAR_S,
    }
    if video_path:
        metrics["video"] = str(video_path)
    if gold:
        metrics["gold_video"] = gold.get("video")
        metrics["reference_boundaries_s"] = ref_bounds
        metrics["boundary_errors_s"] = [round(e, 2) for e in errors]
        metrics["mean_boundary_error_s"] = mean_err
        metrics["pass"] = mean_err is not None and mean_err <= PASS_BAR_S

    if args.output.suffix.lower() == ".json":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    else:
        strip_dir = args.output.parent / "segment-embed-strip"
        render_html(
            out_path=args.output,
            frames=frames,
            segments=segments,
            distances=distances,
            peaks=peaks,
            metrics=metrics,
            strip_dir=strip_dir,
        )
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video", nargs="?", default=None,
                    help="walkthrough video (default: examples/videos/IMG_5512.MOV)")
    ap.add_argument("--demo", action="store_true",
                    help="synthetic colour frames (no video/opencv)")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD,
                    help="segment-gold.json with manual boundary starts")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT_HTML,
                    help="HTML contact sheet or .json metrics path")
    ap.add_argument("--encoder", choices=["dinov2", "openclip"], default="dinov2",
                    help="Apache-2.0 frame encoder")
    ap.add_argument("--every", type=float, default=5.0,
                    help="sample interval in seconds")
    ap.add_argument("--width", type=int, default=448,
                    help="thumbnail width for strip")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-torch", action="store_true",
                    help="skip torch encoders; use synthetic distance demo")
    args = ap.parse_args()

    metrics = run(args)
    print(json.dumps({k: v for k, v in metrics.items()
                      if k not in ("detected_boundaries_s",)}, indent=2))
    print(f"wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
