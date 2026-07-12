"""Hero-cover benchmark identity and label-contract tests."""

import json
from pathlib import Path

import pytest

from evals.hero_gold import (
    HeroGoldValidationError,
    acceptable_frames,
    compatibility_issues,
    load_gold_document,
    preferred_frames,
    validate_gold_document,
)


ROOT = Path(__file__).resolve().parents[1]
HERO_GOLD = ROOT / "evals/fixtures/own-property/hero-gold.json"
DENSE_HERO_GOLD = (
    ROOT / "evals/fixtures/own-property/hero-gold-dense-anchor.json"
)
DENSE_METRICS = (
    ROOT / "evals/fixtures/own-property/hero-dense-detect-metrics.json"
)


def test_committed_hero_gold_and_candidate_manifest_are_valid():
    gold, manifest = load_gold_document(HERO_GOLD)

    assert gold["schema_version"] == 2
    assert manifest is not None
    assert manifest["frame_count"] == 93
    assert set(gold["rooms"]) == set(manifest["rooms"])


def test_dense_anchor_gold_and_detector_result_are_valid():
    gold, manifest = load_gold_document(DENSE_HERO_GOLD)
    metrics = json.loads(DENSE_METRICS.read_text(encoding="utf-8"))

    assert manifest is not None
    assert manifest["frame_count"] == 145
    assert metrics["benchmark_id"] == gold["benchmark_id"]
    rank1 = metrics["rank1"]
    acceptable_hits = sum(
        rank1.get(name) in acceptable_frames(spec)
        for name, spec in gold["rooms"].items()
    )
    preferred_hits = sum(
        rank1.get(name) == preferred_frames(spec)[0]
        for name, spec in gold["rooms"].items()
    )
    assert acceptable_hits == len(gold["rooms"]) == 10
    assert preferred_hits >= 7
    assert metrics["result"]["acceptable_hits"] == acceptable_hits
    assert metrics["result"]["preferred_rank1_hits"] == preferred_hits


def test_schema_v2_rejects_contradictory_acceptable_and_rejected_labels():
    data = {
        "schema_version": 2,
        "benchmark_id": "fixture-v1",
        "candidate_manifest": "candidates.json",
        "rooms": {
            "Kitchen": {
                "preferred": ["a.jpg"],
                "acceptable": ["a.jpg"],
                "rejected": ["a.jpg"],
            }
        },
    }
    manifest = {
        "benchmark_id": "fixture-v1",
        "frame_count": 1,
        "rooms": {"Kitchen": {"candidates": ["a.jpg"]}},
    }

    with pytest.raises(HeroGoldValidationError, match="acceptable/rejected overlap"):
        validate_gold_document(data, manifest)


def test_schema_v2_rejects_labels_outside_frozen_candidate_pool():
    data = {
        "schema_version": 2,
        "benchmark_id": "fixture-v1",
        "candidate_manifest": "candidates.json",
        "rooms": {
            "Kitchen": {
                "preferred": ["missing.jpg"],
                "acceptable": ["missing.jpg"],
                "rejected": [],
            }
        },
    }
    manifest = {
        "benchmark_id": "fixture-v1",
        "frame_count": 1,
        "rooms": {"Kitchen": {"candidates": ["present.jpg"]}},
    }

    with pytest.raises(HeroGoldValidationError, match="absent from candidate pool"):
        validate_gold_document(data, manifest)


def test_compatibility_reports_room_and_frame_drift():
    manifest = {
        "rooms": {
            "Hallway": {"candidates": ["a.jpg", "b.jpg"]},
            "Kitchen": {"candidates": ["c.jpg"]},
        }
    }
    report_rooms = [
        ("Hallway", [{"path": "a.jpg"}, {"path": "new.jpg"}]),
        ("Bedroom", [{"path": "bed.jpg"}]),
    ]

    issues = compatibility_issues(manifest, report_rooms)

    assert "missing rooms: Kitchen" in issues
    assert "unexpected rooms: Bedroom" in issues
    assert "Hallway: 1 expected frames missing, 1 unexpected frames" in issues


def test_legacy_top_labels_remain_readable_by_eval_helpers(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "rooms": {"Room": {"top": ["a.jpg", "b.jpg"], "bottom": ["z.jpg"]}}
    }), encoding="utf-8")

    gold, manifest = load_gold_document(path)
    room = gold["rooms"]["Room"]

    assert manifest is None
    assert preferred_frames(room) == ["a.jpg", "b.jpg"]
    assert acceptable_frames(room) == ["a.jpg", "b.jpg"]
