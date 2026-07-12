"""ML-E2: VLM seam refine ±30 s windows (docs/22 §5.1).

Refines interior segment boundaries on live walkthrough videos where cheap
segmentation can land a few seconds inside the previous room. Falls back to
baseline segments when the VLM is unavailable or the refine call fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .ml_api import vlm_api_available
from .segment import Segment, SampledFrame, segment_frames, sample_strip

log = logging.getLogger(__name__)

REFINE_WINDOW_S = 30.0
REFINE_EVERY_S = 1.0


@dataclass
class BoundaryRefine:
    index: int
    room_before: str
    room_after: str
    baseline_s: float
    refined_s: float
    delta_s: float
    mode: str


def seam_refine_available(model: str) -> bool:
    return vlm_api_available(model)


def interior_boundaries(segments: list[Segment]) -> list[tuple[int, float, str, str]]:
    """[(index, time_s, room_before, room_after), ...] for each interior seam."""
    out: list[tuple[int, float, str, str]] = []
    for i in range(1, len(segments)):
        out.append((
            i,
            segments[i].start_s,
            segments[i - 1].room,
            segments[i].room,
        ))
    return out


def _merge_segments(segments: list[Segment], duration: float) -> list[Segment]:
    merged: list[Segment] = []
    for s in segments:
        if merged and merged[-1].room.strip().lower() == s.room.strip().lower():
            merged[-1].end_s = s.end_s
        else:
            merged.append(Segment(s.room, s.start_s, s.end_s))
    if merged:
        merged[0].start_s = 0.0
        merged[-1].end_s = duration
    return merged


def refine_segment_boundaries(
        video: Path,
        segments: list[Segment],
        *,
        model: str,
        window_s: float = REFINE_WINDOW_S,
        every_s: float = REFINE_EVERY_S,
) -> tuple[list[Segment], list[BoundaryRefine], dict]:
    """VLM refine: 1 s strip in ±window around each interior seam."""
    from .segment import video_duration_s

    duration = video_duration_s(video)
    full_strip = sample_strip(video, every_s=every_s, width=448)
    by_t = {round(f.t_s, 2): f for f in full_strip}

    refined = [Segment(s.room, s.start_s, s.end_s) for s in segments]
    logs: list[BoundaryRefine] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    api_calls = 0

    for idx, baseline_s, before, after in interior_boundaries(segments):
        lo = max(0.0, baseline_s - window_s)
        hi = min(duration, baseline_s + window_s)
        window_frames = [f for t, f in sorted(by_t.items()) if lo <= t <= hi]
        if len(window_frames) < 3:
            continue
        local_duration = hi - lo
        local_frames = [
            SampledFrame(t_s=round(f.t_s - lo, 2), jpeg=f.jpeg)
            for f in window_frames
        ]
        local_segs, meta = segment_frames(
            local_frames, local_duration, every_s, model=model,
        )
        usage["input_tokens"] += meta["usage"]["input_tokens"]
        usage["output_tokens"] += meta["usage"]["output_tokens"]
        api_calls += meta["api_calls"]

        local_bounds = sorted(
            {round(s.start_s, 2) for s in local_segs[1:]}
            if len(local_segs) > 1 else []
        )
        if not local_bounds:
            continue
        local_pick = min(local_bounds, key=lambda b: abs((lo + b) - baseline_s))
        target = round(lo + local_pick, 2)
        refined[idx].start_s = target
        refined[idx - 1].end_s = target
        logs.append(BoundaryRefine(
            index=idx,
            room_before=before,
            room_after=after,
            baseline_s=baseline_s,
            refined_s=target,
            delta_s=round(target - baseline_s, 2),
            mode=f"vlm-{model}",
        ))

    merged = _merge_segments(refined, duration)
    return merged, logs, {
        "api_calls": api_calls,
        "usage": usage,
        "every_s": every_s,
        "model": model,
        "boundaries_refined": len(logs),
    }


def try_refine_segments(
        video: Path,
        segments: list[Segment],
        *,
        model: str,
        window_s: float = REFINE_WINDOW_S,
) -> tuple[list[Segment], dict]:
    """Refine when the VLM is reachable; otherwise return baseline unchanged."""
    if len(segments) <= 1:
        return segments, {"enabled": False, "reason": "single segment"}
    if not seam_refine_available(model):
        log.info("ML-E2 seam refine skipped — no VLM credentials for %s", model)
        return segments, {"enabled": False, "reason": "no api key"}
    try:
        refined, logs, meta = refine_segment_boundaries(
            video, segments, model=model, window_s=window_s,
        )
        meta["enabled"] = True
        meta["refinements"] = [log.__dict__ for log in logs]
        if logs:
            log.info("ML-E2 refined %d segment seam(s) on %s",
                     len(logs), video.name)
        return refined, meta
    except Exception as exc:
        log.warning("ML-E2 seam refine failed (%s) — using baseline segments", exc)
        return segments, {"enabled": False, "reason": str(exc)}
