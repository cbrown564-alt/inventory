"""End-to-end tests using the offline backend (no network, no model weights)."""

import json
from pathlib import Path

from PIL import Image

from homeinventory.cli import main
from homeinventory.ingest import ingest
from homeinventory.report import render
from homeinventory.schema import Inventory, Item, Photo, Room


def _img(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), "white").save(path)


def test_ingest_rooms_and_relative_paths(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Living Room" / "a.jpg")
    _img(cap / "Living Room" / "b.jpg")
    _img(cap / "Kitchen" / "c.jpg")
    _img(cap / "loose.jpg")  # root-level photo lands in "General"
    rooms = ingest(cap, tmp_path / "work")
    assert set(rooms) == {"Living Room", "Kitchen", "General"}
    ids = [p.id for ps in rooms.values() for p in ps]
    assert len(ids) == len(set(ids)) == 4
    for ps in rooms.values():
        for p in ps:
            assert not Path(p.path).is_absolute()


def test_render_writes_utf8(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Living Room" / "a.jpg")
    inv = Inventory(property_address="Flat 2 — £950", rooms=[Room(
        name="Living Room",
        items=[Item(id="LIV-001", name="Sofa", est_value_band=">£1000")],
        photos=[Photo(id="P001", path="Living Room/a.jpg", room="Living Room")],
    )])
    out = tmp_path / "report"
    outputs = render(inv, cap, out, pdf=False)
    html = outputs["html"].read_text(encoding="utf-8")
    assert "£950" in html
    assert (out / "photos" / "P001.jpg").exists()
    again = Inventory.from_json(outputs["json"].read_text(encoding="utf-8"))
    assert again.property_address == "Flat 2 — £950"


def test_build_offline_then_partial_rebuild_keeps_other_rooms(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Living Room" / "l1.jpg")
    out = tmp_path / "report"
    base = ["build", str(cap), "-o", str(out),
            "--backend", "offline", "--no-detect", "--no-pdf"]

    assert main(base) == 0
    inv1 = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    assert {r["name"] for r in inv1["rooms"]} == {"Kitchen", "Living Room"}

    # rebuilding one room must not drop the others from inventory.json
    assert main(base + ["--room", "kitchen"]) == 0
    inv2 = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    assert {r["name"] for r in inv2["rooms"]} == {"Kitchen", "Living Room"}

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["files"]) == 2
    assert all(m["sha256"] for m in manifest["files"])


def test_build_unknown_room_errors(tmp_path, capsys):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    rc = main(["build", str(cap), "-o", str(tmp_path / "report"),
               "--backend", "offline", "--no-detect", "--no-pdf",
               "--room", "ballroom"])
    assert rc == 2
    assert "available rooms" in capsys.readouterr().err


def test_build_from_json_preserves_reviewed_room(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Living Room" / "l1.jpg")
    out = tmp_path / "report"
    base = ["build", str(cap), "-o", str(out),
            "--backend", "offline", "--no-detect", "--no-pdf"]

    assert main(base) == 0
    inv = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    kitchen = next(r for r in inv["rooms"] if r["name"] == "Kitchen")
    pid = kitchen["photos"][0]["id"]
    kitchen["items"] = [{
        "id": "KIT-001", "name": "Window", "category": "other",
        "description": "draft", "condition": "fair", "defects": [],
        "quantity": 1, "photo_ids": [pid], "reviewed": False,
        "rejected": False, "rejected_defects": [], "defect_regions": [],
        "comments": [],
    }]
    kitchen["items"][0]["reviewed"] = True
    kitchen["items"][0]["condition"] = "good"
    kitchen["items"][0]["name"] = "Attested hob"
    kitchen["items"].append({
        "id": "KIT-099", "name": "Added pan", "added_by": "reviewer",
        "reviewed": True, "condition": "good", "category": "other",
        "description": "", "defects": [], "photo_ids": [], "quantity": 1,
        "rejected": False, "rejected_defects": [], "defect_regions": [],
        "comments": [],
    })
    edited = out / "reviewed.json"
    inv["signatures"] = [{"role": "landlord", "name": "C. Brown",
                          "signed_at": "2026-06-10", "inventory_sha256": "abc",
                          "via": "test"}]
    edited.write_text(json.dumps(inv), encoding="utf-8")

    assert main(base + ["--room", "Kitchen", "--from-json", str(edited)]) == 0
    rebuilt = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    assert rebuilt["signatures"][0]["name"] == "C. Brown"
    rk = next(r for r in rebuilt["rooms"] if r["name"] == "Kitchen")
    attested = next(i for i in rk["items"] if i["name"] == "Attested hob")
    assert attested["reviewed"] is True and attested["condition"] == "good"
    assert any(i["name"] == "Added pan" for i in rk["items"])
    assert {r["name"] for r in rebuilt["rooms"]} == {"Kitchen", "Living Room"}


def test_build_from_json_missing_file_errors(tmp_path, capsys):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    rc = main(["build", str(cap), "-o", str(tmp_path / "report"),
               "--backend", "offline", "--no-detect", "--no-pdf",
               "--from-json", str(tmp_path / "nope.json")])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
