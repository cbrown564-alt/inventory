"""Photo-mode ingest and capture-experiment scaffolding (docs/26)."""

import json
from pathlib import Path

import pytest
from PIL import Image, ExifTags

from homeinventory.capture_experiment import (
    validate_capture_layout,
    write_scorecard_template,
)
from homeinventory.cli import main
from homeinventory.ingest import exif_capture_time, ingest


def _img(path: Path, *, exif_dt: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (32, 24), "white")
    if exif_dt:
        exif = im.getexif()
        tag_ids = {v: k for k, v in ExifTags.TAGS.items()}
        exif[tag_ids["DateTimeOriginal"]] = exif_dt
        im.save(path, exif=exif)
    else:
        im.save(path)


def _tiny_video(path: Path) -> None:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
    assert vw.isOpened()
    for _ in range(5):
        vw.write(np.zeros((24, 32, 3), dtype=np.uint8))
    vw.release()


def test_photo_mode_groups_by_room_folder(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "a.jpg")
    _img(cap / "Kitchen" / "b.jpg")
    _img(cap / "Living Room" / "c.jpg")

    rooms = ingest(cap, tmp_path / "work", photo_mode=True)
    assert set(rooms) == {"Kitchen", "Living Room"}
    assert len(rooms["Kitchen"]) == 2
    assert len(rooms["Living Room"]) == 1
    for ps in rooms.values():
        for p in ps:
            assert p.source_video is None
            assert not Path(p.path).is_absolute()


def test_photo_mode_skips_videos(tmp_path):
    cv2 = pytest.importorskip("cv2")

    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "still.jpg")
    _tiny_video(cap / "Kitchen" / "clip.avi")
    _tiny_video(cap / "walk.avi")

    work = tmp_path / "work"
    rooms = ingest(cap, work, photo_mode=True)
    assert set(rooms) == {"Kitchen"}
    assert len(rooms["Kitchen"]) == 1
    assert rooms["Kitchen"][0].path.endswith("still.jpg")
    assert not (work / "frames").exists()


def test_photo_mode_preserves_exif_capture_time(tmp_path):
    cap = tmp_path / "capture"
    dt = "2026:07:08 14:30:00"
    photo = cap / "Kitchen" / "native.jpg"
    _img(photo, exif_dt=dt)

    assert exif_capture_time(photo) == "2026-07-08 14:30:00"

    rooms = ingest(cap, tmp_path / "work", photo_mode=True)
    assert rooms["Kitchen"][0].captured_at == "2026-07-08 14:30:00"


def test_build_photo_mode_offline(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    out = tmp_path / "report"
    rc = main(["build", str(cap), "-o", str(out),
               "--backend", "offline", "--no-detect", "--no-pdf",
               "--photo-mode"])
    assert rc == 0
    inv = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    assert {r["name"] for r in inv["rooms"]} == {"Kitchen"}


def test_experiment_validate_p1_layout(tmp_path):
    cap = tmp_path / "capture"
    for room in ("Kitchen", "Living Room"):
        for i in range(3):
            _img(cap / room / f"{i}.jpg")

    report = validate_capture_layout(cap, "P1")
    assert report.ok
    assert report.total_photos == 6
    assert report.total_videos == 0


def test_experiment_validate_p1_rejects_room_video(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "a.jpg")
    _img(cap / "Kitchen" / "b.jpg")
    _img(cap / "Kitchen" / "c.jpg")
    _tiny_video(cap / "Kitchen" / "oops.avi")

    report = validate_capture_layout(cap, "P1")
    assert not report.ok
    assert any("video" in e.lower() for e in report.errors)


def test_experiment_validate_cli(tmp_path, capsys):
    cap = tmp_path / "capture"
    for i in range(3):
        _img(cap / "Kitchen" / f"{i}.jpg")

    assert main(["experiment", "validate", str(cap), "--arm", "P1"]) == 0
    assert "layout ok" in capsys.readouterr().out


def test_scorecard_template_has_all_arms(tmp_path):
    path = tmp_path / "scorecard.json"
    write_scorecard_template(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["arms"]) == {"V0", "V1", "V2", "P1", "P2", "H1"}
    assert data["arms"]["P1"]["accuracy"]["recall"] is None
