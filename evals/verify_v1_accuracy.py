#!/usr/bin/env python3
"""Verify v1 accuracy targets against committed benchmark runs.

Targets (docs/00, docs/10):
    notable recall >= 90%
    hallucination <= 5%
    defect recall >= 75%

The Phase 3 gate expects a native-resolution InventoryFlex fixture
(``benchmarks/inventoryflex-nativeres/capture/``). When that fixture is
absent, this script re-scores the best available downscaled runs and reports
honest gaps — it does not invent metrics.

Usage:
    python evals/verify_v1_accuracy.py
    python evals/verify_v1_accuracy.py --json
    python evals/verify_v1_accuracy.py --require-native-res   # fail if no native fixture
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402
from homeinventory.schema import Inventory  # noqa: E402

V1_TARGETS = {
    "item_recall_notable": 90.0,
    "hallucination_rate": 5.0,
    "defect_recall": 75.0,
}

GATE_METRICS = ("item_recall_notable", "hallucination_rate", "defect_recall")

FIXTURES: list[tuple[str, Path, str]] = [
    (
        "inventoryflex-downscaled",
        ROOT / "benchmarks" / "inventoryflex" / "capture",
        "800x600 PDF extraction (192 photos, 6 rooms)",
    ),
    (
        "inventoryflex-nativeres",
        ROOT / "benchmarks" / "inventoryflex-nativeres" / "capture",
        "native phone resolution (Phase 3 gate fixture)",
    ),
    (
        "weststand-downscaled",
        ROOT / "benchmarks" / "eoin" / "capture",
        "450x600 PDF extraction (257 photos, 6 rooms)",
    ),
]

BENCHMARKS: list[tuple[str, Path, Path, str]] = [
    (
        "inventoryflex/claude-v4",
        ROOT / "benchmarks" / "inventoryflex" / "report-claude-v4" / "inventory.json",
        ROOT / "evals" / "fixtures" / "inventoryflex" / "labels.json",
        "downscaled",
    ),
    (
        "inventoryflex/gpt54mini-v4",
        ROOT / "benchmarks" / "inventoryflex" / "report-gpt54mini-v4" / "inventory.json",
        ROOT / "evals" / "fixtures" / "inventoryflex" / "labels.json",
        "downscaled",
    ),
    (
        "inventoryflex/gemini35flash",
        ROOT / "benchmarks" / "inventoryflex" / "report-gemini35flash" / "inventory.json",
        ROOT / "evals" / "fixtures" / "inventoryflex" / "labels.json",
        "downscaled",
    ),
    (
        "weststand/eoin-claude-v4",
        ROOT / "benchmarks" / "eoin" / "report-claude-v4" / "inventory.json",
        ROOT / "evals" / "fixtures" / "weststand" / "labels.json",
        "downscaled",
    ),
]


@dataclass
class FixtureStatus:
    name: str
    path: Path
    description: str
    present: bool
    image_count: int
    resolutions: dict[str, int]


@dataclass
class RunScore:
    name: str
    fixture_class: str
    metrics: dict[str, float | None]
    passes: dict[str, bool]
    passes_all: bool
    missing: bool = False


def _image_resolutions(capture_dir: Path, sample_limit: int = 200) -> tuple[int, dict[str, int]]:
    exts = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.heic")
    images: list[Path] = []
    for ext in exts:
        images.extend(capture_dir.rglob(ext))
    if not images:
        return 0, {}

    try:
        from PIL import Image
    except ImportError:
        return len(images), {"PIL unavailable": len(images)}

    sizes: list[str] = []
    for path in images[:sample_limit]:
        try:
            with Image.open(path) as im:
                sizes.append(f"{im.size[0]}x{im.size[1]}")
        except OSError:
            sizes.append("unreadable")
    return len(images), dict(Counter(sizes))


def inventory_fixtures() -> list[FixtureStatus]:
    out: list[FixtureStatus] = []
    for name, path, description in FIXTURES:
        if path.is_dir():
            count, resolutions = _image_resolutions(path)
            out.append(FixtureStatus(name, path, description, True, count, resolutions))
        else:
            out.append(FixtureStatus(name, path, description, False, 0, {}))
    return out


def _passes(metric: str, value: float | None) -> bool:
    if value is None:
        return False
    if metric == "hallucination_rate":
        return value <= V1_TARGETS[metric]
    return value >= V1_TARGETS[metric]


def score_run(name: str, inv_path: Path, labels_path: Path, fixture_class: str) -> RunScore:
    if not inv_path.is_file() or not labels_path.is_file():
        return RunScore(name, fixture_class, {}, {m: False for m in GATE_METRICS}, False, missing=True)

    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    inv = Inventory.from_json(inv_path.read_text(encoding="utf-8"))
    results = run_eval.evaluate(inv, labels)
    metrics = {m: results.get(m) for m in GATE_METRICS}
    passes = {m: _passes(m, metrics[m]) for m in GATE_METRICS}
    return RunScore(name, fixture_class, metrics, passes, all(passes.values()))


def score_all_runs() -> list[RunScore]:
    return [score_run(name, inv, labels, fixture_class) for name, inv, labels, fixture_class in BENCHMARKS]


def native_res_present(fixtures: list[FixtureStatus]) -> bool:
    for fx in fixtures:
        if fx.name == "inventoryflex-nativeres" and fx.present and fx.image_count > 0:
            return True
    return False


def _rank_key(run: RunScore) -> tuple:
    return (
        sum(run.passes.values()),
        run.metrics.get("defect_recall") or -1,
        run.metrics.get("item_recall_notable") or -1,
        -(run.metrics.get("hallucination_rate") or 999),
    )


def best_in_family(runs: list[RunScore], prefix: str) -> RunScore | None:
    candidates = [
        r for r in runs
        if r.fixture_class == "downscaled" and not r.missing and r.name.startswith(prefix)
    ]
    if not candidates:
        return None
    return max(candidates, key=_rank_key)


def native_res_commands() -> str:
    return """\
