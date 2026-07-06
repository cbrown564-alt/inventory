#!/usr/bin/env python3
"""ML-E18: fine-tune Grounding DINO (Swin-T) on the Open Images V7 household
subset (docs/23 §5, docs/22 §5.1).

Fine-tunes the **official IDEA-Research/grounding-dino-tiny checkpoint**
(Apache-2.0), using the architecture and loss already vendored in HF
``transformers`` (``GroundingDinoForObjectDetection`` — the same class
``evals/gdino_detect.py`` and ``evals/oi_detect.py`` use for inference/eval).

Why HF transformers instead of cloning the standalone ``Open-GroundingDino``
repo: that repo's own model class has different ``state_dict`` key names, so
a checkpoint trained there would **not** load into
``oi_detect.OiPretrainedDetector`` (which does
``AutoModelForZeroShotObjectDetection.from_pretrained(...); load_state_dict``).
It also requires compiling custom CUDA ops (MultiScaleDeformableAttention),
which is fragile on Windows without a configured MSVC toolchain. HF's port is
the *same* official architecture + official pretrained weights, already a
project dependency, and ``GroundingDinoForObjectDetection.forward(..., labels=)``
implements the identical Hungarian-matching + focal/L1/GIoU loss — this is
the lightest integration that is still faithfully "the official approach"
while guaranteeing the checkpoint loads where the eval script expects it.

8 GB VRAM constraint (docs/23 §5): batch 1–2, bf16 autocast, and a capped
image size (default 480/800 shortest/longest edge — GDINO's default 800/1333
is what actually blows the budget, not the absence of gradient checkpointing).
``--grad-checkpointing`` is offered best-effort: as of transformers 5.13,
``GroundingDinoForObjectDetection.supports_gradient_checkpointing`` is
``False`` and the decoder's own internal checkpointing branch has a stale
positional-argument list that crashes against the current decoder-layer
signature — so the public API is a hard no-op here. The flag tries it and
falls back cleanly with a warning; do not rely on it fitting the budget.

Usage — smoke test (no real data required; validates the pipeline):
    uv run python evals/train_gdino_oi.py --smoke-test --device cuda

Usage — real run (needs the FiftyOne OI export downloaded first via
``evals/external/scripts/download_datasets.py open-images``):
    uv run python evals/train_gdino_oi.py evals/external/data/open-images-v7 \\
        --device cuda --epochs 3 --batch-size 2 --grad-accum-steps 4 \\
        --amp-dtype bf16

Optional deps: pip install transformers torch fiftyone (uv pip install -e .[ml])
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from oi_vocab import DEFAULT_OI_WEIGHTS, OPEN_IMAGES_HOUSEHOLD_CLASSES, _norm  # noqa: E402

MODEL_ID = "IDEA-Research/grounding-dino-tiny"

DEFAULT_DATASET_DIR = ROOT / "evals/external/data/open-images-v7"
DEFAULT_WEIGHTS_OUT = ROOT / DEFAULT_OI_WEIGHTS
# Deliberately NOT under open-images-v7/ (that tree is the shared download
# cache — a concurrent `download_datasets.py open-images` run may be writing
# there) and deliberately NOT matching the *.pt glob `find_oi_weights()` scans
# in evals/oi_vocab.py, so a smoke checkpoint can never be silently picked up
# as if it were the real fine-tune.
DEFAULT_SMOKE_WEIGHTS_OUT = (
    ROOT / "evals/external/data/_gdino_oi_smoketest/gdino-oi-household.pt"
)


@dataclass
class Sample:
    image_path: Path
    boxes_xyxy: list[tuple[float, float, float, float]]
    class_ids: list[int]


def build_vocab_prompt(vocab: list[str]) -> str:
    """Grounding DINO expects lower-case phrases separated by '.' — must match
    ``gdino_detect._phrase_prompt`` exactly so train/eval tokenize identically."""
    return ". ".join(v.lower().strip() for v in vocab if v.strip()) + "."


def _gpu_mem() -> dict:
    import torch

    return {
        "alloc_gb": round(torch.cuda.memory_allocated() / 1e9, 2),
        "reserved_gb": round(torch.cuda.memory_reserved() / 1e9, 2),
    }


def _nvidia_smi_free_mb() -> float | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            text=True, timeout=5,
        )
        return float(out.strip().splitlines()[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Synthetic placeholder dataset (used when the real FiftyOne OI export is not
# yet on disk — see docs/23 §5 / ML-E18). Exercises the exact same downstream
# code path (image_processor(images=, annotations=) -> model(..., labels=))
# as the real data loader below; only the source of (image, boxes) differs.
# NOT representative of real detector accuracy — pipeline validation only.
# ---------------------------------------------------------------------------

def make_synthetic_samples(
        out_dir: Path, vocab: list[str], n_images: int = 24, seed: int = 0,
) -> list[Sample]:
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    palette = [(200, 80, 80), (80, 140, 200), (90, 180, 90), (210, 180, 60), (150, 90, 180)]
    samples: list[Sample] = []
    for i in range(n_images):
        w, h = rng.choice([(640, 480), (720, 540), (600, 450)])
        bg = rng.randint(180, 230)
        img = Image.new("RGB", (w, h), color=(bg, bg, bg))
        draw = ImageDraw.Draw(img)
        boxes: list[tuple[float, float, float, float]] = []
        class_ids: list[int] = []
        for _ in range(rng.randint(1, 3)):
            cls_idx = rng.randrange(len(vocab))
            bw, bh = rng.randint(w // 6, w // 3), rng.randint(h // 6, h // 3)
            x1 = rng.randint(0, max(1, w - bw))
            y1 = rng.randint(0, max(1, h - bh))
            x2, y2 = x1 + bw, y1 + bh
            draw.rectangle([x1, y1, x2, y2], fill=palette[cls_idx % len(palette)], outline=(0, 0, 0))
            boxes.append((float(x1), float(y1), float(x2), float(y2)))
            class_ids.append(cls_idx)
        path = out_dir / f"synth_{i:03d}.jpg"
        img.save(path, quality=85)
        samples.append(Sample(image_path=path, boxes_xyxy=boxes, class_ids=class_ids))
    return samples


# ---------------------------------------------------------------------------
# Real data: bridge the FiftyOne OI household export (already downloaded via
# evals/external/scripts/download_datasets.py open-images) to Sample objects.
# Uses FiftyOne's own Python API (already a project dep) rather than a COCO
# export round-trip — `foz.load_zoo_dataset(...)` is idempotent against an
# existing local cache (no re-download) and gives typed Detections directly.
# ---------------------------------------------------------------------------

def load_fiftyone_samples(
        dataset_dir: Path, vocab: list[str], max_samples: int | None,
) -> list[Sample]:
    try:
        import fiftyone.zoo as foz
    except ImportError as exc:
        raise RuntimeError(
            "fiftyone not installed — pip install fiftyone (uv pip install -e .[ml])"
        ) from exc

    vocab_index = {_norm(v): i for i, v in enumerate(vocab)}
    dataset = foz.load_zoo_dataset(
        "open-images-v7",
        split="train",
        label_types=["detections"],
        classes=list(OPEN_IMAGES_HOUSEHOLD_CLASSES),
        max_samples=max_samples,
        dataset_dir=str(dataset_dir),
    )

    samples: list[Sample] = []
    for fo_sample in dataset.iter_samples(progress=False):
        det_field = getattr(fo_sample, "detections", None)
        if det_field is None or not det_field.detections:
            continue
        meta = fo_sample.metadata
        w = getattr(meta, "width", None) if meta else None
        h = getattr(meta, "height", None) if meta else None
        if not w or not h:
            from PIL import Image
            with Image.open(fo_sample.filepath) as im:
                w, h = im.size
        boxes: list[tuple[float, float, float, float]] = []
        class_ids: list[int] = []
        for det in det_field.detections:
            idx = vocab_index.get(_norm(det.label))
            if idx is None:
                continue
            x, y, bw, bh = det.bounding_box
            x1, y1 = x * w, y * h
            x2, y2 = (x + bw) * w, (y + bh) * h
            boxes.append((x1, y1, x2, y2))
            class_ids.append(idx)
        if boxes:
            samples.append(Sample(image_path=Path(fo_sample.filepath), boxes_xyxy=boxes, class_ids=class_ids))
    return samples


# ---------------------------------------------------------------------------
# Checkpoint round-trip verification — the "done" contract from
# evals/oi_detect.OiPretrainedDetector: torch.load -> (optional state_dict
# unwrap) -> model.load_state_dict(strict=False). Exercises that exact class.
# ---------------------------------------------------------------------------

def verify_checkpoint(weights_path: Path, model_id: str) -> dict:
    import torch
    from transformers import AutoModelForZeroShotObjectDetection

    fresh = AutoModelForZeroShotObjectDetection.from_pretrained(model_id)
    state = torch.load(weights_path, map_location="cpu", weights_only=False)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    missing, unexpected = fresh.load_state_dict(state, strict=False)

    from oi_detect import OiPretrainedDetector  # noqa: E402  (evals/ on sys.path)

    det = OiPretrainedDetector(weights_path=str(weights_path), device="cpu", model_id=model_id)
    det._load()
    return {
        "strict_load_missing_keys": len(missing),
        "strict_load_unexpected_keys": len(unexpected),
        "state_dict_clean": not missing and not unexpected,
        "oi_pretrained_detector_available": det.available,
        "oi_pretrained_detector_error": det._load_error,
    }


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def run_training(args: argparse.Namespace) -> dict:
    import torch
    from PIL import Image
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    vocab = list(OPEN_IMAGES_HOUSEHOLD_CLASSES)
    text_prompt = build_vocab_prompt(vocab)

    print(f"loading {args.model_id} on {device} ...", flush=True)
    processor = AutoProcessor.from_pretrained(args.model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(args.model_id).to(device)
    model.train()

    grad_ckpt_status = "disabled"
    if args.grad_checkpointing:
        try:
            model.gradient_checkpointing_enable()
            grad_ckpt_status = "enabled"
        except Exception as exc:
            grad_ckpt_status = (
                f"unsupported on this transformers build ({exc}); continuing without it "
                "— see module docstring"
            )
            print(f"warning: gradient checkpointing unavailable: {exc}", file=sys.stderr)

    if args.smoke_test:
        synth_dir = Path(tempfile.mkdtemp(prefix="mle18-smoke-"))
        samples = make_synthetic_samples(synth_dir, vocab, n_images=args.smoke_images, seed=args.seed)
        dataset_source = {"kind": "synthetic-placeholder", "n_images": len(samples), "dir": str(synth_dir)}
        print(f"[smoke] generated {len(samples)} synthetic placeholder images at {synth_dir}", flush=True)
    else:
        samples = load_fiftyone_samples(args.dataset_dir, vocab, args.max_samples)
        dataset_source = {"kind": "fiftyone-open-images-v7", "n_images": len(samples), "dir": str(args.dataset_dir)}
        if not samples:
            raise SystemExit(
                f"error: no OI household samples found under {args.dataset_dir} — run "
                "evals/external/scripts/download_datasets.py open-images first"
            )

    rng = random.Random(args.seed)
    rng.shuffle(samples)

    image_processor = processor.image_processor
    tokenizer = processor.tokenizer
    size = {"shortest_edge": args.image_shortest_edge, "longest_edge": args.image_longest_edge}

    amp_enabled = args.amp_dtype != "off" and device == "cuda"
    amp_dtype = {"bf16": torch.bfloat16, "fp16": torch.float16}.get(args.amp_dtype, torch.bfloat16)
    use_scaler = amp_enabled and args.amp_dtype == "fp16"
    scaler = torch.amp.GradScaler("cuda", enabled=use_scaler) if device == "cuda" else None

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    tok = tokenizer([text_prompt], return_tensors="pt", padding=True)
    input_ids_1 = tok["input_ids"].to(device)
    token_type_ids_1 = tok.get("token_type_ids")
    if token_type_ids_1 is not None:
        token_type_ids_1 = token_type_ids_1.to(device)
    attention_mask_1 = tok["attention_mask"].to(device)

    def batch_text(bsz: int):
        return (
            input_ids_1.repeat(bsz, 1),
            None if token_type_ids_1 is None else token_type_ids_1.repeat(bsz, 1),
            attention_mask_1.repeat(bsz, 1),
        )

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    vram_before = _gpu_mem() if device == "cuda" else None

    step = 0
    accum = 0
    losses: list[float] = []
    step_times: list[float] = []
    opt.zero_grad(set_to_none=True)

    done = False
    for epoch in range(args.epochs):
        if done:
            break
        for i in range(0, len(samples), args.batch_size):
            if args.max_steps is not None and step >= args.max_steps:
                done = True
                break
            batch = samples[i:i + args.batch_size]
            if not batch:
                continue
            imgs = [Image.open(s.image_path).convert("RGB") for s in batch]
            coco_anns = []
            for j, s in enumerate(batch):
                anns = [
                    {
                        "image_id": j,
                        "category_id": cid,
                        "bbox": [x1, y1, x2 - x1, y2 - y1],
                        "area": (x2 - x1) * (y2 - y1),
                        "iscrowd": 0,
                    }
                    for (x1, y1, x2, y2), cid in zip(s.boxes_xyxy, s.class_ids)
                ]
                coco_anns.append({"image_id": j, "annotations": anns})

            t0 = time.time()
            enc = image_processor(images=imgs, annotations=coco_anns, size=size, return_tensors="pt")
            pixel_values = enc["pixel_values"].to(device)
            pixel_mask = enc.get("pixel_mask")
            if pixel_mask is not None:
                pixel_mask = pixel_mask.to(device)
            labels = [{k: v.to(device) for k, v in lab.items()} for lab in enc["labels"]]
            input_ids, token_type_ids, attention_mask = batch_text(len(batch))

            with torch.autocast(device_type=device, dtype=amp_dtype, enabled=amp_enabled):
                out = model(
                    pixel_values=pixel_values,
                    pixel_mask=pixel_mask,
                    input_ids=input_ids,
                    token_type_ids=token_type_ids,
                    attention_mask=attention_mask,
                    labels=labels,
                )
                step_loss = out.loss / args.grad_accum_steps

            if use_scaler:
                scaler.scale(step_loss).backward()
            else:
                step_loss.backward()
            accum += 1

            if accum >= args.grad_accum_steps:
                if use_scaler:
                    scaler.step(opt)
                    scaler.update()
                else:
                    opt.step()
                opt.zero_grad(set_to_none=True)
                accum = 0

            if device == "cuda":
                torch.cuda.synchronize()
            dt = time.time() - t0
            step_times.append(dt)
            losses.append(float(out.loss.item()))
            if step % args.log_every == 0:
                mem = _gpu_mem() if device == "cuda" else {}
                print(f"step {step} epoch {epoch} loss {losses[-1]:.3f} dt {dt:.2f}s {mem}", flush=True)
            step += 1

    if accum > 0:
        if use_scaler:
            scaler.step(opt)
            scaler.update()
        else:
            opt.step()
        opt.zero_grad(set_to_none=True)

    vram_after = _gpu_mem() if device == "cuda" else None
    peak_gb = round(torch.cuda.max_memory_allocated() / 1e9, 2) if device == "cuda" else None

    weights_out = args.weights_out
    weights_out.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    torch.save(model.state_dict(), weights_out)

    verification = verify_checkpoint(weights_out, args.model_id)

    return {
        "experiment": "ML-E18",
        "model_id": args.model_id,
        "device": device,
        "vocab_size": len(vocab),
        "vocab": vocab,
        "dataset_source": dataset_source,
        "training_args": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "grad_accum_steps": args.grad_accum_steps,
            "effective_batch_size": args.batch_size * args.grad_accum_steps,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "amp_dtype": args.amp_dtype if amp_enabled else "off",
            "gradient_checkpointing": grad_ckpt_status,
            "image_size": size,
            "max_steps": args.max_steps,
            "seed": args.seed,
        },
        "steps_run": step,
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "loss_history": losses,
        "sec_per_step_mean": round(sum(step_times) / len(step_times), 3) if step_times else None,
        "vram_before": vram_before,
        "vram_after": vram_after,
        "vram_peak_allocated_gb": peak_gb,
        "weights_file": str(weights_out),
        "weights_size_mb": round(weights_out.stat().st_size / 1_048_576, 1),
        "checkpoint_verification": verification,
        "smoke_test": args.smoke_test,
        "licence": "Apache-2.0 (IDEA-Research/grounding-dino-tiny base + HF transformers port)",
        "note": (
            "SMOKE-TEST checkpoint — trained on synthetic placeholder images for a "
            "handful of steps; NOT a real detector. Re-run without --smoke-test "
            "against the real FiftyOne OI export for the actual fine-tune."
        ) if args.smoke_test else (
            "Full fine-tune run — see docs/23 §5 ML-E18 for the eval + comparison step."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset_dir", type=Path, nargs="?", default=DEFAULT_DATASET_DIR,
                    help="FiftyOne OI household export dir (ignored with --smoke-test)")
    ap.add_argument("--weights-out", type=Path, default=None,
                    help="default: evals/oi_vocab.DEFAULT_OI_WEIGHTS (or the smoketest "
                         "path under --smoke-test)")
    ap.add_argument("--meta-out", type=Path, default=None,
                    help="default: <weights-out>.meta.json")
    ap.add_argument("--model-id", default=MODEL_ID)
    ap.add_argument("--device", default=None, help="default: cuda if available else cpu")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--max-samples", type=int, default=None, help="cap OI training images (real run)")
    ap.add_argument("--max-steps", type=int, default=None, help="hard cap on optimizer micro-steps")
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--grad-accum-steps", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--amp-dtype", choices=["bf16", "fp16", "off"], default="bf16")
    ap.add_argument("--grad-checkpointing", action="store_true",
                    help="best-effort; a no-op fallback on this GDINO HF port (see docstring)")
    ap.add_argument("--image-shortest-edge", type=int, default=480)
    ap.add_argument("--image-longest-edge", type=int, default=800)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--log-every", type=int, default=1)
    ap.add_argument("--smoke-test", action="store_true",
                    help="tiny synthetic placeholder set + a few steps; validates the "
                         "pipeline without the real OI download")
    ap.add_argument("--smoke-images", type=int, default=24)
    args = ap.parse_args()

    if args.weights_out is None:
        args.weights_out = DEFAULT_SMOKE_WEIGHTS_OUT if args.smoke_test else DEFAULT_WEIGHTS_OUT
    if args.meta_out is None:
        args.meta_out = args.weights_out.with_suffix(".meta.json")
    if args.max_steps is None and args.smoke_test:
        args.max_steps = 8

    free_before = _nvidia_smi_free_mb()
    if free_before is not None:
        print(f"nvidia-smi free VRAM before: {free_before:.0f} MiB", flush=True)

    result = run_training(args)
    result["nvidia_smi_free_mb_before"] = free_before
    result["nvidia_smi_free_mb_after"] = _nvidia_smi_free_mb()

    args.meta_out.parent.mkdir(parents=True, exist_ok=True)
    args.meta_out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\nwrote checkpoint: {result['weights_file']} ({result['weights_size_mb']} MB)")
    print(f"wrote metadata: {args.meta_out}")
    if result["loss_first"] is not None:
        print(f"loss: {result['loss_first']:.3f} -> {result['loss_last']:.3f} "
              f"over {result['steps_run']} steps "
              f"({result['sec_per_step_mean']}s/step mean)")
    print(f"checkpoint verification: {json.dumps(result['checkpoint_verification'])}")
    if result["nvidia_smi_free_mb_after"] is not None:
        print(f"nvidia-smi free VRAM after: {result['nvidia_smi_free_mb_after']:.0f} MiB")

    return 0 if result["checkpoint_verification"].get("oi_pretrained_detector_available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
