"""Eval-only Grounding DINO open-vocabulary detector (Apache-2.0).

Not wired into the build pipeline — use ``evals/eval_detect_gdino.py`` to
benchmark against YOLOE text mode. Requires ``transformers`` and ``torch``;
weights download from Hugging Face on first run (``IDEA-Research/grounding-dino-tiny``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from homeinventory.detect import HOUSEHOLD_VOCAB, Detection

log = logging.getLogger(__name__)

DEFAULT_MODEL = "IDEA-Research/grounding-dino-tiny"


def _phrase_prompt(vocab: list[str]) -> str:
    """Grounding DINO expects lower-case phrases separated by ``.``."""
    return ". ".join(v.lower().strip() for v in vocab if v.strip()) + "."


def _norm_label(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


class GroundingDinoDetector:
    """Lazy-loading Grounding DINO wrapper matching ``Detector.detect`` shape."""

    def __init__(
        self,
        vocab: Optional[list[str]] = None,
        conf: float = 0.25,
        device: str | None = None,
        model_id: str = DEFAULT_MODEL,
    ):
        self.vocab = vocab or HOUSEHOLD_VOCAB
        self.conf = conf
        self.device = device
        self.model_id = model_id
        self._model = None
        self._processor = None
        self.available = True
        self._load_error: Optional[str] = None
        self._label_map = {_norm_label(v): v for v in self.vocab}

    def _load(self) -> None:
        if self._model is not None or not self.available:
            return
        try:
            import torch
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
                self.model_id,
            )
            if self.device:
                self._model = self._model.to(self.device)
            elif torch.cuda.is_available():
                self._model = self._model.to("cuda")
            self._model.eval()
        except Exception as exc:
            self.available = False
            self._load_error = str(exc)
            log.warning("Grounding DINO unavailable (%s)", exc)

    def _map_label(self, phrase: str) -> str:
        key = _norm_label(phrase)
        if key in self._label_map:
            return self._label_map[key]
        for norm, original in self._label_map.items():
            if norm in key or key in norm:
                return original
        return phrase.strip()

    def detect(self, image_path: Path, crops_dir: Path | None = None) -> list[Detection]:
        self._load()
        if not self.available:
            return []
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        text = _phrase_prompt(self.vocab)
        inputs = self._processor(images=image, text=text, return_tensors="pt")
        dev = next(self._model.parameters()).device
        inputs = {k: v.to(dev) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)

        target_sizes = torch.tensor([image.size[::-1]], device=dev)
        results = self._processor.post_process_grounded_object_detection(
            outputs,
            inputs["input_ids"],
            box_threshold=self.conf,
            text_threshold=self.conf,
            target_sizes=target_sizes,
        )[0]

        dets: list[Detection] = []
        boxes = results.get("boxes")
        scores = results.get("scores")
        labels = results.get("labels") or results.get("text_labels") or []
        if boxes is None or scores is None:
            return dets

        for box, score, label in zip(boxes, scores, labels):
            x1, y1, x2, y2 = (int(v) for v in box.tolist())
            if (x2 - x1) < 20 or (y2 - y1) < 20:
                continue
            mapped = self._map_label(str(label))
            dets.append(
                Detection(
                    label=mapped,
                    confidence=float(score),
                    box=(x1, y1, x2, y2),
                ),
            )
        return dets
