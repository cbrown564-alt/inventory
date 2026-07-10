from benchmarks.quality_gate import evaluate


def test_quality_gate_requires_native_resolution_and_all_three_metrics():
    metrics = {"notable_recall": .91, "hallucination": .04,
               "defect_recall": .76}
    result = evaluate(metrics, {"native_resolution": True})
    assert result["pass"]
    assert not evaluate(metrics, {"native_resolution": False})["pass"]
    assert not evaluate({**metrics, "hallucination": .06},
                        {"native_resolution": True})["pass"]
