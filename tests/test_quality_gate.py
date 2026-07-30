from benchmarks.quality_gate import evaluate


def test_quality_gate_requires_native_resolution_and_all_three_metrics():
    metrics = {"notable_recall": .91, "hallucination": .04,
               "defect_recall": .76}
    evidence = {"checks": {
        "two_external_properties": True,
        "source_authority_recorded": True,
        "independently_annotated": True,
        "notable_fact_denominator": True,
        "material_defect_denominator": True,
        "clean_negative_controls": True,
        "ambiguous_near_negatives": True,
        "property_capture_dirs": True,
        "fixture_frozen": True,
        "image_manifest_complete": True,
        "capture_dir_matches_fixture": True,
    }, "counts": {"images": 1}}
    resolution = {
        "images": 1,
        "median_megapixels": 12.0,
        "native_resolution": True,
    }
    result = evaluate(metrics, resolution, evidence)
    assert result["pass"]
    assert not evaluate(
        metrics, {**resolution, "native_resolution": False}, evidence
    )["pass"]
    assert not evaluate({**metrics, "hallucination": .06},
                        resolution, evidence)["pass"]
    assert not evaluate(metrics, resolution)["pass"]


def test_quality_gate_requires_the_frozen_capture_and_decodable_images():
    metrics = {
        "notable_recall": .91,
        "hallucination": .04,
        "defect_recall": .76,
    }
    evidence = {"checks": {
        name: True
        for name in (
            "two_external_properties",
            "source_authority_recorded",
            "independently_annotated",
            "notable_fact_denominator",
            "material_defect_denominator",
            "clean_negative_controls",
            "ambiguous_near_negatives",
            "property_capture_dirs",
            "fixture_frozen",
            "image_manifest_complete",
            "capture_dir_matches_fixture",
        )
    }, "counts": {"images": 2}}
    one_readable = {
        "images": 1,
        "median_megapixels": 12.0,
        "native_resolution": True,
    }
    assert not evaluate(metrics, one_readable, evidence)["pass"]

    evidence["checks"]["capture_dir_matches_fixture"] = False
    two_readable = {**one_readable, "images": 2}
    assert not evaluate(metrics, two_readable, evidence)["pass"]


def test_quality_gate_rejects_non_numeric_metrics_without_crashing():
    result = evaluate(
        {
            "notable_recall": "unknown",
            "hallucination": None,
            "defect_recall": [],
        },
        {"images": 0, "native_resolution": False},
    )

    assert result["pass"] is False
    assert result["checks"]["notable_recall"] is False
