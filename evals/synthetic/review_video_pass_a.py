#!/usr/bin/env python3
"""Two independent Pass A visual screens over a sampled video strip.

The image-arm equivalent is ``review_pass_a.py``. This cannot reuse it, for
three reasons that are all about video rather than about code.

**The unit of review is a strip, not a frame.** Five of the nine acceptance
criteria in ``video/dataset.json`` — continuity, geometry through motion, the
unbroken take, unenumerated difference, and the VU-5 occlusion rule — are
properties of a *sequence*. A per-frame reviewer cannot see any of them, and
averaging per-frame verdicts would report a clip as fine when every frame is
individually plausible and the room quietly changes shape across them.

**Three criteria are already settled before the reviewer runs.** Cuts, audio
mode and container facts are measured by ``build_video_strip.py``. They are
handed to the reviewer as findings, with an instruction not to re-decide them:
a vision model cannot hear, and one asked to judge whether a take is unbroken
will describe rather than measure.

**The two reviewers are different model families.** The parent Pass A ran the
same model twice, which buys independence of *conclusion* but not of blind
spot. Here the generator is Google, so the primary reviewer is deliberately not
Google: a same-family reviewer judging what is visible in its own family's
output is the bias docs/31 Amendment B B6 legislates against for labels, and
it costs nothing to avoid it here too. Disagreement escalates to the owner
rather than being reconciled away.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_video_strip import load_clip_specs
from evals.synthetic.build_video_tasks import DEFAULT_DATASET

#: Primary is non-Google by design (see module docstring); the second check is
#: the parent dataset's Pass A reviewer, so the video arm stays comparable to
#: the image arm it is measured against.
PRIMARY_MODEL = "claude-sonnet-4-6"
SECOND_MODEL = "gemini-3.5-flash-low"

VALID_DECISIONS = {"accept", "reject", "escalate"}

#: The acceptance criteria a reviewer can actually see. The remaining three
#: (one_unbroken_take, audio mode, container facts) are measured.
VISUAL_CRITERIA = [
    ("opening_frame_matches_reference",
     "The first strip frame matches the pinned reference image in layout, "
     "fittings, finishes and lighting."),
    ("continuity_holds_through_take",
     "Every element of the continuity list holds across the whole strip; "
     "nothing morphs, gains or loses identity between frames."),
    ("required_evidence_legible",
     "Every required evidence item is legible in at least one strip frame."),
    ("negative_controls_not_rendered_as_defects",
     "No enumerated negative control is rendered as a real defect."),
    ("no_unenumerated_material_difference",
     "No unenumerated material difference from the reference frame appears at "
     "any point in the strip."),
    ("no_people_text_logos",
     "No people, no readable text, no logos, no watermark."),
    ("geometry_coherent_through_motion",
     "Geometry stays coherent through camera motion: no furniture sliding, no "
     "doorway changing count or position, no room growing."),
]

OCCLUSION_CRITERION = (
    "occlusion_respected",
    "Nothing on the must-never-be-visible list appears in any strip frame.",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolve_cli(cli: Path | None = None) -> Path:
    configured = cli or Path(os.environ.get("ANTIGRAVITY_CLI", "agy"))
    if configured.is_file():
        return configured.resolve()
    discovered = shutil.which(str(configured))
    if discovered:
        return Path(discovered).resolve()
    raise FileNotFoundError(f"CLI not found: {configured}")


def _extract_json(text: str) -> Any:
    """Pull the review object out of whatever prose the CLI wrapped it in."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    starts = [index for index in (stripped.find("{"), stripped.find("["))
              if index >= 0]
    if not starts:
        raise ValueError("no JSON found in reviewer output")
    start = min(starts)
    closing = "}" if stripped[start] == "{" else "]"
    return json.loads(stripped[start:stripped.rfind(closing) + 1])


def review_input(dataset_dir: Path, row: dict[str, str],
                 clip_spec: dict[str, Any]) -> dict[str, Any]:
    strip_dir = dataset_dir / "video" / "strips" / row["clip_id"]
    manifest = json.loads((strip_dir / "strip.json").read_text(encoding="utf-8"))
    scenario = json.loads(
        (dataset_dir / "scenarios" / f"{row['scenario_id']}.json").read_text(
            encoding="utf-8")
    )
    use_case = clip_spec["use_case"]
    payload: dict[str, Any] = {
        "clip_id": row["clip_id"],
        "use_case": f"{use_case['id']} — {use_case['use_case']}",
        "room_type": row["room_type"],
        "requested_camera_move": clip_spec["camera"],
        "reference_image": str((dataset_dir / row["reference_path"]).resolve()),
        "contact_sheet": {
            **manifest["contact_sheet"],
            "path": str((strip_dir / manifest["contact_sheet"]["file"]).resolve()),
        },
        "strip_frames": [
            {
                "frame": index,
                "timestamp_s": frame["timestamp_s"],
                "path": str((strip_dir / frame["file"]).resolve()),
            }
            for index, frame in enumerate(manifest["frames"])
        ],
        "continuity_requirements": scenario["continuity_requirements"],
        "required_evidence": clip_spec["required_evidence"],
        "intended_defects": clip_spec.get("intended_defects") or [],
        "intended_negatives": clip_spec.get("intended_negatives") or [],
        "already_measured": manifest["mechanical_checks"],
    }
    if clip_spec.get("must_not_be_visible"):
        payload["must_never_be_visible"] = clip_spec["must_not_be_visible"]
    if clip_spec.get("second_room"):
        payload["second_room_entered"] = clip_spec["second_room"]
    boundary_rule = (clip_spec.get("gold") or {}).get("boundary_rule")
    if boundary_rule:
        payload["boundary_rule"] = boundary_rule
    return payload


def _criteria_for(payload: dict[str, Any]) -> list[tuple[str, str]]:
    criteria = list(VISUAL_CRITERIA)
    if payload.get("must_never_be_visible"):
        criteria.append(OCCLUSION_CRITERION)
    return criteria


def build_prompt(payload: dict[str, Any], reviewer_id: str) -> str:
    criteria = _criteria_for(payload)
    criteria_text = "\n".join(
        f"- {name}: {description}" for name, description in criteria
    )
    boundary = ""
    if payload.get("boundary_rule"):
        boundary = (
            "\n\nThis clip crosses from one room into another. Also report "
            "observed_boundary_frame (the first strip frame in which the "
            "doorway plane is behind the camera) and observed_rooms (the room "
            "names you can actually see, in order). The strip is sampled once "
            "a second, so this brackets the boundary to a second; do not "
            "report a precision the strip cannot carry. Rule: "
            f"{payload['boundary_rule']}"
        )
    occlusion = ""
    if payload.get("must_never_be_visible"):
        occlusion = (
            "\n\nThis clip carries a must-never-be-visible list. Check every "
            "frame for those surfaces specifically and report "
            "occlusion_breaches with the frame number of any appearance. A "
            "single frame is a breach."
        )
    return (
        "Act only as an independent Pass A visual reviewer for a bounded "
        "synthetic property-video evaluation. Do not edit any file and do not "
        "search the filesystem: every path below is absolute and correct.\n\n"
        "Open, with the local image-reading tool and in this order: (1) the "
        "reference image, (2) the contact sheet, which is the whole strip "
        "tiled in one image, (3) any individual strip frame you need at full "
        "resolution to settle a detail. The contact sheet is for the sequence; "
        "the individual frames are for detail. Open enough of them to justify "
        "your verdicts.\n\n"
        "The strip is frames sampled once a second from one generated clip. "
        "You are judging the clip through the strip, so continuity, geometry "
        "and occlusion are judged ACROSS frames — a clip whose frames are each "
        "individually plausible still fails if the room changes shape, an "
        "object moves without the camera moving, or a fitting appears or "
        "disappears between frames.\n\n"
        "Treat the requested camera move and the evidence lists as a "
        "hypothesis about what was asked for, never as a description of what "
        "is there. Judge only what you can see.\n\n"
        f"Criteria to judge:\n{criteria_text}\n\n"
        "The findings under already_measured were decided by measurement, not "
        "by sight. Do not re-judge them and do not let them change your visual "
        "verdicts; they are given so your reasons do not contradict the "
        "record.\n\n"
        "Reject on any hard failure: the named room is not recognisable; the "
        "opening frame is not the reference room; geometry breaks under "
        "motion; a person, logo or readable brand appears; a negative control "
        "is rendered as a real defect; a must-never-be-visible surface "
        "appears. Escalate genuine visual uncertainty. Do not excuse a hard "
        "failure because the rest of the clip is good."
        f"{boundary}{occlusion}\n\n"
        "Return ONLY a JSON object, no Markdown fence, with exactly these "
        "keys: clip_id, decision (accept|reject|escalate), reason, criteria "
        "[{criterion, verdict(pass|fail|uncertain), note}], required_evidence "
        "[{name, visibility(clear|ambiguous|absent|malformed), "
        "first_seen_frame}], hard_failures [string], continuity_notes "
        "[string], occlusion_breaches [{surface, frame, note}], "
        "observed_boundary_frame (integer or null), observed_rooms [string].\n"
        f"Reviewer context: {reviewer_id}.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def invoke(cli: Path, model: str, prompt: str, cwd: Path,
           timeout: int) -> tuple[dict[str, Any], float, str]:
    command = [
        str(cli), "--sandbox", "--dangerously-skip-permissions",
        "--model", model,
        "--print-timeout", f"{max(1, timeout // 60)}m",
        "-p", prompt,
    ]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout + 60)
    elapsed = round(time.perf_counter() - started, 3)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return _extract_json(result.stdout), elapsed, result.stdout


