"""Guards for the docs/10 product-quality pass: the evidence chain in the
deliverable (item→photo refs, Appendix B photo IDs, printed defect regions,
path hygiene) and report polish (category grouping, escaping, date format,
photo re-encode caching)."""

from pathlib import Path

from PIL import Image

from homeinventory.report import _display_path, human_date, render
from homeinventory.schema import Inventory, Item, Photo, Room


def _img(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), "white").save(path)


def _fixture(tmp_path) -> tuple[Inventory, Path, Path]:
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Kitchen" / "k2.jpg")
    inv = Inventory(
        property_address="1 Test Street",
        inspected_at="2026-07-03",
        rooms=[Room(name="Kitchen", items=[
            Item(id="KIT-001", name="Worktop", category="fixture",
                 condition="good", photo_ids=["P001", "P002"],
                 defects=["chip to front edge"],
                 defect_regions=[{"defect": "chip to front edge",
                                  "photo_id": "P001",
                                  "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2}]),
            Item(id="KIT-002", name="Framed print", category="decor",
                 condition="good", photo_ids=["P002"]),
            Item(id="KIT-003", name="Ceiling light", category="fixture",
                 condition="good", photo_ids=["P001"]),
        ], photos=[
            Photo(id="P001", path="Kitchen/k1.jpg", room="Kitchen",
                  sha256="a" * 64),
            Photo(id="P002", path="Kitchen/k2.jpg", room="Kitchen",
                  sha256="b" * 64),
        ])])
    return inv, cap, tmp_path / "report"


def test_human_date():
    assert human_date("2026-07-03") == "3 July 2026"
    assert human_date("2026-07-03T10:00:00+00:00") == "3 July 2026"
    assert human_date("") == ""
    assert human_date("not a date") == "not a date"


def test_display_path_never_absolute(tmp_path):
    cap, out = tmp_path / "capture", tmp_path / "report"
    frame = out / "work" / "frames" / "Kitchen" / "k_f000001.jpg"
    assert _display_path(str(frame), cap, out) == \
        "work/frames/Kitchen/k_f000001.jpg"
    assert _display_path("Kitchen/k1.jpg", cap, out) == "Kitchen/k1.jpg"
    # a path under neither root still yields something relative
    assert not _display_path("/somewhere/else/room/x.jpg", cap, out
                             ).startswith("/")


def test_print_cells_cite_evidence(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert "Evidence: P001, P002" in html      # item -> photo refs in print


def test_appendix_b_captions_carry_photo_ids(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert "P001 — Ref 2" in html              # not the old bare room number
    assert "Ref #" not in html


def test_defect_regions_print_in_appendix(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    appendix = html.split('id="appendix-photos"', 1)[1]
    assert 'class="region"' in appendix        # pins reach the PDF layout
    assert "annotated" in appendix             # natural-aspect frame for pins


def test_appendix_a_full_hashes_and_relative_paths(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    # simulate a video keyframe stored with an absolute path (the M2 shape)
    frame = out / "work" / "frames" / "Kitchen" / "k_f000001.jpg"
    _img(frame)
    inv.rooms[0].photos.append(Photo(
        id="P003", path=str(frame), room="Kitchen", sha256="c" * 64,
        source_video="/somewhere/on/disk/Kitchen/walk.mp4"))
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert str(tmp_path) not in html           # no build-machine paths at all
    assert "a" * 64 in html                    # full hash, not a truncation
    assert "frame of walk.mp4" in html         # provenance without the path


def test_category_headings_never_repeat(tmp_path):
    inv, cap, out = _fixture(tmp_path)        # fixture, decor, fixture order
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert html.count("Fixtures &amp; fittings") == 1


def test_item_fields_are_escaped(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    inv.rooms[0].items[0].name = "<script>alert(1)</script>"
    inv.rooms[0].items[0].description = "<img src=x onerror=alert(1)>"
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html


def test_cover_uses_human_dates_and_hides_empty_rows(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    inv.inspected_by = ""                      # empty -> row hidden, not "—"
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert "3 July 2026" in html
    assert "Prepared by" not in html


def test_final_issue_strips_review_instrument(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    inv.rooms[0].items[0].reviewed = True
    inv.rooms[0].items.append(Item(id="KIT-004", name="Phantom lamp",
                                   rejected=True))
    outputs = render(inv, cap, out, pdf=False)
    live = outputs["html"].read_text(encoding="utf-8")
    issue = outputs["issue"].read_text(encoding="utf-8")
    assert 'id="hi-data"' in live and "Review docket" in live
    assert 'id="hi-data"' not in issue         # no embedded payload
    assert "Review docket" not in issue        # no instrument layer
    assert "review-flag ok" not in issue       # no review-state chips
    assert "review-flag pending" not in issue
    assert "review app" not in issue           # no reviewer-facing copy
    assert "reviewer rejected" in issue        # transparency promise kept


def test_appendix_b_uses_print_tier(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    # a big source so the two tiers actually differ
    Image.new("RGB", (1600, 1200), "white").save(cap / "Kitchen" / "k1.jpg")
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    appendix = html.split('id="appendix-photos"', 1)[1]
    assert "photos/print/P001.jpg" in appendix
    with Image.open(out / "photos" / "P001.jpg") as full:
        assert max(full.size) == 1400
    with Image.open(out / "photos" / "print" / "P001.jpg") as small:
        assert max(small.size) <= 900
    # the screen strips and lightbox keep the full tier
    assert 'src="photos/P001.jpg"' in html.split('id="appendix-photos"')[0]


def test_appendix_b_prunes_near_duplicate_frames(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    for i in (1, 2, 3):
        _img(cap / "Kitchen" / f"walk_f{i}.jpg")   # identical frames
    inv = Inventory(
        inspected_at="2026-07-03",
        rooms=[Room(name="Kitchen", items=[
            Item(id="KIT-001", name="Worktop", condition="good",
                 photo_ids=["P001", "P003"]),
        ], photos=[
            Photo(id="P001", path="Kitchen/k1.jpg", room="Kitchen"),
            Photo(id="P002", path="Kitchen/walk_f1.jpg", room="Kitchen",
                  source_video="walk.mp4"),
            Photo(id="P003", path="Kitchen/walk_f2.jpg", room="Kitchen",
                  source_video="walk.mp4"),
            Photo(id="P004", path="Kitchen/walk_f3.jpg", room="Kitchen",
                  source_video="walk.mp4"),
        ])])
    html = render(inv, cap, tmp_path / "report",
                  pdf=False)["html"].read_text(encoding="utf-8")
    appendix = html.split('id="appendix-photos"', 1)[1]
    assert 'data-photo-id="P002"' in appendix   # first frame of the video
    assert 'data-photo-id="P003"' in appendix   # near-duplicate but CITED
    assert 'data-photo-id="P004"' not in appendix  # uncited near-dup pruned
    assert "listed with its checksum in Appendix A" in appendix  # honest note
    # every file still listed with its hash in Appendix A
    manifest = html.split('id="appendix-manifest"', 1)[1]
    for pid in ("P002", "P003", "P004"):
        assert f"<td>{pid}</td>" in manifest


def test_photo_export_cache_skips_unchanged(tmp_path):
    inv, cap, out = _fixture(tmp_path)
    render(inv, cap, out, pdf=False)
    exported = out / "photos" / "P001.jpg"
    first = exported.stat().st_mtime_ns
    render(inv, cap, out, pdf=False)
    assert exported.stat().st_mtime_ns == first   # not re-encoded

    # touching the source invalidates the cache
    src = cap / "Kitchen" / "k1.jpg"
    import os
    os.utime(src, ns=(first + 10_000_000_000, first + 10_000_000_000))
    render(inv, cap, out, pdf=False)
    assert exported.stat().st_mtime_ns != first
