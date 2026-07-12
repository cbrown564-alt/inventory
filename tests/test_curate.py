"""Curation (docs/15 M2/M3): score frames, elect a small distinct hero set,
honour reviewer overrides across rebuilds, and never lose cited evidence."""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from homeinventory.cli import main
from homeinventory.curate import (apply_override, apply_room_cover_status,
                                  assess_rank1_cover, centre_border_ratio,
                                  curate, establishing_score,
                                  exposure_clipped_fraction, finalize_room_covers,
                                  frame_quality, hero_budget, load_cover_status,
                                  load_overrides, override_key,
                                  rerank_covers_with_detections, save_override,
                                  sharpness, smooth_fraction)
from homeinventory.detect import Detection
from homeinventory.report import render
from homeinventory.schema import Inventory, Item, Photo, Room
from evals.hero_gold import (
    acceptable_frames,
    load_gold_document,
    preferred_frames,
)


def _noise_img(path: Path, seed: int, blur: float = 0.0):
    """A detailed test frame; blur > 0 makes it a low-quality variant."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (96, 64))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                for _ in range(96 * 64)])
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)


def _frame(tmp_path: Path, i: int, *, seed: int, blur: float = 0.0) -> Photo:
    p = tmp_path / f"walk_f{i:06d}.jpg"
    _noise_img(p, seed=seed, blur=blur)
    return Photo(id=f"P{i:03d}", path=str(p), room="Kitchen",
                 source_video="walk.mp4")


def test_hero_budget_scales_3_to_6():
    assert hero_budget(2) == 2          # tiny rooms show everything
    assert hero_budget(3) == 3
    assert hero_budget(8) == 3
    assert hero_budget(16) == 4
    assert hero_budget(24) == 6
    assert hero_budget(100) == 6


def test_blurred_frames_lose_the_election(tmp_path):
    photos = [_frame(tmp_path, i, seed=i, blur=4.0 if i % 2 else 0.0)
              for i in range(8)]
    curate({"Kitchen": photos}, tmp_path, tmp_path / "work")
    heroes = {p.id for p in photos if p.hero}
    assert heroes and len(heroes) <= 6
    blurred = {photos[i].id for i in range(8) if i % 2}
    assert not heroes & blurred          # the minimum standard: no blur
    assert all(p.quality is not None for p in photos)


def test_deliberate_photos_are_always_heroes(tmp_path):
    manual = tmp_path / "corner.jpg"
    _noise_img(manual, seed=1, blur=5.0)     # even a soft one — a person
    photos = [Photo(id="P001", path=str(manual), room="K"),  # chose to take it
              _frame(tmp_path, 2, seed=2)]
    curate({"K": photos}, tmp_path, tmp_path / "work")
    assert photos[0].hero
    assert photos[1].hero                    # sharp frame elected alongside


def test_near_duplicates_do_not_crowd_the_hero_set(tmp_path):
    # ten near-identical sharp frames of one corner + two distinct views
    photos = [_frame(tmp_path, i, seed=99) for i in range(10)]
    photos += [_frame(tmp_path, 100 + j, seed=seed)
               for j, seed in enumerate((7, 8))]
    curate({"K": photos}, tmp_path, tmp_path / "work")
    heroes = [p for p in photos if p.hero]
    assert len([p for p in heroes if int(p.id[1:]) < 100]) <= 1
    assert {"P100", "P101"} <= {p.id for p in heroes}


def test_overrides_survive_a_rebuild(tmp_path):
    work = tmp_path / "work"
    photos = [_frame(tmp_path, i, seed=i, blur=0.0 if i < 4 else 4.0)
              for i in range(8)]
    curate({"K": photos}, tmp_path, work)
    demoted = next(p for p in photos if p.hero)
    promoted = photos[7]                       # blurred — machine said no
    save_override(work, override_key(demoted), "hidden")
    save_override(work, override_key(promoted), "hero")
    # a rebuild re-derives everything: fresh Photo objects, new ids
    fresh = [Photo(id=f"N{i:03d}", path=p.path, room="K",
                   source_video="walk.mp4") for i, p in enumerate(photos)]
    curate({"K": fresh}, tmp_path, work)
    by_path = {p.path: p for p in fresh}
    assert not by_path[demoted.path].hero      # demoted stays demoted
    assert by_path[promoted.path].hero         # promoted stays promoted


def test_detector_rerank_promotes_room_defining_overview_and_honours_hidden():
    closeup = Photo(id="P001", path="vanity.jpg", room="Bedroom 1", hero=1,
                    quality=1.0, source_video="walk.mp4")
    overview = Photo(id="P002", path="bed.jpg", room="Bedroom 1", hero=None,
                     quality=0.55, source_video="walk.mp4", cover_anchor=True)
    hidden = Photo(id="P003", path="hidden-bed.jpg", room="Bedroom 1",
                   hero=None, quality=1.0, source_video="walk.mp4")
    det = lambda label, conf: Detection(label, conf, (0, 0, 10, 10))
    detections = {
        "P001": [det("mirror", 0.95), det("cabinet", 0.9)],
        "P002": [det("bed", 0.8), det("wardrobe", 0.7)],
        "P003": [det("bed", 0.99), det("wardrobe", 0.99)],
    }

    changed = rerank_covers_with_detections(
        {"Bedroom 1": [closeup, overview, hidden]}, detections,
        {"hidden-bed.jpg": "hidden"},
    )

    assert changed == {"Bedroom 1": "P002"}
    assert overview.hero == 1
    assert closeup.hero == 2
    assert hidden.hero is None


def test_detector_rerank_leaves_unsupported_room_types_to_classical_cover():
    classical = Photo(id="P001", path="stairs.jpg", room="Stairs and Landing",
                      hero=1, quality=0.8, source_video="walk.mp4")
    false_positive = Photo(id="P002", path="partial.jpg",
                           room="Stairs and Landing", quality=0.2,
                           source_video="walk.mp4")
    detections = {
        "P002": [Detection("handrail", 0.9, (0, 0, 10, 10))],
    }

    changed = rerank_covers_with_detections(
        {"Stairs and Landing": [classical, false_positive]}, detections)

    assert changed == {}
    assert classical.hero == 1
    assert false_positive.hero is None


def test_detector_rerank_ignores_one_weak_room_label():
    classical = Photo(id="P001", path="living.jpg", room="Living Room",
                      hero=1, quality=0.8, source_video="walk.mp4")
    weak = Photo(id="P002", path="partial.jpg", room="Living Room",
                 quality=0.9, source_video="walk.mp4")
    detections = {
        "P002": [Detection("sofa", 0.31, (0, 0, 10, 10))],
    }

    changed = rerank_covers_with_detections(
        {"Living Room": [classical, weak]}, detections)

    assert changed == {}
    assert classical.hero == 1


def test_apply_override_is_literal_and_persisted(tmp_path):
    work = tmp_path / "work"
    inv = Inventory(rooms=[Room(name="K", photos=[
        Photo(id="P001", path="a.jpg", room="K", hero=1,
              source_video="w.mp4"),
        Photo(id="P002", path="b.jpg", room="K", source_video="w.mp4"),
    ])])
    out = apply_override(inv, "P002", "promote", work)
    assert out["hero"] == 2 and inv.rooms[0].photos[1].hero == 2
    apply_override(inv, "P001", "demote", work)
    assert inv.rooms[0].photos[0].hero is None
    assert load_overrides(work) == {"b.jpg": "hero", "a.jpg": "hidden"}


def test_report_cited_evidence_never_lost(tmp_path):
    """A cited frame that lost the election stays reachable: anchored in
    the screen report's disclosure and reproduced in the print appendix."""
    cap = tmp_path / "capture"
    photos = []
    for i, (hero, seed) in enumerate([(1, 1), (2, 2), (None, 3), (None, 4)],
                                     start=1):
        name = f"walk_f{i:06d}.jpg"
        _noise_img(cap / "Kitchen" / name, seed=seed)
        photos.append(Photo(id=f"P{i:03d}", path=f"Kitchen/{name}",
                            room="Kitchen", source_video="walk.mp4",
                            hero=hero, quality=0.5))
    inv = Inventory(rooms=[Room(
        name="Kitchen",
        items=[Item(id="KIT-001", name="Worktop", condition="good",
                    photo_ids=["P003"])],       # cites a non-hero frame
        photos=photos)])
    out = tmp_path / "report"
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert 'id="photo-P003"' in html            # evidence link resolves
    assert '<details class="more-frames' in html
    assert 'id="pdf-photo-P003"' in html        # printed appendix keeps it
    assert 'id="pdf-photo-P004"' not in html    # uncited non-hero: analysed,
    assert "listed with its checksum" in html   # hashed, disclosed on screen
    assert 'class="room-cover' in html          # top hero heads the section


