#!/usr/bin/env python3
"""Build a static review/contact sheet from tasks and review records."""

from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET


def build(dataset_dir: Path, output: Path) -> None:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    cards = []
    for row in rows:
        image = dataset_dir / row["output_path"]
        if image.exists():
            src = Path("..").joinpath(row["output_path"]).as_posix() if output.parent == dataset_dir / "reports" else image.as_uri()
            media = f'<img src="{html.escape(src)}" alt="{html.escape(row["task_id"])}">'
        else:
            label = ("Generator failed after 2 attempts"
                     if row["status"] == "generator_failed" else "Generation pending")
            media = f'<div class="missing">{html.escape(label)}</div>'
        cards.append(f'''<article>
          {media}
          <div class="body"><h2>{html.escape(row["scenario_id"])} · {html.escape(row["view_id"])}</h2>
          <p>{html.escape(row["provider"])} / {html.escape(row["model_display_name"])}</p>
          <p><strong>Status:</strong> {html.escape(row["status"])}</p>
          <details><summary>Exact prompt</summary><p>{html.escape(row["exact_prompt"])}</p></details></div>
        </article>''')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Synthetic room slice review</title>
<style>body{{font:15px system-ui;margin:0;background:#f4f1ea;color:#18221d}}header{{padding:32px 4vw}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px;padding:0 4vw 48px}}article{{background:white;border:1px solid #d8d4c9;border-radius:14px;overflow:hidden}}img,.missing{{width:100%;aspect-ratio:3/2;object-fit:cover;background:#dfddd7}}.missing{{display:grid;place-items:center;color:#6d716e}}.body{{padding:16px}}h1{{margin:0 0 8px}}h2{{font-size:17px;margin:0}}p{{line-height:1.45}}details p{{font-size:13px}}</style></head>
<body><header><h1>Representative synthetic room slice</h1><p>Intended prompts are not gold. Accept and label only visible evidence through both review passes.</p></header><main>{''.join(cards)}</main></body></html>''', encoding="utf-8")


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
