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
frames outrank cleaner compositions of equal sharpness. An
``establishing_score`` (0..1, PIL-only) dampens that bias by penalising
edge activity concentrated in one quadrant (typical object close-up) and
rewarding balanced activity across vertical bands (ceiling + floor
visible). ``frame_quality`` multiplies sharpness×exposure by
``0.4 + 0.6 × establishing``; after MMR election, rank 1 is reassigned
among **elected heroes plus one optional cover slot** (approach B — not the
full frame pool). The cover slot admits the best ``cover_score`` frame above
a quality floor when MMR missed it (e.g. a wide bedroom view outranked by
texture). Rank 1 is the hero maximising ``cover_score =
establishing × min(1, 2.5/cbr)`` with an adaptive sharpness floor: a
low-quality winner is rejected when a sharper alternative scores within 8%
(docs/18 E5). Hard cover gates (E4) are kept for offline eval only — they
regressed on the own-property fixture.

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
_LAPLACIAN_KERNEL = (3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0]
# establishing swings quality between 40% and 100% of sharpness×exposure
_ESTABLISHING_WEIGHT = 0.6
# rank-1 cover selection (docs/18 E5) and offline eval gates (E4)
_COVER_CBR_REF = 2.5
_COVER_CBR_LOW = 1.05        # penalise uniform-surface close-ups (drawer tops)
_COVER_CBR_TEXTURE = 1.5     # prefer wider alt when winner looks texture-filled
_COVER_TEXTURE_ALT = 0.88
_COVER_SLOT_QUALITY = 0.12   # min quality ratio to admit a cover-slot hero
_COVER_RANK1_QUALITY = 0.25  # prefer sharper rank-1 when within 8% cover score
_COVER_ALT_WITHIN = 0.92
_CLIP_GATE = 0.15
_SMOOTH_GATE = 0.97
_CBR_GATE = 3.0
_SMOOTH_LAP_TOL = 2          # |lap − 128| ≤ this → "smooth" pixel


def hero_budget(n: int) -> int:
    """Video-frame heroes for a room with *n* frames — 3..6, scaled."""
    if n <= HERO_MIN:
        return n
    return max(HERO_MIN, min(HERO_MAX, round(n / 4)))


def _laplacian(g):
    from PIL import ImageFilter

    return g.filter(ImageFilter.Kernel(
        *_LAPLACIAN_KERNEL, scale=1, offset=128))


def _region_var(lap, box: tuple[int, int, int, int]) -> float:
    from PIL import ImageStat

    return ImageStat.Stat(lap.crop(box)).var[0]


def sharpness(g) -> float:
    """Full-frame Laplacian variance — higher is sharper."""
    lap = _laplacian(g)
    return _region_var(lap, (0, 0, g.size[0], g.size[1]))


def smooth_fraction(g) -> float:
    """Fraction of pixels with near-zero Laplacian response (blur / empty wall)."""
    lap = _laplacian(g)
    data = lap.get_flattened_data()
    if not data:
        return 0.0
    smooth = sum(1 for p in data if abs(p - 128) <= _SMOOTH_LAP_TOL)
    return smooth / len(data)


def centre_border_ratio(g) -> float:
    """Centre vs border Laplacian variance — high values suggest object fill."""
    w, h = g.size
    if w < 8 or h < 8:
        return 1.0
    lap = _laplacian(g)
    mx, my = w // 4, h // 4
    centre_var = _region_var(lap, (mx, my, w - mx, h - my))
    border_boxes = [(0, 0, w, my), (0, h - my, w, h),
                    (0, my, mx, h - my), (w - mx, my, w, h - my)]
    border_var = sum(_region_var(lap, b) for b in border_boxes) / 4.0
    if border_var <= 0:
        return centre_var if centre_var > 0 else 1.0
    return centre_var / border_var


def exposure_clipped_fraction(g) -> float:
    """Fraction of pixels at or near 0 / 255 (blown windows, crushed shadows)."""
    hist = g.histogram()
    total = sum(hist) or 1
    return (sum(hist[:6]) + sum(hist[250:])) / total


