"""compare (M4): lexical alignment, mutation-class outcomes, rubric contract.

Fixtures here are purpose-built synthetic inventories (committable — no
own-property data). The synthetic check-out comes from the committed, seeded
generator benchmarks/make_synthetic_checkout.py so every mutation class has a
ground-truth manifest to assert against individually.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

from homeinventory.cli import main as cli_main
from homeinventory.compare import (CLASSIFICATION_CLASSES, OfflineRubric,
                                   OpenAIRubric, align_items, change_prompt,
                                   compare_inventories, diff_pair,
                                   match_score, needs_classification)
from homeinventory.schema import Inventory, Item, Photo, Room

ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "make_synthetic_checkout",
        ROOT / "benchmarks" / "make_synthetic_checkout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _item(id, name, condition="good", defects=(), photo_ids=("P001",), **kw):
    return Item(id=id, name=name, condition=condition,
                defects=list(defects), photo_ids=list(photo_ids), **kw)


def _fixture_inventory() -> Inventory:
    """Purpose-built synthetic check-in: 3 rooms, 14 unique-named items."""
    inv = Inventory(property_address="1 Synthetic Street, Testville")
    inv.rooms = [
        Room(name="Kitchen", items=[
            _item("KIT-001", "Walls", "good"),
            _item("KIT-002", "Oak-effect laminate flooring", "good",
                  defects=["scratch to centre"]),
            _item("KIT-003", "Oven", "excellent"),
            _item("KIT-004", "Fridge freezer", "good"),
            _item("KIT-005", "Window", "good"),
        ], photos=[Photo(id="P001", path="k1.jpg", room="Kitchen")]),
        Room(name="Living Room", items=[
            _item("LIV-001", "Three-seat sofa", "good", photo_ids=["P002"]),
            _item("LIV-002", "Ceiling", "excellent", photo_ids=["P002"]),
            _item("LIV-003", "Television stand", "good", photo_ids=["P002"]),
            _item("LIV-004", "Curtains", "good", photo_ids=["P002"]),
            _item("LIV-005", "Radiator", "good", photo_ids=["P002"]),
        ], photos=[Photo(id="P002", path="l1.jpg", room="Living Room")]),
        Room(name="Bathroom", items=[
            _item("BAT-001", "Toilet", "good", photo_ids=["P003"]),
            _item("BAT-002", "Wash basin", "good", photo_ids=["P003"]),
            _item("BAT-003", "Shaver mirror", "excellent", photo_ids=["P003"]),
            _item("BAT-004", "Extractor fan", "good", photo_ids=["P003"]),
        ], photos=[Photo(id="P003", path="b1.jpg", room="Bathroom")]),
    ]
    return inv


# --------------------------------------------------------------------------
# match_score / align_items — head-noun reuse from merge.py
# --------------------------------------------------------------------------

def test_match_score_exact_and_descriptor_rename():
    assert match_score("Walls", "walls") == 4
    assert match_score("Walls", "Walls (Cream Emulsion)") == 3
    assert match_score("Sofa", "Fabric upholstered sofa") == 3
    assert match_score("Door", "Door handle and lockset") == 2  # containment
    assert match_score("Sofa", "Radiator") == 0


def test_align_unmutated_is_100_percent():
    inv = _fixture_inventory()
    for room in inv.rooms:
        pairs, removed, added = align_items(room.items, room.items)
        assert len(pairs) == len(room.items)
        assert removed == [] and added == []
        # identity alignment: every item pairs with itself at top score
        assert all(a.id == b.id and s == 4 for a, b, s in pairs)


def test_align_nothing_silently_dropped():
    ci = [_item("A-001", "Walls"), _item("A-002", "Window"),
          _item("A-003", "Radiator")]
    co = [_item("B-001", "Walls painted white"), _item("B-002", "Doormat")]
    pairs, removed, added = align_items(ci, co)
    accounted_ci = {p[0].id for p in pairs} | {i.id for i in removed}
    accounted_co = {p[1].id for p in pairs} | {i.id for i in added}
    assert accounted_ci == {"A-001", "A-002", "A-003"}
    assert accounted_co == {"B-001", "B-002"}


def test_diff_pair_grade_delta_and_new_defects():
    ci = _item("K-001", "Oven", "excellent", defects=["grease to hob"])
    co = _item("K-501", "Oven", "fair",
               defects=["grease to hob", "burn mark to door glass"])
    change = diff_pair(ci, co)
    assert change["grade_delta"] == 2            # excellent -> fair, worse
    assert change["new_defects"] == ["burn mark to door glass"]
    assert change["resolved_defects"] == []
    assert needs_classification(change)


def test_needs_classification_only_on_deterioration():
    same = diff_pair(_item("A-001", "Walls"), _item("B-001", "Walls"))
    assert not needs_classification(same)
    better = diff_pair(_item("A-001", "Walls", "fair"),
                       _item("B-001", "Walls", "good"))
    assert not needs_classification(better)      # improvement: nothing to attribute
    worse = diff_pair(_item("A-001", "Walls", "good"),
                      _item("B-001", "Walls", "fair"))
    assert needs_classification(worse)


# --------------------------------------------------------------------------
# Synthetic-checkout generator: per-mutation-class outcomes
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mutated():
    gen = _load_generator()
    checkin = _fixture_inventory()
    checkout, mutations = gen.generate(checkin, seed=42, per_class=2)
    result = compare_inventories(checkin, checkout, rubric=OfflineRubric())
    return checkin, checkout, mutations, result


def _by_class(mutations, cls):
    out = [m for m in mutations if m["class"] == cls]
    assert len(out) == 2, f"generator must emit 2 {cls} mutations"
    return out


def _room(result, name):
    return next(r for r in result["rooms"] if r["name"] == name)


def test_generator_is_deterministic():
    gen = _load_generator()
    a = gen.generate(_fixture_inventory(), seed=42, per_class=2)[1]
    b = gen.generate(_fixture_inventory(), seed=42, per_class=2)[1]
    assert a == b


def test_mutation_grade_drop_detected(mutated):
    _, _, mutations, result = mutated
    for m in _by_class(mutations, "grade_drop"):
        changed = _room(result, m["room"])["changed"]
        entry = next(c for c in changed if c["checkin_id"] == m["checkin_id"])
        assert entry["checkin_condition"] == m["from"]
        assert entry["checkout_condition"] == m["to"]
        assert entry["grade_delta"] == 1
        assert entry["classification"] == "unclassified"  # offline rubric


def test_mutation_new_defect_detected(mutated):
    _, _, mutations, result = mutated
    for m in _by_class(mutations, "new_defect"):
        changed = _room(result, m["room"])["changed"]
        entry = next(c for c in changed if c["checkin_id"] == m["checkin_id"])
        assert m["defect"] in entry["new_defects"]


def test_mutation_item_removed_detected(mutated):
    _, _, mutations, result = mutated
    for m in _by_class(mutations, "item_removed"):
        removed = _room(result, m["room"])["removed"]
        assert any(i["id"] == m["checkin_id"] for i in removed)


def test_mutation_item_added_detected(mutated):
    _, _, mutations, result = mutated
    for m in _by_class(mutations, "item_added"):
        added = _room(result, m["room"])["added"]
        assert any(i["name"] == m["name"] for i in added)


def test_mutation_alias_rename_still_aligns(mutated):
    _, _, mutations, result = mutated
    for m in _by_class(mutations, "alias_rename"):
        room = _room(result, m["room"])
        # renamed item aligned (not reported removed+added) …
        assert not any(i["id"] == m["checkin_id"] for i in room["removed"])
        assert not any(i["name"] == m["to"] for i in room["added"])
        # … and matched to its check-in counterpart
        matched = [c for c in room["changed"] + room["unchanged"]
                   if c["checkin_id"] == m["checkin_id"]]
        assert len(matched) == 1


def test_nothing_silently_dropped_end_to_end(mutated):
    checkin, checkout, _, result = mutated
    t = result["totals"]
    n_ci = sum(len(r.items) for r in checkin.rooms)
    n_co = sum(len(r.items) for r in checkout.rooms)
    assert t["matched"] + t["removed"] == n_ci
    assert t["matched"] + t["added"] == n_co
    assert t["changed"] + t["unchanged"] == t["matched"]


# --------------------------------------------------------------------------
# Rubric backends: offline yields unclassified; openai contract (mocked)
# --------------------------------------------------------------------------

def test_offline_rubric_unclassified():
    verdict = OfflineRubric().classify("Item: Oven …")
    assert verdict["classification"] == "unclassified"


def test_change_prompt_not_provided_defaults():
    change = diff_pair(_item("A-001", "Walls", "good"),
                       _item("B-001", "Walls", "fair"))
    text = change_prompt(change, "Kitchen", None, None, None)
    assert "Tenancy length: not provided" in text
    assert "Occupancy: not provided" in text
    assert "Item age at check-in: not provided" in text
    provided = change_prompt(change, "Kitchen", 18, "2 adults", "fitted 2019")
    assert "Tenancy length: 18 months" in provided
    assert "Occupancy: 2 adults" in provided
    assert "Item age at check-in: fitted 2019" in provided


def test_openai_rubric_contract(monkeypatch):
    """Mocked-backend contract (pattern: tests/test_openai_backend.py)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    rubric = OpenAIRubric()
    sent = {}

    def fake_post(payload):
        sent.update(payload)
        return {
            "choices": [{"message": {"content": json.dumps({
                "classification": "fair_wear_and_tear",
                "rationale": "Light wear over an 18 month tenancy."})}}],
            "usage": {"prompt_tokens": 700, "completion_tokens": 40},
        }

    monkeypatch.setattr(rubric._api, "_post", fake_post)
    verdict = rubric.classify("Item: Walls (room: Kitchen)\nClassify this change.")

    assert verdict["classification"] == "fair_wear_and_tear"
    assert sent["model"] == "gpt-5.4-mini"       # rubric-validated default
    assert sent["response_format"]["json_schema"]["strict"] is True
    enum = sent["response_format"]["json_schema"]["schema"][
        "properties"]["classification"]["enum"]
    assert enum == CLASSIFICATION_CLASSES
    system = sent["messages"][0]
    assert system["role"] == "system"
    assert "fair_wear_and_tear" in system["content"]
    assert "betterment" in system["content"]     # cites repo-held TDS guidance
    assert sent["messages"][1]["content"].startswith("Item: Walls")
    assert rubric.usage == {"prompt_tokens": 700, "completion_tokens": 40}


