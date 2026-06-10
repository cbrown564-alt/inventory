from homeinventory.merge import merge_items, room_code
from homeinventory.schema import Item


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