def establishing_score(g) -> float:
    """0..1 heuristic favouring wide room views over object close-ups.

    Penalises Laplacian edge activity concentrated in one quadrant; rewards
    balanced activity across top/middle/bottom vertical bands (ceiling and
    floor both visible in a typical establishing shot).
    """
    w, h = g.size
    if w < 8 or h < 8:
        return 0.5

    lap = _laplacian(g)
    mx, my = w // 2, h // 2
    quads = [(0, 0, mx, my), (mx, 0, w, my),
             (0, my, mx, h), (mx, my, w, h)]
    qe = [_region_var(lap, q) for q in quads]
    q_total = sum(qe) or 1.0
    q_max = max(qe) / q_total
    quadrant_balance = max(0.0, min(1.0, 1.0 - (q_max - 0.25) / 0.75))

    b1, b2 = h // 3, 2 * h // 3
    bands = [(0, 0, w, b1), (0, b1, w, b2), (0, b2, w, h)]
    be = [_region_var(lap, b) for b in bands]
    b_total = sum(be) or 1.0
    b_max = max(be) / b_total
    band_balance = max(0.0, min(1.0, 1.0 - (b_max - 1 / 3) / (2 / 3)))

    return 0.5 * quadrant_balance + 0.5 * band_balance


def frame_quality(path: Path) -> tuple[float, Optional[bytes], float]:
    """(quality score, grey thumbnail bytes, establishing score) for one image.

    Sharpness (Laplacian variance) × exposure factor × establishing bias.
    The exposure factor tolerates ~8% clipped pixels (dark corners and
    windows are normal in interiors) then decays. Establishing bias is
    ``0.4 + 0.6 × establishing_score`` — see module docstring. Unreadable
    files score 0 so a corrupt frame can never be elected over a readable one.
    """
    from PIL import Image, ImageFilter, ImageStat

    try:
        with Image.open(path) as im:
            im.draft("L", (640, 640))       # fast JPEG downscale-on-decode
            g = im.convert("L")
            if max(g.size) > 640:
                g.thumbnail((640, 640))
            sh = sharpness(g)
            clipped = exposure_clipped_fraction(g)
            exposure = max(0.1, 1.0 - 2.5 * max(0.0, clipped - 0.08))
            establishing = establishing_score(g)
            quality = (sh * exposure
                       * (1.0 - _ESTABLISHING_WEIGHT
                          + _ESTABLISHING_WEIGHT * establishing))
            thumb = g.resize(_THUMB).tobytes()
            return quality, thumb, establishing
    except Exception as e:
        log.warning("could not score %s (%s) — treating as lowest quality",
                    path, e)
        return 0.0, None, 0.0


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


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if p == 0.5:
        if n % 2:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0
    idx = min(max(int(n * p), 0), n - 1)
    return s[idx]


def _passes_cover_gates(
        sh: float, smooth: float, cbr: float, clipped: float, *,
        room_median: float, room_p25: float) -> bool:
    if sh < room_median:
        return False
    if clipped > _CLIP_GATE:
        return False
    if smooth > _SMOOTH_GATE and sh < room_p25:
        return False
    if cbr > _CBR_GATE:
        return False
    return True


def cover_score(establishing: float, cbr: float) -> float:
    """Rank-1 cover heuristic: establishing damped by object-fill and uniform tops.

    High centre/border ratio → object filling the frame; very low ratio → a
    uniform surface close-up (drawer front, bread bin lid) that still looks
    "balanced" to ``establishing_score``.
    """
    high_pen = min(1.0, _COVER_CBR_REF / max(cbr, 0.5))
    low_pen = min(1.0, cbr / _COVER_CBR_LOW) if cbr < _COVER_CBR_LOW else 1.0
    return establishing * high_pen * low_pen


def _assign_rank_one(photos: list[Photo], best: Photo) -> None:
    """Promote *best* to hero rank 1, shifting intervening ranks down."""
    heroes = [p for p in photos if p.hero is not None]
    if best.hero == 1 or len(heroes) <= 1:
        return
    old_rank = best.hero
    for p in heroes:
        if p is best:
            p.hero = 1
        elif p.hero is not None and p.hero < old_rank:
            p.hero += 1


