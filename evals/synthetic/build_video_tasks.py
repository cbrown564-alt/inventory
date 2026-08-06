#!/usr/bin/env python3
"""Build generation tasks for the Phase 3.6 video feasibility probe.

Each clip is one Gemini Omni generation conditioned on an accepted still from
the parent image pilot. The still is pinned by path and SHA-256 because room
identity is what drifts: the parent pilot rejected 36% of first attempts on
four *static* views, and a moving camera has strictly more drift surface
(docs/34).

Prompts are composed here rather than written by hand so that the video arm
inherits the parent dataset's evidence/defect/negative-control clauses
verbatim. A clip's prompt is content-addressed the same way an image task's
is, so an edited prompt is visible as a changed hash and cannot be silently
folded into an existing accepted clip.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path("evals/fixtures/synthetic-room-eval")

#: Video-specific prohibitions, appended to each scenario's ``avoid`` list.
#: Scene cuts and titles are the failure that makes a clip unusable as a
#: walkthrough proxy regardless of how good the room looks.
VIDEO_AVOID = (
    "scene cuts",
    "dissolves or fades",
    "speed ramps",
    "slow motion",
    "title cards",
    "music",
    "sound effects",
    "camera-operator commentary",
    "drone or crane moves",
    "tripod-smooth motorised motion",
)

AUDIO_CLAUSE = {
    "silent": (
        "the clip is silent; no speech, no music, no sound effects, no room tone"
    ),
    "narrated": None,  # composed from the clip's ``audio`` block
}

FIELDNAMES = [
    "task_id", "use_case_id", "use_case", "clip_id", "scenario_id", "room_type",
    "arm", "speed_rung", "provider", "product", "model_display_name",
    "reference_path", "reference_sha256", "reference_provenance", "output_path",
    "prompt_sha256", "exact_prompt", "audio_mode", "status", "attempts",
    "operator", "generated_at", "duration_s", "output_sha256", "strip_sha256",
]


def _ledger_status(dataset_dir: Path) -> dict[str, str]:
    """Map parent output paths to their ledger status.

    The Gemini Omni stills are not in ``tasks.csv`` at all as of Amendment B:
    their Pass A import is item 6 of the B work order and is named there as
    the droppable one. A clip conditioned on an unimported still is therefore
    conditioned on an artefact with no recorded provenance, which is the exact
    failure docs/31 forbids ("do not mark ... any packet gold without that
    recorded path"). This lookup makes that visible instead of assumed.
    """
    path = dataset_dir / "tasks.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["output_path"]: row["status"] for row in csv.DictReader(handle)}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _article(noun: str) -> str:
    """Pick a/an for the closed set of room types in this dataset.

    Leading "u" is excluded because every u-initial room type here reads with
    a /juː/ onset ("a utility cupboard"). This is not a general rule and does
    not need to be; the room-type vocabulary is fixed by the scenario set.
    """
    return "an" if noun[:1].lower() in "aeio" else "a"


def _audio_clause(clip: dict[str, Any]) -> str:
    mode = clip["audio_mode"]
    if mode == "silent":
        return AUDIO_CLAUSE["silent"]
    if mode == "narrated":
        audio = clip["audio"]
        return (
            f"one line of speech only, {audio['voice']}, saying exactly "
            f"\"{audio['cue_text']}\" at about {audio['cue_at_s']:g} second"
        f"{'' if audio['cue_at_s'] == 1 else 's'} in; "
            f"then {audio['after_cue']}"
        )
    raise ValueError(f"{clip['id']}: unknown audio_mode {mode!r}")


def build_prompt(scene: dict[str, Any], use_case: dict[str, Any],
                 clip: dict[str, Any]) -> str:
    """Compose the exact generation prompt for one clip.

    Mirrors ``build_tasks.build_prompt`` clause for clause so that a video and
    a still of the same scenario are bound by the same evidence contract, and
    adds only what a moving camera introduces: the take, the path, the audio.
    """
    items = ", ".join(clip["required_evidence"])
    defects = "; ".join(clip.get("intended_defects", [])) or "none"
    negatives = "; ".join(clip.get("intended_negatives", [])) or "none"
    continuity = "; ".join(scene["continuity_requirements"])
    avoid = ", ".join(list(scene["avoid"]) + list(VIDEO_AVOID))

    room = scene["room_type"].lower()
    parts = [
        "Create one continuous photorealistic video that looks like an ordinary "
        f"handheld smartphone walkthrough of {_article(room)} "
        f"{room} in a {scene['property_profile']}. "
        "The supplied reference image is the opening frame: match its layout, "
        "fittings, finishes and lighting exactly, then move from it. ",
        f"Camera: {clip['camera']}. ",
        "One unbroken take from a single handheld phone. ",
        f"Visible evidence required across the take: {items}. ",
        f"Intended visible defects: {defects}. Negative controls: {negatives}. ",
        f"The room is {scene['cleanliness']} under {scene['lighting']}. ",
        f"Hold fixed for the whole take: {continuity}. ",
    ]
    if clip.get("must_not_be_visible"):
        hidden = ", ".join(clip["must_not_be_visible"])
        parts.append(
            f"Must never become visible in any frame: {hidden}. "
        )
    if clip.get("second_room"):
        room = clip["second_room"]
        parts.append(
            f"Beyond the doorway the camera enters {room['prose']}. "
        )
    parts.extend([
        f"Audio: {_audio_clause(clip)}. ",
        f"Avoid: {avoid}. ",
        "Do not add labels, captions, borders, or inspection annotations. ",
        "Show only visually supportable property evidence; do not make hidden "
        "areas visible.",
    ])
    return "".join(parts)


def build_rows(dataset_dir: Path) -> list[dict[str, str]]:
    video_dir = dataset_dir / "video"
    config = _load(video_dir / "dataset.json")
    provider_id, provider = next(iter(config["providers"].items()))
    ledger = _ledger_status(dataset_dir)

    rows: list[dict[str, str]] = []
    for spec_path in sorted((video_dir / "clips").glob("VU-*.json")):
        use_case = _load(spec_path)
        for clip in use_case["clips"]:
            scene = _load(dataset_dir / "scenarios" / f"{clip['scenario_id']}.json")
            reference = (
                Path("images") / "google" / "gemini-omni"
                / f"{clip['scenario_id']}-{clip['reference_view']}.jpeg"
            )
            reference_abs = dataset_dir / reference
            if not reference_abs.exists():
                raise FileNotFoundError(
                    f"{clip['id']}: reference frame {reference} is missing. A clip "
                    "may only be conditioned on a still that exists in the parent "
                    "pilot."
                )
            provenance = ledger.get(reference.as_posix(), "unimported")
            prompt = build_prompt(scene, use_case, clip)
            output = Path("video") / provider["video_directory"] / f"{clip['id']}.{provider['file_extension']}"
            rows.append({
                "task_id": f"{clip['id']}.{provider_id}",
                "use_case_id": use_case["id"],
                "use_case": use_case["use_case"],
                "clip_id": clip["id"],
                "scenario_id": clip["scenario_id"],
                "room_type": scene["room_type"],
                "arm": clip.get("arm", ""),
                "speed_rung": clip.get("speed_rung", ""),
                "provider": provider["provider"],
                "product": provider["product"],
                "model_display_name": provider["model_display_name"],
                "reference_path": reference.as_posix(),
                "reference_sha256": _sha256_file(reference_abs),
                "reference_provenance": provenance,
                "output_path": output.as_posix(),
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "exact_prompt": prompt,
                "audio_mode": clip["audio_mode"],
                "status": "pending",
                "attempts": "0",
                "operator": "",
                "generated_at": "",
                "duration_s": "",
                "output_sha256": "",
                "strip_sha256": "",
            })
    return rows


def check_reference_provenance(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Return ``(clip_id, reference status)`` for clips not cleared to generate.

    The status is reported rather than just the clip id because the reasons are
    no longer interchangeable. Before the Omni Pass A import every reference was
    ``unimported`` — absent from the ledger entirely. Now a reference can be
    ``pass_a_rejected``, which is a different and worse thing: an unimported
    still might turn out fine, whereas a rejected one has been looked at twice
    and found wanting, and no amount of regenerating the clip changes it.

    ``retired`` rows are exempt, and only ``retired``. The gate exists to stop a
    clip being *generated* against a reference that cannot produce gold; a use
    case the programme has retired will not be generated, so holding a rejected
    reference is now its recorded epitaph rather than a live risk — and leaving
    it gated would make the queue permanently unbuildable in order to prevent
    something nobody is going to do. ``suspended`` stays gated on purpose: a
    suspension can be revived, and the reference must still be good when it is.
    """
    return [(row["clip_id"], row["reference_provenance"]) for row in rows
            if row["reference_provenance"] != "pass_a_accepted"
            and row.get("status") != "retired"]


def write_tasks(dataset_dir: Path, allow_unimported: bool = False) -> list[dict[str, str]]:
    rows = build_rows(dataset_dir)
    path = dataset_dir / "video" / "tasks.csv"
    previous: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            previous = {row["task_id"]: row for row in csv.DictReader(handle)}
    for row in rows:
        old = previous.get(row["task_id"])
        # Carry execution state forward only when the prompt is byte-identical.
        # A changed prompt is a different task, not a retry of this one.
        if old and old.get("prompt_sha256") == row["prompt_sha256"]:
            # A delivered clip was conditioned on the reference frame as it was
            # at generation time. Silently restamping the row with a new
            # reference digest would rewrite that history into something that
            # never happened — which is exactly how the Omni view mix-up stayed
            # invisible. Reject the clip first; the reject clears the output and
            # the row then legitimately describes the next attempt.
            if (old.get("output_sha256")
                    and old.get("reference_sha256")
                    and old["reference_sha256"] != row["reference_sha256"]):
                raise SystemExit(
                    f"{row['task_id']}: the reference frame changed but this row "
                    "still holds a delivered clip generated against the old one. "
                    "Recording the new digest here would claim a conditioning "
                    "that never happened.\nArchive the clip first:\n  python -m "
                    f"evals.synthetic.reject_video_clip {row['task_id']} "
                    "'reference frame corrected'"
                )
            for field in ("status", "attempts", "operator", "generated_at",
                          "duration_s", "output_sha256", "strip_sha256"):
                row[field] = old.get(field, row[field])

    # Gated after the carry-forward, not before it: the exemption above turns on
    # the row's *previous* status, and a freshly built row is always "pending".
    ungated = check_reference_provenance(rows)
    if ungated and not allow_unimported:
        listing = "\n  ".join(f"{clip_id:24} reference is {status}"
                              for clip_id, status in ungated)
        raise SystemExit(
            f"{len(ungated)} of {len(rows)} clips are conditioned on a still that "
            f"is not pass_a_accepted:\n  {listing}\n\n"
            "A clip may only be conditioned on a still the ledger records as "
            "accepted. 'pass_a_rejected' is terminal for that clip: the "
            "reference itself failed review, and regenerating the clip cannot "
            "repair it — the use case needs a different scenario or dropping.\n"
            "Pass --allow-unimported-reference to write the queue anyway as an "
            "explicitly ungated probe."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--print", dest="print_prompts", action="store_true",
                        help="print each composed prompt instead of writing tasks.csv")
    parser.add_argument("--allow-unimported-reference", action="store_true",
                        help="write the queue even though the reference stills lack "
                             "a pass_a_accepted ledger row (docs/31 Amendment B item 6)")
    args = parser.parse_args()

    if args.print_prompts:
        for row in build_rows(args.dataset_dir):
            print(f"=== {row['clip_id']}  ({row['use_case']})")
            print(row["exact_prompt"])
            print()
        return 0

    rows = write_tasks(args.dataset_dir, args.allow_unimported_reference)
    print(f"wrote {len(rows)} video tasks to "
          f"{args.dataset_dir / 'video' / 'tasks.csv'}")
    ungated = check_reference_provenance(rows)
    for clip_id, status in ungated:
        print(f"WARNING: {clip_id} is conditioned on a {status} still and "
              "cannot produce gold")
    # Counted from the reference itself, not from what the gate let through:
    # exempting retired rows must not read as having repaired them.
    accepted = sum(1 for row in rows
                   if row["reference_provenance"] == "pass_a_accepted")
    print(f"{accepted} of {len(rows)} clips have an accepted reference frame")
    for status in ("retry_pending", "suspended", "retired"):
        held = [row["clip_id"] for row in rows if row["status"] == status]
        if held:
            print(f"{status:14} {len(held):>2}  {', '.join(sorted(held))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
