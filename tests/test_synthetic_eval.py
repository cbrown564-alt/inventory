import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import pytest

pytestmark = pytest.mark.eval

import evals.synthetic.review_pass_a as retry_pass_a
import evals.synthetic.review_pass_b as pass_b
from evals.synthetic.build_review import build
from evals.synthetic.build_pass_a_gallery import build as build_pass_a_gallery
from evals.synthetic.build_tasks import build_rows, write_tasks
from evals.synthetic.apply_owner_adjudications import apply
from evals.synthetic.apply_pass_b import apply as apply_pass_b
from evals.synthetic.apply_retry_pass_a import apply as apply_retry_pass_a
from evals.synthetic.audit_google_provenance import audit
from evals.synthetic.generate_antigravity import _load_packets, _packet_prompt
from evals.synthetic.record_outputs import record
from evals.synthetic.record_imagegen_retries import build_ledger
from evals.synthetic.reject_output import reject
from evals.synthetic.run_eval import build_run_plan
from evals.synthetic.review_pass_b import _checks, _ordinary_sample
from evals.synthetic.prompts import PROMPTS, prompt_sha256
from evals.synthetic.score import score_run
from evals.synthetic.validate_dataset import validate
from homeinventory.usecases.tenancy import SYSTEM_PROMPT


DATASET = Path(__file__).resolve().parents[1] / "evals/fixtures/synthetic-room-eval"


def _matched(rows):
    """Rows belonging to the matched two-provider design.

    The Gemini Omni slice shares the provider *name* "Google" with the
    Antigravity arm, so it has to be excluded by provider key.
    """
    return [row for row in rows
            if row["task_id"].split(".")[1] != "gemini-omni"]


def test_pilot_has_twenty_five_matched_four_view_packets():
    rows = _matched(build_rows(DATASET))
    assert len(rows) == 200
    assert len({row["scenario_id"] for row in rows}) == 25
    for scenario in {row["scenario_id"] for row in rows}:
        subset = [row for row in rows if row["scenario_id"] == scenario]
        assert len(subset) == 8
        assert {row["provider"] for row in subset} == {"Google", "OpenAI"}
        assert {row["product"] for row in subset} == {
            "Antigravity CLI generate_image",
            "Codex built-in image generation",
        }
        assert {row["view_id"] for row in subset} == {"A-wide", "B-reverse", "C-inventory", "D-condition"}


