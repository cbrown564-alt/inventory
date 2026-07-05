"""Tests for detection-label → gold-item matching rules."""

from homeinventory.det_match import (
    BOOTSTRAP_SKIP_GOLD,
    DET_GOLD_BLOCK,
    gold_for_detection,
    match_score,
)


def _gold(name: str, *, aliases: list[str] | None = None, notable: bool = True) -> dict:
    return {"name": name, "aliases": aliases or [], "notable": notable}


def test_door_does_not_match_flooring():
    items = [
        _gold("laminate flooring", aliases=["flooring", "floor"]),
        _gold("balcony door", aliases=["patio door"]),
    ]
    gold, _ = gold_for_detection("door", items, mode="bootstrap")
    assert gold["name"] == "balcony door"
    assert gold_for_detection("door", [_gold("laminate flooring", aliases=["floor"])], mode="bootstrap") is None
    assert match_score("door", _gold("laminate flooring", aliases=["floor"])) < 0.6


def test_ceiling_light_routes_to_fixtures_not_ceiling():
    items = [
        _gold("ceiling"),
        _gold("recessed spotlights", aliases=["ceiling lights", "downlights"]),
        _gold("smoke alarm"),
    ]
    gold, _ = gold_for_detection("ceiling light", items, mode="bootstrap")
    assert gold["name"] == "recessed spotlights"
    assert gold_for_detection("smoke alarm", items, mode="bootstrap")[0]["name"] == "smoke alarm"


def test_bootstrap_skips_surface_gold():
    items = [_gold("ceiling"), _gold("laminate flooring", aliases=["floor"])]
    assert gold_for_detection("ceiling light", items, mode="bootstrap") is None
    assert gold_for_detection("door", items, mode="bootstrap") is None


def test_window_not_balcony_door():
    items = [_gold("balcony door"), _gold("window")]
    gold, _ = gold_for_detection("window", items, mode="bootstrap")
    assert gold["name"] == "window"
    assert ("window", "balcony door") in DET_GOLD_BLOCK


def test_stove_routes_to_oven_not_microwave():
    items = [_gold("oven"), _gold("microwave"), _gold("induction hob", aliases=["hob"])]
    gold, _ = gold_for_detection("stove", items, mode="bootstrap")
    assert gold["name"] in ("oven", "induction hob")


def test_kettle_never_matches_sofa():
    items = [_gold("sofa"), _gold("kitchen contents", aliases=["kettle"])]
    assert gold_for_detection("kettle", items, mode="bootstrap")[0]["name"] == "kitchen contents"
    items2 = [_gold("sofa"), _gold("coffee table")]
    assert gold_for_detection("kettle", items2, mode="bootstrap") is None


def test_bootstrap_skip_gold_includes_surfaces():
    assert "ceiling" in BOOTSTRAP_SKIP_GOLD
    assert "laminate flooring" in BOOTSTRAP_SKIP_GOLD
