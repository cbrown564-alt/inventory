#!/usr/bin/env python3
"""ML-E17 (correct): within-room photo-quality ranker on real embeddings.

``train_iqa_koniq.py`` fits a linear head on hand-crafted PIL features
(brightness/contrast/sharpness heuristics). Swapping in real KonIQ-10k MOS
labels there would only change the training *target*, not the model class —
and ``eval_hero_cover.py --scorer linear-musiq`` would still score frames
through those same PIL features. That is not a real learned-IQA test
(docs/22 §3.4, docs/23 §5).

This script instead reuses the embedding-head engine shared with
``train_room_classifier.py`` (``evals/embed_head.py``) in *regression* mode:

  1. Embed each KonIQ-10k image with a frozen Apache-2.0 encoder (OpenCLIP,
     default ViT-L-14 — same embedder as the room classifier).
  2. Train a linear regression head (not softmax) over the embeddings against
     KonIQ MOS.
  3. Save MIT-licensed weights JSON consumed by
     ``eval_hero_cover.py --scorer embed-iqa``.

KonIQ-10k needs manual registration (no self-serve download URL) — see
``evals/external/scripts/download_datasets.py koniq`` and docs/23 §0. Until
that data is unpacked to ``evals/external/data/koniq10k/``, run the
self-test instead:

    uv run python evals/train_iqa_embed.py --self-test

Real run (after KonIQ lands):

    uv run python evals/train_iqa_embed.py \\
        --encoder-model ViT-L-14 --pretrained laion2b_s32b_b82k --device cuda
    uv run python evals/eval_hero_cover.py report --scorer embed-iqa \\
        --embed-iqa-weights evals/fixtures/own-property/iqa-embed-weights.json \\
        --device cuda --gold evals/fixtures/own-property/hero-gold.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.embed_head import (  # noqa: E402
    ClipEmbedder,
    predict_regression_from_json,
    regressor_head_to_json,
    train_linear_regressor,
)
from evals.train_iqa_koniq import (  # noqa: E402
    KONIQ_DIR,
    find_koniq_image,
    find_koniq_scores,
    load_koniq_mos,
)

DEFAULT_WEIGHTS = ROOT / "evals" / "fixtures" / "own-property" / "iqa-embed-weights.json"


# ---------------------------------------------------------------------------
# Data (KonIQ-10k local cache only — no HF streaming source as of Jul 2026,
# mirroring train_iqa_koniq.py)
# ---------------------------------------------------------------------------

def load_koniq_pairs(max_samples: int) -> list[tuple]:
    """[(PIL image, MOS)] from the local KonIQ-10k cache. Empty if absent."""
    from PIL import Image

    scores_path = find_koniq_scores()
    if scores_path is None:
        return []
    mos_map = load_koniq_mos(scores_path)
    out: list[tuple] = []
    for stem, mos in mos_map.items():
        if len(out) >= max_samples:
            break
        img_path = find_koniq_image(stem)
        if img_path is None:
            continue
        try:
            with Image.open(img_path) as im:
                out.append((im.convert("RGB").copy(), float(mos)))
        except OSError:
            continue
    return out


def build_training_tensors(pairs: list[tuple], embedder, batch: int = 64):
    """pairs: [(PIL image, float MOS)] -> (X, y) tensors."""
    import torch

    feats = []
    ys: list[float] = []
    buf_imgs, buf_y = [], []

    def flush():
        if not buf_imgs:
            return
        feats.append(embedder.embed_pil(buf_imgs))
        ys.extend(buf_y)
        buf_imgs.clear()
        buf_y.clear()

    for img, mos in pairs:
        buf_imgs.append(img)
        buf_y.append(mos)
        if len(buf_imgs) >= batch:
            flush()
    flush()
    X = torch.cat(feats, dim=0) if feats else torch.empty(0)
    y = torch.tensor(ys, dtype=torch.float32)
    return X, y


# ---------------------------------------------------------------------------

def self_test() -> int:
    """Validate regressor training + save/load/predict on synthetic data.

    No network, no KonIQ download — mirrors train_room_classifier.py's
    --self-test (synthetic embeddings, but a regression target here: a known
    linear function of the embedding plus noise, instead of class clusters).
    """
    import torch

    d, n = 64, 200
    torch.manual_seed(0)
    true_w = torch.randn(d)
    true_b = 0.3
    X = torch.randn(n, d)
    y = X @ true_w + true_b + 0.01 * torch.randn(n)

    head, metrics = train_linear_regressor(X, y, device="cpu", epochs=300)
    weights = regressor_head_to_json(head, {"model": "synthetic"}, metrics)

    pred0 = predict_regression_from_json(weights, X[0])
    target0 = float(y[0])
    assert metrics["spearman_train"] is not None and metrics["spearman_train"] > 0.9, metrics
    assert abs(pred0 - target0) < 1.0, (pred0, target0)

    print(json.dumps({"self_test": "ok", **metrics, "pred0": round(pred0, 3),
                      "target0": round(target0, 3)}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--encoder-model", default="ViT-L-14")
    ap.add_argument("--pretrained", default="laion2b_s32b_b82k")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--max-samples", type=int, default=2000,
                    help="cap KonIQ rows embedded (local cache)")
    ap.add_argument("-o", "--weights-out", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    pairs = load_koniq_pairs(args.max_samples)
    if not pairs:
        print(f"no KonIQ images/scores found under {KONIQ_DIR.relative_to(ROOT)} "
              "— register and download first "
              "(evals/external/scripts/download_datasets.py koniq; docs/23 §0)",
              file=sys.stderr)
        return 1

    embedder = ClipEmbedder(args.encoder_model, args.pretrained, args.device)
    print(f"embedding {len(pairs)} KonIQ images ({args.encoder_model}, "
          f"dim={embedder.dim}) …", flush=True)
    X, y = build_training_tensors(pairs, embedder)
    head, metrics = train_linear_regressor(X, y, device=args.device, epochs=args.epochs)
    metrics["n_train"] = int(len(y))

    weights = regressor_head_to_json(head, {
        "model": args.encoder_model, "pretrained": args.pretrained,
        "dim": embedder.dim}, metrics)
    args.weights_out.parent.mkdir(parents=True, exist_ok=True)
    args.weights_out.write_text(json.dumps(weights, indent=2), encoding="utf-8")
    print(f"wrote {args.weights_out} (spearman_train={metrics['spearman_train']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
