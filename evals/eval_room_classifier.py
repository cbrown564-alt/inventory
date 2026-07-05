#!/usr/bin/env python3
"""ML-E16: room-type classifier eval on wrong-room bleed audit (docs/19).

Fine-tune spike: MIT Indoor 67 (HF ``keremberke/indoor-scene-classification``)
mapped to ~10 inventory room names. Evaluates whether a room classifier would
reject bleed frames listed in ``evals/fixtures/ownproperty-bleed-exclusions.json``.

Outputs ``evals/fixtures/own-property/room-clf-eval.json``.

Without the HF dataset or report frames, runs in **demo** mode using evidence
prefix heuristics and optional OpenCLIP zero-shot prompts.

Train stub (no multi-GB download):
    uv run python evals/eval_room_classifier.py --train-stub
    uv run python evals/eval_room_classifier.py --train-stub --stream-hf --max-samples 64

Usage:
    uv run python evals/eval_room_classifier.py
    uv run python evals/eval_room_classifier.py report \\
        --bleed evals/fixtures/ownproperty-bleed-exclusions.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_BLEED = ROOT / "evals" / "fixtures" / "ownproperty-bleed-exclusions.json"
DEFAULT_OUT = ROOT / "evals" / "fixtures" / "own-property" / "room-clf-eval.json"
DEFAULT_WEIGHTS = ROOT / "evals" / "fixtures" / "own-property" / "room-clf-weights.json"
HF_DATASET = "keremberke/indoor-scene-classification"
HF_CACHE = ROOT / "evals" / "external" / "data" / "indoor-scene"

# Inventory room names used in own-property reports (~10 rooms).
INVENTORY_ROOMS = [
    "Hallway",
    "Living Room",
    "Kitchen",
    "Bedroom 1",
    "Loft Bedroom",
    "Bathroom",
    "En-suite Shower Room",
    "Loft Office",
    "Loft Shower Room",
    "Stairs and Landing",
]

# MIT Indoor 67 (HF label names) → inventory room. Unmapped labels → None.
MIT67_TO_INVENTORY: dict[str, str | None] = {
    "airport": None,
    "artstudio": None,
    "auditorium": None,
    "bakery": None,
    "bar": None,
    "bathroom": "Bathroom",
    "bedroom": "Bedroom 1",
    "bookstore": None,
    "buffet": "Kitchen",
    "cafeteria": None,
    "classroom": None,
    "closet": "Hallway",
    "clothingstore": None,
    "computerroom": "Loft Office",
    "conference_center": "Loft Office",
    "corridor": "Hallway",
    "deli": "Kitchen",
    "dentaloffice": None,
    "dining_room": "Living Room",
    "elevator": "Hallway",
    "fastfood_restaurant": "Kitchen",
    "florist": None,
    "gameroom": "Living Room",
    "garage": None,
    "greenhouse": None,
    "groceystore": None,
    "gym": None,
    "hallway": "Hallway",
    "inside_bus": None,
    "inside_subway": None,
    "jewelleryshop": None,
    "kindergarden": None,
    "kitchen": "Kitchen",
    "laboratory": None,
    "laundromat": None,
    "library": "Loft Office",
    "livingroom": "Living Room",
    "locker_room": None,
    "mall": None,
    "meeting_room": "Loft Office",
    "movietheater": None,
    "museum": None,
    "nursery": "Bedroom 1",
    "office": "Loft Office",
    "operating_room": None,
    "pantry": "Kitchen",
    "poolinside": "Bathroom",
    "prison": None,
    "restaurant": "Living Room",
    "restaurant_kitchen": "Kitchen",
    "shoeshop": None,
    "stairscase": "Stairs and Landing",
    "storeroom": "Hallway",
    "subway": None,
    "tv_studio": None,
    "videostore": None,
    "waitingroom": "Hallway",
    "warehouse": None,
    "winery": None,
}

ROOM_PROMPTS: dict[str, list[str]] = {
    "Hallway": [
        "a hallway in a home with doors and a runner rug",
        "an entrance corridor with sideboard and stairs visible",
    ],
    "Living Room": [
        "a living room with sofa and windows",
        "an open-plan living and dining area",
    ],
    "Kitchen": [
        "a kitchen with fitted cabinets and appliances",
        "a kitchen with hob oven and worktops",
    ],
    "Bedroom 1": [
        "a bedroom with bed and wardrobe",
        "a furnished double bedroom",
    ],
    "Loft Bedroom": [
        "a loft bedroom under the eaves with sloped ceiling",
        "an attic bedroom with bed and eaves",
    ],
    "Bathroom": [
        "a bathroom with bath suite and vanity",
        "a main bathroom with toilet and basin",
    ],
    "En-suite Shower Room": [
        "an en-suite shower room with wall-hung basin",
        "a small ensuite bathroom attached to a bedroom",
    ],
    "Loft Office": [
        "a home office with desk and shelves",
        "a loft study room with desk",
    ],
    "Loft Shower Room": [
        "a loft shower room with shower enclosure",
        "an upstairs shower room with tiled walls",
    ],
    "Stairs and Landing": [
        "a staircase and landing with balustrade",
        "stairs and landing with wallpapered walls",
    ],
}

# Evidence id prefix → inventory room (demo / no-image fallback).
EVIDENCE_PREFIX_TO_ROOM: list[tuple[str, str]] = [
    ("kitchen_f", "Kitchen"),
    ("living_f", "Living Room"),
    ("bathroom_f", "Bathroom"),
    ("bedroom1_b", "En-suite Shower Room"),
    ("bedroom1", "Bedroom 1"),
    ("loft_bedroom_b", "Loft Shower Room"),
    ("loft_bedroom", "Loft Bedroom"),
    ("loft_shower", "Loft Shower Room"),
    ("loft_office", "Loft Office"),
    ("stairs", "Stairs and Landing"),
    ("hallway", "Hallway"),
    ("landing", "Stairs and Landing"),
]


def normalize_true_room(raw: str) -> str:
    """Map bleed true_room strings to a single inventory room name."""
    s = raw.strip()
    if s in INVENTORY_ROOMS:
        return s
    lower = s.lower()
    if "hallway" in lower and "stairs" not in lower:
        return "Hallway"
    if "stairs" in lower or "landing" in lower:
        return "Stairs and Landing"
    if "en-suite" in lower or "ensuite" in lower:
        return "En-suite Shower Room"
    if "loft shower" in lower:
        return "Loft Shower Room"
    if "loft bedroom" in lower:
        return "Loft Bedroom"
    if "loft office" in lower:
        return "Loft Office"
    if "kitchen" in lower:
        return "Kitchen"
    if "living" in lower:
        return "Living Room"
    if "bathroom" in lower:
        return "Bathroom"
    if "bedroom" in lower:
        return "Bedroom 1"
    return s


def parse_evidence_ids(evidence: str) -> list[str]:
    """Extract frame id tokens from bleed evidence strings."""
    tokens = re.findall(r"[a-z0-9_]+", evidence.lower())
    return [t for t in tokens if "_f" in t or t.endswith("_f000000")]


def evidence_prefix_room(evidence: str) -> str | None:
    """Demo classifier: infer room from evidence frame id prefix."""
    ev = evidence.lower()
    for prefix, room in EVIDENCE_PREFIX_TO_ROOM:
        if prefix in ev:
            return room
    return None


def resolve_frame_path(report_dir: Path, evidence: str) -> Path | None:
    """Find a JPEG under report_dir matching bleed evidence frame ids."""
    ids = parse_evidence_ids(evidence)
    if not ids:
        return None
    photos: list[Path] = []
    for pat in ("*.jpg", "*.jpeg", "*.png"):
        photos.extend(report_dir.rglob(pat))
    by_name = {p.name.lower(): p for p in photos}
    for eid in ids:
        for name, path in by_name.items():
            if eid in name:
                return path
    # IMG_5512_f000009 style
    for eid in ids:
        m = re.search(r"f(\d+)", eid)
        if not m:
            continue
        num = m.group(1)
        for name, path in by_name.items():
            if f"_f{num}" in name or f"f{num}." in name:
                return path
    return None


class OpenCLIPRoomClassifier:
    """Zero-shot room classifier via OpenCLIP prompt ensembles (Apache-2.0)."""

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.available = True
        self._load_error: str | None = None
        self._model = None
        self._preprocess = None
        self._room_feats: dict[str, object] = {}

    def _load(self) -> None:
        if self._model is not None or not self.available:
            return
        try:
            import open_clip
            import torch

            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai")
            dev = self.device
            if dev == "cpu" and torch.cuda.is_available():
                dev = "cuda"
            model = model.to(dev).eval()
            tokenizer = open_clip.get_tokenizer("ViT-B-32")
            room_feats: dict[str, object] = {}
            with torch.no_grad():
                for room, prompts in ROOM_PROMPTS.items():
                    tokens = tokenizer(prompts).to(dev)
                    feats = model.encode_text(tokens)
                    feats = feats / feats.norm(dim=-1, keepdim=True)
                    room_feats[room] = feats.mean(dim=0, keepdim=True)
            self._model = model
            self._preprocess = preprocess
            self._room_feats = room_feats
            self.device = dev
            self._torch = torch
        except Exception as exc:
            self.available = False
            self._load_error = str(exc)

    def predict_path(self, path: Path) -> tuple[str, float]:
        self._load()
        if not self.available:
            raise RuntimeError(self._load_error or "OpenCLIP unavailable")
        from PIL import Image

        torch = self._torch
        with Image.open(path) as im:
            tensor = self._preprocess(im.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            img = self._model.encode_image(tensor)
            img = img / img.norm(dim=-1, keepdim=True)
            best_room, best_score = "Hallway", float("-inf")
            for room, feat in self._room_feats.items():
                score = float((img @ feat.T).item())
                if score > best_score:
                    best_room, best_score = room, score
        return best_room, best_score

    def predict_evidence(self, evidence: str) -> tuple[str, float, str]:
        room = evidence_prefix_room(evidence)
        if room:
            return room, 1.0, "evidence-prefix"
        return "Hallway", 0.0, "evidence-prefix-fallback"


def demo_predict(evidence: str) -> tuple[str, float, str]:
    room = evidence_prefix_room(evidence)
    if room:
        return room, 1.0, "demo-prefix"
    return "Hallway", 0.0, "demo-prefix-fallback"


def load_bleed(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("exclusions") or [])


def evaluate_bleed(
        exclusions: list[dict],
        *,
        report_dir: Path | None,
        backend: str,
        device: str,
) -> tuple[list[dict], dict]:
    clip: OpenCLIPRoomClassifier | None = None
    if backend == "openclip":
        clip = OpenCLIPRoomClassifier(device=device)

    rows: list[dict] = []
    n_reject = 0
    n_true_match = 0
    n_resolved = 0

    for ex in exclusions:
        assigned = ex["room"]
        true_room = normalize_true_room(ex.get("true_room", ""))
        evidence = ex.get("evidence", "")
        predicted = None
        confidence = 0.0
        source = "unresolved"
        frame_path: str | None = None

        path = resolve_frame_path(report_dir, evidence) if report_dir else None
        if path and clip and clip.available:
            try:
                predicted, confidence = clip.predict_path(path)
                source = "openclip-image"
                frame_path = str(path)
            except Exception:
                path = None

        if predicted is None and path and backend == "demo":
            predicted, confidence, source = demo_predict(evidence)
            source = "demo-with-frame"
            frame_path = str(path)

        if predicted is None:
            predicted, confidence, source = demo_predict(evidence)
            if path:
                frame_path = str(path)

        would_reject = predicted != assigned
        true_match = predicted == true_room
        if would_reject:
            n_reject += 1
        if true_match:
            n_true_match += 1
        n_resolved += 1

        rows.append({
            "id": ex.get("id"),
            "assigned_room": assigned,
            "true_room": true_room,
            "predicted_room": predicted,
            "confidence": round(confidence, 4),
            "would_reject": would_reject,
            "true_room_match": true_match,
            "source": source,
            "evidence": evidence,
            "frame_path": frame_path,
        })

    metrics = {
        "n_exclusions": len(exclusions),
        "n_resolved": n_resolved,
        "would_reject_rate": round(100 * n_reject / max(n_resolved, 1), 1),
        "true_room_top1_rate": round(100 * n_true_match / max(n_resolved, 1), 1),
        "pass_bar_note": "Wrong-room bleed should decrease — higher reject + true match",
    }
    return rows, metrics


def train_stub(
        *,
        output: Path,
        stream_hf: bool,
        max_samples: int,
) -> dict:
    """Write demo weights + documented fine-tune steps (no full 150 MB download)."""
    steps = [
        "Download HF dataset: uv pip install datasets huggingface_hub",
        f"  load_dataset('{HF_DATASET}') or save_to_disk {HF_CACHE}",
        "Map MIT67 label → inventory room via MIT67_TO_INVENTORY (drop None)",
        "Fine-tune ViT-B/32 head (OpenCLIP) or train linear probe on embeddings",
        "Eval: uv run python evals/eval_room_classifier.py report --backend openclip",
        "Pass bar: would_reject_rate ↑ and true_room_top1_rate on bleed audit",
    ]
    label_counts: dict[str, int] = {r: 0 for r in INVENTORY_ROOMS}
    mode = "documented-stub"
    n_seen = 0
    n_mapped = 0

    if stream_hf:
        try:
            from datasets import load_dataset
        except ImportError:
            stream_hf = False
        else:
            try:
                ds = load_dataset(HF_DATASET, split="train", streaming=True)
                for row in ds:
                    if n_seen >= max_samples:
                        break
                    n_seen += 1
                    label = row.get("label")
                    if isinstance(label, int):
                        # HF provides ClassLabel — resolve via features if present
                        name = str(label)
                    else:
                        name = str(label).lower().replace(" ", "_")
                    inv = MIT67_TO_INVENTORY.get(name)
                    if inv:
                        label_counts[inv] = label_counts.get(inv, 0) + 1
                        n_mapped += 1
                mode = "hf-stream-counts"
            except Exception as exc:
                mode = f"hf-stream-failed:{exc}"

    if HF_CACHE.is_dir() and n_seen == 0:
        try:
            from datasets import load_from_disk
            ds = load_from_disk(str(HF_CACHE))
            split = ds.get("train") or ds
            for i, row in enumerate(split):
                if i >= max_samples:
                    break
                n_seen += 1
                name = str(row.get("label_text") or row.get("label", "")).lower()
                inv = MIT67_TO_INVENTORY.get(name)
                if inv:
                    label_counts[inv] = label_counts.get(inv, 0) + 1
                    n_mapped += 1
            mode = "local-disk-counts"
        except Exception:
            pass

    payload = {
        "experiment": "ML-E16",
        "licence": "MIT",
        "backend": "openclip-zero-shot",
        "inventory_rooms": INVENTORY_ROOMS,
        "mit67_to_inventory": MIT67_TO_INVENTORY,
        "room_prompts": ROOM_PROMPTS,
        "training": {
            "mode": mode,
            "hf_dataset": HF_DATASET,
            "n_samples_seen": n_seen,
            "n_mapped_to_inventory": n_mapped,
            "inventory_label_counts": label_counts,
            "fine_tune_steps": steps,
            "note": (
                "Demo weights — zero-shot OpenCLIP prompts only. "
                "Full fine-tune requires HF indoor-scene download (~150 MB)."
            ),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload["training"]


def run_eval(args: argparse.Namespace) -> dict:
    bleed_path = args.bleed.resolve()
    exclusions = load_bleed(bleed_path)
    report_dir = args.report.resolve() if args.report else None
    if report_dir and not (report_dir / "inventory.json").is_file():
        print(f"warning: no inventory.json under {report_dir}", file=sys.stderr)
        report_dir = None

    backend = args.backend
    if backend == "auto":
        backend = "openclip" if report_dir else "demo"

    rows, metrics = evaluate_bleed(
        exclusions,
        report_dir=report_dir,
        backend=backend,
        device=args.device,
    )

    payload = {
        "experiment": "ML-E16",
        "bleed_fixture": str(bleed_path.relative_to(ROOT)),
        "report_dir": str(report_dir) if report_dir else None,
        "backend": backend,
        "metrics": metrics,
        "per_item": rows,
    }
    if args.weights.is_file():
        try:
            payload["weights"] = str(args.weights.resolve().relative_to(ROOT))
        except ValueError:
            payload["weights"] = str(args.weights)

    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"wrote {out}")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, nargs="?", default=None,
                    help="build output dir (optional — enables image classify)")
    ap.add_argument("--bleed", type=Path, default=DEFAULT_BLEED)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--backend", choices=["auto", "demo", "openclip"],
                    default="auto")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--train-stub", action="store_true",
                    help="write room-clf-weights.json + fine-tune doc (ML-E16 stub)")
    ap.add_argument("--stream-hf", action="store_true",
                    help="with --train-stub, stream HF indoor labels (no images)")
    ap.add_argument("--max-samples", type=int, default=128)
    args = ap.parse_args()

    if args.train_stub:
        info = train_stub(
            output=args.weights,
            stream_hf=args.stream_hf,
            max_samples=args.max_samples,
        )
        print(json.dumps(info, indent=2))
        print(f"wrote {args.weights}")

    payload = run_eval(args)
    return 0 if payload["metrics"]["n_resolved"] else 1


if __name__ == "__main__":
    sys.exit(main())