def validate_review(payload: dict[str, Any], review: Any) -> dict[str, Any]:
    if isinstance(review, list):
        review = next(
            (item for item in review
             if item.get("clip_id") == payload["clip_id"]), review[0]
        )
    if not isinstance(review, dict):
        raise ValueError("reviewer did not return a JSON object")
    if review.get("decision") not in VALID_DECISIONS:
        raise ValueError(f"invalid decision: {review.get('decision')!r}")
    if not isinstance(review.get("criteria"), list) or not review["criteria"]:
        raise ValueError("reviewer returned no per-criterion verdicts")
    expected = {name for name, _ in _criteria_for(payload)}
    returned = {item.get("criterion") for item in review["criteria"]}
    missing = expected - returned
    if missing:
        raise ValueError(f"reviewer skipped criteria: {sorted(missing)}")
    review["clip_id"] = payload["clip_id"]
    return review


def reconcile(first: dict[str, Any], second: dict[str, Any],
              mechanical: list[dict[str, Any]]) -> tuple[str, str]:
    """Combine two reviews and the measured findings into one decision.

    A measured failure is not a matter of opinion, so it cannot be voted away
    by two reviewers who could not observe it. But it is also not automatically
    fatal to the probe — an audio track on a clip whose use case is entirely
    visual is a defect in the artefact with a free remedy — so it lands on the
    owner rather than on an automatic reject.
    """
    failures = [check["criterion"] for check in mechanical
                if check["status"] == "fail"]
    first_decision = first["decision"]
    second_decision = second["decision"]
    if first_decision == "reject" or second_decision == "reject":
        if first_decision == second_decision:
            return "reject", first.get("reason") or "both reviewers rejected"
        return "escalate", (
            f"Reviewers disagreed: {first_decision} vs {second_decision}"
        )
    if failures:
        return "escalate", (
            "Measured acceptance-criteria failure requires an owner decision: "
            + ", ".join(failures)
        )
    if first_decision == second_decision == "accept":
        return "accept", first.get("reason") or "both reviewers accepted"
    return "escalate", f"Reviewers disagreed: {first_decision} vs {second_decision}"


