"""Regression: short fuzzy tokens must not false-match."""

from evals.run_eval import name_match


def test_door_does_not_fuzzy_match_floor_alias():
    gold = {"name": "laminate flooring", "aliases": ["flooring", "floor"]}
    assert name_match("door", gold) < 0.6
