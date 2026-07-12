from homeinventory.detect import Detection, build_item_queries
from homeinventory.merge import (accept_crop, attach_detector_crops,
                                 crop_review_queue, ground_missing_crops, merge_items,
                                 merge_room_with_prior, reject_crop, room_code)
from homeinventory.schema import Item, Photo, Room


def make(name, **kw):
    return Item(id="", name=name, **kw)


def test_attach_detector_crops_is_conservative():
    """docs/15 M4: a VLM item borrows a YOLOE close-up only when the label's
    words all appear in its name AND the detection is in a photo it cites."""
    items = [
        Item(id="K-001", name="Three-seat sofa", photo_ids=["P001"]),
        Item(id="K-002", name="Coffee table", photo_ids=["P002"]),
        Item(id="K-003", name="Radiator", photo_ids=["P001"],
             crop_path="mine.jpg"),
    ]
    dets = {"P001": [
        Detection(label="sofa", confidence=0.6, box=(0, 0, 9, 9),
                  crop_path="weak-sofa.jpg"),
        Detection(label="sofa", confidence=0.9, box=(0, 0, 9, 9),
                  crop_path="best-sofa.jpg"),
        Detection(label="table", confidence=0.9, box=(0, 0, 9, 9),
                  crop_path="table.jpg"),
        Detection(label="radiator", confidence=0.9, box=(0, 0, 9, 9),
                  crop_path="radiator.jpg"),
    ]}
    attach_detector_crops(items, dets)
    assert items[0].crop_path == "best-sofa.jpg"   # highest confidence match
    assert items[0].crop_status == "auto"
    assert items[1].crop_path is None    # "table" seen only in an uncited photo
    assert items[2].crop_path == "mine.jpg"        # never overwritten


def test_attach_detector_crops_accepts_structural_aliases():
    item = Item(id="HAL-001", name="Timber staircase with grey carpet",
                photo_ids=["P001"])
    dets = {"P001": [
        Detection(label="stairs", confidence=0.72, box=(0, 0, 100, 100),
                  crop_path="stairs.jpg"),
    ]}
    attach_detector_crops([item], dets)
    assert item.crop_path == "stairs.jpg"
    assert item.crop_status == "auto"


def test_build_item_queries_covers_schedule_synonyms():
    qs = build_item_queries("Pendant light fittings")
    assert "ceiling light" in qs or "light fitting" in qs
    qs2 = build_item_queries("Canvas wall art")
    assert "picture frame" in qs2 or "painting" in qs2
    qs3 = build_item_queries("Skirting boards")
    assert "skirting board" in qs3


def test_attach_detector_crops_item_conditioned_synonyms():
    """Schedule wording ≠ detector label: score existing boxes via queries."""
    pendant = Item(id="LIV-001", name="Pendant light fittings",
                   photo_ids=["P001"])
    art = Item(id="LIV-002", name="Canvas wall art", photo_ids=["P001"])
    stairs = Item(id="HAL-001", name="Staircase", photo_ids=["P001"])
    # Wrong pairing must not attach: skirting ≠ flooring.
    skirting = Item(id="HAL-002", name="Skirting boards", photo_ids=["P001"])
    dets = {"P001": [
        Detection(label="ceiling light", confidence=0.88, box=(0, 0, 40, 40),
                  crop_path="light.jpg"),
        Detection(label="picture frame", confidence=0.81, box=(0, 0, 40, 40),
                  crop_path="art.jpg"),
        Detection(label="stairwell", confidence=0.77, box=(0, 0, 40, 40),
                  crop_path="stairs.jpg"),
        Detection(label="flooring", confidence=0.95, box=(0, 0, 40, 40),
                  crop_path="floor.jpg"),
    ]}
    attach_detector_crops([pendant, art, stairs, skirting], dets)
    assert pendant.crop_path == "light.jpg"
    assert pendant.crop_status == "auto"
    assert pendant.crop_confidence and pendant.crop_confidence >= 0.72
    assert art.crop_path == "art.jpg"
    assert stairs.crop_path == "stairs.jpg"
    assert skirting.crop_path is None  # flooring must not steal skirting


