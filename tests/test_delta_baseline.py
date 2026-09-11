"""The delta pairs as a gate rather than a report (docs/36 §6.4).

Two things have to hold for the baseline to be worth having. It must re-derive
the numbers rather than read them back — a gate that reads
``reports/delta-compare/`` would pass for any change to ``compare_inventories``
at all — and it must notice the gold moving underneath it, because the cheapest
way to make a failing metric pass is to edit what it is scored against.

The pin logic is tested against a canned report so that a metric breach is one
named perturbation. The re-derivation is tested once, for real, against the
committed 5 Aug numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval

from evals.synthetic.delta_baseline import GOLD_FIELDS, check, gold_digest, rederive

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "fixtures" / "synthetic-room-eval"
REVIEW = DATASET / "reports" / "phase35-pilot-review-recut-2026-08-05.json"
SUMMARY = DATASET / "reports" / "phase35-pilot-summary-2026-08-05.json"
SCORED = DATASET / "reports" / "phase35-delta-score-2026-08-05.json"


def _resolve(path):
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


# --------------------------------------------------------------------------
# The gold digest
# --------------------------------------------------------------------------


def _spec(tmp_path: Path, delta_id: str, **fields) -> Path:
    payload = {
        "id": delta_id,
        "delta_of": "P35-901",
        "notes": "prose that is not gold",
        "changes": [{"kind": "item_removed", "target": "Sofa"}],
        "observed_changes": [],
        "retracted_changes": [],
    }
    payload.update(fields)
    directory = tmp_path / "deltas"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{delta_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_digest_is_stable_across_things_that_are_not_gold(tmp_path):
    """Prose, provenance and view lists move all the time; the pin must not.

    A digest over the whole spec file would fail on every unrelated edit, and a
    pin that fails for no reason gets re-pinned without being read, which is
    the failure mode it exists to prevent.
    """
    _spec(tmp_path, "P35-901-T1")
    before = gold_digest(tmp_path, ["P35-901-T1"])
    _spec(tmp_path, "P35-901-T1", notes="entirely different prose")
    assert gold_digest(tmp_path, ["P35-901-T1"]) == before


@pytest.mark.parametrize("field", GOLD_FIELDS)
def test_editing_gold_moves_the_digest(tmp_path, field):
    """Every list the score is computed against is covered.

    ``retracted_changes`` matters as much as ``changes``: Amendment C's
    24 retractions moved the scorable gold from 173 to 153, and doing that
    again silently would move every rate in the baseline.
    """
    _spec(tmp_path, "P35-901-T1")
    before = gold_digest(tmp_path, ["P35-901-T1"])
    _spec(tmp_path, "P35-901-T1", **{field: [{"kind": "cleanliness", "target": "Rug"}]})
    assert gold_digest(tmp_path, ["P35-901-T1"]) != before


def test_the_digest_does_not_depend_on_the_order_pairs_are_named(tmp_path):
    _spec(tmp_path, "P35-901-T1")
    _spec(tmp_path, "P35-902-T1")
    ids = ["P35-901-T1", "P35-902-T1"]
    assert gold_digest(tmp_path, ids) == gold_digest(tmp_path, list(reversed(ids)))


def test_a_scored_pair_with_no_specification_is_an_error(tmp_path):
    (tmp_path / "deltas").mkdir()
    with pytest.raises(FileNotFoundError, match="no delta specification"):
        gold_digest(tmp_path, ["P35-999-T1"])


# --------------------------------------------------------------------------
# The pins, against a canned report
# --------------------------------------------------------------------------


CANNED = {
    "pairs_scored": 27,
    "all_pairs": {
        "metrics": {"delta_recall": 26.6, "false_change_rate": 90.4},
        "counts": {},
    },
    "by_change_kind": {
        "item_removed": {"gold": 18, "detected": 9, "recall": 50.0},
        "cleanliness": {"gold": 26, "detected": 1, "recall": 3.8},
    },
    "per_pair": [{"delta_id": "P35-901-T1"}],
}


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    """A spec pinned to the canned report, with the gold digest made to match."""
    _spec(tmp_path, "P35-901-T1")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    review = tmp_path / "reports" / "review.json"
    review.write_text(json.dumps({"status": "complete", "pairs": []}), encoding="utf-8")

    monkeypatch.setattr(
        "evals.synthetic.delta_baseline.rederive",
        lambda *args, **kwargs: json.loads(json.dumps(CANNED)),
    )
    return {
        "name": "test-baseline",
        "dataset_dir": str(tmp_path),
        "review": str(review),
        "pairs_scored": 27,
        "gold_sha256": gold_digest(tmp_path, ["P35-901-T1"]),
        "floors": {"delta_recall": 26.6, "recall_item_removed": 50.0},
        "ceilings": {"false_change_rate": 90.4},
    }


def test_the_measured_numbers_pass_their_own_pins(baseline):
    assert check(baseline, _resolve) == []


def test_a_recall_regression_fails(baseline):
    baseline["floors"]["delta_recall"] = 30.0
    (failure,) = check(baseline, _resolve)
    assert "delta_recall 26.6 < floor 30.0" in failure


def test_a_false_change_regression_fails(baseline):
    baseline["ceilings"]["false_change_rate"] = 85.0
    (failure,) = check(baseline, _resolve)
    assert "false_change_rate 90.4 > ceiling 85.0" in failure


def test_per_kind_recall_is_pinned_independently(baseline):
    """docs/36 §6.4's named failure mode.

    An arm that drops ``false_change_rate`` by refusing to report removals
    would leave ``delta_recall`` roughly intact while gutting the one kind the
    product most needs. Pinning the kinds separately is what catches it.
    """
    baseline["floors"]["recall_item_removed"] = 60.0
    (failure,) = check(baseline, _resolve)
    assert "recall_item_removed 50.0 < floor 60.0" in failure


def test_editing_gold_fails_the_gate(baseline, tmp_path):
    _spec(tmp_path, "P35-901-T1", changes=[{"kind": "worsened", "target": "Rug"}])
    (failure,) = check(baseline, _resolve)
    assert "gold digest" in failure and "re-pin it in the same commit" in failure


def test_a_changed_pair_count_is_reported_before_the_rates(baseline):
    """A shrinking denominator moves every rate without any being a regression."""
    baseline["pairs_scored"] = 30
    failures = check(baseline, _resolve)
    assert "scored 27 pairs, baseline is 30" in failures[0]
    assert "not comparable" in failures[0]


def test_a_pinned_metric_the_report_does_not_carry_is_a_failure(baseline):
    """Silently skipping an unknown pin would let a typo disable a gate."""
    baseline["floors"]["recall_invented_kind"] = 10.0
    (failure,) = check(baseline, _resolve)
    assert "not in the re-derived report" in failure


def test_a_missing_dataset_is_reported_rather_than_crashing(baseline):
    baseline["dataset_dir"] = "evals/fixtures/does-not-exist"
    (failure,) = check(baseline, _resolve)
    assert "missing dataset dir" in failure


# --------------------------------------------------------------------------
# The re-derivation itself
# --------------------------------------------------------------------------


@pytest.mark.skipif(not SCORED.is_file(), reason="synthetic fixtures not present")
def test_rederiving_reproduces_the_committed_scores():
    """The gate re-runs compare and score; this pins that it agrees with 5 Aug.

    If this fails and nothing about the dataset changed, ``compare_inventories``
    moved — which is the entire point of the gate, and is why the numbers are
    checked against the committed report rather than against constants written
    out here.
    """
    committed = json.loads(SCORED.read_text(encoding="utf-8"))
    report = rederive(
        DATASET, REVIEW, SUMMARY, "gemini-3.5-flash-low", "production-v1"
    )
    assert report["pairs_scored"] == committed["pairs_scored"]
    assert report["all_pairs"]["metrics"] == committed["all_pairs"]["metrics"]
    assert {
        kind: data["recall"] for kind, data in report["by_change_kind"].items()
    } == {
        kind: data["recall"] for kind, data in committed["by_change_kind"].items()
    }


@pytest.mark.skipif(not SCORED.is_file(), reason="synthetic fixtures not present")
def test_the_committed_pins_match_the_committed_report():
    """The thresholds file is the gate; a stale pin is a gate that gates nothing."""
    cfg = json.loads(
        (ROOT / "evals" / "fixtures" / "thresholds.json").read_text(encoding="utf-8")
    )
    (spec,) = cfg["delta_baselines"]
    committed = json.loads(SCORED.read_text(encoding="utf-8"))
    metrics = committed["all_pairs"]["metrics"]

    assert spec["pairs_scored"] == committed["pairs_scored"]
    assert spec["floors"]["delta_recall"] == metrics["delta_recall"]
    assert spec["ceilings"]["false_change_rate"] == metrics["false_change_rate"]
    for kind, data in committed["by_change_kind"].items():
        assert spec["floors"][f"recall_{kind}"] == data["recall"], kind
