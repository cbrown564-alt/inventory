#!/usr/bin/env python3
"""ML-E19: Zero-shot shot-scale classifier vs hero-gold (docs/19).

Scores each video frame with a CLIP zero-shot margin between *long shot /
establishing* prompts and *close-up* prompts (types-of-film-shots concept).
Benchmarks Spearman ρ against ``hero-gold.json`` ranks and compares to the
classical E5 ``cover`` scorer baseline from ``eval_hero_cover.py``.

Usage:
    python evals/eval_shot_scale.py report \\
        --gold evals/fixtures/own-property/hero-gold.json \\
        -o evals/fixtures/own-property/hero-contact-shotscale.html

Optional deps (eval only):
    pip install open-clip-torch
    # or: pip install transformers
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
    aggregate_metrics,
    build_room_entries,
    evaluate_room,
    frame_name,
    gold_rank_map,
    img_href,
    load_gold,
    load_rooms,
    resolve_path,
    spearman,
)

DEFAULT_OUT = ROOT / "evals/fixtures/own-property/hero-contact-shotscale.html"
DEFAULT_GOLD = ROOT / "evals/fixtures/own-property/hero-gold.json"

# Film-shot vocabulary (types-of-film-shots / CineScale long vs close-up)
LONG_SHOT_PROMPTS = [
    "long shot of a room interior",
    "wide establishing shot showing the full room",
    "long shot showing floor walls and ceiling",
    "full room overview photograph",
]

CLOSE_UP_PROMPTS = [
    "close-up shot of an object or fixture",
    "extreme close-up detail photograph",
    "macro close-up of a household item",
    "tight crop filling the frame with one surface",
]


class ShotScaleScorer:
    """CLIP zero-shot long-shot vs close-up margin (Apache-2.0 encoder)."""

    def __init__(self, device: str | None = None, backend: str = "open_clip"):
        self.device = device
        self.backend = backend
        self.available = True
        self._load_error: str | None = None
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._text_features = None

    def _load(self) -> None:
        if self._model is not None or not self.available:
            return
        try:
            if self.backend == "open_clip":
                import open_clip
                import torch

                model, _, preprocess = open_clip.create_model_and_transforms(
                    "ViT-B-32", pretrained="openai",
                )
                tokenizer = open_clip.get_tokenizer("ViT-B-32")
                dev = self._resolve_device(torch)
                model = model.to(dev).eval()
                text = LONG_SHOT_PROMPTS + CLOSE_UP_PROMPTS
                tokens = tokenizer(text).to(dev)
                with torch.no_grad():
                    feats = model.encode_text(tokens)
                    feats = feats / feats.norm(dim=-1, keepdim=True)
                self._model = model
                self._preprocess = preprocess
                self._text_features = feats
                self._n_long = len(LONG_SHOT_PROMPTS)
            else:
                import torch
                from transformers import CLIPModel, CLIPProcessor

                model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
                processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
                dev = self._resolve_device(torch)
                model = model.to(dev).eval()
                text = LONG_SHOT_PROMPTS + CLOSE_UP_PROMPTS
                inputs = processor(text=text, return_tensors="pt", padding=True)
                inputs = {k: v.to(dev) for k, v in inputs.items()}
                with torch.no_grad():
                    feats = model.get_text_features(**inputs)
                    feats = feats / feats.norm(dim=-1, keepdim=True)
                self._model = model
                self._processor = processor
                self._text_features = feats
                self._n_long = len(LONG_SHOT_PROMPTS)
        except Exception as exc:
            self.available = False
            self._load_error = str(exc)

    def _resolve_device(self, torch):
        if self.device:
            return self.device
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def score(self, path: Path) -> dict:
        """Return long-shot margin and component softmax probabilities."""
        self._load()
        if not self.available:
            return {"margin": float("nan"), "long_prob": float("nan"),
                    "close_prob": float("nan")}
        import torch
        from PIL import Image

        image = Image.open(path).convert("RGB")
        dev = self._resolve_device(torch)

        if self.backend == "open_clip":
            tensor = self._preprocess(image).unsqueeze(0).to(dev)
            with torch.no_grad():
                img_feat = self._model.encode_image(tensor)
                img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
                sims = (img_feat @ self._text_features.T).squeeze(0)
        else:
            inputs = self._processor(images=image, return_tensors="pt")
            inputs = {k: v.to(dev) for k, v in inputs.items()}
            with torch.no_grad():
                img_feat = self._model.get_image_features(**inputs)
                img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
                sims = (img_feat @ self._text_features.T).squeeze(0)

        sims = sims.float().cpu()
        long_sims = sims[: self._n_long]
        close_sims = sims[self._n_long :]
        long_mean = float(long_sims.mean())
        close_mean = float(close_sims.mean())
        margin = long_mean - close_mean

        # Softmax over the two shot-scale groups (not individual prompts)
        pair = torch.tensor([long_mean, close_mean])
        probs = torch.softmax(pair * 100.0, dim=0)
        return {
            "margin": margin,
            "long_prob": float(probs[0]),
            "close_prob": float(probs[1]),
        }


def shot_scale_sort_key(metrics: dict) -> tuple:
    """Higher margin / long_prob = better establishing rank."""
    m = metrics.get("shot_scale", {})
    margin = m.get("margin", float("-inf"))
    if math.isnan(margin):
        margin = float("-inf")
    return (margin, m.get("long_prob", 0))


def evaluate_shot_scale_room(
        *,
        entries: list[dict],
        metrics: dict[str, dict],
        gold_room: dict | None,
        cover_metrics: dict[str, dict],
) -> dict:
    """Per-room metrics for shot-scale vs gold; includes E5 cover baseline ρ."""
    by_shot = sorted(entries, key=lambda e: shot_scale_sort_key(metrics[e["name"]]),
                     reverse=True)
    shot_rank = {e["name"]: i + 1 for i, e in enumerate(by_shot)}

    room_metrics: dict = {"n_frames": len(entries)}

    if not gold_room:
        return room_metrics

    gold_ranks = gold_rank_map(gold_room, len(entries))
    labeled = [n for n in gold_ranks if any(e["name"] == n for e in entries)]
    if len(labeled) >= 5:
        gold_vals = [gold_ranks[n] for n in labeled]
        shot_vals = [float(shot_rank[n]) for n in labeled]
        room_metrics["spearman_shot_scale"] = round(spearman(gold_vals, shot_vals), 3)

        cover_room = evaluate_room(
            scorer="cover",
            entries=entries,
            metrics=cover_metrics,
            gold_room=gold_room,
        )
        room_metrics["spearman_cover_e5"] = cover_room.get("spearman")
        room_metrics["top1_hit_cover_e5"] = cover_room.get("top1_hit")
        room_metrics["top3_hit_cover_e5"] = cover_room.get("top3_hit")
    else:
        room_metrics["spearman_shot_scale"] = None
        room_metrics["spearman_cover_e5"] = None

    pick = by_shot[0]["name"] if by_shot else None
    top_gold = gold_room.get("top", [])
    if pick and top_gold:
        room_metrics["top1_hit_shot_scale"] = pick == top_gold[0]
        room_metrics["top3_hit_shot_scale"] = pick in {e["name"] for e in by_shot[:3]}

    return room_metrics


def aggregate_shot_scale(per_room: dict[str, dict]) -> dict:
    out: dict = {"per_room": per_room, "n_rooms": len(per_room)}
    with_gold = [r for r in per_room.values() if r.get("spearman_shot_scale") is not None]
    if with_gold:
        rhos_shot = [r["spearman_shot_scale"] for r in with_gold]
        rhos_cover = [r["spearman_cover_e5"] for r in with_gold
                      if r.get("spearman_cover_e5") is not None]
        out["mean_spearman_shot_scale"] = round(sum(rhos_shot) / len(rhos_shot), 3)
        out["mean_spearman_cover_e5"] = round(sum(rhos_cover) / len(rhos_cover), 3) if rhos_cover else None
        out["pass_bar"] = (
            out["mean_spearman_shot_scale"] >= (out["mean_spearman_cover_e5"] or 0)
            if out["mean_spearman_cover_e5"] is not None else None
        )
        hits = [r for r in with_gold if "top1_hit_shot_scale" in r]
        if hits:
            out["top1_hit_rate_shot_scale"] = round(
                100 * sum(1 for r in hits if r["top1_hit_shot_scale"]) / len(hits), 1)
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
        "<html><head>",
        "<meta charset='utf-8'>",
        "<title>ML-E19 shot-scale contact sheet</title>",
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
        "<h1>ML-E19 — shot-scale (long vs close-up)</h1>",
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
        display = sorted(entries, key=lambda e: e.get("shot_rank", 999))
        for e in display:
            m = e["metrics"]
            ss = m.get("shot_scale", {})
            hero = e.get("hero")
            hero_txt = f"hero={hero}" if hero else "hero=—"
            gold_txt = (f"gold={gold_ranks[e['name']]:g}"
                        if e["name"] in gold_ranks else "gold=—")
            star = "<span class='star'>★ </span>" if hero == 1 else ""
            margin = ss.get("margin", float("nan"))
            parts.extend([
                f"<div class='cell{' pick' if e.get('shot_rank') == 1 else ''}'>",
                f"<img src='{img_href(html_path, e['path'])}' "
                f"alt='{html.escape(e['name'])}'>",
                "<div class='meta'>",
                f"{star}<strong>{html.escape(e['name'])}</strong><br>",
                "<span class='metrics'>",
                f"margin={margin:.3f} long={ss.get('long_prob', 0):.2f} "
                f"shot={e.get('shot_rank', '—')} {hero_txt} {gold_txt}",
                "</span></div></div>",
            ])
        parts.append("</div>")

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"),
                    help="build output dir containing inventory.json")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--device", default=None)
    ap.add_argument("--backend", default="open_clip", choices=["open_clip", "transformers"])
    args = ap.parse_args()

    report_dir = args.report_dir.resolve()
    if not (report_dir / "inventory.json").is_file():
        print(f"error: inventory.json not found in {report_dir}", file=sys.stderr)
        print("Provide a build output dir with video frames (e.g. report/).", file=sys.stderr)
        return 2

    gold = load_gold(args.gold)
    rooms = load_rooms(report_dir)
    if not rooms:
        print("no video frames found", file=sys.stderr)
        return 1

    scorer = ShotScaleScorer(device=args.device, backend=args.backend)
    if not scorer.available:
        scorer._load()  # populate _load_error
    if not scorer.available:
        print(f"shot-scale scorer unavailable: {scorer._load_error}", file=sys.stderr)
        payload = {
            "experiment": "ML-E19",
            "available": False,
            "error": scorer._load_error,
            "dependency_notes": "pip install open-clip-torch  # or transformers",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "\n".join([
                "<!DOCTYPE html><html><body><pre>",
                html.escape(json.dumps(payload, indent=2)),
                "</pre></body></html>",
            ]),
            encoding="utf-8",
        )
        print(f"wrote stub {args.output}")
        return 1

    print(f"{len(rooms)} rooms, scorer={args.backend}")
    t0 = time.perf_counter()

    room_entries: dict[str, list[dict]] = {}
    all_metrics: dict[str, dict] = {}
    for room_name, frames in rooms:
        entries, cover_metrics = build_room_entries(report_dir, frames)
        for e in entries:
            ss = scorer.score(e["path"])
            cover_metrics[e["name"]]["shot_scale"] = ss
        room_entries[room_name] = entries
        all_metrics[room_name] = cover_metrics

    infer_s = time.perf_counter() - t0
    n_frames = sum(len(v) for v in room_entries.values())
    print(f"scored {n_frames} frames in {infer_s:.1f}s "
          f"({1000 * infer_s / max(1, n_frames):.0f} ms/frame)")

    per_room: dict[str, dict] = {}
    for room_name, entries in room_entries.items():
        metrics = all_metrics[room_name]
        per_room[room_name] = evaluate_shot_scale_room(
            entries=entries,
            metrics=metrics,
            gold_room=gold.get(room_name),
            cover_metrics=metrics,
        )
        by_shot = sorted(entries, key=lambda e: shot_scale_sort_key(metrics[e["name"]]),
                         reverse=True)
        shot_rank = {e["name"]: i + 1 for i, e in enumerate(by_shot)}
        for e in entries:
            e["metrics"] = metrics[e["name"]]
            e["shot_rank"] = shot_rank[e["name"]]

    summary = aggregate_shot_scale(per_room)
    summary["timing"] = {
        "infer_s": round(infer_s, 2),
        "ms_per_frame": round(1000 * infer_s / max(1, n_frames), 1),
        "backend": args.backend,
    }
    summary["prompts"] = {
        "long_shot": LONG_SHOT_PROMPTS,
        "close_up": CLOSE_UP_PROMPTS,
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "per_room"}, indent=2))

    note = (
        "CLIP zero-shot margin: mean(long-shot prompts) − mean(close-up prompts). "
        "Pass bar: mean Spearman ρ vs hero-gold ≥ E5 cover scorer (classical baseline)."
    )
    render_html(
        html_path=args.output.resolve(),
        report_dir=report_dir,
        rooms=rooms,
        room_data=room_entries,
        metrics_summary=summary,
        gold=gold,
        scorer_note=note,
    )
    print(f"wrote {args.output}")
    return 0 if summary.get("pass_bar") is not False else 0


if __name__ == "__main__":
    sys.exit(main())
