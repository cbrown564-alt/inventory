import copy
import csv
import json
import subprocess
from pathlib import Path

import pytest

from evals.synthetic.build_delta_tasks import (
    DELTA_VIEWS,
    build_prompt,
    build_rows,
    load_specs,
    validate_spec,
    write_tasks,
)
from evals.synthetic.generate_delta_codex import (
    build_instruction,
    generate_one,
    pending_rows,
    reported_prompt,
)
from evals.synthetic.record_delta_outputs import MAX_PROBE_ATTEMPTS, record
from evals.synthetic.review_delta_pair import (
    combine,
    probe_verdict,
    review_inputs,
)
from evals.synthetic.score_delta import build_report, score_delta

DATASET = Path(__file__).resolve().parents[1] / "evals/fixtures/synthetic-room-eval"

PARENT = {
    "id": "RP-901",
    "room_type": "Living Room",
    "property_profile": "modest 1990s UK flat",
    "cleanliness": "clean and tidy",
    "lighting": "overcast daylight",
    "continuity_requirements": ["same sofa, carpet and window"],
    "avoid": ["people", "logos"],
    "provider_assignments": ["gpt-image-2"],
    "views": [
        {
            "id": "A-wide",
            "viewpoint": "standing at the doorway",
            "shot_scale": "wide establishing view",
            "intended_visible_items": ["sofa", "carpet", "radiator"],
            "intended_defects": [],
            "intended_negatives": [],
        },
        {
            "id": "D-condition",
            "viewpoint": "close to the carpet",
            "shot_scale": "condition detail",
            "intended_visible_items": ["carpet", "skirting board"],
            "intended_defects": [],
            "intended_negatives": [],
        },
    ],
}

SPEC = {
    "id": "RP-901-T1",
    "delta_of": "RP-901",
    "delta_class": "temporal",
    "timepoint": "T1",
    "changes": [
        {
            "id": "D1",
            "kind": "new_defect",
            "target": "carpet",
            "description": "dark stain roughly 15cm across by the radiator",
            "material": True,
        },
        {
            "id": "D2",
            "kind": "item_removed",
            "target": "floor lamp",
            "description": "lamp present at T0 is absent at T1",
            "material": True,
        },
    ],
    "unchanged_assertions": ["same sofa, window and skirting boards"],
}


def _write_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    (dataset / "scenarios").mkdir(parents=True)
    (dataset / "deltas").mkdir(parents=True)
    images = dataset / "images/openai/gpt-image-2"
    images.mkdir(parents=True)
    (dataset / "dataset.json").write_text(json.dumps({
        "providers": {
            "gpt-image-2": {
                "provider": "OpenAI",
                "product": "Codex built-in image generation",
                "model_display_name": "GPT Image 2",
                "image_directory": "openai/gpt-image-2",
                "file_extension": "png",
            }
        }
    }), encoding="utf-8")
    (dataset / "scenarios/RP-901.json").write_text(json.dumps(PARENT), encoding="utf-8")
    (dataset / "deltas/RP-901-T1.json").write_text(json.dumps(SPEC), encoding="utf-8")
    for view in DELTA_VIEWS:
        (images / f"RP-901-{view}.png").write_bytes(b"t0-" + view.encode())
    return dataset


# --------------------------------------------------------------------------
# build_delta_tasks
# --------------------------------------------------------------------------


def test_build_rows_pins_two_views_and_the_accepted_t0_reference(tmp_path):
    dataset = _write_dataset(tmp_path)
    rows = build_rows(dataset)
    assert len(rows) == 2
    assert {row["view_id"] for row in rows} == set(DELTA_VIEWS)
    for row in rows:
        assert row["provider"] == "OpenAI"
        assert row["reference_path"].endswith(f"RP-901-{row['view_id']}.png")
        assert row["reference_sha256"]
        assert "deltas/" in row["output_path"]


def test_delta_pair_requires_an_accepted_t0_frame(tmp_path):
    dataset = _write_dataset(tmp_path)
    (dataset / "images/openai/gpt-image-2/RP-901-A-wide.png").unlink()
    with pytest.raises(FileNotFoundError, match="T0 reference"):
        build_rows(dataset)