def test_attach_detector_crops_proposes_mid_confidence():
    item = Item(id="LIV-003", name="Canvas wall art", photo_ids=["P001"])
    dets = {"P001": [
        Detection(label="picture frame", confidence=0.55, box=(0, 0, 40, 40),
                  crop_path="maybe-art.jpg"),
    ]}
    attach_detector_crops([item], dets)
    assert item.crop_path == "maybe-art.jpg"
    assert item.crop_status == "proposed"
    assert crop_review_queue([item]) == [item]
    accept_crop(item)
    assert item.crop_status == "accepted"
    item.crop_status = "proposed"
    reject_crop(item)
    assert item.crop_path is None
    assert item.crop_status == "rejected"


def test_grounding_does_not_auto_attach_weak_literal_query(tmp_path):
    """Fresh item-conditioned labels still have to clear the auto threshold."""
    item = Item(id="HAL-001", name="Staircase", photo_ids=["P001"])

    class StubDetector:
        available = True
        mode = "text"

        def detect_queries(self, path, queries, crops_dir=None, stem_suffix=""):
            return [Detection(label="staircase", confidence=0.51,
                              box=(0, 0, 80, 80), crop_path="weak.jpg")]

    attached = ground_missing_crops(
        [item], {"P001": tmp_path / "P001.jpg"}, StubDetector(), tmp_path
    )
    assert attached == 1
    assert item.crop_status == "proposed"
    assert item.crop_confidence == 0.51


def test_attach_blocks_known_false_pairs():
    """Reuse det_match blocklist so ceiling light never grounds to ceiling."""
    item = Item(id="KIT-001", name="Ceiling", photo_ids=["P001"])
    dets = {"P001": [
        Detection(label="ceiling light", confidence=0.99, box=(0, 0, 40, 40),
                  crop_path="spot.jpg"),
    ]}
    attach_detector_crops([item], dets)
    assert item.crop_path is None


def test_attach_rejects_fuzzy_false_positives():
    """Query-membership gate: no bare difflib/substring proposes."""
    bedside = Item(id="BED-001", name="Bedside lamps", photo_ids=["P001"])
    dining = Item(id="LIV-001", name="Dining table", photo_ids=["P001"])
    smoke = Item(id="KIT-001", name="Smoke/heat alarm", photo_ids=["P001"])
    radiator = Item(id="BAT-001", name="Towel Radiator", photo_ids=["P001"])
    dets = {"P001": [
        Detection(label="bed", confidence=0.95, box=(0, 0, 40, 40),
                  crop_path="bed.jpg"),
        Detection(label="coffee table", confidence=0.9, box=(0, 0, 40, 40),
                  crop_path="coffee.jpg"),
        Detection(label="lamp", confidence=0.9, box=(0, 0, 40, 40),
                  crop_path="lamp.jpg"),
        Detection(label="toilet", confidence=0.9, box=(0, 0, 40, 40),
                  crop_path="toilet.jpg"),
    ]}
    attach_detector_crops([bedside, dining, smoke, radiator], dets)
    assert bedside.crop_path == "lamp.jpg"  # lamp ∈ bedside queries
    assert dining.crop_path is None         # coffee table must not steal
    assert smoke.crop_path is None          # lamp must not ground to smoke
    assert radiator.crop_path is None       # toilet must not ground to radiator


def test_build_item_queries_bedside_includes_lamp():
    qs = build_item_queries("Bedside lamps")
    assert "lamp" in qs


def test_merge_duplicates_worst_grade_and_union():
    a = make("Sofa", condition="good", defects=["scuff"],
             photo_ids=["P001"], description="short")
    b = make("sofa", condition="poor", defects=["scuff", "tear"],
             photo_ids=["P002"], description="a longer description")
    out = merge_items([a, b], "LIV")
    assert len(out) == 1
    m = out[0]
    assert m.id == "LIV-001"
    assert m.condition == "poor"          # worst grade wins (deposit-conservative)
    assert m.defects == ["scuff", "tear"]
    assert m.photo_ids == ["P001", "P002"]
    assert m.description == "a longer description"


