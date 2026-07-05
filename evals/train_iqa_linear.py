#!/usr/bin/env python3
"""ML-E6: train a global linear reranker on classical features → MUSIQ score.

Reads ``evals/fixtures/own-property/iqa-comparison-mps.json`` for MUSIQ
oracle targets (eval only, NC licence) and fits ridge regression on PIL
features from ``homeinventory.curate``. Exports MIT-licensed weights for
``eval_hero_cover.py --scorer linear-musiq``.

Usage:
    uv run python evals/train_iqa_linear.py
    uv run python evals/train_iqa_linear.py --report report \\
        -o evals/fixtures/own-property/iqa-linear-weights.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeinventory.curate import (  # noqa: E402
    _cover_metrics,
    classical_features,
    frame_quality,
)

DEFAULT_FIXTURE = (
    ROOT / "evals" / "fixtures" / "own-property" / "iqa-comparison-mps.json"
)
DEFAULT_OUT = ROOT / "evals" / "fixtures" / "own-property" / "iqa-linear-weights.json"

FEATURE_NAMES = [
    "bias",
    "log_sharpness",
    "smooth",
    "log_cbr",
    "clipped",
    "establishing",
    "cover",
]


def resolve_frame_path(raw: str, report_dir: Path) -> Path | None:
    p = Path(raw)
    if p.is_file():
        return p
    if not p.is_absolute():
        candidate = report_dir / p
        if candidate.is_file():
            return candidate
    # fixture paths often use absolute mac paths — match by basename
    name = p.name
    for hit in report_dir.rglob(name):
        if hit.is_file():
            return hit
    return None


def extract_row(path: Path) -> dict[str, float] | None:
    try:
        q, _, est = frame_quality(path)
        sh, smooth, cbr, clipped = _cover_metrics(path)
        feats = classical_features(sh, smooth, cbr, clipped, est, q)
        row = {n: 1.0 if n == "bias" else feats.get(n, 0.0)
               for n in FEATURE_NAMES}
        return row
    except OSError:
        return None


def load_training_rows(
        fixture: Path, report_dir: Path) -> tuple[list[list[float]], list[float], int]:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    musiq = data["scores"]["musiq"]
    frames = data["frames"]
    xs: list[list[float]] = []
    ys: list[float] = []
    n_resolved = 0
    for room, room_frames in frames.items():
        targets = musiq.get(room, [])
        for i, fr in enumerate(room_frames):
            if i >= len(targets):
                break
            path = resolve_frame_path(fr["path"], report_dir)
            if path is None:
                continue
            row = extract_row(path)
            if row is None:
                continue
            xs.append([row[n] for n in FEATURE_NAMES])
            ys.append(float(targets[i]))
            n_resolved += 1
    return xs, ys, n_resolved


def bootstrap_from_scores(fixture: Path) -> tuple[list[list[float]], list[float]]:
    """When frame files are absent, fit on classical+MUSIQ score arrays only."""
    data = json.loads(fixture.read_text(encoding="utf-8"))
    classical = data["scores"]["classical"]
    musiq = data["scores"]["musiq"]
    xs: list[list[float]] = []
    ys: list[float] = []
    for room in classical:
        cs = classical[room]
        ms = musiq.get(room, [])
        if not cs or len(cs) != len(ms):
            continue
        lo, hi = min(cs), max(cs)
        span = hi - lo or 1.0
        order = sorted(range(len(cs)), key=lambda i: cs[i])
        rank_pct = [0.0] * len(cs)
        for r, idx in enumerate(order):
            rank_pct[idx] = (r + 1) / len(cs)
        for i, (c, m) in enumerate(zip(cs, ms)):
            norm_c = (c - lo) / span
            xs.append([
                1.0,
                math.log1p(max(c, 0.0) / 100.0),
                1.0 - norm_c,          # proxy smooth (low classical)
                math.log(1.0 + (1.0 - rank_pct[i]) * 5),
                max(0.0, norm_c - 0.85),  # proxy clipped
                rank_pct[i],           # proxy establishing
                norm_c * rank_pct[i],  # proxy cover
            ])
            ys.append(float(m))
    return xs, ys


def ridge_fit(xs: list[list[float]], ys: list[float], *,
              alpha: float = 1.0) -> list[float]:
    """Normal-equations ridge regression (pure Python)."""
    n = len(FEATURE_NAMES)
    if not xs:
        raise ValueError("no training rows")

    # X'X + alpha I
    xtx = [[0.0] * n for _ in range(n)]
    xty = [0.0] * n
    for x, y in zip(xs, ys):
        for i in range(n):
            xty[i] += x[i] * y
            for j in range(n):
                xtx[i][j] += x[i] * x[j]
    for i in range(n):
        xtx[i][i] += alpha

    # Gaussian elimination
    aug = [xtx[i][:] + [xty[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col] or 1e-9
        for j in range(col, n + 1):
            aug[col][j] /= div
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    if len(xs) < 3:
        return float("nan")
    ra, rb = ranks(xs), ranks(ys)
    ma = sum(ra) / len(ra)
    mb = sum(rb) / len(rb)
    cov = sum((a - ma) * (b - mb) for a, b in zip(ra, rb))
    va = sum((a - ma) ** 2 for a in ra)
    vb = sum((b - mb) ** 2 for b in rb)
    if va == 0 or vb == 0:
        return float("nan")
    return cov / (va * vb) ** 0.5


def train_eval(xs: list[list[float]], ys: list[float], weights: list[float]) -> dict:
    preds = [sum(w * x for w, x in zip(weights, row)) for row in xs]
    return {
        "n_samples": len(xs),
        "spearman_pred_vs_musiq": round(spearman(preds, ys), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--report", type=Path, default=Path("report"))
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--alpha", type=float, default=1.0, help="ridge penalty")
    ap.add_argument("--bootstrap-scores", action="store_true",
                    help="force score-only bootstrap (no frame files)")
    args = ap.parse_args()

    xs, ys, n_resolved = load_training_rows(args.fixture, args.report)
    mode = "features"
    if not xs or args.bootstrap_scores:
        xs, ys = bootstrap_from_scores(args.fixture)
        mode = "bootstrap-scores"
        n_resolved = len(xs)

    weights = ridge_fit(xs, ys, alpha=args.alpha)
    metrics = train_eval(xs, ys, weights)

    payload = {
        "experiment": "ML-E6",
        "licence": "MIT",
        "target": "musiq_score",
        "target_note": "MUSIQ oracle (eval only, NC) — weights are MIT",
        "features": FEATURE_NAMES,
        "weights": [round(w, 6) for w in weights],
        "training": {
            "fixture": str(args.fixture.relative_to(ROOT)),
            "mode": mode,
            "n_resolved_frames": n_resolved,
            "ridge_alpha": args.alpha,
            **metrics,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    size_kb = args.output.stat().st_size / 1024
    print(json.dumps(payload["training"], indent=2))
    print(f"wrote {args.output} ({size_kb:.1f} KB)")
    if size_kb > 10:
        print("warning: weights file exceeds 10 KB target", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
