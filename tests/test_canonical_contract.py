from homeinventory.canonical_contract import (
    DECOMPOSITION_RULES, build_canonical_item_schema, validate_decomposition,
)
from homeinventory.ontology import ITEM_TYPE_KEYS, ONTOLOGY_VERSION


def test_contract_requires_canonical_identity_and_separates_display_prose():
    schema = build_canonical_item_schema()
    item = schema["properties"]["items"]["items"]
    assert item["properties"]["item_type"]["enum"] == list(ITEM_TYPE_KEYS)
    assert "item_type" in item["required"]
    assert "display_name" in item["required"]
    assert "subtype" in item["required"]
    assert "attributes" in item["required"]
    assert "instance_key" in item["required"]
    assert schema["properties"]["ontology_version"]["const"] == ONTOLOGY_VERSION


def test_contract_can_omit_tenancy_value_band_for_other_use_cases():
    schema = build_canonical_item_schema(include_value_band=False)
    item = schema["properties"]["items"]["items"]
    assert "est_value_band" not in item["properties"]
    assert "est_value_band" not in item["required"]


def test_decomposition_rules_cover_known_instability_modes():
    assert "door vs door_frame vs door_handle" in DECOMPOSITION_RULES
    assert "window and sill" in DECOMPOSITION_RULES
    assert "patio doors and windows" in DECOMPOSITION_RULES
    assert "pedestal basin remains" in DECOMPOSITION_RULES
    assert "instance_key" in DECOMPOSITION_RULES
    assert "other" in DECOMPOSITION_RULES


def test_validator_accepts_minimal_valid_identity_record():
    payload = {
        "ontology_version": ONTOLOGY_VERSION,
        "items": [{"item_type": "basin", "display_name": "White pedestal basin", "quantity": 1}],
    }
    assert validate_decomposition(payload) == []


def test_validator_rejects_unknown_identity_and_bad_quantity():
    payload = {
        "ontology_version": ONTOLOGY_VERSION,
        "items": [{"item_type": "pedestal_basin", "display_name": "Pedestal basin", "quantity": 0}],
    }
    errors = validate_decomposition(payload)
    assert any("item_type" in e for e in errors)
    assert any("quantity" in e for e in errors)
