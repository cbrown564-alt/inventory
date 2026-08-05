import hashlib

import pytest

from benchmarks.native_fixture import audit_fixture, freeze, initialise


def _fact(prefix: str, count: int) -> list[dict]:
    return [
        {"id": f"{prefix}-{index}", "description": f"Evidence {index}"}
        for index in range(count)
    ]


def test_native_fixture_initialise_requires_two_properties(tmp_path):
    with pytest.raises(ValueError):
        initialise(tmp_path / "native", ["property-a"])


def test_native_fixture_initialise_rejects_unsafe_property_paths(tmp_path):
    with pytest.raises(ValueError, match="directory names"):
        initialise(tmp_path / "native", ["property-a", "../outside"])


def test_native_fixture_audit_requires_frozen_status(tmp_path):
    fixture = tmp_path / "native"
    manifest_path = initialise(fixture, ["property-a", "property-b"])
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frozen_at"] = "2026-07-30T12:00:00+00:00"

    result = audit_fixture(fixture, manifest)

    assert result["checks"]["fixture_frozen"] is False


def test_native_fixture_freeze_hashes_complete_external_evidence(tmp_path):
    fixture = tmp_path / "native"
    manifest_path = initialise(fixture, ["property-a", "property-b"])
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    for index, prop in enumerate(manifest["properties"]):
        prop["annotator"] = f"independent-reviewer-{index}"
        prop["source_authority"] = "permission-record"
        prop["independently_annotated"] = True
        prop["notable_facts"] = _fact(f"fact-{index}", 50)
        prop["material_defects"] = _fact(f"defect-{index}", 10)
        prop["negative_controls"]["clean"] = _fact(f"clean-{index}", 1)
        prop["negative_controls"]["ambiguous"] = _fact(
            f"ambiguous-{index}", 1
        )
        image = fixture / "capture" / prop["capture_subdir"] / "source.jpg"
        image.write_bytes(f"image-{index}".encode())
    manifest_path.write_text(
        __import__("json").dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    result = freeze(fixture)

    assert result["ready"]
    saved = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["status"] == "frozen"
    expected = hashlib.sha256(b"image-0").hexdigest()
    assert saved["image_manifest"][0]["sha256"] == expected


def test_native_fixture_audit_detects_changed_image(tmp_path):
    fixture = tmp_path / "native"
    manifest_path = initialise(fixture, ["property-a", "property-b"])
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    for index, prop in enumerate(manifest["properties"]):
        prop["annotator"] = f"reviewer-{index}"
        prop["source_authority"] = "permission-record"
        prop["independently_annotated"] = True
        prop["notable_facts"] = _fact(f"fact-{index}", 50)
        prop["material_defects"] = _fact(f"defect-{index}", 10)
        prop["negative_controls"]["clean"] = [{}]
        prop["negative_controls"]["ambiguous"] = [{}]
        (fixture / "capture" / prop["capture_subdir"] / "source.jpg").write_bytes(
            f"image-{index}".encode()
        )
    manifest_path.write_text(__import__("json").dumps(manifest), encoding="utf-8")
    freeze(fixture)
    changed = fixture / "capture/property-a/source.jpg"
    changed.write_bytes(b"changed")
    saved = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))

    result = audit_fixture(fixture, saved)

    assert not result["ready"]
    assert not result["checks"]["image_manifest_complete"]


def test_native_fixture_freeze_requires_images_for_each_property(tmp_path):
    fixture = tmp_path / "native"
    manifest_path = initialise(fixture, ["property-a", "property-b"])
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    for index, prop in enumerate(manifest["properties"]):
        prop["annotator"] = f"reviewer-{index}"
        prop["source_authority"] = "permission-record"
        prop["independently_annotated"] = True
        prop["notable_facts"] = _fact(f"fact-{index}", 50)
        prop["material_defects"] = _fact(f"defect-{index}", 10)
        prop["negative_controls"]["clean"] = [{}]
        prop["negative_controls"]["ambiguous"] = [{}]
    (fixture / "capture/property-a/source.jpg").write_bytes(b"only one property")
    manifest_path.write_text(__import__("json").dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="property capture dirs"):
        freeze(fixture)
