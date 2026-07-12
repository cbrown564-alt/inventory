"""Map YOLOE detection labels to InventoryFlex gold item names.

Bootstrap bbox labelling and detection eval share gold names but need different
strictness: eval recall should stay permissive; bbox bootstrap must reject
surface items and short-token fuzzy false positives (e.g. door~floor).
"""

from __future__ import annotations

import difflib
from typing import Literal

MatchMode = Literal["eval", "bootstrap"]

# Whole-room surfaces / finishes — not valid bbox gold (fixture-level items only).
BOOTSTRAP_SKIP_GOLD = frozenset({
    "ceiling",
    "walls",
    "laminate flooring",
    "tiled flooring",
    "tiled walls",
    "skirting boards",
})

# Prefer these gold names when the detector emits a given label (checked first).
DET_GOLD_PREFER: dict[str, tuple[str, ...]] = {
    "smoke alarm": ("smoke alarm",),
    "ceiling light": ("recessed spotlights", "pendant light fittings"),
    "light fitting": ("recessed spotlights", "pendant light fittings"),
    "lamp": ("pendant light fittings",),
    "bathtub": ("bath",),
    "refrigerator": ("fridge freezer",),
    "stove": ("oven", "induction hob"),
    "microwave": ("microwave",),
    "washing machine": ("washing machine",),
    "dishwasher": ("dishwasher",),
    "blinds": ("roller blinds",),
    "chair": ("bar chairs", "dining chairs", "armchair"),
    "dining table": ("dining table",),
    "cabinet": ("kitchen units", "utility cupboard", "mirrored cabinet", "medicine cabinet"),
    "mirror": ("mirror", "mirrored cabinet", "medicine cabinet"),
    "sink": ("sink",),
    "toilet": ("toilet",),
    "tap": ("sink",),
    "door": ("balcony door", "utility cupboard"),
    "window": ("window",),
    "towel rail": ("heated towel rail",),
    "rug": ("floor rug",),
    "oven": ("oven",),
    "kettle": ("kitchen contents",),
    "sofa": ("sofa",),
    "coffee table": ("coffee table",),
    "picture frame": ("canvas picture",),
    "painting": ("canvas picture",),
    "hob": ("induction hob",),
    "extractor hood": ("extractor hood",),
}

# Never link this detection label to this gold item name.
DET_GOLD_BLOCK: frozenset[tuple[str, str]] = frozenset({
    ("ceiling light", "ceiling"),
    ("light fitting", "ceiling"),
    ("smoke alarm", "ceiling"),
    ("lamp", "ceiling"),
    ("door", "laminate flooring"),
    ("door", "tiled flooring"),
    ("door", "floor rug"),
    ("window", "balcony door"),
    ("kettle", "sofa"),
    ("kettle", "armchair"),
    ("kettle", "coffee table"),
    ("kettle", "dining table"),
    ("kettle", "bar chairs"),
    ("shower", "bath"),
    ("mirror", "kitchen units"),
    ("mirror", "worktop"),
    ("cabinet", "mirror"),
    ("refrigerator", "dishwasher"),
    ("dishwasher", "washing machine"),
    ("stove", "microwave"),
    ("microwave", "oven"),
    ("washing machine", "oven"),
    ("sink", "microwave"),
    ("sink", "washing machine"),
    ("chair", "sofa"),
    ("chair", "dining table"),
    ("bathtub", "shower screen"),
    # Crop-grounding false positives (substring / fuzzy stem collisions).
    ("bed", "bedside lamps"),
    ("bed", "bedside lamp"),
    ("coffee table", "dining table"),
    ("dining table", "coffee table"),
    ("lamp", "smoke alarm"),
    ("toilet", "towel radiator"),
    ("toilet", "radiator"),
    ("painting", "dining table"),
    ("picture frame", "dining table"),
})

_DEFAULT_THRESHOLDS: dict[MatchMode, float] = {
    "eval": 0.6,
    "bootstrap": 0.75,
}


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def match_score(det_label: str, gold: dict) -> float:
    """Best similarity between a detector label and a gold name/aliases."""
    det_n = _norm(det_label)
    best = 0.0
    for candidate in [gold["name"], *gold.get("aliases", [])]:
        c_n = _norm(candidate)
        if not c_n:
            continue
        if c_n in det_n or det_n in c_n:
            shorter, longer = sorted((c_n, det_n), key=len)
            score = 0.9 + 0.1 * (len(shorter) / len(longer))
        else:
            score = difflib.SequenceMatcher(None, det_n, c_n).ratio()
            # Short-token fuzzy false positives (door~floor, tap~bathtub).
            if max(len(det_n), len(c_n)) <= 5 and score < 0.85:
                score = min(score, 0.55)
        best = max(best, score)
    return best


def _blocked(det_label: str, gold_name: str) -> bool:
    return (_norm(det_label), _norm(gold_name)) in DET_GOLD_BLOCK


def gold_for_detection(
        det_label: str,
        gold_items: list[dict],
        *,
        mode: MatchMode = "bootstrap",
        threshold: float | None = None,
        notable_only: bool = True,
) -> tuple[dict, float] | None:
    """Return (gold_item, score) for a detector label, or None."""
    if threshold is None:
        threshold = _DEFAULT_THRESHOLDS[mode]
    by_name = {g["name"]: g for g in gold_items}
    det_n = _norm(det_label)

    prefer = DET_GOLD_PREFER.get(det_n, ())
    prefer_threshold = 0.6 if mode == "eval" else 0.65
    for name in prefer:
        gold = by_name.get(name)
        if gold is None:
            continue
        if notable_only and not gold.get("notable", True):
            continue
        if mode == "bootstrap" and name in BOOTSTRAP_SKIP_GOLD:
            continue
        if _blocked(det_label, name):
            continue
        if mode == "bootstrap":
            # Explicit inventory routes — no fuzzy confirmation needed.
            return gold, 1.0
        score = match_score(det_label, gold)
        if score >= prefer_threshold:
            return gold, score

    best: tuple[float, dict] | None = None
    for gold in gold_items:
        if notable_only and not gold.get("notable", True):
            continue
        name = gold["name"]
        if mode == "bootstrap" and name in BOOTSTRAP_SKIP_GOLD:
            continue
        if _blocked(det_label, name):
            continue
        score = match_score(det_label, gold)
        if score >= threshold and (best is None or score > best[0]):
            best = (score, gold)
    if best is None:
        return None
    return best[1], best[0]


def label_matches_gold(det_label: str, gold: dict, threshold: float = 0.6) -> bool:
    """Eval-mode check: does this detection label match one gold item?"""
    return match_score(det_label, gold) >= threshold