def test_build_offline_curates_photo_captures_as_heroes(tmp_path):
    cap = tmp_path / "capture"
    for i in range(8):
        _noise_img(cap / "Kitchen" / f"k{i}.jpg", seed=i)
    out = tmp_path / "report"
    assert main(["build", str(cap), "-o", str(out),
                 "--backend", "offline", "--no-detect", "--no-pdf"]) == 0
    inv = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    photos = inv["rooms"][0]["photos"]
    assert all(p["hero"] for p in photos)       # deliberate captures all show
    assert all(p["quality"] is not None for p in photos)
    html = (out / "inventory.html").read_text(encoding="utf-8")
    assert '<details class="more-frames' not in html   # nothing to disclose


def _wide_balanced_img(path: Path) -> None:
    """Synthetic establishing shot: detail in every quadrant and band."""
    w, h = 320, 180
    im = Image.new("L", (w, h), 128)
    draw = ImageDraw.Draw(im)
    rnd = random.Random(42)
    for y in range(0, h, 4):
        shade = rnd.randrange(80, 176)
        draw.line([(0, y), (w, y)], fill=shade)
    for x in range(0, w, 6):
        shade = rnd.randrange(70, 186)
        draw.line([(x, 0), (x, h)], fill=shade)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)


def _corner_closeup_img(path: Path) -> None:
    """Synthetic object fill: sharp detail in centre on a flat field."""
    w, h = 320, 180
    im = Image.new("L", (w, h), 128)
    pw, ph = w // 5, h // 5
    detail = Image.new("L", (pw, ph))
    detail.putdata([random.Random(i).randrange(64, 192) for i in range(pw * ph)])
    im.paste(detail, ((w - pw) // 2, (h - ph) // 2))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)


def _drawer_top_img(path: Path) -> None:
    """Uniform worktop / drawer front — low centre/border ratio, high establishing."""
    w, h = 320, 180
    im = Image.new("L", (w, h), 140)
    draw = ImageDraw.Draw(im)
    for y in range(2 * h // 3, h, 6):
        draw.line([(0, y), (w, y)], fill=90)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)


def test_uniform_drawer_closeup_loses_rank_one(tmp_path):
    """Drawer-top uniform fills must not beat a wide balanced room view."""
    wide_path = tmp_path / "wide.jpg"
    drawer_path = tmp_path / "drawer.jpg"
    _wide_balanced_img(wide_path)
    _drawer_top_img(drawer_path)
    photos = [
        Photo(id="P001", path=str(drawer_path), room="Kitchen",
              source_video="walk.mp4"),
        Photo(id="P002", path=str(wide_path), room="Kitchen",
              source_video="walk.mp4"),
    ]
    curate({"Kitchen": photos}, tmp_path, tmp_path / "work")
    assert photos[1].hero == 1
    assert photos[0].hero != 1


    wide = Image.new("L", (320, 180), 128)
    draw = ImageDraw.Draw(wide)
    rnd = random.Random(7)
    for y in range(0, 180, 3):
        draw.line([(0, y), (320, y)], fill=rnd.randrange(256))
    for x in range(0, 320, 5):
        draw.line([(x, 0), (x, 180)], fill=rnd.randrange(256))

    close = Image.new("L", (320, 180), 30)
    patch = Image.new("L", (160, 90))
    patch.putdata([random.Random(i).randrange(256) for i in range(160 * 90)])
    close.paste(patch, (80, 45))

    wide_score = establishing_score(wide)
    close_score = establishing_score(close)
    assert wide_score > close_score
    assert 0.0 <= wide_score <= 1.0
    assert 0.0 <= close_score <= 1.0


def test_establishing_score_uniform_frame_is_neutral():
    flat = Image.new("L", (160, 90), 128)
    assert establishing_score(flat) == 1.0


def _blurred_wide_img(path: Path) -> None:
    """Wide layout but motion-blurred — should fail sharpness gate."""
    w, h = 320, 180
    im = Image.new("L", (w, h), 128)
    draw = ImageDraw.Draw(im)
    rnd = random.Random(99)
    for y in range(0, h, 4):
        draw.line([(0, y), (w, y)], fill=rnd.randrange(80, 176))
    for x in range(0, w, 6):
        draw.line([(x, 0), (x, h)], fill=rnd.randrange(70, 186))
    im = im.filter(ImageFilter.GaussianBlur(6.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)


def test_hard_gates_reject_blur_and_closeup_for_rank_one(tmp_path):
    """Rank 1 stays on the wide establishing frame, not blur or object fill."""
    wide_path = tmp_path / "wide.jpg"
    close_path = tmp_path / "close.jpg"
    blur_path = tmp_path / "blur.jpg"
    _wide_balanced_img(wide_path)
    _corner_closeup_img(close_path)
    _blurred_wide_img(blur_path)

    photos = [
        Photo(id="P001", path=str(close_path), room="Kitchen",
              source_video="walk.mp4"),
        Photo(id="P002", path=str(wide_path), room="Kitchen",
              source_video="walk.mp4"),
        Photo(id="P003", path=str(blur_path), room="Kitchen",
              source_video="walk.mp4"),
    ]
    curate({"Kitchen": photos}, tmp_path, tmp_path / "work")

    assert photos[1].hero == 1          # wide balanced cover
    assert photos[0].hero != 1          # object fill never rank 1
    assert photos[2].hero != 1          # blur never rank 1

    with Image.open(wide_path) as im:
        g = im.convert("L")
    with Image.open(close_path) as im:
        close_g = im.convert("L")
    assert centre_border_ratio(close_g) > 3.0
    assert smooth_fraction(close_g) < 0.97 or sharpness(close_g) >= sharpness(g)


def test_cover_gate_helpers_on_synthetics(tmp_path):
    wide_path = tmp_path / "wide.jpg"
    close_path = tmp_path / "close.jpg"
    _wide_balanced_img(wide_path)
    _corner_closeup_img(close_path)
    with Image.open(wide_path) as im:
        wide_g = im.convert("L")
    with Image.open(close_path) as im:
        close_g = im.convert("L")
    assert smooth_fraction(wide_g) < 0.97
    assert centre_border_ratio(close_g) > centre_border_ratio(wide_g)
    assert 0.0 <= exposure_clipped_fraction(wide_g) <= 1.0


HERO_GOLD = (Path(__file__).resolve().parents[1]
             / "evals/fixtures/own-property/hero-gold-dense-anchor.json")
HERO_METRICS = (Path(__file__).resolve().parents[1]
                / "evals/fixtures/own-property/hero-dense-detect-metrics.json")


def test_two_tier_eligibility_flags_on_curate(tmp_path):
    """ML-E3: describe permissive, presentation uses E4 gates."""
    from homeinventory.curate import tier_eligibility

    photos = [_frame(tmp_path, i, seed=i, blur=4.0 if i % 3 == 0 else 0.0)
              for i in range(9)]
    curate({"Kitchen": photos}, tmp_path, tmp_path / "work")
    assert all(p.describe_eligible is True for p in photos)
    assert any(p.presentation_eligible is False for p in photos)
    assert any(p.presentation_eligible is True for p in photos)
    # tier helper mirrors gate logic
    assert tier_eligibility(10.0, 0.5, 2.0, 0.05,
                            room_median=50.0, room_p25=20.0) == (True, False)


def test_linear_iqa_score_dot_product():
    from homeinventory.curate import linear_iqa_score

    weights = {
        "features": ["bias", "establishing"],
        "weights": [0.5, 2.0],
    }
    assert linear_iqa_score({"bias": 1.0, "establishing": 0.8}, weights) == 2.1


def _frozen_hero_benchmark():
    """Return gold + rank 1 from the same immutable benchmark run."""
    gold, manifest = load_gold_document(HERO_GOLD)
    assert manifest is not None
    metrics = json.loads(HERO_METRICS.read_text(encoding="utf-8"))
    assert metrics["benchmark_id"] == gold["benchmark_id"]
    assert set(metrics["rank1"]) == set(gold["rooms"])
    return gold["rooms"], metrics["rank1"]


def test_rank1_is_acceptable_on_compatible_hero_benchmark():
    """Every room cover must belong to its human-approved acceptable set."""
    rooms, rank1 = _frozen_hero_benchmark()
    misses = {
        room_name: rank1.get(room_name)
        for room_name, spec in rooms.items()
        if rank1.get(room_name) not in acceptable_frames(spec)
    }
    assert not misses, f"unacceptable rank-1 covers: {misses}"


def test_rank1_matches_hero_preference_on_compatible_benchmark():
    """Preference regression lock (docs/18 pass bar: exact top 1 ≥7/10)."""
    rooms, rank1 = _frozen_hero_benchmark()
    hits = sum(
        rank1.get(room_name) == preferred_frames(spec)[0]
        for room_name, spec in rooms.items()
    )
    assert hits >= 7, f"preferred rank-1 hit {hits}/{len(rooms)}"


def test_frozen_gold_pinning_uses_dense_anchor_not_mutable_report():
    """CI-safe: rank-1 contract is pinned to immutable fixtures, not report/."""
    gold, manifest = load_gold_document(HERO_GOLD)
    metrics = json.loads(HERO_METRICS.read_text(encoding="utf-8"))
    assert gold["candidate_manifest"] == "hero-candidates-dense-anchor.json"
    assert manifest is not None
    assert manifest["frame_count"] == 145
    assert metrics["rank1"]["Kitchen"] == "IMG_5512_f004023.jpg"
    assert set(metrics["rank1"]) == set(gold["rooms"])


def test_no_confident_cover_flags_review_required(tmp_path):
    """Low-quality rank-1 is kept but marked review_required, not silent."""
    blur_path = tmp_path / "blur.jpg"
    wide_path = tmp_path / "wide.jpg"
    _blurred_wide_img(blur_path)
    _wide_balanced_img(wide_path)
    photos = [
        Photo(id="P001", path=str(blur_path), room="Kitchen",
              source_video="walk.mp4", hero=1, quality=0.1,
              presentation_eligible=False),
        Photo(id="P002", path=str(wide_path), room="Kitchen",
              source_video="walk.mp4", hero=2, quality=0.9,
              presentation_eligible=True),
    ]
    establishing = {p.id: frame_quality(Path(p.path))[2] for p in photos}
    from homeinventory.curate import _cover_metrics
    cover = {p.id: _cover_metrics(Path(p.path)) for p in photos}
    status, reason, photo_id = assess_rank1_cover(
        "Kitchen", photos, establishing, cover)
    assert status == "review_required"
    assert photo_id == "P001"
    assert "low_quality" in reason or "fails_presentation_gates" in reason


def test_semantic_wrong_room_detection_flags_review_required():
    """Rank-1 with strong wrong-room detections is flagged, not trusted."""
    kitchen = Photo(id="P001", path="kitchen.jpg", room="Kitchen", hero=1,
                    quality=0.8, source_video="walk.mp4",
                    presentation_eligible=True)
    establishing = {"P001": 0.6}
    cover = {"P001": (100.0, 0.2, 1.5, 0.02)}
    detections = {
        "P001": [Detection("toilet", 0.9, (0, 0, 10, 10)),
                 Detection("shower", 0.8, (0, 0, 10, 10))],
    }
    status, reason, photo_id = assess_rank1_cover(
        "Kitchen", [kitchen], establishing, cover, detections)
    assert status == "review_required"
    assert photo_id == "P001"
    assert "wrong_room_detections" in reason


def test_finalize_room_covers_persists_curation_json(tmp_path):
    wide_path = tmp_path / "wide.jpg"
    close_path = tmp_path / "close.jpg"
    _wide_balanced_img(wide_path)
    _corner_closeup_img(close_path)
    photos = [
        Photo(id="P001", path=str(close_path), room="Kitchen",
              source_video="walk.mp4"),
        Photo(id="P002", path=str(wide_path), room="Kitchen",
              source_video="walk.mp4"),
    ]
    curate({"Kitchen": photos}, tmp_path, tmp_path / "work")
    statuses = finalize_room_covers(
        {"Kitchen": photos}, tmp_path, tmp_path / "work")
    assert statuses["Kitchen"]["status"] in ("confident", "review_required")
    saved = load_cover_status(tmp_path / "work")
    assert saved["Kitchen"]["photo_id"] in {"P001", "P002"}
    room = Room(name="Kitchen", photos=photos)
    apply_room_cover_status(room, statuses["Kitchen"])
    assert room.cover_status == statuses["Kitchen"]["status"]


def test_wide_balanced_frame_wins_hero_rank_one(tmp_path):
    wide_path = tmp_path / "wide.jpg"
    close_path = tmp_path / "close.jpg"
    _wide_balanced_img(wide_path)
    _corner_closeup_img(close_path)
    photos = [
        Photo(id="P001", path=str(close_path), room="Living Room",
              source_video="walk.mp4"),
        Photo(id="P002", path=str(wide_path), room="Living Room",
              source_video="walk.mp4"),
    ]
    curate({"Living Room": photos}, tmp_path, tmp_path / "work")
    assert photos[1].hero == 1
    assert photos[0].hero != 1
    _, _, wide_est = frame_quality(wide_path)
    _, _, close_est = frame_quality(close_path)
    assert wide_est > close_est


def test_curate_only_reruns_curation_without_describe(tmp_path):
    """curate-only reloads inventory.json, re-elects heroes, saves + renders."""
    cap = tmp_path / "capture"
    out = tmp_path / "report"
    n = 8
    photos = []
    for i in range(n):
        rel = f"Kitchen/walk_f{i:06d}.jpg"
        _noise_img(cap / rel, seed=i, blur=4.0 if i % 2 else 0.0)
        photos.append({
            "id": f"P{i:03d}", "path": rel, "room": "Kitchen",
            "source_video": "walk.mp4", "hero": 99, "quality": 0.001,
        })
    out.mkdir(parents=True)
    (out / "work").mkdir()
    (out / "inventory.json").write_text(json.dumps({
        "property_address": "",
        "rooms": [{"name": "Kitchen", "summary": "", "items": [], "photos": photos}],
    }), encoding="utf-8")

    assert main(["curate-only", str(cap), "-o", str(out), "--no-pdf"]) == 0
    inv2 = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    photos2 = inv2["rooms"][0]["photos"]
    heroes = [p for p in photos2 if p["hero"]]
    assert heroes and len(heroes) <= 6
    blurred = {photos2[i]["id"] for i in range(n) if i % 2}
    assert not {p["id"] for p in heroes} & blurred
    assert (out / "inventory.html").is_file()
