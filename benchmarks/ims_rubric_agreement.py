#!/usr/bin/env python3
"""Score the wear-vs-damage rubric against the IMS sample check-out clerk.

Ground truth: benchmarks/samples/ims-checkout-labels.json — the clerk's own
FWT / CC / TC / MI-LC calls hand-transcribed from the public IMS sample
(benchmarks/samples/ims-checkout.pdf). Each scored entry is sent through the
SAME rubric code path `homeinventory compare` uses
(homeinventory.compare.OpenAIRubric.classify, RUBRIC_PROMPT + strict JSON
schema), text-only. The observation text has the clerk's liability codes
stripped, so the model cannot parrot the answer.

Publishes per-class agreement + confusion counts + measured token cost to
benchmarks/samples/ims-rubric-results.json (also printed as a markdown table
for docs/08-compare.md).

Usage:
    set -a && source .env && set +a       # OPENAI_API_KEY
    python benchmarks/ims_rubric_agreement.py [--model gpt-5.4-mini]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeinventory.compare import OpenAIRubric  # noqa: E402

LABELS = ROOT / "benchmarks" / "samples" / "ims-checkout-labels.json"
RESULTS = ROOT / "benchmarks" / "samples" / "ims-rubric-results.json"

# USD per 1M tokens (June 2026) — same source as benchmarks/cost_estimate.py
PRICE = {"gpt-5.4-mini": (0.75, 4.50)}


def entry_text(entry: dict, tenancy_months: int | None,
               occupancy: str | None) -> str:
    """IMS clerk-table row -> the rubric's user-message shape (mirrors
    compare.change_prompt: item, check-in record, check-out record, context
    values rendered 'not provided' when absent)."""
    lines = [
        f"Item: {entry['item']} (room: {entry['room']})",
        f"Check-in record: {entry['checkin']}",
        f"Check-out record: {entry['observation']}",
        f"Tenancy length: {tenancy_months} months" if tenancy_months
        else "Tenancy length: not provided",
        f"Occupancy: {occupancy}" if occupancy else "Occupancy: not provided",
        "Item age at check-in: not provided",
        "Classify this change.",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gpt-5.4-mini")
    args = ap.parse_args()

    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    ctx = labels["_context"]
    scored = [e for e in labels["entries"] if e.get("clerk_class")]
    excluded = [e for e in labels["entries"] if not e.get("clerk_class")]

    rubric = OpenAIRubric(model=args.model)
    per_entry: list[dict] = []
    confusion: dict[str, Counter] = defaultdict(Counter)
    for e in scored:
        text = entry_text(e, ctx.get("tenancy_months"), ctx.get("occupancy"))
        verdict = rubric.classify(text)
        agree = verdict["classification"] == e["clerk_class"]
        confusion[e["clerk_class"]][verdict["classification"]] += 1
        per_entry.append({
            "id": e["id"], "item": e["item"],
            "clerk_code": e["clerk_code"], "clerk_class": e["clerk_class"],
            "rubric_class": verdict["classification"],
            "agree": agree, "rationale": verdict["rationale"],
        })
        mark = "ok " if agree else "MISS"
        print(f"{mark} {e['id']:>4}  clerk={e['clerk_class']:<24} "
              f"rubric={verdict['classification']:<24} {e['item']}")

    per_class = {}
    for cls, row in sorted(confusion.items()):
        n = sum(row.values())
        agree = row[cls]
        per_class[cls] = {"n": n, "agree": agree,
                          "agreement_pct": round(100.0 * agree / n, 1),
                          "rubric_said": dict(row)}
    total_n = sum(v["n"] for v in per_class.values())
    total_agree = sum(v["agree"] for v in per_class.values())

    usage = rubric.usage
    in_rate, out_rate = PRICE.get(args.model, (None, None))
    cost_usd = (round(usage["prompt_tokens"] / 1e6 * in_rate
                      + usage["completion_tokens"] / 1e6 * out_rate, 4)
                if in_rate else None)

    results = {
        "model": rubric.model,
        "labels": str(LABELS.relative_to(ROOT)),
        "context": ctx,
        "scored_entries": len(scored),
        "excluded_entries": [
            {"id": e["id"], "reason": e.get("exclude_reason")}
            for e in excluded],
        "per_class": per_class,
        "overall_agreement_pct": round(100.0 * total_agree / total_n, 1),
        "usage": usage,
        "cost_usd": cost_usd,
        "price_per_mtok_usd": {"input": in_rate, "output": out_rate},
        "per_entry": per_entry,
    }
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                       encoding="utf-8")

    print("\n| Clerk class | n | rubric agrees | agreement |")
    print("|---|---|---|---|")
    for cls, v in per_class.items():
        print(f"| {cls} | {v['n']} | {v['agree']} | {v['agreement_pct']}% |")
    print(f"| **overall** | {total_n} | {total_agree} | "
          f"{round(100.0 * total_agree / total_n, 1)}% |")
    print(f"\ntokens: {usage['prompt_tokens']} in / "
          f"{usage['completion_tokens']} out; cost: "
          f"${cost_usd if cost_usd is not None else 'n/a (unknown price)'}")
    print(f"results -> {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
