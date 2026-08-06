import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from evals.synthetic.apply_video_pass_a import apply
from evals.synthetic.build_video_strip import (
    SILENT_MAX_DBFS,
    build_all,
    declared_gold_timestamps,
    mechanical_checks,
    sample_indices,
)
from evals.synthetic.build_video_tasks import FIELDNAMES
from evals.synthetic.review_video_pass_a import (
    _criteria_for,
    _extract_json,
    reconcile,
    validate_review,
)

DATASET = Path(__file__).resolve().parents[1] / "evals/fixtures/synthetic-room-eval"

CONTAINER = {"duration_s": 10.005, "width": 1280, "height": 720, "fps": 24.0,
             "frame_count": 240, "video_codec": "h264", "audio_streams": 1,
             "audio_codec": "aac"}


def _audio(**overrides):
    base = {"stream_present": True, "max_dbfs": -80.0, "mean_dbfs": -90.0,
            "sound_runs": [], "first_sound_at_s": None}
    return {**base, **overrides}


def test_strip_samples_every_second_and_always_the_final_frame():
    """A clip that "comes to rest facing X" is only judged at its last frame.

    A cadence that stops at the last whole second lands on frame 216 of 240 and
    never sees where the camera settled.
    """
    frames = sample_indices(CONTAINER, [])
    assert [frame["index"] for frame in frames] == [
        0, 24, 48, 72, 96, 120, 144, 168, 192, 216, 239
    ]
    assert frames[-1]["source"] == "final_frame"
    assert frames[-1]["timestamp_s"] == pytest.approx(9.958, abs=0.001)


def test_declared_gold_timestamps_are_sampled_and_labelled_as_requested():
    """The grid must include declared times without calling them gold.

    docs/34: gold timing is read from the delivered file. A frame sampled at a
    requested cue time is evidence about that moment, not proof the cue is
    there, and the label is what stops a later reader treating it as proof.
    """
    frames = sample_indices(CONTAINER, [1.0, 4.5])
    by_index = {frame["index"]: frame for frame in frames}
    assert by_index[24]["source"] == "declared_gold_timestamp"
    assert by_index[108]["source"] == "declared_gold_timestamp"
    assert by_index[0]["source"] == "cadence"


def test_declared_gold_timestamps_reads_cue_and_boundary_and_skips_nulls():
    assert declared_gold_timestamps(
        {"audio": {"cue_at_s": 1.0}, "gold": {"boundary_at_s": None}}
    ) == [1.0]
    assert declared_gold_timestamps({"gold": {"boundary_at_s": 3.5}}) == [3.5]
    assert declared_gold_timestamps({}) == []


def test_a_silent_clip_with_an_audible_track_fails_its_audio_criterion():
    """Acceptance criterion 9 covers the silent case explicitly."""
    checks = mechanical_checks(
        {"audio_mode": "silent"}, CONTAINER,
        _audio(max_dbfs=-22.6, sound_runs=[{"start_s": 1.3, "end_s": 2.0}]),
        [],
    )
    audio = next(c for c in checks if c["criterion"] == "audio_mode_silent")
    assert audio["status"] == "fail"
    assert "-22.6" in audio["detail"]


def test_a_silent_clip_below_the_floor_or_without_a_stream_passes():
    quiet = mechanical_checks({"audio_mode": "silent"}, CONTAINER,
                              _audio(max_dbfs=SILENT_MAX_DBFS - 1), [])
    assert next(c for c in quiet
                if c["criterion"] == "audio_mode_silent")["status"] == "pass"
    none = mechanical_checks(
        {"audio_mode": "silent"}, {**CONTAINER, "audio_streams": 0},
        _audio(stream_present=False, max_dbfs=None), [],
    )
    assert next(c for c in none
                if c["criterion"] == "audio_mode_silent")["status"] == "pass"


def test_a_narrated_clip_is_indeterminate_rather_than_passed():
    """Measurement can find speech; it cannot confirm the words.

    Reporting a pass here would claim the declared cue was spoken, which no
    part of this pipeline has checked.
    """
    checks = mechanical_checks(
        {"audio_mode": "narrated"}, CONTAINER,
        _audio(max_dbfs=-13.7, sound_runs=[{"start_s": 1.1, "end_s": 2.4}],
               first_sound_at_s=1.1),
        [],
    )
    narrated = next(c for c in checks if c["criterion"] == "audio_mode_narrated")
    assert narrated["status"] == "indeterminate"
    assert "1.1" in narrated["detail"]