def test_write_tasks_preserves_operator_progress_on_a_stable_prompt(tmp_path):
    dataset = _write_dataset(tmp_path)
    write_tasks(dataset)
    path = dataset / "delta_tasks.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["status"] = "review_pending"
    rows[0]["attempts"] = "1"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    rebuilt = write_tasks(dataset)
    assert rebuilt[0]["status"] == "review_pending"
    assert rebuilt[0]["attempts"] == "1"


def test_prompt_pins_the_reference_and_forbids_a_collage(tmp_path):
    prompt = build_prompt(SPEC, PARENT, PARENT["views"][0], "RP-901-A-wide.png")
    assert "RP-901-A-wide.png" in prompt
    assert "dark stain roughly 15cm across" in prompt
    assert "same sofa, window and skirting boards" in prompt
    assert "Introduce no other new object" in prompt
    assert "side-by-side" in prompt


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda s: s.update(unchanged_assertions=[]), "unchanged_assertions"),
        (lambda s: s.update(changes=[]), "changes must be"),
        (lambda s: s.update(delta_class="drift"), "delta_class"),
        (lambda s: s["changes"].append(dict(s["changes"][0])), "duplicate change id"),
        (lambda s: s["changes"][0].update(kind="teleported"), "kind must be"),
        (lambda s: s["changes"][0].pop("material"), "material must be"),
        (
            lambda s: s.update(changes=[dict(s["changes"][0], material=False)]),
            "at least one change must be material",
        ),
    ],
)
def test_validate_spec_rejects_unscorable_specifications(mutate, message):
    spec = copy.deepcopy(SPEC)
    mutate(spec)
    with pytest.raises(ValueError, match=message):
        validate_spec(spec, PARENT)


def test_load_specs_rejects_a_missing_parent(tmp_path):
    dataset = _write_dataset(tmp_path)
    (dataset / "scenarios/RP-901.json").unlink()
    with pytest.raises(FileNotFoundError, match="parent scenario"):
        load_specs(dataset)


# --------------------------------------------------------------------------
# review_delta_pair
# --------------------------------------------------------------------------


def _accepting_review(delta_id="RP-901-T1", **overrides):
    review = {
        "delta_id": delta_id,
        "decision": "accept",
        "same_room": True,
        "same_room_notes": "",
        "enumerated": [
            {"change_id": "D1", "visibility": "clear", "notes": ""},
            {"change_id": "D2", "visibility": "clear", "notes": ""},
        ],
        "unenumerated_changes": [],
        "reason": "",
    }
    review.update(overrides)
    return review


EXPECTED = {
    "delta_id": "RP-901-T1",
    "delta_class": "temporal",
    "enumerated_changes": SPEC["changes"],
}


def test_two_accepting_reviews_accept_the_pair():
    result = combine(EXPECTED, _accepting_review(), _accepting_review())
    assert result["decision"] == "accept"
    assert result["reviewers_agreed"] is True


def test_any_unenumerated_material_change_rejects_the_pair():
    drifted = _accepting_review(unenumerated_changes=[
        {"target": "curtains", "description": "now patterned", "material": True}
    ])
    result = combine(EXPECTED, drifted, _accepting_review())
    assert result["decision"] == "reject"
    assert "unenumerated material change" in result["decision_basis"]


def test_drift_rejects_even_when_both_reviewers_said_accept():
    drifted = _accepting_review(unenumerated_changes=[
        {"target": "flooring", "description": "laminate replaced carpet"}
    ])
    result = combine(EXPECTED, drifted, drifted)
    assert result["decision"] == "reject"


def test_failed_room_identity_rejects_the_pair():
    result = combine(
        EXPECTED,
        _accepting_review(same_room=False, decision="reject"),
        _accepting_review(),
    )
    assert result["decision"] == "reject"
    assert result["decision_basis"] == "room identity failed"


