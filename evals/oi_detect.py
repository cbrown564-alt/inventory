"""Eval-only OI-pretrain detector wrappers (ML-E18).

* ``OiPretrainedDetector`` — loads fine-tuned weights when present.
* ``OiProxyGroudingDinoDetector`` — bootstrap comparison using base GDINO
  with an expanded Open Images phrase list (no OI download required).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from homeinventory.detect import Detection

from gdino_detect import DEFAULT_MODEL, GroundingDinoDetector, _norm_label
from oi_vocab import (
    OI_CLASS_TO_HOUSEHOLD,
    expanded_proxy_vocab,
    find_oi_weights,
    map_oi_label_to_household,
)

log = logging.getLogger(__name__)


class OiProxyGroudingDinoDetector(GroundingDinoDetector):
    """GDINO with OI household phrases; maps detections to HOUSEHOLD_VOCAB."""

    def __init__(
        self,
        conf: float = 0.25,
        device: str | None = None,
        model_id: str = DEFAULT_MODEL,
    ):
        proxy_vocab = expanded_proxy_vocab()
        super().__init__(
            vocab=proxy_vocab,
            conf=conf,
            device=device,
            model_id=model_id,
        )
        self.mode = "oi_proxy"
        # Prompt phrases → household term for eval metrics.
        self._label_map = {}
        for phrase in proxy_vocab:
            household = map_oi_label_to_household(phrase)
            self._label_map[_norm_label(phrase)] = household
        for oi_key, household in OI_CLASS_TO_HOUSEHOLD.items():
            self._label_map.setdefault(oi_key, household)

    def _map_label(self, phrase: str) -> str:
        mapped = map_oi_label_to_household(phrase)
        if mapped != phrase.strip():
            return mapped
        return super()._map_label(phrase)


class OiPretrainedDetector(GroundingDinoDetector):
    """Grounding DINO fine-tuned on OI household subset (weights optional)."""

    def __init__(
        self,
        weights_path: str | None = None,
        conf: float = 0.25,
        device: str | None = None,
        model_id: str = DEFAULT_MODEL,
    ):
        self.weights_path = weights_path or find_oi_weights()
        self.mode = "oi_pretrain"
        super().__init__(
            vocab=expanded_proxy_vocab(),
            conf=conf,
            device=device,
            model_id=model_id,
        )
        if not self.weights_path:
            self.available = False
            self._load_error = (
                "OI-pretrained weights not found — see training_recipe in "
                "detect-comparison-oi.json and evals/external/README.md"
            )
            return
        self._custom_state_path = Path(self.weights_path)

    def _load(self) -> None:
        if self._model is not None or not self.available:
            return
        if not self.weights_path:
            self.available = False
            self._load_error = "OI-pretrained weights path not configured"
            return
        try:
            import torch

            super()._load()
            if not self.available:
                return
            state = torch.load(self.weights_path, map_location="cpu", weights_only=False)
            if isinstance(state, dict) and "state_dict" in state:
                state = state["state_dict"]
            if isinstance(state, dict):
                missing, unexpected = self._model.load_state_dict(state, strict=False)
                if missing:
                    log.info("OI weights partial load — missing keys: %d", len(missing))
                if unexpected:
                    log.info("OI weights partial load — unexpected keys: %d", len(unexpected))
            self._model.eval()
        except Exception as exc:
            self.available = False
            self._load_error = f"failed to load OI weights ({self.weights_path}): {exc}"
            log.warning("OI-pretrained detector unavailable (%s)", exc)

    def _map_label(self, phrase: str) -> str:
        mapped = map_oi_label_to_household(phrase)
        if mapped != phrase.strip():
            return mapped
        return super()._map_label(phrase)
