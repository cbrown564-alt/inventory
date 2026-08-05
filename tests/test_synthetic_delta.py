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
from evals.synthetic.apply_delta_gold_corrections import apply as apply_corrections
from evals.synthetic.build_delta_gallery import build as build_gallery
from evals.synthetic.generate_delta_codex import (
    build_command,
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
from evals.synthetic.prompts import PROMPTS, prompt_sha256
from evals.synthetic.run_eval import _rendered_request, _sha256_file
from evals.synthetic.run_delta_eval import build_delta_run_plan, compare_pair
from evals.synthetic.aggregate_delta_scores import (
    attribute_missed_conditions,
    _decomposition_summary,
    _metrics,
    decompose_false_changes,
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
    (dataset / "splits").mkdir(parents=True)
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
    (dataset / "splits/development.json").write_text(
        json.dumps({"split": "development", "scenario_ids": ["RP-901"]}),
        encoding="utf-8",
    )
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


OBSERVED = {
    "id": "O1",
    "kind": "item_added",
    "target": "scatter cushions",
    "description": "an extra blue cushion is present at T1",
    "material": True,
    "source": "reports/phase35-delta-review-2026-08-04.json",
}


def test_observed_changes_never_touch_the_generation_prompt(tmp_path):
    """Completing the gold must not rewrite the prompt of an existing image.

    `changes` is both the generation instruction and the gold. Once a frame
    exists its prompt is frozen history — the hash pins the frame's
    provenance — so drift found afterwards has to be scored from somewhere the
    prompt builder cannot see.
    """
    dataset = _write_dataset(tmp_path)
    before = write_tasks(dataset)
    hashes = {row["task_id"]: row["prompt_sha256"] for row in before}

    spec = copy.deepcopy(SPEC)
    spec["observed_changes"] = [OBSERVED]
    (dataset / "deltas/RP-901-T1.json").write_text(json.dumps(spec), encoding="utf-8")

    after = write_tasks(dataset)
    assert {row["task_id"]: row["prompt_sha256"] for row in after} == hashes
    assert "extra blue cushion" not in after[0]["exact_prompt"]


def test_observed_drift_is_scored_as_gold_not_as_a_false_change(tmp_path):
    """The reason the field exists: correct reporting must not be punished."""
    spec = copy.deepcopy(SPEC)
    spec["observed_changes"] = [dict(OBSERVED, target="wall mirror",
                                     description="a mirror is present at T1")]
    comparison = _comparison(added=[{"name": "wall mirror"}])

    without = score_delta(comparison, [SPEC])
    assert without["counts"]["false_changes"] == 1

    with_observed = score_delta(comparison, [spec])
    assert with_observed["counts"]["false_changes"] == 0
    assert with_observed["metrics"]["false_change_rate"] == 0.0


def test_an_observed_change_must_name_the_review_that_found_it():
    spec = copy.deepcopy(SPEC)
    spec["observed_changes"] = [{k: v for k, v in OBSERVED.items() if k != "source"}]
    with pytest.raises(ValueError, match="must name the review"):
        validate_spec(spec, PARENT)


def test_an_observed_change_cannot_reuse_an_enumerated_change_id():
    spec = copy.deepcopy(SPEC)
    spec["observed_changes"] = [dict(OBSERVED, id="D1")]
    with pytest.raises(ValueError, match="duplicate change id"):
        validate_spec(spec, PARENT)


RETRACTION = {
    "id": "D1",
    "issue": "t0_premise_wrong",
    "reason": "there is no stain-free carpet at T0 to worsen",
    "source": "reports/phase35-pilot-review-recut-2026-08-05.json",
}


def test_a_retracted_change_leaves_the_generation_prompt_alone(tmp_path):
    """Same reason as observed_changes, from the other direction.

    A change the frames do not carry still has to stay in `changes`, because
    that list is the prompt an existing image was made under.
    """
    dataset = _write_dataset(tmp_path)
    before = write_tasks(dataset)
    hashes = {row["task_id"]: row["prompt_sha256"] for row in before}

    spec = copy.deepcopy(SPEC)
    spec["retracted_changes"] = [RETRACTION]
    (dataset / "deltas/RP-901-T1.json").write_text(json.dumps(spec), encoding="utf-8")

    after = write_tasks(dataset)
    assert {row["task_id"]: row["prompt_sha256"] for row in after} == hashes
    assert "dark stain roughly 15cm" in after[0]["exact_prompt"]


def test_a_retracted_change_stops_costing_recall_and_starts_costing_invention():
    """A change that is not in the frames must score both ways round.

    Missing it is not a miss — there is nothing to see. Reporting it is an
    invention, because the model is describing the prompt, not the photograph.
    """
    spec = copy.deepcopy(SPEC)
    spec["retracted_changes"] = [RETRACTION]
    comparison = _comparison()

    without = score_delta(comparison, [SPEC])
    assert without["counts"]["material_changes"] == 2
    assert without["counts"]["false_changes"] == 0

    with_retraction = score_delta(comparison, [spec])
    assert with_retraction["counts"]["material_changes"] == 1
    assert with_retraction["counts"]["false_changes"] == 1


def test_a_retraction_must_name_a_real_change_and_carry_its_reasons():
    spec = copy.deepcopy(SPEC)
    spec["retracted_changes"] = [dict(RETRACTION, id="D9")]
    with pytest.raises(ValueError, match="not in changes"):
        validate_spec(spec, PARENT)

    for field in ("reason", "source"):
        spec["retracted_changes"] = [
            {k: v for k, v in RETRACTION.items() if k != field}
        ]
        with pytest.raises(ValueError, match=f"must give a {field}"):
            validate_spec(spec, PARENT)

    spec["retracted_changes"] = [dict(RETRACTION, issue="looked wrong")]
    with pytest.raises(ValueError, match="retraction issue must be"):
        validate_spec(spec, PARENT)


def test_retracting_every_material_change_in_a_view_is_rejected():
    """A spec that retracts its way to nothing cannot be scored."""
    spec = copy.deepcopy(SPEC)
    spec["retracted_changes"] = [
        dict(RETRACTION, id=change["id"]) for change in spec["changes"]
    ]
    with pytest.raises(ValueError, match="at least one change must be material"):
        validate_spec(spec, PARENT)


def _recut_review(tmp_path: Path) -> Path:
    review = tmp_path / "recut.json"
    review.write_text(json.dumps({
        "completed_at": "2026-08-05",
        "pairs": [{
            "delta_id": "RP-901-T1",
            "decision": "accept",
            "gold_corrections": [
                {"change_id": "D1", "issue": "t0_premise_wrong",
                 "recommendation": "no clean carpet at T0; drop D1"},
                {"change_id": "D2", "issue": "spec_contradiction",
                 "recommendation": "reword the unchanged assertion"},
            ],
            "incidental_differences": [
                {"target": "tea towel", "description": "moved to the other handle"},
                {"target": "camera", "description": "the T1 framing is closer"},
            ],
        }],
    }), encoding="utf-8")
    return review


def test_applying_gold_corrections_writes_both_side_lists(tmp_path):
    dataset = _write_dataset(tmp_path)
    write_tasks(dataset)
    report = apply_corrections(dataset, _recut_review(tmp_path))

    spec = json.loads(
        (dataset / "deltas/RP-901-T1.json").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in spec["retracted_changes"]] == ["D1"]
    assert [item["target"] for item in spec["observed_changes"]] == ["tea towel"]
    assert spec["observed_changes"][0]["material"] is False
    assert report["prompt_hashes_unchanged"] is True
    # A wording problem in the unchanged assertions cannot be repaired by a
    # side list, so it is skipped loudly rather than half-applied.
    assert report["counts"]["skipped:spec_contradiction"] == 1


def test_applying_gold_corrections_never_records_a_camera_move_as_gold(tmp_path):
    """Framing drift is review context. As gold it would let a compare run
    score a camera move as a change in the property."""
    dataset = _write_dataset(tmp_path)
    write_tasks(dataset)
    apply_corrections(dataset, _recut_review(tmp_path))

    spec = json.loads(
        (dataset / "deltas/RP-901-T1.json").read_text(encoding="utf-8")
    )
    assert all(item["target"] != "camera" for item in spec["observed_changes"])


def test_applying_gold_corrections_twice_changes_nothing_the_second_time(tmp_path):
    dataset = _write_dataset(tmp_path)
    write_tasks(dataset)
    review = _recut_review(tmp_path)
    apply_corrections(dataset, review)
    first = (dataset / "deltas/RP-901-T1.json").read_text(encoding="utf-8")

    apply_corrections(dataset, review)
    assert (dataset / "deltas/RP-901-T1.json").read_text(encoding="utf-8") == first


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
        "room_identity_findings": [],
        "enumerated": [
            {"change_id": "D1", "visibility": "clear", "notes": ""},
            {"change_id": "D2", "visibility": "clear", "notes": ""},
        ],
        "incidental_differences": [],
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


def test_a_moved_fixture_rejects_the_pair_even_when_both_reviewers_accepted():
    """The failure the pilot has to catch: the room stopped being the room."""
    drifted = _accepting_review(room_identity_findings=[
        {"view": "A-wide", "element": "oven",
         "description": "the built-in oven sits lower in the run at T1"}
    ])
    result = combine(EXPECTED, drifted, drifted)
    assert result["decision"] == "reject"
    assert result["decision_basis"] == "room identity failed"
    assert result["same_room"] is False


def test_moved_clutter_is_recorded_and_never_rejects_the_pair():
    """A tenant moves a tea towel; that is not the generator losing the room.

    The old rubric rejected on exactly this, which buried the real failures
    under a list of towels and toasters.
    """
    cluttered = _accepting_review(incidental_differences=[
        {"target": "tea towel", "description": "hung on the other oven handle"}
    ])
    result = combine(EXPECTED, cluttered, _accepting_review())
    assert result["decision"] == "accept"
    assert result["incidental_differences"][0]["target"] == "tea towel"


def test_failed_room_identity_rejects_the_pair():
    result = combine(
        EXPECTED,
        _accepting_review(same_room=False, decision="reject"),
        _accepting_review(),
    )
    assert result["decision"] == "reject"
    assert result["decision_basis"] == "room identity failed"


def test_a_missing_change_corrects_the_gold_rather_than_binning_the_pair():
    absent = _accepting_review(enumerated=[
        {"change_id": "D1", "visibility": "absent", "notes": ""},
        {"change_id": "D2", "visibility": "clear", "notes": ""},
    ])
    result = combine(EXPECTED, absent, _accepting_review())
    assert result["decision"] == "accept"
    assert result["missing_material_changes"] == ["D1"]
    assert result["visible_material_changes"] == ["D1", "D2"]


def test_a_pair_showing_no_enumerated_change_carries_no_signal():
    blank = _accepting_review(enumerated=[
        {"change_id": "D1", "visibility": "absent", "notes": ""},
        {"change_id": "D2", "visibility": "ambiguous", "notes": ""},
    ])
    result = combine(EXPECTED, blank, blank)
    assert result["decision"] == "reject"
    assert "no delta signal" in result["decision_basis"]


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
            "room_identity_findings": list(drift),
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


def test_the_prompt_never_follows_the_variadic_image_flag(tmp_path):
    """`-i/--image` is variadic and will eat the prompt as a second filename.

    When it does, Codex finds no prompt argument, falls back to stdin, gets
    nothing and exits having generated no image. The whole batch failed this
    way once; the argument order is the fix, so it is asserted rather than
    remembered.
    """
    dataset = _write_dataset(tmp_path)
    row = write_tasks(dataset)[0]
    command = build_command(dataset, row, Path("codex"), tmp_path / "last.txt")

    assert command[-1] == build_instruction(row)
    assert command[-2] != "-i"
    assert command[command.index("-i") + 2].startswith("-")


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
        Path(command[command.index("-o") + 1]).write_text(
            f"```text\n{reported}\n```\n", encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

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
# build_delta_gallery
# --------------------------------------------------------------------------


def test_the_gallery_pairs_each_t0_with_its_t1(tmp_path):
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    record(dataset, "operator", "cli")

    output = build_gallery(dataset, tmp_path / "gallery.html")
    html = output.read_text(encoding="utf-8")
    assert html.count("RP-901-A-wide.png") == 1
    assert html.count("RP-901-T1-A-wide.png") == 1
    assert "T0 — check-in (accepted)" in html
    assert "unreviewed" in html


def test_the_gallery_names_the_immaterial_change_as_a_false_change(tmp_path):
    """The owner has to see which difference is a trap, not just which exist.

    A rearranged cushion is a real difference and reporting it is a false
    change. Shown in an undifferentiated list, it reads as one more thing to
    tick off, and the pair gets adjudicated against the wrong standard.
    """
    dataset = _write_dataset(tmp_path)
    spec = copy.deepcopy(SPEC)
    spec["changes"].append({
        "id": "D9", "kind": "immaterial", "target": "cushions",
        "description": "rearranged along the sofa", "material": False,
    })
    (dataset / "deltas/RP-901-T1.json").write_text(json.dumps(spec), encoding="utf-8")
    _render(dataset)

    html = build_gallery(dataset, tmp_path / "gallery.html").read_text(encoding="utf-8")
    assert "rearranged along the sofa" in html
    assert "false change" in html


def test_the_gallery_surfaces_reported_drift(tmp_path):
    """Old flat-drift reports still render; they predate the 5 Aug rubric."""
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"status": "complete", "pairs": [{
        "delta_id": "RP-901-T1", "decision": "reject",
        "decision_basis": "unenumerated material change observed",
        "unenumerated_material_changes": [
            {"target": "curtains", "description": "now patterned", "material": True}
        ],
    }]}), encoding="utf-8")

    html = build_gallery(
        dataset, tmp_path / "gallery.html", review
    ).read_text(encoding="utf-8")
    assert "curtains" in html and "now patterned" in html
    assert 'class="verdict reject"' in html