def test_missing_material_change_rejects_the_pair():
    absent = _accepting_review(enumerated=[
        {"change_id": "D1", "visibility": "absent", "notes": ""},
        {"change_id": "D2", "visibility": "clear", "notes": ""},
    ])
    result = combine(EXPECTED, absent, _accepting_review())
    assert result["decision"] == "reject"
    assert "D1" in result["decision_basis"]


def test_reviewer_disagreement_escalates():
    result = combine(
        EXPECTED, _accepting_review(), _accepting_review(decision="escalate")
    )
    assert result["decision"] == "escalate"
    assert result["reviewers_agreed"] is False


def test_review_inputs_only_offers_pairs_with_every_view(tmp_path):
    dataset = _write_dataset(tmp_path)
    rows = write_tasks(dataset)
    for row in rows:
        row["status"] = "review_pending"
        row["output_sha256"] = "abc"
    output = dataset / "images/openai/gpt-image-2/deltas"
    output.mkdir(parents=True)
    for row in rows:
        (dataset / row["output_path"]).write_bytes(b"t1")
    path = dataset / "delta_tasks.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    inputs = review_inputs(dataset)
    assert len(inputs) == 1
    assert {view["view_id"] for view in inputs[0]["views"]} == set(DELTA_VIEWS)
    assert len(inputs[0]["enumerated_changes"]) == 2

    rows[0]["status"] = "pending"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="needs every view"):
        review_inputs(dataset)


def test_probe_gate_needs_two_clean_accepted_pairs():
    def pair(delta_id, decision, drift=()):
        return {
            "delta_id": delta_id,
            "decision": decision,
            "unenumerated_material_changes": list(drift),
        }

    passing = {"pairs": [
        pair("a", "accept"), pair("b", "accept"), pair("c", "reject")
    ]}
    assert probe_verdict(passing)["probe_passed"] is True

    failing = {"pairs": [pair("a", "accept"), pair("b", "reject")]}
    assert probe_verdict(failing)["probe_passed"] is False
    assert "Do not retry at a looser bar" in probe_verdict(failing)["verdict"]


# --------------------------------------------------------------------------
# generate_delta_codex
# --------------------------------------------------------------------------


def test_the_instruction_carries_the_frozen_prompt_unaltered(tmp_path):
    dataset = _write_dataset(tmp_path)
    row = write_tasks(dataset)[0]
    instruction = build_instruction(row)
    assert f"<prompt>\n{row['exact_prompt']}\n</prompt>" in instruction
    assert row["output_path"] in instruction


def test_reported_prompt_reads_the_last_fenced_block():
    assert reported_prompt("done\n```text\nthe prompt\n```") == "the prompt"
    assert reported_prompt("```\nfirst\n```\nthen\n```text\nsecond\n```") == "second"
    assert reported_prompt("no block here") is None


