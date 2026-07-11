import json
import zipfile

from homeinventory.archive import build_evidence_archive, verify_evidence_archive


def test_archive_includes_capture_and_report_but_not_capabilities(tmp_path):
    capture = tmp_path / "capture"
    report = tmp_path / "report"
    capture.mkdir()
    report.mkdir()
    (capture / "walk.mp4").write_bytes(b"video")
    (report / "inventory.json").write_text('{"address":"1 High St"}')
    (report / "manifest.json").write_text('{"files":[]}')
    (report / "share.json").write_text('{"tenant_token":"secret"}')
    (report / "owner-pairing.json").write_text('{"owner_token":"secret"}')
    destination = report / "evidence.zip"

    index = build_evidence_archive(capture, report, destination)

    assert not verify_evidence_archive(destination)
    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        assert "capture/walk.mp4" in names
        assert "report/inventory.json" in names
        assert "report/manifest.json" in names
        assert "report/share.json" not in names
        assert "report/owner-pairing.json" not in names
        assert "report/evidence.zip" not in names
        embedded = json.loads(archive.read("evidence-index.json"))
    assert embedded == index


def test_verify_reports_tampered_member(tmp_path):
    capture = tmp_path / "capture"
    report = tmp_path / "report"
    capture.mkdir()
    report.mkdir()
    (capture / "photo.jpg").write_bytes(b"original")
    destination = tmp_path / "evidence.zip"
    build_evidence_archive(capture, report, destination)

    with zipfile.ZipFile(destination, "a") as archive:
        archive.writestr("capture/photo.jpg", b"changed")

    assert "hash mismatch: capture/photo.jpg" in verify_evidence_archive(destination)


def test_archive_skips_symlinks(tmp_path):
    capture = tmp_path / "capture"
    report = tmp_path / "report"
    capture.mkdir()
    report.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (capture / "escape.txt").symlink_to(outside)
    destination = tmp_path / "evidence.zip"

    build_evidence_archive(capture, report, destination)

    with zipfile.ZipFile(destination) as archive:
        assert "capture/escape.txt" not in archive.namelist()
