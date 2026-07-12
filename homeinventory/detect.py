"""Open-vocabulary object detection with YOLOE (Ultralytics).

The detector's job in this pipeline is grounding, not description:
  * crops of detected items become report thumbnails,
  * the per-photo detection list is passed to the describe backend as a hint so
    the VLM doesn't silently skip visible items,
  * in the fully-offline configuration it is the only source of item names.

Two inference modes are supported:

* ``text`` (default) — ``yoloe-*-seg.pt`` with ``HOUSEHOLD_VOCAB`` baked in via
  ``set_classes``. Only the ~40 household classes are searched; fast and tuned
  for inventory coverage checks.
* ``prompt_free`` — ``yoloe-*-seg-pf.pt`` with Ultralytics' built-in LVIS +
  Objects365 vocabulary (~1,200 categories). Broader recall on generic objects
  but noisier labels and no inventory-specific terms (e.g. "towel rail").

Item-conditioned grounding (``build_item_queries`` / ``detect_queries``) builds
a short query list from a schedule item's name and aliases, then re-runs text
mode against that item's cited photos. Matching logic in ``merge`` scores those
boxes (and existing household detections) without loosening the global matcher.

If torch/ultralytics or the model weights are unavailable the pipeline degrades
gracefully to whole-image mode (no crops, no hints) rather than failing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

log = logging.getLogger(__name__)

DetectMode = Literal["text", "prompt_free"]

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
    # InventoryFlex / UK schedule terms missing from base COCO-like set
    "hob", "extractor hood", "bar stool", "patio door", "medicine cabinet",
    # Structural and finish items: broad boxes are still useful context for
    # the report rail, even when the detector cannot isolate every component.
    "staircase", "stairwell", "banister", "handrail", "newel post",
    "skirting board", "flooring", "ceiling", "wall", "window sill",
    "door handle", "light switch", "power socket",
]

# Schedule wording → detector text queries. Keys are normalised item names
# (or distinctive substrings). Values must be phrases YOLOE can ground —
# prefer HOUSEHOLD_VOCAB terms. Used by item-conditioned grounding only.
ITEM_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "skirting boards": ("skirting board",),
    "skirting board": ("skirting board",),
    "laminate flooring": ("flooring",),
    "tiled flooring": ("flooring",),
    "flooring": ("flooring",),
    "pendant light fittings": ("ceiling light", "light fitting", "lamp"),
    "pendant light fitting": ("ceiling light", "light fitting", "lamp"),
    "recessed spotlights": ("ceiling light", "light fitting"),
    "ceiling lights": ("ceiling light", "light fitting"),
    "ceiling light": ("ceiling light", "light fitting"),
    "staircase": ("staircase", "stairwell", "banister", "handrail"),
    "stairwell": ("staircase", "stairwell", "banister", "handrail"),
    "stairs": ("staircase", "stairwell"),
    "canvas wall art": ("picture frame", "painting"),
    "canvas picture": ("picture frame", "painting"),
    "wall art": ("picture frame", "painting"),
    "picture": ("picture frame", "painting"),
    "heated towel rail": ("towel rail",),
    "towel rail": ("towel rail",),
    "fridge freezer": ("refrigerator",),
    "fridge": ("refrigerator",),
    "induction hob": ("hob", "stove"),
    "bath": ("bathtub",),
    "roller blinds": ("blinds",),
    "roller blind": ("blinds",),
    "bedside lamps": ("lamp",),
    "bedside lamp": ("lamp",),
    "table lamps": ("lamp",),
    "table lamp": ("lamp",),
    "smoke alarm": ("smoke alarm",),
    "smoke heat alarm": ("smoke alarm",),
    "floor rug": ("rug",),
    "balcony door": ("patio door", "door"),
    "patio door": ("patio door", "door"),
    "kitchen units": ("cabinet",),
    "utility cupboard": ("cabinet", "door"),
    "mirrored cabinet": ("medicine cabinet", "mirror", "cabinet"),
    "medicine cabinet": ("medicine cabinet", "mirror", "cabinet"),
    "bar chairs": ("bar stool", "chair"),
    "dining chairs": ("chair",),
    "walls": ("wall",),
    "wall": ("wall",),
}

_VOCAB_SET = frozenset(HOUSEHOLD_VOCAB)
_DESCRIPTOR_QUERY_TOKENS = frozenset(
    "white cream grey gray black brown beige taupe magnolia oak wood wooden "
    "wood-effect woodeffect effect laminate vinyl engineered painted emulsion "
    "finish finished colour color light dark upper lower left right interior "
    "exterior internal external single double tall round large small mounted "
    "wall-mounted wallmounted upvc metal silver stainless steel brushed gloss "
    "matte fabric upholstered marble ceramic section area side front back main "
    "primary fitted built-in builtin built timber greyed".split()
)


def _norm_query(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", s.strip().lower())
    s = re.sub(r"\bx\s*\d+\b", " ", s)
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def build_item_queries(name: str,
                       aliases: Iterable[str] | None = None) -> list[str]:
    """Build YOLOE text queries for grounding one schedule item.

    Starts from the item name and aliases, expands known schedule↔detector
    synonyms, then keeps phrases that overlap ``HOUSEHOLD_VOCAB`` so we do not
    invent classes the text-prompt model was never asked to find.
    """
    seeds: list[str] = []
    for raw in (name, *(aliases or ())):
        n = _norm_query(raw)
        if n:
            seeds.append(n)

    queries: list[str] = []

    def add(q: str) -> None:
        q = _norm_query(q)
        if q and q not in queries:
            queries.append(q)

    for seed in seeds:
        add(seed)
        if seed in ITEM_QUERY_ALIASES:
            for q in ITEM_QUERY_ALIASES[seed]:
                add(q)
        else:
            for key, vals in ITEM_QUERY_ALIASES.items():
                if key in seed or seed in key:
                    for q in vals:
                        add(q)

        tokens = [t for t in seed.split() if t not in _DESCRIPTOR_QUERY_TOKENS]
        if tokens:
            add(" ".join(tokens))
        for i, tok in enumerate(tokens):
            add(tok)
            # Plural schedule wording ("lamps", "blinds") → vocab singular.
            if tok.endswith("s") and len(tok) > 3:
                stem = tok[:-1]
                if stem in _VOCAB_SET:
                    add(stem)
            if i + 1 < len(tokens):
                add(f"{tok} {tokens[i + 1]}")

    # Prefer detector-vocab phrases; keep non-vocab seeds only when short
    # enough to be useful text prompts (YOLOE accepts free phrases).
    ranked: list[str] = []
    for q in queries:
        if q in _VOCAB_SET:
            ranked.append(q)
    for q in queries:
        if q not in ranked and (q in _VOCAB_SET or len(q.split()) <= 3):
            ranked.append(q)
    return ranked[:8]

DEFAULT_MODEL_TEXT = "yoloe-11s-seg.pt"       # smallest text-prompt YOLOE; fine on CPU
DEFAULT_MODEL_PROMPT_FREE = "yoloe-11s-seg-pf.pt"
DEFAULT_MODEL = DEFAULT_MODEL_TEXT


def default_model(mode: DetectMode = "text") -> str:
    """Return the default weight file for a detection mode."""
    return DEFAULT_MODEL_PROMPT_FREE if mode == "prompt_free" else DEFAULT_MODEL_TEXT


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]   # x1, y1, x2, y2 in pixels
    crop_path: Optional[str] = None


class Detector:
    """Lazy-loading YOLOE wrapper; `available` is False if the stack is missing."""

    def __init__(self, model_name: str | None = None,
                 vocab: Optional[list[str]] = None, conf: float = 0.25,
                 mode: DetectMode = "text", device: str | None = None):
        self.mode = mode
        self.model_name = model_name or default_model(mode)
        self.vocab = vocab or HOUSEHOLD_VOCAB
        self.conf = conf
        self.device = device
        self._model = None
        self.available = True
        self._load_error: Optional[str] = None

    def _load(self):
        if self._model is not None or not self.available:
            return
        try:
            from ultralytics import YOLOE
            self._model = YOLOE(self.model_name)
            if self.mode == "text":
                self._model.set_classes(self.vocab, self._model.get_text_pe(self.vocab))
            elif hasattr(self._model.model.model[-1], "lrpc"):
                log.debug("YOLOE prompt-free model loaded (%s)", self.model_name)
            else:
                log.warning(
                    "model %s looks like a text-prompt weight but mode=prompt_free; "
                    "switching to text mode", self.model_name,
                )
                self.mode = "text"
                self._model.set_classes(self.vocab, self._model.get_text_pe(self.vocab))
        except Exception as e:  # missing torch, no weights, no network...
            self.available = False
            self._load_error = str(e)
            log.warning("YOLOE unavailable (%s); continuing in whole-image mode", e)

    def detect(self, image_path: Path, crops_dir: Optional[Path] = None) -> list[Detection]:
        self._load()
        if not self.available:
            return []
        kwargs = {"conf": self.conf, "verbose": False}
        if self.device:
            kwargs["device"] = self.device
        results = self._model.predict(str(image_path), **kwargs)
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

    def _set_text_classes(self, vocab: list[str]) -> None:
        """Bake *vocab* into the loaded text-prompt model (no-op otherwise)."""
        if self._model is None or self.mode != "text":
            return
        self.vocab = list(vocab)
        self._model.set_classes(self.vocab, self._model.get_text_pe(self.vocab))

    def detect_queries(self, image_path: Path, queries: list[str],
                       crops_dir: Optional[Path] = None,
                       stem_suffix: str = "") -> list[Detection]:
        """Run text-prompt detection for one item's query list.

        Temporarily replaces the household vocabulary with *queries*, then
        restores it. Prompt-free mode and an unavailable stack return [].
        """
        self._load()
        if not self.available or self.mode != "text":
            return []
        clean = list(dict.fromkeys(_norm_query(q) for q in queries if _norm_query(q)))
        if not clean:
            return []
        previous = list(self.vocab)
        try:
            self._set_text_classes(clean)
            dets = self.detect(image_path, crops_dir=None)
            if crops_dir is None:
                return dets
            from PIL import Image
            crops_dir.mkdir(parents=True, exist_ok=True)
            crop_img = Image.open(image_path)
            tag = stem_suffix or "g"
            out: list[Detection] = []
            for i, det in enumerate(dets):
                x1, y1, x2, y2 = det.box
                if (x2 - x1) <= 40 or (y2 - y1) <= 40:
                    out.append(det)
                    continue
                pad_x, pad_y = (x2 - x1) // 10, (y2 - y1) // 10
                crop = crop_img.crop((max(0, x1 - pad_x), max(0, y1 - pad_y),
                                      min(crop_img.width, x2 + pad_x),
                                      min(crop_img.height, y2 + pad_y)))
                path = (crops_dir /
                        f"{image_path.stem}_{tag}{i:02d}_{det.label.replace(' ', '-')}.jpg")
                crop.convert("RGB").save(path, quality=90)
                det.crop_path = str(path)
                out.append(det)
            return out
        finally:
            self._set_text_classes(previous)
