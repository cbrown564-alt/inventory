#!/usr/bin/env python3
"""ML-E5: multi-scale Laplacian ratio contact sheet vs hero-gold (docs/19).

Thin wrapper around eval_hero_cover with --scorer mslap defaults.
Pass bar: top-3 hit rate ≥ E5 (100% on IMG_5512 gold per docs/18).

Output: evals/fixtures/own-property/hero-contact-mslap.html

Usage:
    uv run python evals/eval_mslap_cover.py report \\
        --gold evals/fixtures/own-property/hero-gold.json
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "evals/fixtures/own-property/hero-gold.json"
DEFAULT_OUT = ROOT / "evals/fixtures/own-property/hero-contact-mslap.html"
E5_TOP3_BASELINE = 100.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report_dir", type=Path, nargs="?", default=Path("report"),
                    help="build output dir containing inventory.json")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD,
                    help="hero-gold.json for metrics")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT,
                    help="HTML contact sheet path")
    args = ap.parse_args()

    cmd = [
        sys.executable,
        str(ROOT / "evals/eval_hero_cover.py"),
        str(args.report_dir),
        "--scorer", "mslap",
        "--gold", str(args.gold),
        "-o", str(args.output),
    ]
    print(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        return proc.returncode
    print(f"\nML-E5 pass bar: top-3 hit rate ≥ {E5_TOP3_BASELINE}% (E5 baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
