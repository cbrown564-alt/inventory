"""Focused tests for the simplified describe-check seeder."""

from __future__ import annotations

from evals.synthetic.describe_check import seed_claims


def test_seed_claims_attaches_defect_to_overlapping_item() -> None:
    scenario = {
        "cleanliness": "ordinarily occupied with cushions and a few objects",
        "views": [
            {
                "id": "D-condition",
                "intended_visible_items": [
                    "sofa arm",
                    "seat cushion",
                    "fabric seam",
                    "carpet",
                ],
                "intended_defects": [
                    "small frayed patch on the outer sofa arm",
                ],
            }
        ],
    }
    claims = seed_claims(scenario)
    by_name = {claim["name"]: claim for claim in claims}
    assert by_name["sofa arm"]["defects"] == [
        "small frayed patch on the outer sofa arm"
    ]
    assert by_name["sofa arm"]["condition"] == "fair"
    assert by_name["carpet"]["defects"] == []


def test_seed_claims_prefers_vinyl_floor_for_floor_tear() -> None:
    scenario = {
        "cleanliness": "ordinarily occupied with a few dishes",
        "views": [
            {
                "id": "D-condition",
                "intended_visible_items": [
                    "vinyl floor",
                    "plinth",
                    "base unit",
                    "cooker side",
                ],
                "intended_defects": [
                    "small triangular tear in the vinyl floor beside the cooker",
                ],
            }
        ],
    }
    claims = seed_claims(scenario)
    by_name = {claim["name"]: claim for claim in claims}
    assert by_name["vinyl floor"]["defects"]
    assert by_name["cooker side"]["defects"] == []
