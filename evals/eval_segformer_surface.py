#!/usr/bin/env python3
"""ML-E13: SegFormer floor+wall fraction vs hero-gold establishing (docs/19 §1.5).

Scores each video frame in a build report for visible floor+wall area using
SegFormer (ADE20K) when transformers/torch are available, or a lightweight
colour-histogram fallback (--demo / no-deps).

Pass bar: mean Spearman ρ vs hero-gold ranks ≥ classical establishing score.

Outputs:
  evals/fixtures/own-property/segformer-surface.html
  evals/fixtures/own-property/segformer-surface-metrics.json

Usage:
    uv run python evals/eval_segformer_surface.py report
    uv run python evals/eval_segformer_surface.py report --demo
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_hero_cover import (  # noqa: E402
    build_room_entries,
    evaluate_room,
    gold_rank_map,
    img_href,
    load_gold,
    load_rooms,
    spearman,
)

DEFAULT_GOLD = ROOT / "evals/fixtures/own-property/hero-gold.json"
DEFAULT_HTML = ROOT / "evals/fixtures/own-property/segformer-surface.html"
DEFAULT_JSON = ROOT / "evals/fixtures/own-property/segformer-surface-metrics.json"

# ADE20K ids for SegFormer-b0-finetuned-ade-512-512
ADE_WALL = 0
ADE_FLOOR = 3
ADE_CEILING = 5
SURFACE_IDS = {ADE_WALL, ADE_FLOOR, ADE_CEILING}


class SurfaceScorer:
    """Floor+wall (+ceiling) pixel fraction; SegFormer or histogram fallback."""

    def __init__(self, *, backend: str = "auto", device: str | None = None):
        self.backend = backend
        self.device = device
        self.mode = "histogram"
        self._model = None
        self._processor = None
        self._load_error: str | None = None

    def _try_load_segformer(self) -> bool:
        if self.backend == "histogram":
            return False
        try:
            import torch
            from transformers import SegformerForSemanticSegmentation
            from transformers import SegformerImageProcessor

            model_id = "nvidia/segformer-b0-finetuned-ade-512-512"
            self._processor = SegformerImageProcessor.from_pretrained(model_id)
            self._model = SegformerForSemanticSegmentation.from_pretrained(model_id)
            dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._model = self._model.to(dev).eval()
            self._device = dev
            self.mode = "segformer"
            return True
        except Exception as exc:
            self._load_error = str(exc)
            return False

    def score_path(self, path: Path) -> dict:
        if self.backend != "histogram" and self._model is None:
            self._try_load_segformer()
        if self.mode == "segformer" and self._model is not None:
            return self._score_segformer(path)
        return self._score_histogram(path)

    def _score_segformer(self, path: Path) -> dict:
        import torch
        from PIL import Image

        image = Image.open(path).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = self._model(**inputs).logits
        upsampled = torch.nn.functional.interpolate(
            logits,
            size=image.size[::-1],
            mode="bilinear",
            align_corners=False,
        )
        pred = upsampled.argmax(dim=1).squeeze(0).cpu().numpy()
        total = pred.size
        wall = int((pred == ADE_WALL).sum())
        floor = int((pred == ADE_FLOOR).sum())
        ceiling = int((pred == ADE_CEILING).sum())
        surface = wall + floor + ceiling
        return {
            "floor_wall_fraction": round(surface / total, 4),
            "wall_fraction": round(wall / total, 4),
            "floor_fraction": round(floor / total, 4),
            "ceiling_fraction": round(ceiling / total, 4),
            "backend": "segformer",
        }

    def _score_histogram(self, path: Path) -> dict:
        """Lower-third floor band + side wall strips via muted-structure heuristic."""
        from PIL import Image
        import numpy as np

        img = np.array(Image.open(path).convert("RGB"), dtype=np.float32)
        h, w, _ = img.shape
        # normalised channels
        r, g, b = img[..., 0] / 255, img[..., 1] / 255, img[..., 2] / 255
        maxc = np.maximum(np.maximum(r, g), b)
        minc = np.minimum(np.minimum(r, g), b)
        sat = maxc - minc

        floor_band = slice(int(h * 0.65), h)
        upper = slice(0, int(h * 0.65))
        side_w = max(1, int(w * 0.12))

        floor_region = sat[floor_band, :]
        floor_struct = float((floor_region < 0.22).mean())

        left_wall = sat[upper, :side_w]
        right_wall = sat[upper, -side_w:]
        wall_struct = float(
            ((left_wall < 0.20).mean() + (right_wall < 0.20).mean()) / 2
        )

        # centre clutter penalty — high-frequency mid-frame reduces establishing
        centre = sat[upper, side_w:-side_w] if w > 2 * side_w else sat[upper, :]
        clutter = float((centre > 0.35).mean())

        raw = 0.45 * floor_struct + 0.45 * wall_struct + 0.10 * (1.0 - clutter)
        frac = max(0.0, min(1.0, raw))
        return {
            "floor_wall_fraction": round(frac, 4),
            "wall_fraction": round(wall_struct * 0.5, 4),
            "floor_fraction": round(floor_struct * 0.5, 4),
            "ceiling_fraction": round(0.05, 4),
            "backend": "histogram",
        }


def surface_sort_key(metrics: dict) -> float:
    s = metrics.get("surface", {})
    frac = s.get("floor_wall_fraction", float("-inf"))
    return frac if not math.isnan(frac) else float("-inf")


def evaluate_surface_room(
        *,
        entries: list[dict],
        metrics: dict[str, dict],
        gold_room: dict | None,
        cover_metrics: dict[str, dict],
) -> dict:
    by_surface = sorted(
        entries,
        key=lambda e: surface_sort_key(metrics[e["name"]]),
        reverse=True,
    )
    surface_rank = {e["name"]: i + 1 for i, e in enumerate(by_surface)}
    room_metrics: dict = {"n_frames": len(entries)}

    if not gold_room:
        return room_metrics

    gold_ranks = gold_rank_map(gold_room, len(entries))
    labeled = [n for n in gold_ranks if any(e["name"] == n for e in entries)]
    if len(labeled) >= 5:
        gold_vals = [gold_ranks[n] for n in labeled]
        surface_vals = [float(surface_rank[n]) for n in labeled]
        room_metrics["spearman_surface"] = round(spearman(gold_vals, surface_vals), 3)

        cover_room = evaluate_room(
            scorer="establishing",
            entries=entries,
            metrics=cover_metrics,
            gold_room=gold_room,
        )
        room_metrics["spearman_establishing"] = cover_room.get("spearman")
        room_metrics["top3_hit_establishing"] = cover_room.get("top3_hit")
    else:
        room_metrics["spearman_surface"] = None
        room_metrics["spearman_establishing"] = None

    pick = by_surface[0]["name"] if by_surface else None
    top_gold = gold_room.get("top", [])
    if pick and top_gold:
        room_metrics["top1_hit_surface"] = pick == top_gold[0]
        room_metrics["top3_hit_surface"] = pick in {e["name"] for e in by_surface[:3]}

    return room_metrics


def aggregate_surface(per_room: dict[str, dict]) -> dict:
    out: dict = {"per_room": per_room, "n_rooms": len(per_room)}
    with_gold = [r for r in per_room.values() if r.get("spearman_surface") is not None]
    if with_gold:
        rhos_surface = [r["spearman_surface"] for r in with_gold]
        rhos_est = [r["spearman_establishing"] for r in with_gold
                    if r.get("spearman_establishing") is not None]
        out["mean_spearman_surface"] = round(sum(rhos_surface) / len(rhos_surface), 3)
        out["mean_spearman_establishing"] = (
            round(sum(rhos_est) / len(rhos_est), 3) if rhos_est else None
        )
        baseline = out["mean_spearman_establishing"] or 0.0
        out["pass_bar"] = f"mean ρ surface ≥ establishing ({baseline})"
        out["pass"] = out["mean_spearman_surface"] >= baseline
    return out


def render_html(
        *,
        html_path: Path,
        report_dir: Path,
        rooms: list[tuple[str, list[dict]]],
        room_data: dict[str, list[dict]],
        metrics_summary: dict,
        gold: dict[str, dict],
        scorer_note: str,
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>ML-E13 SegFormer surface contact sheet</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:1rem;background:#111;color:#eee}",
        "h1,h2{margin:0.5rem 0}",
        ".summary{background:#222;padding:1rem;border-radius:8px;margin-bottom:1.5rem}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}",
        ".cell{background:#222;border-radius:8px;overflow:hidden;border:2px solid #333}",
        ".cell.pick{border-color:#f5c518}",
        ".cell img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover;background:#000}",
        ".meta{padding:8px;font-size:12px;line-height:1.4}",
        ".star{color:#f5c518;font-weight:bold}",
        ".metrics{color:#aaa}",
        "</style></head><body>",
        "<h1>ML-E13 — floor+wall surface fraction</h1>",
        f"<p>Report: {html.escape(str(report_dir))}</p>",
        f"<p>{html.escape(scorer_note)}</p>",
        "<div class='summary'><h2>Metrics</h2><pre>",
        html.escape(json.dumps(metrics_summary, indent=2)),
        "</pre></div>",
    ]

    for room_name, _frames in rooms:
        entries = room_data[room_name]
        gold_room = gold.get(room_name, {})
        gold_ranks = gold_rank_map(gold_room, len(entries))
        parts.append(f"<h2>{html.escape(room_name)}</h2>")
        if gold_room.get("notes"):
            parts.append(f"<p><em>{html.escape(gold_room['notes'])}</em></p>")
        parts.append("<div class='grid'>")
        display = sorted(entries, key=lambda e: e.get("surface_rank", 999))
        for e in display:
            m = e["metrics"]
            ss = m.get("surface", {})
            hero = e.get("hero")
            hero_txt = f"hero={hero}" if hero else "hero=—"
            gold_txt = (
                f"gold={gold_ranks[e['name']]:g}"
                if e["name"] in gold_ranks else "gold=—"
            )
            star = "<span class='star'>★ </span>" if hero == 1 else ""
            frac = ss.get("floor_wall_fraction", float("nan"))
            parts.extend([
                f"<div class='cell{' pick' if e.get('surface_rank') == 1 else ''}'>",
                f"<img src='{img_href(html_path, e['path'])}' "
                f"alt='{html.escape(e['name'])}'>",
                "<div class='meta'>",
                f"{star}<strong>{html.escape(e['name'])}</strong><br>",
                "<span class='metrics'>",
                f"surface={frac:.3f} floor={ss.get('floor_fraction', 0):.2f} "
                f"wall={ss.get('wall_fraction', 0):.2f} "
                f"rank={e.get('surface_rank', '—')} {hero_txt} {gold_txt}",
                "</span></div></div>",
            ])
        parts.append("</div>")

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    report_dir = args.report_dir.resolve()
    if not (report_dir / "inventory.json").is_file():
        raise FileNotFoundError(f"inventory.json not found in {report_dir}")

    gold = load_gold(args.gold)
    rooms = load_rooms(report_dir)
    if not rooms:
        raise RuntimeError("no video frames found in report")

    backend = "histogram" if args.demo else args.backend
    scorer = SurfaceScorer(backend=backend, device=args.device)
    t0 = time.perf_counter()

    room_entries: dict[str, list[dict]] = {}
    all_metrics: dict[str, dict] = {}
    for room_name, frames in rooms:
        entries, cover_metrics = build_room_entries(report_dir, frames)
        for e in entries:
            ss = scorer.score_path(e["path"])
            cover_metrics[e["name"]]["surface"] = ss
        room_entries[room_name] = entries
        all_metrics[room_name] = cover_metrics

    infer_s = time.perf_counter() - t0
    n_frames = sum(len(v) for v in room_entries.values())

    per_room: dict[str, dict] = {}
    for room_name, entries in room_entries.items():
        metrics = all_metrics[room_name]
        per_room[room_name] = evaluate_surface_room(
            entries=entries,
            metrics=metrics,
            gold_room=gold.get(room_name),
            cover_metrics=metrics,
        )
        by_surface = sorted(
            entries,
            key=lambda e: surface_sort_key(metrics[e["name"]]),
            reverse=True,
        )
        surface_rank = {e["name"]: i + 1 for i, e in enumerate(by_surface)}
        for e in entries:
            e["metrics"] = metrics[e["name"]]
            e["surface_rank"] = surface_rank[e["name"]]

    summary = aggregate_surface(per_room)
    summary["timing"] = {
        "infer_s": round(infer_s, 2),
        "ms_per_frame": round(1000 * infer_s / max(1, n_frames), 1),
        "scorer_mode": scorer.mode,
    }
    if scorer._load_error and scorer.mode != "segformer":
        summary["segformer_load_error"] = scorer._load_error

    payload = {
        "experiment": "ML-E13",
        "report_dir": str(report_dir),
        "n_rooms": len(rooms),
        "n_frames": n_frames,
        "demo": args.demo,
        **{k: v for k, v in summary.items() if k != "per_room"},
        "per_room": per_room,
        "pass": summary.get("pass"),
    }

    args.html_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    note = (
        f"Floor+wall fraction via {scorer.mode}. "
        "Pass bar: mean Spearman ρ vs hero-gold ≥ classical establishing scorer."
    )
    render_html(
        html_path=args.html_output.resolve(),
        report_dir=report_dir,
        rooms=rooms,
        room_data=room_entries,
        metrics_summary=payload,
        gold=gold,
        scorer_note=note,
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"),
                    help="build output dir containing inventory.json")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--html-output", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--demo", action="store_true",
                    help="histogram fallback only (no SegFormer download)")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "segformer", "histogram"],
                    help="scorer backend (auto tries SegFormer)")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    try:
        payload = run(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(
        {k: v for k, v in payload.items() if k not in ("per_room",)},
        indent=2,
    ))
    print(f"wrote {args.html_output.resolve()}")
    print(f"wrote {args.json_output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
