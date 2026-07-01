from homeinventory.merge import merge_items, merge_room_with_prior, room_code
from homeinventory.schema import Item, Photo, Room


def make(name, **kw):
    return Item(id="", name=name, **kw)


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
