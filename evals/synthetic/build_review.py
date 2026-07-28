#!/usr/bin/env python3
"""Build a static review/contact sheet from tasks and review records."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET


def build(dataset_dir: Path, output: Path) -> None:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    split_by_scenario = {}
    for split_path in sorted((dataset_dir / "splits").glob("*.json")):
        split = json.loads(split_path.read_text(encoding="utf-8"))
        for scenario_id in split["scenario_ids"]:
            split_by_scenario[scenario_id] = split["split"]
    cards = []
    for row in rows:
        provider_id = row["task_id"].split(".")[1]
        review_path = (
            dataset_dir
            / "reviews"
            / f"{row['scenario_id']}.{provider_id}.json"
        )
        review = (
            json.loads(review_path.read_text(encoding="utf-8"))
            if review_path.is_file()
            else {}
        )
        pass_a_frame = next(
            (
                frame
                for frame in review.get("pass_a", {}).get("frames", [])
                if frame.get("frame_id") == row["view_id"]
            ),
            {},
        )
        visible_claims = [
            claim["canonical_name"]
            for claim in review.get("pass_b", {}).get("claims", [])
            if row["view_id"] in claim.get("evidence_frame_ids", [])
        ]
        visible_negatives = [
            negative["wording"]
            for negative in review.get("pass_b", {}).get(
                "negative_controls", []
            )
            if row["view_id"] in negative.get("evidence_frame_ids", [])
        ]
        requested = [
            item["name"]
            for item in pass_a_frame.get("requested_evidence", [])
        ]
        split_name = split_by_scenario.get(row["scenario_id"], "unassigned")
        image = dataset_dir / row["output_path"]
        if image.exists():
            src = Path("..").joinpath(row["output_path"]).as_posix() if output.parent == dataset_dir / "reports" else image.as_uri()
            media = f'<img src="{html.escape(src)}" alt="{html.escape(row["task_id"])}">'
        else:
            label = ("Generator failed after 2 attempts"
                     if row["status"] == "generator_failed" else "Generation pending")
            media = f'<div class="missing">{html.escape(label)}</div>'
        cards.append(f'''<article data-split="{html.escape(split_name)}" data-status="{html.escape(row["status"])}">
          {media}
          <div class="body"><h2>{html.escape(row["scenario_id"])} · {html.escape(row["view_id"])}</h2>
          <p><span class="badge">{html.escape(split_name)}</span> {html.escape(row["provider"])} / {html.escape(row["model_display_name"])}</p>
          <p><strong>Status:</strong> {html.escape(row["status"])}</p>
          <details><summary>Requested manifest ({len(requested)})</summary><p>{html.escape(", ".join(requested) or "No Pass A manifest yet")}</p></details>
          <details><summary>Observed labels ({len(visible_claims)})</summary><p>{html.escape(", ".join(visible_claims) or "Not reviewed")}</p></details>
          <details><summary>Verified negatives ({len(visible_negatives)})</summary><p>{html.escape("; ".join(visible_negatives) or "Not reviewed")}</p></details>
          <details><summary>Exact prompt</summary><p>{html.escape(row["exact_prompt"])}</p></details></div>
        </article>''')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Synthetic room evaluation review</title>
<style>body{{font:15px system-ui;margin:0;background:#f4f1ea;color:#18221d}}header{{padding:32px 4vw;position:sticky;top:0;background:#f4f1eaf2;backdrop-filter:blur(10px);z-index:2}}.filters{{display:flex;gap:8px;flex-wrap:wrap}}button{{border:1px solid #aaa;border-radius:999px;background:white;padding:7px 12px;cursor:pointer}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px;padding:20px 4vw 48px}}article{{background:white;border:1px solid #d8d4c9;border-radius:14px;overflow:hidden}}article[hidden]{{display:none}}img,.missing{{width:100%;aspect-ratio:3/2;object-fit:cover;background:#dfddd7}}.missing{{display:grid;place-items:center;color:#6d716e}}.body{{padding:16px}}.badge{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;background:#e7eee9;border-radius:999px;padding:3px 7px}}h1{{margin:0 0 8px}}h2{{font-size:17px;margin:0}}p{{line-height:1.45}}details p{{font-size:13px}}</style></head>
<body><header><h1>Synthetic room evaluation review</h1><p>Requested content is not gold. Compare the image, Pass A manifest and Pass B observed labels; accept only visible evidence.</p><div class="filters"><button data-filter="all">All</button><button data-filter="development">Development</button><button data-filter="validation">Validation</button><button data-filter="sealed">Sealed</button><button data-filter="review_pending">Needs Pass A</button><button data-filter="pending">Ungenerated</button><button data-filter="generator_failed">Generator failed</button></div></header><main>{''.join(cards)}</main><script>for(const b of document.querySelectorAll("button[data-filter]"))b.onclick=()=>{{const f=b.dataset.filter;for(const c of document.querySelectorAll("article"))c.hidden=!(f==="all"||c.dataset.split===f||c.dataset.status===f)}};</script></body></html>''', encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.dataset_dir / "reports/contact-sheet.html"
    build(args.dataset_dir, output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
