"""Tests for homeinventory.detect (no model weights required)."""

from homeinventory.detect import (
    HOUSEHOLD_VOCAB,
    default_model,
)


def test_default_model_per_mode():
    assert default_model("text") == "yoloe-11s-seg.pt"
    assert default_model("prompt_free") == "yoloe-11s-seg-pf.pt"
    assert default_model("prompt_free").endswith("-pf.pt")


def test_household_vocab_covers_coverage_expectations():
    from homeinventory.coverage import ROOM_EXPECTATIONS, GENERIC_EXPECTED

    needed: set[str] = set()
    for exp in GENERIC_EXPECTED + [
        alt for exps in ROOM_EXPECTATIONS.values() for exp in exps for alt in exp.split("|")
    ]:
        needed.add(exp.split("|")[0])
    for term in needed:
        alts = term.split("|")
        assert any(a in HOUSEHOLD_VOCAB for a in alts), f"{term!r} missing from vocab"
