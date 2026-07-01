"""Tests for the eval CI regression gate."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_gate_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "ci_gate.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_ci_gate_reference_scores_meet_floors():
    sys.path.insert(0, str(ROOT / "evals"))
    import ci_gate  # noqa: E402

    cfg = json.loads((ROOT / "evals" / "fixtures" / "thresholds.json").read_text())
    failures = []
    for ref in cfg["references"]:
        failures.extend(ci_gate.check_reference(ref))
    assert failures == [], failures


def test_score_benchmarks_runs():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "score_benchmarks.py"), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    scores = json.loads(proc.stdout)
    assert "claude-v4" in scores
    assert scores["claude-v4"]["item_recall_notable"] >= 85.0
