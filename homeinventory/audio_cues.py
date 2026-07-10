"""Replayable, confidence-bearing narration cues for capture experiments.

The transcript is kept as research evidence.  Production consumers receive
only the small typed cue lists needed for segmentation or hero selection, so
the item describer is never exposed to narration prose.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def _number(value, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def load_audio_cues(path: Path) -> dict:
    """Load and validate one frozen transcript/cue artifact."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("audio cue artifact must be a JSON object")
    source = data.get("source") or {}
    if not isinstance(source, dict) or not str(source.get("video") or "").strip():
        raise ValueError("audio cue artifact requires source.video")
    fps = _number(source.get("fps"), "source.fps")
    if fps <= 0:
        raise ValueError("source.fps must be positive")

    room_cues = []
    for index, raw in enumerate(data.get("room_cues") or []):
        room = str(raw.get("room") or "").strip()
        if not room:
            raise ValueError(f"room_cues[{index}].room is required")
        confidence = _number(raw.get("confidence"),
                             f"room_cues[{index}].confidence")
        if not 0 <= confidence <= 1:
            raise ValueError(f"room_cues[{index}].confidence must be 0..1")
        room_cues.append({"t_s": max(0.0, _number(raw.get("t_s"),
                           f"room_cues[{index}].t_s")),
                          "room": room, "confidence": confidence})

    establishing_cues = []
    for index, raw in enumerate(data.get("establishing_cues") or []):
        start = max(0.0, _number(raw.get("start_s"),
                                f"establishing_cues[{index}].start_s"))
        end = _number(raw.get("end_s"),
                      f"establishing_cues[{index}].end_s")
        room = str(raw.get("room") or "").strip()
        confidence = _number(raw.get("confidence", 1.0),
                             f"establishing_cues[{index}].confidence")
        if not room or end <= start or not 0 <= confidence <= 1:
            raise ValueError(f"invalid establishing_cues[{index}]")
        establishing_cues.append({"start_s": start, "end_s": end,
                                   "room": room, "confidence": confidence,
                                   "source": str(raw.get("source") or "")})

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return {**data,
            "source": {**source, "video": str(source["video"]), "fps": fps},
            "room_cues": sorted(room_cues, key=lambda c: c["t_s"]),
            "establishing_cues": sorted(establishing_cues,
                                         key=lambda c: c["start_s"]),
            "sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def segmentation_hint(cues: dict, start_s: float, end_s: float,
                      min_confidence: float = 0.7) -> str:
    """Plain model-facing room-name hints for one sampled strip."""
    relevant = [c for c in cues.get("room_cues", [])
                if start_s <= c["t_s"] <= end_s
                and c["confidence"] >= min_confidence]
    if not relevant:
        return ""
    lines = [f"- {c['t_s']:.1f}s: {c['room']} ({c['confidence']:.0%} confidence)"
             for c in relevant]
    return ("\nThe recording contains these likely spoken room names. Use them "
            "as hints only. If a hint conflicts with the images, trust the "
            "images:\n" + "\n".join(lines))
