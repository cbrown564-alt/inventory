"""Probe one local Ollama VLM batch and dump reproducible response metadata.

Example:
    python benchmarks/probe_local.py "Entrance Hall" 0 --model qwen3.5:9b \
        --compact-schema --think false --host http://127.0.0.1:11435
"""
import argparse
import base64
import json
import urllib.request
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeinventory.describe import (LocalBackend, SYSTEM_PROMPT,
                                    _ollama_timing)  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("room")
parser.add_argument("start_idx", type=int)
parser.add_argument("--num-ctx", type=int, default=12288)
parser.add_argument("--num-predict", type=int, default=4096)
parser.add_argument("--model", default="qwen3.5:9b")
parser.add_argument("--host", default="http://127.0.0.1:11434")
parser.add_argument("--compact-schema", action="store_true")
parser.add_argument("--think", choices=["default", "true", "false"],
                    default="default")
args = parser.parse_args()

paths = sorted((Path(__file__).parent / "inventoryflex" / "capture" / args.room).glob("*.jpg"))
batch = paths[args.start_idx:args.start_idx + 6]
# InventoryFlex sources are already 800×600, below the application's 1120px
# local-backend cap. Encode their original JPEG bytes so this probe is runnable
# even when the system Python lacks Pillow.
images = [base64.standard_b64encode(p.read_bytes()).decode() for p in batch]
backend = LocalBackend(model=args.model, host=args.host, num_ctx=args.num_ctx,
                       num_predict=args.num_predict,
                       compact_schema=args.compact_schema)
if args.think != "default":
    backend.think = args.think == "true"
print(f"model: {backend.model}")
print(f"host: {backend.host}")
print(f"{args.room}: photos {args.start_idx}..{args.start_idx + len(batch) - 1}, "
      f"num_ctx={backend.num_ctx}, num_predict={backend.num_predict}")
print(f"compact_schema: {backend.compact_schema}; think: {backend.think}")
photo_ids = [f"P{i:03d}" for i in range(args.start_idx + 1,
                                           args.start_idx + len(batch) + 1)]
id_list = ", ".join(photo_ids)

body_dict = {
    "model": backend.model,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f'These photos all show the room: "{args.room}".\n'
                                    f'The {len(batch)} attached photos are, in order: {id_list}.\n'
                                    "Produce the complete item schedule for everything visible in "
                                    "THESE photos."
                                    + (" Return only name, condition, defects, and photo IDs."
                                       if backend.compact_schema else ""),
         "images": images},
    ],
    "stream": False,
    "format": backend.response_schema,
    "options": {"num_ctx": backend.num_ctx, "num_predict": backend.num_predict,
                "temperature": 0, "repeat_penalty": 1.1},
}
if backend.think is not None:
    body_dict["think"] = backend.think
body = json.dumps(body_dict).encode()
req = urllib.request.Request(f"{backend.host}/api/chat", data=body,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=900) as resp:
    r = json.loads(resp.read().decode("utf-8"))

msg = r.get("message", {})
content = msg.get("content") or ""
print("done_reason:", r.get("done_reason"))

# Timing/throughput — the question this probe exists to answer. A steep
# eval_tok_per_s drop vs a prior run means Ollama offloaded layers to CPU.
for k, v in _ollama_timing(r).items():
    print(f"{k}: {v}")

print("message keys:", list(msg.keys()))
print("thinking len:", len(msg.get("thinking") or ""))
print("content len:", len(content))
print("content head:", content[:200].replace("\n", " "))
try:
    json.loads(content)
    print("content parses as JSON: yes")
except ValueError as e:
    print("content parses as JSON: NO -", e)