def _fake_codex(dataset, monkeypatch, *, writes=True, prompt=None):
    """Stand in for `codex exec`, writing what a real run would write."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        instruction = command[-1]
        row_prompt = instruction.split("<prompt>\n", 1)[1].split("\n</prompt>")[0]
        if writes:
            relative = instruction.split("unedited to ", 1)[1].split(" (relative")[0]
            target = dataset / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"generated-" + target.name.encode())
        reported = row_prompt if prompt is None else prompt
        return subprocess.CompletedProcess(
            command, 0, stdout=f"codex\n```text\n{reported}\n```\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_a_generated_frame_reports_a_verbatim_prompt(tmp_path, monkeypatch):
    dataset = _write_dataset(tmp_path)
    rows = write_tasks(dataset)
    calls = _fake_codex(dataset, monkeypatch)

    outcome = generate_one(dataset, rows[0], Path("codex"), timeout=60)
    assert outcome["output_written"] is True
    assert outcome["prompt_verbatim"] is True
    assert outcome["metered_api_call"] is False
    assert (dataset / rows[0]["output_path"]).is_file()
    assert "-i" in calls[0] and rows[0]["reference_path"] in calls[0]


def test_a_paraphrased_prompt_discards_the_frame(tmp_path, monkeypatch):
    """A frame whose generating prompt is unknown is not evidence.

    Left on disk it would be picked up by the next record run and enter the
    ledger under the queue's exact_prompt — a provenance record that reads as
    exact while describing a prompt that generated nothing.
    """
    dataset = _write_dataset(tmp_path)
    rows = write_tasks(dataset)
    _fake_codex(dataset, monkeypatch, prompt="make the kitchen look a bit worse")

    outcome = generate_one(dataset, rows[0], Path("codex"), timeout=60)
    assert outcome["prompt_verbatim"] is False
    assert outcome["output_written"] is False
    assert not (dataset / rows[0]["output_path"]).exists()
    assert "discarded" in outcome["error"]


def test_a_run_that_saves_nothing_is_reported_as_an_error(tmp_path, monkeypatch):
    dataset = _write_dataset(tmp_path)
    rows = write_tasks(dataset)
    _fake_codex(dataset, monkeypatch, writes=False)

    outcome = generate_one(dataset, rows[0], Path("codex"), timeout=60)
    assert outcome["output_written"] is False
    assert "no image was saved" in outcome["error"]


def test_pending_rows_skips_frames_that_already_exist(tmp_path):
    dataset = _write_dataset(tmp_path)
    rows = write_tasks(dataset)
    assert len(pending_rows(dataset)) == 2
    path = dataset / rows[0]["output_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"already-generated")
    assert [row["task_id"] for row in pending_rows(dataset)] == [rows[1]["task_id"]]


# --------------------------------------------------------------------------
# record_delta_outputs
# --------------------------------------------------------------------------


def _render(dataset: Path, contents: dict[str, bytes] | None = None) -> list[dict]:
    """Write a T1 frame for every queued view and return the queue rows."""
    rows = write_tasks(dataset)
    for row in rows:
        path = dataset / row["output_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        default = b"t1-" + row["view_id"].encode()
        path.write_bytes((contents or {}).get(row["view_id"], default))
    return rows


def _queue(dataset: Path) -> dict[str, dict[str, str]]:
    with (dataset / "delta_tasks.csv").open(newline="", encoding="utf-8") as handle:
        return {row["task_id"]: row for row in csv.DictReader(handle)}


def test_recording_moves_rendered_frames_into_the_review_queue(tmp_path):
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    report = record(dataset, "operator", "Codex built-in imagegen / GPT Image 2")

    assert report["generation_count"] == 2
    assert report["generation_policy"]["image_api_used"] is False
    for row in _queue(dataset).values():
        assert row["status"] == "review_pending"
        assert row["attempts"] == "1"
        assert row["output_sha256"]
    assert len(review_inputs(dataset)) == 1


def test_a_t1_that_copies_its_t0_reference_is_refused(tmp_path):
    """The delta-specific failure: a copy looks like the perfect result.

    Identity holds and nothing drifts, so a copied reference fails only on its
    enumerated changes being absent — indistinguishable by eye from an ordinary
    generator miss, and it would enter the ledger as one.
    """
    dataset = _write_dataset(tmp_path)
    _render(dataset, contents={"A-wide": b"t0-A-wide"})
    with pytest.raises(ValueError, match="byte-identical to its T0 reference"):
        record(dataset, "operator", "cli")


def test_one_render_saved_to_both_views_is_refused(tmp_path):
    dataset = _write_dataset(tmp_path)
    _render(dataset, contents={"A-wide": b"same", "D-condition": b"same"})
    with pytest.raises(ValueError, match="one render was saved to both paths"):
        record(dataset, "operator", "cli")


def test_an_output_duplicating_another_dataset_image_is_refused(tmp_path):
    dataset = _write_dataset(tmp_path)
    other = dataset / "images/openai/gpt-image-2/RP-902-A-wide.png"
    other.write_bytes(b"some-other-accepted-frame")
    _render(dataset, contents={"A-wide": b"some-other-accepted-frame"})
    with pytest.raises(ValueError, match="duplicates an existing dataset image"):
        record(dataset, "operator", "cli")


def test_a_moved_t0_reference_refuses_the_pair(tmp_path):
    """Gold describes the pinned frame, not whatever now sits at that path."""
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    (dataset / "images/openai/gpt-image-2/RP-901-A-wide.png").write_bytes(b"redone")
    with pytest.raises(ValueError, match="T0 reference has changed"):
        record(dataset, "operator", "cli")


def test_recorded_provenance_is_immutable(tmp_path):
    dataset = _write_dataset(tmp_path)
    rows = _render(dataset)
    record(dataset, "operator", "cli")
    (dataset / rows[0]["output_path"]).write_bytes(b"quietly-swapped")
    with pytest.raises(ValueError, match="changed after provenance was recorded"):
        record(dataset, "operator", "cli")


def test_the_probe_cannot_be_retried_past_its_gate(tmp_path):
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    record(dataset, "operator", "cli")

    path = dataset / "delta_tasks.csv"
    rows = list(_queue(dataset).values())
    for index, row in enumerate(rows):
        row["status"] = "retry_pending"
        row["output_sha256"] = ""
        (dataset / row["output_path"]).write_bytes(b"attempt-2-" + str(index).encode())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    record(dataset, "operator", "cli")
    assert {row["attempts"] for row in _queue(dataset).values()} == {"2"}

    rows = list(_queue(dataset).values())
    for index, row in enumerate(rows):
        row["status"] = "retry_pending"
        row["output_sha256"] = ""
        (dataset / row["output_path"]).write_bytes(b"attempt-3-" + str(index).encode())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match=f"exceeds the {MAX_PROBE_ATTEMPTS}-attempt"):
        record(dataset, "operator", "cli")


# --------------------------------------------------------------------------
# score_delta
# --------------------------------------------------------------------------


def _comparison(**overrides):
    room = {
        "name": "Living Room",
        "changed": [
            {
                "name": "carpet",
                "grade_delta": 1,
                "new_defects": ["dark stain by the radiator"],
                "checkout_defects": ["dark stain by the radiator"],
            }
        ],
        "unchanged": [{"name": "sofa"}, {"name": "radiator"}],
        "removed": [{"name": "floor lamp"}],
        "added": [],
    }
    room.update(overrides)
    return {"rooms": [room]}


def test_perfect_compare_run_scores_full_recall_and_no_false_changes():
    report = score_delta(_comparison(), [SPEC])
    assert report["metrics"]["delta_recall"] == 100.0
    assert report["metrics"]["false_change_rate"] == 0.0
    assert report["metrics"]["unchanged_stability"] == 100.0
    assert report["missed_material_changes"] == []


def test_an_invented_change_is_counted_against_the_run():
    comparison = _comparison(added=[{"name": "wall mirror"}])
    report = score_delta(comparison, [SPEC])
    assert report["metrics"]["delta_recall"] == 100.0
    assert report["counts"]["false_changes"] == 1
    assert report["metrics"]["false_change_rate"] == pytest.approx(33.3)
    assert report["false_changes"][0]["name"] == "wall mirror"


def test_a_missed_defect_is_named_in_the_report():
    comparison = _comparison(changed=[])
    report = score_delta(comparison, [SPEC])
    assert report["metrics"]["delta_recall"] == 50.0
    assert [row["change_id"] for row in report["missed_material_changes"]] == ["D1"]


def test_unchanged_items_are_not_counted_as_reported_changes():
    report = score_delta(_comparison(), [SPEC])
    assert report["counts"]["reported_changes"] == 2
    assert report["counts"]["unchanged_reported"] == 2


def test_severity_direction_is_scored_on_directional_kinds():
    spec = copy.deepcopy(SPEC)
    spec["changes"] = [{
        "id": "D3", "kind": "worsened", "target": "carpet",
        "description": "existing stain widened", "material": True,
    }]
    improved = _comparison(changed=[{
        "name": "carpet", "grade_delta": -1, "new_defects": [],
    }])
    report = score_delta(improved, [spec])
    assert report["metrics"]["delta_recall"] == 100.0
    assert report["metrics"]["severity_direction_accuracy"] == 0.0


def test_immaterial_changes_do_not_count_toward_recall():
    spec = copy.deepcopy(SPEC)
    spec["changes"].append({
        "id": "D9", "kind": "immaterial", "target": "cushion",
        "description": "cushion moved along the sofa", "material": False,
    })
    report = score_delta(_comparison(), [spec])
    assert report["counts"]["material_changes"] == 2
    assert report["counts"]["immaterial_changes"] == 1
    assert report["metrics"]["delta_recall"] == 100.0


def test_build_report_scores_only_review_accepted_pairs(tmp_path):
    dataset = _write_dataset(tmp_path)
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(json.dumps(_comparison()), encoding="utf-8")
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps({
        "status": "complete",
        "pairs": [{"delta_id": "RP-901-T1", "decision": "reject",
                   "unenumerated_material_changes": []}],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="no accepted delta specifications"):
        build_report(dataset, comparison_path, review_path)

    review_path.write_text(json.dumps({
        "status": "complete",
        "pairs": [{"delta_id": "RP-901-T1", "decision": "accept",
                   "unenumerated_material_changes": []}],
    }), encoding="utf-8")
    report = build_report(dataset, comparison_path, review_path)
    assert report["scored_deltas"] == ["RP-901-T1"]
    assert report["review_gated"] is True
    assert "cannot promote compare behaviour" in report["evidence_class"]


def test_build_report_refuses_an_incomplete_review(tmp_path):
    dataset = _write_dataset(tmp_path)
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(json.dumps(_comparison()), encoding="utf-8")
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps({"status": "partial", "pairs": []}),
                           encoding="utf-8")
    with pytest.raises(ValueError, match="not complete"):
        build_report(dataset, comparison_path, review_path)


def test_the_shipped_dataset_holds_only_the_feasibility_probe():
    """Phase 3.5 is gated on the probe, so only probe specs may exist.

    The pilot's 8 temporal and 4 counterfactual pairs are downstream of a gate
    that has not been run. A spec that is not marked as probe work would be
    pilot work authored before its gate, which is the sequencing failure the
    phase is built to prevent.
    """
    specs = [spec for spec, _ in load_specs(DATASET)]
    assert sorted(spec["id"] for spec in specs) == [
        "RP-002-T1", "RP-004-T1", "RP-011-T1"
    ]
    assert {spec["probe"] for spec in specs} == {"phase-3.5-feasibility"}


def test_the_probe_spans_the_three_required_room_classes():
    """The gate asks for a kitchen, a soft-furnished room and a bathroom.

    One room class is one drift surface. Three kitchens would pass a gate that
    says nothing about carpet, fabric or sealant, which is where the pilot's
    change kinds actually live.
    """
    rooms = {parent["room_type"] for _, parent in load_specs(DATASET)}
    assert rooms == {"Kitchen", "Living room", "Bathroom"}


def test_the_probe_queue_stays_within_its_gate():
    """The probe is six frames at no more than two attempts each.

    Generation began on 4 Aug 2026, so the queue is no longer uniformly
    pending. What must stay true is the shape of the gate itself: docs/31
    caps the probe at two attempts per scenario and forbids a looser retry,
    and a seventh row would be pilot work authored before its gate.
    """
    with (DATASET / "delta_tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert all(int(row["attempts"] or 0) <= MAX_PROBE_ATTEMPTS for row in rows)


def test_no_recorded_probe_frame_is_a_copy_of_its_reference():
    """A T1 that echoes its T0 is the failure this phase cannot afford.

    It presents as flawless — identity intact, nothing drifted — and fails
    only on the enumerated changes being absent. Checked against the shipped
    fixture, not just in the recorder's unit tests, because this is the one
    defect that would look like clean gold in the ledger.
    """
    with (DATASET / "delta_tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if not row["output_sha256"]:
            continue
        assert row["output_sha256"] != row["reference_sha256"], row["task_id"]
