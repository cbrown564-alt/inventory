"""Use-case profile registry and invariants."""

from __future__ import annotations

import pytest

from homeinventory.compare import (CLASSIFICATION_CLASSES as COMPARE_CLASSES,
                                   CLASS_LABELS as COMPARE_LABELS,
                                   RUBRIC_PROMPT as COMPARE_RUBRIC)
from homeinventory.schema import Inventory, Item, Room, cover_value, set_cover_value
from homeinventory.usecases import DEFAULT_USE_CASE, REGISTRY, get_use_case, use_case_for
from homeinventory.usecases.deepclean import DEEP_CLEAN
from homeinventory.usecases.tenancy import (CLASSIFICATION_CLASSES, CLASS_LABELS,
                                            CLASS_TONES, RUBRIC_PROMPT, SYSTEM_PROMPT,
                                            TENANCY)


def test_registry_lookup():
    assert DEFAULT_USE_CASE == "tenancy"
    assert set(REGISTRY) == {"tenancy", "deepclean"}
    assert get_use_case("tenancy") is TENANCY
    assert get_use_case("deepclean") is DEEP_CLEAN
    with pytest.raises(KeyError, match="unknown use case"):
        get_use_case("nope")


def test_use_case_for_reads_inventory_field():
    inv = Inventory(use_case="deepclean")
    assert use_case_for(inv) is DEEP_CLEAN
    blank = Inventory()
    assert use_case_for(blank) is TENANCY


@pytest.mark.parametrize("profile", [TENANCY, DEEP_CLEAN])
def test_profile_class_labels_cover_classes_and_unclassified(profile):
    for cls in profile.comparison.classes:
        assert cls in profile.comparison.class_labels
        assert cls in profile.comparison.class_tones
    assert "unclassified" in profile.comparison.class_labels
    assert "unclassified" in profile.comparison.class_tones


@pytest.mark.parametrize("profile", [TENANCY, DEEP_CLEAN])
def test_profile_session_keys(profile):
    assert 1 <= len(profile.sessions) <= 2
    keys = [s.key for s in profile.sessions]
    assert len(keys) == len(set(keys))
    labels = [s.label for s in profile.sessions]
    assert all(labels)


def test_tenancy_single_checkin_session():
    assert len(TENANCY.sessions) == 1
    assert TENANCY.sessions[0].key == "checkin"
    assert TENANCY.comparison.baseline == "Check-in"
    assert TENANCY.comparison.followup == "Check-out"


def test_deepclean_before_after_sessions():
    assert len(DEEP_CLEAN.sessions) == 2
    assert [s.key for s in DEEP_CLEAN.sessions] == ["before", "after"]
    assert DEEP_CLEAN.comparison.baseline == "Before"
    assert DEEP_CLEAN.comparison.followup == "After"
    assert DEEP_CLEAN.value_bands is None
    assert DEEP_CLEAN.summary_section_title == "Cleanliness Summary"


def test_cover_fields_resolve_on_blank_inventory():
    inv = Inventory()
    for field in TENANCY.cover_fields:
        assert cover_value(inv, field) == ""
    set_cover_value(inv, TENANCY.cover_fields[0], "1 Test Street")
    assert inv.property_address == "1 Test Street"
    customer_field = next(f for f in DEEP_CLEAN.cover_fields if f.name == "customer_name")
    set_cover_value(inv, customer_field, "Jane Doe")
    assert inv.parties["customer_name"] == "Jane Doe"
    assert cover_value(inv, customer_field) == "Jane Doe"


def test_tenancy_prompt_anchors_tds():
    assert "TDS" in SYSTEM_PROMPT
    assert "Scheme (TDS)" in SYSTEM_PROMPT


def test_tenancy_classes_match_compare_originals():
    assert list(CLASSIFICATION_CLASSES) == COMPARE_CLASSES
    assert CLASS_LABELS == COMPARE_LABELS
    assert RUBRIC_PROMPT == COMPARE_RUBRIC


def test_tenancy_gate_matches_spec():
    gate = TENANCY.comparison.gate
    assert gate({"grade_delta": None, "new_defects": []}) is False
    assert gate({"grade_delta": 1, "new_defects": []}) is True
    assert gate({"grade_delta": 0, "new_defects": ["chip"]}) is True


def test_deepclean_gate_fires_on_any_change():
    gate = DEEP_CLEAN.comparison.gate
    assert gate({"grade_delta": 0, "new_defects": [], "resolved_defects": [],
                 "checkin_cleanliness": "cleaned to domestic standard",
                 "checkout_cleanliness": "cleaned to domestic standard"}) is False
    assert gate({"grade_delta": 0, "new_defects": [], "resolved_defects": ["x"],
                 "checkin_cleanliness": None, "checkout_cleanliness": None}) is True
    assert gate({"grade_delta": -1, "new_defects": [], "resolved_defects": [],
                 "checkin_cleanliness": None, "checkout_cleanliness": None}) is True
    assert gate({"grade_delta": 0, "new_defects": [], "resolved_defects": [],
                 "checkin_cleanliness": "professionally cleaned",
                 "checkout_cleanliness": "requires cleaning"}) is True


def test_deepclean_summary_rows_one_per_room():
    inv = Inventory(rooms=[
        Room(name="Kitchen", items=[
            Item(id="K1", name="Floor", cleanliness="requires cleaning"),
            Item(id="K2", name="Worktop", cleanliness="requires cleaning"),
        ]),
        Room(name="Bathroom", items=[
            Item(id="B1", name="Tiles", cleanliness="professionally cleaned"),
        ]),
    ])
    rows = DEEP_CLEAN.summary_rows(inv)
    assert len(rows) == 2
    assert rows[0]["name"] == "Kitchen"
    assert "Requires cleaning" in rows[0]["condition"]
    assert rows[1]["name"] == "Bathroom"
    assert "Professionally cleaned" in rows[1]["condition"]


def test_build_item_schema_tenancy_has_est_value_band():
    from homeinventory.describe import build_item_schema

    schema = build_item_schema(TENANCY)
    item = schema["properties"]["items"]["items"]
    assert "est_value_band" in item["properties"]
    assert "est_value_band" in item["required"]
    desc = item["properties"]["description"]["description"]
    assert "inventory clerk" not in desc.lower()


def test_build_item_schema_deepclean_omits_est_value_band():
    from homeinventory.describe import build_item_schema

    schema = build_item_schema(DEEP_CLEAN)
    item = schema["properties"]["items"]["items"]
    assert "est_value_band" not in item["properties"]
    assert "est_value_band" not in item["required"]


def test_get_backend_deepclean_uses_cleaning_prompt(monkeypatch):
    from homeinventory.describe import get_backend

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    backend = get_backend("openai", use_case="deepclean")
    assert "TDS" not in backend.system_prompt
    assert "Cleaning Condition Report" in backend.system_prompt
    assert "est_value_band" not in backend.item_schema["properties"]["items"]["items"]["properties"]


def test_get_backend_tenancy_uses_tds_prompt(monkeypatch):
    from homeinventory.describe import get_backend

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    backend = get_backend("openai", use_case="tenancy")
    assert "TDS" in backend.system_prompt
    assert "est_value_band" in backend.item_schema["properties"]["items"]["items"]["properties"]
