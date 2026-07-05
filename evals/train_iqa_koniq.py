#!/usr/bin/env python3
"""ML-E17: KonIQ-10k pretrain spike → distill linear / ONNX head (docs/19).

Attempts KonIQ-10k MOS targets from:
  1. Local cache ``evals/external/data/koniq10k/`` (scores CSV + images)
  2. HF streaming if a repo is configured (none official as of Jul 2026)
  3. **Bootstrap fallback** from ``iqa-comparison-mps.json`` (MUSIQ as MOS proxy)

Exports MIT-licensed weights for ``eval_iqa_koniq.py`` and optional ONNX via
``export_onnx.py``.

Usage:
    uv run python evals/train_iqa_koniq.py
    uv run python evals/train_iqa_koniq.py --bootstrap-scores
    uv run python evals/export_onnx.py evals/fixtures/own-property/iqa-koniq-weights.json \\
        -o evals/fixtures/own-property/iqa-koniq.onnx
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.train_iqa_linear import (  # noqa: E402
    FEATURE_NAMES,
    bootstrap_from_scores,
    extract_row,
    load_training_rows,
    ridge_fit,
    spearman,
    train_eval,
)

DEFAULT_FIXTURE = (
    ROOT / "evals" / "fixtures" / "own-property" / "iqa-comparison-mps.json"
)
DEFAULT_OUT = ROOT / "evals" / "fixtures" / "own-property" / "iqa-koniq-weights.json"
KONIQ_DIR = ROOT / "evals" / "external" / "data" / "koniq10k"
KONIQ_SCORE_FILES = (
    "koniq10k_scores_and_distributions.csv",
    "koniq10k_scores_and_distributions.tab",
    "koniq10k_distributions_sets.csv",
)


def find_koniq_scores() -> Path | None:
    for name in KONIQ_SCORE_FILES:
        p = KONIQ_DIR / name
        if p.is_file():
            return p
    for p in KONIQ_DIR.glob("*scores*"):
        if p.is_file():
            return p
    return None


def load_koniq_mos(scores_path: Path) -> dict[str, float]:
    """{image_stem: MOS} from KonIQ scores file."""
    mos: dict[str, float] = {}
    delim = "\t" if scores_path.suffix == ".tab" else ","
    with scores_path.open(encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delim)
        for row in reader:
            name = (
                row.get("image_name")
                or row.get("image")
                or row.get("name")
                or row.get("file_name")
                or ""
            ).strip()
            if not name:
                continue
            stem = Path(name).stem
            raw = (
                row.get("MOS")
                or row.get("mos")
                or row.get("mean")
                or row.get("quality")
            )
            if raw is None:
                continue
            try:
                mos[stem] = float(raw)
            except ValueError:
                continue
    return mos


def find_koniq_image(stem: str) -> Path | None:
    for sub in ("images", "512x384", "1024x768", ""):
        base = KONIQ_DIR / sub if sub else KONIQ_DIR
        for ext in (".jpg", ".jpeg", ".png"):
            p = base / f"{stem}{ext}"
            if p.is_file():
                return p
    hits = list(KONIQ_DIR.rglob(f"{stem}.*"))
    return hits[0] if hits else None


def load_koniq_feature_rows(
        *,
        scores_path: Path,
        max_samples: int,
) -> tuple[list[list[float]], list[float], int]:
    mos_map = load_koniq_mos(scores_path)
    xs: list[list[float]] = []
    ys: list[float] = []
    n_resolved = 0
    for stem, mos in mos_map.items():
        if n_resolved >= max_samples:
            break
        img = find_koniq_image(stem)
        if img is None:
            continue
        row = extract_row(img)
        if row is None:
            continue
        xs.append([row[n] for n in FEATURE_NAMES])
        ys.append(mos)
        n_resolved += 1
    return xs, ys, n_resolved


def try_stream_koniq(max_samples: int) -> tuple[list[list[float]], list[float], int, str]:
    """Placeholder for future HF KonIQ repo — returns empty if unavailable."""
    return [], [], 0, "hf-unavailable"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--report", type=Path, default=Path("report"))
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--max-samples", type=int, default=512,
                    help="cap KonIQ rows processed (local cache)")
    ap.add_argument("--bootstrap-scores", action="store_true",
                    help="force MUSIQ-proxy bootstrap (disclaimer in output)")
    args = ap.parse_args()

    mode = "unset"
    disclaimer: str | None = None
    xs: list[list[float]] = []
    ys: list[float] = []
    n_resolved = 0

    if not args.bootstrap_scores:
        scores_path = find_koniq_scores()
        if scores_path:
            xs, ys, n_resolved = load_koniq_feature_rows(
                scores_path=scores_path, max_samples=args.max_samples)
            mode = "koniq-local"
        if not xs:
            xs, ys, n_resolved, hf_mode = try_stream_koniq(args.max_samples)
            if xs:
                mode = hf_mode

    if args.bootstrap_scores:
        xs, ys = bootstrap_from_scores(args.fixture)
        mode = "bootstrap-musiq-proxy"
        disclaimer = (
            "DISCLAIMER: KonIQ-10k images/scores not present under "
            f"{KONIQ_DIR.relative_to(ROOT)}. Trained classical→MUSIQ "
            "proxy from iqa-comparison-mps.json — NOT true KonIQ pretrain. "
            "Register at https://database.mmsp-kn.de/koniq-10k-database.html "
            "and unpack to evals/external/data/koniq10k/ for real MOS targets."
        )
        n_resolved = len(xs)
    elif not xs:
        xs, ys, n_resolved = load_training_rows(args.fixture, args.report)
        mode = "own-property-features"
        if not xs:
            xs, ys = bootstrap_from_scores(args.fixture)
            mode = "bootstrap-musiq-proxy"
            disclaimer = (
                "DISCLAIMER: KonIQ-10k images/scores not present under "
                f"{KONIQ_DIR.relative_to(ROOT)}. Trained classical→MUSIQ "
                "proxy from iqa-comparison-mps.json — NOT true KonIQ pretrain. "
                "Register at https://database.mmsp-kn.de/koniq-10k-database.html "
                "and unpack to evals/external/data/koniq10k/ for real MOS targets."
            )
            n_resolved = len(xs)

    weights = ridge_fit(xs, ys, alpha=args.alpha)
    metrics = train_eval(xs, ys, weights)

    payload = {
        "experiment": "ML-E17",
        "licence": "MIT",
        "target": "koniq_mos",
        "target_note": (
            "KonIQ-10k MOS (research download) — distilled linear head on "
            "classical PIL features (KonCept512-style spike simplified)"
        ),
        "features": FEATURE_NAMES,
        "weights": [round(w, 6) for w in weights],
        "training": {
            "fixture": str(args.fixture.relative_to(ROOT)),
            "koniq_dir": str(KONIQ_DIR.relative_to(ROOT)),
            "mode": mode,
            "n_resolved_frames": n_resolved,
            "ridge_alpha": args.alpha,
            "max_samples": args.max_samples,
            **metrics,
        },
    }
    if disclaimer:
        payload["disclaimer"] = disclaimer
        payload["training"]["disclaimer"] = disclaimer

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    size_kb = args.output.stat().st_size / 1024
    print(json.dumps(payload["training"], indent=2))
    if disclaimer:
        print(disclaimer, file=sys.stderr)
    print(f"wrote {args.output} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
