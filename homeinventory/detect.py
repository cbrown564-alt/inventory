"""Open-vocabulary object detection with YOLOE (Ultralytics).

The detector's job in this pipeline is grounding, not description:
  * crops of detected items become report thumbnails,
  * the per-photo detection list is passed to the describe backend as a hint so
    the VLM doesn't silently skip visible items,
  * in the fully-offline configuration it is the only source of item names.

If torch/ultralytics or the model weights are unavailable the pipeline degrades
gracefully to whole-image mode (no crops, no hints) rather than failing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Text-prompt vocabulary for household items of worth. YOLOE's text-prompted
# mode detects exactly these classes; tune freely — it needs no retraining.
HOUSEHOLD_VOCAB = [
    "sofa", "armchair", "chair", "dining table", "coffee table", "desk", "bed",
    "mattress", "wardrobe", "chest of drawers", "bookshelf", "cabinet", "mirror",
    "television", "monitor", "laptop", "speaker", "lamp", "light fitting",
    "ceiling light", "curtains", "blinds", "rug", "carpet", "radiator",
    "refrigerator", "oven", "stove", "microwave", "kettle", "toaster",
    "washing machine", "dishwasher", "vacuum cleaner", "sink", "tap", "toilet",
    "bathtub", "shower", "towel rail", "picture frame", "painting", "clock",
    "plant pot", "bicycle", "smoke alarm", "door", "window",
]

DEFAULT_MODEL = "yoloe-11s-seg.pt"  # smallest YOLOE; fine on CPU


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]   # x1, y1, x2, y2 in pixels
    crop_path: Optional[str] = None


class Detector:
    """Lazy-loading YOLOE wrapper; `available` is False if the stack is missing."""

    def __init__(self, model_name: str = DEFAULT_MODEL,
                 vocab: Optional[list[str]] = None, conf: float = 0.25):
        self.model_name = model_name
        self.vocab = vocab or HOUSEHOLD_VOCAB
        self.conf = conf
        self._model = None
        self.available = True
        self._load_error: Optional[str] = None

    def _load(self):
        if self._model is not None or not self.available:
            return
        try:
            from ultralytics import YOLOE
            self._model = YOLOE(self.model_name)
            self._model.set_classes(self.vocab, self._model.get_text_pe(self.vocab))
        except Exception as e:  # missing torch, no weights, no network...
            self.available = False
            self._load_error = str(e)
            log.warning("YOLOE unavailable (%s); continuing in whole-image mode", e)

    def detect(self, image_path: Path, crops_dir: Optional[Path] = None) -> list[Detection]:
        self._load()
        if not self.available:
            return []
        results = self._model.predict(str(image_path), conf=self.conf, verbose=False)
        dets: list[Detection] = []
        r = results[0]
        names = r.names
        if r.boxes is None:
            return dets
        crop_img = None
        if crops_dir is not None:
            from PIL import Image
            crops_dir.mkdir(parents=True, exist_ok=True)
            crop_img = Image.open(image_path)
        for i, b in enumerate(r.boxes):
            x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
            det = Detection(
                label=names[int(b.cls[0])],
                confidence=float(b.conf[0]),
                box=(x1, y1, x2, y2),
            )
            if crop_img is not None and (x2 - x1) > 40 and (y2 - y1) > 40:
                pad_x, pad_y = (x2 - x1) // 10, (y2 - y1) // 10
                crop = crop_img.crop((max(0, x1 - pad_x), max(0, y1 - pad_y),
                                      min(crop_img.width, x2 + pad_x),
                                      min(crop_img.height, y2 + pad_y)))
                out = crops_dir / f"{image_path.stem}_d{i:02d}_{det.label.replace(' ', '-')}.jpg"
                crop.convert("RGB").save(out, quality=90)
                det.crop_path = str(out)
            dets.append(det)
        return dets
