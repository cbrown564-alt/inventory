#!/usr/bin/env python3
"""Optional ONNX export stub for ML-E6 linear IQA weights (docs/19).

The shipped reranker is a tiny dot-product on classical features — ONNX is
only needed if we embed it in a non-Python runtime. This stub documents the
export path; run after ``train_iqa_linear.py``.

Usage:
    uv run python evals/export_onnx.py \\
        evals/fixtures/own-property/iqa-linear-weights.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = (
    ROOT / "evals" / "fixtures" / "own-property" / "iqa-linear-weights.json"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("weights", type=Path, nargs="?", default=DEFAULT_WEIGHTS)
    ap.add_argument("-o", "--output", type=Path,
                    default=ROOT / "evals" / "fixtures" / "own-property"
                    / "iqa-linear.onnx")
    args = ap.parse_args()

    weights_path = args.weights.resolve()
    if not weights_path.is_file():
        print(f"missing {weights_path}", file=sys.stderr)
        return 1

    data = json.loads(weights_path.read_text(encoding="utf-8"))
    names = data["features"]
    w = data["weights"]
    n = len(names)

    try:
        import numpy as np
        import onnx
        from onnx import helper, numpy_helper
    except ImportError:
        print("ONNX export requires: pip install onnx numpy", file=sys.stderr)
        print(f"Would export {n}-feature linear model to {args.output}")
        print(f"  features: {names}")
        print(f"  weights:  {w}")
        return 2

    inp = helper.make_tensor_value_info(
        "features", onnx.TensorProto.FLOAT, [n])
    out = helper.make_tensor_value_info(
        "score", onnx.TensorProto.FLOAT, [1])
    w_init = numpy_helper.from_array(
        np.array(w, dtype=np.float32), name="W")
    model = helper.make_model(
        helper.make_graph(
            nodes=[
                helper.make_node("Mul", ["features", "W"], ["mul"]),
                helper.make_node("ReduceSum", ["mul"], ["score"], axes=[0],
                                 keepdims=0),
            ],
            name="linear_iqa",
            inputs=[inp],
            outputs=[out],
            initializer=[w_init],
        ),
        opset_imports=[helper.make_opsetid("", 13)],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    print(f"wrote {args.output} ({n} inputs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
