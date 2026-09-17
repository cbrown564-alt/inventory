from homeinventory.ontology import (ITEM_TYPE_BY_KEY, ITEM_TYPE_KEYS,
                                    ONTOLOGY_VERSION, canonicalize_name,
                                    category_for)
from homeinventory.schema import Item


def test_ontology_has_broad_but_bounded_inventory_vocabulary():
    assert ONTOLOGY_VERSION == "tenancy-items-v1"
    assert 80 <= len(ITEM_TYPE_KEYS) <= 140
    assert len(ITEM_TYPE_KEYS) == len(set(ITEM_TYPE_KEYS))
    assert "other" in ITEM_TYPE_BY_KEY


def test_common_synonyms_collapse_to_same_machine_identity():
    assert canonicalize_name("Extractor hood") == "extractor_hood"
    assert canonicalize_name("Cooker hood") == "extractor_hood"
    assert canonicalize_name("Pedestal basin") == "basin"
    assert canonicalize_name("Wash basin") == "basin"
    assert canonicalize_name("Fridge-freezer") == "refrigerator"
    assert canonicalize_name("Waste bin") == "bin"


def test_material_and_colour_do_not_create_identity():
    assert canonicalize_name("White ceramic pedestal basin") == "basin"
    assert canonicalize_name("Grey fabric three seat sofa") == "sofa"


def test_materially_different_items_do_not_collapse():
    assert canonicalize_name("Bread bin") == "bread_bin"
    assert canonicalize_name("Waste bin") == "bin"
    assert canonicalize_name("Bedside table") == "bedside_table"
    assert canonicalize_name("Dining table") == "table"
    assert canonicalize_name("Door") == "door"
    assert canonicalize_name("Door handle") == "door_handle"


def test_unknown_name_abstains_instead_of_guessing():
    assert canonicalize_name("Mystery bespoke object") is None


def test_item_normalise_backfills_identity_without_overwriting_prose():
    item = Item(id="X", name="White ceramic pedestal basin", category="other").normalise()
    assert item.name == "White ceramic pedestal basin"
    assert item.item_type == "basin"
    assert item.category == category_for("basin")
    assert item.ontology_version == ONTOLOGY_VERSION


def test_explicit_valid_identity_is_authoritative():
    item = Item(id="X", name="Unusual wording", item_type="radiator", category="other").normalise()
    assert item.item_type == "radiator"
    assert item.category == "fixture"
