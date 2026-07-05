#!/usr/bin/env python3
"""Compare YOLOE text-prompt vs prompt-free detection on labelled fixtures.

Scores how well each detection mode finds gold inventory items (recall) and
how noisy its label set is (unmatched detections). This is a *detector* eval —
it does not run the describe backend.

Usage:
    python evals/eval_detect.py CAPTURE_DIR LABELS.json
    python evals/eval_detect.py CAPTURE_DIR LABELS.json --modes text prompt_free
    python evals/eval_detect.py CAPTURE_DIR LABELS.json -o results.json

Example (InventoryFlex benchmark — extract photos first):
    python benchmarks/extract_inventoryflex.py
    python evals/eval_detect.py benchmarks/inventoryflex/capture \\
        evals/fixtures/inventoryflex/labels.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402
from homeinventory.coverage import coverage_gaps, expected_for  # noqa: E402
from homeinventory.detect import (  # noqa: E402
    HOUSEHOLD_VOCAB,
    DetectMode,
    Detector,
    default_model,
)
from homeinventory.ingest import ingest  # noqa: E402


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def label_matches_gold(label: str, gold: dict, threshold: float) -> bool:
    from homeinventory.det_match import label_matches_gold as _match
    return _match(label, gold, threshold)


def gold_matches_any_label(gold: dict, labels: set[str], threshold: float) -> bool:
    return any(label_matches_gold(lb, gold, threshold) for lb in labels)


def label_matches_any_gold(label: str, gold_items: list[dict],
                           threshold: float) -> bool:
    return any(label_matches_gold(label, g, threshold) for g in gold_items)


def collect_room_labels(capture_dir: Path, room_name: str, photos: list,
                        detector) -> tuple[set[str], int]:
    """Run detector on every photo in a room; return unique labels + det count."""
    seen: set[str] = set()
    total = 0
    for p in photos:
        full = Path(p.path)
        if not full.is_absolute():
            full = capture_dir / p.path
        for det in detector.detect(full):
            seen.add(det.label)
            total += 1
    return seen, total


def evaluate_detector(
        capture_dir: Path,
        labels: dict,
        detector,
        *,
        backend: str,
        mode: str = "text",
        model: str | None = None,
        match_threshold: float = 0.6,
        device: str | None = None,
        conf: float = 0.25,
        rooms_filter: set[str] | None = None,
        rooms_photos: dict | None = None,
) -> dict:
    """Score one detector backend against gold labels."""
    if rooms_photos is None:
        rooms_photos = ingest(capture_dir, capture_dir / ".eval-detect-work")
    if not detector.available:
        return {
            "backend": backend,
            "mode": mode,
            "model": model,
            "available": False,
            "error": getattr(detector, "_load_error", None),
        }

    stats = {
        "gold_items": 0,
        "gold_notable": 0,
        "found": 0,
        "found_notable": 0,
        "detections": 0,
        "unique_labels": 0,
        "unmatched_labels": 0,
        "coverage_gaps": 0,
        "coverage_checks": 0,
        "vocab_hits": 0,
    }
    per_room: dict[str, dict] = {}
    all_labels: Counter[str] = Counter()
    all_unmatched: Counter[str] = Counter()
    gold_rooms = labels["rooms"]

    for room_name, gold_room in gold_rooms.items():
        if rooms_filter and room_name.lower() not in rooms_filter:
            continue
        # Match ingest room names case-insensitively
        photos = None
        for ingest_name, ingest_photos in rooms_photos.items():
            if ingest_name.lower() == room_name.lower():
                photos = ingest_photos
                room_key = ingest_name
                break
        if photos is None:
            per_room[room_name] = {"error": "no photos for room in capture dir"}
            continue

        seen, det_count = collect_room_labels(capture_dir, room_name, photos, detector)
        stats["detections"] += det_count
        all_labels.update(seen)
        gold_items = gold_room["items"]
        room_found = 0
        room_found_notable = 0
        room_gold = 0
        room_notable = 0
        unmatched = [lb for lb in seen
                     if not label_matches_any_gold(lb, gold_items, match_threshold)]

        for gold in gold_items:
            stats["gold_items"] += 1
            room_gold += 1
            notable = gold.get("notable", True)
            if notable:
                stats["gold_notable"] += 1
                room_notable += 1
            if gold_matches_any_label(gold, seen, match_threshold):
                stats["found"] += 1
                room_found += 1
                if notable:
                    stats["found_notable"] += 1
                    room_found_notable += 1

        stats["unmatched_labels"] += len(unmatched)
        for lb in unmatched:
            all_unmatched[lb] += 1
        gaps = coverage_gaps(seen, room_name)
        stats["coverage_gaps"] += len(gaps)
        stats["coverage_checks"] += len(expected_for(room_name))

        per_room[room_name] = {
            "photos": len(photos),
            "detections": det_count,
            "unique_labels": len(seen),
            "labels": sorted(seen),
            "unmatched_labels": unmatched,
            "gold_recall": _pct(room_found, room_gold),
            "gold_recall_notable": _pct(room_found_notable, room_notable),
            "coverage_gaps": gaps,
        }

    stats["unique_labels"] = len(all_labels)
    stats["unique_unmatched"] = len(all_unmatched)
    if mode == "text":
        stats["vocab_hits"] = sum(1 for v in HOUSEHOLD_VOCAB if v in all_labels)

    return {
        "backend": backend,
        "mode": mode,
        "model": model,
        "device": device,
        "conf": conf,
        "available": True,
        "gold_recall_all": _pct(stats["found"], stats["gold_items"]),
        "gold_recall_notable": _pct(stats["found_notable"], stats["gold_notable"]),
        "unmatched_label_rate": _pct(stats["unique_unmatched"], stats["unique_labels"]),
        "detections_per_photo": round(
            stats["detections"] / max(1, sum(r.get("photos", 0) for r in per_room.values())),
            2,
        ),
        "coverage_gap_rate": _pct(stats["coverage_gaps"], stats["coverage_checks"]),
        "vocab_coverage": _pct(stats["vocab_hits"], len(HOUSEHOLD_VOCAB)) if mode == "text" else None,
        "top_unmatched_labels": _top_unmatched(per_room),
        "rooms": per_room,
        "_counts": stats,
    }


def evaluate_mode(capture_dir: Path, labels: dict, mode: DetectMode,
                  *, match_threshold: float = 0.6, conf: float = 0.25,
                  model: str | None = None, device: str | None = None,
                  rooms_filter: set[str] | None = None) -> dict:
    """Score one YOLOE detection mode against gold labels."""
    detector = Detector(
        model_name=model or default_model(mode),
        mode=mode,
        conf=conf,
        device=device,
    )
    return evaluate_detector(
        capture_dir,
        labels,
        detector,
        backend="yoloe",
        mode=mode,
        model=model or default_model(mode),
        match_threshold=match_threshold,
        device=device,
        conf=conf,
        rooms_filter=rooms_filter,
    )


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def _top_unmatched(per_room: dict, limit: int = 15) -> list[dict]:
    counts: Counter[str] = Counter()
    for room in per_room.values():
        for lb in room.get("unmatched_labels", []):
            counts[lb] += 1
    return [{"label": lb, "rooms": n} for lb, n in counts.most_common(limit)]


def compare_modes(results: list[dict]) -> dict:
    """Side-by-side delta when exactly two modes ran successfully."""
    ok = [r for r in results if r.get("available")]
    if len(ok) != 2:
        return {}
    a, b = ok[0], ok[1]

    def delta(metric: str) -> float | None:
        va, vb = a.get(metric), b.get(metric)
        if va is None or vb is None:
            return None
        return round(vb - va, 1)

    return {
        "modes": [a["mode"], b["mode"]],
        "gold_recall_notable_delta": delta("gold_recall_notable"),
        "gold_recall_all_delta": delta("gold_recall_all"),
        "unmatched_label_rate_delta": delta("unmatched_label_rate"),
        "coverage_gap_rate_delta": delta("coverage_gap_rate"),
        "recommendation": _recommend(a, b),
    }


def _recommend(a: dict, b: dict) -> str:
    """Heuristic pick for inventory pipeline default."""
    a_notable = a.get("gold_recall_notable") or 0
    b_notable = b.get("gold_recall_notable") or 0
    a_cov = a.get("coverage_gap_rate") or 0
    b_cov = b.get("coverage_gap_rate") or 0
    a_noise = a.get("unmatched_label_rate") or 100
    b_noise = b.get("unmatched_label_rate") or 100

    better = b if b_notable >= a_notable else a
    worse = a if better is b else b
    recall_gain = abs(b_notable - a_notable)
    cov_penalty = abs(b_cov - a_cov)

    if better["mode"] == "prompt_free" and recall_gain >= 5:
        if cov_penalty >= 10:
            return (
                f"text (default) — prompt_free recall +{recall_gain:.1f}pp on this "
                f"fixture but coverage gaps +{cov_penalty:.1f}pp (LVIS names miss "
                "checklist terms like smoke alarm / towel rail); keep household "
                "vocabulary for build/check, re-run eval_detect after capture"
            )
        return f"prompt_free — notable recall +{recall_gain:.1f}pp with acceptable coverage"

    if a["mode"] == "text" and a_notable >= b_notable - 5 and a_noise <= b_noise:
        return "text — household vocabulary matches or beats prompt_free with less label noise"
    if recall_gain >= 5 and cov_penalty < 10:
        return f"{better['mode']} — higher notable recall on this fixture"
    return "text — tuned household vocabulary remains the default for build/check"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture_dir", type=Path)
    ap.add_argument("labels_json", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="write JSON results here")
    ap.add_argument("--modes", nargs="+", default=["text", "prompt_free"],
                    choices=["text", "prompt_free"],
                    help="detection modes to compare (default: both)")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="fuzzy name-match threshold for gold items")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--model-text", default=None, help="override text-prompt weights")
    ap.add_argument("--model-pf", default=None, help="override prompt-free weights")
    ap.add_argument("--device", default=None,
                    help="torch device for inference (e.g. cpu, cuda, 0)")
    ap.add_argument("--room", help="comma-separated room filter")
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

    results = []
    for mode in args.modes:
        print(f"evaluating mode={mode} …", flush=True)
        model = args.model_text if mode == "text" else args.model_pf
        r = evaluate_mode(
            args.capture_dir, labels, mode,  # type: ignore[arg-type]
            match_threshold=args.threshold,
            conf=args.conf,
            model=model,
            device=args.device,
            rooms_filter=rooms_filter,
        )
        results.append(r)
        if not r.get("available"):
            print(f"  unavailable: {r.get('error')}", file=sys.stderr)
        else:
            print(f"  gold recall (notable): {r['gold_recall_notable']}%  "
                  f"unmatched labels: {r['unmatched_label_rate']}%  "
                  f"coverage gaps: {r['coverage_gap_rate']}%")

    payload = {
        "capture_dir": str(args.capture_dir),
        "labels": str(args.labels_json),
        "modes": results,
        "comparison": compare_modes(results),
    }
    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"\nwrote {args.out}")
    else:
        print("\n" + text)
    if any(not r.get("available") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
