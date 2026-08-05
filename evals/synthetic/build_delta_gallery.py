#!/usr/bin/env python3
"""Build the owner adjudication gallery for Phase 3.5 delta pairs.

docs/31 requires the owner to adjudicate all three probe pairs. Adjudicating a
delta pair means answering a question the static Pass A gallery never asks:
not "is this frame acceptable" but "is anything different here that nobody
enumerated". That is a comparison, so the two frames have to sit side by side
at the same size, and the enumerated changes have to be readable next to them
— otherwise the reviewer is holding the gold in their head while scanning.

The gallery reports the two independent AI reviews when they exist, but shows
the pair regardless. Probe images are calibration evidence, not scored data.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from html import escape
from pathlib import Path
from typing import Any

from evals.synthetic.build_delta_tasks import DELTA_VIEWS, load_specs
from evals.synthetic.build_pass_a_gallery import GALLERY_CSS
from evals.synthetic.build_tasks import DEFAULT_DATASET

EXTRA_CSS = r"""
.wrap { max-width: 1180px; margin: 0 auto; padding: 32px 20px 80px; }
h1 { font: 600 26px/1.2 var(--serif); margin: 0 0 6px; }
.lede { color: var(--muted); margin: 0 0 28px; max-width: 62ch; }
.pair { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
        box-shadow: var(--shadow); padding: 20px; margin: 0 0 28px; }
.pair > header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
                 margin-bottom: 4px; }
.pair h2 { font: 600 18px/1.3 var(--serif); margin: 0; }
.room { color: var(--muted); }
.verdict { margin-left: auto; font-weight: 600; font-size: 12px; letter-spacing: .06em;
           text-transform: uppercase; padding: 4px 10px; border-radius: 999px;
           border: 1px solid var(--line); }
.verdict.accept { color: var(--ok); border-color: rgba(29,111,76,.35); }
.verdict.reject { color: var(--bad); border-color: rgba(163,49,42,.35); }
.verdict.escalate, .verdict.unreviewed { color: var(--warn); border-color: rgba(138,106,31,.35); }
.basis { color: var(--muted); margin: 2px 0 18px; }
.view { margin: 22px 0 0; }
.view h3 { font: 600 12px/1 var(--sans); letter-spacing: .08em; text-transform: uppercase;
           color: var(--muted); margin: 0 0 10px; }
