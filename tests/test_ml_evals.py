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


def test_eval_room_classifier_demo_writes_json(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_room_classifier as erc  # noqa: E402

    out = tmp_path / "room-clf-eval.json"
    weights_path = tmp_path / "room-clf-weights.json"

    class Args:
        report = None
        bleed = ROOT / "evals/fixtures/ownproperty-bleed-exclusions.json"
        output = out
        weights = weights_path
        backend = "demo"
        device = "cpu"
        train_stub = True
        stream_hf = False
        max_samples = 8

    erc.train_stub(output=weights_path, stream_hf=False, max_samples=8)
    payload = erc.run_eval(Args())
    assert payload["experiment"] == "ML-E16"
    assert payload["metrics"]["n_exclusions"] >= 30
    assert payload["metrics"]["would_reject_rate"] > 0
    assert out.is_file()
    assert weights_path.is_file()
    wdata = json.loads(weights_path.read_text(encoding="utf-8"))
    assert "fine_tune_steps" in wdata["training"]


def test_train_iqa_koniq_bootstrap(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import train_iqa_koniq as tik  # noqa: E402

    out = tmp_path / "iqa-koniq-weights.json"
    sys.argv = [
        "train_iqa_koniq.py",
        "--bootstrap-scores",
        "-o",
        str(out),
    ]
    assert tik.main() == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["experiment"] == "ML-E17"
    assert data["training"]["mode"] == "bootstrap-musiq-proxy"
    assert "disclaimer" in data
    assert len(data["weights"]) == len(data["features"])


def test_eval_finetune_detect_demo(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_finetune_detect as efd  # noqa: E402

    out = tmp_path / "detect-finetune-eval.json"
    weights = tmp_path / "detect-finetune-probe.json"

    class Args:
        demo = True
        capture_dir = ROOT / "benchmarks/inventoryflex/capture"
        labels = ROOT / "evals/fixtures/inventoryflex/labels.json"
        boxes = ROOT / "evals/fixtures/inventoryflex/labels_boxes.json"
        split = ROOT / "evals/splits/inventoryflex.json"
        output = out
        weights_meta = weights
        weights_out = None
        work_dir = None
        conf = 0.25
        iou = 0.5
        match_threshold = 0.6
        bootstrap_threshold = 0.65
        bootstrap_conf = 0.15
        epochs = 5
        batch = 4
        imgsz = 640
        device = "cpu"
        skip_train = False

    payload = efd.run(Args())
    assert payload["experiment"] == "ML-E12"
    assert payload["pass"] is False
    assert payload["delta_recall_pp"] < 0
    assert out.is_file()
    assert weights.is_file()
    wdata = json.loads(weights.read_text(encoding="utf-8"))
    assert wdata["experiment"] == "ML-E12"
    assert "licence" in wdata


def test_box_iou():
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_finetune_detect as efd  # noqa: E402

    assert efd.box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert efd.box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_eval_iqa_koniq_demo(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import train_iqa_koniq as tik  # noqa: E402
    import eval_iqa_koniq as eik  # noqa: E402

    weights = tmp_path / "iqa-koniq-weights.json"
    sys.argv = [
        "train_iqa_koniq.py",
        "--bootstrap-scores",
        "-o",
        str(weights),
    ]
    tik.main()

    class DemoArgs:
        report_dir = pathlib.Path("report")
        gold = ROOT / "evals/fixtures/own-property/hero-gold.json"
        koniq_weights = weights
        mle6_weights = ROOT / "evals/fixtures/own-property/iqa-linear-weights.json"
        output = tmp_path / "iqa-koniq-onnx.html"
        json_output = tmp_path / "iqa-koniq-metrics.json"
        demo = True

    summary = eik.run(DemoArgs())
    assert summary["experiment"] == "ML-E17"
    assert DemoArgs.output.is_file()
    assert DemoArgs.json_output.is_file()
