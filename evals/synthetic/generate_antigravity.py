#!/usr/bin/env python3
"""Generate Google-side synthetic packets through Antigravity CLI only.

Each packet submits the four frozen per-view prompts in one Antigravity
operator run. The operator must invoke ``generate_image`` independently for
each view and save the unedited original at the task queue's exact path.
No image-generation API credential or endpoint is used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.run_eval import _cli_version, _resolve_cli


MODEL_MODE = "gemini-3.5-flash-low"
PROVIDER_ID = "antigravity-builtin"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _packet_prompt(
    scenario_id: str,
    rows: list[dict[str, str]],
    dataset_dir: Path,
    preexisting: list[dict[str, Any]],
) -> str:
    tasks = []
    for row in rows:
        tasks.append(
            {
                "task_id": row["task_id"],
                "view_id": row["view_id"],
                "exact_generation_prompt": row["exact_prompt"],
                "required_output_path": str(
                    (dataset_dir / row["output_path"]).resolve()
                ),
            }
        )
    existing_note = ""
    if preexisting:
        existing_note = (
            "These earlier outputs already exist and are immutable; do not "
            "overwrite them: "
            + json.dumps(preexisting, ensure_ascii=False)
            + ". Generate only the tasks listed below. "
        )
    return (
        "Act only as the image-generation operator for this bounded synthetic "
        "property-room evaluation. Do not edit source code, documentation, "
        "task CSV files or review records.\n\n"
        f"Complete the four-view packet for {scenario_id}. "
        + existing_note
        + "When A-wide is among the tasks, generate and save it first. For "
        "every later view, invoke generate_image with the saved A-wide image "
        "as an explicit visual reference/input as well as that task's exact "
        "prompt. Preserve the same room geometry, fixed "
        "fittings, finishes, windows, doors and object positions while moving "
        "the camera to the requested viewpoint. If the tool cannot accept the "
        "reference image, stop and report that limitation rather than "
        "generating unrelated rooms. Save the original generated JPEG bytes "
        "at required_output_path. Do not crop, resize, retouch, recompress or "
        "substitute an earlier image. Do not create a collage. Do not copy one "
        "view to another. The four outputs must be distinct files.\n\n"
        "After the required tool calls finish, verify every listed required "
        "path and calculate its SHA-256. Return only a JSON object with "
        "scenario_id, tool_name, backend_model (use \"unknown\" unless the "
        "tool explicitly exposes it), and outputs [{task_id,path,sha256}].\n\n"
        + json.dumps(tasks, ensure_ascii=False, indent=2)
    )


def _load_packets(
    dataset_dir: Path,
    scenario_ids: set[str] | None,
) -> dict[str, list[dict[str, str]]]:
    with (dataset_dir / "tasks.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    all_packets: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if f".{PROVIDER_ID}." not in row["task_id"]:
            continue
        if scenario_ids and row["scenario_id"] not in scenario_ids:
            continue
        all_packets.setdefault(row["scenario_id"], []).append(row)
    packets = {
        scenario_id: packet
        for scenario_id, packet in all_packets.items()
        if any(
            row["status"] in {"pending", "retry_pending"}
            for row in packet
        )
    }
    for scenario_id, packet in packets.items():
        if len(packet) != 4:
            raise ValueError(
                f"{scenario_id}: expected four Antigravity tasks, "
                f"found {len(packet)}"
            )
        packet.sort(key=lambda row: row["view_id"])
    return packets


def _validate_packet(
    rows: list[dict[str, str]],
    dataset_dir: Path,
) -> list[dict[str, Any]]:
    outputs = []
    hashes = set()
    for row in rows:
        path = dataset_dir / row["output_path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        with Image.open(path) as image:
            width, height = image.size
            if width < 1024 or height < 768:
                raise ValueError(
                    f"{row['task_id']}: {width}x{height} below 1024x768"
                )
            if image.format != "JPEG":
                raise ValueError(
                    f"{row['task_id']}: expected JPEG, found {image.format}"
                )
        digest = _sha256(path)
        if digest in hashes:
            raise ValueError(
                f"{row['scenario_id']}: duplicate bytes within packet"
            )
        hashes.add(digest)
        outputs.append(
            {
                "task_id": row["task_id"],
                "path": str(path.resolve()),
                "sha256": digest,
                "width": width,
                "height": height,
            }
        )
    return outputs


def generate_packet(
    scenario_id: str,
    rows: list[dict[str, str]],
    *,
    dataset_dir: Path,
    cli: Path,
    model: str,
) -> dict[str, Any]:
    attempt = max(
        1,
        max(int(row.get("attempts") or 0) for row in rows) + 1,
    )
    run_dir = dataset_dir / "generation_runs" / "antigravity"
    base_run_path = run_dir / f"{scenario_id}.json"
    run_path = (
        base_run_path
        if attempt == 1 and not base_run_path.exists()
        else run_dir / f"{scenario_id}-attempt-{attempt}.json"
    )
    if run_path.exists() and all(
        (dataset_dir / row["output_path"]).is_file() for row in rows
    ):
        outputs = _validate_packet(rows, dataset_dir)
        return {
            "scenario_id": scenario_id,
            "status": "cached",
            "outputs": outputs,
        }
    preexisting = []
    missing_rows = []
    for row in rows:
        output = dataset_dir / row["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            preexisting.append(
                {
                    "task_id": row["task_id"],
                    "path": str(output.resolve()),
                    "sha256": _sha256(output),
                }
            )
        elif row["status"] in {"pending", "retry_pending"}:
            missing_rows.append(row)
        else:
            raise FileNotFoundError(
                f"{row['task_id']}: accepted packet reference is missing"
            )
    if not missing_rows:
        outputs = _validate_packet(rows, dataset_dir)
        record = {
            "schema_version": 1,
            "scenario_id": scenario_id,
            "recorded_at": _utc_now(),
            "generation_path": "Antigravity CLI built-in generate_image",
            "backend_model": "unknown",
            "metered_api_call": False,
            "cli_version": _cli_version(cli),
            "operator_model_mode": model,
            "status": "files_recovered_after_wrapper_error",
            "provenance_warning": (
                "All four original files were present, but the prior CLI "
                "wrapper returned ERROR and no successful raw run record was "
                "available. File hashes and task timestamps are retained."
            ),
            "outputs": outputs,
        }
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {"scenario_id": scenario_id, "status": "recovered", **record}
    prompt = _packet_prompt(
        scenario_id,
        missing_rows,
        dataset_dir,
        preexisting,
    )
    command = [
        str(cli),
        "--sandbox",
        "--dangerously-skip-permissions",
        "--model",
        model,
        "--effort",
        "low",
        "--print-timeout",
        "8m",
        "--output-format",
        "json",
        "-p",
        prompt,
    ]
    started_at = _utc_now()
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=dataset_dir,
        capture_output=True,
        text=True,
        timeout=510,
    )
    elapsed = round(time.perf_counter() - started, 3)
    if result.returncode:
        diagnostic = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"{scenario_id}: Antigravity exited {result.returncode}: "
            f"{diagnostic}"
        )
    wrapper = json.loads(result.stdout)
    if wrapper.get("status") != "SUCCESS":
        raise RuntimeError(f"{scenario_id}: {wrapper}")
    # Conversation IDs are provider session data, not dataset provenance.
    wrapper.pop("conversation_id", None)
    outputs = _validate_packet(rows, dataset_dir)
    record = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "latency_seconds": elapsed,
        "generation_path": "Antigravity CLI built-in generate_image",
        "backend_model": "unknown",
        "metered_api_call": False,
        "cli_version": _cli_version(cli),
        "operator_model_mode": model,
        "prompt": prompt,
        "raw_cli_response": wrapper,
        "stderr": result.stderr.strip(),
        "preexisting_outputs": preexisting,
        "outputs": outputs,
    }
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {"scenario_id": scenario_id, "status": "generated", **record}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET
    )
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument("--model", default=MODEL_MODE)
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    cli = _resolve_cli(args.cli)
    packets = _load_packets(
        args.dataset_dir,
        set(args.scenarios) if args.scenarios else None,
    )
    if not packets:
        print("No pending Antigravity packets.")
        return 0
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(
                generate_packet,
                scenario_id,
                rows,
                dataset_dir=args.dataset_dir,
                cli=cli,
                model=args.model,
            ): scenario_id
            for scenario_id, rows in sorted(packets.items())
        }
        for future in as_completed(futures):
            scenario_id = futures[future]
            try:
                record = future.result()
                print(
                    f"{scenario_id}: {record['status']} "
                    f"({len(record['outputs'])} images)"
                )
            except Exception as exc:
                failures.append((scenario_id, str(exc)))
                print(f"{scenario_id}: FAILED: {exc}")
    if failures:
        raise SystemExit(
            f"{len(failures)} packet(s) failed: "
            + "; ".join(f"{sid}: {error}" for sid, error in failures)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
