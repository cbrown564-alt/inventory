#!/usr/bin/env python3
"""Per-room hero cover contact sheets and gold-set metrics (docs/18).

Scores every video frame in a build output dir, ranks them by a configurable
scorer, and renders an HTML contact sheet per room with sharpness,
establishing score, current hero rank, gold rank (when provided), and a ★ on
the inventory rank-1 pick. Reports top-1 / top-3 hit rate, Spearman vs gold,
and blur-reject rate.

Usage:
    uv run python evals/eval_hero_cover.py report
    uv run python evals/eval_hero_cover.py report --scorer hard-gates \\
        -o evals/fixtures/own-property/hero-contact-hard-gates.html
    uv run python evals/eval_hero_cover.py report --gold \\
        evals/fixtures/own-property/hero-gold.json
    uv run python evals/eval_hero_cover.py report --scorer mslap \\
        -o evals/fixtures/own-property/hero-contact-mslap.html
    uv run python evals/eval_relevance_siglip.py report
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeinventory.curate import (  # noqa: E402
    _COVER_ALT_WITHIN,
    _COVER_RANK1_QUALITY,
    _COVER_SLOT_QUALITY,
    _cover_metrics,
    _passes_cover_gates,
    _percentile,
    classical_features,
    cover_score,
    frame_quality,
    linear_iqa_score,
    mslap_score,
)

DEFAULT_WEIGHTS = (
    ROOT / "evals" / "fixtures" / "own-property" / "iqa-linear-weights.json"
)

_CLIP_PROMPTS = (
    ("a wide interior photograph of a room", "a close-up of an object"),
    ("a sharp photograph", "a blurry photograph"),
)
_clip_model = None


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


def frame_name(path: Path | str) -> str:
    return Path(path).name


def load_rooms(report_dir: Path) -> list[tuple[str, list[dict]]]:
    """Walkthrough-ordered [(room_name, video frames only)]."""
    inv = json.loads((report_dir / "inventory.json").read_text(encoding="utf-8"))
    out: list[tuple[str, list[dict]]] = []
    for room in inv["rooms"]:
        frames = [
            {"id": p["id"], "path": p["path"], "hero": p.get("hero")}
            for p in room.get("photos", [])
            if p.get("source_video")
        ]
        if frames:
            out.append((room["name"], frames))
    return out


def resolve_path(report_dir: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = report_dir / path
    return path


def load_gold(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("rooms", {})


def score_frame(path: Path, *, include_mslap: bool = True) -> dict:
    quality, _, establishing = frame_quality(path)
    sh, smooth, cbr, clipped = _cover_metrics(path)
    out = {
        "quality": quality,
        "sharpness": sh,
        "establishing": establishing,
        "smooth": smooth,
        "cbr": cbr,
        "clipped": clipped,
    }
    if include_mslap:
        out["mslap"] = mslap_score(path)
    return out


def score_siglip(paths: list[Path], *, backend: str = "siglip",
                 device: str = "cpu") -> dict[str, float]:
    """{filename: relevance margin} for ML-E4."""
    from evals.ml_scorers import make_relevance_scorer

    scorer = make_relevance_scorer(backend=backend, device=device)
    out: dict[str, float] = {}
    for path in paths:
        out[path.name] = scorer.score_path(path)
    return out


def load_linear_weights(path: Path | None) -> dict:
    p = path or DEFAULT_WEIGHTS
    if not p.is_file():
        raise FileNotFoundError(f"linear weights not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def metrics_features(metrics: dict) -> dict[str, float]:
    return classical_features(
        metrics["sharpness"],
        metrics["smooth"],
        metrics["cbr"],
        metrics["clipped"],
        metrics["establishing"],
        metrics["quality"],
    )


def linear_musiq_value(metrics: dict, weights: dict) -> float:
    feats = metrics_features(metrics)
    row = {n: 1.0 if n == "bias" else feats.get(n, 0.0)
           for n in weights["features"]}
    return linear_iqa_score(row, weights)


def load_clip_model():
    """Lazy-load OpenCLIP ViT-B/32 (Apache-2.0, ML-E7)."""
    global _clip_model
    if _clip_model is not None:
        return _clip_model
    try:
        import open_clip
        import torch
        from PIL import Image
    except ImportError as e:
        raise ImportError(
            "clip-establishing requires: uv pip install open-clip-torch torch"
        ) from e

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai")
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    pos_texts = [p[0] for p in _CLIP_PROMPTS]
    neg_texts = [p[1] for p in _CLIP_PROMPTS]
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    with torch.no_grad():
        pos = model.encode_text(tokenizer(pos_texts).to(device))
        neg = model.encode_text(tokenizer(neg_texts).to(device))
        pos = pos / pos.norm(dim=-1, keepdim=True)
        neg = neg / neg.norm(dim=-1, keepdim=True)
    _clip_model = {
        "model": model,
        "preprocess": preprocess,
        "device": device,
        "pos": pos,
        "neg": neg,
        "Image": Image,
        "torch": torch,
    }
    return _clip_model


def clip_establishing_score(path: Path) -> float:
    """Prompt-pair margin: establishing wide interior vs close-up (+ sharp)."""
    clip = load_clip_model()
    torch = clip["torch"]
    with clip["Image"].open(path) as im:
        im = im.convert("RGB")
        tensor = clip["preprocess"](im).unsqueeze(0).to(clip["device"])
    with torch.no_grad():
        img = clip["model"].encode_image(tensor)
        img = img / img.norm(dim=-1, keepdim=True)
        pos_sim = (img @ clip["pos"].T).mean().item()
        neg_sim = (img @ clip["neg"].T).mean().item()
    return pos_sim - neg_sim


def scorer_sort_key(scorer: str, metrics: dict, *, gated: bool,
                    weights: dict | None = None) -> tuple:
    """Sort key for contact-sheet ordering (higher = better rank)."""
    if scorer == "classical":
        return (metrics["quality"], metrics["establishing"])
    if scorer == "establishing":
        return (metrics["establishing"], metrics["quality"])
    if scorer == "hard-gates":
        # survivors first, then by establishing
        return (1 if gated else 0, metrics["establishing"], metrics["quality"])
    if scorer == "cover":
        cs = cover_score(metrics["establishing"], metrics["cbr"])
        return (cs, metrics["quality"])
    if scorer == "linear-musiq":
        if weights is None:
            raise ValueError("linear-musiq requires weights")
        return (linear_musiq_value(metrics, weights), metrics["establishing"])
    if scorer == "clip-establishing":
        return (metrics.get("clip_margin", 0.0), metrics["quality"])
    if scorer == "mslap":
        return (metrics.get("mslap", 0.0), metrics["quality"])
    if scorer == "siglip":
        return (metrics.get("siglip", 0.0), metrics["quality"])
    raise ValueError(f"unknown scorer: {scorer}")


def pick_rank_one(
        scorer: str,
        entries: list[dict],
        metrics: dict[str, dict],
        *,
        room_median: float,
        room_p25: float,
        weights: dict | None = None,
) -> dict:
    """Return the entry dict the scorer would pick as rank-1 cover."""
    if scorer == "classical":
        return max(entries, key=lambda e: metrics[e["name"]]["quality"])
    if scorer == "establishing":
        return max(entries, key=lambda e: metrics[e["name"]]["establishing"])
    if scorer == "hard-gates":
        survivors = [
            e for e in entries
            if _passes_cover_gates(
                metrics[e["name"]]["sharpness"],
                metrics[e["name"]]["smooth"],
                metrics[e["name"]]["cbr"],
                metrics[e["name"]]["clipped"],
                room_median=room_median,
                room_p25=room_p25,
            )
        ]
        pool = survivors if survivors else entries
        return max(pool, key=lambda e: metrics[e["name"]]["establishing"])
    if scorer == "cover":
        def cs(entry: dict) -> float:
            m = metrics[entry["name"]]
            return cover_score(m["establishing"], m["cbr"])

        # mirror curate._promote_cover_rank_one among frames above slot floor
        slot_pool = [
            e for e in entries
            if (e.get("quality") or 0) >= _COVER_SLOT_QUALITY
        ]
        pool = slot_pool if slot_pool else entries
        best = max(pool, key=cs)
        top = cs(best)
        q = best.get("quality") or 0
        if q < _COVER_RANK1_QUALITY:
            alts = [e for e in pool
                    if (e.get("quality") or 0) >= _COVER_RANK1_QUALITY
                    and cs(e) >= top * _COVER_ALT_WITHIN]
            if alts:
                best = max(alts, key=cs)
        return best
    if scorer == "linear-musiq":
        return max(
            entries,
            key=lambda e: linear_musiq_value(metrics[e["name"]], weights or {}),
        )
    if scorer == "clip-establishing":
        return max(
            entries,
            key=lambda e: metrics[e["name"]].get("clip_margin", 0.0),
        )
    if scorer == "mslap":
        return max(entries, key=lambda e: metrics[e["name"]].get("mslap", 0.0))
    if scorer == "siglip":
        return max(entries, key=lambda e: metrics[e["name"]].get("siglip", 0.0))
    raise ValueError(f"unknown scorer: {scorer}")


def gold_rank_map(gold_room: dict, n_frames: int) -> dict[str, float]:
    """{filename: gold rank} for top-3 and bottom-2 labels."""
    out: dict[str, float] = {}
    for i, name in enumerate(gold_room.get("top", []), start=1):
        out[name] = float(i)
    for i, name in enumerate(gold_room.get("bottom", []), start=1):
        out[name] = float(n_frames - len(gold_room.get("bottom", [])) + i)
    return out


def img_href(html_path: Path, frame_path: Path) -> str:
    try:
        return html.escape(str(frame_path.relative_to(html_path.parent)))
    except ValueError:
        return html.escape(str(frame_path))


def render_html(
        *,
        html_path: Path,
        report_dir: Path,
        scorer: str,
        rooms: list[tuple[str, list[dict]]],
        room_data: dict[str, list[dict]],
        metrics_summary: dict,
        gold: dict[str, dict],
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        f"<title>Hero cover contact — {html.escape(scorer)}</title>",
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
        f"<h1>Hero cover — scorer: {html.escape(scorer)}</h1>",
        f"<p>Report: {html.escape(str(report_dir))}</p>",
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
        display = sorted(
            entries,
            key=lambda e: e.get("scorer_rank", 999),
        )
        for e in display:
            m = e["metrics"]
            hero = e.get("hero")
            hero_txt = f"hero={hero}" if hero else "hero=—"
            gold_txt = (f"gold={gold_ranks[e['name']]:g}"
                        if e["name"] in gold_ranks else "gold=—")
            star = "<span class='star'>★ </span>" if hero == 1 else ""
            gate = " gate=OUT" if e.get("gated_out") else ""
            parts.extend([
                f"<div class='cell{' pick' if hero == 1 else ''}'>",
                f"<img src='{img_href(html_path, e['path'])}' "
                f"alt='{html.escape(e['name'])}'>",
                "<div class='meta'>",
                f"{star}<strong>{html.escape(e['name'])}</strong><br>",
                f"<span class='metrics'>",
                f"sh={m['sharpness']:.0f} est={m['establishing']:.2f} "
                f"mslap={m.get('mslap', 0):.2f} "
                f"{hero_txt} {scorer}={e['scorer_rank']:.0f} {gold_txt}{gate}",
                "</span></div></div>",
            ])
        parts.append("</div>")

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def evaluate_room(
        *,
        scorer: str,
        entries: list[dict],
        metrics: dict[str, dict],
        gold_room: dict | None,
        weights: dict | None = None,
) -> dict:
    sharpnesses = [metrics[e["name"]]["sharpness"] for e in entries]
    room_median = _percentile(sharpnesses, 0.5)
    room_p25 = _percentile(sharpnesses, 0.25)

    pick = pick_rank_one(
        scorer, entries, metrics,
        room_median=room_median, room_p25=room_p25,
        weights=weights,
    )
    pick_name = pick["name"]
    pick_sh = metrics[pick_name]["sharpness"]

    by_scorer = sorted(
        entries,
        key=lambda e: scorer_sort_key(
            scorer, metrics[e["name"]],
            gated=e.get("gated_out", False),
            weights=weights,
        ),
        reverse=True,
    )
    scorer_rank = {e["name"]: i + 1 for i, e in enumerate(by_scorer)}

    room_metrics: dict = {
        "n_frames": len(entries),
        "pick": pick_name,
        "pick_sharpness": round(pick_sh, 1),
        "room_median_sharpness": round(room_median, 1),
        "blur_reject": pick_sh < room_median,
    }

    if not gold_room:
        return room_metrics

    top_gold = gold_room.get("top", [])
    if top_gold:
        room_metrics["top1_hit"] = pick_name == top_gold[0]
        room_metrics["top3_hit"] = top_gold[0] in {
            e["name"] for e in by_scorer[:3]
        }

    gold_ranks = gold_rank_map(gold_room, len(entries))
    labeled = [n for n in gold_ranks if any(e["name"] == n for e in entries)]
    if len(labeled) >= 5:
        gold_vals = [gold_ranks[n] for n in labeled]
        scorer_vals = [float(scorer_rank[n]) for n in labeled]
        room_metrics["spearman"] = round(spearman(gold_vals, scorer_vals), 3)
    else:
        room_metrics["spearman"] = None

    return room_metrics


def build_room_entries(
        report_dir: Path,
        frames: list[dict],
        *,
        scorer: str = "cover",
) -> tuple[list[dict], dict[str, dict]]:
    entries: list[dict] = []
    metrics: dict[str, dict] = {}
    for f in frames:
        path = resolve_path(report_dir, f["path"])
        name = frame_name(path)
        m = score_frame(path)
        if scorer == "clip-establishing":
            m["clip_margin"] = clip_establishing_score(path)
        metrics[name] = m
        entries.append({
            "id": f["id"],
            "path": path,
            "name": name,
            "hero": f.get("hero"),
            "quality": f.get("quality") or 0,
        })

    sharpnesses = [metrics[e["name"]]["sharpness"] for e in entries]
    room_median = _percentile(sharpnesses, 0.5)
    room_p25 = _percentile(sharpnesses, 0.25)
    for e in entries:
        m = metrics[e["name"]]
        e["gated_out"] = not _passes_cover_gates(
            m["sharpness"], m["smooth"], m["cbr"], m["clipped"],
            room_median=room_median, room_p25=room_p25,
        )
    return entries, metrics


def aggregate_metrics(per_room: dict[str, dict]) -> dict:
    rooms_with_gold = [r for r in per_room.values() if "top1_hit" in r]
    out: dict = {"per_room": per_room, "n_rooms": len(per_room)}
    latencies = [r["clip_ms_per_frame"] for r in per_room.values()
                 if "clip_ms_per_frame" in r]
    if latencies:
        out["clip_latency_ms_per_frame"] = round(
            sum(latencies) / len(latencies), 1)
    if rooms_with_gold:
        out["top1_hit_rate"] = round(
            100 * sum(1 for r in rooms_with_gold if r["top1_hit"])
            / len(rooms_with_gold), 1)
        out["top3_hit_rate"] = round(
            100 * sum(1 for r in rooms_with_gold if r["top3_hit"])
            / len(rooms_with_gold), 1)
        rhos = [r["spearman"] for r in rooms_with_gold
                if r.get("spearman") is not None]
        out["mean_spearman"] = round(sum(rhos) / len(rhos), 3) if rhos else None
    blur = [r for r in per_room.values() if "blur_reject" in r]
    if blur:
        out["blur_reject_rate"] = round(
            100 * sum(1 for r in blur if r["blur_reject"]) / len(blur), 1)
    return out


def default_output(scorer: str) -> Path:
    return (ROOT / "evals" / "fixtures" / "own-property"
            / f"hero-contact-{scorer}.html")


SCORER_CHOICES = [
    "classical", "establishing", "hard-gates", "cover",
    "linear-musiq", "clip-establishing", "mslap", "siglip",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"),
                    help="build output dir containing inventory.json")
    ap.add_argument("--scorer", default="cover",
                    choices=SCORER_CHOICES,
                    help="ranking method for cover selection (default: cover)")
    ap.add_argument("--weights", type=Path, default=None,
                    help="iqa-linear-weights.json for linear-musiq")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="HTML contact sheet path")
    ap.add_argument("--gold", type=Path, default=None,
                    help="hero-gold.json for metrics")
    ap.add_argument("--relevance-backend", default="siglip",
                    choices=["siglip", "openclip"],
                    help="encoder for --scorer siglip (Apache-2.0)")
    ap.add_argument("--device", default="cpu",
                    help="torch device for --scorer siglip")
    args = ap.parse_args()

    report_dir = args.report_dir.resolve()
    gold = load_gold(args.gold)
    rooms = load_rooms(report_dir)
    if not rooms:
        print("no video frames found", file=sys.stderr)
        return 1

    weights = None
    if args.scorer == "linear-musiq":
        weights = load_linear_weights(args.weights)

    clip_timer = {"start": None, "total": 0.0, "n": 0}
    if args.scorer == "clip-establishing":
        import time
        clip_timer["start"] = time.perf_counter()

    n_frames = sum(len(f) for _, f in rooms)
    print(f"{len(rooms)} rooms, {n_frames} video frames, scorer={args.scorer}")

    room_entries: dict[str, list[dict]] = {}
    all_metrics: dict[str, dict] = {}
    for room_name, frames in rooms:
        entries, metrics = build_room_entries(
            report_dir, frames, scorer=args.scorer)
        room_entries[room_name] = entries
        all_metrics[room_name] = metrics

    if args.scorer == "siglip":
        paths = [e["path"] for entries in room_entries.values() for e in entries]
        try:
            siglip_by_name = score_siglip(
                paths, backend=args.relevance_backend, device=args.device)
        except ImportError as e:
            print(str(e), file=sys.stderr)
            return 1
        for room_name, entries in room_entries.items():
            metrics = all_metrics[room_name]
            for e in entries:
                metrics[e["name"]]["siglip"] = siglip_by_name.get(e["name"], 0.0)

    if args.scorer == "clip-establishing" and clip_timer["start"] is not None:
        import time
        elapsed = time.perf_counter() - clip_timer["start"]
        clip_timer["total"] = elapsed
        clip_timer["n"] = n_frames

    per_room: dict[str, dict] = {}
    for room_name, entries in room_entries.items():
        metrics = all_metrics[room_name]
        per_room[room_name] = evaluate_room(
            scorer=args.scorer,
            entries=entries,
            metrics=metrics,
            gold_room=gold.get(room_name),
            weights=weights,
        )
        if args.scorer == "clip-establishing" and clip_timer["n"]:
            per_room[room_name]["clip_ms_per_frame"] = round(
                1000 * clip_timer["total"] / clip_timer["n"], 1)
        # attach display ranks after evaluation
        by_scorer = sorted(
            entries,
            key=lambda e: scorer_sort_key(
                args.scorer, metrics[e["name"]],
                gated=e.get("gated_out", False),
                weights=weights,
            ),
            reverse=True,
        )
        scorer_rank = {e["name"]: i + 1 for i, e in enumerate(by_scorer)}
        for e in entries:
            e["metrics"] = metrics[e["name"]]
            e["scorer_rank"] = scorer_rank[e["name"]]

    summary = aggregate_metrics(per_room)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_room"},
                     indent=2))

    out_path = (args.output or default_output(args.scorer)).resolve()
    render_html(
        html_path=out_path,
        report_dir=report_dir,
        scorer=args.scorer,
        rooms=rooms,
        room_data=room_entries,
        metrics_summary=summary,
        gold=gold,
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