def _cover_score_for(
        photo: Photo,
        establishing: dict[str, float],
        cover: dict[str, tuple[float, float, float, float]]) -> float:
    sh, _smooth, cbr, _clipped = cover[photo.id]
    return cover_score(establishing.get(photo.id, 0.0), cbr)


def _ensure_cover_slot(
        photos: list[Photo],
        establishing: dict[str, float],
        cover: dict[str, tuple[float, float, float, float]]) -> None:
    """Add one cover-slot hero when MMR missed the best cover candidate."""
    heroes = {p.id for p in photos if p.hero is not None}
    best: Photo | None = None
    best_score = -1.0
    for p in photos:
        if not p.source_video or p.id not in cover:
            continue
        if (p.quality or 0.0) < _COVER_SLOT_QUALITY:
            continue
        score = _cover_score_for(p, establishing, cover)
        if score > best_score:
            best_score, best = score, p
    if best is None or best.id in heroes:
        return
    top = max((p.hero or 0 for p in photos), default=0)
    best.hero = top + 1


def _promote_cover_rank_one(
        photos: list[Photo],
        establishing: dict[str, float],
        cover: dict[str, tuple[float, float, float, float]]) -> None:
    """Move rank 1 to the best cover_score among heroes (docs/18 E5)."""
    heroes = [p for p in photos if p.hero is not None]
    if len(heroes) <= 1:
        return

    def score(p: Photo) -> float:
        return _cover_score_for(p, establishing, cover)

    best = max(heroes, key=score)
    top_score = score(best)
    if cover[best.id][2] > _COVER_CBR_TEXTURE:
        alts = [p for p in heroes
                if cover[p.id][2] <= _COVER_CBR_TEXTURE
                and score(p) >= top_score * _COVER_TEXTURE_ALT]
        if alts:
            best = max(alts, key=score)
            top_score = score(best)
    if (best.quality or 0.0) < _COVER_RANK1_QUALITY:
        alts = [p for p in heroes
                if (p.quality or 0.0) >= _COVER_RANK1_QUALITY
                and score(p) >= top_score * _COVER_ALT_WITHIN]
        if alts:
            best = max(alts, key=score)
    _assign_rank_one(photos, best)


def elect_heroes(photos: list[Photo],
                 scores: dict[str, tuple[float, Optional[bytes], float]],
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
    raw = {p.id: scores.get(p.id, (0.0, None, 0.0))[0] for p in photos}
    hi = max(raw.values(), default=0.0)
    for p in photos:
        p.quality = round(raw[p.id] / hi, 3) if hi > 0 else 1.0

    def thumb(p: Photo) -> Optional[bytes]:
        return scores.get(p.id, (0.0, None, 0.0))[1]

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


def _cover_metrics(path: Path) -> tuple[float, float, float, float]:
    """(sharpness, smooth_fraction, centre_border_ratio, clipped) for cover gates."""
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.draft("L", (640, 640))
            g = im.convert("L")
            if max(g.size) > 640:
                g.thumbnail((640, 640))
            return (sharpness(g), smooth_fraction(g),
                    centre_border_ratio(g), exposure_clipped_fraction(g))
    except Exception as e:
        log.warning("could not measure cover metrics for %s (%s)", path, e)
        return 0.0, 1.0, 1.0, 1.0


def curate(rooms: dict[str, list[Photo]], capture_dir: Path,
           work_dir: Path) -> None:
    """Score every photo and elect each room's hero set (build step 2b).

    Runs after the integrity manifest so overrides key on sha256. Mutates
    the Photo objects (hero/quality) that flow into the inventory."""
    overrides = load_overrides(work_dir)
    for room_name, photos in rooms.items():
        scores: dict[str, tuple[float, Optional[bytes], float]] = {}
        cover: dict[str, tuple[float, float, float, float]] = {}
        for p in photos:
            full = Path(p.path)
            if not full.is_absolute():
                full = capture_dir / full
            scores[p.id] = frame_quality(full)
            cover[p.id] = _cover_metrics(full)
        establishing = {pid: s[2] for pid, s in scores.items()}
        elect_heroes(photos, scores, overrides)
        _ensure_cover_slot(photos, establishing, cover)
        _promote_cover_rank_one(photos, establishing, cover)
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
