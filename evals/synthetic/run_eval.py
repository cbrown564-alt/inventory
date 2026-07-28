#!/usr/bin/env python3
"""Run the frozen Phase 1 prompt comparison and cache every raw response.

The comparison keeps the production backend, schema and whole-room
architecture fixed.  Only complete, verified four-view packets are eligible.
Existing output files are never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeinventory.describe import ITEM_SCHEMA, OpenAICompatBackend
from homeinventory.dotenv import load_dotenv
from homeinventory.schema import Photo

from evals.synthetic.build_tasks import DEFAULT_DATASET
from evals.synthetic.prompts import PROMPTS, prompt_sha256


DEFAULT_MODEL = "gemini-3.5-flash"
ARCHITECTURE_ID = "production-whole-room-v1"
SCHEMA_VERSION = 1
PRICING = {
    "model": DEFAULT_MODEL,
    "currency": "USD",
    "input_per_million_tokens": 1.50,
    "output_per_million_tokens": 9.00,
    "source": "https://ai.google.dev/gemini-api/docs/pricing",
    "checked_at": "2026-07-28",
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _usage_cost(usage: dict[str, Any]) -> float | None:
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    cost = (
        input_tokens * PRICING["input_per_million_tokens"]
        + output_tokens * PRICING["output_per_million_tokens"]
    ) / 1_000_000
    return round(cost, 6)


class RecordingBackend(OpenAICompatBackend):
    """Production backend with the last raw provider response retained."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.last_response: dict[str, Any] | None = None

    def _post(self, payload: dict) -> dict:
        response = super()._post(payload)
        self.last_response = response
        return response


