#!/usr/bin/env python3
"""Shared embedding + linear-head engine (docs/23 §3, §5).

Factored out of ``train_room_classifier.py`` so both it (classification: room
type over Indoor67) and ``train_iqa_embed.py`` (regression: KonIQ MOS) can
train a linear head on top of the same frozen vision-encoder embeddings
without duplicating the encoder-loading / training-loop code.

Not a general framework — just the two shapes these two call sites need:
a softmax classifier head and a single-output regression head, both trained
with AdamW over full-batch embeddings (small N: a few thousand images at
most), both exported as small MIT-licensed JSON blobs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.train_iqa_linear import spearman  # noqa: E402


# ---------------------------------------------------------------------------
# Encoder (OpenCLIP, Apache-2.0). Fair default is ViT-L-14 on an 8 GB GPU.
# ---------------------------------------------------------------------------

class ClipEmbedder:
    def __init__(self, model_name: str = "ViT-L-14",
                 pretrained: str = "laion2b_s32b_b82k", device: str = "cpu"):
        import open_clip
        import torch

        self.torch = torch
        dev = device
        if dev == "cuda" and not torch.cuda.is_available():
            dev = "cpu"
        self.device = dev
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=dev)
        self.model.eval()
        self.dim = int(self.model.visual.output_dim)

    def embed_pil(self, images: list) -> "list":
        import torch

        tensors = torch.stack([self.preprocess(im.convert("RGB")) for im in images])
        tensors = tensors.to(self.device)
        with torch.no_grad():
            feats = self.model.encode_image(tensors)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu()

    def embed_path(self, path: Path):
        from PIL import Image

        with Image.open(path) as im:
            return self.embed_pil([im])[0]


# ---------------------------------------------------------------------------
# Classification head (softmax over ~10 rooms — ML-E16)
# ---------------------------------------------------------------------------

def train_linear_head(X, y, *, n_classes: int, device: str = "cpu",
                      epochs: int = 60, lr: float = 0.05, weight_decay: float = 1e-4):
    """Train a softmax head. X: (N,D) float tensor, y: (N,) long tensor."""
    import torch
    from torch import nn

    dev = device if (device != "cuda" or torch.cuda.is_available()) else "cpu"
    X = X.to(dev)
    y = y.to(dev)
    head = nn.Linear(X.shape[1], n_classes).to(dev)
    opt = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=weight_decay)
    lossf = nn.CrossEntropyLoss()
    head.train()
    for _ in range(epochs):
        opt.zero_grad()
        loss = lossf(head(X), y)
        loss.backward()
        opt.step()
    head.eval()
    with torch.no_grad():
        acc = float((head(X).argmax(1) == y).float().mean().item())
    return head, {"train_loss": round(float(loss.item()), 4),
                  "train_acc": round(acc, 4), "epochs": epochs}


def head_to_json(head, classes: list[str], encoder: dict, metrics: dict) -> dict:
    W = head.weight.detach().cpu().tolist()
    b = head.bias.detach().cpu().tolist()
    return {
        "experiment": "ML-E16",
        "licence": "MIT (head) — OpenCLIP encoder Apache-2.0",
        "kind": "linear-softmax-head-on-clip-embeddings",
        "encoder": encoder,
        "classes": classes,
        "weight": W,   # (n_classes, dim)
        "bias": b,     # (n_classes,)
        "training": metrics,
    }


def predict_from_json(weights: dict, feat) -> tuple[str, float]:
    import torch

    W = torch.tensor(weights["weight"])
    b = torch.tensor(weights["bias"])
    logits = W @ feat + b
    probs = torch.softmax(logits, dim=-1)
    idx = int(probs.argmax().item())
    return weights["classes"][idx], float(probs[idx].item())


# ---------------------------------------------------------------------------
# Regression head (scalar quality/MOS target — ML-E17)
# ---------------------------------------------------------------------------

def train_linear_regressor(X, y, *, device: str = "cpu", epochs: int = 200,
                           lr: float = 0.05, weight_decay: float = 1e-4):
    """Train a single-output linear regression head.

    X: (N,D) float tensor, y: (N,) float tensor (regression target, e.g. MOS).
    """
    import torch
    from torch import nn

    dev = device if (device != "cuda" or torch.cuda.is_available()) else "cpu"
    X = X.to(dev)
    y = y.to(dev).view(-1, 1)
    head = nn.Linear(X.shape[1], 1).to(dev)
    opt = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=weight_decay)
    lossf = nn.MSELoss()
    head.train()
    for _ in range(epochs):
        opt.zero_grad()
        loss = lossf(head(X), y)
        loss.backward()
        opt.step()
    head.eval()
    with torch.no_grad():
        preds = head(X).view(-1)
    rho = spearman(preds.cpu().tolist(), y.view(-1).cpu().tolist())
    return head, {
        "train_mse": round(float(loss.item()), 4),
        "spearman_train": round(rho, 4) if rho == rho else None,  # NaN-safe
        "epochs": epochs,
    }


def regressor_head_to_json(head, encoder: dict, metrics: dict) -> dict:
    W = head.weight.detach().cpu().view(-1).tolist()
    b = float(head.bias.detach().cpu().item())
    return {
        "experiment": "ML-E17",
        "licence": "MIT (head) — OpenCLIP encoder Apache-2.0",
        "kind": "linear-regression-head-on-clip-embeddings",
        "encoder": encoder,
        "weight": W,   # (dim,)
        "bias": b,     # scalar
        "training": metrics,
    }


def predict_regression_from_json(weights: dict, feat) -> float:
    import torch

    W = torch.tensor(weights["weight"])
    b = float(weights["bias"])
    return float((W @ feat).item() + b)
