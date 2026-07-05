"""Frame curation: score every photo and elect a small hero set per room.

Two populations of frames (docs/15): the describe backend needs dense,
coverage-guaranteed keyframes (ingest.extract_keyframes — untouched); a
human reading the report needs few, high-quality, distinct frames.
Curation decides what is *shown by default* — nothing is deleted, every
frame stays reachable (report disclosure, review "all frames", Appendix A
always lists every file), and cited evidence is never lost.

Scoring is comparative within a room — absolute thresholds don't transfer
across devices, codecs and lighting (the same reasoning as
extract_keyframes): Laplacian-variance sharpness damped by an
exposure-clipping penalty, pure PIL so the core install curates without
cv2/torch. The learned no-reference IQA tier was benchmarked and NOT
adopted (docs/15, 5 Jul 2026): MUSIQ ranked marginally more like a human
(it fixes this gate's texture bias) but pyiqa is CC BY-NC-SA — unusable
commercially — and ~100x slower; CLIP-IQA rewards overexposure and lost
to this gate outright. Known bias to keep in mind: Laplacian variance
rewards patterned surfaces (wallpaper, oven racks), so texture-rich
frames outrank cleaner compositions of equal sharpness.

Election is greedy maximal-marginal-relevance: each pick maximises
quality minus similarity to what is already picked, so near-identical
angles of the same corner don't crowd the hero set. Deliberate photo
captures (no source_video) are always heroes — a person chose to take
them; only video frames compete for the budget.

Reviewer overrides (promote/demote in the review app, docs/15 M3) are
keyed by the photo's sha256 — content identity survives rebuilds, room
renames and photo-id renumbering — and live in work_dir/curation.json,
the room-aliases pattern: builds re-derive everything, so review-time
decisions must be re-applied here or a rebuild resurrects the machine's
choices.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .schema import Photo

log = logging.getLogger(__name__)

CURATION_FILE = "curation.json"

HERO_MIN = 3
HERO_MAX = 6
# similarity below this floor is treated as "distinct enough"; the spread
# above it is what the MMR penalty acts on (grey-thumb similarity between
# any two frames of the same room rarely drops below ~0.75)
SIM_FLOOR = 0.75
MMR_LAMBDA = 0.5
# a candidate this similar to an already-picked hero is a duplicate and is
# only admitted if the budget cannot otherwise be filled
DUP_SIM = 0.95

_THUMB = (48, 27)


def hero_budget(n: int) -> int:
    """Video-frame heroes for a room with *n* frames — 3..6, scaled."""
    if n <= HERO_MIN:
        return n
    return max(HERO_MIN, min(HERO_MAX, round(n / 4)))


def frame_quality(path: Path) -> tuple[float, Optional[bytes]]:
    """(quality score, grey thumbnail bytes) for one image.

    Sharpness (Laplacian variance) × exposure factor. The factor tolerates
    ~8% clipped pixels (dark corners and windows are normal in interiors)
    then decays, so blown-out or near-black frames lose to balanced ones
    even when their in-focus regions are sharp. Unreadable files score 0
    so a corrupt frame can never be elected over a readable one.
    """
    from PIL import Image, ImageFilter, ImageStat

    try:
        with Image.open(path) as im:
            im.draft("L", (640, 640))       # fast JPEG downscale-on-decode
            g = im.convert("L")
            if max(g.size) > 640:
                g.thumbnail((640, 640))
            lap = g.filter(ImageFilter.Kernel(
                (3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
            sharpness = ImageStat.Stat(lap).var[0]
            hist = g.histogram()
            total = sum(hist) or 1
            clipped = (sum(hist[:6]) + sum(hist[250:])) / total
            exposure = max(0.1, 1.0 - 2.5 * max(0.0, clipped - 0.08))
            thumb = g.resize(_THUMB).tobytes()
            return sharpness * exposure, thumb
    except Exception as e:
        log.warning("could not score %s (%s) — treating as lowest quality",
                    path, e)
        return 0.0, None


def _similarity(a: Optional[bytes], b: Optional[bytes]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    diff = sum(abs(x - y) for x, y in zip(a, b))
    return 1.0 - diff / (len(a) * 255.0)


def _sim_penalty(sim: float) -> float:
    return max(0.0, (sim - SIM_FLOOR) / (1.0 - SIM_FLOOR))


def override_key(photo: Photo) -> str:
    """Content identity when we have it; the frame filename (video stem +
    frame index — stable across rebuilds) when we don't."""
    return photo.sha256 or Path(photo.path.replace("\\", "/")).name


def load_overrides(work_dir: Path) -> dict[str, str]:
    """{override_key: "hero" | "hidden"} recorded by the review app."""
    path = work_dir / CURATION_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    ov = data.get("overrides") if isinstance(data, dict) else None
    return ov if isinstance(ov, dict) else {}


