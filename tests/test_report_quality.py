"""Report rendering quality: use-case-aware HTML and stable re-renders."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from homeinventory.cli import main
from homeinventory.report import build_cover_rows, render, summary_rows
from homeinventory.schema import Inventory, Item, Photo, Room
from homeinventory.usecases import use_case_for
from homeinventory.usecases.deepclean import DEEP_CLEAN
from homeinventory.usecases.tenancy import TENANCY


def _img(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), "white").save(path)


def _tenancy_inv() -> Inventory:
    return Inventory(
        property_address="Test Flat, 1 Example Street",
        inspected_by="C. Brown",
        inspected_at="2026-06-10",
        landlord_name="L. Smith",
        tenant_name="T. Jones",
        rooms=[
            Room(
                name="Kitchen",
                items=[
                    Item(id="K1", name="Floor", category="structure",
                         condition="good", cleanliness="cleaned to domestic standard"),
                    Item(id="K2", name="Window", category="fixture", condition="good"),
                ],
                photos=[Photo(id="P001", path="Kitchen/k1.jpg", room="Kitchen")],
            ),
            Room(
                name="Living Room",
                items=[
                    Item(id="L1", name="Walls", category="structure",
                         condition="good", cleanliness="cleaned to domestic standard"),
                ],
                photos=[Photo(id="P002", path="Living Room/a.jpg", room="Living Room")],
            ),
        ],
    )


def _setup_capture(tmp_path: Path) -> Path:
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Living Room" / "a.jpg")
    return cap


def test_tenancy_render_has_use_case_markers(tmp_path):
    cap = _setup_capture(tmp_path)
    out = tmp_path / "report"
    inv = _tenancy_inv()
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")

    assert TENANCY.report_kicker in html
    assert TENANCY.summary_section_title in html
    assert "Schedule of Condition" in html
    assert TENANCY.initials_note in html
    assert "Tenant initials:" in html
    assert "Landlord / Agent" in html
    assert "Tenant &nbsp; — date" in html
    assert TENANCY.declaration_text in html
    assert "L. Smith" in html
    assert "T. Jones" in html


def test_tenancy_rerender_is_stable(tmp_path):
    cap = _setup_capture(tmp_path)
    out = tmp_path / "report"
    inv = _tenancy_inv()
    render(inv, cap, out, pdf=False)
    first = (out / "inventory.html").read_text(encoding="utf-8")
    render(inv, cap, out, pdf=False)
    second = (out / "inventory.html").read_text(encoding="utf-8")
    assert first == second


def test_deepclean_render_basics(tmp_path):
    cap = _setup_capture(tmp_path)
    out = tmp_path / "report"
    inv = Inventory(
        use_case="deepclean",
        property_address="14 High Street",
        inspected_by="Clean Co",
        inspected_at="2026-07-04",
        parties={"customer_name": "Jane Doe", "cleaner_name": "Sparkle Ltd"},
        rooms=[
            Room(
                name="Kitchen",
                items=[Item(id="K1", name="Worktop", cleanliness="requires cleaning")],
                photos=[Photo(id="P001", path="Kitchen/k1.jpg", room="Kitchen")],
            ),
        ],
    )
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")

    assert DEEP_CLEAN.report_kicker in html
    assert DEEP_CLEAN.summary_section_title in html
    assert "Cleanliness Summary" in html
    assert DEEP_CLEAN.declaration_text in html
    assert "Jane Doe" in html
    assert "Sparkle Ltd" in html
    assert "Customer &nbsp; — date" in html
    assert "Cleaner &nbsp; — date" in html
    assert TENANCY.initials_note not in html
    assert "Tenant initials:" not in html


def test_summary_rows_respects_manual_schedule():
    inv = _tenancy_inv()
    manual = [{"ref": "1.1", "name": "Custom", "condition": "Manual row"}]
    inv.schedule_summary = manual
    assert summary_rows(inv, TENANCY) == manual


def test_summary_rows_falls_back_to_use_case():
    inv = _tenancy_inv()
    rows = summary_rows(inv, TENANCY)
    assert rows and rows[0]["ref"] == "1.1"
    assert rows[0]["name"] == "Property details"


def test_cover_rows_skip_empty_and_header_fields():
    inv = Inventory(landlord_name="L. Smith", tenant_name="", report_ref="R-1")
    rows = build_cover_rows(inv, TENANCY)
    labels = [r["label"] for r in rows]
    assert "Landlord" in labels
    assert "Tenant(s)" not in labels
    assert "Report reference" in labels
    assert "Property address" not in labels


def test_render_cli_use_case_override(tmp_path):
    cap = _setup_capture(tmp_path)
    out = tmp_path / "report"
    inv = _tenancy_inv()
    render(inv, cap, out, pdf=False)
    assert main(["render", str(cap), "-o", str(out),
                 "--use-case", "deepclean", "--no-pdf"]) == 0
    html = (out / "inventory.html").read_text(encoding="utf-8")
    assert DEEP_CLEAN.report_kicker in html
    assert "Cleanliness Summary" in html


def test_sample_report_rerender_idempotent(tmp_path):
    """Committed sample inventory re-renders without drift."""
    sample_dir = Path("examples/sample-report")
    if not sample_dir.is_dir():
        return
    inv_path = sample_dir / "inventory.json"
    if not inv_path.is_file():
        return

    inv = Inventory.from_json(inv_path.read_text(encoding="utf-8"))
    cap = tmp_path / "capture"
    cap.mkdir()
    for room in inv.rooms:
        for photo in room.photos:
            src = Path(photo.path.replace("\\", "/"))
            if src.is_absolute():
                dest = Path(photo.path)
            else:
                dest = cap / src
            _img(dest)

    out = tmp_path / "report"
    out.mkdir()
    (out / "inventory.json").write_text(inv.to_json(), encoding="utf-8")
    render(inv, cap, out, pdf=False)
    first = (out / "inventory.html").read_text(encoding="utf-8")
    render(inv, cap, out, pdf=False)
    second = (out / "inventory.html").read_text(encoding="utf-8")
    assert first == second
    assert TENANCY.report_kicker in first
    assert "Schedule of Condition" in first