Native-res InventoryFlex benchmark — prerequisites and commands
---------------------------------------------------------------
Blocker: benchmarks/inventoryflex-nativeres/capture/ does not exist yet.
See docs/23 §6 and docs/22 §5.3.

1. Source native-res photos (or walkthrough) of the InventoryFlex sample property
   at full phone resolution. Keep the same 6-room set so gold labels still apply.

2. Place photos under:
       benchmarks/inventoryflex-nativeres/capture/<Room>/*.jpg

3. Build a reference run (requires API credentials in .env):
       homeinventory build benchmarks/inventoryflex-nativeres/capture \\
           -o benchmarks/inventoryflex-nativeres/report-claude-v4 \\
           --backend claude --no-detect

4. Score and gate:
       python evals/verify_v1_accuracy.py --require-native-res

5. Compare lift vs downscaled baseline:
       python evals/score_benchmarks.py
"""


def format_table(runs: list[RunScore]) -> str:
    header = f"{'run':<32} {'notable':>8} {'halluc':>8} {'defect':>8} {'v1':>6}"
    lines = [header, "-" * len(header)]
    for run in runs:
        if run.missing:
            lines.append(f"{run.name:<32} {'—':>8} {'—':>8} {'—':>8} {'MISS':>6}")
            continue
        n = run.metrics["item_recall_notable"]
        h = run.metrics["hallucination_rate"]
        d = run.metrics["defect_recall"]
        status = "PASS" if run.passes_all else "FAIL"
        lines.append(
            f"{run.name:<32} {n:8.1f} {h:8.1f} {d:8.1f} {status:>6}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit JSON summary")
    ap.add_argument(
        "--require-native-res",
        action="store_true",
        help="exit 2 when native-res fixture is absent",
    )
    args = ap.parse_args()

    fixtures = inventory_fixtures()
    runs = score_all_runs()
    has_native = native_res_present(fixtures)
    best_if = best_in_family(runs, "inventoryflex/")
    best_ws = best_in_family(runs, "weststand/")

    payload = {
        "targets": V1_TARGETS,
        "native_res_fixture_present": has_native,
        "fixtures": [
            {
                "name": fx.name,
                "path": str(fx.path.relative_to(ROOT)),
                "present": fx.present,
                "image_count": fx.image_count,
                "resolutions": fx.resolutions,
                "description": fx.description,
            }
            for fx in fixtures
        ],
        "runs": [
            {
                "name": r.name,
                "fixture_class": r.fixture_class,
                "missing": r.missing,
                "metrics": r.metrics,
                "passes": r.passes,
                "passes_all": r.passes_all,
            }
            for r in runs
        ],
        "best_inventoryflex_downscaled": None if best_if is None else {
            "name": best_if.name,
            "metrics": best_if.metrics,
            "passes": best_if.passes,
            "passes_all": best_if.passes_all,
        },
        "best_weststand_downscaled": None if best_ws is None else {
            "name": best_ws.name,
            "metrics": best_ws.metrics,
            "passes": best_ws.passes,
            "passes_all": best_ws.passes_all,
        },
        "v1_gate_pass": has_native and any(r.passes_all for r in runs if "nativeres" in r.name),
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("v1 accuracy verification (docs/00, docs/10)")
        print(f"Targets: notable >= {V1_TARGETS['item_recall_notable']:.0f}%, "
              f"hallucination <= {V1_TARGETS['hallucination_rate']:.0f}%, "
              f"defect >= {V1_TARGETS['defect_recall']:.0f}%")
        print()
        print("Fixtures:")
        for fx in fixtures:
            status = "present" if fx.present and fx.image_count else "ABSENT"
            res = ", ".join(f"{k} ({v})" for k, v in sorted(fx.resolutions.items())) or "—"
            print(f"  [{status}] {fx.name}: {fx.path.relative_to(ROOT)}")
            print(f"           {fx.description}")
            if fx.present:
                print(f"           {fx.image_count} images; resolutions: {res}")
        print()
        print(format_table(runs))
        print()
        for label, best in (
            ("Best InventoryFlex downscaled", best_if),
            ("Best Weststand downscaled", best_ws),
        ):
            if best and not best.missing:
                gaps = []
                for m in GATE_METRICS:
                    v = best.metrics[m]
                    t = V1_TARGETS[m]
                    if v is None:
                        gaps.append(f"{m}: no score")
                    elif m == "hallucination_rate" and v > t:
                        gaps.append(f"{m}: {v:.1f}% (need <= {t:.0f}%, gap +{v - t:.1f} pp)")
                    elif m != "hallucination_rate" and v < t:
                        gaps.append(f"{m}: {v:.1f}% (need >= {t:.0f}%, gap -{t - v:.1f} pp)")
                print(f"{label}: {best.name} — {'PASS' if best.passes_all else 'FAIL'}")
                if gaps:
                    for g in gaps:
                        print(f"  - {g}")
                print()
        if not has_native:
            print()
            print(native_res_commands())

    if args.require_native_res and not has_native:
        return 2

    # Phase 3 gate: pass only when a native-res run meets all three targets.
    if has_native and any(r.passes_all for r in runs):
        return 0

    # No native-res fixture yet — report downscaled status but do not claim v1 pass.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