def save_override(work_dir: Path, key: str, action: str) -> None:
    """Record one promote ("hero") / demote ("hidden") decision."""
    overrides = load_overrides(work_dir)
    overrides[key] = action
    path = work_dir / CURATION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "overrides": overrides},
                               indent=2, ensure_ascii=False),
                    encoding="utf-8")


def elect_heroes(photos: list[Photo],
                 scores: dict[str, tuple[float, Optional[bytes]]],
                 overrides: dict[str, str]) -> None:
    """Assign Photo.hero ranks (and Photo.quality) for one room, in place.

    Forced first — deliberate photo captures and reviewer-promoted frames
    are heroes regardless of score; demoted frames never are. Remaining
    video frames fill the budget by MMR: quality minus similarity to the
    already-picked set.
    """
    for p in photos:
        p.hero = None

    # quality is the ratio to the room's best frame — min-max would blow
    # sensor noise between equally sharp frames up into a full 0..1 spread
    # and drown the MMR distinctness term; a ratio keeps like frames alike
    # while genuinely blurred ones fall away
    raw = {p.id: scores.get(p.id, (0.0, None))[0] for p in photos}
    hi = max(raw.values(), default=0.0)
    for p in photos:
        p.quality = round(raw[p.id] / hi, 3) if hi > 0 else 1.0

    def thumb(p: Photo) -> Optional[bytes]:
        return scores.get(p.id, (0.0, None))[1]

    demoted = {p.id for p in photos if overrides.get(override_key(p)) == "hidden"}
    forced = [p for p in photos if p.id not in demoted
              and (not p.source_video
                   or overrides.get(override_key(p)) == "hero")]
    frames = [p for p in photos
              if p.source_video and p.id not in demoted and p not in forced]

    heroes: list[Photo] = list(forced)
    budget = hero_budget(len(frames))
    picked_thumbs = [thumb(p) for p in heroes]

    remaining = sorted(frames, key=lambda p: -p.quality)
    while remaining and len(heroes) - len(forced) < budget:
        best, best_score, best_dup = None, None, None
        for p in remaining:
            sim = max((_similarity(thumb(p), t) for t in picked_thumbs),
                      default=0.0)
            score = p.quality - MMR_LAMBDA * _sim_penalty(sim)
            if best is None or score > best_score:
                best, best_score, best_dup = p, score, sim >= DUP_SIM
        if best_dup and len(heroes) > len(forced):
            break    # only near-duplicates left — a smaller hero set wins
        heroes.append(best)
        picked_thumbs.append(thumb(best))
        remaining.remove(best)

    for rank, p in enumerate(heroes, start=1):
        p.hero = rank


def curate(rooms: dict[str, list[Photo]], capture_dir: Path,
           work_dir: Path) -> None:
    """Score every photo and elect each room's hero set (build step 2b).

    Runs after the integrity manifest so overrides key on sha256. Mutates
    the Photo objects (hero/quality) that flow into the inventory."""
    overrides = load_overrides(work_dir)
    for room_name, photos in rooms.items():
        scores: dict[str, tuple[float, Optional[bytes]]] = {}
        for p in photos:
            full = Path(p.path)
            if not full.is_absolute():
                full = capture_dir / full
            scores[p.id] = frame_quality(full)
        elect_heroes(photos, scores, overrides)
        n_hero = sum(1 for p in photos if p.hero)
        if n_hero < len(photos):
            log.info("curated %s: %d of %d frames shown by default",
                     room_name, n_hero, len(photos))


def apply_override(inv, photo_id: str, action: str, work_dir: Path) -> dict:
    """Promote/demote one photo now and persist the decision (docs/15 M3).

    Interactive semantics are deliberately literal — promote makes *this*
    frame a hero (appended after the current set), demote removes it; no
    re-election happens until the next build, so the reviewer sees exactly
    what they asked for. Returns {"photo_id", "hero"}.
    """
    if action not in ("promote", "demote"):
        raise ValueError("action must be promote or demote")
    photo, room = None, None
    for r in inv.rooms:
        for p in r.photos:
            if p.id == photo_id:
                photo, room = p, r
                break
        if photo:
            break
    if photo is None:
        raise KeyError(f"no such photo: {photo_id}")
    if action == "promote":
        if not photo.hero:
            top = max((p.hero or 0 for p in room.photos), default=0)
            photo.hero = top + 1
    else:
        photo.hero = None
    save_override(work_dir, override_key(photo),
                  "hero" if action == "promote" else "hidden")
    return {"photo_id": photo.id, "hero": photo.hero}
