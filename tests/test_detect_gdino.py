from homeinventory.detect import Detection, verify_detection_proposals


def test_detection_verify_keeps_repeat_support_or_strong_singletons():
    proposals = {
        "P1": [Detection("chair", 0.3, (0, 0, 50, 50)),
               Detection("ghost", 0.2, (0, 0, 50, 50))],
        "P2": [Detection("chair", 0.32, (0, 0, 50, 50)),
               Detection("oven", 0.7, (0, 0, 50, 50))],
    }
    verified = verify_detection_proposals(proposals)
    assert [d.label for d in verified["P1"]] == ["chair"]
    assert [d.label for d in verified["P2"]] == ["chair", "oven"]
