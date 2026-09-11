"""Focused tests for compare-check signal ratios."""

from __future__ import annotations

import pytest

from evals.synthetic.compare_check import signal_ratios

pytestmark = pytest.mark.eval


def test_signal_ratios_mark_aligned_state_not_membership() -> None:
    phase0 = {
        "instruments": {
            "repeat_describe_control": {
                "counts": {
                    "naming_churn": 100,
                    "unpaired_removed": 100,
                    "membership_churn": 100,
                    "unpaired_added": 100,
                    "condition_scored": 100,
                    "condition_exact": 80,
                    "cleanliness_scored": 100,
                    "cleanliness_exact": 80,
                    "changed": 40,
                }
            },
            "delta_pairs": {
                "counts": {
                    "naming_churn": 100,
                    "unpaired_removed": 100,
                    "membership_churn": 100,
                    "unpaired_added": 100,
                    "condition_scored": 100,
                    "condition_exact": 60,
                    "cleanliness_scored": 100,
                    "cleanliness_exact": 50,
                    "changed": 80,
                }
            },
        }
    }
    rows = {row["label"]: row for row in signal_ratios(phase0)}
    assert rows["Naming churn"]["aligned_state_signal"] is False
    assert rows["Items reported changed"]["aligned_state_signal"] is True
    assert rows["Items reported changed"]["ratio"] == 2.0
    assert rows["Condition disagreements"]["ratio"] == 2.0
    assert rows["Cleanliness disagreements"]["ratio"] == 2.5
