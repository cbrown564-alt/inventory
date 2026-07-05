"""OpenCLIP zero-shot defect vs clean margin scorer (ML-E15 / ML-E20).

Apache-2.0 encoder only — eval harness, not imported by product build.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

DEFECT_PROMPTS = [
    "visible damage on a surface",
    "stain on wall or floor",
    "crack in wall or ceiling",
    "chip or scratch on furniture",
    "mould or water damage",
]

CLEAN_PROMPTS = [
    "clean undamaged interior surface",
    "well-maintained room with no visible damage",
    "pristine wall or floor surface",
    "clean household fixture in good condition",
]

DEFAULT_THRESHOLD = 0.5


class DefectZeroshotScorer:
    """CLIP margin: defect prompts vs clean-surface prompts."""

    def __init__(self, device: str | None = None, backend: str = "open_clip"):
        self.device = device
        self.backend = backend
        self.available = True
        self._load_error: str | None = None
        self._model = None
        self._preprocess = None
        self._text_features = None
        self._n_defect = len(DEFECT_PROMPTS)

    def _load(self) -> None:
        if self._model is not None or not self.available:
            return
        try:
            import open_clip
            import torch

            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai",
            )
            tokenizer = open_clip.get_tokenizer("ViT-B-32")
            dev = self._resolve_device(torch)
            model = model.to(dev).eval()
            text = DEFECT_PROMPTS + CLEAN_PROMPTS
            tokens = tokenizer(text).to(dev)
            with torch.no_grad():
                feats = model.encode_text(tokens)
                feats = feats / feats.norm(dim=-1, keepdim=True)
            self._model = model
            self._preprocess = preprocess
            self._text_features = feats
            self._torch = torch
        except Exception as exc:
            self.available = False
            self._load_error = str(exc)

    def _resolve_device(self, torch):
        if self.device:
            return self.device
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def score_path(self, path: Path) -> dict:
        """Return defect margin and softmax defect probability."""
        self._load()
        if not self.available:
            return {
                "margin": float("nan"),
                "defect_prob": float("nan"),
                "flagged": False,
            }

        from PIL import Image

        image = Image.open(path).convert("RGB")
        dev = self._resolve_device(self._torch)
        tensor = self._preprocess(image).unsqueeze(0).to(dev)
        with self._torch.no_grad():
            img_feat = self._model.encode_image(tensor)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            sims = (img_feat @ self._text_features.T).squeeze(0)

        sims = sims.float().cpu()
        defect_mean = float(sims[: self._n_defect].mean())
        clean_mean = float(sims[self._n_defect :].mean())
        margin = defect_mean - clean_mean
        pair = self._torch.tensor([defect_mean, clean_mean])
        defect_prob = float(self._torch.softmax(pair * 100.0, dim=0)[0])
        return {
            "margin": margin,
            "defect_prob": defect_prob,
            "defect_sim": defect_mean,
            "clean_sim": clean_mean,
            "flagged": defect_prob >= DEFAULT_THRESHOLD,
        }


def synthetic_defect_score(path: Path, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Deterministic pseudo-scores for --demo / --no-torch (no torch download)."""
    digest = hashlib.sha256(str(path).encode()).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    # Skew high: InventoryFlex clean photos still get ~45% flagged in live runs.
    defect_prob = 0.35 + 0.55 * bucket
    margin = defect_prob - 0.5
    return {
        "margin": round(margin, 4),
        "defect_prob": round(defect_prob, 4),
        "defect_sim": round(0.22 + 0.1 * bucket, 4),
        "clean_sim": round(0.20 + 0.08 * (1 - bucket), 4),
        "flagged": defect_prob >= threshold,
        "synthetic": True,
    }
