#!/usr/bin/env python3
"""ML-E3: estimate describe token savings from two-tier pool scoring.

Scores every video frame like ``curate()`` and reports what fraction would
be dropped if the describe backend skipped the bottom decile by composite
``frame_quality`` score. Production describe is **not** gated — this script
measures savings only (docs/19 ML-E3).

Usage:
    uv run python evals/eval_describe_pool.py report
    uv run python evals/eval_describe_pool.py report --decile 0.1 -o pool.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeinventory.curate import (  # noqa: E402
    _cover_metrics,
    _percentile,
    frame_quality,
    tier_eligibility,
)


def load_video_frames(report_dir: Path) -> list[dict]:
    inv = json.loads((report_dir / "inventory.json").read_text(encoding="utf-8"))
    out: list[dict] = []
    for room in inv["rooms"]:
        for p in room.get("photos", []):
            if p.get("source_video"):
                out.append({
                    "room": room["name"],
                    "id": p["id"],
                    "path": p["path"],
                })
    return out


def resolve_path(report_dir: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else report_dir / path


def score_frames(report_dir: Path, frames: list[dict]) -> list[dict]:
    by_room: dict[str, list[dict]] = {}
    for f in frames:
        by_room.setdefault(f["room"], []).append(f)

    scored: list[dict] = []
    for room, room_frames in by_room.items():
        qualities: list[float] = []
        cover_rows: list[tuple] = []
        for f in room_frames:
            path = resolve_path(report_dir, f["path"])
            q, _, est = frame_quality(path)
            sh, smooth, cbr, clipped = _cover_metrics(path)
            qualities.append(q)
            cover_rows.append((f, q, est, sh, smooth, cbr, clipped))

        room_median = _percentile([r[3] for r in cover_rows], 0.5)
        room_p25 = _percentile([r[3] for r in cover_rows], 0.25)

        for f, q, est, sh, smooth, cbr, clipped in cover_rows:
            desc, pres = tier_eligibility(
                sh, smooth, cbr, clipped,
                room_median=room_median, room_p25=room_p25,
            )
            scored.append({
                "room": room,
                "id": f["id"],
                "path": str(resolve_path(report_dir, f["path"])),
                "composite_quality": q,
                "establishing": est,
                "describe_eligible": desc,
                "presentation_eligible": pres,
            })
    return scored


def bottom_decile_drop(
        scored: list[dict], *, decile: float) -> dict:
    """Fraction of frames below room decile threshold on composite quality."""
    by_room: dict[str, list[dict]] = {}
    for row in scored:
        by_room.setdefault(row["room"], []).append(row)

    dropped = 0
    kept = 0
    per_room: dict[str, dict] = {}
    for room, rows in by_room.items():
        qs = sorted(r["composite_quality"] for r in rows)
        idx = max(int(len(qs) * decile) - 1, 0)
        threshold = qs[idx] if qs else 0.0
        room_drop = sum(1 for r in rows if r["composite_quality"] <= threshold)
        room_keep = len(rows) - room_drop
        dropped += room_drop
        kept += room_keep
        per_room[room] = {
            "n_frames": len(rows),
            "decile_threshold": round(threshold, 2),
            "would_drop": room_drop,
            "would_keep": room_keep,
            "drop_pct": round(100 * room_drop / len(rows), 1) if rows else 0,
        }

    total = dropped + kept
    presentation_in = sum(1 for r in scored if r["presentation_eligible"])
    return {
        "decile": decile,
        "n_frames": total,
        "would_drop_bottom_decile": dropped,
        "would_keep": kept,
        "drop_fraction": round(dropped / total, 3) if total else 0,
        "drop_pct": round(100 * dropped / total, 1) if total else 0,
        "presentation_eligible_count": presentation_in,
        "presentation_eligible_pct": round(
            100 * presentation_in / total, 1) if total else 0,
        "per_room": per_room,
    }


def token_estimate(drop_fraction: float, n_frames: int, *,
                   tokens_per_frame: int) -> dict:
    baseline = n_frames * tokens_per_frame
    saved = int(baseline * drop_fraction)
    return {
        "tokens_per_frame_assumption": tokens_per_frame,
        "baseline_tokens": baseline,
        "estimated_saved_tokens": saved,
        "estimated_remaining_tokens": baseline - saved,
        "saved_pct": round(100 * drop_fraction, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"))
    ap.add_argument("--decile", type=float, default=0.1,
                    help="bottom fraction to hypothetically drop (default 0.1)")
    ap.add_argument("--tokens-per-frame", type=int, default=800,
                    help="VLM token budget per frame for savings estimate")
    ap.add_argument("-o", "--output", type=Path, default=None)
    args = ap.parse_args()

    report_dir = args.report_dir.resolve()
    inv_path = report_dir / "inventory.json"
    if not inv_path.is_file():
        print(f"missing {inv_path}", file=sys.stderr)
        return 1

    frames = load_video_frames(report_dir)
    if not frames:
        print("no video frames found", file=sys.stderr)
        return 1

    scored = score_frames(report_dir, frames)
    drop = bottom_decile_drop(scored, decile=args.decile)
    tokens = token_estimate(
        drop["drop_fraction"], drop["n_frames"],
        tokens_per_frame=args.tokens_per_frame,
    )

    result = {
        "report_dir": str(report_dir),
        "experiment": "ML-E3",
        "note": "describe pool not gated in production — eval estimate only",
        "two_tier_flags": {
            "describe_eligible": "permissive (all frames True in curate)",
            "presentation_eligible": "strict E4 cover gates",
        },
        "pool_drop": drop,
        "token_savings_estimate": tokens,
    }

    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("pool_drop",)}, indent=2))
    print(json.dumps({"pool_drop": drop["drop_pct"],
                      "token_saved_pct": tokens["saved_pct"]}, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
