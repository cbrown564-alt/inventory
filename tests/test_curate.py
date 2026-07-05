"""Curation (docs/15 M2/M3): score frames, elect a small distinct hero set,
honour reviewer overrides across rebuilds, and never lose cited evidence."""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from homeinventory.cli import main
from homeinventory.curate import (apply_override, centre_border_ratio, curate,
                                  establishing_score, exposure_clipped_fraction,
                                  frame_quality, hero_budget, load_overrides,
                                  override_key, save_override, sharpness,
                                  smooth_fraction)
from homeinventory.report import render
from homeinventory.schema import Inventory, Item, Photo, Room


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


HERO_GOLD = Path(__file__).resolve().parents[1] / "evals/fixtures/own-property/hero-gold.json"


def test_rank1_matches_hero_gold_when_fixture_present():
    """Regression lock when hero-gold.json exists (docs/18 pass bar ≥7/9)."""
    if not HERO_GOLD.is_file():
        return
    gold = json.loads(HERO_GOLD.read_text(encoding="utf-8"))
    report = Path(__file__).resolve().parents[1] / "report"
    inv_path = report / "inventory.json"
    if not inv_path.is_file():
        return
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    hits = 0
    rooms = gold.get("rooms", {})
    for room_name, spec in rooms.items():
        gold_top = (spec.get("top") or [None])[0]
        if not gold_top:
            continue
        room = next((r for r in inv["rooms"] if r["name"] == room_name), None)
        if not room:
            continue
        rank1 = min((p for p in room["photos"] if p.get("hero")),
                    key=lambda p: p["hero"], default=None)
        if rank1 and Path(rank1["path"]).name == gold_top:
            hits += 1
    assert hits >= 7, f"rank-1 hit {hits}/{len(rooms)} — re-curate report/ and update gold"


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
