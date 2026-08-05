#!/usr/bin/env python3
"""Run two independent subscription-backed Pass A reviews.

The runner reads local images through Antigravity CLI. It never calls an image
or vision API endpoint. The second review receives the same evidence but never
the first reviewer's conclusion.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.run_eval import _cli_version, _resolve_cli


MODEL_MODE = "gemini-3.5-flash-low"
VALID_DECISIONS = {"accept", "reject", "escalate"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
        if not starts:
            raise
        start = min(starts)
        closing = "]" if text[start] == "[" else "}"
        return json.loads(text[start : text.rfind(closing) + 1])


def _load_rows(dataset_dir: Path) -> list[dict[str, str]]:
    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _review_inputs(
    dataset_dir: Path,
    task_ids: set[str] | None,
    provider_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = _load_rows(dataset_dir)
    by_packet: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        row_provider = row["task_id"].split(".")[1]
        by_packet.setdefault((row["scenario_id"], row_provider), []).append(row)
    inputs = []
    for row in rows:
        if task_ids is not None and row["task_id"] not in task_ids:
            continue
        # A provider selector takes every review_pending row in that arm. The
        # unfiltered default below is not a general queue: it encodes the
        # attempts==2, scenario<=20 retry cohort of one earlier run, and would
        # silently select nothing for any other arm.
        if provider_id is not None and (
            row["task_id"].split(".")[1] != provider_id
            or row["status"] != "review_pending"
        ):
            continue
        if task_ids is None and provider_id is None and not (
            row["status"] == "review_pending"
            and int(row.get("attempts") or 0) == 2
            and int(row["scenario_id"].split("-")[1]) <= 20
        ):
            continue
        path = dataset_dir / row["output_path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        packet = by_packet[(row["scenario_id"], row["task_id"].split(".")[1])]
        inputs.append(
            {
                "task_id": row["task_id"],
                "scenario_id": row["scenario_id"],
                "provider": row["provider"],
                "room_type": row["room_type"],
                "view_id": row["view_id"],
                "image_path": str(path.resolve()),
                "image_sha256": row["output_sha256"],
                "frozen_generation_prompt": row["exact_prompt"],
                "packet_images": [
                    {
                        "view_id": candidate["view_id"],
                        "path": str(
                            (dataset_dir / candidate["output_path"]).resolve()
                        ),
                    }
                    for candidate in packet
                    if (dataset_dir / candidate["output_path"]).is_file()
                ],
            }
        )
    return inputs


def _prompt(inputs: list[dict[str, Any]], reviewer_id: str) -> str:
    return (
        "Act only as an independent Pass A visual reviewer for a bounded "
        "synthetic property-room evaluation. Do not edit any file. Use the "
        "local image-reading tool to inspect every image_path and the listed "
        "packet_images before deciding. Treat the frozen generation prompt as "
        "a hypothesis, never as visible truth.\n\n"
        "Reject when the named room is not recognisable; a required anchor is "
        "absent or malformed; geometry is unreliable; a person, logo or "
        "readable brand appears; an unintended defect falsifies the intended "
        "label; the image is illustrative rather than photographic; or packet "
        "continuity is too weak for multi-image evaluation. Escalate genuine "
        "visual uncertainty. Do not excuse a hard failure because other "
        "anchors are present.\n\n"
        "Return only a JSON array, one object per task, with exactly: task_id, "
        "decision (accept|reject|escalate), reason, requested_evidence "
        "[{name, visibility(clear|ambiguous|absent|malformed)}], hard_failures "
        "[string], continuity_notes [string]. Do not wrap the JSON in "
        f"Markdown. Reviewer context: {reviewer_id}.\n\n"
        + json.dumps(inputs, ensure_ascii=False, indent=2)
    )


def _invoke(
    cli: Path,
    model: str,
    prompt: str,
    timeout: int,
    cwd: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    command = [
        str(cli),
        "--sandbox",
        "--dangerously-skip-permissions",
        "--model",
        model,
    ]
    # The CLI rejects --effort outright for models that carry their own
    # reasoning budget. Gemini modes take it and every earlier Pass A record was
    # produced with it, so it stays for them: dropping it would change the
    # recorded protocol of runs this one is meant to be comparable with.
    if model.startswith("gemini-"):
        command += ["--effort", "low"]
    command += [
        "--print-timeout",
        f"{max(1, timeout // 60)}m",
        "--output-format",
        "json",
        "-p",
        prompt,
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout + 30,
    )
    elapsed = round(time.perf_counter() - started, 3)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    wrapper = json.loads(result.stdout)
    if wrapper.get("status") != "SUCCESS":
        # Antigravity can finish the model task and then race its cleanup:
        # the wrapper reports ERROR even though `response` contains a complete
        # JSON answer and the only error is "task is not running". Preserve
        # that answer, but accept no other non-success status here.
        cleanup_race = (
            wrapper.get("response")
            and "task is not running" in str(wrapper.get("error", ""))
        )
        if not cleanup_race:
            raise RuntimeError(str(wrapper))
    wrapper.pop("conversation_id", None)
    parsed = _extract_json(wrapper.get("response"))
    if isinstance(parsed, dict):
        parsed = parsed.get("frames") or parsed.get("decisions")
    if not isinstance(parsed, list):
        raise ValueError("Pass A reviewer did not return a JSON array")
    return parsed, wrapper, elapsed


def _validate_review(
    expected: list[dict[str, Any]],
    review: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected_ids = {item["task_id"] for item in expected}
    by_id = {item.get("task_id"): item for item in review}
    if len(by_id) != len(review):
        raise ValueError("Pass A reviewer returned duplicate task IDs")
    if set(by_id) != expected_ids:
        raise ValueError(
            f"review task mismatch: missing={sorted(expected_ids - set(by_id))}, "
            f"extra={sorted(set(by_id) - expected_ids)}"
        )
    for task_id, item in by_id.items():
        if item.get("decision") not in VALID_DECISIONS:
            raise ValueError(f"{task_id}: invalid decision")
        if not isinstance(item.get("requested_evidence"), list):
            raise ValueError(f"{task_id}: requested_evidence is not a list")
    return by_id


def review(
    dataset_dir: Path,
    output_path: Path,
    task_ids: set[str] | None = None,
    cli_path: Path | None = None,
    model: str = MODEL_MODE,
    batch_size: int = 2,
    timeout: int = 480,
    provider_id: str | None = None,
    second_model: str | None = None,
    review_type: str = "phase3_retry_pass_a_visual_screen",
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    cli = _resolve_cli(cli_path)
    cli_version = _cli_version(cli)
    # Defaulting to the same model twice preserves the recorded protocol of the
    # earlier runs exactly. Passing a different second model buys independence
    # of blind spot as well as of conclusion, which matters most when the
    # reviewer would otherwise share a family with whatever made the images.
    second = second_model or model
    inputs = _review_inputs(dataset_dir, task_ids, provider_id)
    if not inputs:
        raise ValueError("no retry outputs are ready for Pass A")
    frames: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    started_at = _utc_now()
    if output_path.exists():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        if previous.get("status") != "partial":
            raise FileExistsError(
                f"refusing to overwrite completed review: {output_path}"
            )
        if previous.get("reviewer_model_mode") != model:
            raise ValueError("partial review uses a different reviewer model")
        frames = list(previous.get("frames") or [])
        calls = list(previous.get("calls") or [])
        started_at = previous.get("reviewed_at") or started_at
    completed_list = [frame["task_id"] for frame in frames]
    if len(set(completed_list)) != len(completed_list):
        raise ValueError("partial Pass A review contains duplicate tasks")
    completed_ids = set(completed_list)
    available_ids = {item["task_id"] for item in inputs}
    if not completed_ids <= available_ids:
        raise ValueError("partial review contains tasks outside the current queue")
    remaining = [item for item in inputs if item["task_id"] not in completed_ids]

    def write_report(status: str) -> dict[str, Any]:
        counts = Counter(frame["pass_a_decision"] for frame in frames)
        report = {
            "review_type": review_type,
            "status": status,
            "reviewed_at": started_at,
            "completed_at": _utc_now() if status == "complete" else None,
            "generation_path": "Antigravity CLI independent local-image review",
            "metered_api_call": False,
            "cli_version": cli_version,
            "reviewer_model_mode": model,
            "reviewer_second_model_mode": second,
            "counts": dict(sorted(counts.items())),
            "frames": frames,
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

    for offset in range(0, len(remaining), batch_size):
        batch = remaining[offset : offset + batch_size]
        batch_number = len(calls) + 1
        print(
            f"Pass A batch {batch_number}: first review "
            f"({len(batch)} image(s))",
            flush=True,
        )
        first_prompt = _prompt(batch, f"first-{batch_number}")
        second_prompt = _prompt(batch, f"second-{batch_number}")
        first, first_wrapper, first_elapsed = _invoke(
            cli, model, first_prompt, timeout, dataset_dir
        )
        print(f"Pass A batch {batch_number}: second review", flush=True)
        second_review, second_wrapper, second_elapsed = _invoke(
            cli, second, second_prompt, timeout, dataset_dir
        )
        first_by_id = _validate_review(batch, first)
        second_by_id = _validate_review(batch, second_review)
        calls.append(
            {
                "batch": batch_number,
                "task_ids": [item["task_id"] for item in batch],
                "first_prompt_sha256": _sha256_text(first_prompt),
                "second_prompt_sha256": _sha256_text(second_prompt),
                "first_latency_seconds": first_elapsed,
                "second_latency_seconds": second_elapsed,
                "first_wrapper": first_wrapper,
                "second_wrapper": second_wrapper,
            }
        )
        for source in batch:
            task_id = source["task_id"]
            first_item = first_by_id[task_id]
            second_item = second_by_id[task_id]
            first_decision = first_item["decision"]
            second_decision = second_item["decision"]
            reconciled = (
                first_decision
                if first_decision == second_decision
                else "escalate"
            )
            if "escalate" in {first_decision, second_decision}:
                reconciled = "escalate"
            frames.append(
                {
                    **source,
                    "first_review": first_item,
                    "second_review": second_item,
                    "pass_a_decision": reconciled,
                    "pass_a_reason": (
                        first_item.get("reason")
                        if reconciled == first_decision == second_decision
                        else "Independent reviewer disagreement or escalation"
                    ),
                }
            )
        write_report("partial")
        print(f"Pass A batch {batch_number}: checkpointed", flush=True)
    return write_report("complete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list eligible immutable inputs without invoking Antigravity",
    )
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--model", default=MODEL_MODE)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=480)
    parser.add_argument("--provider", dest="provider_id",
                        help="review every review_pending row in one arm, "
                             "e.g. gemini-omni")
    parser.add_argument("--second-model",
                        help="model for the blind second check (default: same "
                             "as --model, which is the earlier runs' protocol)")
    parser.add_argument("--review-type",
                        default="phase3_retry_pass_a_visual_screen")
    args = parser.parse_args()
    task_ids = set(args.tasks) if args.tasks else None
    if args.dry_run:
        inputs = _review_inputs(args.dataset_dir, task_ids, args.provider_id)
        print(
            json.dumps(
                {
                    "review_type": "phase3_retry_pass_a_preflight",
                    "count": len(inputs),
                    "tasks": [
                        {
                            "task_id": item["task_id"],
                            "provider": item["provider"],
                            "image_path": item["image_path"],
                            "image_sha256": item["image_sha256"],
                        }
                        for item in inputs
                    ],
                },
                indent=2,
            )
        )
        return 0
    report = review(
        args.dataset_dir,
        args.output,
        task_ids,
        args.cli,
        args.model,
        args.batch_size,
        args.timeout,
        args.provider_id,
        args.second_model,
        args.review_type,
    )
    print(json.dumps(report["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