def review(dataset_dir: Path, output_path: Path,
           clip_ids: set[str] | None = None, cli_path: Path | None = None,
           primary_model: str = PRIMARY_MODEL,
           second_model: str = SECOND_MODEL,
           timeout: int = 900) -> dict[str, Any]:
    cli = _resolve_cli(cli_path)
    specs = load_clip_specs(dataset_dir)
    with (dataset_dir / "video" / "tasks.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))

    queue = []
    for row in rows:
        if clip_ids is not None and row["clip_id"] not in clip_ids:
            continue
        if clip_ids is None and row["status"] != "review_pending":
            continue
        strip = dataset_dir / "video" / "strips" / row["clip_id"] / "strip.json"
        if not strip.is_file():
            raise FileNotFoundError(
                f"{row['clip_id']}: no strip. Run build_video_strip first."
            )
        queue.append(row)
    if not queue:
        raise ValueError("no clips are ready for video Pass A")

    clips: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    started_at = _utc_now()
    if output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        if previous.get("status") != "partial":
            raise FileExistsError(f"refusing to overwrite: {output_path}")
        clips = list(previous.get("clips") or [])
        calls = list(previous.get("calls") or [])
        started_at = previous.get("reviewed_at") or started_at
    done = {clip["clip_id"] for clip in clips}

    def write_report(status: str) -> dict[str, Any]:
        counts = Counter(clip["pass_a_decision"] for clip in clips)
        report = {
            "review_type": "phase3.6_video_pass_a_visual_screen",
            "status": status,
            "reviewed_at": started_at,
            "completed_at": _utc_now() if status == "complete" else None,
            "generation_path": "Antigravity CLI independent local-image review",
            "metered_api_call": False,
            "reviewer_primary_model": primary_model,
            "reviewer_second_model": second_model,
            "reviewer_family_independence": (
                "Primary is not the generator's model family. The second check "
                "is the parent dataset's Pass A reviewer and IS the generator's "
                "family; it is retained for comparability with the image arm "
                "and is not treated as an independent-family confirmation."
            ),
            "counts": dict(sorted(counts.items())),
            "clips": clips,
            "calls": calls,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)
        return report

    for row in queue:
        if row["clip_id"] in done:
            continue
        payload = review_input(dataset_dir, row, specs[row["clip_id"]])
        strip_dir = dataset_dir / "video" / "strips" / row["clip_id"]
        manifest = json.loads(
            (strip_dir / "strip.json").read_text(encoding="utf-8"))
        print(f"Pass A {row['clip_id']}: primary review "
              f"({len(payload['strip_frames'])} frames)", flush=True)
        first_prompt = build_prompt(payload, "primary")
        first_raw, first_elapsed, _ = invoke(
            cli, primary_model, first_prompt, dataset_dir, timeout)
        print(f"Pass A {row['clip_id']}: second review", flush=True)
        second_prompt = build_prompt(payload, "second")
        second_raw, second_elapsed, _ = invoke(
            cli, second_model, second_prompt, dataset_dir, timeout)
        first = validate_review(payload, first_raw)
        second = validate_review(payload, second_raw)
        decision, reason = reconcile(first, second,
                                     manifest["mechanical_checks"])
        calls.append({
            "clip_id": row["clip_id"],
            "primary_prompt_sha256": _sha256_text(first_prompt),
            "second_prompt_sha256": _sha256_text(second_prompt),
            "primary_latency_seconds": first_elapsed,
            "second_latency_seconds": second_elapsed,
        })
        clips.append({
            "clip_id": row["clip_id"],
            "task_id": row["task_id"],
            "use_case": payload["use_case"],
            "clip_sha256": manifest["clip_sha256"],
            "strip_sha256": manifest["strip_sha256"],
            "mechanical_checks": manifest["mechanical_checks"],
            "primary_review": first,
            "second_review": second,
            "pass_a_decision": decision,
            "pass_a_reason": reason,
        })
        write_report("partial")
        print(f"Pass A {row['clip_id']}: {decision}", flush=True)
    return write_report("complete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clip", action="append", dest="clips")
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--primary-model", default=PRIMARY_MODEL)
    parser.add_argument("--second-model", default=SECOND_MODEL)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the composed prompts without invoking a CLI")
    args = parser.parse_args()

    if args.dry_run:
        specs = load_clip_specs(args.dataset_dir)
        with (args.dataset_dir / "video" / "tasks.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            for row in csv.DictReader(handle):
                if args.clips and row["clip_id"] not in args.clips:
                    continue
                if not args.clips and row["status"] != "review_pending":
                    continue
                payload = review_input(args.dataset_dir, row,
                                       specs[row["clip_id"]])
                print(f"=== {row['clip_id']}")
                print(build_prompt(payload, "primary"))
                print()
        return 0

    report = review(args.dataset_dir, args.output,
                    set(args.clips) if args.clips else None, args.cli,
                    args.primary_model, args.second_model, args.timeout)
    print(json.dumps(report["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
