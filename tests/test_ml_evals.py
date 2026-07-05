"""Smoke tests for ML Phase 1 eval harnesses."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeinventory.curate import mslap_ratio, mslap_score  # noqa: E402
from PIL import Image


def _wide_img(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("L", (320, 180), color=180)
    px = img.load()
    for y in range(180):
        for x in range(320):
            if (x + y) % 17 == 0:
                px[x, y] = 40
    img.save(path)


def _flat_img(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (320, 180), color=128).save(path)


def test_mslap_ratio_textured_above_flat(tmp_path):
    wide = tmp_path / "wide.jpg"
    flat = tmp_path / "flat.jpg"
    _wide_img(wide)
    _flat_img(flat)
    with Image.open(wide) as im:
        wide_g = im.convert("L")
    with Image.open(flat) as im:
        flat_g = im.convert("L")
    assert mslap_ratio(wide_g) > mslap_ratio(flat_g)
    assert mslap_score(wide) > mslap_score(flat)


def test_eval_segment_embed_demo_writes_html(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_segment_embed as ese  # noqa: E402

    out = tmp_path / "segment-embed.html"

    class Args:
        demo = True
        video = None
        gold = ROOT / "evals/fixtures/own-property/segment-gold.json"
        output = out
        encoder = "dinov2"
        every = 5.0
        width = 448
        device = "cpu"
        no_torch = True

    metrics = ese.run(Args())
    assert metrics["experiment"] == "ML-E1"
    assert metrics["n_frames"] >= 10
    assert out.is_file()
    assert "mean_boundary_error_s" in metrics


def test_segment_gold_fixture_loads():
    path = ROOT / "evals/fixtures/own-property/segment-gold.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["rooms"]) == 10
    assert data["rooms"][0]["room"] == "Hallway"
