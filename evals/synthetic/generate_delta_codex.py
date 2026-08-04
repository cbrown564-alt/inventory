#!/usr/bin/env python3
"""Generate Phase 3.5 delta frames through Codex's built-in imagegen only.

One ``codex exec`` run per view. The accepted T0 frame is attached as the
visual reference and the frozen queue prompt is passed through verbatim; no
image-generation API credential or endpoint is used (docs/31 permanent
generation boundary).

The run verifies the prompt that actually reached the image tool. A driver
that wraps a prompt in instructions is a driver that can have its prompt
paraphrased, and the ledger would then record a prompt that never generated
anything — provenance that reads as exact and is not. The agent reports the
string it passed and this module compares it by hash to the queue.

Recording provenance is deliberately not done here. ``record_delta_outputs``
owns that, and it owns the copy and duplicate checks that decide whether a
frame is fit to record at all.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.synthetic.build_tasks import DEFAULT_DATASET

#: docs/31: Codex built-in imagegen is the sole GPT Image 2 route.
GENERATION_PATH = "Codex built-in imagegen / GPT Image 2"
OPERATOR = "Codex GPT Image 2 built-in imagegen"

#: ``codex exec`` appends piped stdin to the prompt and waits for EOF, so a
#: driver that leaves stdin open hangs before it generates anything.
STDIN = subprocess.DEVNULL

_PROMPT_BLOCK = re.compile(r"```(?:text)?\n(.*?)\n```", re.S)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_cli(cli: Path | None = None) -> Path:
    if cli and cli.is_file():
        return cli.resolve()
    discovered = shutil.which(str(cli) if cli else "codex")
    if not discovered:
        raise FileNotFoundError("Codex CLI not found; install codex or pass --cli")
    return Path(discovered).resolve()


def cli_version(cli: Path) -> str:
    result = subprocess.run(
        [str(cli), "--version"],
        capture_output=True, check=True, text=True, timeout=60, stdin=STDIN,
    )
    return result.stdout.strip()


def build_instruction(row: dict[str, str]) -> str:
    """Wrap the frozen prompt without altering it.

    The wrapper carries delivery instructions only. Everything that decides
    what the image contains lives inside the markers and is passed through.
    """
    return (
        "Generate exactly one image with your built-in image generation tool, "
        "using the attached image as the visual reference.\n\n"
        "Pass the text between the <prompt> markers to the image tool "
        "VERBATIM — no additions, omissions, rewording or summarising.\n\n"
        f"<prompt>\n{row['exact_prompt']}\n</prompt>\n\n"
        f"Save the returned image unedited to {row['output_path']} (relative "
        "to your working root). Do not edit the image. Do not modify, move or "
        "delete any other file. Do not run git.\n\n"
        "Then report the exact string you passed to the image tool inside a "
        "```text fenced block, and nothing else inside that block."
    )


def reported_prompt(message: str) -> str | None:
    """The prompt the agent says it passed, from the last fenced block."""
    blocks = _PROMPT_BLOCK.findall(message or "")
    return blocks[-1].strip() if blocks else None


def build_command(
    dataset_dir: Path,
    row: dict[str, str],
    cli: Path,
    last_message: Path,
) -> list[str]:
    """Argument order matters here, so it is built in one place and tested.

    ``-i/--image`` is variadic. With the prompt placed directly after it, the
    prompt is parsed as a second image filename, Codex finds no prompt
    argument and falls back to reading one from stdin — which is closed — and
    the run ends having generated nothing. Keeping a flag between ``-i`` and
    the prompt is what makes the prompt a positional argument.
    """
    return [
        str(cli), "exec",
        "-C", str(dataset_dir.resolve()),
        "-i", row["reference_path"],
        "-s", "workspace-write",
        "-o", str(last_message),
        build_instruction(row),
    ]


def pending_rows(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
    task_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    with (dataset_dir / "delta_tasks.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = []
    for row in rows:
        if delta_ids is not None and row["delta_id"] not in delta_ids:
            continue
        if task_ids is not None and row["task_id"] not in task_ids:
            continue
        if row["status"] not in {"pending", "retry_pending"}:
            continue
        if (dataset_dir / row["output_path"]).is_file():
            continue
        selected.append(row)
    return selected


def generate_one(
    dataset_dir: Path,
    row: dict[str, str],
    cli: Path,
    timeout: int,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    output = dataset_dir / row["output_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    started = _utc_now()
    with tempfile.TemporaryDirectory() as workspace:
        final = Path(workspace) / "last-message.txt"
        result = subprocess.run(
            build_command(dataset_dir, row, cli, final),
            capture_output=True, text=True, timeout=timeout, stdin=STDIN,
            cwd=str(dataset_dir.resolve()),
        )
        message = final.read_text(encoding="utf-8") if final.is_file() else result.stdout
    message = message or ""
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{row['task_id']}.log").write_text(
            message + "\n--- stderr ---\n" + (result.stderr or ""), encoding="utf-8"
        )

    used = reported_prompt(message)
    outcome = {
        "task_id": row["task_id"],
        "delta_id": row["delta_id"],
        "view_id": row["view_id"],
        "started_at": started,
        "finished_at": _utc_now(),
        "exit_code": result.returncode,
        "generation_path": GENERATION_PATH,
        "metered_api_call": False,
        "output_written": output.is_file(),
        "prompt_verbatim": used is not None and used == row["exact_prompt"].strip(),
        "prompt_reported": used is not None,
    }
    if not outcome["output_written"]:
        outcome["error"] = "no image was saved at the queued output path"
    elif not outcome["prompt_verbatim"]:
        # An unverifiable prompt cannot be recorded as the exact prompt, and a
        # frame whose prompt is unknown is not evidence. Remove it so the
        # attempt does not silently become gold on a later record run.
        output.unlink()
        outcome["output_written"] = False
        outcome["error"] = (
            "the prompt reaching the image tool did not match the queue "
            "verbatim; the frame was discarded"
        )
    return outcome


def generate(
    dataset_dir: Path,
    delta_ids: set[str] | None = None,
    task_ids: set[str] | None = None,
    cli: Path | None = None,
    timeout: int = 900,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    resolved = resolve_cli(cli)
    rows = pending_rows(dataset_dir, delta_ids, task_ids)
    results = []
    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] generating {row['task_id']}", flush=True)
        results.append(generate_one(dataset_dir, row, resolved, timeout, log_dir))
        state = "ok" if results[-1]["output_written"] else results[-1].get("error")
        print(f"    {state}", flush=True)
    return {
        "record_type": "phase35_delta_codex_run",
        "ran_at": _utc_now(),
        "cli_version": cli_version(resolved),
        "generation_path": GENERATION_PATH,
        "operator": OPERATOR,
        "metered_api_call": False,
        "attempted": len(results),
        "written": sum(1 for item in results if item["output_written"]),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--delta", action="append", dest="deltas")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list the frames that would be generated without calling Codex",
    )
    args = parser.parse_args()
    delta_ids = set(args.deltas) if args.deltas else None
    task_ids = set(args.tasks) if args.tasks else None
    if args.dry_run:
        rows = pending_rows(args.dataset_dir, delta_ids, task_ids)
        for row in rows:
            print(f"{row['task_id']}  ref={row['reference_path']}")
        print(f"{len(rows)} frame(s) pending")
        return 0
    report = generate(
        args.dataset_dir, delta_ids, task_ids, args.cli, args.timeout, args.log_dir
    )
    print(f"Generated {report['written']}/{report['attempted']} delta frame(s)")
    return 0 if report["written"] == report["attempted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
