#!/usr/bin/env python3
"""Re-file the prior-batch Gemini Omni stills under their true view ids.

``stage_gemini_omni_prior_batches.py`` assigned ``A-wide, B-reverse,
C-inventory, D-condition`` **positionally**, in the order the operator supplied
four files per packet, and never checked that position 0 held a wide
establishing view. The supplied order was the reverse, so within every packet
the four labels are exactly inverted:

    A-wide  <-> D-condition
    B-reverse <-> C-inventory

Evidence, all of it recorded before this script was written (docs/34, "Day 1
result"):

* Four source filenames state their own view id. All four contradict the id
  they were filed under, all four fit exact reversal, none contradicts it. Two
  read ``View_D-condition…`` and were filed as ``A-wide``.
* Across all nine packets the file filed as ``A-wide`` is a condition detail
  and the file filed as ``D-condition`` is a wide establishing view, confirmed
  by inspecting every one.
* The files filed as ``B-reverse`` match their scenario's *C-inventory*
  viewpoint — the cooking wall, the entry controls, the upper services, the
  basin wall, the desk wall — and two filenames in the ``C-inventory`` slot
  read ``View_B-reverse…``.

The mapping is read from the staging report rather than from the staging
script, because the report is the record of what was actually written to disk.
Bytes never change: this is a rename, and the manifest asserts that by carrying
the same digest on both sides. The 21 stills staged through
``import_gemini_omni_batch.py`` name a view per file, show no contradiction,
and are not touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET

#: The staging run this repairs.
STAGING_REPORT = "gemini-omni-prior-batches-2026-08-03.json"

VIEWS = ["A-wide", "B-reverse", "C-inventory", "D-condition"]

#: The correction: a label's true value is its mirror within the packet.
TRUE_VIEW = {view: VIEWS[len(VIEWS) - 1 - index]
             for index, view in enumerate(VIEWS)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(dataset_dir: Path) -> list[dict[str, Any]]:
    """Every rename this repair will perform, with the digest that must survive."""
    report = json.loads(
        (dataset_dir / "reports" / STAGING_REPORT).read_text(encoding="utf-8")
    )
    moves: list[dict[str, Any]] = []
    for record in report["records"]:
        filed_as = record["view_id"]
        true_view = TRUE_VIEW[filed_as]
        if true_view == filed_as:
            continue
        current = dataset_dir / "images" / "google" / "gemini-omni" / \
            f"{record['scenario_id']}-{filed_as}.jpeg"
        target = current.with_name(f"{record['scenario_id']}-{true_view}.jpeg")
        moves.append({
            "scenario_id": record["scenario_id"],
            "source_filename": record["source_filename"],
            "filed_as": filed_as,
            "true_view": true_view,
            "from": current,
            "to": target,
            "sha256": record["output_sha256"],
        })
    return moves


def verify(moves: list[dict[str, Any]]) -> None:
    """Refuse to move anything unless every file is present and unmodified.

    A partial rename would leave the packet in a state where neither the old
    nor the new labelling is true, and the digests are the only thing tying a
    file on disk to the staging record that says what it is.
    """
    for move in moves:
        if not move["from"].is_file():
            raise FileNotFoundError(f"{move['from']} is missing")
        actual = _sha256(move["from"])
        if actual != move["sha256"]:
            raise ValueError(
                f"{move['from']} does not match its staging digest; it has "
                "been modified since it was staged and this repair cannot "
                "assume what it holds"
            )


def apply(dataset_dir: Path, moves: list[dict[str, Any]]) -> None:
    """Rename in two phases so a mirrored pair cannot overwrite itself.

    A-wide becomes D-condition and D-condition becomes A-wide in the same
    packet; renaming in place would destroy one of them.
    """
    staging: list[tuple[Path, Path]] = []
    for move in moves:
        temporary = move["from"].with_suffix(".repair-tmp")
        move["from"].rename(temporary)
        staging.append((temporary, move["to"]))
    for temporary, target in staging:
        if target.exists():
            raise FileExistsError(
                f"{target} still exists after phase one; refusing to overwrite"
            )
        temporary.rename(target)


def repair(dataset_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    moves = plan(dataset_dir)
    verify(moves)
    if not dry_run:
        apply(dataset_dir, moves)
        for move in moves:
            if _sha256(move["to"]) != move["sha256"]:
                raise ValueError(f"{move['to']} changed during the rename")
    return {
        "repair": "gemini_omni_view_assignment",
        "repaired_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "staging_report": STAGING_REPORT,
        "rule": "within each packet the four view ids were assigned in reverse "
                "order; each file is re-filed under its mirrored label",
        "basis": "docs/34 'Day 1 result'; evals/synthetic/audit_gemini_omni_views.py",
        "untouched": "the 21 stills staged by import_gemini_omni_batch.py, which "
                     "names a view per file and shows no contradiction",
        "count": len(moves),
        "moves": [
            {
                "scenario_id": move["scenario_id"],
                "source_filename": move["source_filename"],
                "filed_as": move["filed_as"],
                "true_view": move["true_view"],
                "from": move["from"].name,
                "to": move["to"].name,
                "sha256": move["sha256"],
                "bytes_changed": False,
            }
            for move in moves
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = repair(args.dataset_dir, args.dry_run)
    for move in result["moves"]:
        print(f"{move['from']:26} -> {move['to']:26} "
              f"({move['source_filename'][:40]})")
    print(f"\n{result['count']} file(s) "
          f"{'would be' if args.dry_run else ''} re-filed; bytes unchanged")
    if args.report and not args.dry_run:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
