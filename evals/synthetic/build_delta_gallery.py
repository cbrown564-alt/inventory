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

from evals.synthetic.build_delta_tasks import (
    DELTA_VIEWS,
    RETRACTED_CHANGES_FIELD,
    load_specs,
)
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
.changes li.retracted { color: var(--muted); }
.changes li.retracted .struck { text-decoration: line-through; }
.changes li.observed .kind { color: var(--muted); }
.tag { font-size: 11px; border: 1px solid var(--line); border-radius: 999px;
       padding: 1px 8px; margin-left: 6px; color: var(--muted); }
.drift { margin-top: 14px; padding: 12px 16px; border-radius: 9px;
         background: rgba(163,49,42,.06); border: 1px solid rgba(163,49,42,.25); }
.drift h3 { color: var(--bad); }
.drift .where { font-variant: all-small-caps; letter-spacing: .04em; font-weight: 600; }
.incidental { margin-top: 14px; padding: 12px 16px; border-radius: 9px;
              background: var(--panel-muted); }
.incidental h3, .incidental li { color: var(--muted); }
.incidental h3 { font: 600 12px/1 var(--sans); letter-spacing: .08em;
                 text-transform: uppercase; margin: 0 0 8px; }
.incidental ul { margin: 0; padding-left: 20px; }
.audit li.absent { color: var(--bad); }
.audit li.ambiguous { color: var(--muted); }
.vis { font-variant: all-small-caps; letter-spacing: .04em; font-weight: 600; }
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
        retractions = {
            item["id"]: item for item in spec.get(RETRACTED_CHANGES_FIELD) or []
        }
        for change in spec["changes"]:
            scope = change.get("views")
            tag = f'<span class="tag">{escape(", ".join(scope))}</span>' if scope else ""
            immaterial = "" if change["material"] else ' <em class="immaterial">(immaterial — reporting this is a false change)</em>'
            retraction = retractions.get(change["id"])
            note = (
                f' <em class="immaterial">(retracted — '
                f'{escape(retraction["issue"].replace("_", " "))}: '
                f'{escape(retraction["reason"])})</em>'
                if retraction
                else ""
            )
            # The strikethrough has to stop at the withdrawn claim: struck text
            # over the reason for striking it is unreadable.
            open_li = '<li class="retracted"><span class="struck">' if retraction else "<li>"
            close_struck = "</span>" if retraction else ""
            changes.append(
                f"{open_li}"
                f'<span class="kind">{escape(change["kind"].replace("_", " "))}</span> — '
                f'{escape(change["target"])}: {escape(change["description"])}'
                f"{close_struck}{tag}{immaterial}{note}</li>"
            )
        for change in spec.get("observed_changes") or []:
            changes.append(
                f'<li class="observed"><span class="kind">observed</span> — '
                f'{escape(change["target"])}: {escape(change["description"])}'
                ' <em class="immaterial">(found after the render; scored so '
                'reporting it is not a false change)</em></li>'
            )
        unchanged = "".join(
            f"<li>{escape(item)}</li>" for item in spec["unchanged_assertions"]
        )

        drift_html = ""
        findings = (review or {}).get("room_identity_findings")
        if findings is None:
            # Reports written before the 5 Aug rubric kept one flat drift list.
            findings = [
                {
                    "description": f'{item.get("target", "")}: '
                                   f'{item.get("description", "")}'.strip(": ")
                }
                for item in (review or {}).get("unenumerated_material_changes") or []
            ]
        if findings:
            items = "".join(
                "<li>"
                + (
                    f'<span class="where">{escape(str(item["view"]))} · '
                    f'{escape(str(item.get("element", "")))}</span> — '
                    if item.get("view")
                    else ""
                )
                + f'{escape(str(item.get("description", "")))}</li>'
                for item in findings
            )
            drift_html = (
                '<div class="drift"><h3>Room identity findings</h3>'
                f"<ul>{items}</ul></div>"
            )

        for conflict in (review or {}).get("cross_view_conflicts") or []:
            drift_html += (
                '<div class="drift"><h3>Views disagree at the same timepoint</h3>'
                f"<p>{escape(str(conflict))}</p></div>"
            )

        audit_html = ""
        audited = (review or {}).get("enumerated") or []
        if audited:
            items = "".join(
                f'<li class="{escape(entry["visibility"])}">'
                f'{escape(entry["change_id"])} '
                f'<span class="vis">{escape(entry["visibility"])}</span> — '
                f'{escape(str(entry.get("notes", "")))}</li>'
                for entry in audited
            )
            audit_html = (
                '<div class="changes audit"><h3>What is actually visible</h3>'
                f"<ul>{items}</ul></div>"
            )

        corrections = (review or {}).get("gold_corrections") or []
        if corrections:
            items = "".join(
                f'<li>{escape(item["change_id"])} '
                f'<span class="vis">{escape(item["issue"].replace("_", " "))}</span> — '
                f'{escape(item["recommendation"])}</li>'
                for item in corrections
            )
            audit_html += (
                '<div class="changes"><h3>Gold corrections before scoring</h3>'
                f"<ul>{items}</ul></div>"
            )

        incidental = (review or {}).get("incidental_differences") or []
        incidental_html = ""
        if incidental:
            items = "".join(
                f'<li>{escape(str(item.get("target", "")))}: '
                f'{escape(str(item.get("description", "")))}</li>'
                for item in incidental
            )
            incidental_html = (
                '<div class="incidental"><h3>Incidental — recorded, not counted '
                "against the pair</h3>"
                f"<ul>{items}</ul></div>"
            )

        note = (review or {}).get("reviewer_note")
        note_html = f'<p class="basis">{escape(note)}</p>' if note else ""

        sections.append(
            f'<section class="pair"><header><h2>{escape(delta_id)}</h2>'
            f'<span class="room">{escape(parent["room_type"])} · '
            f'{escape(spec["delta_class"])}</span>'
            f'<span class="verdict {escape(decision)}">{escape(decision)}</span></header>'
            f'<p class="basis">{escape(basis)}</p>'
            + note_html
            + drift_html
            + "".join(views_html)
            + '<div class="changes"><h3>Enumerated changes (the gold)</h3>'
            f"<ol>{''.join(changes)}</ol></div>"
            + audit_html
            + '<div class="changes"><h3>Asserted unchanged</h3>'
            f"<ul>{unchanged}</ul></div>"
            + incidental_html
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
good image but whether it is still the same room. Fixed fabric — layout,
fittings, appliances, sanitaryware, finishes — has to hold; movable clutter
does not, and is listed separately because the gold must name it, not because
it counts against the pair. These images are synthetic evidence and are never
treated as real tenancy comparisons.</p>
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
