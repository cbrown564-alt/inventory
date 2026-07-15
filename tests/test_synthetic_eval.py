import csv
import json
from pathlib import Path

from evals.synthetic.build_review import build
from evals.synthetic.build_tasks import build_rows, write_tasks
from evals.synthetic.record_outputs import record
from evals.synthetic.reject_output import reject
from evals.synthetic.validate_dataset import validate


DATASET = Path(__file__).resolve().parents[1] / "evals/fixtures/synthetic-room-eval"


def test_representative_slice_has_two_matched_four_view_packets():
    rows = build_rows(DATASET)
    assert len(rows) == 16
    assert {row["scenario_id"] for row in rows} == {"RP-001", "RP-002"}
    for scenario in {row["scenario_id"] for row in rows}:
        subset = [row for row in rows if row["scenario_id"] == scenario]
        assert len(subset) == 8
        assert {row["provider"] for row in subset} == {"Google", "OpenAI"}
        assert {row["product"] for row in subset} == {
            "Antigravity CLI generate_image",
            "Codex built-in image generation",
        }
        assert {row["view_id"] for row in subset} == {"A-wide", "B-reverse", "C-inventory", "D-condition"}


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


def test_fixture_validates_accepted_images_and_reports_terminal_failures(tmp_path):
    errors, warnings = validate(DATASET)
    assert errors == []
    assert len([w for w in warnings if w.startswith("RP-")]) == 2
    assert all("generator_failed" in warning for warning in warnings)
    strict_errors, _ = validate(DATASET, require_complete=True)
    assert len([e for e in strict_errors if "not accepted" in e]) == 2
    output = tmp_path / "contact-sheet.html"
    build(DATASET, output)
    page = output.read_text()
    assert "<strong>Status:</strong>" in page
    assert page.count("<article>") == 16
    assert "Intended prompts are not gold" in page


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


def test_primary_pass_b_reviews_are_complete_and_keep_rejected_frames_out_of_gold():
    reviews = [json.loads(path.read_text()) for path in sorted((DATASET / "reviews").glob("RP-*.json"))]
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