def test_the_bias_check_slice_is_present_but_outside_the_matched_design():
    """The Omni slice is imported, and is not counted as matched-design work.

    docs/31 Amendment B B9: opportunistic, unbalanced, no completeness
    obligation. Views with no candidate are terminal rather than queued,
    because Google generation is retired and they will never be filled.
    """
    rows = [row for row in build_rows(DATASET)
            if row["task_id"].split(".")[1] == "gemini-omni"]
    assert len(rows) == 100
    assert {row["provenance"] for row in rows} == {
        "candidate_only_prompt_not_recorded"
    }
    assert {row["provenance"] for row in _matched(build_rows(DATASET))} == {
        "recorded"
    }
    with (DATASET / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        ledger = [row for row in csv.DictReader(handle)
                  if row["task_id"].split(".")[1] == "gemini-omni"]
    statuses = Counter(row["status"] for row in ledger)
    assert statuses["not_generated"] == 43
    assert sum(statuses.values()) - statuses["not_generated"] == 57
    # A row has an image exactly when it is not not_generated, and only a row
    # with an image may carry a digest.
    for row in ledger:
        exists = (DATASET / row["output_path"]).is_file()
        assert exists == (row["status"] != "not_generated"), row["task_id"]
        assert bool(row["output_sha256"]) == exists


def _omni_ledger(tmp_path, sha="abc"):
    dataset = tmp_path / "ds"
    dataset.mkdir()
    row = {name: "" for name in build_tasks_fieldnames()}
    row.update({"task_id": "RP-003.gemini-omni.A-wide", "scenario_id": "RP-003",
                "view_id": "A-wide", "status": "review_pending",
                "output_sha256": sha,
                "provenance": "candidate_only_prompt_not_recorded"})
    with (dataset / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_tasks_fieldnames())
        writer.writeheader()
        writer.writerow(row)
    return dataset


def build_tasks_fieldnames():
    from evals.synthetic.build_tasks import FIELDNAMES

    return FIELDNAMES


def _omni_review(tmp_path, decision="accept", sha="abc", **overrides):
    payload = {
        "status": "complete",
        "frames": [{"task_id": "RP-003.gemini-omni.A-wide",
                    "image_sha256": sha, "pass_a_decision": decision}],
    }
    payload.update(overrides)
    path = tmp_path / "omni-review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_rejected_omni_candidate_is_excluded_not_failed(tmp_path):
    """A rejected candidate is not a generation that failed twice.

    apply_retry_pass_a writes terminal generator_failed and archives the file,
    which is right for a retry and wrong here: Google generation is retired, so
    there is no attempt to fail. The candidate is excluded and its file stays
    where the staging reports say it is.
    """
    from evals.synthetic.apply_gemini_omni_pass_a import apply as apply_omni

    dataset = _omni_ledger(tmp_path)
    result = apply_omni(dataset, _omni_review(tmp_path, "reject"))
    assert result["counts"] == {"pass_a_rejected": 1}
    with (dataset / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        assert next(iter(csv.DictReader(handle)))["status"] == "pass_a_rejected"
    assert not (dataset / "rejected").exists()


def test_omni_escalations_go_to_the_owner_and_partials_cannot_apply(tmp_path):
    from evals.synthetic.apply_gemini_omni_pass_a import apply as apply_omni

    dataset = _omni_ledger(tmp_path)
    apply_omni(dataset, _omni_review(tmp_path, "escalate"))
    with (dataset / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        assert next(iter(csv.DictReader(handle)))["status"] == "owner_review_pending"
    with pytest.raises(ValueError, match="partial review"):
        apply_omni(dataset, _omni_review(tmp_path, status="partial"))


def test_owner_adjudication_resolves_only_escalated_omni_rows(tmp_path):
    """An adjudication may settle an escalation, not overturn an agreement.

    The gallery exports whatever the owner clicked; reaching a row both
    reviewers agreed on would overturn a decision this path never saw the
    evidence for.
    """
    from evals.synthetic.apply_gemini_omni_pass_a import apply_adjudications

    dataset = _omni_ledger(tmp_path)
    with (dataset / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["status"] = "owner_review_pending"
    with (dataset / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_tasks_fieldnames())
        writer.writeheader()
        writer.writerows(rows)

    export = tmp_path / "owner-adjudications.json"
    export.write_text(json.dumps({"decisions": [
        {"task_id": "RP-003.gemini-omni.A-wide", "owner_decision": "accept"}
    ]}), encoding="utf-8")
    result = apply_adjudications(dataset, export)
    assert result["counts"] == {"pass_a_accepted": 1}
    assert result["still_escalated"] == 0

    # The row is settled now, so the same export must not re-apply.
    with pytest.raises(ValueError, match="only an escalated row"):
        apply_adjudications(dataset, export)


def test_omni_apply_refuses_when_the_image_changed_after_review(tmp_path):
    from evals.synthetic.apply_gemini_omni_pass_a import apply as apply_omni

    dataset = _omni_ledger(tmp_path, sha="the-image-in-the-ledger")
    with pytest.raises(ValueError, match="changed after it was reviewed"):
        apply_omni(dataset, _omni_review(tmp_path, sha="a-different-image"))


def test_the_omni_slice_has_been_through_pass_a():
    """The import's whole point: these rows now hold a recorded decision.

    Before 4 Aug 2026 all 57 had owner review and no Pass A, which is why the
    view mix-up was invisible. Escalations stay owner_review_pending — that is
    a decision the owner still owes, not a decision already taken.
    """
    review = json.loads(
        (DATASET / "reports" / "gemini-omni-pass-a-review-2026-08-04.json")
        .read_text(encoding="utf-8")
    )
    assert review["status"] == "complete"
    assert len(review["frames"]) == 57
    assert review["reviewer_model_mode"] == "claude-sonnet-4-6"
    assert review["reviewer_second_model_mode"] == "gemini-3.5-flash-low"

    with (DATASET / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        ledger = [row for row in csv.DictReader(handle)
                  if row["task_id"].split(".")[1] == "gemini-omni"]
    statuses = Counter(row["status"] for row in ledger)
    # 14 accepted by the reviewers, plus the three reference frames the owner
    # adjudicated on 4 Aug. The other 25 escalations stay open on purpose:
    # this arm cannot carry a conclusion alone, so resolving them buys nothing.
    assert statuses["pass_a_accepted"] == 17
    assert statuses["pass_a_rejected"] == 15
    assert statuses["owner_review_pending"] == 25
    assert statuses["not_generated"] == 43
    assert "review_pending" not in statuses


def test_no_video_clip_may_rest_on_an_unaccepted_reference_frame():
    """The rule the probe now enforces, stated as a check over real state.

    RP-022's A-wide was rejected by both reviewers — the scenario requires a
    corner basin and the candidate has a flat wall-hung one — so VU-4 has no
    reference frame at all, and that is a fact about the fixture no
    regeneration can change.
    """
    with (DATASET / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        status = {row["output_path"]: row["status"]
                  for row in csv.DictReader(handle)}
    with (DATASET / "video" / "tasks.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        clips = list(csv.DictReader(handle))
    usable = {clip["clip_id"]: status.get(clip["reference_path"])
              for clip in clips}
    cleared = [clip_id for clip_id, s in usable.items() if s == "pass_a_accepted"]
    assert len(cleared) == 6
    assert usable["VU-1.RP-003"] == "pass_a_accepted"
    assert usable["VU-5.RP-019-push"] == "pass_a_accepted"
    assert usable["VU-5.RP-019-hold"] == "pass_a_accepted"
    # RP-022's reference failed review outright, so VU-4 has nothing to sit on.
    assert usable["VU-4.RP-022-slow"] == "pass_a_rejected"
    assert [clip["reference_provenance"] for clip in clips
            if clip["clip_id"] == "VU-4.RP-022-slow"] == ["pass_a_rejected"]
    # Nothing may be sitting on a rejected reference in a generated state.
    for clip in clips:
        if status.get(clip["reference_path"]) == "pass_a_rejected":
            assert not clip["output_sha256"], clip["clip_id"]


def test_pass_a_review_selects_only_unreviewed_rows_in_an_arm(tmp_path):
    """The unfiltered default is one run's retry cohort, not a general queue.

    Selecting the Omni arm with it would have silently reviewed nothing. The
    provider selector takes review_pending rows only, so a completed arm
    presents an empty queue rather than re-reviewing itself.
    """
    from evals.synthetic.review_pass_a import _review_inputs

    assert _review_inputs(DATASET, None, "gemini-omni") == []
    assert _review_inputs(DATASET, None, "gpt-image-2") == []

    dataset = _omni_ledger(tmp_path)
    (dataset / "images/google/gemini-omni").mkdir(parents=True)
    (dataset / "images/google/gemini-omni/RP-003-A-wide.jpeg").write_bytes(b"x")
    with (dataset / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["output_path"] = "images/google/gemini-omni/RP-003-A-wide.jpeg"
    with (dataset / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_tasks_fieldnames())
        writer.writeheader()
        writer.writerows(rows)
    assert len(_review_inputs(dataset, None, "gemini-omni")) == 1


def test_effort_is_only_sent_to_models_that_accept_it():
    """The CLI errors outright when a thinking model is given --effort."""
    import inspect

    from evals.synthetic import review_pass_a

    source = inspect.getsource(review_pass_a._invoke)
    assert 'model.startswith("gemini-")' in source
    assert '"--effort"' in source


def test_antigravity_resume_skips_terminal_packets_and_preserves_partial_files():
    assert _load_packets(DATASET, {"RP-003"}) == {}
    packet = _load_packets(DATASET, {"RP-016"})["RP-016"]
    missing = [row for row in packet if row["view_id"] in {
        "C-inventory",
        "D-condition",
    }]
    prompt = _packet_prompt(
        "RP-016",
        missing,
        DATASET,
        [{"task_id": packet[0]["task_id"], "path": "existing.jpg", "sha256": "abc"}],
    )
    assert "already exist and are immutable" in prompt
    assert "Generate only the tasks listed below" in prompt
    assert "RP-016.antigravity-builtin.C-inventory" in prompt
    assert "RP-016.antigravity-builtin.A-wide" in prompt


def test_antigravity_retry_loads_full_packet_with_one_actionable_view(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    source = DATASET / "scenarios/RP-001.json"
    shutil.copyfile(source, fixture / "scenarios" / source.name)
    rows = write_tasks(fixture)
    for row in rows:
        if row["provider"] != "Google":
            row["status"] = "generator_failed"
        elif row["view_id"] == "D-condition":
            row["status"] = "retry_pending"
            row["attempts"] = "1"
        else:
            row["status"] = "pass_a_accepted"
    with (fixture / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    packet = _load_packets(fixture, {"RP-001"})["RP-001"]
    assert len(packet) == 4
    assert [row["view_id"] for row in packet if row["status"] == "retry_pending"] == [
        "D-condition"
    ]


def test_prompts_are_deterministic_and_task_progress_is_preserved(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    for source in (DATASET / "scenarios").glob("*.json"):
        shutil.copyfile(source, fixture / "scenarios" / source.name)
    first = write_tasks(fixture)
    with (fixture / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["status"] = "review_pending"
    with (fixture / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader(); writer.writerows(rows)
    second = write_tasks(fixture)
    assert first[0]["prompt_sha256"] == second[0]["prompt_sha256"]
    assert second[0]["status"] == "review_pending"


def test_fixture_validates_accepted_images_and_reports_pending_tasks(tmp_path):
    errors, warnings = validate(DATASET)
    assert errors == []
    with (DATASET / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    incomplete = [
        row for row in rows
        if row["status"] not in {"accepted", "pass_a_accepted"}
    ]
    assert len([w for w in warnings if w.startswith("RP-")]) == len(incomplete)
    assert all(
        any(status in warning for status in (
            "pending",
            "review_pending",
            "retry_pending",
            "generator_failed",
            "not_generated",
            # A screened-out candidate is a resolved state, not an open task.
            "pass_a_rejected",
            "owner_review_pending",
        ))
        for warning in warnings
    )
    strict_errors, _ = validate(DATASET, require_complete=True)
    assert len([e for e in strict_errors if "not accepted" in e]) == len(
        incomplete
    )
    output = tmp_path / "contact-sheet.html"
    build(DATASET, output)
    page = output.read_text(encoding="utf-8")
    assert "<strong>Status:</strong>" in page
    # 200 matched-design tasks plus the 100-row Gemini Omni bias-check slice.
    assert page.count("<article ") == 300
    assert "Requested content is not gold" in page
    for filter_name in (
        "development",
        "validation",
        "sealed",
        "review_pending",
        "pending",
        "generator_failed",
    ):
        assert f'data-filter="{filter_name}"' in page
    assert "c.dataset.split===f||c.dataset.status===f" in page


def test_schema_files_are_valid_json():
    for path in (DATASET / "schemas").glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))["$schema"]
        assert schema.endswith("2020-12/schema")


def test_review_templates_include_structured_negative_controls(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    for source in (DATASET / "scenarios").glob("*.json"):
        shutil.copyfile(source, fixture / "scenarios" / source.name)
    write_tasks(fixture)
    review = json.loads(
        next((fixture / "reviews").glob("*.json")).read_text(encoding="utf-8"))
    assert review["pass_b"]["negative_controls"] == []


def test_verified_pass_b_reviews_keep_rejected_frames_out_of_gold():
    reviews = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((DATASET / "reviews").glob("RP-*.json"))
        if json.loads(path.read_text(encoding="utf-8")).get("review_status")
        == "verified_synthetic_gold"
    ]
    assert len(reviews) == 4
    defects = []
    for review in reviews:
        pass_b = review["pass_b"]
        assert pass_b["reviewer"]
        assert pass_b["completed_at"]
        assert pass_b["claims"]
        assert pass_b["negative_controls"]
        rejected = {
            frame["frame_id"] for frame in review["pass_a"]["frames"]
            if frame["decision"] == "rejected"
        }
        for claim in pass_b["claims"]:
            assert rejected.isdisjoint(claim["evidence_frame_ids"])
            defects.extend(claim["defects"])
        for negative in pass_b["negative_controls"]:
            assert rejected.isdisjoint(negative["evidence_frame_ids"])
            assert negative["second_review"]["required"] is True
        ordinary = [claim for claim in pass_b["claims"] if not claim["defects"]]
        selected = [claim for claim in ordinary if claim["second_review"]["required"]]
        assert len(selected) * 4 >= len(ordinary)
    assert len(defects) == 3
    assert {(defect["wording"], defect["severity"]) for defect in defects} == {
        ("Small chip", "minor"),
        ("Short shallow scuff", "minor"),
    }


def test_record_outputs_pins_hash_and_generation_provenance(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    for source in (DATASET / "scenarios").glob("*.json"):
        shutil.copyfile(source, fixture / "scenarios" / source.name)
    rows = write_tasks(fixture)
    output = fixture / rows[0]["output_path"]
    output.parent.mkdir(parents=True)
    output.write_bytes(b"generated image bytes")
    assert record(fixture, "test operator", "1.1.2") == 1
    with (fixture / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        saved = next(csv.DictReader(handle))
    assert saved["status"] == "review_pending"
    assert saved["operator"] == "test operator"
    assert saved["generator_cli_version"] == "1.1.2"
    assert len(saved["output_sha256"]) == 64
    rejected = reject(fixture, saved["task_id"], ["malformed fixture"])
    assert rejected.is_file()
    assert not output.exists()
    manifest = json.loads(
        (fixture / "rejected/manifest.jsonl").read_text(encoding="utf-8"))
    assert manifest["reasons"] == ["malformed fixture"]


def test_record_outputs_replaces_rejection_operator_on_retry(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    source = DATASET / "scenarios/RP-001.json"
    shutil.copyfile(source, fixture / "scenarios" / source.name)
    rows = write_tasks(fixture)
    row = rows[0]
    row["status"] = "retry_pending"
    row["attempts"] = "1"
    row["operator"] = "rejection reviewer"
    output = fixture / row["output_path"]
    output.parent.mkdir(parents=True)
    output.write_bytes(b"second attempt")
    with (fixture / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    record(fixture, "generation operator", "retry tool", provider=row["provider"])
    with (fixture / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        saved = next(csv.DictReader(handle))
    assert saved["operator"] == "generation operator"
    assert saved["attempts"] == "2"


def test_imagegen_retry_ledger_pins_prompt_output_and_reference_hashes(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    source = DATASET / "scenarios/RP-001.json"
    shutil.copyfile(source, fixture / "scenarios" / source.name)
    rows = write_tasks(fixture)
    openai = [row for row in rows if row["provider"] == "OpenAI"]
    for row in openai:
        output = fixture / row["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"image:{row['task_id']}".encode())
        row["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        row["generated_at"] = "2026-07-30T00:00:00+00:00"
    retry = next(row for row in openai if row["view_id"] == "C-inventory")
    retry["attempts"] = "2"
    retry["operator"] = "Codex GPT Image 2 built-in imagegen"
    with (fixture / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    ledger = build_ledger(fixture)
    assert ledger["retry_count"] == 1
    entry = ledger["retries"][0]
    assert entry["prompt_sha256"] == retry["prompt_sha256"]
    assert len(entry["output_sha256"]) == 64
    assert entry["reference_image"]["task_id"].endswith(".A-wide")
    assert len(entry["reference_image"]["sha256"]) == 64


def test_pass_b_second_check_covers_all_risk_labels_and_stratified_sample():
    claims = [
        {
            "canonical_name": f"clear item {index}",
            "aliases": [],
            "evidence_frame_ids": ["A-wide"],
            "visibility": "clear",
            "condition": None,
            "defects": [],
        }
        for index in range(8)
    ]
    claims += [
        {
            "canonical_name": f"partial item {index}",
            "aliases": [],
            "evidence_frame_ids": ["B-reverse"],
            "visibility": "partial",
            "condition": None,
            "defects": [],
        }
        for index in range(4)
    ]
    claims.append(
        {
            "canonical_name": "defective door",
            "aliases": [],
            "evidence_frame_ids": ["D-condition"],
            "visibility": "clear",
            "condition": "Small visible chip.",
            "defects": [
                {
                    "wording": "Small chip",
                    "location": "lower edge",
                    "severity": "minor",
                }
            ],
        }
    )
    selected = _ordinary_sample("RP-999.test", claims)
    assert len([index for index in selected if index < 8]) >= 2
    assert len([index for index in selected if 8 <= index < 12]) >= 1
    packet = {
        "packet_id": "RP-999.test",
        "claims": claims,
        "negative_controls": [
            {
                "wording": "Shadow is not damp.",
                "evidence_frame_ids": ["B-reverse"],
                "assessment": "supported",
            }
        ],
    }
    checks = _checks(packet)
    assert any(check["kind"] == "defect" for check in checks)
    assert sum(check["kind"] == "negative" for check in checks) == 1
    assert sum(check["kind"] == "ordinary" for check in checks) >= 3


def test_google_provenance_audit_does_not_equate_integrity_with_origin():
    report = audit(DATASET, {"RP-009", "RP-012", "RP-018"})
    packets = {packet["packet_id"]: packet for packet in report["packets"]}
    assert packets["RP-009.antigravity-builtin"]["integrity_verified"] is True
    assert packets["RP-009.antigravity-builtin"][
        "generation_provenance_status"
    ] == "insufficient"
    assert packets["RP-012.antigravity-builtin"]["pass_b_eligible"] is False
    assert packets["RP-018.antigravity-builtin"][
        "generation_provenance_status"
    ] == "integrity_only"


def test_complete_pass_a_import_applies_ai_accept_and_protocol_correction(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    shutil.copyfile(DATASET / "dataset.json", fixture / "dataset.json")
    source = DATASET / "scenarios/RP-001.json"
    shutil.copyfile(source, fixture / "scenarios" / source.name)
    rows = write_tasks(fixture)
    google = [row for row in rows if row["provider"] == "Google"]
    for row in google[:2]:
        output = fixture / row["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"image:{row['task_id']}".encode())
        row["status"] = "review_pending"
        row["attempts"] = "1"
        row["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    with (fixture / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    review_path = fixture / "source-review.json"
    review_path.write_text(json.dumps({
        "reviewed_at": "2026-07-30",
        "frames": [
            {
                "task_id": google[0]["task_id"],
                "scenario_id": "RP-001",
                "provider": "Google",
                "view_id": google[0]["view_id"],
                "path": google[0]["output_path"],
                "pass_a_decision": "accept",
                "pass_a_reason": "clear",
                "second_review_agreed": True,
            },
            {
                "task_id": google[1]["task_id"],
                "scenario_id": "RP-001",
                "provider": "Google",
                "view_id": google[1]["view_id"],
                "path": google[1]["output_path"],
                "pass_a_decision": "reject",
                "pass_a_reason": "required blind absent",
                "second_review_agreed": True,
            },
        ],
    }), encoding="utf-8")
    adjudication_path = fixture / "owner.json"
    adjudication_path.write_text(json.dumps({"decisions": [{
        "task_id": google[1]["task_id"],
        "owner_decision": "accept",
        "owner_reason": "required blind absent",
    }]}), encoding="utf-8")
    correction_path = fixture / "corrections.json"
    correction_path.write_text(json.dumps({"corrections": [{
        "task_id": google[1]["task_id"],
        "replaces_decision": "accept",
        "final_decision": "reject",
        "reason": "required anchor absent",
    }]}), encoding="utf-8")

    dry_run = apply(
        fixture, review_path, adjudication_path, correction_path, dry_run=True
    )
    assert dry_run["counts"] == {"accept": 1, "reject": 1}
    result = apply(
        fixture,
        review_path,
        adjudication_path,
        correction_path,
        prepare_retries=True,
    )
    assert len(result["retry_moves"]) == 1
    with (fixture / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        saved = {row["task_id"]: row for row in csv.DictReader(handle)}
    assert saved[google[0]["task_id"]]["status"] == "pass_a_accepted"
    assert saved[google[1]["task_id"]]["status"] == "retry_pending"
    assert not (fixture / google[1]["output_path"]).exists()
    packet_review = json.loads(
        (fixture / "reviews/RP-001.antigravity-builtin.json")
        .read_text(encoding="utf-8")
    )
    decisions = {
        frame["frame_id"]: frame["decision"]
        for frame in packet_review["pass_a"]["frames"]
    }
    assert decisions[google[0]["view_id"]] == "accepted"
    assert decisions[google[1]["view_id"]] == "rejected"
    assert packet_review["review_status"] == "provisional"
    visibility = {
        frame["frame_id"]: frame["requested_evidence"][0]["visibility"]
        for frame in packet_review["pass_a"]["frames"][:2]
    }
    assert visibility[google[0]["view_id"]] == "clear"
    assert visibility[google[1]["view_id"]] == "absent"


def test_prompt_comparison_uses_product_prompt_and_plain_model_facing_text():
    assert PROMPTS["production-v1"] == SYSTEM_PROMPT
    assert len({prompt_sha256(prompt) for prompt in PROMPTS.values()}) == 2
    candidate = PROMPTS["evidence-bounded-coverage-v1"].lower()
    for research_term in ("benchmark", "candidate", "gold", "scorer", "stop rule"):
        assert research_term not in candidate
    assert '"photo_ids"' in candidate
    assert "do not infer working order" in " ".join(candidate.split())
    assert "wood grain mould" in candidate


def test_phase1_plan_keeps_production_architecture_and_complete_packets_only():
    plan = build_run_plan(DATASET)
    assert len(plan) == 4
    assert {run["scenario_id"] for run in plan} == {"RP-001", "RP-002"}
    assert {run["prompt_id"] for run in plan} == set(PROMPTS)
    assert {run["model"] for run in plan} == {"gemini-3.5-flash-low"}
    assert all(len(run["inputs"]) == 4 for run in plan)
    assert all(run["image_model"] == "GPT Image 2" for run in plan)


def test_owner_gallery_accepts_dual_retry_review_schema(tmp_path):
    dataset = tmp_path / "fixture"
    image = dataset / "images/openai/gpt-image-2/RP-001-A-wide.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not decoded by the static builder")
    scenarios = dataset / "scenarios"
    scenarios.mkdir()
    scenarios.joinpath("RP-001.json").write_text(json.dumps({
        "id": "RP-001",
        "views": [{
            "id": "A-wide",
            "intended_visible_items": ["kitchen units", "window"],
            "intended_defects": ["small chip on a base-unit door"],
        }],
    }), encoding="utf-8")
    report = dataset / "reports/phase3-retry-pass-a-review.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "review_type": "phase3_retry_pass_a_visual_screen",
        "reviewed_at": "2026-07-30T12:00:00+00:00",
        "counts": {"accept": 0, "reject": 0, "escalate": 1},
        "frames": [{
            "task_id": "RP-001.gpt-image-2.A-wide",
            "scenario_id": "RP-001",
            "provider": "OpenAI",
            "room_type": "Kitchen",
            "view_id": "A-wide",
            "image_path": str(image),
            "frozen_generation_prompt": "Wide kitchen with a window.",
            "pass_a_decision": "escalate",
            "first_review": {"decision": "accept", "reason": "Kitchen is clear."},
            "second_review": {"decision": "reject", "reason": "Window is absent."},
        }],
    }), encoding="utf-8")
    output = dataset / "reports/retry-owner-gallery.html"

    build_pass_a_gallery(dataset, report, output)

    html = output.read_text(encoding="utf-8")
    assert "RP-001.gpt-image-2.A-wide" in html
    assert "Independent reviewers disagreed: accept vs reject" in html
    assert "kitchen units, window" in html
    assert "small chip on a base-unit door" in html
    assert "First review:" in html
    assert "Second review:" in html
    assert "activeThumb.scrollIntoView" not in html
    assert "els.filmstrip.scrollTo" in html
    assert "pass-a-owner-adjudications-v2:${data.source_file" in html


def test_owner_gallery_rejects_partial_review(tmp_path):
    report = tmp_path / "partial.json"
    report.write_text(json.dumps({
        "status": "partial",
        "frames": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="partial"):
        build_pass_a_gallery(tmp_path, report, tmp_path / "gallery.html")


def test_partial_ai_reports_cannot_be_applied(tmp_path):
    report = tmp_path / "partial.json"
    report.write_text(json.dumps({"status": "partial"}), encoding="utf-8")

    with pytest.raises(ValueError, match="partial"):
        apply_retry_pass_a(tmp_path, report)
    with pytest.raises(ValueError, match="partial"):
        apply_pass_b(tmp_path, report)


def test_retry_adjudications_must_match_the_ai_review(tmp_path):
    report = tmp_path / "retry.json"
    report.write_text(json.dumps({
        "status": "complete",
        "frames": [],
    }), encoding="utf-8")
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps({
        "source_review": "different-review.json",
        "decisions": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="different Pass A review"):
        apply_retry_pass_a(tmp_path, report, owner)


def test_retry_pass_a_checkpoints_and_resumes_completed_batches(
    tmp_path, monkeypatch
):
    dataset = tmp_path / "fixture"
    (dataset / "images").mkdir(parents=True)
    fields = [
        "task_id", "scenario_id", "provider", "room_type", "view_id",
        "status", "attempts", "output_path", "output_sha256", "exact_prompt",
    ]
    rows = []
    for number in (1, 2):
        task_id = f"RP-00{number}.gpt-image-2.A-wide"
        image = dataset / "images" / f"{task_id}.png"
        image.write_bytes(f"image-{number}".encode())
        rows.append({
            "task_id": task_id,
            "scenario_id": f"RP-00{number}",
            "provider": "OpenAI",
            "room_type": "Kitchen",
            "view_id": "A-wide",
            "status": "review_pending",
            "attempts": "2",
            "output_path": image.relative_to(dataset).as_posix(),
            "output_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "exact_prompt": "Photographic kitchen.",
        })
    with (dataset / "tasks.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    output = dataset / "reports/retry.json"
    monkeypatch.setattr(retry_pass_a, "_resolve_cli", lambda _: Path("fake"))
    monkeypatch.setattr(retry_pass_a, "_cli_version", lambda _: "fake-1")

    def interrupted(_cli, _model, prompt, _timeout, _cwd):
        if "RP-002" in prompt:
            raise RuntimeError("simulated interruption")
        decision = [{
            "task_id": "RP-001.gpt-image-2.A-wide",
            "decision": "accept",
            "reason": "clear",
            "requested_evidence": [],
        }]
        return decision, {"status": "SUCCESS"}, 1.0

    monkeypatch.setattr(retry_pass_a, "_invoke", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        retry_pass_a.review(dataset, output, batch_size=1)
    partial = json.loads(output.read_text(encoding="utf-8"))
    assert partial["status"] == "partial"
    assert len(partial["frames"]) == 1

    def successful(_cli, _model, prompt, _timeout, _cwd):
        task_id = (
            "RP-001.gpt-image-2.A-wide"
            if "RP-001" in prompt
            else "RP-002.gpt-image-2.A-wide"
        )
        decision = [{
            "task_id": task_id,
            "decision": "accept",
            "reason": "clear",
            "requested_evidence": [],
        }]
        return decision, {"status": "SUCCESS"}, 1.0

    monkeypatch.setattr(retry_pass_a, "_invoke", successful)
    completed = retry_pass_a.review(dataset, output, batch_size=1)
    assert completed["status"] == "complete"
    assert len(completed["frames"]) == 2
    assert len(completed["calls"]) == 2


def test_pass_b_checkpoints_and_resumes_completed_packets(tmp_path, monkeypatch):
    packets = [
        {
            "packet_id": packet_id,
            "scenario_id": packet_id.split(".")[0],
            "provider": "OpenAI",
            "room_type": "Kitchen",
            "images": [],
            "scene_hypotheses": {"views": [], "continuity_requirements": []},
        }
        for packet_id in ("RP-001.gpt-image-2", "RP-002.gpt-image-2")
    ]
    output = tmp_path / "pass-b.json"
    monkeypatch.setattr(pass_b, "_resolve_cli", lambda _: Path("fake"))
    monkeypatch.setattr(pass_b, "_cli_version", lambda _: "fake-1")
    monkeypatch.setattr(pass_b, "_packet_inputs", lambda *_: packets)

    def response(packet_id: str, second: bool) -> list[dict]:
        if second:
            return [{
                "packet_id": packet_id,
                "checks": [],
                "additional_material_findings": [],
                "continuity_concerns": [],
            }]
        return [{
            "packet_id": packet_id,
            "claims": [],
            "negative_controls": [],
            "generator_deviations": [],
            "ambiguity_notes": [],
            "continuity_concerns": [],
        }]

    def interrupted(_cli, _model, prompt, _timeout, _cwd):
        packet_id = (
            "RP-001.gpt-image-2"
            if "RP-001.gpt-image-2" in prompt
            else "RP-002.gpt-image-2"
        )
        if packet_id.startswith("RP-002"):
            raise RuntimeError("simulated interruption")
        second = "fresh, independent Pass B checker" in prompt
        return response(packet_id, second), {"status": "SUCCESS"}, 1.0

    monkeypatch.setattr(pass_b, "_invoke", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        pass_b.review(tmp_path, output, batch_size=1)
    partial = json.loads(output.read_text(encoding="utf-8"))
    assert partial["status"] == "partial"
    assert [item["packet_id"] for item in partial["packets"]] == [
        "RP-001.gpt-image-2"
    ]

    def successful(_cli, _model, prompt, _timeout, _cwd):
        packet_id = (
            "RP-001.gpt-image-2"
            if "RP-001.gpt-image-2" in prompt
            else "RP-002.gpt-image-2"
        )
        second = "fresh, independent Pass B checker" in prompt
        return response(packet_id, second), {"status": "SUCCESS"}, 1.0

    monkeypatch.setattr(pass_b, "_invoke", successful)
    completed = pass_b.review(tmp_path, output, batch_size=1)
    assert completed["status"] == "complete"
    assert len(completed["packets"]) == 2
    assert len(completed["calls"]) == 2


def test_phase1_scorer_traces_items_defects_and_evidence_links():
    review = json.loads(
        (DATASET / "reviews/RP-001.gpt-image-2.json").read_text(encoding="utf-8")
    )
    items = []
    for claim in review["pass_b"]["claims"]:
        items.append(
            {
                "name": claim["canonical_name"],
                "description": claim.get("condition") or "",
                "defects": [
                    f"{defect['wording']} {defect['location']}"
                    for defect in claim["defects"]
                ],
                "photo_ids": claim["evidence_frame_ids"],
            }
        )
    record = {
        "run_id": "test",
        "scenario_id": "RP-001",
        "room_type": "Kitchen",
        "prompt_id": "production-v1",
        "parsed_output": {"items": items},
        "latency_seconds": 1.0,
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        "estimated_cost": {"amount": 0.001},
    }
    scored = score_run(record, review)
    assert scored["item_recall_against_reviewed_gold"] == 100.0
    assert scored["defect_recall"] == 100.0
    assert scored["evidence_link_accuracy"] == 100.0
    assert scored["counts"]["unsupported_defects"] == 0


def test_phase1_scorer_allows_visible_defect_on_grouped_item_name():
    review = json.loads(
        (DATASET / "reviews/RP-001.gpt-image-2.json").read_text(encoding="utf-8")
    )
    record = {
        "run_id": "test-grouped-defect",
        "scenario_id": "RP-001",
        "room_type": "Kitchen",
        "prompt_id": "production-v1",
        "parsed_output": {
            "items": [
                {
                    "name": "Kitchen cabinets",
                    "description": "Laminate base and wall units.",
                    "defects": ["small chip to lower edge of corner base cupboard"],
                    "photo_ids": ["D-condition"],
                }
            ]
        },
        "latency_seconds": 1.0,
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "estimated_cost": {"amount": 0.0},
    }
    scored = score_run(record, review)
    assert scored["defect_recall"] == 100.0
    assert scored["counts"]["unsupported_defects"] == 0
