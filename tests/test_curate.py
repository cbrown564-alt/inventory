"""Curation (docs/15 M2/M3): score frames, elect a small distinct hero set,
honour reviewer overrides across rebuilds, and never lose cited evidence."""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from homeinventory.cli import main
from homeinventory.curate import (apply_override, curate, establishing_score,
                                  frame_quality, hero_budget, load_overrides,
                                  override_key, save_override)
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
    """Synthetic close-up: sharp detail in one quadrant only."""
    w, h = 320, 180
    im = Image.new("L", (w, h), 30)          # dark surround — distinct thumb
    detail = Image.new("L", (w // 2, h // 2))
    detail.putdata([random.Random(i).randrange(256) for i in range(w // 2 * h // 2)])
    im.paste(detail, (w // 2, h // 2))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=92)


def test_establishing_score_prefers_wide_balanced_frame():
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
    close.paste(patch, (160, 90))

    wide_score = establishing_score(wide)
    close_score = establishing_score(close)
    assert wide_score > close_score
    assert 0.0 <= wide_score <= 1.0
    assert 0.0 <= close_score <= 1.0


def test_establishing_score_uniform_frame_is_neutral():
    flat = Image.new("L", (160, 90), 128)
    assert establishing_score(flat) == 1.0


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
    assert photos[0].hero == 2
    _, _, wide_est = frame_quality(wide_path)
    _, _, close_est = frame_quality(close_path)
    assert wide_est > close_est
