"""Phase 0.5 of docs/35 — the local sampling control (docs/36 §6.1).

The experiment's whole claim is that its two arms differ in temperature and in
nothing else, and that neither arm is the dataset's scored Antigravity path.
Most of what is tested here is the machinery that enforces those two things,
because both fail silently: an exported ``HI_TEMPERATURE`` makes both arms one
arm, and a record written into the dataset's output tree becomes gold nobody
adjudicated.

Nothing here calls Ollama. The backend is a stub returning fixed items, so the
tests measure the harness rather than a model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from homeinventory.describe import ITEM_SCHEMA, SYSTEM_PROMPT, _parse_items
from homeinventory.schema import Item, Photo

from evals.synthetic.run_eval import _sha256_json
from evals.synthetic.run_local_stability import (
    ARCHITECTURE_ID,
    ARMS,
    BACKEND_ID,
    CHURN_EXCLUDES_SAMPLING,
    PROMPT_ID,
    RUN_SIDES,
    SAMPLING_ENV_VARS,
    _reading,
    assert_clean_sampling_env,
    describe_local,
    parsed_output_from_items,
    record_path,
    records_dir,
    select_pairs,
)
from evals.synthetic.run_repeat_describe import assert_identical_calls

MODEL = "qwen3.5:9b"


class StubBackend:
    """A ``LocalBackend`` shaped object that returns items instead of calling Ollama."""

    def __init__(self, temperature: float, items: list[Item] | None = None):
        self.temperature = temperature
        self.num_ctx = 24576
        self.num_predict = 12288
        self.repeat_penalty = 1.1
        self.batch_size = 6
        self.max_dim = 1120
        self.think = None
        self.last_room_timing = {"eval_tok_per_s": 12.5}
        self._items = items if items is not None else [_item("Sofa")]
        self.calls: list[tuple] = []

    def describe_room(self, room_name, photos, photo_paths, detections):
        self.calls.append((room_name, tuple(p.id for p in photos)))
        return "A room.", list(self._items)


def _item(name: str, **overrides) -> Item:
    fields = {
        "id": "",
        "name": name,
        "category": "furniture",
        "description": "A thing.",
        "condition": "good",
        "cleanliness": "cleaned to domestic standard",
        "defects": [],
        "quantity": 1,
        "est_value_band": "<£50",
        "photo_ids": ["P35-901-A-wide"],
        "confidence": 0.9,
    }
    fields.update(overrides)
    return Item(**fields).normalise()


def _run(tmp_path: Path, arm: str = "t0", side: str = "A", **overrides) -> dict:
    run = {
        "delta_id": "P35-901-T1",
        "side": side,
        "arm": arm,
        "temperature": ARMS[arm],
        "room_type": "Living Room",
        "model": MODEL,
        "inputs": [
            {
                "frame_id": "P35-901-A-wide",
                "view_id": "A-wide",
                "relative_path": "images/P35-901-A-wide.png",
                "sha256": "frame-hash",
            }
        ],
        "output": record_path(tmp_path, "P35-901-T1", MODEL, arm, side),
    }
    run.update(overrides)
    return run


# --------------------------------------------------------------------------
# The arm cannot be overridden underneath the experiment
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", SAMPLING_ENV_VARS)
def test_a_sampling_override_in_the_environment_is_a_hard_refusal(name):
    """Both arms would run identically and the null would be an artefact.

    ``LocalBackend`` reads these variables and lets them beat its constructor
    argument, so with ``HI_TEMPERATURE=0.3`` exported the 0.7 arm is not the
    0.7 arm. The failure is invisible in the output — the record would still
    say what it was asked for — which is exactly why it is refused up front
    rather than warned about.
    """
    with pytest.raises(SystemExit, match="would override"):
        assert_clean_sampling_env({name: "0.3"})


def test_a_clean_environment_runs():
    assert assert_clean_sampling_env({"PATH": "/usr/bin", "HOME": "/root"}) is None


# --------------------------------------------------------------------------
# These records are not the dataset's records
# --------------------------------------------------------------------------


def test_records_land_outside_the_scored_output_tree(tmp_path):
    """docs/31's gold lives in outputs/delta and outputs/repeat. This is neither.

    A local run written into either would be a describe record with no
    adjudicated provenance sitting where scored records live, and the next
    thing to walk that tree would score it.
    """
    directory = records_dir(tmp_path, MODEL, "t0")
    relative = directory.relative_to(tmp_path).parts
    assert relative[:2] == ("outputs", "local-stability")
    assert BACKEND_ID in relative
    assert "delta" not in relative and "repeat" not in relative


def test_the_record_names_the_local_backend_and_not_the_frozen_prompt(tmp_path):
    """``production-v1`` is the dataset's frozen prompt; this path does not use it.

    Claiming it would invite a like-for-like comparison against the Phase 0
    floor that the run cannot support, so the prompt id and its hash both name
    the product's own system prompt instead.
    """
    record = describe_local(_run(tmp_path), tmp_path, StubBackend(0.0))
    assert record["prompt_id"] == PROMPT_ID != "production-v1"
    assert record["prompt_sha256"] == _sha256_json(SYSTEM_PROMPT)
    assert record["architecture_id"] == ARCHITECTURE_ID
    assert record["backend_provider"] == "Ollama (local)"
    assert record["estimated_cost"]["metered_api_call"] is False
    assert record["response_schema_sha256"] == _sha256_json(ITEM_SCHEMA)


def test_a_backend_at_the_wrong_temperature_is_refused(tmp_path):
    """The record would name an arm it was not run at."""
    with pytest.raises(ValueError, match="is not the arm's"):
        describe_local(_run(tmp_path, arm="t07"), tmp_path, StubBackend(0.0))


def test_cached_records_are_immutable(tmp_path):
    describe_local(_run(tmp_path), tmp_path, StubBackend(0.0))
    with pytest.raises(FileExistsError, match="immutable"):
        describe_local(_run(tmp_path), tmp_path, StubBackend(0.0))


def test_the_recorded_temperature_is_the_arms(tmp_path):
    for arm, temperature in ARMS.items():
        record = describe_local(
            _run(tmp_path, arm=arm), tmp_path, StubBackend(temperature)
        )
        assert record["sampling_controls"]["temperature"] == temperature
        assert record["arm"] == arm


# --------------------------------------------------------------------------
# Two runs of one arm are the same call, so the Phase 0 metrics can read them
# --------------------------------------------------------------------------


def test_both_sides_of_an_arm_pass_the_identical_call_check(tmp_path):
    """The Phase 0 scorer refuses pairs that were not the same call.

    This control reuses that scorer, so its own records have to satisfy it.
    Everything in ``IDENTITY_FIELDS`` is derived from the arm and the frames,
    both shared between A and B, and the assertion is that nothing drifted.
    """
    backend = StubBackend(0.0)
    records = [
        describe_local(_run(tmp_path, side=side), tmp_path, backend)
        for side in RUN_SIDES
    ]
    assert_identical_calls(*records)


def test_two_arms_are_not_the_same_call(tmp_path):
    """A t0 record against a t07 record is a temperature comparison, not a floor.

    Scoring one against the other would report the arms' difference as
    non-determinism. Nothing in the runner does that, but the records carry
    different sampling settings and the guard is worth pinning: the two arms
    are pooled separately and never paired.
    """
    cold = describe_local(_run(tmp_path, arm="t0"), tmp_path, StubBackend(0.0))
    hot = describe_local(_run(tmp_path, arm="t07"), tmp_path, StubBackend(0.7))
    assert cold["sampling_controls"]["temperature"] != hot[
        "sampling_controls"
    ]["temperature"]
    # The identity check passes on the call itself — same prompt, schema, model
    # and frames — which is precisely why the arms must be kept apart by the
    # scorer's structure rather than by this check.
    assert_identical_calls(cold, hot)


# --------------------------------------------------------------------------
# The Item round trip, because every metric re-parses parsed_output
# --------------------------------------------------------------------------


def test_items_survive_the_round_trip_into_a_record(tmp_path):
    """``describe_room`` returns Items; a record has to carry a payload.

    Every docs/35 metric reads ``parsed_output`` and re-parses it, so a lossy
    serialisation would show up as stability the model did not have — two runs
    agreeing because the same fields were dropped from both.
    """
    items = [
        _item("Sofa", condition="fair", defects=["scuff to left arm"], quantity=2),
        _item("Rug", cleanliness="marked", est_value_band="£50-£250"),
    ]
    payload = parsed_output_from_items("A room.", items)
    photos = [Photo(id="P35-901-A-wide", path="x.png", room="Living Room")]
    summary, reparsed = _parse_items(payload, photos)

    assert summary == "A room."
    assert len(reparsed) == len(items)
    for before, after in zip(items, reparsed):
        for field in (
            "name",
            "category",
            "description",
            "condition",
            "cleanliness",
            "defects",
            "quantity",
            "est_value_band",
            "photo_ids",
            "confidence",
        ):
            assert getattr(after, field) == getattr(before, field), field


def test_the_record_carries_what_the_backend_returned(tmp_path):
    backend = StubBackend(0.0, items=[_item("Sofa"), _item("Rug")])
    record = describe_local(_run(tmp_path), tmp_path, backend)
    assert [item["name"] for item in record["parsed_output"]["items"]] == [
        "Sofa",
        "Rug",
    ]
    on_disk = json.loads(Path(record_path(tmp_path, "P35-901-T1", MODEL, "t0", "A")).read_text())
    assert on_disk["parsed_output"] == record["parsed_output"]


# --------------------------------------------------------------------------
# The subset rule, and the reading
# --------------------------------------------------------------------------


def test_the_subset_is_a_rule_not_a_choice():
    """Picking pairs by eye would let the arm be chosen after the fact."""
    accepted = ["P35-011-T1", "P35-002-T1", "P35-004-T1", "P35-003-T1"]
    assert select_pairs(accepted, 2) == ["P35-002-T1", "P35-003-T1"]
    assert select_pairs(accepted, None) == sorted(accepted)
    assert select_pairs(accepted, 99) == sorted(accepted)


def _arm(churn: float) -> dict:
    return {
        "temperature": 0.0,
        "pairs_scored": 10,
        "metrics": {"membership_churn_per_room": churn},
    }


def test_a_churning_greedy_arm_excludes_sampling():
    """docs/36 §6.1's branch: if temperature 0 still churns, arms A-D stand."""
    reading = _reading({"t0": _arm(CHURN_EXCLUDES_SAMPLING + 1)})
    assert reading["verdict"] == "sampling_excluded"


def test_a_stable_greedy_arm_alone_does_not_reach_a_verdict():
    """The comparative claim needs the second arm; a single arm must say so."""
    reading = _reading({"t0": _arm(0.5)})
    assert reading["verdict"] == "greedy_stable_second_arm_needed"


def test_a_stable_greedy_arm_against_a_churning_hot_arm_implicates_sampling():
    reading = _reading({"t0": _arm(0.5), "t07": _arm(9.0)})
    assert reading["verdict"] == "sampling_implicated"


def test_without_the_greedy_arm_there_is_no_reading():
    """Every branch in docs/36 §6.1 turns on temperature 0."""
    reading = _reading({"t07": _arm(9.0)})
    assert reading["verdict"] == "indeterminate"
