"""Optional torch encoders for ML eval harnesses (ML-E1, ML-E4).

Apache-2.0 encoders only: OpenCLIP, timm DINOv2, SigLIP via transformers.
Install manually when running GPU evals:

    uv pip install torch torchvision open-clip-torch timm transformers pillow

Nothing here is imported by the product build path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

_ESTABLISHING = "a wide interior photograph of a room"
_CLOSEUP = "a close-up photograph of an object"

_TORCH_ERR = (
    "torch is required for this scorer — install with:\n"
    "  uv pip install torch torchvision open-clip-torch timm transformers"
)


def require_torch():
    try:
        import torch  # noqa: F401
    except ImportError as e:
        raise ImportError(_TORCH_ERR) from e


def _load_grey_pil(path: Path, max_px: int = 640):
    from PIL import Image

    with Image.open(path) as im:
        im.draft("RGB", (max_px, max_px))
        rgb = im.convert("RGB")
        if max(rgb.size) > max_px:
            rgb.thumbnail((max_px, max_px))
        return rgb


class SigLIPRelevanceScorer:
    """SigLIP margin: establishing interior vs object close-up (ML-E4)."""

    def __init__(self, model_id: str = "google/siglip-base-patch16-224",
                 device: str = "cpu"):
        require_torch()
        import torch
        from transformers import AutoModel, AutoProcessor

        self.device = device
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id).to(device).eval()
        self.torch = torch
        with torch.no_grad():
            pos = self._encode_text(_ESTABLISHING)
            neg = self._encode_text(_CLOSEUP)
            pos = pos / pos.norm(dim=-1, keepdim=True)
            neg = neg / neg.norm(dim=-1, keepdim=True)
            self._pos = pos
            self._neg = neg

    def _encode_text(self, text: str):
        inputs = self.processor(text=[text], return_tensors="pt", padding=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        feat = self.model.get_text_features(**inputs)
        if not hasattr(feat, "norm"):
            feat = feat.pooler_output
        return feat

    def _encode_image(self, path: Path):
        rgb = _load_grey_pil(path)
        inputs = self.processor(images=[rgb], return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with self.torch.no_grad():
            feat = self.model.get_image_features(**inputs)
        if not hasattr(feat, "norm"):
            feat = feat.pooler_output
        feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat[0]

    def score_path(self, path: Path) -> float:
        """Higher = more establishing, less close-up."""
        feat = self._encode_image(path)
        pos = float((feat @ self._pos[0]).item())
        neg = float((feat @ self._neg[0]).item())
        return pos - neg


class OpenCLIPRelevanceScorer:
    """OpenCLIP prompt-pair margin (Apache-2.0 fallback for ML-E4)."""

    def __init__(self, model_name: str = "ViT-B-32",
                 pretrained: str = "openai", device: str = "cpu"):
        require_torch()
        import open_clip
        import torch

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=device)
        self.tokenizer = open_clip.get_tokenizer(model_name)
        self.model.eval()
        self.device = device
        with torch.no_grad():
            pos = self._encode_text(_ESTABLISHING)
            neg = self._encode_text(_CLOSEUP)
            self._pos = pos / pos.norm(dim=-1, keepdim=True)
            self._neg = neg / neg.norm(dim=-1, keepdim=True)

    def _encode_text(self, text: str):
        tokens = self.tokenizer([text]).to(self.device)
        return self.model.encode_text(tokens)

    def _encode_image(self, path: Path):
        rgb = _load_grey_pil(path)
        tensor = self.preprocess(rgb).unsqueeze(0).to(self.device)
        with self.torch.no_grad():
            feat = self.model.encode_image(tensor)
        return feat / feat.norm(dim=-1, keepdim=True)

    def score_path(self, path: Path) -> float:
        feat = self._encode_image(path)
        pos = float((feat @ self._pos.T).item())
        neg = float((feat @ self._neg.T).item())
        return pos - neg


# Recommended fair-test encoders for a CUDA re-run (docs/22 §3.2 / docs/23).
# The ViT-B-32 / siglip-base-224 defaults are the *weakest* common variants and
# are the reason ML-E4/E7/E19 read as failures on CPU. On an 8 GB GPU these all
# fit for inference.
FAIR_ENCODERS = {
    "siglip": "google/siglip-large-patch16-384",   # ~1.7 GB, strong zero-shot
    "siglip2": "google/siglip2-large-patch16-384",
    "openclip": ("ViT-L-14", "laion2b_s32b_b82k"),
}


def make_relevance_scorer(
        backend: str = "siglip",
        device: str = "cpu",
        model_id: str | None = None,
        pretrained: str | None = None,
) -> SigLIPRelevanceScorer | OpenCLIPRelevanceScorer:
    """Build a relevance scorer.

    ``model_id`` overrides the (deliberately weak) defaults so a GPU re-run can
    use a fair encoder, e.g. ``google/siglip-large-patch16-384`` for siglip or
    ``ViT-L-14`` (+ ``pretrained='laion2b_s32b_b82k'``) for openclip.
    """
    if backend == "siglip":
        if model_id:
            return SigLIPRelevanceScorer(model_id=model_id, device=device)
        return SigLIPRelevanceScorer(device=device)
    if backend == "openclip":
        if model_id:
            return OpenCLIPRelevanceScorer(
                model_name=model_id,
                pretrained=pretrained or "laion2b_s32b_b82k",
                device=device,
            )
        return OpenCLIPRelevanceScorer(device=device)
    raise ValueError(f"unknown relevance backend: {backend}")


class FrameEmbedder:
    """Frame embeddings for changepoint detection (ML-E1)."""

    def __init__(self, backend: str = "dinov2", device: str = "cpu"):
        require_torch()
        import torch

        self.torch = torch
        self.device = device
        self.backend = backend
        self._encode_jpeg: Callable[[bytes], "torch.Tensor"]

        if backend == "dinov2":
            import timm
            from timm.data import create_transform, resolve_model_data_config

            self.model = timm.create_model(
                "vit_small_patch14_dinov2.lvd142m", pretrained=True)
            self.model.eval().to(device)
            data_config = resolve_model_data_config(self.model)
            self.transform = create_transform(**data_config, is_training=False)

            def encode_jpeg(jpeg: bytes):
                from PIL import Image
                import io

                rgb = Image.open(io.BytesIO(jpeg)).convert("RGB")
                t = self.transform(rgb).unsqueeze(0).to(device)
                with torch.no_grad():
                    feat = self.model(t)
                feat = feat / feat.norm(dim=-1, keepdim=True)
                return feat[0].cpu()

            self._encode_jpeg = encode_jpeg

        elif backend == "openclip":
            import open_clip

            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai", device=device)
            self.model.eval()

            def encode_jpeg(jpeg: bytes):
                from PIL import Image
                import io

                rgb = Image.open(io.BytesIO(jpeg)).convert("RGB")
                t = self.preprocess(rgb).unsqueeze(0).to(device)
                with torch.no_grad():
                    feat = self.model.encode_image(t)
                feat = feat / feat.norm(dim=-1, keepdim=True)
                return feat[0].cpu()

            self._encode_jpeg = encode_jpeg
        else:
            raise ValueError(f"unknown embed backend: {backend}")

    def embed_jpeg(self, jpeg: bytes):
        return self._encode_jpeg(jpeg)


def cosine_distance(a, b) -> float:
    import torch

    return float(1.0 - torch.dot(a, b).item())


def detect_changepoints(
        distances: list[float],
        *,
        threshold: Optional[float] = None,
        min_gap: int = 2,
) -> list[int]:
    """Return indices *after* which a boundary is proposed (peak picking)."""
    if len(distances) < 3:
        return []
    if threshold is None:
        mu = sum(distances) / len(distances)
        var = sum((d - mu) ** 2 for d in distances) / len(distances)
        threshold = mu + 1.5 * (var ** 0.5)
    peaks: list[int] = []
    for i in range(1, len(distances) - 1):
        if distances[i] >= threshold and distances[i] >= distances[i - 1] \
                and distances[i] >= distances[i + 1]:
            if peaks and i - peaks[-1] < min_gap:
                if distances[i] > distances[peaks[-1]]:
                    peaks[-1] = i
            else:
                peaks.append(i)
    return peaks


def synthetic_demo_distances(n: int = 40, boundaries: list[int] | None = None) -> list[float]:
    """Demo cosine distances with spikes at known boundaries (no video/torch)."""
    boundaries = boundaries or [10, 22, 33]
    base = 0.08
    out = [base] * (n - 1)
    for b in boundaries:
        if 0 < b < len(out):
            out[b - 1] = 0.45
            if b < len(out):
                out[b] = 0.38
    return out