def test_the_gallery_separates_identity_findings_from_moved_clutter(tmp_path):
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"status": "complete", "pairs": [{
        "delta_id": "RP-901-T1", "decision": "reject",
        "decision_basis": "room identity failed",
        "room_identity_findings": [
            {"view": "A-wide", "element": "oven",
             "description": "the oven sits lower in the run at T1"}
        ],
        "incidental_differences": [
            {"target": "tea towel", "description": "hung on the other handle"}
        ],
        "cross_view_conflicts": ["the toaster is in one T1 view only"],
        "enumerated": [
            {"change_id": "D1", "visibility": "absent", "notes": "no stain rendered"}
        ],
        "gold_corrections": [
            {"change_id": "D1", "issue": "not_rendered", "recommendation": "drop D1"}
        ],
    }]}), encoding="utf-8")

    html = build_gallery(
        dataset, tmp_path / "gallery.html", review
    ).read_text(encoding="utf-8")
    identity = html.index("Room identity findings")
    incidental = html.index("Incidental")
    assert identity < incidental, "identity findings must lead the pair"
    assert "the oven sits lower in the run at T1" in html
    assert "hung on the other handle" in html
    assert "the toaster is in one T1 view only" in html
    assert "no stain rendered" in html and "drop D1" in html


def test_the_gallery_can_limit_to_reviewed_pairs(tmp_path):
    dataset = _write_dataset(tmp_path)
    _render(dataset)
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"status": "complete", "pairs": [{
        "delta_id": "RP-901-T1", "decision": "accept",
    }]}), encoding="utf-8")

    html = build_gallery(
        dataset, tmp_path / "gallery.html", review, reviewed_only=True
    ).read_text(encoding="utf-8")
    assert html.count('class="pair"') == 1
    assert "RP-901-T1" in html


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


