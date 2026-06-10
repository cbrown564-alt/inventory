from homeinventory.schema import (CONDITION_GRADES, Inventory, Item, Photo,
                                  Room, _norm_grade)


def test_norm_grade_aliases():
    assert _norm_grade("Very Good", CONDITION_GRADES) == "excellent"
    assert _norm_grade("damaged", CONDITION_GRADES) == "poor"
    assert _norm_grade("GOOD", CONDITION_GRADES) == "good"
    assert _norm_grade("sparkly", CONDITION_GRADES) is None
    assert _norm_grade(None, CONDITION_GRADES) is None


def test_item_normalise():
    it = Item(id="X", name="TV", category="banana", quantity=0, condition="ok")
    it.normalise()
    assert it.category == "other"
    assert it.quantity == 1
    assert it.condition == "fair"


def test_inventory_json_roundtrip_unicode():
    inv = Inventory(
        property_address="Flat 2 — £950pcm",
        rooms=[Room(
            name="Living Room",
            summary="café-style décor",
            items=[Item(id="LIV-001", name="Sofa", est_value_band="£250-1000")],
            photos=[Photo(id="P001", path="Living Room/a.jpg", room="Living Room")],
        )],
    )
    again = Inventory.from_json(inv.to_json())
    assert again.property_address == "Flat 2 — £950pcm"
    assert again.rooms[0].summary == "café-style décor"
    assert again.rooms[0].items[0].est_value_band == "£250-1000"
    assert again.rooms[0].photos[0].id == "P001"