def test_a_narrated_clip_with_no_audible_run_fails():
    checks = mechanical_checks({"audio_mode": "narrated"}, CONTAINER,
                               _audio(), [])
    assert next(c for c in checks
                if c["criterion"] == "audio_mode_narrated")["status"] == "fail"


def test_a_scene_cut_fails_the_unbroken_take_criterion():
    checks = mechanical_checks(
        {"audio_mode": "silent"}, CONTAINER, _audio(),
        [{"timestamp_s": 4.5, "score": 0.82}],
    )
    take = next(c for c in checks if c["criterion"] == "one_unbroken_take")
    assert take["status"] == "fail"
    assert "4.5" in take["detail"]


def test_the_occlusion_criterion_is_only_asked_of_clips_that_declare_one():
    plain = {name for name, _ in _criteria_for({})}
    occluded = {name for name, _ in
                _criteria_for({"must_never_be_visible": ["rear floor"]})}
    assert "occlusion_respected" not in plain
    assert occluded - plain == {"occlusion_respected"}


def test_a_measured_failure_escalates_instead_of_being_voted_away():
    """Two reviewers who cannot hear must not be able to accept a bad track.

    It escalates rather than auto-rejecting because the remedy for an unwanted
    audio track on a visual use case is free, and choosing to take it is the
    owner's call.
    """
    accept = {"decision": "accept", "reason": "clean"}
    decision, reason = reconcile(
        accept, dict(accept),
        [{"criterion": "audio_mode_silent", "status": "fail", "detail": "-22 dBFS"}],
    )
    assert decision == "escalate"
    assert "audio_mode_silent" in reason


def test_reconcile_agrees_disagrees_and_accepts():
    clean = [{"criterion": "one_unbroken_take", "status": "pass", "detail": ""}]
    assert reconcile({"decision": "accept", "reason": "ok"},
                     {"decision": "accept", "reason": "ok"}, clean)[0] == "accept"
    assert reconcile({"decision": "reject", "reason": "bad"},
                     {"decision": "reject", "reason": "bad"}, clean)[0] == "reject"
    assert reconcile({"decision": "accept", "reason": "ok"},
                     {"decision": "reject", "reason": "bad"}, clean)[0] == "escalate"
    # A measured failure must not turn a genuine reject into an escalation.
    failed = [{"criterion": "audio_mode_silent", "status": "fail", "detail": ""}]
    assert reconcile({"decision": "reject", "reason": "bad"},
                     {"decision": "reject", "reason": "bad"}, failed)[0] == "reject"


def test_review_json_survives_prose_and_braces_around_it():
    """Slicing first-brace-to-last-brace parses as nothing once prose has one.

    This cost a run: a reviewer wrote a sentence after its JSON and the whole
    batch died six clips in.
    """
    assert _extract_json(
        'Here is my review:\n{"decision": "accept", "criteria": []}\n'
        "Hope that helps {not json}."
    ) == {"decision": "accept", "criteria": []}
    assert _extract_json(
        '{"decision": "escalate", "reason": "a brace { in a note", "criteria": []}'
    )["reason"] == "a brace { in a note"
    assert _extract_json('```json\n{"decision": "reject", "criteria": []}\n```')[
        "decision"] == "reject"
    with pytest.raises(ValueError, match="no JSON object found"):
        _extract_json("I could not complete the review.")


def test_a_review_that_skips_a_criterion_is_rejected():
    """A silently short answer would read as a pass on the missing criterion."""
    payload = {"clip_id": "VU-9.RP-000"}
    complete = [{"criterion": name, "verdict": "pass", "note": ""}
                for name, _ in _criteria_for(payload)]
    validate_review(payload, {"decision": "accept", "criteria": complete})
    with pytest.raises(ValueError, match="skipped criteria"):
        validate_review(payload, {"decision": "accept", "criteria": complete[:-1]})
    with pytest.raises(ValueError, match="invalid decision"):
        validate_review(payload, {"decision": "looks fine", "criteria": complete})


