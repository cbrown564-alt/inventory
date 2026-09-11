#!/usr/bin/env python3
"""Apply the 6 Aug 2026 triage of the Phase 3.6 video arm to the ledger.

docs/34's nine queued clips have been sitting `retry_pending` since the day-1
batch was voided and its fixture repaired. "Regenerate or suspend" was the
question; the answer is neither, because the arm is five independent questions
sharing a generator and a budget, and the docs/35 Phase 0 noise floor lands on
them unevenly. Three dispositions:

``retry_pending`` — **VU-5 only.** The occlusion counterfactual measures whether
the describer claims what the camera never saw. That is a hallucination test,
not a recall test, and non-determinism does not rescue a hallucination: a claim
about geometry the camera never reached is wrong whichever run emits it. It is
also the probe's only ``both_ways`` case, and its day-1 failure was on the
*control* arm, which a corrected reference is exactly the thing that resolves.
It closes either way — a hold clip that honours the instruction is the first
positive result the probe can produce, and one that breaches again is a clean
negative about controllability.

``suspended`` — **VU-1, VU-2, VU-3.** Not abandoned for lack of time. VU-1 and
VU-3 measure a recall difference between two describe runs, at n=2 and n=1
clips, against a floor where two runs on byte-identical pixels agree on 34.6% of
the schedule; they are the measurement shape Phase 0 invalidated in the image
arm. VU-2's metric is not a describe schedule and survives that argument, but it
is n=1 on the easiest boundary that exists, and docs/34 already concedes a hit
is weak. The status is written so the record says *under-powered against a
measured floor*, not *ran out of schedule* — the distinction is what stops these
being revived without the design change that would make them readable.

``retired`` — **VU-4.** Dead twice: RP-022's ``A-wide`` was rejected by both
reviewers for showing a wall-hung basin where the specification requires a
corner one, and no regeneration repairs a reference; and it already sat behind
Amendment B's free degradation ladder, which answers the same question without
a clip. This needs recording, not deciding.

Idempotent, and it re-checks its own premise: VU-5 is cleared only while its
reference stays ``pass_a_accepted``, so a triage that outlived the fact it rests
on fails rather than blessing a clip that cannot produce gold.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from evals.synthetic.build_video_tasks import DEFAULT_DATASET, FIELDNAMES

REVIEW = "docs/36-synthetic-programme-review.md §6.3"

#: use case -> (status, reason). VU-5 keeps ``retry_pending``: the triage clears
#: it to generate, and saying so is a decision even though the value is unchanged.
TRIAGE: dict[str, tuple[str, str]] = {
    "VU-5": ("retry_pending",
             "Cleared to regenerate. A hallucination test, not a recall test, so "
             "the describe-stability floor does not reach it; the probe's only "
             "both-ways case; resolves either way on two clips."),
    "VU-1": ("suspended",
             "Under-powered against the docs/35 Phase 0 floor: a recall "
             "difference between two describe runs at n=2 clips, where two runs "
             "on identical pixels agree on 34.6% of the schedule."),
    "VU-3": ("suspended",
             "Under-powered against the docs/35 Phase 0 floor: 'does one spoken "
             "cue move any metric' at n=1 clip. The input control is perfect and "
             "the measurement is still one describe run a side."),
    "VU-2": ("suspended",
             "Not reached by the floor — room naming and boundary timing are not "
             "a describe schedule — but n=1 on the strongest boundary cue that "
             "exists, where docs/34 already grants that a hit is weak."),
    "VU-4": ("retired",
             "Terminal on its reference: RP-022's A-wide was rejected by both "
             "reviewers for a wall-hung basin where the specification requires a "
             "corner one, and no regeneration repairs a reference. Already "
             "dominated by Amendment B's free degradation ladder."),
}

CLEARED = "VU-5"


def triage(dataset_dir: Path, operator: str | None = None) -> dict[str, object]:
    task_path = dataset_dir / "video" / "tasks.csv"
    with task_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    unknown = sorted({row["use_case_id"] for row in rows} - set(TRIAGE))
    if unknown:
        raise ValueError(
            f"no disposition for {', '.join(unknown)}. The triage names every use "
            "case in docs/34; a new one must be decided, not defaulted."
        )

    decisions: list[dict[str, object]] = []
    for row in rows:
        status, reason = TRIAGE[row["use_case_id"]]

        # A row still holding a delivered clip has an artefact that belongs in
        # video/rejected/ with its Pass A reasons. Parking it under a programme
        # status would strand the file outside both the queue and the archive.
        if row.get("output_sha256"):
            raise ValueError(
                f"{row['task_id']} still holds a delivered clip. Archive it first:\n"
                f"  python -m evals.synthetic.reject_video_clip {row['task_id']} "
                "'superseded by the phase 3.6 triage'"
            )

        # The clearance is the load-bearing half of this decision and it rests on
        # a fact that can change underneath it.
        if (row["use_case_id"] == CLEARED
                and row["reference_provenance"] != "pass_a_accepted"):
            raise ValueError(
                f"{row['task_id']} is cleared to regenerate but its reference is "
                f"{row['reference_provenance']}. The triage rests on that "
                "clearance; re-decide it rather than generating against a "
                "reference that cannot produce gold."
            )

        decisions.append({
            "task_id": row["task_id"],
            "use_case_id": row["use_case_id"],
            "clip_id": row["clip_id"],
            "was": row["status"],
            "now": status,
            "reference_provenance": row["reference_provenance"],
            "reason": reason,
        })
        row["status"] = status
        if operator:
            row["operator"] = operator

    with task_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    counts: dict[str, int] = {}
    for decision in decisions:
        counts[str(decision["now"])] = counts.get(str(decision["now"]), 0) + 1
    return {
        "schema_version": 1,
        "record_type": "phase36_video_arm_triage",
        "dataset_id": "synthetic-room-video-probe",
        "decided_by": REVIEW,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "operator": operator,
        "counts": counts,
        "clips_cleared_to_generate": sorted(
            str(d["clip_id"]) for d in decisions if d["now"] == "retry_pending"),
        "decisions": decisions,
        "wall": "Synthetic video is development evidence. Nothing here promotes a "
                "capture-strategy, compare or product accuracy claim, and the "
                "Google arm remains unpublishable on terms grounds (docs/31 B9).",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--operator")
    parser.add_argument("--report", type=Path,
                        help="write the decision record here as well as stdout")
    args = parser.parse_args()
    record = triage(args.dataset_dir, args.operator)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
