"""Semantic rank-one cover verification with evidence-bound caching."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from .schema import Photo

log = logging.getLogger(__name__)

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "shows_named_room": {"type": "boolean",
                              "description": "True when the image depicts the named room."},
        "is_establishing_view": {"type": "boolean",
                                 "description": "True when the image gives a useful wide overview."},
        "reason": {"type": "string",
                   "description": "Short visible reason for the decision."},
    },
    "required": ["shows_named_room", "is_establishing_view", "reason"],
    "additionalProperties": False,
}


def verification_prompt(room_name: str) -> str:
    return (f"Named room: {room_name}. Check whether this image depicts that "
            "room and gives a useful wide overview. Judge only what is visible.")


def _content(room_name: str, path: Path, provider: str) -> list[dict]:
    encoded = base64.b64encode(path.read_bytes()).decode()
    content = [{"type": "text", "text": verification_prompt(room_name)}]
    if provider == "anthropic":
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": encoded}})
    else:
        content.append({"type": "image_url", "image_url": {
            "url": f"data:image/jpeg;base64,{encoded}"}})
    return content


def verify_cover(room_name: str, path: Path, model: str) -> dict:
    """Return the typed semantic verdict for one proposed rank-one cover."""
    if model.startswith("claude"):
        import anthropic
        response = anthropic.Anthropic().messages.create(
            model=model, max_tokens=300,
            messages=[{"role": "user",
                       "content": _content(room_name, path, "anthropic")}],
            output_config={"format": {"type": "json_schema",
                                      "schema": VERIFY_SCHEMA}},
        )
        text = next(b.text for b in response.content if b.type == "text")
    else:
        from .describe import OpenAICompatBackend
        backend = OpenAICompatBackend(model=model)
        response = backend._post({
            "model": model,
            "messages": [{"role": "user",
                          "content": _content(room_name, path, "openai")}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "cover_verification", "strict": True,
                "schema": VERIFY_SCHEMA}},
        })
        text = response["choices"][0]["message"]["content"]
    return json.loads(text)


def verify_rank_one_covers(rooms: dict[str, list[Photo]], capture_dir: Path,
                           work_dir: Path, model: str) -> None:
    """Verify each room's elected cover; failures remain explicitly unknown."""
    cache_path = work_dir / "cover-verification.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    changed = False
    for room_name, photos in rooms.items():
        heroes = sorted((p for p in photos if p.hero), key=lambda p: p.hero)
        if not heroes:
            continue
        cover = heroes[0]
        key = json.dumps({"room": room_name, "sha256": cover.sha256,
                          "model": model}, sort_keys=True)
        verdict = cache.get(key)
        if verdict is None:
            path = Path(cover.path)
            if not path.is_absolute():
                path = capture_dir / path
            try:
                verdict = verify_cover(room_name, path, model)
                cache[key] = verdict
                changed = True
            except Exception as exc:
                log.warning("cover verification failed for %s: %s",
                            room_name, exc)
                continue
        cover.room_match = bool(verdict.get("shows_named_room")) and bool(
            verdict.get("is_establishing_view"))
        cover.room_match_reason = str(verdict.get("reason") or "").strip()
    if changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                              encoding="utf-8")
