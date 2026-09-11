"""Phase 0 of docs/35 — the repeat-describe control and its metrics.

The control's whole claim is that its two runs differ in nothing but the fact
of running twice, so most of what is tested here is the machinery that refuses
a pair when that is not true. The metrics themselves are tested against the
degenerate case (a record against itself, which must be perfect) and against
single, named perturbations, because a stability number that moves for two
reasons at once cannot be read.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval

from evals.synthetic.build_delta_tasks import DELTA_VIEWS
from evals.synthetic.run_eval import _sha256_file
from evals.synthetic.run_repeat_describe import (
    BASE_SIDE,
    REPEAT_SIDE,
    assert_identical_calls,
    build_repeat_run_plan,
    compare_repeat,
)
from evals.synthetic.score_stability import (
    _exact_key,
    _gate,
    _intended_items,
    _multiset_agreement,
    pair_stability,
    pool,
)

MODEL = "gemini-3.5-flash-low"
PROMPT = "production-v1"


def _item(name: str, **overrides) -> dict:
    item = {
        "name": name,
        "category": "furniture",
        "description": "",
        "condition": "good",
        "cleanliness": "cleaned to domestic standard",
        "defects": [],
        "quantity": 1,
        "photo_ids": ["RP-901-A-wide"],
        "confidence": 0.9,
        "est_value_band": "<£50",
    }
    item.update(overrides)
    return item


def _record(names_or_items, side: str = BASE_SIDE, **overrides) -> dict:
    """A ``run_delta_eval``-shaped describe record over the A-wide frame."""
    items = [
        _item(entry) if isinstance(entry, str) else entry
        for entry in names_or_items
    ]
    record = {
        "run_id": f"RP-901-T1.{side}.{MODEL}.{PROMPT}",
        "delta_id": "RP-901-T1",
        "side": side,
        "room_type": "Living Room",
        "backend_model": MODEL,
        "architecture_id": "antigravity-whole-room-v1",
        "prompt_id": PROMPT,
        "prompt_sha256": "prompt-hash",
        "instruction_sha256": "instruction-hash",
        "response_schema_sha256": "schema-hash",
        "completed_at": "2026-08-06T00:00:00+00:00",
        "inputs": [
            {
                "frame_id": "RP-901-A-wide",
                "view_id": "A-wide",
                "relative_path": "images/RP-901-A-wide.png",
                "sha256": "frame-hash",
            }
        ],
        "parsed_output": {"room_summary": "A room.", "items": items},
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------
# The control refuses anything that is not a repeat of the same call
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("instruction_sha256", "a-different-instruction"),
        ("prompt_sha256", "a-different-prompt"),
        ("response_schema_sha256", "a-different-schema"),
        ("backend_model", "some-other-model"),
        ("room_type", "Kitchen"),
    ],
)
def test_two_runs_that_were_not_the_same_call_are_refused(field, value):
    """A floor confounded with a prompt or model difference is worse than none.

    The number this instrument produces is only interpretable as
    non-determinism if nothing else could have caused the disagreement, so the
    identity is checked rather than assumed.
    """
    base = _record(["Sofa"])
    repeat = _record(["Sofa"], side=REPEAT_SIDE, **{field: value})
    with pytest.raises(ValueError, match="not the same call"):
        assert_identical_calls(base, repeat)


def test_two_runs_reading_different_frames_are_not_a_control():
    base = _record(["Sofa"])
    repeat = _record(["Sofa"], side=REPEAT_SIDE)
    repeat["inputs"] = [dict(repeat["inputs"][0], sha256="a-different-frame")]
    with pytest.raises(ValueError, match="did not read the same frames"):
        assert_identical_calls(base, repeat)


def test_the_control_compares_the_two_runs_and_says_they_are_spurious():
    pair = {
        "delta_id": "RP-901-T1",
        "delta_class": "temporal",
        "parent_scenario_id": "RP-901",
        "parent_split": "development",
        "room_type": "Living Room",
        "image_model": "GPT Image 2",
    }
    result = compare_repeat(
        pair, _record(["Sofa", "Rug"]), _record(["Sofa"], side=REPEAT_SIDE)
    )
    meta = result["stability_eval"]
    assert meta["instrument"] == "repeat-describe"
    assert set(meta["sides"]) == {BASE_SIDE, REPEAT_SIDE}
    assert result["totals"]["removed"] == 1
    assert "non-determinism" in meta["control_note"]


# --------------------------------------------------------------------------
# The run plan
# --------------------------------------------------------------------------


def _write_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    images = dataset / "images"
    images.mkdir(parents=True)
    rows = []
    for view in DELTA_VIEWS:
        reference = images / f"RP-901-{view}.png"
        reference.write_bytes(f"t0-{view}".encode())
        output = images / f"RP-901-T1-{view}.png"
        output.write_bytes(f"t1-{view}".encode())
        rows.append({
            "delta_id": "RP-901-T1",
            "parent_scenario_id": "RP-901",
            "parent_split": "development",
            "delta_class": "temporal",
            "room_type": "Living Room",
            "model_display_name": "GPT Image 2",
            "view_id": view,
            "reference_path": str(reference.relative_to(dataset)),
            "reference_sha256": _sha256_file(reference),
            "output_path": str(output.relative_to(dataset)),
            "output_sha256": _sha256_file(output),
        })
    with (dataset / "delta_tasks.csv").open("w", newline="", encoding="utf-8") as h:
        writer = csv.DictWriter(h, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return dataset


def _write_review(dataset: Path, decision: str = "accept") -> Path:
    path = dataset / "review.json"
    path.write_text(
        json.dumps({
            "status": "complete",
            "pairs": [{"delta_id": "RP-901-T1", "decision": decision}],
        }),
        encoding="utf-8",
    )
    return path


def _write_base_record(dataset: Path) -> Path:
    path = (
        dataset / "outputs" / "delta" / "antigravity-cli" / MODEL / PROMPT
        / f"RP-901-T1.{BASE_SIDE}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_record(["Sofa"])), encoding="utf-8")
    return path


def test_the_repeat_reads_the_t0_frames_not_the_generated_ones(tmp_path):
    """The control's premise: both sides read the same, already-described frames.

    Pointing the repeat at the T1 renders would quietly turn the control back
    into a second delta comparison, and its number would no longer be a floor.
    """
    dataset = _write_dataset(tmp_path)
    _write_base_record(dataset)
    plan = build_repeat_run_plan(dataset, _write_review(dataset), PROMPT, MODEL)
    inputs = plan[0]["run"]["inputs"]
    assert [item["relative_path"] for item in inputs] == [
        f"images/RP-901-{view}.png" for view in sorted(DELTA_VIEWS)
    ]
    assert all("RP-901-T1-" not in item["relative_path"] for item in inputs)


def test_the_control_cannot_run_without_the_run_it_is_the_floor_for(tmp_path):
    """No cached T0 means no pair to repeat.

    Describing fresh frames instead would produce a floor for runs nobody
    scored, which answers a question docs/35 did not ask.
    """
    dataset = _write_dataset(tmp_path)
    with pytest.raises(FileNotFoundError, match="run_delta_eval first"):
        build_repeat_run_plan(dataset, _write_review(dataset), PROMPT, MODEL)


def test_a_rejected_pair_is_not_repeated(tmp_path):
    dataset = _write_dataset(tmp_path)
    _write_base_record(dataset)
    plan = build_repeat_run_plan(
        dataset, _write_review(dataset, "reject"), PROMPT, MODEL
    )
    assert plan == []


def test_an_incomplete_review_cannot_authorise_the_control(tmp_path):
    dataset = _write_dataset(tmp_path)
    review = dataset / "review.json"
    review.write_text(json.dumps({"status": "in_progress", "pairs": []}), "utf-8")
    with pytest.raises(ValueError, match="not complete"):
        build_repeat_run_plan(dataset, review, PROMPT, MODEL)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def test_a_run_against_itself_is_perfectly_stable():
    """The degenerate case pins every metric's zero point.

    If a schedule compared with itself showed churn, every number this
    instrument produces would be measuring the metric rather than the model.
    """
    record = _record(["Sofa", "Rug", "Curtains"])
    result = pair_stability(record, record, [])
    metrics, counts = result["metrics"], result["counts"]
    assert metrics["schedule_agreement_exact"] == 100.0
    assert metrics["schedule_agreement_normalised"] == 100.0
    assert metrics["membership_churn"] == 0
    assert metrics["naming_churn"] == 0
    assert metrics["condition_agreement"] == 100.0
    assert metrics["cleanliness_agreement"] == 100.0
    assert metrics["quantity_agreement"] == 100.0
    assert metrics["photo_view_agreement"] == 100.0
    assert counts["reported_changes"] == 0


def test_a_renamed_item_is_naming_churn_not_membership_churn():
    """`Towel radiator` for `Heated towel rail` is the description moving.

    The aligner catches this one, so it must not also be counted as an item
    appearing and another disappearing — that would double-count the same
    instability under two headings that call for different fixes.
    """
    a = _record(["Bath panel"])
    b = _record(["Bath side panel"], side=REPEAT_SIDE)
    result = pair_stability(a, b, [])
    assert result["metrics"]["naming_churn"] == 1
    assert result["metrics"]["membership_churn"] == 0
    assert result["naming_churn_pairs"][0]["a"] == "Bath panel"


def test_normalisation_separates_naming_instability_from_membership():
    """Exact and normalised agreement differ by exactly the renames.

    Reporting only one of the two would leave a reader unable to tell "the two
    runs saw different rooms" from "the two runs used different words".
    """
    a = _record(["Bath panel", "Sofa"])
    b = _record(["Bath side panel", "Sofa"], side=REPEAT_SIDE)
    metrics = pair_stability(a, b, [])["metrics"]
    assert metrics["schedule_agreement_exact"] < 100.0
    assert metrics["schedule_agreement_normalised"] == 100.0


def test_a_dropped_item_is_membership_churn():
    a = _record(["Sofa", "Rug"])
    b = _record(["Sofa"], side=REPEAT_SIDE)
    result = pair_stability(a, b, [])
    assert result["metrics"]["membership_churn"] == 1
    assert result["unpaired_removed"] == ["Rug"]
    assert result["metrics"]["schedule_agreement_exact"] == 50.0


def test_agreement_is_measured_on_the_schedule_the_product_would_ship():
    """A run that lists "Curtain" twice ships one curtain, so it agrees.

    ``inventory_from_record`` puts both sides through ``merge_items``, which is
    what deduplicates a room in the shipped pipeline. Measuring stability on
    the raw model output instead would charge the describe step with churn the
    product already absorbs.
    """
    a = _record(["Curtain", "Curtain"])
    b = _record(["Curtain"], side=REPEAT_SIDE)
    result = pair_stability(a, b, [])
    assert result["counts"]["items_a"] == 1
    assert result["metrics"]["schedule_agreement_exact"] == 100.0


def test_schedule_agreement_counts_items_not_distinct_names():
    """Two curtains are not one curtain, wherever a duplicate does survive.

    The merge collapses exact repeats, but not every near-duplicate, and a set
    would score a run that saw two of something and a run that saw one as
    perfect agreement.
    """
    agreement = _multiset_agreement(["Curtain", "Curtain"], ["Curtain"], _exact_key)
    assert agreement == {"both": 1, "either": 2, "agreement": 50.0}


def test_a_wholesale_grade_shift_is_visible_even_when_compare_is_silent():
    """The tenancy gate only reports items that got *worse*.

    A second run that grades the whole room better than the first reports zero
    changes and looks perfectly stable through the compare surface. Grade
    agreement is in docs/35's metric list precisely because it is the only one
    that sees this, and it was the first thing the real data showed.
    """
    a = _record([_item("Sofa", condition="good"), _item("Rug", condition="good")])
    b = _record(
        [_item("Sofa", condition="excellent"), _item("Rug", condition="excellent")],
        side=REPEAT_SIDE,
    )
    result = pair_stability(a, b, [])
    assert result["counts"]["reported_changes"] == 0
    assert result["metrics"]["condition_agreement"] == 0.0
    assert result["metrics"]["condition_agreement_within_one"] == 100.0
    # Both disagreements are real and both are invisible through compare, so
    # the headline floor understates the instability by exactly this much.
    assert result["counts"]["grade_disagreements"] == 2
    assert result["counts"]["grade_disagreements_gated_out"] == 2


def test_a_worsening_grade_is_not_counted_as_gated_out():
    """The gate suppresses improvements, not everything.

    Without this the gated-out count could quietly become "every grade move",
    and the report's claim that these are changes a reader never sees would
    stop being true.
    """
    a = _record([_item("Sofa", condition="good")])
    b = _record([_item("Sofa", condition="poor")], side=REPEAT_SIDE)
    counts = pair_stability(a, b, [])["counts"]
    assert counts["reported_changes"] == 1
    assert counts["grade_disagreements"] == 1
    assert counts["grade_disagreements_gated_out"] == 0


def test_grade_agreement_within_one_is_reported_apart_from_exact():
    """The grade scale is ordinal: `good`/`fair` is not `good`/`poor`."""
    a = _record([_item("Sofa", condition="new")])
    b = _record([_item("Sofa", condition="good")], side=REPEAT_SIDE)
    metrics = pair_stability(a, b, [])["metrics"]
    assert metrics["condition_agreement"] == 0.0
    assert metrics["condition_agreement_within_one"] == 0.0


def test_quantity_disagreement_is_its_own_defect():
    """A schedule stable in names and unstable in counts is a different bug."""
    a = _record([_item("Dining chair", quantity=4)])
    b = _record([_item("Dining chair", quantity=6)], side=REPEAT_SIDE)
    metrics = pair_stability(a, b, [])["metrics"]
    assert metrics["schedule_agreement_exact"] == 100.0
    assert metrics["quantity_agreement"] == 0.0


def test_photo_agreement_survives_the_two_sides_naming_frames_differently():
    """T0 reads `RP-901-A-wide` and T1 reads `P35-901-T1-A-wide`.

    Comparing photo IDs literally would score identical evidence at zero on
    the delta instrument, and the metric would be measuring the filenames.
    """
    a = _record([_item("Sofa", photo_ids=["RP-901-A-wide"])])
    b = _record([_item("Sofa", photo_ids=["P35-901-T1-A-wide"])], side=REPEAT_SIDE)
    b["inputs"] = [
        {
            "frame_id": "P35-901-T1-A-wide",
            "view_id": "A-wide",
            "relative_path": "images/P35-901-T1-A-wide.png",
            "sha256": "frame-hash",
        }
    ]
    assert pair_stability(a, b, [])["metrics"]["photo_view_agreement"] == 100.0


def test_an_item_only_one_run_names_is_unstable_coverage():
    a = _record(["Radiator", "Sofa"])
    b = _record(["Sofa"], side=REPEAT_SIDE)
    coverage = pair_stability(a, b, ["radiator", "sofa", "carpet"])["coverage"]
    assert coverage["named_by_both"] == 1
    assert coverage["named_by_either"] == 2
    assert coverage["unstable"] == ["radiator"]
    assert coverage["missed_by_both"] == ["carpet"]


# --------------------------------------------------------------------------
# Pooling and the gate
# --------------------------------------------------------------------------


def test_pooled_rates_come_from_summed_counts_not_averaged_pairs():
    """A 3-item room and a 1-item room do not carry the same weight.

    ``aggregate_delta_scores`` made this choice for the delta metrics; the
    stability metrics have to make it the same way or the two instruments
    cannot be read against each other.
    """
    big = pair_stability(
        _record(["Sofa", "Rug", "Curtains"]),
        _record(["Sofa", "Rug", "Curtains"], side=REPEAT_SIDE),
        [],
    )
    small = pair_stability(
        _record(["Lamp"]), _record(["Bookcase"], side=REPEAT_SIDE), []
    )
    pooled = pool([
        {"delta_id": "a", "stability": big},
        {"delta_id": "b", "stability": small},
    ])
    # 3 agreed of 5 named by either, not the mean of 100% and 0%.
    assert pooled["metrics"]["schedule_agreement_exact"] == 60.0


def test_the_gate_states_the_fraction_and_decides_nothing(tmp_path):
    """docs/35 exits Phase 0 on a measurement, not a threshold.

    A script that graded its own gate would be setting the programme's
    direction by a number it chose itself.
    """
    score = tmp_path / "delta-score.json"
    score.write_text(
        json.dumps({"all_pairs": {"counts": {"false_changes": 368}}}), "utf-8"
    )
    gate = _gate(
        {"counts": {"reported_changes": 92, "grade_disagreements_gated_out": 0}},
        {"counts": {"reported_changes": 407}},
        score,
    )
    assert gate["floor_share_of_delta_false_changes"] == 25.0
    assert gate["delta_false_changes"] == 368
    assert "Not decided here" in gate["decision"]


def test_the_gate_never_invents_a_denominator():
    """The 368 is read from the scored report or not stated at all."""
    gate = _gate(
        {"counts": {"reported_changes": 92, "grade_disagreements_gated_out": 0}},
        {"counts": {"reported_changes": 407}},
        None,
    )
    assert gate["floor_share_of_delta_false_changes"] is None
    assert gate["control_reported_changes"] == 92


# --------------------------------------------------------------------------
# The shipped dataset
# --------------------------------------------------------------------------


DATASET = Path(__file__).resolve().parents[1] / "evals/fixtures/synthetic-room-eval"


def test_scene_specs_supply_coverage_gold_for_every_accepted_pair():
    """docs/35's coverage metric needs `intended_visible_items` to exist.

    The scenarios have carried it since Phase 1 and no delta work has read it;
    this is the check that it is actually there before a number is built on it.
    """
    review = DATASET / "reports/phase35-pilot-review-recut-2026-08-05.json"
    accepted = {
        pair["delta_id"]
        for pair in json.loads(review.read_text(encoding="utf-8"))["pairs"]
        if pair["decision"] == "accept"
    }
    intended = _intended_items(DATASET, accepted)
    assert set(intended) == accepted
    assert all(items for items in intended.values())
