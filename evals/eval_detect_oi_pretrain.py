#!/usr/bin/env python3
"""ML-E18: Open Images V7 household pretrain vs ML-E10 GDINO baseline.

Compares an OI-pretrained detector (when weights exist) against the ML-E10
Grounding DINO baseline on InventoryFlex. Does **not** download the full
561 GB Open Images corpus — see ``evals/external/README.md`` for the FiftyOne
class filter.

When OI fine-tuned weights are absent, writes ``detect-comparison-oi.json``
with ``available: false`` and a documented training recipe. Optionally runs a
**proxy** comparison: base GDINO with an expanded Open Images phrase list
(bootstrap — no OI download required).

Usage:
    python benchmarks/extract_inventoryflex.py
    python3 evals/eval_detect_oi_pretrain.py benchmarks/inventoryflex/capture \\
        evals/fixtures/inventoryflex/labels.json
    python3 evals/eval_detect_oi_pretrain.py CAPTURE LABELS.json -o \\
        evals/fixtures/inventoryflex/detect-comparison-oi.json --device cpu

Optional deps (eval only):
    pip install transformers accelerate torch
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_detect import evaluate_detector  # noqa: E402
from gdino_detect import DEFAULT_MODEL, GroundingDinoDetector  # noqa: E402
from homeinventory.ingest import ingest  # noqa: E402
from oi_detect import OiPretrainedDetector, OiProxyGroudingDinoDetector  # noqa: E402
from oi_vocab import (  # noqa: E402
    DEFAULT_OI_WEIGHTS,
    find_oi_weights,
    open_images_subset_doc,
    training_recipe,
)

DEFAULT_OUT = ROOT / "evals/fixtures/inventoryflex/detect-comparison-oi.json"
DEFAULT_BASELINE = ROOT / "evals/fixtures/inventoryflex/detect-comparison-gdino.json"


def _load_gdino_baseline(path: Path) -> dict | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for mode in payload.get("modes", []):
        if mode.get("backend") == "gdino" and mode.get("available"):
            return mode
    return None


def _recommendation(baseline: dict | None, oi: dict, proxy: dict | None) -> str:
    base_rec = baseline.get("gold_recall_notable") if baseline else None
    oi_rec = oi.get("gold_recall_notable") if oi.get("available") else None
    proxy_rec = proxy.get("gold_recall_notable") if proxy and proxy.get("available") else None

    if not oi.get("available"):
        if proxy and proxy.get("available") and base_rec is not None and proxy_rec is not None:
            delta = round(proxy_rec - base_rec, 1)
            if delta >= 3:
                return (
                    f"oi proxy bootstrap — expanded OI phrases +{delta}pp notable recall "
                    f"vs ML-E10 GDINO; worth running OI pretrain (see training_recipe)"
                )
            return (
                f"await oi pretrain — proxy phrase expansion {delta:+.1f}pp vs ML-E10; "
                "download filtered OI and fine-tune before G3 swap (docs/19 ML-E18)"
            )
        return (
            "await oi pretrain — OI weights missing; see training_recipe and "
            "evals/external/README.md FiftyOne filter (do not download 561 GB full OI)"
        )

    if base_rec is None or oi_rec is None:
        return "oi pretrain available — re-run with ML-E10 baseline for comparison"

    delta = round(oi_rec - base_rec, 1)
    oi_noise = oi.get("unmatched_label_rate") or 100
    base_noise = baseline.get("unmatched_label_rate") or 100
    if delta >= 5 and oi_noise <= base_noise + 5:
        return (
            f"oi pretrain candidate — notable recall +{delta}pp vs ML-E10 GDINO with "
            "acceptable noise; review latency before detector swap"
        )
    if delta >= 5:
        return (
            f"oi pretrain mixed — recall +{delta}pp but unmatched labels "
            f"+{round(oi_noise - base_noise, 1)}pp vs baseline; tune threshold"
        )
    return (
        f"keep gdino baseline — oi pretrain recall delta {delta:+.1f}pp "
        "(need ≥+5pp vs ML-E10 for pretrain path)"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture_dir", type=Path)
    ap.add_argument("labels_json", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--baseline-json", type=Path, default=DEFAULT_BASELINE,
                    help="ML-E10 detect-comparison-gdino.json (skip re-run)")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--model-gdino", default=DEFAULT_MODEL)
    ap.add_argument("--oi-weights", default=None, help="path to OI fine-tuned checkpoint")
    ap.add_argument("--device", default=None)
    ap.add_argument("--room", help="comma-separated room filter")
    ap.add_argument("--skip-proxy", action="store_true",
                    help="skip GDINO expanded-phrase proxy bootstrap")
    ap.add_argument("--rerun-baseline", action="store_true",
                    help="re-run ML-E10 GDINO baseline instead of loading JSON")
    args = ap.parse_args()

    if not args.capture_dir.is_dir():
        print(f"error: capture dir not found: {args.capture_dir}", file=sys.stderr)
        return 2
    if not args.labels_json.is_file():
        print(f"error: labels not found: {args.labels_json}", file=sys.stderr)
        return 2

    labels = json.loads(args.labels_json.read_text(encoding="utf-8"))
    rooms_filter = None
    if args.room:
        rooms_filter = {r.strip().lower() for r in args.room.split(",")}

    rooms_photos = ingest(args.capture_dir, args.capture_dir / ".eval-detect-oi-work")
    modes: list[dict] = []

    baseline: dict | None = None
    if args.rerun_baseline:
        print("evaluating backend=gdino baseline (ML-E10) …", flush=True)
        gdino_baseline = GroundingDinoDetector(
            conf=args.conf,
            device=args.device,
            model_id=args.model_gdino,
        )
        baseline = evaluate_detector(
            args.capture_dir,
            labels,
            gdino_baseline,
            backend="gdino",
            mode="baseline",
            model=args.model_gdino,
            match_threshold=args.threshold,
            device=args.device,
            conf=args.conf,
            rooms_filter=rooms_filter,
            rooms_photos=rooms_photos,
        )
        modes.append(baseline)
        if baseline.get("available"):
            print(f"  gold recall (notable): {baseline['gold_recall_notable']}%")
    else:
        baseline = _load_gdino_baseline(args.baseline_json)
        if baseline:
            print(f"loaded ML-E10 baseline from {args.baseline_json}", flush=True)
            print(f"  gold recall (notable): {baseline.get('gold_recall_notable')}%")
            modes.append({**baseline, "source": "evals/fixtures/inventoryflex/detect-comparison-gdino.json"})
        else:
            print(f"warning: no baseline at {args.baseline_json}; use --rerun-baseline",
                  file=sys.stderr)

    weights_path = args.oi_weights or find_oi_weights()
    oi_doc = open_images_subset_doc()
    oi_doc["weights_path"] = weights_path or DEFAULT_OI_WEIGHTS
    oi_doc["weights_present"] = bool(weights_path)

    print("evaluating backend=oi_pretrain …", flush=True)
    oi_detector = OiPretrainedDetector(
        weights_path=weights_path,
        conf=args.conf,
        device=args.device,
        model_id=args.model_gdino,
    )
    if oi_detector.available and weights_path:
        oi_result = evaluate_detector(
            args.capture_dir,
            labels,
            oi_detector,
            backend="oi_pretrain",
            mode="oi_pretrain",
            model=str(weights_path),
            match_threshold=args.threshold,
            device=args.device,
            conf=args.conf,
            rooms_filter=rooms_filter,
            rooms_photos=rooms_photos,
        )
        if oi_result.get("available"):
            print(f"  gold recall (notable): {oi_result['gold_recall_notable']}%")
    else:
        oi_result = {
            "backend": "oi_pretrain",
            "mode": "oi_pretrain",
            "model": weights_path,
            "available": False,
            "error": oi_detector._load_error,
            "training_recipe": training_recipe(weights_path or DEFAULT_OI_WEIGHTS),
        }
        print(f"  unavailable: {oi_result.get('error')}", file=sys.stderr)
    modes.append(oi_result)

    proxy_result: dict | None = None
    if not args.skip_proxy:
        print("evaluating backend=oi_proxy (GDINO expanded OI phrases) …", flush=True)
        proxy_detector = OiProxyGroudingDinoDetector(
            conf=args.conf,
            device=args.device,
            model_id=args.model_gdino,
        )
        proxy_result = evaluate_detector(
            args.capture_dir,
            labels,
            proxy_detector,
            backend="oi_proxy",
            mode="gdino_expanded_phrases",
            model=args.model_gdino,
            match_threshold=args.threshold,
            device=args.device,
            conf=args.conf,
            rooms_filter=rooms_filter,
            rooms_photos=rooms_photos,
        )
        modes.append(proxy_result)
        if proxy_result.get("available"):
            print(f"  gold recall (notable): {proxy_result['gold_recall_notable']}%  "
                  f"(proxy bootstrap — not OI fine-tune)")
        else:
            print(f"  unavailable: {proxy_result.get('error')}", file=sys.stderr)

    comparison: dict = {
        "baseline_backend": "gdino",
        "baseline_source": "ML-E10",
        "oi_weights_present": bool(weights_path),
        "recommendation": _recommendation(baseline or {}, oi_result, proxy_result),
    }
    if baseline and baseline.get("available") and oi_result.get("available"):
        comparison["gold_recall_notable_delta"] = round(
            (oi_result.get("gold_recall_notable") or 0)
            - (baseline.get("gold_recall_notable") or 0),
            1,
        )
        comparison["unmatched_label_rate_delta"] = round(
            (oi_result.get("unmatched_label_rate") or 0)
            - (baseline.get("unmatched_label_rate") or 0),
            1,
        )
    if baseline and baseline.get("available") and proxy_result and proxy_result.get("available"):
        comparison["proxy_gold_recall_notable_delta"] = round(
            (proxy_result.get("gold_recall_notable") or 0)
            - (baseline.get("gold_recall_notable") or 0),
            1,
        )
        comparison["proxy_unmatched_label_rate_delta"] = round(
            (proxy_result.get("unmatched_label_rate") or 0)
            - (baseline.get("unmatched_label_rate") or 0),
            1,
        )

    payload = {
        "experiment": "ML-E18",
        "capture_dir": str(args.capture_dir),
        "labels": str(args.labels_json),
        "baseline_json": str(args.baseline_json.relative_to(ROOT))
        if args.baseline_json.is_relative_to(ROOT)
        else str(args.baseline_json),
        "device": args.device,
        "evaluated": date.today().isoformat(),
        "open_images_household_subset": oi_doc,
        "modes": modes,
        "comparison": comparison,
        "dependency_notes": {
            "gdino": "pip install transformers accelerate torch (Apache-2.0; eval only)",
            "oi_dataset": "FiftyOne class filter — evals/external/README.md; not committed",
            "oi_weights": f"expected at {DEFAULT_OI_WEIGHTS} after fine-tune",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(f"recommendation: {comparison['recommendation']}")

    if not oi_result.get("available"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
