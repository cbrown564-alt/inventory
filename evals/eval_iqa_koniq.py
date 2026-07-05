#!/usr/bin/env python3
"""ML-E17: compare KonIQ-distilled linear head vs ML-E6 on hero-gold (docs/19).

Scores each room's video frames with:
  - ``iqa-koniq-weights.json`` (this spike)
  - ``iqa-linear-weights.json`` (ML-E6 baseline)

Reports top-1 / top-3 hit rate vs ``hero-gold.json`` and writes an HTML contact
sheet plus JSON metrics.

Usage:
    uv run python evals/train_iqa_koniq.py --bootstrap-scores
    uv run python evals/eval_iqa_koniq.py report \\
        --gold evals/fixtures/own-property/hero-gold.json \\
        -o evals/fixtures/own-property/iqa-koniq-onnx.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_hero_cover import (  # noqa: E402
    build_room_entries,
    evaluate_room,
    img_href,
    linear_musiq_value,
    load_gold,
    load_linear_weights,
    load_rooms,
)

DEFAULT_GOLD = ROOT / "evals" / "fixtures" / "own-property" / "hero-gold.json"
DEFAULT_KONIQ = ROOT / "evals" / "fixtures" / "own-property" / "iqa-koniq-weights.json"
DEFAULT_MLE6 = ROOT / "evals" / "fixtures" / "own-property" / "iqa-linear-weights.json"
DEFAULT_HTML = ROOT / "evals" / "fixtures" / "own-property" / "iqa-koniq-onnx.html"
DEFAULT_JSON = ROOT / "evals" / "fixtures" / "own-property" / "iqa-koniq-metrics.json"


def compare_top1(per_room_koniq: dict, per_room_mle6: dict) -> dict:
    rooms = sorted(set(per_room_koniq) | set(per_room_mle6))
    koniq_hits = []
    mle6_hits = []
    for room in rooms:
        k = per_room_koniq.get(room, {})
        m = per_room_mle6.get(room, {})
        if "top1_hit" in k:
            koniq_hits.append(bool(k["top1_hit"]))
        if "top1_hit" in m:
            mle6_hits.append(bool(m["top1_hit"]))
    n = max(len(koniq_hits), len(mle6_hits), 1)
    koniq_rate = round(100 * sum(koniq_hits) / max(len(koniq_hits), 1), 1)
    mle6_rate = round(100 * sum(mle6_hits) / max(len(mle6_hits), 1), 1)
    return {
        "n_rooms_with_gold": len(koniq_hits),
        "koniq_top1_hit_rate": koniq_rate,
        "mle6_top1_hit_rate": mle6_rate,
        "koniq_top1_hits": f"{sum(koniq_hits)}/{len(koniq_hits) or n}",
        "mle6_top1_hits": f"{sum(mle6_hits)}/{len(mle6_hits) or n}",
        "koniq_beats_mle6": koniq_rate >= mle6_rate,
        "pass_bar": "top-1 ≥ ML-E6 on hero-gold (≥8/9 target per docs/19)",
    }


def render_html(
        *,
        html_path: Path,
        report_dir: Path,
        summary: dict,
        per_room: dict[str, dict],
        room_entries: dict[str, list[dict]],
        koniq_weights: dict,
        mle6_weights: dict,
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        "<title>ML-E17 KonIQ linear vs ML-E6</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:1rem;background:#111;color:#eee}",
        "h1,h2{margin:0.5rem 0}",
        ".summary{background:#222;padding:1rem;border-radius:8px;margin-bottom:1.5rem}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}",
        ".cell{background:#222;border-radius:8px;overflow:hidden;border:2px solid #333}",
        ".cell.koniq{border-color:#4caf50}",
        ".cell.mle6{border-color:#2196f3}",
        ".cell img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover;background:#000}",
        ".meta{padding:8px;font-size:12px;line-height:1.4}",
        ".metrics{color:#aaa}",
        "</style></head><body>",
        "<h1>ML-E17 — KonIQ-distilled linear vs ML-E6</h1>",
        f"<p>Report: {html.escape(str(report_dir))}</p>",
        "<div class='summary'><h2>Summary</h2><pre>",
        html.escape(json.dumps(summary, indent=2)),
        "</pre></div>",
    ]

    for room_name, room_metrics in per_room.items():
        entries = room_entries[room_name]
        parts.append(f"<h2>{html.escape(room_name)}</h2>")
        parts.append(
            f"<p>KonIQ pick: <strong>{html.escape(room_metrics.get('koniq_pick', '—'))}</strong> "
            f"| ML-E6 pick: <strong>{html.escape(room_metrics.get('mle6_pick', '—'))}</strong> "
            f"| gold top-1 hit koniq={room_metrics.get('koniq_top1_hit')} "
            f"mle6={room_metrics.get('mle6_top1_hit')}</p>"
        )
        parts.append("<div class='grid'>")
        for e in sorted(entries, key=lambda x: x.get("koniq_rank", 999)):
            m = e["metrics"]
            cls = ""
            if e["name"] == room_metrics.get("koniq_pick"):
                cls = " koniq"
            elif e["name"] == room_metrics.get("mle6_pick"):
                cls = " mle6"
            parts.extend([
                f"<div class='cell{cls}'>",
                f"<img src='{img_href(html_path, e['path'])}' "
                f"alt='{html.escape(e['name'])}'>",
                "<div class='meta'>",
                f"<strong>{html.escape(e['name'])}</strong><br>",
                f"<span class='metrics'>",
                f"koniq={e.get('koniq_score', 0):.2f} rank={e.get('koniq_rank')} "
                f"mle6={e.get('mle6_score', 0):.2f} rank={e.get('mle6_rank')} "
                f"sh={m['sharpness']:.0f}",
                "</span></div></div>",
            ])
        parts.append("</div>")

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    gold = load_gold(args.gold)
    koniq_w = load_linear_weights(args.koniq_weights)
    mle6_w = load_linear_weights(args.mle6_weights)

    if args.demo:
        return run_demo(args, koniq_w, mle6_w, gold)

    report_dir = args.report_dir.resolve()
    rooms = load_rooms(report_dir)
    if not rooms:
        raise SystemExit("no video frames found — pass report dir or --demo")

    per_room_out: dict[str, dict] = {}
    per_room_koniq: dict[str, dict] = {}
    per_room_mle6: dict[str, dict] = {}
    room_entries: dict[str, list[dict]] = {}

    for room_name, frames in rooms:
        entries, metrics = build_room_entries(report_dir, frames)
        for e in entries:
            m = metrics[e["name"]]
            e["koniq_score"] = linear_musiq_value(m, koniq_w)
            e["mle6_score"] = linear_musiq_value(m, mle6_w)

        by_koniq = sorted(entries, key=lambda e: e["koniq_score"], reverse=True)
        by_mle6 = sorted(entries, key=lambda e: e["mle6_score"], reverse=True)
        koniq_rank = {e["name"]: i + 1 for i, e in enumerate(by_koniq)}
        mle6_rank = {e["name"]: i + 1 for i, e in enumerate(by_mle6)}
        for e in entries:
            e["koniq_rank"] = koniq_rank[e["name"]]
            e["mle6_rank"] = mle6_rank[e["name"]]
            e["metrics"] = metrics[e["name"]]

        room_entries[room_name] = entries
        km = evaluate_room(
            scorer="linear-musiq", entries=entries, metrics=metrics,
            gold_room=gold.get(room_name), weights=koniq_w,
        )
        mm = evaluate_room(
            scorer="linear-musiq", entries=entries, metrics=metrics,
            gold_room=gold.get(room_name), weights=mle6_w,
        )
        per_room_koniq[room_name] = km
        per_room_mle6[room_name] = mm
        per_room_out[room_name] = {
            "koniq_pick": km.get("pick"),
            "mle6_pick": mm.get("pick"),
            "koniq_top1_hit": km.get("top1_hit"),
            "mle6_top1_hit": mm.get("top1_hit"),
            "koniq_top3_hit": km.get("top3_hit"),
            "mle6_top3_hit": mm.get("top3_hit"),
            "koniq_spearman": km.get("spearman"),
            "mle6_spearman": mm.get("spearman"),
        }

    comparison = compare_top1(per_room_koniq, per_room_mle6)
    summary = {
        "experiment": "ML-E17",
        "report_dir": str(report_dir),
        "koniq_weights": str(args.koniq_weights.relative_to(ROOT)),
        "mle6_weights": str(args.mle6_weights.relative_to(ROOT)),
        "comparison": comparison,
        "koniq_training_mode": koniq_w.get("training", {}).get("mode"),
        "disclaimer": koniq_w.get("disclaimer"),
        "per_room": per_room_out,
    }

    if args.output.suffix.lower() == ".json":
        json_path = args.output
        html_path = args.json_output or DEFAULT_HTML
    else:
        html_path = args.output
        json_path = args.json_output or DEFAULT_JSON

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    render_html(
        html_path=html_path,
        report_dir=report_dir,
        summary=summary,
        per_room=per_room_out,
        room_entries=room_entries,
        koniq_weights=koniq_w,
        mle6_weights=mle6_w,
    )
    print(json.dumps(comparison, indent=2))
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    return summary


def run_demo(
        args: argparse.Namespace,
        koniq_w: dict,
        mle6_w: dict,
        gold: dict,
) -> dict:
    """Metrics-only demo when report frames are absent (CI-safe)."""
    comparison = {
        "n_rooms_with_gold": len(gold),
        "koniq_top1_hit_rate": None,
        "mle6_top1_hit_rate": 77.8,
        "koniq_top1_hits": "demo",
        "mle6_top1_hits": "7/9",
        "koniq_beats_mle6": None,
        "pass_bar": "top-1 ≥ ML-E6 on hero-gold (≥8/9 target per docs/19)",
        "mode": "demo-no-report",
        "note": "Re-run with report dir containing inventory.json for live metrics",
    }
    summary = {
        "experiment": "ML-E17",
        "report_dir": None,
        "comparison": comparison,
        "koniq_training_mode": koniq_w.get("training", {}).get("mode"),
        "disclaimer": koniq_w.get("disclaimer"),
    }
    json_path = args.json_output or DEFAULT_JSON
    html_path = args.output if args.output.suffix.lower() != ".json" else DEFAULT_HTML
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    html_path.write_text(
        "<!DOCTYPE html><html><body><pre>"
        + html.escape(json.dumps(summary, indent=2))
        + "</pre></body></html>",
        encoding="utf-8",
    )
    print(json.dumps(comparison, indent=2))
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"))
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--koniq-weights", type=Path, default=DEFAULT_KONIQ)
    ap.add_argument("--mle6-weights", type=Path, default=DEFAULT_MLE6)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--json-output", type=Path, default=None)
    ap.add_argument("--demo", action="store_true",
                    help="write demo metrics without report frames")
    args = ap.parse_args()

    if not args.koniq_weights.is_file():
        print(f"missing {args.koniq_weights} — run train_iqa_koniq.py first",
              file=sys.stderr)
        return 1

    try:
        run(args)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
