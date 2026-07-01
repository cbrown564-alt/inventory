import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))
import run_eval  # noqa: E402

from homeinventory.schema import Inventory, Item, Room  # noqa: E402


def test_name_match_substring_and_aliases():
    # exact (after normalisation) scores 1.0; substring scores 0.9-1.0 graded
    # by length ratio so closer-length matches win ties
    assert run_eval.name_match("Sofa", {"name": "sofa"}) == 1.0
    assert run_eval.name_match("Three-seat sofa", {"name": "sofa"}) >= 0.9
    assert run_eval.name_match("TV", {"name": "television", "aliases": ["tv"]}) == 1.0
    assert run_eval.name_match("Disco ball", {"name": "television"}) < 0.6


def test_name_match_tiebreak_prefers_closer_length():
    # regression: gold "double bed" (alias "bed") must rank "Double bed base"
    # above "Bedside table" — the flat substring score tied them at 1.0 and
    # let list order decide
    gold = {"name": "double bed", "aliases": ["bed"]}
    assert (run_eval.name_match("Double bed base", gold)
            > run_eval.name_match("Bedside table", gold))


def test_evaluate_recall_hallucination_condition_defects():
    inv = Inventory(rooms=[Room(name="Living Room", items=[
        Item(id="LIV-001", name="Three-seat sofa", condition="good",
             defects=["scuff on left arm"]),
        Item(id="LIV-002", name="Disco ball"),
    ])])
    labels = {"rooms": {"living room": {"items": [
        {"name": "sofa", "condition": "good", "defects": ["scuff left arm"]},
        {"name": "television", "notable": True},
    ]}}}
    r = run_eval.evaluate(inv, labels)
    assert r["item_recall_all"] == 50.0
    assert r["hallucination_rate"] == 50.0
    assert r["condition_exact"] == 100.0
    assert r["defect_recall"] == 100.0


def test_granularity_split_not_counted_as_hallucination():
    inv = Inventory(rooms=[Room(name="Bathroom", items=[
        Item(id="BTH-001", name="Bath", condition="good"),
        Item(id="BTH-002", name="Bath/shower mixer controls", condition="good"),
    ])])
    labels = {"rooms": {"bathroom": {"items": [
        {"name": "bath", "condition": "good",
         "components": ["mixer controls"], "notable": True},
    ]}}}
    r = run_eval.evaluate(inv, labels)
    assert r["item_recall_all"] == 100.0
    assert r["hallucination_rate"] == 0.0
    assert r["granularity_split_rate"] == 50.0


def test_weak_fuzzy_match_does_not_absorb_unrelated_pred():
    inv = Inventory(rooms=[Room(name="Living Room", items=[
        Item(id="LIV-001", name="Coffee table", condition="good"),
        Item(id="LIV-002", name="Coffee machine", condition="good"),
    ])])
    labels = {"rooms": {"living room": {"items": [
        {"name": "coffee table", "condition": "good", "notable": True},
    ]}}}
    r = run_eval.evaluate(inv, labels)
    assert r["hallucination_rate"] == 50.0
    assert r["granularity_split_rate"] == 0.0
