"""End-to-end tests using the offline backend (no network, no model weights)."""

import json
from pathlib import Path

from PIL import Image

from homeinventory.cli import main
from homeinventory.ingest import ingest
from homeinventory.pipeline import _checkpoint_identity, _checkpoint_matches
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


def test_checkpoint_reuse_is_bound_to_evidence_backend_and_use_case():
    class Backend:
        name = "claude"
        model = "claude-opus-4-8"

    photos = [Photo(id="P001", path="Kitchen/a.jpg", room="Kitchen",
                    sha256="abc")]
    identity = _checkpoint_identity(photos, Backend(), "tenancy")
    assert _checkpoint_matches({"checkpoint": identity}, identity)
    assert not _checkpoint_matches({}, identity)  # legacy checkpoint: safe miss

    changed_photo = [Photo(id="P001", path="Kitchen/a.jpg", room="Kitchen",
                           sha256="different")]
    assert not _checkpoint_matches(
        {"checkpoint": identity},
        _checkpoint_identity(changed_photo, Backend(), "tenancy"))

    other_backend = Backend()
    other_backend.model = "claude-haiku-4-5"
    assert not _checkpoint_matches(
        {"checkpoint": identity},
        _checkpoint_identity(photos, other_backend, "tenancy"))
    assert not _checkpoint_matches(
        {"checkpoint": identity},
        _checkpoint_identity(photos, Backend(), "contents"))


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


def test_extract_keyframes_lead_trim(tmp_path):
    """Room videos cut from one continuous walkthrough with stream copy start
    up to ~2s inside the previous room; lead_trim_s drops those bleed frames
    at the source (the M2 boundary-bleed failure mode, docs/07)."""
    import pytest
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    from homeinventory.ingest import extract_keyframes

    fps, seconds, size = 10, 6, (64, 48)
    video = tmp_path / "room.avi"
    vw = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    assert vw.isOpened()
    rng = np.random.default_rng(0)  # noise: every frame sharp and distinct
    for _ in range(seconds * fps):
        vw.write(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    vw.release()

    def kept_indices(sub, trim):
        frames = extract_keyframes(video, tmp_path / sub, lead_trim_s=trim)
        assert frames, "expected keyframes"
        return [int(f.stem.rsplit("_f", 1)[1]) for f in frames]

    # default keeps the bleed window; trimming 2.0s removes every frame
    # before 2.0s * 10fps = frame 20
    assert min(kept_indices("untrimmed", 0.0)) < 2.0 * fps
    assert min(kept_indices("trimmed", 2.0)) >= 2.0 * fps
