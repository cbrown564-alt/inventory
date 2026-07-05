#!/usr/bin/env python3
"""ML-E12: YOLOE fine-tune probe on InventoryFlex train split (docs/19 §1.4).

Bootstraps pseudo bbox labels from ``train_rooms`` in
``evals/splits/inventoryflex.json``, runs a short YOLOE-seg fine-tune, and
evaluates bbox recall @ IoU 0.5 on held-out ``val_rooms`` gold in
``labels_boxes.json`` (ML-E11).

Pass bar: fine-tuned recall ≥ baseline + 10 pp on val bbox gold.

Artifacts (default):
  ``evals/fixtures/inventoryflex/detect-finetune-eval.json``
  ``evals/fixtures/inventoryflex/detect-finetune-probe.json`` (weights metadata)

Fine-tuned ``.pt`` weights (~28 MB) are written beside the eval JSON when
training runs; they are not committed — see ``weights`` block in probe JSON.

Usage:
    python benchmarks/extract_inventoryflex.py
    python3 evals/eval_finetune_detect.py benchmarks/inventoryflex/capture
    python3 evals/eval_finetune_detect.py CAPTURE --skip-train  # baseline only
    python3 evals/eval_finetune_detect.py --demo -o /tmp/detect-finetune-eval.json

Optional deps: ``pip install ultralytics`` (same stack as ``homeinventory[detect]``).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from homeinventory.det_match import label_matches_gold  # noqa: E402
from homeinventory.detect import (  # noqa: E402
    HOUSEHOLD_VOCAB,
    Detector,
    default_model,
)
from label_boxes import bootstrap_boxes, load_json  # noqa: E402

DEFAULT_CAPTURE = ROOT / "benchmarks" / "inventoryflex" / "capture"
DEFAULT_LABELS = ROOT / "evals" / "fixtures" / "inventoryflex" / "labels.json"
DEFAULT_BOXES = ROOT / "evals/fixtures/inventoryflex/labels_boxes.json"
DEFAULT_SPLIT = ROOT / "evals/splits/inventoryflex.json"
DEFAULT_OUT = ROOT / "evals/fixtures/inventoryflex/detect-finetune-eval.json"
DEFAULT_WEIGHTS_META = (
    ROOT / "evals/fixtures/inventoryflex/detect-finetune-probe.json"
)

PASS_BAR_PP = 10.0
IOU_THRESHOLD = 0.5
MATCH_THRESHOLD = 0.6


def box_iou(a: tuple[int, ...] | list[int], b: tuple[int, ...] | list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


def val_gold_boxes(boxes_doc: dict) -> list[dict]:
    return [
        b for b in boxes_doc.get("boxes", [])
        if not b.get("_example") and b.get("verified")
    ]


def eval_bbox_recall(
        *,
        capture_dir: Path,
        labels: dict,
        gold_boxes: list[dict],
        detector: Detector | None = None,
        yolo_model: Any | None = None,
        conf: float = 0.25,
        iou_threshold: float = IOU_THRESHOLD,
        match_threshold: float = MATCH_THRESHOLD,
) -> dict:
    """Fraction of gold boxes with a matching detection at ``iou_threshold``."""
    if detector is None and yolo_model is None:
        raise ValueError("detector or yolo_model required")

    hits = 0
    per_room: dict[str, dict[str, int]] = {}
    misses: list[dict] = []

    for gb in gold_boxes:
        room = gb["room"]
        photo_path = capture_dir / room / gb["photo"]
        gold_dict = next(
            it for it in labels["rooms"][room]["items"]
            if it["name"] == gb["gold_item"]
        )
        best_iou = 0.0
        best_label: str | None = None

        if detector is not None:
            for det in detector.detect(photo_path):
                if not label_matches_gold(det.label, gold_dict, match_threshold):
                    continue
                best_iou = max(best_iou, box_iou(det.box, gb["box_xyxy"]))
                best_label = det.label
        else:
            results = yolo_model.predict(str(photo_path), conf=conf, verbose=False)
            r = results[0]
            if r.boxes is not None:
                for bx in r.boxes:
                    label = r.names[int(bx.cls[0])]
                    if not label_matches_gold(label, gold_dict, match_threshold):
                        continue
                    box = tuple(int(v) for v in bx.xyxy[0].tolist())
                    iou = box_iou(box, gb["box_xyxy"])
                    if iou > best_iou:
                        best_iou = iou
                        best_label = label

        room_stats = per_room.setdefault(room, {"gold": 0, "hits": 0})
        room_stats["gold"] += 1
        if best_iou >= iou_threshold:
            hits += 1
            room_stats["hits"] += 1
        else:
            misses.append({
                "id": gb["id"],
                "room": room,
                "gold_item": gb["gold_item"],
                "best_iou": round(best_iou, 3),
                "expected_det_label": gb.get("det_label"),
                "best_label": best_label,
            })

    n = len(gold_boxes)
    recall = round(100.0 * hits / n, 1) if n else None
    room_recall = {
        room: round(100.0 * st["hits"] / st["gold"], 1)
        for room, st in per_room.items()
        if st["gold"]
    }
    return {
        "iou_threshold": iou_threshold,
        "match_threshold": match_threshold,
        "conf": conf,
        "n_gold_boxes": n,
        "hits": hits,
        "recall_pct": recall,
        "per_room_recall_pct": room_recall,
        "misses": misses[:25],
        "n_misses": len(misses),
    }


def export_yolo_seg_dataset(
        *,
        work_dir: Path,
        capture_dir: Path,
        train_boxes: list[dict],
        class_names: list[str],
) -> Path:
    """Write YOLO segment labels (rect polygons) for ultralytics training."""
    class_to_id = {c: i for i, c in enumerate(class_names)}
    img_train = work_dir / "images" / "train"
    lbl_train = work_dir / "labels" / "train"
    img_train.mkdir(parents=True, exist_ok=True)
    lbl_train.mkdir(parents=True, exist_ok=True)

    from PIL import Image

    exported = 0
    for box in train_boxes:
        dl = box["det_label"]
        if dl not in class_to_id:
            continue
        src = capture_dir / box["room"] / box["photo"]
        if not src.is_file():
            continue
        dst_name = f"{box['id']}.jpg"
        shutil.copy2(src, img_train / dst_name)
        with Image.open(src) as im:
            w, h = im.size
        x1, y1, x2, y2 = box["box_xyxy"]
        pts = [(x1 / w, y1 / h), (x2 / w, y1 / h), (x2 / w, y2 / h), (x1 / w, y2 / h)]
        seg = " ".join(f"{x:.6f} {y:.6f}" for x, y in pts)
        cid = class_to_id[dl]
        (lbl_train / f"{box['id']}.txt").write_text(f"{cid} {seg}\n", encoding="utf-8")
        exported += 1

    names_lines = "\n".join(f"  {i}: {c}" for i, c in enumerate(class_names))
    data_yaml = work_dir / "data.yaml"
    data_yaml.write_text(
        f"path: {work_dir}\n"
        f"train: images/train\n"
        f"val: images/train\n"
        f"nc: {len(class_names)}\n"
        f"names:\n{names_lines}\n",
        encoding="utf-8",
    )
    if exported == 0:
        raise RuntimeError("no train boxes exported — check capture dir and bootstrap")
    return data_yaml


def run_finetune_probe(
        *,
        data_yaml: Path,
        work_dir: Path,
        epochs: int = 5,
        device: str | None = "cpu",
        imgsz: int = 640,
        batch: int = 4,
) -> Path:
    from ultralytics import YOLOE

    model = YOLOE(default_model())
    model.set_classes(HOUSEHOLD_VOCAB, model.get_text_pe(HOUSEHOLD_VOCAB))
    model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device or "cpu",
        patience=max(20, epochs * 4),
        verbose=False,
        project=str(work_dir / "runs"),
        name="probe",
    )
    best = work_dir / "runs" / "probe" / "weights" / "best.pt"
    if not best.is_file():
        raise RuntimeError(f"fine-tune did not produce weights at {best}")
    return best


def _recommendation(baseline: float | None, finetuned: float | None) -> str:
    if baseline is None or finetuned is None:
        return "incomplete — baseline or fine-tuned eval unavailable"
    delta = round(finetuned - baseline, 1)
    if delta >= PASS_BAR_PP:
        return (
            f"fine-tune candidate — val bbox recall +{delta}pp (≥{PASS_BAR_PP}pp bar); "
            "review AGPL licence before product investment (docs/19 §9 Q1)"
        )
    if delta >= 0:
        return (
            f"keep baseline — fine-tune delta +{delta}pp below +{PASS_BAR_PP}pp bar; "
            "need more train bbox labels or Apache detector path (ML-E18)"
        )
    return (
        f"reject fine-tune — val recall {delta:+.1f}pp vs baseline; "
        f"{37} train pseudo-boxes insufficient for YOLOE probe"
    )


def build_payload(
        *,
        capture_dir: Path,
        baseline: dict,
        finetuned: dict | None,
        train_meta: dict,
        weights_path: Path | None,
        weights_meta_path: Path,
        skip_train: bool,
) -> dict:
    b_rec = baseline.get("recall_pct")
    f_rec = finetuned.get("recall_pct") if finetuned else None
    delta = round(f_rec - b_rec, 1) if b_rec is not None and f_rec is not None else None
    passed = delta is not None and delta >= PASS_BAR_PP

    weights_doc = {
        "experiment": "ML-E12",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_model": default_model(),
        "vocab": HOUSEHOLD_VOCAB,
        "training": train_meta,
        "weights_file": str(weights_path) if weights_path and weights_path.is_file() else None,
        "weights_size_mb": round(weights_path.stat().st_size / 1_048_576, 1)
        if weights_path and weights_path.is_file() else None,
        "note": (
            "Fine-tuned .pt is ~28 MB — not committed. Re-run this script after "
            "extract_inventoryflex to regenerate weights locally."
        ),
        "licence": "AGPL-3.0 (YOLOE/Ultralytics) — eval probe only; see docs/19 §9 Q1",
    }
    weights_meta_path.parent.mkdir(parents=True, exist_ok=True)
    weights_meta_path.write_text(json.dumps(weights_doc, indent=2), encoding="utf-8")

    def _rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(ROOT))
        except ValueError:
            return str(p)

    return {
        "experiment": "ML-E12",
        "date": date.today().isoformat(),
        "capture_dir": _rel(capture_dir),
        "labels_boxes": _rel(DEFAULT_BOXES),
        "split": _rel(DEFAULT_SPLIT),
        "pass_bar_pp": PASS_BAR_PP,
        "iou_threshold": IOU_THRESHOLD,
        "baseline": baseline,
        "finetuned": finetuned,
        "delta_recall_pp": delta,
        "pass": passed,
        "recommendation": _recommendation(b_rec, f_rec),
        "train": train_meta,
        "weights_meta": _rel(weights_meta_path),
        "skip_train": skip_train,
    }


def demo_payload(out: Path, weights_meta: Path) -> dict:
    """Fixture-shaped payload when capture or torch stack is unavailable."""
    baseline = {
        "backend": "yoloe-text",
        "recall_pct": 82.7,
        "n_gold_boxes": 98,
        "hits": 81,
        "demo": True,
    }
    finetuned = {
        "backend": "yoloe-text-finetuned",
        "recall_pct": 65.3,
        "n_gold_boxes": 98,
        "hits": 64,
        "demo": True,
    }
    train_meta = {
        "train_rooms": ["Entrance Hall", "Walk In Wardrobe", "Bedroom", "Balcony"],
        "val_rooms": ["Bathroom", "Reception & Open Plan Kitchen"],
        "n_train_pseudo_boxes": 37,
        "epochs": 5,
        "mode": "demo",
    }
    payload = build_payload(
        capture_dir=DEFAULT_CAPTURE,
        baseline=baseline,
        finetuned=finetuned,
        train_meta=train_meta,
        weights_path=None,
        weights_meta_path=weights_meta,
        skip_train=False,
    )
    payload["demo"] = True
    payload["note"] = "Demo metrics from committed CPU run 2026-07-05; re-run without --demo for live eval."
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def run(args: argparse.Namespace) -> dict:
    if args.demo:
        return demo_payload(args.output.resolve(), args.weights_meta.resolve())

    capture_dir = args.capture_dir.resolve()
    if not capture_dir.is_dir():
        raise SystemExit(
            f"error: capture dir not found: {capture_dir}\n"
            "run: python benchmarks/extract_inventoryflex.py"
        )

    labels = load_json(args.labels.resolve())
    boxes_doc = load_json(args.boxes.resolve())
    split = load_json(args.split.resolve())
    train_rooms = split["train_rooms"]
    val_rooms = split["val_rooms"]

    gold = [b for b in val_gold_boxes(boxes_doc) if b.get("room") in val_rooms]
    if not gold:
        raise SystemExit("error: no verified val-room gold boxes in labels_boxes.json")

    print(f"evaluating baseline YOLOE text on {len(gold)} val gold boxes …", flush=True)
    baseline_det = Detector(conf=args.conf, device=args.device)
    if not baseline_det.available:
        raise SystemExit(
            f"YOLOE unavailable: {getattr(baseline_det, '_load_error', '?')}"
        )
    baseline = eval_bbox_recall(
        capture_dir=capture_dir,
        labels=labels,
        gold_boxes=gold,
        detector=baseline_det,
        conf=args.conf,
        iou_threshold=args.iou,
        match_threshold=args.match_threshold,
    )
    baseline["backend"] = "yoloe-text"
    baseline["model"] = default_model()
    print(f"  baseline recall@{args.iou}: {baseline['recall_pct']}%", flush=True)

    finetuned: dict | None = None
    weights_path: Path | None = None
    train_meta: dict = {
        "train_rooms": train_rooms,
        "val_rooms": val_rooms,
        "bootstrap_match_threshold": args.bootstrap_threshold,
        "bootstrap_min_conf": args.bootstrap_conf,
        "epochs": args.epochs,
        "device": args.device or "cpu",
    }

    if not args.skip_train:
        print(f"bootstrapping train pseudo-labels from {len(train_rooms)} rooms …", flush=True)
        boot_det = Detector(conf=args.bootstrap_conf, device=args.device)
        train_boxes = bootstrap_boxes(
            capture_dir=capture_dir,
            labels=labels,
            rooms=train_rooms,
            detector=boot_det,
            match_threshold=args.bootstrap_threshold,
            min_conf=args.bootstrap_conf,
            labeler="yoloe-bootstrap-train",
            verified=False,
        )
        train_meta["n_train_pseudo_boxes"] = len(train_boxes)
        print(f"  {len(train_boxes)} pseudo boxes", flush=True)

        work_parent = args.work_dir.resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="mle12-"))
        work_dir = work_parent / "yolo-dataset"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)

        data_yaml = export_yolo_seg_dataset(
            work_dir=work_dir,
            capture_dir=capture_dir,
            train_boxes=train_boxes,
            class_names=HOUSEHOLD_VOCAB,
        )
        train_meta["dataset"] = str(work_dir)

        print(f"fine-tuning YOLOE ({args.epochs} epochs, device={args.device or 'cpu'}) …", flush=True)
        best_pt = run_finetune_probe(
            data_yaml=data_yaml,
            work_dir=work_dir,
            epochs=args.epochs,
            device=args.device,
            imgsz=args.imgsz,
            batch=args.batch,
        )

        if args.weights_out:
            weights_path = args.weights_out.resolve()
            weights_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best_pt, weights_path)
        else:
            weights_path = args.output.resolve().parent / "detect-finetune-best.pt"
            shutil.copy2(best_pt, weights_path)
        try:
            train_meta["weights_file"] = str(weights_path.resolve().relative_to(ROOT))
        except ValueError:
            train_meta["weights_file"] = str(weights_path)

        from ultralytics import YOLOE

        ft_model = YOLOE(str(weights_path))
        ft_model.set_classes(HOUSEHOLD_VOCAB, ft_model.get_text_pe(HOUSEHOLD_VOCAB))

        print("evaluating fine-tuned model on val gold …", flush=True)
        finetuned = eval_bbox_recall(
            capture_dir=capture_dir,
            labels=labels,
            gold_boxes=gold,
            yolo_model=ft_model,
            conf=args.conf,
            iou_threshold=args.iou,
            match_threshold=args.match_threshold,
        )
        finetuned["backend"] = "yoloe-text-finetuned"
        finetuned["model"] = str(weights_path)
        print(f"  finetuned recall@{args.iou}: {finetuned['recall_pct']}%", flush=True)

    payload = build_payload(
        capture_dir=capture_dir,
        baseline=baseline,
        finetuned=finetuned,
        train_meta=train_meta,
        weights_path=weights_path,
        weights_meta_path=args.weights_meta.resolve(),
        skip_train=args.skip_train,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture_dir", type=Path, nargs="?", default=DEFAULT_CAPTURE)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--boxes", type=Path, default=DEFAULT_BOXES)
    ap.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--weights-meta", type=Path, default=DEFAULT_WEIGHTS_META)
    ap.add_argument("--weights-out", type=Path, default=None,
                    help="copy fine-tuned best.pt here (default: beside eval JSON)")
    ap.add_argument("--work-dir", type=Path, default=None,
                    help="persistent YOLO dataset + runs dir (default: temp)")
    ap.add_argument("--conf", type=float, default=0.25, help="inference confidence")
    ap.add_argument("--iou", type=float, default=IOU_THRESHOLD)
    ap.add_argument("--match-threshold", type=float, default=MATCH_THRESHOLD)
    ap.add_argument("--bootstrap-threshold", type=float, default=0.65)
    ap.add_argument("--bootstrap-conf", type=float, default=0.15)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--skip-train", action="store_true",
                    help="baseline bbox recall only (no fine-tune)")
    ap.add_argument("--demo", action="store_true",
                    help="write demo JSON without capture or training")
    args = ap.parse_args()

    payload = run(args)
    delta = payload.get("delta_recall_pp")
    print(f"\nwrote {args.output}")
    print(f"wrote {args.weights_meta}")
    print(f"pass: {payload.get('pass')}  delta: {delta:+.1f}pp" if delta is not None
          else f"pass: {payload.get('pass')}  (baseline only)")
    print(f"recommendation: {payload.get('recommendation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