def _ledger(tmp_path: Path, clip_sha: str) -> Path:
    dataset = tmp_path / "ds"
    (dataset / "video").mkdir(parents=True)
    row = {name: "" for name in FIELDNAMES}
    row.update({"task_id": "VU-9.RP-000.gemini-omni-video", "clip_id": "VU-9.RP-000",
                "status": "review_pending", "output_sha256": clip_sha})
    with (dataset / "video" / "tasks.csv").open("w", newline="", encoding="utf-8") as h:
        writer = csv.DictWriter(h, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(row)
    return dataset


def _review(tmp_path: Path, **overrides) -> Path:
    payload = {
        "status": "complete",
        "clips": [{"clip_id": "VU-9.RP-000", "clip_sha256": "abc",
                   "strip_sha256": "def", "pass_a_decision": "accept"}],
    }
    payload.update(overrides)
    path = tmp_path / "review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_apply_writes_the_strip_hash_alongside_the_decision(tmp_path):
    dataset = _ledger(tmp_path, "abc")
    apply(dataset, _review(tmp_path))
    with (dataset / "video" / "tasks.csv").open(newline="", encoding="utf-8") as h:
        row = next(iter(csv.DictReader(h)))
    assert row["status"] == "pass_a_accepted"
    assert row["strip_sha256"] == "def"


def test_apply_refuses_a_partial_review(tmp_path):
    dataset = _ledger(tmp_path, "abc")
    with pytest.raises(ValueError, match="partial review"):
        apply(dataset, _review(tmp_path, status="partial"))


def test_apply_refuses_when_the_clip_changed_after_review(tmp_path):
    """A review describes one file. Restaging a different take voids it."""
    dataset = _ledger(tmp_path, "a-different-clip")
    with pytest.raises(ValueError, match="changed after it was reviewed"):
        apply(dataset, _review(tmp_path))


def test_a_rejected_clip_is_not_archived_by_the_apply_step(tmp_path):
    """Archiving is destructive and consumes a slot; it stays an owner act."""
    dataset = _ledger(tmp_path, "abc")
    apply(dataset, _review(tmp_path, clips=[
        {"clip_id": "VU-9.RP-000", "clip_sha256": "abc", "strip_sha256": "def",
         "pass_a_decision": "reject"}]))
    with (dataset / "video" / "tasks.csv").open(newline="", encoding="utf-8") as h:
        row = next(iter(csv.DictReader(h)))
    assert row["status"] == "pass_a_rejected"
    assert not (dataset / "video" / "rejected").exists()


def test_the_video_ledger_carries_a_strip_hash_column():
    with (DATASET / "video" / "tasks.csv").open(newline="", encoding="utf-8") as h:
        assert "strip_sha256" in (csv.DictReader(h).fieldnames or [])


def test_no_omni_view_assignment_contradicts_its_own_source_filename():
    """After the repair, no filename that names a view disagrees with its id.

    Gemini names downloads after the prompt, so a good fraction of these files
    state their own view. Before the repair four of them contradicted the id
    they were filed under and every packet's A-wide slot held a condition
    detail; both are now zero.
    """
    from evals.synthetic.audit_gemini_omni_views import audit

    result = audit()
    assert result["total_contradictions"] == 0
    positional, named = result["routes"]
    assert positional["contradictions"] == []
    assert named["contradictions"] == []
    # The bug is still described, so the repair cannot be quietly undone.
    assert positional["superseded_rule"]["contradictions_it_produced"] == 4
    slot = result["a_wide_slot"]
    assert len(slot["packets"]) == 9
    assert slot["naming_a_condition_view"] == 0


def test_rebuilding_refuses_to_restamp_a_delivered_clips_reference(tmp_path,
                                                                  monkeypatch):
    """A delivered clip's reference digest is history, not a derived field.

    Recomputing it after the reference frame changed would record a
    conditioning that never happened — which is precisely how the Omni view
    mix-up survived: nothing ever compared what a clip was made from against
    what the ledger said it was made from.
    """
    import evals.synthetic.build_video_tasks as build

    rows = [{name: "" for name in FIELDNAMES}]
    rows[0].update({"task_id": "VU-9.RP-000.gemini-omni-video",
                    "clip_id": "VU-9.RP-000", "prompt_sha256": "p",
                    "reference_sha256": "new-reference", "status": "pending"})
    monkeypatch.setattr(build, "build_rows", lambda _dir: rows)
    dataset = tmp_path / "ds"
    (dataset / "video").mkdir(parents=True)
    stale = dict(rows[0], reference_sha256="old-reference",
                 output_sha256="a-delivered-clip", status="pass_a_accepted")
    with (dataset / "video" / "tasks.csv").open("w", newline="",
                                                encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(stale)
    with pytest.raises(SystemExit, match="reference frame changed"):
        build.write_tasks(dataset, allow_unimported=True)


def test_the_repair_is_a_rename_and_nothing_else():
    """Bytes are evidence. Re-filing may move a name, never a pixel."""
    from evals.synthetic.repair_gemini_omni_views import TRUE_VIEW

    report = json.loads(
        (DATASET / "reports" / "gemini-omni-view-repair-2026-08-04.json")
        .read_text(encoding="utf-8")
    )
    assert report["count"] == 36
    assert all(move["bytes_changed"] is False for move in report["moves"])
    images = DATASET / "images/google/gemini-omni"
    for move in report["moves"]:
        target = images / move["to"]
        assert target.is_file(), move["to"]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == move["sha256"]
    # The correction is its own inverse, which is what "reversed" means.
    assert all(TRUE_VIEW[TRUE_VIEW[view]] == view for view in TRUE_VIEW)


def test_every_video_reference_frame_comes_from_the_affected_import():
    """Scope the damage: which clips rest on a suspect reference frame."""
    from evals.synthetic.stage_gemini_omni_prior_batches import BATCHES

    with (DATASET / "video" / "tasks.csv").open(newline="", encoding="utf-8") as h:
        rows = list(csv.DictReader(h))
    assert rows
    assert all(row["reference_path"].endswith("-A-wide.jpeg") for row in rows)
    assert {row["scenario_id"] for row in rows} <= set(BATCHES)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_the_strip_hash_is_stable_across_rebuilds():
    """The strip hash is over decoded pixels, so a rebuild must reproduce it.

    If it drifted, an accepted clip's recorded strip could never be checked
    again and the acceptance record would be unfalsifiable.
    """
    clip_id = "VU-5.RP-019-hold"
    manifest_path = DATASET / "video" / "strips" / clip_id / "strip.json"
    if not manifest_path.is_file():
        pytest.skip("strip not built")
    rebuilt = build_all(DATASET, {clip_id})
    if not rebuilt:
        pytest.skip("clip is no longer staged; its strip is a historical record")
    before = json.loads(manifest_path.read_text(encoding="utf-8"))
    after = rebuilt[0]
    assert after["strip_sha256"] == before["strip_sha256"]
    assert [f["pixel_sha256"] for f in after["frames"]] == \
           [f["pixel_sha256"] for f in before["frames"]]


def _triage_ledger(tmp_path, rows):
    dataset = tmp_path / "ds"
    (dataset / "video").mkdir(parents=True)
    with (dataset / "video" / "tasks.csv").open("w", newline="",
                                               encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: "" for name in FIELDNAMES} | row)
    return dataset


def _triage_row(use_case_id, **overrides):
    return {"task_id": f"{use_case_id}.RP-000.gemini-omni-video",
            "clip_id": f"{use_case_id}.RP-000", "use_case_id": use_case_id,
            "reference_provenance": "pass_a_accepted",
            "status": "retry_pending"} | overrides


def test_the_triage_clears_only_vu5_and_says_why_for_the_rest(tmp_path):
    """Three dispositions, not two. The arm is five questions, not one."""
    from evals.synthetic.triage_video_arm import triage

    dataset = _triage_ledger(tmp_path, [_triage_row(uc)
                                        for uc in ("VU-1", "VU-2", "VU-3",
                                                   "VU-4", "VU-5")])
    record = triage(dataset)

    now = {d["use_case_id"]: d["now"] for d in record["decisions"]}
    assert now == {"VU-1": "suspended", "VU-2": "suspended", "VU-3": "suspended",
                   "VU-4": "retired", "VU-5": "retry_pending"}
    assert record["clips_cleared_to_generate"] == ["VU-5.RP-000"]
    # A suspension that does not carry its reason is indistinguishable from
    # having run out of schedule, which is the thing this triage is not.
    assert all(d["reason"] for d in record["decisions"])


def test_the_triage_survives_being_applied_twice(tmp_path):
    from evals.synthetic.triage_video_arm import triage

    dataset = _triage_ledger(tmp_path, [_triage_row("VU-1"), _triage_row("VU-5")])
    first = triage(dataset)
    second = triage(dataset)
    assert [d["now"] for d in first["decisions"]] == [d["now"] for d in
                                                      second["decisions"]]
    assert [d["was"] for d in second["decisions"]] == ["suspended", "retry_pending"]


def test_the_triage_refuses_when_vu5s_reference_stops_being_accepted(tmp_path):
    """The clearance is the load-bearing half and it rests on a mutable fact."""
    from evals.synthetic.triage_video_arm import triage

    dataset = _triage_ledger(
        tmp_path, [_triage_row("VU-5", reference_provenance="pass_a_rejected")])
    with pytest.raises(ValueError, match="cannot produce gold"):
        triage(dataset)


def test_the_triage_refuses_to_park_a_row_holding_a_delivered_clip(tmp_path):
    """Suspension is not an archive. The artefact belongs in video/rejected/."""
    from evals.synthetic.triage_video_arm import triage

    dataset = _triage_ledger(tmp_path,
                             [_triage_row("VU-1", output_sha256="delivered")])
    with pytest.raises(ValueError, match="reject_video_clip"):
        triage(dataset)


def test_a_new_use_case_must_be_decided_rather_than_defaulted(tmp_path):
    from evals.synthetic.triage_video_arm import triage

    dataset = _triage_ledger(tmp_path, [_triage_row("VU-6")])
    with pytest.raises(ValueError, match="no disposition for VU-6"):
        triage(dataset)


def test_the_applied_triage_matches_the_shipped_ledger():
    """The fixture is the record; drift between them is a silent revival."""
    with (DATASET / "video" / "tasks.csv").open(newline="",
                                                encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_status = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row["use_case_id"])
    assert sorted(by_status["retry_pending"]) == ["VU-5", "VU-5"]
    assert sorted(by_status["suspended"]) == ["VU-1", "VU-1", "VU-2", "VU-3"]
    assert sorted(by_status["retired"]) == ["VU-4", "VU-4", "VU-4"]


def test_a_retired_row_stops_blocking_the_queue_but_a_suspended_one_does_not():
    """Exempting retired rows must not read as having repaired their reference."""
    from evals.synthetic.build_video_tasks import check_reference_provenance

    rows = [{"clip_id": "VU-4.RP-022-slow", "status": "retired",
             "reference_provenance": "pass_a_rejected"},
            {"clip_id": "VU-1.RP-003", "status": "suspended",
             "reference_provenance": "pass_a_rejected"},
            {"clip_id": "VU-5.RP-019-push", "status": "retry_pending",
             "reference_provenance": "pass_a_accepted"}]
    assert check_reference_provenance(rows) == [("VU-1.RP-003", "pass_a_rejected")]


def test_the_provenance_gate_sees_the_carried_status_not_the_fresh_one(tmp_path,
                                                                      monkeypatch):
    """The exemption turns on the previous status; a built row is always pending.

    Checking before the carry-forward would gate every retired row forever and
    leave the queue permanently unbuildable.
    """
    import evals.synthetic.build_video_tasks as build

    fresh = {name: "" for name in FIELDNAMES} | {
        "task_id": "VU-4.RP-022-slow.gemini-omni-video",
        "clip_id": "VU-4.RP-022-slow", "use_case_id": "VU-4", "prompt_sha256": "p",
        "reference_provenance": "pass_a_rejected", "status": "pending"}
    monkeypatch.setattr(build, "build_rows", lambda _dir: [dict(fresh)])
    dataset = tmp_path / "ds"
    (dataset / "video").mkdir(parents=True)
    task_path = dataset / "video" / "tasks.csv"

    # No prior ledger: nothing has retired this row, so the gate still bites.
    with pytest.raises(SystemExit, match="pass_a_rejected"):
        build.write_tasks(dataset)

    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(dict(fresh, status="retired"))
    assert build.write_tasks(dataset)[0]["status"] == "retired"
