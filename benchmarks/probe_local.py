"""Probe the Ollama local backend with one batch and dump response metadata.

Usage: python benchmarks/probe_local.py <room> <start_idx> [num_ctx]
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeinventory.describe import ITEM_SCHEMA, SYSTEM_PROMPT, _encode_image  # noqa: E402

room = sys.argv[1]
start = int(sys.argv[2])
num_ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 16384

paths = sorted((Path(__file__).parent / "inventoryflex" / "capture" / room).glob("*.jpg"))
batch = paths[start:start + 6]
images = [_encode_image(p, max_dim=1120)[1] for p in batch]
print(f"{room}: photos {start}..{start+len(batch)-1}, num_ctx={num_ctx}")

body = json.dumps({
    "model": "qwen3.5:9b",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f'Room: "{room}". Produce the complete item '
                                    "schedule for everything visible in THESE photos.",
         "images": images},
    ],
    "stream": False,
    "format": ITEM_SCHEMA,
    "options": {"num_ctx": num_ctx, "temperature": 0},
}).encode()
req = urllib.request.Request("http://localhost:11434/api/chat", data=body,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=900) as resp:
    r = json.loads(resp.read().decode("utf-8"))

msg = r.get("message", {})
content = msg.get("content") or ""
print("done_reason:", r.get("done_reason"))
print("prompt_eval_count:", r.get("prompt_eval_count"), " eval_count:", r.get("eval_count"))
print("message keys:", list(msg.keys()))
print("thinking len:", len(msg.get("thinking") or ""))
print("content len:", len(content))
print("content head:", content[:200].replace("\n", " "))
try:
    json.loads(content)
    print("content parses as JSON: yes")
except ValueError as e:
    print("content parses as JSON: NO -", e)
