import csv
import hashlib
import json
from pathlib import Path

from evals.synthetic.build_review import build
from evals.synthetic.build_tasks import build_rows, write_tasks
from evals.synthetic.apply_owner_adjudications import apply
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


def test_pilot_has_twenty_five_matched_four_view_packets():
    rows = build_rows(DATASET)
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
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    source = DATASET / "scenarios/RP-001.json"
    (fixture / "scenarios" / source.name).write_text(source.read_text())
    rows = write_tasks(fixture)
    for row in rows:
        if row["provider"] != "Google":
            row["status"] = "generator_failed"
        elif row["view_id"] == "D-condition":
            row["status"] = "retry_pending"
            row["attempts"] = "1"
        else:
            row["status"] = "pass_a_accepted"
    with (fixture / "tasks.csv").open("w", newline="") as handle:
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
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    for source in (DATASET / "scenarios").glob("*.json"):
        (fixture / "scenarios" / source.name).write_text(source.read_text())
    first = write_tasks(fixture)
    with (fixture / "tasks.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["status"] = "review_pending"
    with (fixture / "tasks.csv").open("w", newline="") as handle:
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
        ))
        for warning in warnings
    )
    strict_errors, _ = validate(DATASET, require_complete=True)
    assert len([e for e in strict_errors if "not accepted" in e]) == len(
        incomplete
    )
    output = tmp_path / "contact-sheet.html"
    build(DATASET, output)
    page = output.read_text()
    assert "<strong>Status:</strong>" in page
    assert page.count("<article ") == 200
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
        assert json.loads(path.read_text())["$schema"].endswith("2020-12/schema")


def test_review_templates_include_structured_negative_controls(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    for source in (DATASET / "scenarios").glob("*.json"):
        (fixture / "scenarios" / source.name).write_text(source.read_text())
    write_tasks(fixture)
    review = json.loads(next((fixture / "reviews").glob("*.json")).read_text())
    assert review["pass_b"]["negative_controls"] == []


def test_verified_pass_b_reviews_keep_rejected_frames_out_of_gold():
    reviews = [
        json.loads(path.read_text())
        for path in sorted((DATASET / "reviews").glob("RP-*.json"))
        if json.loads(path.read_text()).get("review_status")
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
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    for source in (DATASET / "scenarios").glob("*.json"):
        (fixture / "scenarios" / source.name).write_text(source.read_text())
    rows = write_tasks(fixture)
    output = fixture / rows[0]["output_path"]
    output.parent.mkdir(parents=True)
    output.write_bytes(b"generated image bytes")
    assert record(fixture, "test operator", "1.1.2") == 1
    with (fixture / "tasks.csv").open(newline="") as handle:
        saved = next(csv.DictReader(handle))
    assert saved["status"] == "review_pending"
    assert saved["operator"] == "test operator"
    assert saved["generator_cli_version"] == "1.1.2"
    assert len(saved["output_sha256"]) == 64
    rejected = reject(fixture, saved["task_id"], ["malformed fixture"])
    assert rejected.is_file()
    assert not output.exists()
    assert json.loads((fixture / "rejected/manifest.jsonl").read_text())["reasons"] == ["malformed fixture"]


def test_record_outputs_replaces_rejection_operator_on_retry(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    source = DATASET / "scenarios/RP-001.json"
    (fixture / "scenarios" / source.name).write_text(source.read_text())
    rows = write_tasks(fixture)
    row = rows[0]
    row["status"] = "retry_pending"
    row["attempts"] = "1"
    row["operator"] = "rejection reviewer"
    output = fixture / row["output_path"]
    output.parent.mkdir(parents=True)
    output.write_bytes(b"second attempt")
    with (fixture / "tasks.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    record(fixture, "generation operator", "retry tool", provider=row["provider"])
    with (fixture / "tasks.csv").open(newline="") as handle:
        saved = next(csv.DictReader(handle))
    assert saved["operator"] == "generation operator"
    assert saved["attempts"] == "2"


def test_imagegen_retry_ledger_pins_prompt_output_and_reference_hashes(tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "scenarios").mkdir(parents=True)
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    source = DATASET / "scenarios/RP-001.json"
    (fixture / "scenarios" / source.name).write_text(source.read_text())
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
    with (fixture / "tasks.csv").open("w", newline="") as handle:
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
    (fixture / "dataset.json").write_text((DATASET / "dataset.json").read_text())
    source = DATASET / "scenarios/RP-001.json"
    (fixture / "scenarios" / source.name).write_text(source.read_text())
    rows = write_tasks(fixture)
    google = [row for row in rows if row["provider"] == "Google"]
    for row in google[:2]:
        output = fixture / row["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"image:{row['task_id']}".encode())
        row["status"] = "review_pending"
        row["attempts"] = "1"
        row["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    with (fixture / "tasks.csv").open("w", newline="") as handle:
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
    }))
    adjudication_path = fixture / "owner.json"
    adjudication_path.write_text(json.dumps({"decisions": [{
        "task_id": google[1]["task_id"],
        "owner_decision": "accept",
        "owner_reason": "required blind absent",
    }]}))
    correction_path = fixture / "corrections.json"
    correction_path.write_text(json.dumps({"corrections": [{
        "task_id": google[1]["task_id"],
        "replaces_decision": "accept",
        "final_decision": "reject",
        "reason": "required anchor absent",
    }]}))

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
    with (fixture / "tasks.csv").open(newline="") as handle:
        saved = {row["task_id"]: row for row in csv.DictReader(handle)}
    assert saved[google[0]["task_id"]]["status"] == "pass_a_accepted"
    assert saved[google[1]["task_id"]]["status"] == "retry_pending"
    assert not (fixture / google[1]["output_path"]).exists()
    packet_review = json.loads(
        (fixture / "reviews/RP-001.antigravity-builtin.json").read_text()
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


def test_phase1_scorer_traces_items_defects_and_evidence_links():
    review = json.loads(
        (DATASET / "reviews/RP-001.gpt-image-2.json").read_text()
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
        (DATASET / "reviews/RP-001.gpt-image-2.json").read_text()
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
