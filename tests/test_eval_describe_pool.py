"""Smoke tests for evals/eval_describe_pool.py (ML-E3)."""

import json
import pathlib
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))
import eval_describe_pool  # noqa: E402


def _synthetic_report(tmp_path: pathlib.Path) -> pathlib.Path:
    report = tmp_path / "report"
    frames_dir = report / "work" / "frames" / "Room"
    frames_dir.mkdir(parents=True)
    paths = []
    for i, val in enumerate([30, 80, 160, 240], start=1):
        p = frames_dir / f"walk_f00000{i}.jpg"
        Image.new("L", (96, 64), color=val).save(p, format="JPEG")
        paths.append(p)
    inv = {
        "rooms": [{
            "name": "Room",
            "photos": [
                {"id": f"P{i:03d}", "path": str(p), "source_video": "w.mp4"}
                for i, p in enumerate(paths, start=1)
            ],
        }],
    }
    (report / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    return report


def test_describe_pool_bottom_decile_estimate(tmp_path):
    report = _synthetic_report(tmp_path)
    frames = eval_describe_pool.load_video_frames(report)
    scored = eval_describe_pool.score_frames(report, frames)
    drop = eval_describe_pool.bottom_decile_drop(scored, decile=0.1)
    assert drop["n_frames"] == 4
    assert drop["would_drop_bottom_decile"] >= 1
    assert all(r["describe_eligible"] for r in scored)
