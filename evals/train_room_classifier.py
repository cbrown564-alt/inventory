#!/usr/bin/env python3
"""ML-E16 (real): room-type classifier — fine-tune a linear head on encoder
embeddings of MIT Indoor 67, mapped to ~10 inventory rooms (docs/19 §1.5, docs/23).

This replaces the label-counting *stub* in ``eval_room_classifier.py`` with an
actual trained model:

  1. Load Indoor 67 (HF ``keremberke/indoor-scene-classification`` — local cache
     ``evals/external/data/indoor-scene`` if present, else download).
  2. Keep only classes that map to an inventory room (``MIT67_TO_INVENTORY``);
     embed each image with an Apache-2.0 encoder (OpenCLIP, default ViT-L-14).
  3. Train a linear softmax head (logistic regression) over the ~10 rooms.
  4. Save MIT-licensed weights JSON + training metrics.
  5. Optionally evaluate on the wrong-room bleed audit (report frames) and write
     ``room-clf-eval.json`` with would-reject / true-room-top1 rates.

Pass bar (docs/21 ML-E16): would-reject on bleed ↑ **and** true-room top-1 not
near-zero (the stub's 8.6% is the failure this run must beat).

Usage (GPU box):
    uv run python evals/train_room_classifier.py \\
        --encoder-model ViT-L-14 --pretrained laion2b_s32b_b82k \\
        --device cuda --epochs 60
    # then eval on the own-property build (frames resolved from bleed evidence):
    uv run python evals/train_room_classifier.py --eval-only report \\
        --device cuda

Smoke test (no download):
    uv run python evals/train_room_classifier.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.eval_room_classifier import (  # noqa: E402
    HF_CACHE,
    HF_DATASET,
    INVENTORY_ROOMS,
    MIT67_TO_INVENTORY,
    load_bleed,
    normalize_true_room,
    resolve_frame_path,
)
from evals.embed_head import (  # noqa: E402
    ClipEmbedder,
    head_to_json,
    predict_from_json,
    train_linear_head,
)

DEFAULT_WEIGHTS = ROOT / "evals" / "fixtures" / "own-property" / "room-clf-weights.json"
DEFAULT_EVAL = ROOT / "evals" / "fixtures" / "own-property" / "room-clf-eval.json"
DEFAULT_BLEED = ROOT / "evals" / "fixtures" / "ownproperty-bleed-exclusions.json"

# Encoder loading, the linear-head training loop, and the JSON save/load
# helpers live in evals/embed_head.py — shared with train_iqa_embed.py
# (regression mode over the same embeddings, docs/23 §5).


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_indoor67_split(max_per_class: int):
    """Yield (PIL image, inventory_room) for mapped classes."""
    from datasets import load_dataset, load_from_disk

    if HF_CACHE.is_dir():
        ds = load_from_disk(str(HF_CACHE))
        split = ds["train"] if hasattr(ds, "keys") and "train" in ds else ds
    else:
        split = load_dataset(HF_DATASET, split="train")

    # HF label column name varies by dataset build: keremberke's
    # indoor-scene-classification uses "labels" (plural); some mirrors use
    # singular "label". Support both rather than hardcoding one.
    label_col = None
    feats = getattr(split, "features", {})
    for candidate in ("labels", "label"):
        if candidate in feats:
            label_col = candidate
            break
    int2str = None
    if label_col and hasattr(feats[label_col], "int2str"):
        int2str = feats[label_col].int2str

    counts: dict[str, int] = {}
    out = []
    for row in split:
        label = row.get(label_col) if label_col else (row.get("labels") if "labels" in row else row.get("label"))
        name = int2str(label) if (int2str and isinstance(label, int)) else str(
            row.get("label_text") or label)
        name = str(name).lower().replace(" ", "_")
        inv = MIT67_TO_INVENTORY.get(name)
        if not inv:
            continue
        if counts.get(inv, 0) >= max_per_class:
            continue
        img = row.get("image")
        if img is None:
            continue
        out.append((img, inv))
        counts[inv] = counts.get(inv, 0) + 1
    return out, counts


def build_training_tensors(pairs, classes, embedder, batch: int = 64):
    import torch

    cls_index = {c: i for i, c in enumerate(classes)}
    feats = []
    ys = []
    buf_imgs, buf_lab = [], []

    def flush():
        if not buf_imgs:
            return
        feats.append(embedder.embed_pil(buf_imgs))
        ys.extend(buf_lab)
        buf_imgs.clear()
        buf_lab.clear()

    for img, inv in pairs:
        buf_imgs.append(img)
        buf_lab.append(cls_index[inv])
        if len(buf_imgs) >= batch:
            flush()
    flush()
    X = torch.cat(feats, dim=0) if feats else torch.empty(0)
    y = torch.tensor(ys, dtype=torch.long)
    return X, y


# ---------------------------------------------------------------------------
# Eval on bleed audit
# ---------------------------------------------------------------------------

def eval_bleed(weights: dict, embedder, report_dir: Path | None) -> dict:
    exclusions = load_bleed(DEFAULT_BLEED)
    rows, n_reject, n_true, n_res = [], 0, 0, 0
    for ex in exclusions:
        assigned = ex["room"]
        true_room = normalize_true_room(ex.get("true_room", ""))
        evidence = ex.get("evidence", "")
        path = resolve_frame_path(report_dir, evidence) if report_dir else None
        if not path:
            continue
        feat = embedder.embed_path(path)
        pred, conf = predict_from_json(weights, feat)
        would_reject = pred != assigned
        true_match = pred == true_room
        n_reject += would_reject
        n_true += true_match
        n_res += 1
        rows.append({"id": ex.get("id"), "assigned_room": assigned,
                     "true_room": true_room, "predicted_room": pred,
                     "confidence": round(conf, 4), "would_reject": would_reject,
                     "true_room_match": true_match, "frame_path": str(path)})
    metrics = {
        "n_resolved": n_res,
        "would_reject_rate": round(100 * n_reject / max(n_res, 1), 1),
        "true_room_top1_rate": round(100 * n_true / max(n_res, 1), 1),
    }
    return {"experiment": "ML-E16", "backend": "clip-linear-head",
            "metrics": metrics, "per_item": rows}


# ---------------------------------------------------------------------------

def self_test() -> int:
    """Validate head training + save/load/predict on synthetic embeddings."""
    import torch

    classes = INVENTORY_ROOMS
    d, n = 64, len(classes)
    torch.manual_seed(0)
    centers = torch.randn(n, d)
    X = torch.cat([centers[i] + 0.1 * torch.randn(20, d) for i in range(n)])
    y = torch.cat([torch.full((20,), i) for i in range(n)])
    head, m = train_linear_head(X, y, n_classes=n, device="cpu", epochs=40)
    js = head_to_json(head, classes, {"model": "synthetic"}, m)
    pred, conf = predict_from_json(js, X[0])
    assert pred == classes[0], (pred, classes[0])
    assert m["train_acc"] > 0.9, m
    print(json.dumps({"self_test": "ok", **m, "pred0": pred,
                      "conf": round(conf, 3)}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, nargs="?", default=None,
                    help="build dir for bleed eval (resolves frames from evidence)")
    ap.add_argument("--encoder-model", default="ViT-L-14")
    ap.add_argument("--pretrained", default="laion2b_s32b_b82k")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--max-per-class", type=int, default=400)
    ap.add_argument("-o", "--weights-out", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--eval-out", type=Path, default=DEFAULT_EVAL)
    ap.add_argument("--eval-only", action="store_true",
                    help="skip training; load existing weights and eval on bleed")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    embedder = ClipEmbedder(args.encoder_model, args.pretrained, args.device)

    if args.eval_only:
        weights = json.loads(args.weights_out.read_text(encoding="utf-8"))
    else:
        pairs, counts = load_indoor67_split(args.max_per_class)
        if not pairs:
            print("no mapped Indoor67 images found — download the dataset first "
                  "(evals/external/scripts/download_datasets.py indoor67)",
                  file=sys.stderr)
            return 1
        classes = [c for c in INVENTORY_ROOMS if counts.get(c)]
        print(f"embedding {len(pairs)} images across {len(classes)} rooms "
              f"({args.encoder_model}, dim={embedder.dim}) …", flush=True)
        X, y = build_training_tensors(pairs, classes, embedder)
        # remap y to the reduced class list order
        head, metrics = train_linear_head(
            X, y, n_classes=len(classes), device=args.device, epochs=args.epochs)
        metrics["n_train"] = int(len(y))
        metrics["per_room_counts"] = counts
        weights = head_to_json(head, classes, {
            "model": args.encoder_model, "pretrained": args.pretrained,
            "dim": embedder.dim}, metrics)
        args.weights_out.parent.mkdir(parents=True, exist_ok=True)
        args.weights_out.write_text(json.dumps(weights, indent=2), encoding="utf-8")
        print(f"wrote {args.weights_out} (train_acc={metrics['train_acc']})")

    report_dir = args.report.resolve() if args.report else None
    if report_dir:
        result = eval_bleed(weights, embedder, report_dir)
        args.eval_out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result["metrics"], indent=2))
        print(f"wrote {args.eval_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