.frames { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.frame figcaption { font-size: 12px; color: var(--muted); margin: 0 0 6px; }
.frame img { width: 100%; height: auto; display: block; border-radius: 8px;
             background: var(--media); border: 1px solid var(--line); }
.changes { margin: 16px 0 0; padding: 14px 16px; background: var(--panel-muted);
           border-radius: 9px; }
.changes h3 { font: 600 12px/1 var(--sans); letter-spacing: .08em; text-transform: uppercase;
              color: var(--muted); margin: 0 0 10px; }
.changes ol, .changes ul { margin: 0; padding-left: 20px; }
.changes li { margin: 0 0 6px; }
.kind { font-variant: all-small-caps; letter-spacing: .04em; color: var(--brass-deep);
        font-weight: 600; }
.immaterial { color: var(--muted); }
.tag { font-size: 11px; border: 1px solid var(--line); border-radius: 999px;
       padding: 1px 8px; margin-left: 6px; color: var(--muted); }
.drift { margin-top: 14px; padding: 12px 16px; border-radius: 9px;
         background: rgba(163,49,42,.06); border: 1px solid rgba(163,49,42,.25); }
.drift h3 { color: var(--bad); }
@media (max-width: 820px) { .frames { grid-template-columns: 1fr; } }
"""


def _rel(path: Path, output: Path) -> str:
    return Path(os.path.relpath(path.resolve(), output.parent.resolve())).as_posix()


def _reviews(review_path: Path | None) -> dict[str, dict[str, Any]]:
    if not review_path or not review_path.is_file():
        return {}
    report = json.loads(review_path.read_text(encoding="utf-8"))
    return {pair["delta_id"]: pair for pair in report.get("pairs", [])}


def build(
    dataset_dir: Path,
    output: Path,
    review_path: Path | None = None,
    reviewed_only: bool = False,
) -> Path:
    with (dataset_dir / "delta_tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    specs = {spec["id"]: (spec, parent) for spec, parent in load_specs(dataset_dir)}
    reviews = _reviews(review_path)

    by_delta: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        by_delta.setdefault(row["delta_id"], {})[row["view_id"]] = row
    if reviewed_only:
        by_delta = {delta_id: views for delta_id, views in by_delta.items()
                    if delta_id in reviews}

    sections: list[str] = []
    for delta_id in sorted(by_delta):
        spec, parent = specs[delta_id]
        review = reviews.get(delta_id)
        decision = (review or {}).get("decision", "unreviewed")
        basis = (review or {}).get(
            "decision_basis", "No independent review recorded yet."
        )

        views_html = []
        for view_id in DELTA_VIEWS:
            row = by_delta[delta_id].get(view_id)
            if row is None:
                continue
            t0 = dataset_dir / row["reference_path"]
            t1 = dataset_dir / row["output_path"]
            if not t1.is_file():
                views_html.append(
                    f'<div class="view"><h3>{escape(view_id)}</h3>'
                    '<p class="basis">Not yet rendered.</p></div>'
                )
                continue
            views_html.append(
                f'<div class="view"><h3>{escape(view_id)}</h3><div class="frames">'
                f'<figure class="frame"><figcaption>T0 — check-in (accepted)</figcaption>'
                f'<img src="{_rel(t0, output)}" alt="{escape(view_id)} at T0"></figure>'
                f'<figure class="frame"><figcaption>T1 — check-out (candidate)</figcaption>'
                f'<img src="{_rel(t1, output)}" alt="{escape(view_id)} at T1"></figure>'
                "</div></div>"
            )

        changes = []
        for change in spec["changes"]:
            scope = change.get("views")
            tag = f'<span class="tag">{escape(", ".join(scope))}</span>' if scope else ""
            immaterial = "" if change["material"] else ' <em class="immaterial">(immaterial — reporting this is a false change)</em>'
            changes.append(
                f'<li><span class="kind">{escape(change["kind"].replace("_", " "))}</span> — '
                f'{escape(change["target"])}: {escape(change["description"])}'
                f"{tag}{immaterial}</li>"
            )
        unchanged = "".join(
            f"<li>{escape(item)}</li>" for item in spec["unchanged_assertions"]
        )

        drift_html = ""
        drift = (review or {}).get("unenumerated_material_changes") or []
        if drift:
            items = "".join(
                f'<li>{escape(str(item.get("target", "")))}: '
                f'{escape(str(item.get("description", "")))}</li>'
                for item in drift
            )
            drift_html = (
                '<div class="drift"><h3>Unenumerated material differences reported</h3>'
                f"<ul>{items}</ul></div>"
            )

        sections.append(
            f'<section class="pair"><header><h2>{escape(delta_id)}</h2>'
            f'<span class="room">{escape(parent["room_type"])} · '
            f'{escape(spec["delta_class"])}</span>'
            f'<span class="verdict {escape(decision)}">{escape(decision)}</span></header>'
            f'<p class="basis">{escape(basis)}</p>'
            + "".join(views_html)
            + '<div class="changes"><h3>Enumerated changes (the gold)</h3>'
            f"<ol>{''.join(changes)}</ol></div>"
            + '<div class="changes"><h3>Asserted unchanged</h3>'
            f"<ul>{unchanged}</ul></div>"
            + drift_html
            + "</section>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 3.5 delta pairs — owner adjudication</title>
<style>{GALLERY_CSS}</style>
<style>{EXTRA_CSS}</style>
</head>
<body>
<div class="wrap">
<h1>Phase 3.5 delta pairs — owner adjudication</h1>
<p class="lede">For each pair, the question is not whether the T1 frame is a
good image but whether anything differs between T0 and T1 that is not in the
enumerated list below it. Any such difference rejects the pair. These images
are synthetic evidence and are never treated as real tenancy comparisons.</p>
{"".join(sections)}
</div>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--review", type=Path)
    parser.add_argument(
        "--reviewed-only", action="store_true",
        help="show only pairs present in the supplied review report",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.dataset_dir / "reports" / "delta-owner-gallery.html"
    print(build(args.dataset_dir, output, args.review, args.reviewed_only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
