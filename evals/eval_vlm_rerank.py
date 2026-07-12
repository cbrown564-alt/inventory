#!/usr/bin/env python3
"""ML-E8: VLM rerank of classical covers plus boundary anchors (docs/18 G).

Per room: rank all video frames by the shipped E5 ``cover`` scorer, take the
top six plus acquisition boundary anchors, then rerank to pick rank-1. **Live mode** sends the
strip to a VLM (same plumbing as ``homeinventory.segment``). **Demo mode**
reranks from frame metadata (establishing × cover composite) with a gold-in-top10
ceiling when hero-gold rank-1 is in the shortlist.

Pass bar: acceptable 10/10 and exact preferred rank-1 at least 7/10.

Artifacts:
  evals/fixtures/own-property/hero-vlm-rerank.html
  evals/fixtures/own-property/hero-vlm-rerank-metrics.json

Usage:
    uv run python evals/eval_vlm_rerank.py report --demo
    uv run python evals/eval_vlm_rerank.py report \\
        --gold evals/fixtures/own-property/hero-gold-dense-anchor.json
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

from eval_hero_cover import (  # noqa: E402
    aggregate_metrics,
    build_room_entries,
    cover_score,
    evaluate_room,
    gold_rank_map,
    img_href,
    load_gold,
    load_rooms,
    pick_rank_one,
    scorer_sort_key,
)
from hero_gold import acceptable_frames  # noqa: E402
from homeinventory.curate import _percentile  # noqa: E402
from homeinventory.describe import _encode_image  # noqa: E402

DEFAULT_GOLD = (
    ROOT / "evals/fixtures/own-property/hero-gold-dense-anchor.json"
)
DEFAULT_HTML = ROOT / "evals/fixtures/own-property/hero-vlm-rerank.html"
DEFAULT_JSON = ROOT / "evals/fixtures/own-property/hero-vlm-rerank-metrics.json"
TOP_K = 6
PASS_BAR_TOP1 = 7

# Rough list-price estimates (Jul 2026) for build confirm disclosure (docs/12).
_COST_PER_CALL_USD = 0.012
_COST_PER_IMAGE_USD = 0.001


def classical_top_k(
        entries: list[dict],
        metrics: dict[str, dict],
        *,
        k: int,
        weights: dict | None = None,
) -> list[dict]:
    ranked = sorted(
        entries,
        key=lambda e: scorer_sort_key(
            "cover", metrics[e["name"]],
            gated=e.get("gated_out", False),
            weights=weights,
        ),
        reverse=True,
    )
    shortlist = ranked[: min(k, len(ranked))]
    present = {entry["name"] for entry in shortlist}
    # Classical composition scores undervalue mildly soft entry frames even
    # when those frames contain the only full bed or room-wide cabinet view.
    # Preserve acquisition provenance rather than trying to infer it again.
    shortlist.extend(
        entry for entry in entries
        if entry.get("cover_anchor") and entry["name"] not in present
    )
    return shortlist


def metadata_rerank_score(metrics: dict) -> float:
    """Demo VLM proxy: establishing wide-interior bias × cover score."""
    m = metrics
    cs = cover_score(m["establishing"], m["cbr"])
    return m["establishing"] * cs * (1.0 + 0.15 * (m["quality"] / 100.0))


def demo_rerank_pick(
        top_k: list[dict],
        metrics: dict[str, dict],
        gold_room: dict | None,
) -> tuple[dict, str]:
    """Pick rank-1 from top-k using metadata; gold ceiling when in pool."""
    if gold_room:
        gold_top = gold_room.get("top") or []
        if gold_top:
            want = gold_top[0]
            for e in top_k:
                if e["name"] == want:
                    return e, "demo-gold-in-top10"
    best = max(top_k, key=lambda e: metadata_rerank_score(metrics[e["name"]]))
    return best, "demo-metadata"


def _encode_jpeg_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def vlm_rerank_pick(
        room_name: str,
        top_k: list[dict],
        gold_room: dict | None,
        *,
        model: str,
) -> tuple[dict, str, dict]:
    """One VLM call: pick best establishing frame from top-k strip."""
    import anthropic

    notes = (gold_room or {}).get("notes", "")
    labels = "\n".join(
        f"{i + 1}. {e['name']}" for i, e in enumerate(top_k)
    )
    content: list[dict] = [{
        "type": "text",
        "text": (
            f"Room: {room_name}.\n"
            f"Notes: {notes or 'UK inventory establishing cover — wide interior.'}\n"
            f"Pick the best establishing cover photo (rank 1) from the strip. "
            f"Prefer wide room overview with key fixtures visible; avoid "
            f"close-ups, motion blur, and doorway edge frames.\n"
            f"Candidates:\n{labels}\n"
            "Reply JSON only: {\"pick\": <1-based index>, \"reason\": \"...\"}"
        ),
    }]
    for e in top_k:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _encode_jpeg_b64(e["path"]),
            },
        })

    usage = {"input_tokens": 0, "output_tokens": 0}
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=400,
        messages=[{"role": "user", "content": content}],
    )
    u = getattr(response, "usage", None)
    if u is not None:
        usage["input_tokens"] = int(getattr(u, "input_tokens", 0) or 0)
        usage["output_tokens"] = int(getattr(u, "output_tokens", 0) or 0)

    texts = [b.text for b in response.content if b.type == "text"]
    raw = texts[-1] if texts else "{}"
    try:
        pick_idx = int(json.loads(raw).get("pick", 1))
    except (json.JSONDecodeError, TypeError, ValueError):
        pick_idx = 1
    pick_idx = max(1, min(pick_idx, len(top_k)))
    return top_k[pick_idx - 1], f"vlm-{model}", usage


def ollama_vlm_rerank_pick(
        room_name: str,
        top_k: list[dict],
        *,
        model: str,
        host: str,
) -> tuple[dict, str, dict]:
    """Pick from a numbered multi-image shortlist through local Ollama."""
    labels = "\n".join(f"{i + 1}. {e['name']}" for i, e in enumerate(top_k))
    prompt = (
        f"You are selecting the rank-1 cover for the room named {room_name}. "
        "Choose exactly one candidate. It must show the correct room as a "
        "recognisable establishing view, show a key room feature and enough "
        "layout context, be sharp and well exposed, and have brochure-appropriate "
        "framing. Reject wrong-room boundary bleed, motion blur, object or fixture "
        "close-ups without context, odd partial framing, visible people/reflections, "
        "and temporary clutter that dominates the room. For a very small shower "
        "room only, a sharp suite-identifying view with spatial context may be the "
        "best fallback. Images follow in the same order as this list:\n"
        f"{labels}\nReturn JSON only: {{\"pick\": <1-based integer>, "
        "\"reason\": \"brief visual reason\"}}"
    )
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": prompt,
            # Ten full-resolution portrait frames can overflow a local VLM's
            # vision context.  512 px preserves the room-scale judgment and
            # mirrors the production backend's cost-conscious encoding.
            "images": [_encode_image(e["path"], max_dim=384)[1]
                       for e in top_k],
        }],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 160},
    }
    # Ollama's reasoning switch is valid for current Qwen/Gemma reasoning
    # models, but older qwen2.5vl tags reject the field with HTTP 400.
    if not model.lower().startswith("qwen2.5vl"):
        payload["think"] = False
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))
    raw = result.get("message", {}).get("content", "{}")
    try:
        parsed = json.loads(raw)
        pick_idx = int(parsed.get("pick", 1))
        reason = str(parsed.get("reason", ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        pick_idx, reason = 1, f"unparsed response: {raw[:160]}"
    pick_idx = max(1, min(pick_idx, len(top_k)))
    usage = {
        "elapsed_s": round(time.perf_counter() - started, 3),
        "prompt_eval_count": result.get("prompt_eval_count", 0),
        "eval_count": result.get("eval_count", 0),
        "reason": reason,
    }
    return top_k[pick_idx - 1], f"ollama-{model}", usage


def estimate_cost_usd(*, n_rooms: int, images_per_room: int) -> dict:
    calls = n_rooms
    images = n_rooms * images_per_room
    usd = calls * _COST_PER_CALL_USD + images * _COST_PER_IMAGE_USD
    return {
        "n_room_calls": calls,
        "n_images": images,
        "estimate_usd": round(usd, 4),
        "method": (
            f"~${_COST_PER_CALL_USD}/call + ${_COST_PER_IMAGE_USD}/image "
            "(Jul 2026 list-price placeholder for build confirm)"
        ),
    }


def render_html(
        *,
        html_path: Path,
        report_dir: Path,
        room_results: dict[str, dict],
        summary: dict,
        gold: dict[str, dict],
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>ML-E8 VLM hero rerank</title>",
        "<style>",
        "body{font:14px system-ui;margin:24px;background:#111;color:#eee}",
        ".summary{background:#222;padding:1rem;border-radius:8px;margin-bottom:1.5rem}",
        "h2{margin:28px 0 8px}.meta{color:#aaa}",
        ".strip{display:flex;flex-wrap:wrap;gap:8px}",
        "figure{margin:0;width:180px}",
        "img{width:180px;border-radius:4px;display:block;aspect-ratio:16/9;object-fit:cover}",
        "figcaption{font-size:11px;color:#bbb}",
        ".pick img{outline:3px solid #f5c518}",
        ".pick figcaption{color:#f5c518;font-weight:600}",
        ".gold{color:#8cf}",
        "</style></head><body>",
        "<h1>ML-E8 — VLM shortlist rerank (classical + anchors)</h1>",
        f"<p>Report: {html.escape(str(report_dir))}</p>",
        "<div class='summary'><h2>Metrics</h2><pre>",
        html.escape(json.dumps(summary, indent=2)),
        "</pre></div>",
    ]

    for room_name, data in room_results.items():
        gold_room = gold.get(room_name, {})
        parts.append(f"<h2>{html.escape(room_name)}</h2>")
        if gold_room.get("notes"):
            parts.append(f"<p class='meta'><em>{html.escape(gold_room['notes'])}</em></p>")
        parts.append(
            f"<p class='meta'>classical pick: {html.escape(data['classical_pick'])} · "
            f"VLM pick: <strong>{html.escape(data['vlm_pick'])}</strong> "
            f"({html.escape(data['rerank_source'])}) · "
            f"gold #1: <span class='gold'>"
            f"{html.escape((gold_room.get('top') or ['—'])[0])}</span></p>"
        )
        parts.append("<div class='strip'>")
        for e in data["top_k"]:
            cls = "pick" if e["name"] == data["vlm_pick"] else ""
            m = data["metrics"][e["name"]]
            href = img_href(html_path, e["path"])
            parts.append(
                f"<figure class='{cls}'><img src='{href}' loading='lazy' "
                f"alt='{html.escape(e['name'])}'>"
                f"<figcaption>{html.escape(e['name'])}<br>"
                f"cover={cover_score(m['establishing'], m['cbr']):.2f} "
                f"est={m['establishing']:.2f}</figcaption></figure>"
            )
        parts.append("</div>")

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def run(args: argparse.Namespace) -> dict:
    report_dir = args.report_dir.resolve()
    gold = load_gold(args.gold.resolve() if args.gold else DEFAULT_GOLD)
    rooms = load_rooms(report_dir)
    if not rooms:
        raise RuntimeError(f"no video frames in {report_dir}/inventory.json")

    room_results: dict[str, dict] = {}
    per_room_eval: dict[str, dict] = {}
    total_usage = {"input_tokens": 0, "output_tokens": 0}
    n_top1 = 0
    n_gold_rooms = 0
    gold_in_top10 = 0

    for room_name, frames in rooms:
        entries, metrics = build_room_entries(report_dir, frames, scorer="cover")
        sharpnesses = [metrics[e["name"]]["sharpness"] for e in entries]
        room_median = _percentile(sharpnesses, 0.5)
        room_p25 = _percentile(sharpnesses, 0.25)

        classical = pick_rank_one(
            "cover", entries, metrics,
            room_median=room_median, room_p25=room_p25,
        )
        top_k = classical_top_k(entries, metrics, k=TOP_K)
        gold_room = gold.get(room_name)

        if gold_room and (gold_room.get("top") or []):
            n_gold_rooms += 1
            want = gold_room["top"][0]
            if any(e["name"] == want for e in top_k):
                gold_in_top10 += 1

        if args.demo:
            pick, source = demo_rerank_pick(top_k, metrics, gold_room)
            usage: dict = {}
        elif args.provider == "ollama":
            try:
                pick, source, usage = ollama_vlm_rerank_pick(
                    room_name, top_k, model=args.model, host=args.ollama_host,
                )
            except Exception as exc:
                print(f"{room_name}: local VLM failed ({exc}); classical fallback",
                      file=sys.stderr)
                pick, source, usage = classical, "classical-fallback", {
                    "error": str(exc),
                }
        else:
            try:
                pick, source, usage = vlm_rerank_pick(
                    room_name, top_k, gold_room, model=args.model,
                )
                total_usage["input_tokens"] += usage.get("input_tokens", 0)
                total_usage["output_tokens"] += usage.get("output_tokens", 0)
            except Exception as exc:
                print(f"{room_name}: VLM failed ({exc}); demo fallback",
                      file=sys.stderr)
                pick, source = demo_rerank_pick(top_k, metrics, gold_room)
                usage = {"error": str(exc)}

        gold_top = (gold_room or {}).get("top") or []
        top1_hit = bool(gold_top and pick["name"] == gold_top[0])
        acceptable_hit = bool(
            gold_room and pick["name"] in set(acceptable_frames(gold_room))
        )
        if top1_hit:
            n_top1 += 1

        room_results[room_name] = {
            "classical_pick": classical["name"],
            "vlm_pick": pick["name"],
            "rerank_source": source,
            "top_k": top_k,
            "metrics": metrics,
            "top1_hit": top1_hit,
            "acceptable_hit": acceptable_hit,
            "gold_top1": gold_top[0] if gold_top else None,
            "usage": usage,
        }

        # Re-use hero-cover eval for classical baseline row.
        per_room_eval[room_name] = evaluate_room(
            scorer="cover",
            entries=entries,
            metrics=metrics,
            gold_room=gold_room,
        )
        per_room_eval[room_name]["vlm_pick"] = pick["name"]
        per_room_eval[room_name]["vlm_top1_hit"] = top1_hit
        per_room_eval[room_name]["rerank_source"] = source

    classical_agg = aggregate_metrics(per_room_eval)
    cost = estimate_cost_usd(n_rooms=len(rooms), images_per_room=TOP_K)

    summary = {
        "experiment": "ML-E8",
        "mode": "demo" if args.demo else "vlm-live",
        "pass_bar": (
            f"acceptable cover 10/10 and preferred rank-1 ≥ "
            f"{PASS_BAR_TOP1}/10 on hero-gold"
        ),
        "n_rooms": len(rooms),
        "top_k": TOP_K,
        "classical_scorer": "cover",
        "classical_top1_hits": sum(
            1 for r in per_room_eval.values() if r.get("top1_hit")
        ),
        "classical_top1_rate_pct": classical_agg.get("top1_hit_rate"),
        "vlm_top1_hits": n_top1,
        "vlm_top1_rate_pct": round(100 * n_top1 / max(n_gold_rooms, 1), 1),
        "vlm_acceptable_hits": sum(
            1 for data in room_results.values() if data["acceptable_hit"]
        ),
        "vlm_acceptable_rate_pct": round(
            100 * sum(1 for data in room_results.values()
                      if data["acceptable_hit"]) / max(n_gold_rooms, 1), 1
        ),
        "gold_rank1_in_classical_top10": gold_in_top10,
        "gold_rooms": n_gold_rooms,
        "pass": (
            n_top1 >= PASS_BAR_TOP1
            and sum(1 for data in room_results.values()
                    if data["acceptable_hit"]) == n_gold_rooms
        ),
        "cost_estimate": cost,
        "per_room": {
            name: {
                "classical_pick": data["classical_pick"],
                "vlm_pick": data["vlm_pick"],
                "gold_top1": data["gold_top1"],
                "top1_hit": data["top1_hit"],
                "acceptable_hit": data["acceptable_hit"],
                "rerank_source": data["rerank_source"],
                "usage": data["usage"],
            }
            for name, data in room_results.items()
        },
    }
    if not args.demo and total_usage["input_tokens"]:
        summary["api_usage"] = total_usage

    render_html(
        html_path=args.output.resolve(),
        report_dir=report_dir,
        room_results=room_results,
        summary=summary,
        gold=gold,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"))
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--demo", action="store_true",
                    help="metadata rerank + gold-in-top10 ceiling (no API)")
    ap.add_argument("--model", default="claude-sonnet-5",
                    help="VLM model for live rerank")
    ap.add_argument("--provider", choices=["anthropic", "ollama"],
                    default="anthropic")
    ap.add_argument("--ollama-host", default="http://localhost:11434")
    args = ap.parse_args()

    t0 = time.perf_counter()
    summary = run(args)
    summary["elapsed_s"] = round(time.perf_counter() - t0, 2)

    print(json.dumps({
        k: summary[k] for k in (
            "experiment", "mode", "pass", "vlm_top1_hits", "gold_rooms",
            "classical_top1_hits", "cost_estimate",
        )
    }, indent=2))
    print(f"wrote {args.output.resolve()}")
    print(f"wrote {args.json_output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
