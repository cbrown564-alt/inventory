import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))
import run_eval  # noqa: E402

from homeinventory.schema import Inventory, Item, Room  # noqa: E402


def test_name_match_substring_and_aliases():
    assert run_eval.name_match("Three-seat sofa", {"name": "sofa"}) == 1.0
    assert run_eval.name_match("TV", {"name": "television", "aliases": ["tv"]}) == 1.0
    assert run_eval.name_match("Disco ball", {"name": "television"}) < 0.6


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
