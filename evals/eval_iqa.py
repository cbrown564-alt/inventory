#!/usr/bin/env python3
"""Benchmark learned no-reference IQA models against the classical curation gate.

Scores every video frame of an existing build with the classical gate
(curate.frame_quality: Laplacian sharpness × exposure penalty) and with
pyiqa pretrained models (MUSIQ, CLIP-IQA, …), then reports per-room rank
agreement and the frames the methods disagree about most. Curation quality
is a *ratio to the room's best frame* (docs/15), so what matters is the
within-room ordering — correlations are computed per room, never pooled.

This is an IQA eval — no describe backend, nothing leaves the machine.

Usage:
    python evals/eval_iqa.py REPORT_DIR
    python evals/eval_iqa.py report --metrics musiq clipiqa -o results.json
    python evals/eval_iqa.py report --device mps

Requires pyiqa, installed manually (`uv pip install pyiqa`) — deliberately
NOT a project extra: IQA-PyTorch is CC BY-NC-SA 4.0 (non-commercial), so it
must never become a product dependency; this script is evaluation only.
Weights download to the torch hub cache on first run. Results + verdict:
docs/15 "The learned IQA tier".
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeinventory.curate import frame_quality  # noqa: E402


def ranks(values: list[float]) -> list[float]:
    """Average ranks (ties shared), 1-based."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation (Pearson on average ranks)."""
    if len(a) < 3:
        return float("nan")
    ra, rb = ranks(a), ranks(b)
    ma = sum(ra) / len(ra)
    mb = sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return float("nan")
    return cov / (va * vb) ** 0.5


def load_rooms(report_dir: Path) -> dict[str, list[dict]]:
    """{room: [{id, path}]} — video frames only; deliberate photo captures
    never compete for the hero budget (docs/15) so they are not scored."""
    inv = json.loads((report_dir / "inventory.json").read_text(encoding="utf-8"))
    rooms: dict[str, list[dict]] = {}
    for room in inv["rooms"]:
        frames = [
            {"id": p["id"], "path": p["path"]}
            for p in room.get("photos", [])
            if p.get("source_video")
        ]
        if frames:
            rooms[room["name"]] = frames
    return rooms


def score_classical(paths: list[Path]) -> tuple[list[float], float]:
    t0 = time.perf_counter()
    scores = [frame_quality(p)[0] for p in paths]
    return scores, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path,
                    help="build output dir containing inventory.json")
    ap.add_argument("--metrics", nargs="+", default=["musiq", "clipiqa"],
                    help="pyiqa metric names (default: musiq clipiqa)")
    ap.add_argument("--device", default=None,
                    help="torch device for pyiqa (e.g. mps, cuda, cpu)")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="write full results JSON here")
    args = ap.parse_args()

    rooms = load_rooms(args.report_dir)
    n_frames = sum(len(v) for v in rooms.values())
    print(f"{len(rooms)} rooms, {n_frames} video frames")

    # resolve paths once; a frame that fails to load scores 0 everywhere
    for frames in rooms.values():
        for f in frames:
            full = Path(f["path"])
            if not full.is_absolute():
                full = args.report_dir / full
            f["full"] = full

    methods: dict[str, dict[str, list[float]]] = {}   # method -> room -> scores
    timing: dict[str, dict] = {}

    all_paths = {room: [f["full"] for f in frames]
                 for room, frames in rooms.items()}

    scores_c, secs = {}, 0.0
    for room, paths in all_paths.items():
        scores_c[room], dt = score_classical(paths)
        secs += dt
    methods["classical"] = scores_c
    timing["classical"] = {"infer_s": round(secs, 2),
                           "ms_per_frame": round(1000 * secs / n_frames, 1)}
    print(f"classical: {secs:.1f}s ({1000 * secs / n_frames:.0f} ms/frame)")

    import pyiqa
    import torch

    for name in args.metrics:
        per_room: dict[str, list[float]] = {}
        t0 = time.perf_counter()
        metric = (pyiqa.create_metric(name, device=torch.device(args.device))
                  if args.device else pyiqa.create_metric(name))
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        with torch.no_grad():
            for room, paths in all_paths.items():
                per_room[room] = [float(metric(str(p)).item()) for p in paths]
        infer_s = time.perf_counter() - t0
        methods[name] = per_room
        timing[name] = {"load_s": round(load_s, 2),
                        "infer_s": round(infer_s, 2),
                        "ms_per_frame": round(1000 * infer_s / n_frames, 1)}
        print(f"{name}: load {load_s:.1f}s, infer {infer_s:.1f}s "
              f"({1000 * infer_s / n_frames:.0f} ms/frame)")

    # per-room Spearman of every learned metric vs classical, and vs each other
    names = list(methods)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    corr: dict[str, dict[str, float]] = {}
    for a, b in pairs:
        key = f"{a}~{b}"
        per_room = {room: round(spearman(methods[a][room], methods[b][room]), 3)
                    for room in rooms}
        vals = [v for v in per_room.values() if v == v]  # drop NaN
        corr[key] = {"per_room": per_room,
                     "mean": round(sum(vals) / len(vals), 3) if vals else None}
        print(f"spearman {key}: mean {corr[key]['mean']}  {per_room}")

    # frames the methods disagree about most (rank gap within room) — these
    # are the ones worth eyeballing
    disagreements = []
    base = "classical"
    for name in args.metrics:
        for room, frames in rooms.items():
            rb = ranks(methods[base][room])
            rn = ranks(methods[name][room])
            n = len(frames)
            for i, f in enumerate(frames):
                gap = (rn[i] - rb[i]) / max(n - 1, 1)
                disagreements.append({
                    "metric": name, "room": room, "id": f["id"],
                    "path": str(f["full"]),
                    "classical_rank": rb[i], f"{name}_rank": rn[i],
                    "of": n, "gap": round(gap, 3)})
    disagreements.sort(key=lambda d: -abs(d["gap"]))

    result = {
        "report_dir": str(args.report_dir),
        "n_rooms": len(rooms), "n_frames": n_frames,
        "timing": timing,
        "spearman": corr,
        "scores": {m: {room: [round(s, 4) for s in per_room[room]]
                       for room in per_room}
                   for m, per_room in methods.items()},
        "frames": {room: [{"id": f["id"], "path": str(f["full"])}
                          for f in frames]
                   for room, frames in rooms.items()},
        "top_disagreements": disagreements[:40],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2),
                               encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
