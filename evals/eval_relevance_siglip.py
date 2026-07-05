#!/usr/bin/env python3
"""ML-E4: SigLIP/OpenCLIP relevance margin vs hero-gold (docs/19).

Scores every video frame with an Apache-2.0 encoder margin:
"wide interior establishing shot" vs "object close-up". Benchmarks Spearman
ρ against evals/fixtures/own-property/hero-gold.json.

Pass bar: mean Spearman ρ ≥ E5 classical baseline (~0.66 from
iqa-comparison-mps.json).

Output: evals/fixtures/own-property/hero-contact-siglip.html

Usage:
    uv run python evals/eval_relevance_siglip.py report \\
        --gold evals/fixtures/own-property/hero-gold.json
    uv run python evals/eval_relevance_siglip.py report \\
        --relevance-backend openclip --device cuda

Requires (optional, gated): torch, transformers, open-clip-torch
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "evals/fixtures/own-property/hero-gold.json"
DEFAULT_OUT = ROOT / "evals/fixtures/own-property/hero-contact-siglip.html"
E5_SPEARMAN_BASELINE = 0.66


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"),
                    help="build output dir containing inventory.json")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD,
                    help="hero-gold.json for metrics")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT,
                    help="HTML contact sheet path")
    ap.add_argument("--relevance-backend", default="siglip",
                    choices=["siglip", "openclip"])
    ap.add_argument("--relevance-model", default=None,
                    help="fair-test encoder id, e.g. google/siglip-large-patch16-384 "
                         "or ViT-L-14 (docs/23); defaults are deliberately weak")
    ap.add_argument("--relevance-pretrained", default=None,
                    help="openclip pretrained tag (e.g. laion2b_s32b_b82k)")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    cmd = [
        sys.executable,
        str(ROOT / "evals/eval_hero_cover.py"),
        str(args.report_dir),
        "--scorer", "siglip",
        "--gold", str(args.gold),
        "-o", str(args.output),
        "--relevance-backend", args.relevance_backend,
        "--device", args.device,
    ]
    if args.relevance_model:
        cmd += ["--relevance-model", args.relevance_model]
    if args.relevance_pretrained:
        cmd += ["--relevance-pretrained", args.relevance_pretrained]
    print(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        return proc.returncode
    print(f"\nML-E4 pass bar: mean Spearman ρ ≥ {E5_SPEARMAN_BASELINE} (E5 baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
