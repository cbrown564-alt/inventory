#!/usr/bin/env python3
"""ML-E14: Siamese embedding distance on check-in/out pairs (docs/19 §1.6).

**Blocker:** no paired check-in/check-out fixture in repo. ``--demo`` uses
InventoryFlex same-room photos as pseudo-pairs (exploratory only — not
visit-aligned before/after crops).

Outputs ``evals/fixtures/own-property/siamese-compare-demo.json``.

Usage:
    uv run python evals/eval_siamese_compare.py --demo
    uv run python evals/eval_siamese_compare.py --demo --encoder openclip
    uv run python evals/eval_siamese_compare.py PAIRED_FIXTURE.json -o out.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeinventory.ingest import ingest  # noqa: E402

DEFAULT_CAPTURE = ROOT / "benchmarks/inventoryflex/capture"
DEFAULT_OUT = ROOT / "evals/fixtures/own-property/siamese-compare-demo.json"
BBOX_FALLBACK = ROOT / "evals/fixtures/inventoryflex/bbox-review/full"


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve_capture_dir(capture_dir: Path | None) -> Path:
    if capture_dir and capture_dir.is_dir():
        return capture_dir.resolve()
    if DEFAULT_CAPTURE.is_dir():
        return DEFAULT_CAPTURE.resolve()
    if BBOX_FALLBACK.is_dir():
        return BBOX_FALLBACK.resolve()
    raise SystemExit(
        "error: no capture photos found\n"
        "run: python benchmarks/extract_inventoryflex.py"
    )


def build_pseudo_pairs(
        rooms_photos: dict,
        *,
        max_same_room: int = 4,
        max_cross_room: int = 12,
        seed: int = 14,
) -> list[dict]:
    """Pseudo-pairs from same-room and cross-room InventoryFlex photos."""
    rng = random.Random(seed)
    pairs: list[dict] = []

    for room, photos in sorted(rooms_photos.items()):
        if len(photos) < 2:
            continue
        paths = [Path(p.path) for p in photos]
        for i in range(min(max_same_room, len(paths) - 1)):
            a, b = paths[i], paths[i + 1]
            pairs.append({
                "kind": "same_room_adjacent",
                "room": room,
                "path_a": str(a),
                "path_b": str(b),
                "expected": "low_distance",
                "label": "no_change_pseudo",
            })
        if len(paths) >= 3:
            pairs.append({
                "kind": "same_room_span",
                "room": room,
                "path_a": str(paths[0]),
                "path_b": str(paths[-1]),
                "expected": "low_distance",
                "label": "no_change_pseudo",
            })

    room_names = sorted(rooms_photos.keys())
    attempts = 0
    while len([p for p in pairs if p["kind"] == "cross_room"]) < max_cross_room \
            and attempts < max_cross_room * 4:
        attempts += 1
        r1, r2 = rng.sample(room_names, 2)
        p1 = rng.choice(rooms_photos[r1])
        p2 = rng.choice(rooms_photos[r2])
        pairs.append({
            "kind": "cross_room",
            "room_a": r1,
            "room_b": r2,
            "path_a": str(Path(p1.path)),
            "path_b": str(Path(p2.path)),
            "expected": "high_distance",
            "label": "different_scene_pseudo",
        })

    return pairs


def synthetic_distance(path_a: Path, path_b: Path, kind: str) -> float:
    """Hash-based cosine distance for --no-torch demo."""
    import hashlib

    def _h(p: Path) -> int:
        return int(hashlib.sha256(str(p).encode()).hexdigest()[:8], 16)

    base = abs(_h(path_a) - _h(path_b)) / 0xFFFFFFFF
    if kind.startswith("same_room"):
        return round(0.05 + 0.25 * base, 4)
    return round(0.25 + 0.55 * base, 4)


def score_pairs(
        pairs: list[dict],
        *,
        capture_dir: Path,
        encoder: str,
        device: str,
        no_torch: bool,
) -> list[dict]:
    cache: dict[str, object] = {}
    scored: list[dict] = []
    embedder = None
    if not no_torch:
        from evals.ml_scorers import FrameEmbedder

        embedder = FrameEmbedder(backend=encoder, device=device)

    def _resolve(rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else capture_dir / p

    def _vec(path: Path):
        key = str(path.resolve())
        if key not in cache:
            with path.open("rb") as fh:
                cache[key] = embedder.embed_jpeg(fh.read())
        return cache[key]

    for pair in pairs:
        pa = _resolve(pair["path_a"])
        pb = _resolve(pair["path_b"])
        row = dict(pair)
        if no_torch:
            dist = synthetic_distance(pa, pb, pair["kind"])
            row["cosine_distance"] = dist
            row["synthetic"] = True
        else:
            from evals.ml_scorers import cosine_distance

            row["cosine_distance"] = round(cosine_distance(_vec(pa), _vec(pb)), 4)
        scored.append(row)
    return scored


def summarize_pairs(scored: list[dict]) -> dict:
    same = [p["cosine_distance"] for p in scored if p["kind"].startswith("same_room")]
    cross = [p["cosine_distance"] for p in scored if p["kind"] == "cross_room"]
    out: dict = {
        "n_pairs": len(scored),
        "n_same_room": len(same),
        "n_cross_room": len(cross),
    }
    if same:
        out["mean_distance_same_room"] = round(sum(same) / len(same), 4)
        out["max_distance_same_room"] = round(max(same), 4)
    if cross:
        out["mean_distance_cross_room"] = round(sum(cross) / len(cross), 4)
        out["min_distance_cross_room"] = round(min(cross), 4)
    if same and cross:
        out["same_below_cross_mean"] = (
            out["mean_distance_same_room"] < out["mean_distance_cross_room"]
        )
    return out


def load_paired_fixture(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = data.get("pairs") or data.get("items") or []
    if not pairs:
        raise SystemExit(f"error: no pairs in fixture: {path}")
    return pairs


def run(args: argparse.Namespace) -> dict:
    blocked = True
    paired_fixture = getattr(args, "paired_fixture", None)

    if paired_fixture and Path(paired_fixture).is_file():
        pairs = load_paired_fixture(Path(paired_fixture))
        capture_dir = resolve_capture_dir(args.capture_dir)
        blocked = False
        mode = "paired_fixture"
    else:
        capture_dir = resolve_capture_dir(args.capture_dir)
        work = capture_dir / ".eval-siamese-work"
        rooms_photos = ingest(capture_dir, work)
        pairs = build_pseudo_pairs(
            rooms_photos,
            max_same_room=args.max_same_room,
            max_cross_room=args.max_cross_room,
        )
        mode = "pseudo_pairs_inventoryflex"

    scored = score_pairs(
        pairs,
        capture_dir=capture_dir,
        encoder=args.encoder,
        device=args.device,
        no_torch=args.no_torch,
    )
    summary = summarize_pairs(scored)

    payload = {
        "experiment": "ML-E14",
        "date": date.today().isoformat(),
        "blocked": blocked,
        "blocker": (
            "No paired check-in/check-out fixture — pseudo-pairs from InventoryFlex "
            "same-room photos are exploratory only (docs/19 §1.6, §2.3)."
            if blocked else None
        ),
        "mode": mode,
        "capture_dir": _rel(capture_dir),
        "encoder": args.encoder if not args.no_torch else "synthetic",
        "device": args.device,
        "pass_bar": None,
        "pass": None,
        "note": (
            "Exploratory embedding distances only; cannot validate wear/damage "
            "change detection without visit-aligned item crops."
        ),
        "metrics": summary,
        "pairs": scored[: args.max_pairs_in_output],
        "recommendation": (
            "blocked — capture a paired check-in/out property fixture before "
            "investing in Siamese or change-detection networks (docs/19 ML-E14)."
            if blocked else "paired fixture available — label 20 item pairs with human change flags"
        ),
    }
    if args.demo:
        payload["demo"] = True

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paired_fixture", nargs="?", default=None,
                    help="optional paired check-in/out JSON (unblocks experiment)")
    ap.add_argument("--capture-dir", type=Path, default=None,
                    help="photo root (default: benchmarks/inventoryflex/capture)")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--demo", action="store_true",
                    help="pseudo-pairs from InventoryFlex (default path)")
    ap.add_argument("--encoder", choices=["openclip", "dinov2"], default="openclip",
                    help="Apache-2.0 image encoder")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-torch", action="store_true",
                    help="synthetic distances (CI-friendly)")
    ap.add_argument("--max-same-room", type=int, default=4)
    ap.add_argument("--max-cross-room", type=int, default=12)
    ap.add_argument("--max-pairs-in-output", type=int, default=40)
    args = ap.parse_args()

    if not args.demo and not args.paired_fixture:
        args.demo = True

    payload = run(args)
    print(json.dumps({k: v for k, v in payload.items() if k != "pairs"}, indent=2))
    print(f"wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