def build_run_plan(
    dataset_dir: Path = DEFAULT_DATASET,
    prompt_ids: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """Return deterministic runs for complete verified GPT Image 2 packets."""
    selected_prompts = prompt_ids or list(PROMPTS)
    unknown = sorted(set(selected_prompts) - set(PROMPTS))
    if unknown:
        raise ValueError(f"unknown prompt id(s): {', '.join(unknown)}")
    config = _json(dataset_dir / "dataset.json")
    frozen_hashes = config["phase_1_prompt_comparison"]["prompts"]
    for prompt_id in selected_prompts:
        actual_hash = prompt_sha256(PROMPTS[prompt_id])
        if frozen_hashes.get(prompt_id) != actual_hash:
            raise ValueError(
                f"{prompt_id} differs from its frozen dataset hash; "
                "do not run after prompt drift"
            )

    with (dataset_dir / "tasks.csv").open(newline="", encoding="utf-8") as handle:
        tasks = list(csv.DictReader(handle))
    tasks_by_packet: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for row in tasks:
        key = (row["scenario_id"], row["model_display_name"])
        tasks_by_packet.setdefault(key, {})[row["view_id"]] = row

    plan: list[dict[str, Any]] = []
    for review_path in sorted((dataset_dir / "reviews").glob("RP-*.json")):
        review = _json(review_path)
        if (
            review.get("review_status") != "verified_synthetic_gold"
            or review.get("model_display_name") != "GPT Image 2"
        ):
            continue
        scenario_id = review["scenario_id"]
        packet = tasks_by_packet.get((scenario_id, "GPT Image 2"), {})
        accepted_ids = [
            frame["frame_id"]
            for frame in review["pass_a"]["frames"]
            if frame["decision"] == "accepted"
        ]
        if len(accepted_ids) != 4 or set(accepted_ids) != set(packet):
            continue
        if any(
            packet[frame_id]["status"] not in {"accepted", "pass_a_accepted"}
            for frame_id in accepted_ids
        ):
            continue

        scenario = _json(dataset_dir / "scenarios" / f"{scenario_id}.json")
        inputs = []
        for frame_id in accepted_ids:
            row = packet[frame_id]
            image_path = dataset_dir / row["output_path"]
            if not image_path.is_file():
                raise FileNotFoundError(image_path)
            inputs.append(
                {
                    "frame_id": frame_id,
                    "relative_path": row["output_path"].replace("\\", "/"),
                    "sha256": _sha256_file(image_path),
                }
            )
        for prompt_id in selected_prompts:
            output = (
                dataset_dir
                / "outputs"
                / model
                / prompt_id
                / f"{scenario_id}.gpt-image-2.json"
            )
            plan.append(
                {
                    "scenario_id": scenario_id,
                    "room_type": scenario["room_type"],
                    "image_provider": "OpenAI",
                    "image_model": "GPT Image 2",
                    "prompt_id": prompt_id,
                    "model": model,
                    "inputs": inputs,
                    "output": output,
                }
            )
    return plan


def _rendered_request(
    *,
    room_type: str,
    prompt_id: str,
    prompt: str,
    inputs: list[dict[str, str]],
    model: str,
) -> dict[str, Any]:
    """Record the model-facing text and image hashes without duplicating bytes."""
    return {
        "model": model,
        "system_instruction": prompt,
        "user_instruction": (
            f'These photos all show the room: "{room_type}".\n'
            "Produce the complete item schedule for this room."
        ),
        "images": [
            {"photo_id": item["frame_id"], "sha256": item["sha256"]}
            for item in inputs
        ],
        "response_schema": ITEM_SCHEMA,
    }


def run_one(
    run: dict[str, Any],
    dataset_dir: Path = DEFAULT_DATASET,
) -> dict[str, Any]:
    output = Path(run["output"])
    if output.exists():
        raise FileExistsError(
            f"{output} already exists; cached evaluation outputs are immutable"
        )
    prompt = PROMPTS[run["prompt_id"]]
    rendered_request = _rendered_request(
        room_type=run["room_type"],
        prompt_id=run["prompt_id"],
        prompt=prompt,
        inputs=run["inputs"],
        model=run["model"],
    )
    photos = [
        Photo(
            id=item["frame_id"],
            path=item["relative_path"],
            room=run["room_type"],
            sha256=item["sha256"],
        )
        for item in run["inputs"]
    ]
    paths = [dataset_dir / item["relative_path"] for item in run["inputs"]]
    backend = RecordingBackend(
        model=run["model"],
        system_prompt=prompt,
        item_schema=ITEM_SCHEMA,
    )
    started_at = _utc_now()
    started = time.perf_counter()
    summary, items = backend.describe_room(run["room_type"], photos, paths, {})
    elapsed = round(time.perf_counter() - started, 3)
    if backend.last_response is None:
        raise RuntimeError("provider returned no response")
    usage = backend.last_response.get("usage") or {}
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": (
            f"{run['scenario_id']}.{run['image_model']}.{run['model']}."
            f"{run['prompt_id']}"
        ),
        "started_at": started_at,
        "completed_at": _utc_now(),
        "dataset_id": "synthetic-room-eval",
        "dataset_phase": "phase-1-representative-slice",
        "scenario_id": run["scenario_id"],
        "room_type": run["room_type"],
        "image_provider": run["image_provider"],
        "image_model": run["image_model"],
        "backend_provider": "Google",
        "backend_model": run["model"],
        "architecture_id": ARCHITECTURE_ID,
        "sampling_controls": {
            "temperature": "production provider default",
            "top_p": "production provider default",
        },
        "retry_policy": "none; a failed call remains failed for operator review",
        "prompt_id": run["prompt_id"],
        "prompt_sha256": prompt_sha256(prompt),
        "response_schema_sha256": _sha256_json(ITEM_SCHEMA),
        "inputs": run["inputs"],
        "rendered_request": rendered_request,
        "raw_response": backend.last_response,
        "parsed_output": {
            "room_summary": summary,
            "items": [asdict(item) for item in items],
        },
        "latency_seconds": elapsed,
        "usage": usage,
        "estimated_cost": {
            **PRICING,
            "amount": _usage_cost(usage),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset_dir", nargs="?", type=Path, default=DEFAULT_DATASET
    )
    parser.add_argument(
        "--prompt",
        action="append",
        choices=sorted(PROMPTS),
        dest="prompts",
        help="prompt id to run; repeat to select both (default: both)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the immutable run plan without calling the provider",
    )
    args = parser.parse_args()
    plan = build_run_plan(args.dataset_dir, args.prompts, args.model)
    if not plan:
        raise SystemExit("no complete verified four-view packets are eligible")
    if args.dry_run:
        printable = [
            {**run, "output": str(run["output"])}
            for run in plan
        ]
        print(json.dumps(printable, indent=2))
        return 0

    load_dotenv()
    for run in plan:
        if Path(run["output"]).exists():
            print(f"{run['output']}: cached; skipped without overwrite")
            continue
        record = run_one(run, args.dataset_dir)
        print(
            f"{record['run_id']}: {record['latency_seconds']}s, "
            f"${record['estimated_cost']['amount']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
