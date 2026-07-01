"""Unit tests for evals/eval_detect.py scoring (no YOLOE weights required)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))
import eval_detect  # noqa: E402


def test_gold_matches_any_label():
    gold = {"name": "sofa", "aliases": ["settee"]}
    assert eval_detect.gold_matches_any_label(gold, {"sofa"}, 0.6)
    assert eval_detect.gold_matches_any_label(gold, {"couch"}, 0.6) is False
    assert eval_detect.gold_matches_any_label(
        {"name": "bathtub", "aliases": ["bath"]},
        {"bathtub"},
        0.6,
    )


def test_label_matches_any_gold():
    items = [
        {"name": "sofa", "aliases": ["settee"]},
        {"name": "television", "aliases": ["tv"]},
    ]
    assert eval_detect.label_matches_any_gold("tv", items, 0.6)
    assert not eval_detect.label_matches_any_gold("bicycle", items, 0.6)


def test_compare_modes_recommends_text_when_comparable():
    text = {
        "mode": "text",
        "available": True,
        "gold_recall_notable": 42.0,
        "gold_recall_all": 35.0,
        "unmatched_label_rate": 10.0,
        "coverage_gap_rate": 20.0,
    }
    pf = {
        "mode": "prompt_free",
        "available": True,
        "gold_recall_notable": 44.0,
        "gold_recall_all": 38.0,
        "unmatched_label_rate": 55.0,
        "coverage_gap_rate": 18.0,
    }
    cmp = eval_detect.compare_modes([text, pf])
    assert cmp["gold_recall_notable_delta"] == 2.0
    assert "text" in cmp["recommendation"] or "household" in cmp["recommendation"]


def test_compare_modes_picks_pf_when_much_better_recall():
    text = {
        "mode": "text",
        "available": True,
        "gold_recall_notable": 30.0,
        "unmatched_label_rate": 5.0,
    }
    pf = {
        "mode": "prompt_free",
        "available": True,
        "gold_recall_notable": 50.0,
        "unmatched_label_rate": 40.0,
    }
    cmp = eval_detect.compare_modes([text, pf])
    assert "prompt_free" in cmp["recommendation"]