def test_the_shipped_dataset_contains_the_probe_and_30_pair_pilot():
    """The feasibility gate remains present beside the completed pilot."""
    specs = [spec for spec, _ in load_specs(DATASET)]
    probe_ids = [
        "RP-002-T1", "RP-004-T1", "RP-011-T1"
    ]
    assert sorted(spec["id"] for spec in specs if spec.get("probe")) == sorted(probe_ids)
    pilot = [spec for spec in specs if spec["id"].startswith("P35-")]
    assert len(pilot) == 30
    assert {spec["delta_class"] for spec in pilot} == {"temporal", "counterfactual"}
    assert sum(spec["delta_class"] == "temporal" for spec in pilot) == 20
    assert sum(spec["delta_class"] == "counterfactual" for spec in pilot) == 10
    assert sum(any(change["kind"] == "immaterial" for change in spec["changes"])
               for spec in pilot) >= 6


def test_the_probe_spans_the_three_required_room_classes():
    """The gate asks for a kitchen, a soft-furnished room and a bathroom.

    One room class is one drift surface. Three kitchens would pass a gate that
    says nothing about carpet, fabric or sealant, which is where the pilot's
    change kinds actually live.
    """
    rooms = {
        parent["room_type"]
        for spec, parent in load_specs(DATASET)
        if spec.get("probe")
    }
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
    assert len(rows) == 66
    assert sum(row["delta_id"].startswith("P35-") for row in rows) == 60
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


