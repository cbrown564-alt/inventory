"""Grounding DINO open-vocabulary detector (Apache-2.0, ML-E10).

High-recall stage-1 proposals for the build pipeline. Pair with
``verify_detections`` to drop unmatched-label noise (docs/22 §5.1).
Requires ``transformers`` and ``torch``; weights download on first run.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .detect import HOUSEHOLD_VOCAB, Detection

log = logging.getLogger(__name__)

DEFAULT_MODEL = "IDEA-Research/grounding-dino-tiny"
_VOCAB_SET = frozenset(HOUSEHOLD_VOCAB)


def _phrase_prompt(vocab: list[str]) -> str:
    return ". ".join(v.lower().strip() for v in vocab if v.strip()) + "."


def _norm_label(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def verify_detections(detections: list[Detection]) -> list[Detection]:
    """Cheap verify: keep only labels in the household vocabulary."""
    kept: list[Detection] = []
    for det in detections:
        label = det.label
        if label in _VOCAB_SET:
            kept.append(det)
            continue
        norm = _norm_label(label)
        if any(_norm_label(v) == norm for v in HOUSEHOLD_VOCAB):
            kept.append(det)
    dropped = len(detections) - len(kept)
    if dropped:
        log.debug("ML-E10 verify dropped %d/%d unmatched labels",
                  dropped, len(detections))
    return kept


class GroundingDinoDetector:
    """Lazy-loading Grounding DINO wrapper matching ``Detector.detect`` shape."""

    mode = "text"
    backend = "gdino"

    def __init__(
        self,
        vocab: Optional[list[str]] = None,
        conf: float = 0.25,
        device: str | None = None,
        model_id: str = DEFAULT_MODEL,
        verify: bool = True,
    ):
        self.vocab = vocab or HOUSEHOLD_VOCAB
        self.conf = conf
        self.device = device
        self.model_id = model_id
        self.verify = verify
        self.model_name = model_id
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
            threshold=self.conf,
            text_threshold=self.conf,
            target_sizes=target_sizes,
        )[0]

        dets: list[Detection] = []
        boxes = results.get("boxes")
        scores = results.get("scores")
        labels = results.get("text_labels") or results.get("labels") or []
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

        if self.verify:
            dets = verify_detections(dets)

        if crops_dir is not None and dets:
            crops_dir.mkdir(parents=True, exist_ok=True)
            for i, det in enumerate(dets):
                x1, y1, x2, y2 = det.box
                if (x2 - x1) <= 40 or (y2 - y1) <= 40:
                    continue
                pad_x, pad_y = (x2 - x1) // 10, (y2 - y1) // 10
                crop = image.crop((max(0, x1 - pad_x), max(0, y1 - pad_y),
                                   min(image.width, x2 + pad_x),
                                   min(image.height, y2 + pad_y)))
                out = (crops_dir /
                       f"{image_path.stem}_d{i:02d}_{det.label.replace(' ', '-')}.jpg")
                crop.convert("RGB").save(out, quality=90)
                det.crop_path = str(out)
        return dets

    def detect_queries(self, image_path: Path, queries: list[str],
                       crops_dir: Path | None = None,
                       stem_suffix: str = "") -> list[Detection]:
        """Item-conditioned grounding via a temporary vocabulary swap."""
        if not queries:
            return []
        previous = list(self.vocab)
        try:
            self.vocab = list(dict.fromkeys(queries))
            self._label_map = {_norm_label(v): v for v in self.vocab}
            return self.detect(image_path, crops_dir=crops_dir)
        finally:
            self.vocab = previous
            self._label_map = {_norm_label(v): v for v in self.vocab}
