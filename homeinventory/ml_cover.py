"""ML-E8: VLM cover rerank (production wiring, docs/22 §5.1).

Classical E5 cover scoring proposes a top-k shortlist per room; a bounded VLM
call disposes rank-1. Falls back to classical E5+E7 when credentials are
missing or the call fails. Results are cached by frame content sha256.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from .curate import (
    _COVER_SLOT_QUALITY,
    _assign_rank_one,
    _cover_metrics,
    _percentile,
    cover_score,
    frame_quality,
    override_key,
)
from .ml_api import vlm_api_available
from .schema import Photo

log = logging.getLogger(__name__)

TOP_K = 6
CACHE_FILE = "cover_rerank_cache.json"
_COST_PER_CALL_USD = 0.012
_COST_PER_IMAGE_USD = 0.001


def should_enable_vlm_cover(*, no_vlm_cover: bool, model: str) -> bool:
    """Default ON when API keys exist; ``--no-vlm-cover`` forces OFF."""
    if no_vlm_cover:
        return False
    return vlm_api_available(model)


def estimate_cover_rerank_cost_usd(*, n_rooms: int, images_per_room: int = TOP_K) -> dict:
    calls = n_rooms
    images = n_rooms * images_per_room
    usd = calls * _COST_PER_CALL_USD + images * _COST_PER_IMAGE_USD
    return {
        "n_room_calls": calls,
        "n_images": images,
        "estimate_usd": round(usd, 4),
        "method": (
            f"~${_COST_PER_CALL_USD}/call + ${_COST_PER_IMAGE_USD}/image "
            "(Jul 2026 list-price placeholder)"
        ),
    }


def _full_path(capture_dir: Path, photo: Photo) -> Path:
    p = Path(photo.path)
    return p if p.is_absolute() else capture_dir / p


def _frame_metrics(photos: list[Photo], capture_dir: Path) -> dict[str, dict]:
    metrics: dict[str, dict] = {}
    for photo in photos:
        path = _full_path(capture_dir, photo)
        quality, _thumb, establishing = frame_quality(path)
        sh, smooth, cbr, clipped = _cover_metrics(path)
        metrics[photo.id] = {
            "sharpness": sh,
            "smooth": smooth,
            "cbr": cbr,
            "clipped": clipped,
            "establishing": establishing,
            "quality": quality,
            "cover": cover_score(establishing, cbr),
        }
    return metrics


def classical_shortlist(
        photos: list[Photo],
        metrics: dict[str, dict],
        *,
        k: int = TOP_K,
) -> list[Photo]:
    """Top-k by E5 cover score plus cover-anchor frames (ML-E8 eval pattern)."""
    video_frames = [p for p in photos if p.source_video]
    if not video_frames:
        return []

    def sort_key(p: Photo) -> float:
        m = metrics[p.id]
        return cover_score(m["establishing"], m["cbr"])

    ranked = sorted(video_frames, key=sort_key, reverse=True)
    shortlist = ranked[: min(k, len(ranked))]
    present = {p.id for p in shortlist}
    for photo in video_frames:
        if photo.cover_anchor and photo.id not in present:
            shortlist.append(photo)
            present.add(photo.id)
    return shortlist


def _cache_key(room_name: str, shortlist: list[Photo]) -> str:
    shas = sorted(p.sha256 for p in shortlist if p.sha256)
    digest = hashlib.sha256("|".join(shas).encode()).hexdigest()[:16]
    return f"{room_name}:{digest}"


def _load_cache(work_dir: Path) -> dict:
    path = work_dir / CACHE_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(work_dir: Path, cache: dict) -> None:
    path = work_dir / CACHE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def vlm_pick_cover(
        room_name: str,
        shortlist: list[Photo],
        paths: dict[str, Path],
        *,
        model: str,
) -> tuple[Photo, str, dict]:
    """One VLM call: pick best establishing frame from the shortlist."""
    labels = "\n".join(
        f"{i + 1}. {paths[p.id].name}" for i, p in enumerate(shortlist)
    )
    prompt = (
        f"Room: {room_name}.\n"
        "Pick the best establishing cover photo (rank 1) from the strip. "
        "Prefer wide room overview with key fixtures visible; avoid "
        "close-ups, motion blur, and doorway edge frames.\n"
        f"Candidates:\n{labels}\n"
        'Reply JSON only: {"pick": <1-based index>, "reason": "..."}'
    )
    content: list[dict] = [{"type": "text", "text": prompt}]
    for photo in shortlist:
        data = base64.b64encode(paths[photo.id].read_bytes()).decode()
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": data,
            },
        })

    usage: dict = {}
    if model.startswith("claude"):
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": content}],
        )
        u = getattr(response, "usage", None)
        if u is not None:
            usage["input_tokens"] = int(getattr(u, "input_tokens", 0) or 0)
            usage["output_tokens"] = int(getattr(u, "output_tokens", 0) or 0)
        texts = [b.text for b in response.content if b.type == "text"]
        raw = texts[-1] if texts else "{}"
        source = f"vlm-{model}"
    else:
        from .describe import OpenAICompatBackend

        openai_content: list[dict] = [{"type": "text", "text": prompt}]
        for photo in shortlist:
            data = base64.b64encode(paths[photo.id].read_bytes()).decode()
            openai_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{data}"},
            })
        backend = OpenAICompatBackend(model=model)
        resp = backend._post({
            "model": backend.model,
            "messages": [{"role": "user", "content": openai_content}],
            "response_format": {"type": "json_object"},
        })
        u = resp.get("usage") or {}
        usage["input_tokens"] = int(u.get("prompt_tokens") or 0)
        usage["output_tokens"] = int(u.get("completion_tokens") or 0)
        raw = resp["choices"][0]["message"]["content"]
        source = f"vlm-{model}"

    try:
        pick_idx = int(json.loads(raw).get("pick", 1))
    except (json.JSONDecodeError, TypeError, ValueError):
        pick_idx = 1
    pick_idx = max(1, min(pick_idx, len(shortlist)))
    return shortlist[pick_idx - 1], source, usage


def apply_vlm_cover_rerank(
        rooms: dict[str, list[Photo]],
        capture_dir: Path,
        work_dir: Path,
        overrides: dict[str, str] | None = None,
        *,
        model: str,
) -> dict[str, dict]:
    """Rerank hero rank-1 per room; returns audit log keyed by room name."""
    overrides = overrides or {}
    cache = _load_cache(work_dir)
    audit: dict[str, dict] = {}
    usage_total = {"input_tokens": 0, "output_tokens": 0}

    for room_name, photos in rooms.items():
        video_frames = [
            p for p in photos
            if p.source_video and overrides.get(override_key(p)) != "hidden"
        ]
        if len(video_frames) < 2:
            continue

        metrics = _frame_metrics(video_frames, capture_dir)
        shortlist = classical_shortlist(video_frames, metrics)
        if len(shortlist) < 2:
            continue

        paths = {p.id: _full_path(capture_dir, p) for p in shortlist}
        ck = _cache_key(room_name, shortlist)
        cached = cache.get(ck)
        if cached and cached.get("pick_id") in {p.id for p in shortlist}:
            pick = next(p for p in shortlist if p.id == cached["pick_id"])
            source = cached.get("source", "cache")
            usage: dict = cached.get("usage") or {}
        else:
            try:
                pick, source, usage = vlm_pick_cover(
                    room_name, shortlist, paths, model=model,
                )
                cache[ck] = {
                    "room": room_name,
                    "pick_id": pick.id,
                    "source": source,
                    "usage": usage,
                }
            except Exception as exc:
                log.warning("ML-E8 cover rerank failed for %s (%s) — classical E5",
                            room_name, exc)
                sharpnesses = [metrics[p.id]["sharpness"] for p in video_frames]
                room_median = _percentile(sharpnesses, 0.5)
                room_p25 = _percentile(sharpnesses, 0.25)
                del room_median, room_p25  # classical pick uses cover score only
                pick = max(
                    video_frames,
                    key=lambda p: cover_score(
                        metrics[p.id]["establishing"], metrics[p.id]["cbr"]),
                )
                source = "classical-fallback"
                usage = {"error": str(exc)}

        current = next((p for p in photos if p.hero == 1), None)
        if current is not pick:
            if pick.hero is None:
                pick.hero = max((p.hero or 0 for p in photos), default=0) + 1
            _assign_rank_one(photos, pick)
            log.info("ML-E8 cover rerank %s: %s (%s)", room_name, pick.id, source)

        usage_total["input_tokens"] += int(usage.get("input_tokens") or 0)
        usage_total["output_tokens"] += int(usage.get("output_tokens") or 0)
        audit[room_name] = {
            "pick_id": pick.id,
            "source": source,
            "shortlist_ids": [p.id for p in shortlist],
            "usage": usage,
        }

    if cache:
        _save_cache(work_dir, cache)
    n_rooms = len(audit)
    if n_rooms:
        summary = {
            "experiment": "ML-E8",
            "model": model,
            "rooms_reranked": n_rooms,
            "usage": usage_total,
            "cost_estimate": estimate_cover_rerank_cost_usd(n_rooms=n_rooms),
        }
        audit["_summary"] = summary
        log_path = work_dir / "cover_rerank_audit.json"
        log_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return audit
