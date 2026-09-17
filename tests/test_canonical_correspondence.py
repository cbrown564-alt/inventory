from evals.synthetic.score_canonical_correspondence import _agreement, canonical_key
from homeinventory.compare import _norm_name


def test_canonical_key_collapses_safe_surface_synonyms():
    assert canonical_key("Pedestal basin") == "type:basin"
    assert canonical_key("Wash basin") == "type:basin"
    assert canonical_key("Cooker hood") == canonical_key("Extractor hood")


def test_unknowns_do_not_collapse_into_one_bucket():
    assert canonical_key("Mystery object alpha") != canonical_key("Mystery object beta")
    assert canonical_key("Mystery object alpha").startswith("surface:")


def test_canonical_agreement_can_remove_vocabulary_churn():
    a = ["Pedestal basin", "Cooker hood", "Waste bin"]
    b = ["Wash basin", "Extractor hood", "Waste bin"]
    exact = _agreement(a, b, _norm_name)
    canonical = _agreement(a, b, canonical_key)
    assert exact["agreement"] < 100.0
    assert canonical["agreement"] == 100.0
    assert canonical["churn"] == 0


def test_multiset_keeps_repeated_item_disagreement_visible():
    a = ["Dining chair", "Dining chair", "Dining chair", "Dining chair"]
    b = ["Chair", "Chair", "Chair"]
    canonical = _agreement(a, b, canonical_key)
    assert canonical["both"] == 3
    assert canonical["either"] == 4
    assert canonical["agreement"] == 75.0
    assert canonical["churn"] == 1


def test_materially_different_types_remain_distinct():
    assert canonical_key("Bread bin") != canonical_key("Waste bin")
    assert canonical_key("Door") != canonical_key("Door handle")