def test_merge_keeps_distinct_items_in_order():
    out = merge_items([make("Sofa"), make("Coffee table")], "LIV")
    assert [i.id for i in out] == ["LIV-001", "LIV-002"]
    assert [i.name for i in out] == ["Sofa", "Coffee table"]


def test_merge_quantity_takes_max():
    out = merge_items([make("Chair", quantity=2), make("chair", quantity=4)], "DIN")
    assert out[0].quantity == 4


def test_merge_collapses_descriptive_variants_of_same_item():
    # the cross-batch duplication signature: the same structural element
    # described with different descriptor words across batches must merge.
    out = merge_items([
        make("Walls (Cream Emulsion)", defects=["scuff lower left"]),
        make("Walls (painted white/magnolia emulsion)", defects=["chip to join"]),
        make("Walls"),
        make("Flooring (Light Wood-effect Laminate/Vinyl)"),
        make("Flooring (light oak effect laminate)"),
    ], "LIV")
    names = [i.name for i in out]
    assert sum(n.lower().startswith("walls") for n in names) == 1
    assert sum(n.lower().startswith("flooring") for n in names) == 1
    wall = next(i for i in out if i.name.lower().startswith("walls"))
    assert "scuff lower left" in wall.defects and "chip to join" in wall.defects


def test_merge_does_not_collapse_items_with_different_head_nouns():
    # "door" must NOT absorb "door handle and lockset": the longer name adds
    # a new noun, so they are distinct items a clerk records separately.
    out = merge_items([
        make("Door"),
        make("Door Handle and Lockset"),
        make("Door Hinges"),
    ], "HALL")
    assert len(out) == 3
    assert {i.name for i in out} == {"Door", "Door Handle and Lockset",
                                     "Door Hinges"}


def test_room_code_collisions():
    used = set()
    assert room_code("Bedroom 1", used) == "BED"
    assert room_code("Bedroom 2", used) == "BED2"
    assert room_code("Bedroom 3", used) == "BED3"
    assert room_code("公寓", used) == "RM"  # no latin letters -> fallback


def test_merge_room_with_prior_keeps_reviewed_and_added_items():
    prior = Room(name="Kitchen", items=[
        Item(id="KIT-001", name="Sofa", reviewed=True, condition="good",
             description="Human attested grey fabric"),
        Item(id="KIT-002", name="Cast-iron skillet", added_by="C. Brown",
             reviewed=True, condition="good"),
        Item(id="KIT-003", name="Window", condition="fair"),
    ], photos=[Photo(id="P001", path="Kitchen/a.jpg", room="Kitchen")])
    fresh = Room(name="Kitchen", summary="new summary",
                 items=[make("Sofa", condition="poor", description="AI draft"),
                        make("Table")],
                 photos=[Photo(id="P001", path="Kitchen/a.jpg", room="Kitchen"),
                         Photo(id="P002", path="Kitchen/b.jpg", room="Kitchen")])
    out = merge_room_with_prior(prior, fresh, "KIT")
    by_name = {i.name: i for i in out.items}
    assert by_name["Sofa"].condition == "good"
    assert by_name["Sofa"].description == "Human attested grey fabric"
    assert by_name["Cast-iron skillet"].added_by == "C. Brown"
    assert by_name["Table"].condition is None
    assert out.summary == "new summary"
    assert {p.id for p in out.photos} == {"P001", "P002"}


def test_merge_room_with_prior_applies_review_overlay():
    prior = Room(name="Kitchen", items=[
        Item(id="KIT-001", name="TV unit",
             rejected_defects=["surface scratch to top right corner"],
             comments=[{"author": "T", "role": "tenant", "text": "sticker",
                        "at": "2026-06-10"}]),
    ], photos=[])
    fresh = Room(name="Kitchen", summary="s",
                 items=[make("TV unit", defects=["surface scratch to top right corner",
                                                  "chip to edge"])],
                 photos=[])
    out = merge_room_with_prior(prior, fresh, "KIT")
    item = out.items[0]
    assert item.rejected_defects == ["surface scratch to top right corner"]
    assert item.comments[0]["text"] == "sticker"
    assert "chip to edge" in item.defects
