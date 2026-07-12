"""Smoke tests for ML Phase 1 eval harnesses."""

import json
import pathlib
import sys

import pytest

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


def _write_grey_jpeg(path: pathlib.Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (64, 48), color=value).save(path, format="JPEG")


def _synthetic_report(tmp_path: pathlib.Path, *, n_rooms: int = 1,
                      frames_per_room: int = 3):
    """Minimal CI-safe report/ + matching gold (no gitignored artifacts).

    Mirrors tests/test_eval_hero_cover.py::_synthetic_report but parametrised
    over room and frame count so the rerank pass bar (top-1 on N gold rooms)
    and the surface eval's ``>= 5 labelled frames`` spearman gate can both be
    met without the real report/ tree, which is gitignored and absent on CI.
    The gold's top-1 is a real frame in each room, so the cover baseline ranks
    it in the top-k and the demo rerank picks it; every frame is labelled so
    the surface spearman is defined.
    """
    report = tmp_path / "report"
    inv_rooms = []
    gold_rooms = {}
    greys = [30 + int(190 * i / max(1, frames_per_room - 1))
             for i in range(frames_per_room)]
    hero_idx = frames_per_room // 2
    for r in range(n_rooms):
        room_name = f"Room {r:02d}"
        seg = f"{room_name.replace(' ', '_')}_seg00"
        frames_dir = report / "work" / "frames" / seg
        names = []
        photos = []
        for i, val in enumerate(greys):
            fn = f"clip{r:02d}_f{i + 1:06d}.jpg"
            _write_grey_jpeg(frames_dir / fn, val)
            names.append(fn)
            photos.append({
                "id": f"P{r:02d}{i}",
                "path": str(frames_dir / fn),
                "source_video": "clip.MOV",
                "hero": 1 if i == hero_idx else None,
            })
        inv_rooms.append({"name": room_name, "photos": photos})
        # Hero first (rerank target), then a full ranked split so the surface
        # eval sees every frame labelled (needs >= 5).
        ordered = [names[hero_idx]] + [n for n in names if n != names[hero_idx]]
        half = max(1, len(ordered) // 2)
        gold_rooms[room_name] = {
            "top": ordered[:half],
            "bottom": ordered[half:],
            "notes": "synthetic",
        }
    report.mkdir(parents=True, exist_ok=True)
    (report / "inventory.json").write_text(
        json.dumps({"rooms": inv_rooms}), encoding="utf-8")
    gold_path = tmp_path / "hero-gold.json"
    gold_path.write_text(json.dumps({"rooms": gold_rooms}), encoding="utf-8")
    return report, gold_path


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


def test_train_room_classifier_self_test():
    """embed_head.py refactor (docs/23 §5): room classifier's --self-test
    (synthetic embeddings, no download) must still pass unchanged."""
    pytest.importorskip("torch")
    sys.path.insert(0, str(ROOT / "evals"))
    import train_room_classifier as trc  # noqa: E402

    assert trc.self_test() == 0


def test_train_iqa_embed_self_test():
    """ML-E17 (correct): embedding regression head, synthetic self-test path
    (no KonIQ download) — mirrors train_room_classifier.py's --self-test but
    in regression mode (docs/23 §5)."""
    pytest.importorskip("torch")
    sys.path.insert(0, str(ROOT / "evals"))
    import train_iqa_embed as tie  # noqa: E402

    assert tie.self_test() == 0


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


def test_eval_siamese_compare_demo_writes_json(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_siamese_compare as esc  # noqa: E402

    out = tmp_path / "siamese-compare-demo.json"

    class Args:
        paired_fixture = None
        capture_dir = ROOT / "benchmarks/inventoryflex/capture"
        output = out
        demo = True
        encoder = "openclip"
        device = "cpu"
        no_torch = True
        max_same_room = 2
        max_cross_room = 4
        max_pairs_in_output = 20

    payload = esc.run(Args())
    assert payload["experiment"] == "ML-E14"
    assert payload["blocked"] is True
    assert payload["metrics"]["n_pairs"] >= 4
    assert out.is_file()


def test_eval_defect_zeroshot_demo_writes_json(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_defect_zeroshot as edz  # noqa: E402

    out = tmp_path / "defect-filter-report.json"
    capture = ROOT / "benchmarks/inventoryflex/capture"
    if not capture.is_dir():
        capture = ROOT / "evals/fixtures/inventoryflex/bbox-review/full"

    class Args:
        capture_dir = capture
        output = out
        demo = True
        device = "cpu"
        no_torch = True
        threshold = 0.5
        max_photos = 16

    payload = edz.run(Args())
    assert payload["experiment"] == "ML-E15"
    assert payload["metrics"]["n_photos"] == 16
    assert payload["pass"] is False
    assert payload["metrics"]["fp_pct"] > 10
    assert out.is_file()


def test_eval_defect_pretrain_demo_writes_json(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_defect_pretrain as edp  # noqa: E402

    out = tmp_path / "defect-pretrain-report.json"
    capture = ROOT / "benchmarks/inventoryflex/capture"
    if not capture.is_dir():
        capture = ROOT / "evals/fixtures/inventoryflex/bbox-review/full"

    class Args:
        capture_dir = capture
        output = out
        demo = True
        device = "cpu"
        no_torch = True
        weights = None
        threshold = 0.5
        max_photos = 16

    payload = edp.run(Args())
    assert payload["experiment"] == "ML-E20"
    assert payload["pretrain_available"] is False
    assert "training_recipe" in payload
    assert payload["data_needs"]["tier_c_datasets"]
    assert payload["pass"] is False
    assert out.is_file()


def test_eval_segment_vlm_refine_demo(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_segment_vlm_refine as esvr  # noqa: E402

    out = tmp_path / "segment-vlm-refine.json"

    class Args:
        video = None
        demo = True
        # No VLM segments.json on a clean checkout (segment-spike*/ is
        # gitignored) → run() synthesises the baseline from segment-gold.
        segments = None
        gold = ROOT / "evals/fixtures/own-property/segment-gold.json"
        bleed = ROOT / "evals/fixtures/ownproperty-bleed-exclusions.json"
        report = None
        output = out
        model = "gemini-3.5-flash"

    payload = esvr.run(Args())
    assert payload["experiment"] == "ML-E2"
    assert payload["baseline_bleed_items"] >= 30
    assert payload["refined_bleed_items"] < payload["baseline_bleed_items"]
    assert payload["pass"] is True
    assert out.is_file()


def test_eval_vlm_rerank_demo(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_vlm_rerank as evr  # noqa: E402

    # Synthesise nine gold rooms whose top-1 the demo rerank recovers. The real
    # report/ tree is gitignored (absent on CI).
    report, gold_path = _synthetic_report(tmp_path, n_rooms=9)

    class Args:
        report_dir = report
        gold = gold_path
        output = tmp_path / "hero-vlm-rerank.html"
        json_output = tmp_path / "hero-vlm-rerank-metrics.json"
        demo = True
        model = "claude-sonnet-5"

    summary = evr.run(Args())
    assert summary["experiment"] == "ML-E8"
    assert summary["gold_rank1_in_classical_top10"] == summary["gold_rooms"]
    assert summary["vlm_top1_hits"] == summary["gold_rooms"]
    assert summary["pass"] is True
    assert "cost_estimate" in summary
    assert Args.output.is_file()
    assert Args.json_output.is_file()


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


def test_eval_pause_detect_demo_writes_artifacts(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_pause_detect as epd  # noqa: E402

    class Args:
        video = None
        report_dir = ROOT / "report"
        demo = True
        gold = ROOT / "evals/fixtures/own-property/hero-gold.json"
        segment_gold = ROOT / "evals/fixtures/own-property/segment-gold.json"
        html_output = tmp_path / "pause-timeline.html"
        json_output = tmp_path / "pause-detect-metrics.json"
        every = 0.5
        width = 320

    metrics = epd.run(Args())
    assert metrics["experiment"] == "ML-E9"
    assert metrics["mode"] == "synthetic"
    assert Args.html_output.is_file()
    assert Args.json_output.is_file()
    assert "gold_top3_pause_recall" in metrics.get("eval", {})


def test_eval_segformer_surface_demo_writes_artifacts(tmp_path):
    sys.path.insert(0, str(ROOT / "evals"))
    import eval_segformer_surface as ess  # noqa: E402

    # Synthetic report/ (the real one is gitignored, absent on CI). Six frames
    # per room so the surface spearman gate (>= 5 labelled frames) is met.
    report, gold_path = _synthetic_report(tmp_path, n_rooms=2, frames_per_room=6)

    class Args:
        report_dir = report
        gold = gold_path
        html_output = tmp_path / "segformer-surface.html"
        json_output = tmp_path / "segformer-surface-metrics.json"
        demo = True
        backend = "histogram"
        device = None

    payload = ess.run(Args())
    assert payload["experiment"] == "ML-E13"
    assert payload["demo"] is True
    assert Args.html_output.is_file()
    assert Args.json_output.is_file()
    assert "mean_spearman_surface" in payload
