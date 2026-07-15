"""De-duplicate items reported across multiple photos of the same room.

The describe backend sees a whole room's photos in one call, so duplication is
already rare with the claude backend; the offline backend and any per-photo or
batched mode (the local Ollama backend sends photos in batches of six) need
this pass. Strategy: within a room, items describing the same thing merge —
keeping the longest description, the worst condition grade (conservative for
deposit purposes), the union of defects and photo references.

Two items are "the same thing" when their head nouns agree — i.e. one name
adds only descriptor words (material, colour, finish, qualifier) to the other.
"Walls (Cream Emulsion)" / "Walls" / "Walls painted white" all share the head
noun "walls" and merge; "Door" never absorbs "Door Handle and Lockset" because
that adds the new noun "handle". This is what collapses the cross-batch
structural duplication the batched local backend produces (the same wall /
floor / ceiling re-described per batch with different wording).

Crop attachment uses item-conditioned grounding: each schedule item builds a
query list from its name/aliases, scores detector boxes in its cited photos,
auto-attaches high-confidence matches, and queues mid-confidence proposals for
accept/reject review. Manual crop drawing remains the fallback when grounding
finds nothing safe.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

from .detect import build_item_queries
from .det_match import DET_GOLD_BLOCK
from .schema import CONDITION_GRADES, Item, Photo, Room

if TYPE_CHECKING:
    from .detect import Detection, Detector

# Descriptor / non-head tokens: materials, colours, finishes, qualifiers,
# quantities and glue words. These are stripped before comparing names so that
# "Walls (Cream Emulsion)" and "Walls" reduce to the same head noun "walls".
_DESCRIPTOR_TOKENS = frozenset(
    "white cream grey gray black brown beige taupe magnolia oak wood wooden "
    "wood-effect woodeffect effect laminate vinyl engineered painted emulsion "
    "finish finished colour color light dark upper lower left right interior "
    "exterior internal external single double tall round large small mounted "
    "wall-mounted wallmounted upvc metal silver stainless steel brushed gloss "
    "matte fabric upholstered marble ceramic carpet section area side front "
    "back main primary x x2 x3 x4 and the a an to of for with or "
    "fitted built-in builtin built".split()
)

# Detector labels are often shorter or more natural than schedule names.
# These aliases only affect the literal/safe crop path; they do not merge
# inventory items or change the names written by the describing backend.
_DETECTION_LABEL_ALIASES = {
    "stairs": "staircase",
    "stairway": "staircase",
    "stairwell": "staircase",
    "skirting": "skirting board",
    "floor": "flooring",
    "wall": "walls",
    "stair carpet": "carpet",
}

# Combined grounding score = label match × detector confidence.
# Auto-attach above AUTO; propose (review queue) between PROPOSE and AUTO;
# reject below PROPOSE so visibly wrong crops stay off the report.
CROP_AUTO_THRESHOLD = 0.72
CROP_PROPOSE_THRESHOLD = 0.48
# The largest current room has 148 distinct schedule queries. Keep one room
# in one detector pass where possible; splitting too aggressively multiplies
# CPU inference time because the same photo is re-scanned for every batch.
GROUNDING_QUERY_BATCH = 192

# Extra crop-only blocks when the schedule name is a paraphrase of a blocked
# gold item (e.g. "Smoke/heat alarm" vs gold "smoke alarm").
_CROP_ITEM_BLOCK_SUBSTRINGS: frozenset[tuple[str, str]] = frozenset({
    ("lamp", "smoke"),     # lamp must not ground to smoke/heat alarm
    ("bed", "bedside"),    # bed box must not attach to bedside lamps
})


def _key(item: Item) -> str:
    base = item.detector_label or item.name
    base = re.sub(r"\bx\s*\d+$", "", base.strip().lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", base)


def _tokens(name: str) -> list[str]:
    """Lowercase content tokens of an item name, parentheticals flattened."""
    s = re.sub(r"\bx\s*\d+$", "", name.strip().lower())
    s = re.sub(r"\([^)]*\)", " ", s)            # flatten parentheticals
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w]


def _detection_matches_item(label: str, item_name: str) -> bool:
    """Return whether a detector label is a safe literal crop candidate.

    Every label word must appear in the schedule name, or an explicit
    structural alias must reduce to that case. Fuzzy / synonym matches go
    through ``_grounding_score`` instead so they can carry a confidence and
    land in the proposed review queue rather than silent auto-attach.
    """
    item_tokens = set(_tokens(item_name))
    label_text = label.strip().lower()
    label_tokens = set(_tokens(label_text))
    if label_tokens and label_tokens <= item_tokens:
        return True
    canonical = _DETECTION_LABEL_ALIASES.get(label_text)
    return bool(canonical and set(_tokens(canonical)) <= item_tokens)


def _norm_pair_text(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").replace("/", " ").split())


def _blocked_pair(label: str, item_name: str) -> bool:
    a = _norm_pair_text(label)
    b = _norm_pair_text(item_name)
    if (a, b) in DET_GOLD_BLOCK:
        return True
    for det, gold in DET_GOLD_BLOCK:
        if a == det and (b == gold or gold in b):
            # Avoid over-blocking surface rules like lamp→ceiling on
            # "ceiling light" schedule names: only apply containment when the
            # gold token is a full word in the item name.
            if b == gold:
                return True
            item_toks = set(b.split())
            gold_toks = set(gold.split())
            if gold_toks and gold_toks <= item_toks:
                return True
    for det, needle in _CROP_ITEM_BLOCK_SUBSTRINGS:
        if a == det and needle in b:
            return True
    return False


def _label_in_queries(label: str, queries: Iterable[str]) -> bool:
    label_n = _norm_pair_text(label)
    return label_n in {_norm_pair_text(q) for q in queries}


def _grounding_score(label: str, item_name: str,
                     aliases: Iterable[str] | None = None) -> float:
    """How well a detector label grounds to this schedule item (0..1).

    Non-literal attaches require the detector label to appear in the item's
    query list. Fuzzy difflib/substring scores are deliberately not used —
    they proposed bed→bedside lamps and lamp→smoke alarm above the review
    threshold.
    """
    if _blocked_pair(label, item_name):
        return 0.0
    if _detection_matches_item(label, item_name):
        return 1.0
    queries = build_item_queries(item_name, aliases)
    if _label_in_queries(label, queries):
        return 1.0
    return 0.0


def _combined_crop_score(label: str, det_confidence: float, item_name: str,
                         aliases: Iterable[str] | None = None) -> float:
    """Label match × detector confidence — ranking key for crop candidates."""
    match = _grounding_score(label, item_name, aliases)
    if match <= 0:
        return 0.0
    return match * float(det_confidence)


def _apply_crop(item: Item, crop_path: str, score: float, status: str,
                detector_label: str | None = None) -> None:
    item.crop_path = crop_path
    item.crop_confidence = round(score, 4)
    item.crop_status = status
    if detector_label and not item.detector_label:
        item.detector_label = detector_label


def _best_detection_for_item(
        item: Item,
        detections: dict,
        aliases: Iterable[str] | None = None,
        min_score: float = CROP_PROPOSE_THRESHOLD,
) -> tuple[Optional["Detection"], float, bool]:
    """Highest-scoring cropped detection in the item's cited photos.

    Returns ``(detection, score, literal)`` where *literal* means the old
    conservative label⊆name rule matched — those always auto-attach.
    """
    best: Optional["Detection"] = None
    best_score = 0.0
    best_literal = False
    for pid in item.photo_ids:
        for det in detections.get(pid) or []:
            if not det.crop_path:
                continue
            literal = _detection_matches_item(det.label, item.name)
            if literal:
                score = float(det.confidence)
            else:
                score = _combined_crop_score(det.label, det.confidence,
                                             item.name, aliases)
            if not literal and score < min_score:
                continue
            if best is None or score > best_score or (
                    score == best_score and literal and not best_literal):
                best, best_score, best_literal = det, score, literal
    return best, best_score, best_literal


def _status_for_score(score: float, *, literal: bool = False) -> str | None:
    if literal and score > 0:
        return "auto"
    if score >= CROP_AUTO_THRESHOLD:
        return "auto"
    if score >= CROP_PROPOSE_THRESHOLD:
        return "proposed"
    return None


def attach_detector_crops(items: list[Item], detections: dict,
                          aliases_by_name: dict[str, list[str]] | None = None
                          ) -> None:
    """Give schedule items a detector close-up via item-conditioned grounding.

    For each item without a crop, score detections in its cited photos against
    a query list derived from the item name (and optional aliases). High scores
    auto-attach; mid scores attach as ``proposed`` for the accept/reject crop
    review queue; low scores are left blank (manual drawing remains the
    fallback). Prior crops are never replaced.
    """
    aliases_by_name = aliases_by_name or {}
    for item in items:
        if item.crop_path:
            continue
        aliases = aliases_by_name.get(item.name) or aliases_by_name.get(
            item.name.lower())
        best, score, literal = _best_detection_for_item(
            item, detections, aliases)
        status = _status_for_score(score, literal=literal)
        if best is None or status is None:
            continue
        _apply_crop(item, best.crop_path, score, status, best.label)


def ground_missing_crops(
        items: list[Item],
        photo_paths: dict[str, Path],
        detector: "Detector",
        crops_dir: Path,
        *,
        aliases_by_name: dict[str, list[str]] | None = None,
        detections: dict | None = None,
) -> int:
    """Re-run YOLOE with per-item queries for items still missing crops.

    Returns the number of items that gained a crop. New detections are merged
    into *detections* when provided so later callers see them. No-ops when the
    detector is unavailable or not in text mode.
    """
    if not getattr(detector, "available", False):
        return 0
    if getattr(detector, "mode", "text") != "text":
        return 0

    aliases_by_name = aliases_by_name or {}
    detections = detections if detections is not None else {}
    attached = 0
    pending: list[tuple[Item, list[str], Iterable[str] | None]] = []
    all_queries: list[str] = []
    photo_ids: set[str] = set()
    conditioned_detections: dict[str, list] = {}

    for item in items:
        if item.crop_path or item.crop_status == "rejected":
            continue
        aliases = aliases_by_name.get(item.name) or aliases_by_name.get(
            item.name.lower())
        queries = build_item_queries(item.name, aliases)
        if not queries:
            continue
        pending.append((item, queries, aliases))
        for query in queries:
            if query not in all_queries:
                all_queries.append(query)
        photo_ids.update(item.photo_ids)

    if not pending or not all_queries:
        return 0

    # Query each room's photos in a few shared batches. The previous
    # implementation reconfigured YOLOE once per item/photo pair; that is
    # needlessly expensive because YOLOE can score many text classes in one
    # pass. Keep batches bounded so the prompt embedding remains manageable.
    query_batches = [all_queries[i:i + GROUNDING_QUERY_BATCH]
                     for i in range(0, len(all_queries), GROUNDING_QUERY_BATCH)]
    for pid in photo_ids:
        path = photo_paths.get(pid)
        if path is None:
            continue
        for batch_index, queries in enumerate(query_batches):
            batch_dets = detector.detect_queries(
                path, queries, crops_dir=crops_dir,
                stem_suffix=f"g-room-{batch_index}-")
            detections.setdefault(pid, []).extend(batch_dets)
            conditioned_detections.setdefault(pid, []).extend(batch_dets)

    for item, queries, aliases in pending:
        # Score only the fresh, item-conditioned detections here.  A query
        # label can look literally compatible with the item name even when
        # its detector confidence is weak; it must still clear the normal
        # auto/proposed thresholds before it reaches the report.
        best, best_score, _literal = _best_detection_for_item(
            item, conditioned_detections, aliases)
        status = _status_for_score(best_score, literal=False)
        if best is None or status is None:
            continue
        _apply_crop(item, best.crop_path, best_score, status, best.label)
        attached += 1
    return attached


def crop_review_queue(items: list[Item]) -> list[Item]:
    """Items whose crop is attached but still needs accept/reject."""
    return [it for it in items if it.crop_status == "proposed" and it.crop_path]


def accept_crop(item: Item) -> None:
    if item.crop_path:
        item.crop_status = "accepted"


def reject_crop(item: Item) -> None:
    """Drop a proposed/auto crop so the reviewer can draw manually."""
    item.crop_path = None
    item.crop_confidence = None
    item.crop_status = "rejected"


def _head_nouns(name: str) -> set[str]:
    """The discriminating noun tokens: everything that is not a descriptor."""
    return {t for t in _tokens(name) if t not in _DESCRIPTOR_TOKENS}


def _same_item(new_name: str, rep_name: str) -> bool:
    """True when *new_name* describes the same item as *rep_name*.

    Two names match when their head nouns are equal, or when the new name's
    heads are a subset of the rep's heads (the new name only qualifies an
    already-seen item with extra descriptors). A new name that introduces an
    extra head noun is a different item and never merges here.
    """
    new_heads = _head_nouns(new_name)
    rep_heads = _head_nouns(rep_name)
    if not new_heads or not rep_heads:
        return False                       # all-descriptor name: too generic
    return new_heads == rep_heads or new_heads <= rep_heads


def _worse(a: str | None, b: str | None) -> str | None:
    grades = [g for g in (a, b) if g in CONDITION_GRADES]
    if not grades:
        return a or b
    return max(grades, key=CONDITION_GRADES.index)


def _combine(into: Item, src: Item) -> None:
    """Fold *src* into *into* (deposit-conservative field union)."""
    if len(src.description) > len(into.description):
        into.description = src.description
    into.condition = _worse(into.condition, src.condition)
    into.cleanliness = into.cleanliness or src.cleanliness
    for d in src.defects:
        if d not in into.defects:
            into.defects.append(d)
    into.photo_ids = sorted(set(into.photo_ids) | set(src.photo_ids))
    into.quantity = max(into.quantity, src.quantity)
    if not into.crop_path and src.crop_path:
        into.crop_path = src.crop_path
        into.crop_confidence = src.crop_confidence
        into.crop_status = src.crop_status
    if src.confidence and (not into.confidence or src.confidence > into.confidence):
        into.confidence = src.confidence


def merge_items(items: list[Item], room_code: str) -> list[Item]:
    # Greedy, non-transitive clustering: each item joins the first existing
    # cluster whose representative is "the same item", else starts a new one.
    # Non-transitivity is deliberate — A~B and B~C must not force A~C, which
    # is what collapsed distinct furniture when a shared generic descriptor
    # chained unrelated items together.
    clusters: list[Item] = []
    for it in items:
        target = next((c for c in clusters if _same_item(it.name, c.name)), None)
        if target is None:
            clusters.append(it)
        else:
            _combine(target, it)
    for i, it in enumerate(clusters, start=1):
        it.id = f"{room_code}-{i:03d}"
    return clusters


def room_code(room_name: str, used: set[str]) -> str:
    letters = re.sub(r"[^A-Z]", "", room_name.upper())[:3] or "RM"
    code, n = letters, 2
    while code in used:
        code, n = f"{letters}{n}", n + 1
    used.add(code)
    return code


def _has_review_overlay(item: Item) -> bool:
    return bool(item.rejected_defects or item.comments or item.defect_regions
                or item.not_inspected)


def _apply_review_overlay(new: Item, prior: Item) -> None:
    """Copy human review annotations onto a freshly described item."""
    new.reviewed = prior.reviewed
    new.rejected = prior.rejected
    new.rejected_defects = list(prior.rejected_defects)
    new.not_inspected = prior.not_inspected
    new.defect_regions = list(prior.defect_regions)
    new.comments = list(prior.comments)


def _merge_photos(prior: list[Photo], new: list[Photo]) -> list[Photo]:
    """Keep ingest photos plus any reviewer-added photos from a prior run."""
    new_ids = {p.id for p in new}
    extra = [p for p in prior if p.id not in new_ids]
    return new + extra


def _used_id_numbers(items: list[Item], prefix: str) -> set[int]:
    used: set[int] = set()
    for it in items:
        if not it.id.startswith(f"{prefix}-"):
            continue
        tail = it.id.rsplit("-", 1)[-1]
        if tail.isdigit():
            used.add(int(tail))
    return used


def _renumber_items(items: list[Item], prefix: str,
                    reserved: set[int] | None = None) -> list[Item]:
    """Assign sequential ids, skipping numbers reserved by kept prior items."""
    used = set(reserved or ())
    n = 1
    for it in items:
        while n in used:
            n += 1
        it.id = f"{prefix}-{n:03d}"
        used.add(n)
        n += 1
    return items


def merge_room_with_prior(prior_room: Room | None, new_room: Room,
                          code: str) -> Room:
    """Re-describe a room but keep attested / hand-edited items from *prior_room*.

    Rules (deposit-conservative — never silently discard human work):
    - reviewer-added items (``added_by``) are kept verbatim
    - reviewed or rejected items are kept verbatim (photo refs unioned if AI
      cites more)
    - partial review overlays (struck defects, comments, regions) are copied
      onto matching fresh AI items by normalised name
    - unreviewed prior items absent from the new describe are dropped
    """
    if prior_room is None:
        return new_room

    kept: list[Item] = []
    kept_keys: set[str] = set()
    overlays: dict[str, Item] = {}

    for prior in prior_room.items:
        k = _key(prior)
        if prior.added_by or prior.reviewed or prior.rejected:
            kept.append(prior)
            kept_keys.add(k)
        elif _has_review_overlay(prior):
            overlays[k] = prior

    fresh: list[Item] = []
    for new in new_room.items:
        k = _key(new)
        if k in kept_keys:
            for item in kept:
                if _key(item) == k:
                    item.photo_ids = sorted(set(item.photo_ids) | set(new.photo_ids))
            continue
        if k in overlays:
            _apply_review_overlay(new, overlays[k])
        fresh.append(new)

    fresh = merge_items(fresh, code)
    for item in fresh:
        prior = overlays.get(_key(item))
        if prior:
            _apply_review_overlay(item, prior)

    fresh = _renumber_items(fresh, code, _used_id_numbers(kept, code))
    items = kept + fresh
    photos = _merge_photos(prior_room.photos, new_room.photos)
    return Room(name=new_room.name, summary=new_room.summary,
                items=items, photos=photos,
                cover_status=new_room.cover_status,
                cover_review_reason=new_room.cover_review_reason)
