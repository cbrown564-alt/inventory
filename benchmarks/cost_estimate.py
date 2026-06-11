"""Reconstruct what the two benchmark runs cost.

- claude: replays the exact per-room request through the free
  messages.count_tokens endpoint -> exact input tokens. Output tokens are
  estimated from the returned JSON (chars/4).
- gpt-5.4-mini: re-sends ONE small room (Balcony, 6 photos) and reads the real
  `usage` block, deriving per-image input tokens and the reasoning-token
  multiplier; scales both to the full run.

Usage: python benchmarks/cost_estimate.py
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeinventory.describe import (  # noqa: E402
    ITEM_SCHEMA, SYSTEM_PROMPT, _encode_image,
)

ROOT = Path(__file__).parent / "inventoryflex"
CAPTURE = ROOT / "capture"

PRICE = {  # USD per 1M tokens (June 2026)
    "claude-opus-4-8": (5.00, 25.00),
    "gpt-5.4-mini": (0.75, 4.50),
}

rooms = {d.name: sorted(d.glob("*.jpg")) for d in sorted(CAPTURE.iterdir()) if d.is_dir()}


def build_content(paths, kind):
    content = []
    for i, p in enumerate(paths):
        media_type, data = _encode_image(p)
        content.append({"type": "text", "text": f"Photo P{i:03d}:"})
        if kind == "anthropic":
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": data}})
        else:
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{media_type};base64,{data}"}})
    content.append({"type": "text", "text": (
        'These photos all show the room: "X".\n'
        "Produce the complete item schedule for this room.")})
    return content


def output_chars(inv_path):
    """Approximate size of the raw model output: room summaries + item fields."""
    inv = json.load(open(inv_path, encoding="utf-8"))
    n = 0
    for r in inv["rooms"]:
        n += len(json.dumps({"room_summary": r.get("summary", "")}))
        for it in r["items"]:
            n += len(json.dumps({k: it.get(k) for k in (
                "name", "category", "description", "condition", "cleanliness",
                "defects", "quantity", "est_value_band", "photo_ids", "confidence")}))
    return n


# ---- claude: exact input tokens via free count_tokens ----------------------
import anthropic  # noqa: E402

client = anthropic.Anthropic()
claude_in = 0
for room, paths in rooms.items():
    r = client.messages.count_tokens(
        model="claude-opus-4-8",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_content(paths, "anthropic")}],
    )
    print(f"claude input  {room}: {r.input_tokens:,} tokens ({len(paths)} photos)")
    claude_in += r.input_tokens

claude_out = output_chars(ROOT / "report-claude" / "inventory.json") // 4
ci, co = PRICE["claude-opus-4-8"]
claude_cost = claude_in / 1e6 * ci + claude_out / 1e6 * co
print(f"\nclaude-opus-4-8: input {claude_in:,} + output ~{claude_out:,} tokens"
      f" -> ${claude_cost:.2f}")

# ---- gpt-5.4-mini: replay smallest room, read usage, scale -----------------
import os  # noqa: E402

balcony = rooms["Balcony"]
payload = {
    "model": "gpt-5.4-mini",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_content(balcony, "openai")},
    ],
    "response_format": {"type": "json_schema", "json_schema": {
        "name": "inventory_room", "strict": True, "schema": ITEM_SCHEMA}},
}
req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
with urllib.request.urlopen(req, timeout=300) as resp:
    r = json.loads(resp.read().decode())
u = r["usage"]
visible = len(r["choices"][0]["message"]["content"])
print(f"\ngpt-5.4-mini Balcony replay usage: {json.dumps(u)}")

# split Balcony prompt into text vs image tokens: text ~= chars/4
text_chars = len(SYSTEM_PROMPT) + sum(
    len(c["text"]) for c in payload["messages"][1]["content"] if c["type"] == "text")
text_tok = text_chars // 4
img_tok = (u["prompt_tokens"] - text_tok) / len(balcony)
print(f"  -> ~{img_tok:.0f} input tokens per 800x600 image")

n_photos = sum(len(p) for p in rooms.values())
gpt_in = round(text_tok_total := 0)
gpt_in = 0
for room, paths in rooms.items():
    room_text = (len(SYSTEM_PROMPT) + sum(len(f"Photo P{i:03d}:") for i in range(len(paths))) + 80) // 4
    gpt_in += room_text + round(img_tok * len(paths))

# output: visible JSON chars/4, scaled by the observed total/visible ratio
# (captures hidden reasoning tokens, billed as output)
ratio = u["completion_tokens"] / max(visible // 4, 1)
gpt_visible_out = output_chars(ROOT / "report-gpt54mini" / "inventory.json") // 4
gpt_out = round(gpt_visible_out * ratio)
gi, go = PRICE["gpt-5.4-mini"]
gpt_cost = gpt_in / 1e6 * gi + gpt_out / 1e6 * go
print(f"gpt-5.4-mini: input ~{gpt_in:,} + output ~{gpt_out:,} tokens "
      f"(reasoning ratio {ratio:.2f}) -> ${gpt_cost:.2f}")

print(f"\nratio: claude is {claude_cost / gpt_cost:.1f}x the cost of gpt-5.4-mini")