def test_openai_rubric_unknown_class_becomes_unclassified(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    rubric = OpenAIRubric()
    monkeypatch.setattr(rubric._api, "_post", lambda p: {
        "choices": [{"message": {"content": json.dumps(
            {"classification": "betterment", "rationale": "?"})}}]})
    assert rubric.classify("x")["classification"] == "unclassified"


def test_classification_failure_does_not_kill_run(monkeypatch):
    class ExplodingRubric(OfflineRubric):
        def classify(self, entry_text):
            raise RuntimeError("boom")

    checkin = _fixture_inventory()
    gen = _load_generator()
    checkout, _ = gen.generate(checkin, seed=42, per_class=2)
    result = compare_inventories(checkin, checkout, rubric=ExplodingRubric())
    changed = [c for r in result["rooms"] for c in r["changed"]]
    assert changed
    assert all(c["classification"] == "unclassified" for c in changed)


# --------------------------------------------------------------------------
# CLI end-to-end (offline): artifacts render, discussion sheet carries no £
# --------------------------------------------------------------------------

def _write_report_dir(tmp_path: Path, name: str, inv: Inventory) -> Path:
    d = tmp_path / name
    (d / "photos").mkdir(parents=True)
    (d / "inventory.json").write_text(inv.to_json(), encoding="utf-8")
    for room in inv.rooms:
        for p in room.photos:
            Image.new("RGB", (64, 48), "white").save(d / "photos" / f"{p.id}.jpg")
    return d


def test_cli_compare_offline_end_to_end(tmp_path):
    checkin = _fixture_inventory()
    gen = _load_generator()
    checkout, mutations = gen.generate(checkin, seed=42, per_class=2)
    ci_dir = _write_report_dir(tmp_path, "checkin", checkin)
    co_dir = _write_report_dir(tmp_path, "checkout", checkout)
    out = tmp_path / "cmp"

    rc = cli_main(["compare", str(ci_dir), str(co_dir), "-o", str(out),
                   "--backend", "offline", "--no-pdf",
                   "--tenancy-months", "12"])
    assert rc == 0
    assert (out / "compare.json").is_file()
    html = (out / "compare.html").read_text(encoding="utf-8")

    # grade-delta summary table + paired evidence + overlays markup present
    assert "Grade-delta summary" in html
    assert "Paired photo evidence" in html
    # discussion sheet: no £ amounts anywhere
    assert "£" not in html
    # evidence photos were exported per side
    assert any((out / "photos" / "checkin").glob("*.jpg"))
    assert any((out / "photos" / "checkout").glob("*.jpg"))

    result = json.loads((out / "compare.json").read_text(encoding="utf-8"))
    assert result["params"]["tenancy_months"] == 12
    assert result["totals"]["changed"] >= 4      # 2 grade drops + 2 new defects


def test_cli_compare_renders_defect_region_overlays(tmp_path):
    """Where both sides carry defect_regions, the report reuses the report
    template's .region overlay markup (docs/05 Level 2 annotation boxes)."""
    checkin = _fixture_inventory()
    region = {"defect": "scuff mark", "photo_id": "P001",
              "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    kit = checkin.rooms[0]
    kit.items[0].defect_regions = [dict(region)]

    checkout = _fixture_inventory()
    checkout.rooms[0].items[0].condition = "fair"
    checkout.rooms[0].items[0].defects = ["scuff mark low level"]
    checkout.rooms[0].items[0].defect_regions = [dict(region)]

    ci_dir = _write_report_dir(tmp_path, "checkin", checkin)
    co_dir = _write_report_dir(tmp_path, "checkout", checkout)
    out = tmp_path / "cmp"
    rc = cli_main(["compare", str(ci_dir), str(co_dir), "-o", str(out),
                   "--backend", "offline", "--no-pdf"])
    assert rc == 0
    html = (out / "compare.html").read_text(encoding="utf-8")
    assert html.count('class="region"') == 2     # one overlay per side
    assert 'data-label="scuff mark"' in html
    assert "left:10.00%" in html


def test_cli_compare_missing_input_errors(tmp_path, capsys):
    rc = cli_main(["compare", str(tmp_path / "nope"), str(tmp_path / "nope2"),
                   "-o", str(tmp_path / "out"), "--backend", "offline"])
    assert rc == 2
    assert "no inventory.json" in capsys.readouterr().err