# --------------------------------------------------------------------------
# run_delta_eval
# --------------------------------------------------------------------------


def _write_eval_dataset(tmp_path: Path) -> Path:
    """A dataset with two delta pairs whose frames exist and hash correctly."""
    dataset = _write_dataset(tmp_path)
    (dataset / "dataset.json").write_text(json.dumps({
        "phase_1_prompt_comparison": {
            "prompts": {name: prompt_sha256(body) for name, body in PROMPTS.items()}
        }
    }), encoding="utf-8")
    images = dataset / "images/openai/gpt-image-2"
    deltas = images / "deltas"
    deltas.mkdir(parents=True, exist_ok=True)
    rows = []
    for delta_id in ("RP-901-T1", "RP-902-T1"):
        for view in DELTA_VIEWS:
            reference = images / f"RP-901-{view}.png"
            output = deltas / f"{delta_id}-{view}.png"
            output.write_bytes(f"t1-{delta_id}-{view}".encode())
            rows.append({
                "delta_id": delta_id,
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
    with (dataset / "delta_tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return dataset


def _write_review(dataset: Path, decisions: dict[str, str]) -> Path:
    path = dataset / "review.json"
    path.write_text(json.dumps({
        "status": "complete",
        "pairs": [
            {"delta_id": delta_id, "decision": decision}
            for delta_id, decision in decisions.items()
        ],
    }), encoding="utf-8")
    return path


def test_only_pairs_the_review_accepted_are_planned(tmp_path):
    """An unreviewed or rejected pair has no standing gold to score against.

    ``score_delta`` already refuses to score one; planning a describe run for
    it would spend quota producing a comparison nobody may use.
    """
    dataset = _write_eval_dataset(tmp_path)
    review = _write_review(dataset, {"RP-901-T1": "accept", "RP-902-T1": "reject"})
    plan = build_delta_run_plan(dataset, review, "production-v1", "gemini-3.5-flash-low")
    assert [pair["delta_id"] for pair in plan] == ["RP-901-T1"]


def test_an_incomplete_review_cannot_authorise_a_run(tmp_path):
    dataset = _write_eval_dataset(tmp_path)
    review = dataset / "review.json"
    review.write_text(json.dumps({"status": "in_progress", "pairs": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="not complete"):
        build_delta_run_plan(dataset, review, "production-v1", "gemini-3.5-flash-low")


def test_a_frame_that_no_longer_matches_the_ledger_is_refused(tmp_path):
    """The reviewed frame and the scored frame have to be the same bytes.

    Otherwise a result is attributed to evidence nobody adjudicated, which is
    the one thing the provenance discipline in this dataset exists to prevent.
    """
    dataset = _write_eval_dataset(tmp_path)
    review = _write_review(dataset, {"RP-901-T1": "accept"})
    frame = dataset / "images/openai/gpt-image-2/deltas/RP-901-T1-A-wide.png"
    frame.write_bytes(b"a different image entirely")
    with pytest.raises(ValueError, match="does not match the ledger"):
        build_delta_run_plan(dataset, review, "production-v1", "gemini-3.5-flash-low")


def test_t0_reads_the_reference_frames_and_t1_the_generated_ones(tmp_path):
    dataset = _write_eval_dataset(tmp_path)
    review = _write_review(dataset, {"RP-901-T1": "accept"})
    plan = build_delta_run_plan(dataset, review, "production-v1", "gemini-3.5-flash-low")
    sides = {run["side"]: run for run in plan[0]["runs"]}
    assert all("deltas/" not in item["relative_path"] for item in sides["T0"]["inputs"])
    assert all("deltas/" in item["relative_path"] for item in sides["T1"]["inputs"])


def test_the_describe_request_never_mentions_the_delta(tmp_path):
    """A backend told what changed reports the prompt, not the photograph.

    This is the same objection that bars an operator who has read the gold
    from describing the frames by hand: the run stops measuring vision. Here
    it is enforceable, so it is enforced.
    """
    dataset = _write_eval_dataset(tmp_path)
    review = _write_review(dataset, {"RP-901-T1": "accept"})
    plan = build_delta_run_plan(dataset, review, "production-v1", "gemini-3.5-flash-low")
    for run in plan[0]["runs"]:
        request = _rendered_request(
            room_type=run["room_type"],
            prompt_id=run["prompt_id"],
            prompt=PROMPTS[run["prompt_id"]],
            inputs=run["inputs"],
            model=run["model"],
        )
        text = json.dumps(request)
        for change in SPEC["changes"]:
            assert change["description"] not in text
            assert change["target"] not in text
        assert "T0" not in text and "delta" not in text.lower()


def test_a_prompt_difference_between_timepoints_refuses_the_comparison(tmp_path):
    """The delta must be carried by the images alone.

    Any other difference between the two calls is confounded with the change
    under test, and the resulting rate would not be about the frames at all.
    """
    dataset = _write_eval_dataset(tmp_path)
    review = _write_review(dataset, {"RP-901-T1": "accept"})
    plan = build_delta_run_plan(dataset, review, "production-v1", "gemini-3.5-flash-low")
    records = {
        side: {
            "instruction_sha256": digest,
            "backend_model": "gemini-3.5-flash-low",
            "prompt_id": "production-v1",
            "prompt_sha256": "x",
            "run_id": f"RP-901-T1.{side}",
            "room_type": "Living Room",
            "delta_id": "RP-901-T1",
            "completed_at": "2026-08-05T00:00:00+00:00",
            "inputs": [],
            "parsed_output": {"room_summary": "", "items": []},
        }
        for side, digest in (("T0", "aaa"), ("T1", "bbb"))
    }
    with pytest.raises(ValueError, match="instructions differ"):
        compare_pair(plan[0], records)


# --------------------------------------------------------------------------
# aggregate_delta_scores
# --------------------------------------------------------------------------


def test_a_renamed_object_is_decomposed_as_alignment_churn():
    """One lamp nobody touched, reported twice because the names moved.

    ``match_score`` needs the discriminating tokens to be equal or contained,
    so ``Recessed spotlight`` and ``Ceiling spotlight`` do not align and both
    halves are counted against the model. Naming that as churn is what makes
    the headline rate readable; it never subtracts from it.
    """
    report = {
        "false_changes": [
            {"room": "Living Room", "bucket": "removed", "name": "Recessed spotlight"},
            {"room": "Living Room", "bucket": "added", "name": "Ceiling spotlight"},
            {"room": "Living Room", "bucket": "added", "name": "Threshold strip"},
        ]
    }
    decomposition = decompose_false_changes(report)
    assert decomposition["counts"]["alignment_churn"] == 2
    assert decomposition["counts"]["unpaired_added"] == 1
    assert decomposition["counts"]["unpaired_removed"] == 0
    assert decomposition["rename_candidates"][0]["shared_tokens"] == ["spotlight"]


def test_two_genuinely_different_items_are_not_paired_away():
    report = {
        "false_changes": [
            {"room": "Bathroom", "bucket": "removed", "name": "Hand towel"},
            {"room": "Bathroom", "bucket": "added", "name": "Waste bin"},
        ]
    }
    decomposition = decompose_false_changes(report)
    assert decomposition["counts"]["alignment_churn"] == 0
    assert decomposition["rename_candidates"] == []


def test_the_diagnostic_never_lowers_the_reported_false_change_rate():
    decompositions = [
        decompose_false_changes({
            "false_changes": [
                {"room": "R", "bucket": "removed", "name": "Recessed spotlight"},
                {"room": "R", "bucket": "added", "name": "Ceiling spotlight"},
            ]
        })
    ]
    totals = {"reported_changes": 10, "false_changes": 2, "unchanged_reported": 5}
    summary = _decomposition_summary(decompositions, totals)
    assert summary["share_of_false_changes_that_are_alignment_churn"] == 100.0
    assert summary["false_change_rate_if_renames_aligned"] == 0.0
    assert "not a corrected metric" in summary["diagnostic_note"]


def test_pooled_rates_come_from_summed_counts_not_averaged_pairs():
    """A pair carrying one change must not outvote a pair carrying nine.

    Averaging per-pair rates is what gives the six thin-signal pairs the same
    weight as the rest of the pilot; summing the counts first is the only
    arrangement in which "delta recall" means what the phase says it means.
    """
    rows = (
        [{"material": True, "detected": False, "direction_correct": None}]
        + [{"material": True, "detected": True, "direction_correct": None}] * 9
    )
    totals = {
        "reported_changes": 10,
        "false_changes": 0,
        "unchanged_reported": 10,
    }
    pooled = _metrics(rows, totals)["delta_recall"]
    averaged = (0.0 + 100.0) / 2
    assert pooled == 90.0
    assert pooled != averaged


def test_a_condition_change_on_a_split_object_is_attributed_to_the_aligner():
    """The three fates of a missed condition change call for different fixes.

    ``_satisfies`` can only credit a cleanliness, defect or severity change on
    an item that reached the ``changed`` bucket. When the aligner splits the
    object across ``removed`` and ``added``, its delta is never compared at
    all — which is a different failure from the model looking and staying
    silent, and different again from neither run naming the object.
    """
    comparison = {
        "rooms": [{
            "name": "Kitchen",
            "changed": [{"name": "Worktop"}],
            "unchanged": [{"name": "Sink"}],
            "removed": [{"name": "Ceramic hob"}],
            "added": [{"name": "Induction hob"}],
        }]
    }
    report = {
        "missed_material_changes": [
            {"kind": "cleanliness", "target": "ceramic hob"},
            {"kind": "new_defect", "target": "worktop"},
            {"kind": "worsened", "target": "extractor hood"},
            {"kind": "item_added", "target": "fruit bowl"},
        ]
    }
    counts = attribute_missed_conditions(comparison, report)
    assert counts == {
        "split_by_aligner": 1,
        "tracked_but_silent": 1,
        "never_named": 1,
    }
