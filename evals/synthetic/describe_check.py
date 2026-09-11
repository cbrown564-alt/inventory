#!/usr/bin/env python3
"""Describe check: gold draft, production describe, invent/omit diagnostics.

Implements the simplified synthetic programme agreed 6 Aug 2026:
spec-seeded gold + cross-family (Gemini) fill, production describe on twelve
GPT Image 2 packets, invent/omit rates per claim type, one results note.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.run_eval import name_match
from evals.synthetic.build_tasks import DEFAULT_DATASET
from homeinventory.describe import OpenAICompatBackend
from homeinventory.schema import CLEANLINESS_GRADES, CONDITION_GRADES

DESCRIBE_CHECK_SCENARIOS = [
    "RP-001",
    "RP-002",
    "RP-004",
    "RP-006",
    "RP-007",
    "RP-009",
    "RP-011",
    "RP-013",
    "RP-015",
    "RP-016",
    "RP-021",
    "RP-024",
]
PROVIDER = "gpt-image-2"
VIEWS = ["A-wide", "B-reverse", "C-inventory", "D-condition"]
MATCH_THRESHOLD = 0.6
GOLD_MODEL = "gemini-3.5-flash"
DESCRIBE_BACKEND = "openai"
DESCRIBE_MODEL = "gemini-3.5-flash"

DEFECT_WORDS = {
    "chip", "chips", "chipped", "crack", "cracks", "cracked", "scuff",
    "scuffs", "scuffed", "scratch", "scratches", "scratched", "stain",
    "stains", "stained", "mould", "mold", "damp", "damage", "damaged",
    "swollen", "swell", "fray", "frayed", "tear", "torn", "wear", "worn",
    "dent", "dented", "loose", "peeling", "hairline",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _tokens(value: str) -> set[str]:
    return set(_norm(value).split())


def _work_dir(dataset_dir: Path) -> Path:
    return dataset_dir / "outputs" / "describe-check"


def _gold_dir(dataset_dir: Path) -> Path:
    return _work_dir(dataset_dir) / "gold"


def _reports_dir(dataset_dir: Path) -> Path:
    return dataset_dir / "reports"


def load_scenario(dataset_dir: Path, scenario_id: str) -> dict[str, Any]:
    return json.loads(
        (dataset_dir / "scenarios" / f"{scenario_id}.json").read_text(encoding="utf-8")
    )


def packet_image_paths(dataset_dir: Path, scenario_id: str) -> dict[str, Path]:
    base = dataset_dir / "images" / "openai" / "gpt-image-2"
    paths = {view: base / f"{scenario_id}-{view}.png" for view in VIEWS}
    missing = [view for view, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{scenario_id}: missing views {missing}")
    return paths


def assert_packets_complete(dataset_dir: Path) -> None:
    rows = list(csv.DictReader((dataset_dir / "tasks.csv").open(newline="", encoding="utf-8")))
    for scenario_id in DESCRIBE_CHECK_SCENARIOS:
        accepted = {
            row["view_id"]
            for row in rows
            if row["scenario_id"] == scenario_id
            and row["model_display_name"] == "GPT Image 2"
            and row["status"] == "pass_a_accepted"
        }
        if set(VIEWS) - accepted:
            raise ValueError(
                f"{scenario_id}: incomplete GPT packet; missing "
                f"{sorted(set(VIEWS) - accepted)}"
            )


def _guess_cleanliness(room_cleanliness: str) -> str:
    text = room_cleanliness.casefold()
    if "professional" in text:
        return "professionally cleaned"
    if any(
        token in text
        for token in (
            "clutter",
            "difficult",
            "obscured",
            "requires",
            "dirty",
            "soiled",
        )
    ):
        return "requires cleaning"
    return "cleaned to domestic standard"


def seed_claims(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Build identity + defect seeds from the scene specification."""
    by_name: dict[str, dict[str, Any]] = {}
    room_cleanliness = _guess_cleanliness(scenario.get("cleanliness") or "")
    for view in scenario["views"]:
        frame_id = view["id"]
        for name in view.get("intended_visible_items") or []:
            key = _norm(name)
            claim = by_name.get(key)
            if claim is None:
                claim = {
                    "name": name,
                    "aliases": [],
                    "condition": "good",
                    "cleanliness": room_cleanliness,
                    "defects": [],
                    "evidence_frame_ids": [],
                    "source": "spec",
                }
                by_name[key] = claim
            if frame_id not in claim["evidence_frame_ids"]:
                claim["evidence_frame_ids"].append(frame_id)
        for defect in view.get("intended_defects") or []:
            # Prefer the seed item with the strongest token overlap with the defect.
            defect_tokens = _tokens(defect)
            candidates = list(view.get("intended_visible_items") or [])

            def _defect_item_score(name: str) -> tuple[int, int, int]:
                name_norm = _norm(name)
                name_tokens = _tokens(name)
                overlap = len(name_tokens & defect_tokens)
                whole = 1 if name_norm and name_norm in _norm(defect) else 0
                return (-whole, -overlap, -len(name_norm))

            ranked = sorted(candidates, key=_defect_item_score)
            attached = False
            if ranked:
                name = ranked[0]
                key = _norm(name)
                if key in by_name and (
                    _defect_item_score(name)[0] < 0 or _defect_item_score(name)[1] < 0
                ):
                    if defect not in by_name[key]["defects"]:
                        by_name[key]["defects"].append(defect)
                    if by_name[key]["condition"] == "good":
                        by_name[key]["condition"] = "fair"
                    if frame_id not in by_name[key]["evidence_frame_ids"]:
                        by_name[key]["evidence_frame_ids"].append(frame_id)
                    attached = True
            if not attached:
                key = _norm(defect)
                by_name[key] = {
                    "name": defect,
                    "aliases": [],
                    "condition": "fair",
                    "cleanliness": room_cleanliness,
                    "defects": [defect],
                    "evidence_frame_ids": [frame_id],
                    "source": "spec",
                }
    # One claim owns a given defect wording — drop duplicates from AI/seed bleed.
    seen_defects: set[str] = set()
    for claim in by_name.values():
        kept = []
        for defect in claim["defects"]:
            key = _norm(defect)
            if key in seen_defects:
                continue
            seen_defects.add(key)
            kept.append(defect)
        claim["defects"] = kept
    return list(by_name.values())


def _encode_image(path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return mime, data


GOLD_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "condition": {"type": "string", "enum": CONDITION_GRADES},
                    "cleanliness": {"type": "string", "enum": CLEANLINESS_GRADES},
                    "defects": {"type": "array", "items": {"type": "string"}},
                    "evidence_frame_ids": {
                        "type": "array",
                        "items": {"type": "string", "enum": VIEWS},
                    },
                    "source": {
                        "type": "string",
                        "enum": ["spec", "ai_fill", "spec+ai_fill"],
                    },
                },
                "required": [
                    "name",
                    "aliases",
                    "condition",
                    "cleanliness",
                    "defects",
                    "evidence_frame_ids",
                    "source",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


def fill_gold_with_gemini(
    scenario: dict[str, Any],
    image_paths: dict[str, Path],
    seeds: list[dict[str, Any]],
    model: str = GOLD_MODEL,
) -> list[dict[str, Any]]:
    """Cross-family vision fill for grades and report-visible surfaces."""
    backend = OpenAICompatBackend(model=model)
    content: list[dict[str, Any]] = []
    for view, path in image_paths.items():
        mime, data = _encode_image(path)
        content.append({"type": "text", "text": f"Frame {view}:"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}"},
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                "You are drafting gold labels for a tenancy inventory & schedule "
                "of condition report. The images are synthetic evaluation stills.\n"
                f"Room type: {scenario['room_type']}.\n"
                f"Room cleanliness cue from the scene spec: {scenario.get('cleanliness')}.\n\n"
                "Seed claims from the scene specification (identity + intended defects):\n"
                f"{json.dumps(seeds, indent=2)}\n\n"
                "Return a complete gold claim list the tenancy report may show a reader:\n"
                "- Keep every seed claim that is actually visible; drop only if truly absent.\n"
                "- Preserve every intended defect on the same seed item; do not move or "
                "duplicate a defect onto another claim. Refine localisation only if clearly "
                "visible; never invent defects not in the seed and not visible.\n"
                "- Add fabric/surfaces the report would list when clearly visible "
                "(walls, ceiling, floor, doors, windows, skirting) with grades.\n"
                "- Use only the condition and cleanliness enums in the schema.\n"
                "- evidence_frame_ids must be a subset of A-wide, B-reverse, "
                "C-inventory, D-condition.\n"
                "- source=spec for unchanged seeds, spec+ai_fill when you edit a seed, "
                "ai_fill for new surface/fabric claims."
            ),
        }
    )
    resp = backend._post(
        {
            "model": backend.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You label visible property evidence for evaluation gold. "
                        "Never invent defects. Prefer omit over guess."
                    ),
                },
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "describe_check_gold",
                    "strict": True,
                    "schema": GOLD_SCHEMA,
                },
            },
        }
    )
    payload = json.loads(resp["choices"][0]["message"]["content"])
    return payload["claims"]


def write_gold(
    dataset_dir: Path,
    scenario_id: str,
    claims: list[dict[str, Any]],
    *,
    filled: bool,
) -> Path:
    scenario = load_scenario(dataset_dir, scenario_id)
    image_paths = packet_image_paths(dataset_dir, scenario_id)
    record = {
        "schema_version": 1,
        "record_type": "describe_check_gold",
        "packet_id": f"{scenario_id}.{PROVIDER}",
        "scenario_id": scenario_id,
        "room_type": scenario["room_type"],
        "generator": "GPT Image 2",
        "gold_method": (
            "spec-seeded + gemini-3.5-flash cross-family fill"
            if filled
            else "spec-seeded only"
        ),
        "created_at": _utc_now(),
        "image_sha256": {
            view: _sha256_file(path) for view, path in image_paths.items()
        },
        "claims": claims,
        "spot_check": {
            "status": "pending",
            "rule": (
                "Owner reviews every defect claim, every post-score invent/omit "
                "disagreement, plus a small random sample of other claims."
            ),
        },
    }
    out = _gold_dir(dataset_dir) / f"{scenario_id}.{PROVIDER}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return out


def draft_gold(
    dataset_dir: Path,
    scenario_ids: list[str] | None = None,
    *,
    fill: bool = True,
) -> list[Path]:
    ids = scenario_ids or DESCRIBE_CHECK_SCENARIOS
    assert_packets_complete(dataset_dir)
    written: list[Path] = []
    for scenario_id in ids:
        scenario = load_scenario(dataset_dir, scenario_id)
        seeds = seed_claims(scenario)
        if fill:
            claims = fill_gold_with_gemini(
                scenario, packet_image_paths(dataset_dir, scenario_id), seeds
            )
        else:
            claims = seeds
        written.append(write_gold(dataset_dir, scenario_id, claims, filled=fill))
        print(f"gold {scenario_id}: {len(claims)} claims", flush=True)
    return written


def stage_capture(dataset_dir: Path, scenario_id: str) -> Path:
    scenario = load_scenario(dataset_dir, scenario_id)
    room = scenario["room_type"]
    capture = _work_dir(dataset_dir) / "captures" / scenario_id / "capture"
    room_dir = capture / room
    if room_dir.exists():
        shutil.rmtree(room_dir)
    room_dir.mkdir(parents=True)
    for view, path in packet_image_paths(dataset_dir, scenario_id).items():
        shutil.copy2(path, room_dir / f"{view}{path.suffix}")
    return capture


def run_describe(
    dataset_dir: Path,
    scenario_ids: list[str] | None = None,
) -> list[Path]:
    ids = scenario_ids or DESCRIBE_CHECK_SCENARIOS
    assert_packets_complete(dataset_dir)
    # Do not Path.resolve() sys.executable: under uv it points at the shared
    # CPython install, not the project venv that holds the console script.
    homeinventory = Path(sys.executable).parent / "homeinventory"
    if not homeinventory.is_file():
        homeinventory = Path(shutil.which("homeinventory") or "")
    if not homeinventory.is_file():
        raise FileNotFoundError("homeinventory CLI not found in venv or PATH")
    reports: list[Path] = []
    for scenario_id in ids:
        capture = stage_capture(dataset_dir, scenario_id)
        out = _work_dir(dataset_dir) / "captures" / scenario_id / "report"
        out.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(homeinventory),
            "build",
            str(capture),
            "-o",
            str(out),
            "--photo-mode",
            "--no-detect",
            "--no-pdf",
            "--backend",
            DESCRIBE_BACKEND,
            "--model",
            DESCRIBE_MODEL,
            "--address",
            f"Describe check {scenario_id}",
            "--inspector",
            "describe-check",
        ]
        print(f"describe {scenario_id}…", flush=True)
        result = subprocess.run(cmd, check=False, text=True, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"describe failed for {scenario_id}:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        inventory = out / "inventory.json"
        if not inventory.is_file():
            raise FileNotFoundError(inventory)
        meta = {
            "scenario_id": scenario_id,
            "packet_id": f"{scenario_id}.{PROVIDER}",
            "finished_at": _utc_now(),
            "backend": DESCRIBE_BACKEND,
            "model": DESCRIBE_MODEL,
            "inventory_path": str(inventory.relative_to(dataset_dir)),
            "inventory_sha256": _sha256_file(inventory),
        }
        meta_path = out / "describe-check-run.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        reports.append(inventory)
        print(f"  wrote {inventory}", flush=True)
    return reports


def _assign(
    predictions: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[int, tuple[float, int]]:
    pairs: list[tuple[float, int, int]] = []
    for claim_index, claim in enumerate(claims):
        gold = {"name": claim["name"], "aliases": claim.get("aliases") or []}
        for prediction_index, prediction in enumerate(predictions):
            score = name_match(prediction["name"], gold)
            if score >= MATCH_THRESHOLD:
                pairs.append((score, claim_index, prediction_index))
    pairs.sort(reverse=True)
    matched: dict[int, tuple[float, int]] = {}
    used: set[int] = set()
    for score, claim_index, prediction_index in pairs:
        if claim_index in matched or prediction_index in used:
            continue
        matched[claim_index] = (score, prediction_index)
        used.add(prediction_index)
    return matched


def _defect_overlap(predicted: list[str], gold_defect: str) -> bool:
    gold_terms = _tokens(gold_defect) & DEFECT_WORDS
    if not gold_terms:
        gold_terms = _tokens(gold_defect)
    pred_text = " ".join(predicted)
    return bool(gold_terms & _tokens(pred_text))


def score_packet(dataset_dir: Path, scenario_id: str) -> dict[str, Any]:
    gold_path = _gold_dir(dataset_dir) / f"{scenario_id}.{PROVIDER}.json"
    inventory_path = (
        _work_dir(dataset_dir) / "captures" / scenario_id / "report" / "inventory.json"
    )
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    claims = gold["claims"]
    predictions: list[dict[str, Any]] = []
    for room in inventory.get("rooms") or []:
        for item in room.get("items") or []:
            predictions.append(item)

    matched = _assign(predictions, claims)
    used_preds = {pred_i for _, pred_i in matched.values()}

    identity_omit = [
        claims[i]["name"] for i in range(len(claims)) if i not in matched
    ]
    identity_invent = [
        predictions[i]["name"]
        for i in range(len(predictions))
        if i not in used_preds
    ]

    condition_omit = []
    condition_invent = []
    cleanliness_omit = []
    cleanliness_invent = []
    defect_omit = []
    defect_invent = []

    for claim_index, (_score, pred_index) in matched.items():
        claim = claims[claim_index]
        pred = predictions[pred_index]
        if claim.get("condition") and pred.get("condition") != claim["condition"]:
            # grade disagreement on an aligned item counts both ways diagnostically
            condition_omit.append(
                {
                    "name": claim["name"],
                    "gold": claim["condition"],
                    "pred": pred.get("condition"),
                }
            )
            condition_invent.append(
                {
                    "name": pred["name"],
                    "gold": claim["condition"],
                    "pred": pred.get("condition"),
                }
            )
        if claim.get("cleanliness") and pred.get("cleanliness") != claim["cleanliness"]:
            cleanliness_omit.append(
                {
                    "name": claim["name"],
                    "gold": claim["cleanliness"],
                    "pred": pred.get("cleanliness"),
                }
            )
            cleanliness_invent.append(
                {
                    "name": pred["name"],
                    "gold": claim["cleanliness"],
                    "pred": pred.get("cleanliness"),
                }
            )
        gold_defects = list(claim.get("defects") or [])
        pred_defects = list(pred.get("defects") or [])
        for defect in gold_defects:
            if not _defect_overlap(pred_defects, defect):
                defect_omit.append({"name": claim["name"], "defect": defect})
        for defect in pred_defects:
            if not any(_defect_overlap([defect], gold_d) for gold_d in gold_defects):
                # only count invent when gold had no matching defect on this item
                if gold_defects or defect:
                    if not any(
                        _defect_overlap([defect], gold_d) for gold_d in gold_defects
                    ):
                        defect_invent.append({"name": pred["name"], "defect": defect})

    def _rate(numer: int, denom: int) -> float | None:
        if denom == 0:
            return None
        return round(numer / denom, 4)

    n_claims = len(claims)
    n_preds = len(predictions)
    n_matched = len(matched)
    n_gold_defects = sum(len(c.get("defects") or []) for c in claims)
    n_pred_defects = sum(len(p.get("defects") or []) for p in predictions)

    return {
        "scenario_id": scenario_id,
        "room_type": gold["room_type"],
        "counts": {
            "gold_claims": n_claims,
            "predictions": n_preds,
            "matched": n_matched,
            "gold_defects": n_gold_defects,
            "pred_defects": n_pred_defects,
        },
        "identity": {
            "omit_n": len(identity_omit),
            "invent_n": len(identity_invent),
            "omit_rate": _rate(len(identity_omit), n_claims),
            "invent_rate": _rate(len(identity_invent), n_preds),
            "omit": identity_omit,
            "invent": identity_invent,
        },
        "condition": {
            "disagreement_n": len(condition_omit),
            "disagreement_rate": _rate(len(condition_omit), n_matched),
            "examples": condition_omit[:12],
        },
        "cleanliness": {
            "disagreement_n": len(cleanliness_omit),
            "disagreement_rate": _rate(len(cleanliness_omit), n_matched),
            "examples": cleanliness_omit[:12],
        },
        "defects": {
            "omit_n": len(defect_omit),
            "invent_n": len(defect_invent),
            "omit_rate": _rate(len(defect_omit), n_gold_defects),
            "invent_rate": _rate(len(defect_invent), n_pred_defects),
            "omit": defect_omit,
            "invent": defect_invent,
        },
    }


def score_all(
    dataset_dir: Path,
    scenario_ids: list[str] | None = None,
) -> dict[str, Any]:
    ids = scenario_ids or DESCRIBE_CHECK_SCENARIOS
    packets = [score_packet(dataset_dir, scenario_id) for scenario_id in ids]

    def _agg(getter) -> dict[str, Any]:
        nums = [getter(p) for p in packets]
        omit_n = sum(n[0] for n in nums)
        invent_n = sum(n[1] for n in nums)
        omit_d = sum(n[2] for n in nums)
        invent_d = sum(n[3] for n in nums)
        return {
            "omit_n": omit_n,
            "invent_n": invent_n,
            "omit_rate": None if omit_d == 0 else round(omit_n / omit_d, 4),
            "invent_rate": None if invent_d == 0 else round(invent_n / invent_d, 4),
        }

    summary = {
        "record_type": "describe_check_score",
        "scored_at": _utc_now(),
        "packet_ids": [f"{s}.{PROVIDER}" for s in ids],
        "backend": DESCRIBE_BACKEND,
        "model": DESCRIBE_MODEL,
        "aggregate": {
            "identity": _agg(
                lambda p: (
                    p["identity"]["omit_n"],
                    p["identity"]["invent_n"],
                    p["counts"]["gold_claims"],
                    p["counts"]["predictions"],
                )
            ),
            "condition_disagreement": {
                "n": sum(p["condition"]["disagreement_n"] for p in packets),
                "matched": sum(p["counts"]["matched"] for p in packets),
                "rate": None,
            },
            "cleanliness_disagreement": {
                "n": sum(p["cleanliness"]["disagreement_n"] for p in packets),
                "matched": sum(p["counts"]["matched"] for p in packets),
                "rate": None,
            },
            "defects": _agg(
                lambda p: (
                    p["defects"]["omit_n"],
                    p["defects"]["invent_n"],
                    p["counts"]["gold_defects"],
                    p["counts"]["pred_defects"],
                )
            ),
        },
        "packets": packets,
    }
    matched = summary["aggregate"]["condition_disagreement"]["matched"]
    if matched:
        summary["aggregate"]["condition_disagreement"]["rate"] = round(
            summary["aggregate"]["condition_disagreement"]["n"] / matched, 4
        )
        summary["aggregate"]["cleanliness_disagreement"]["rate"] = round(
            summary["aggregate"]["cleanliness_disagreement"]["n"] / matched, 4
        )
    out = _reports_dir(dataset_dir) / "describe-check-score-2026-08-06.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def defect_spot_check_list(dataset_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for scenario_id in DESCRIBE_CHECK_SCENARIOS:
        gold = json.loads(
            (_gold_dir(dataset_dir) / f"{scenario_id}.{PROVIDER}.json").read_text(
                encoding="utf-8"
            )
        )
        for claim in gold["claims"]:
            for defect in claim.get("defects") or []:
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "room_type": gold["room_type"],
                        "item": claim["name"],
                        "defect": defect,
                        "frames": claim.get("evidence_frame_ids") or [],
                    }
                )
    return rows


def write_results_note(dataset_dir: Path, score: dict[str, Any]) -> Path:
    agg = score["aggregate"]
    defects = defect_spot_check_list(dataset_dir)
    lines = [
        "# Describe check results",
        "",
        f"Recorded {_utc_now()}.",
        "",
        "## Set",
        "",
        "Twelve complete GPT Image 2 packets:",
        "",
    ]
    for scenario_id in DESCRIBE_CHECK_SCENARIOS:
        scenario = load_scenario(dataset_dir, scenario_id)
        lines.append(f"- `{scenario_id}` — {scenario['room_type']}")
    lines.extend(
        [
            "",
            "## Method",
            "",
            "- Gold: spec-seeded from `intended_visible_items` / `intended_defects`, "
            "filled by Gemini 3.5 Flash (cross-family to GPT Image 2).",
            "- Spot-check: pending owner review of every defect claim "
            f"({len(defects)} defects), post-score disagreements, and a sample of "
            "other claims.",
            f"- Describe: production `homeinventory build --photo-mode --no-detect` "
            f"via `{DESCRIBE_BACKEND}` / `{DESCRIBE_MODEL}`.",
            "- Readout: invent/omit diagnostics only — no pass bar.",
            "",
            "## Invent / omit",
            "",
            "| Claim type | Omit rate | Invent rate | Notes |",
            "|---|---:|---:|---|",
            (
                f"| Identity | {agg['identity']['omit_rate']} | "
                f"{agg['identity']['invent_rate']} | "
                f"omit {agg['identity']['omit_n']} / "
                f"{sum(p['counts']['gold_claims'] for p in score['packets'])}; "
                f"invent {agg['identity']['invent_n']} / "
                f"{sum(p['counts']['predictions'] for p in score['packets'])} |"
            ),
            (
                f"| Condition | {agg['condition_disagreement']['rate']} | "
                f"{agg['condition_disagreement']['rate']} | "
                f"grade disagreements on {agg['condition_disagreement']['n']} / "
                f"{agg['condition_disagreement']['matched']} aligned items |"
            ),
            (
                f"| Cleanliness | {agg['cleanliness_disagreement']['rate']} | "
                f"{agg['cleanliness_disagreement']['rate']} | "
                f"grade disagreements on {agg['cleanliness_disagreement']['n']} / "
                f"{agg['cleanliness_disagreement']['matched']} aligned items |"
            ),
            (
                f"| Defects | {agg['defects']['omit_rate']} | "
                f"{agg['defects']['invent_rate']} | "
                f"omit {agg['defects']['omit_n']}; invent {agg['defects']['invent_n']} |"
            ),
            "",
            "## Stop",
            "",
            "Describe check measurement is complete once owner spot-check of "
            "defects and sampled disagreements is recorded. Compare check remains "
            "deferred. Prompt tournament, Pass B backlog, video arm, and further "
            "generation stay closed.",
            "",
            "## Artifacts",
            "",
            "- Gold: `outputs/describe-check/gold/`",
            "- Describes: `outputs/describe-check/captures/RP-*/report/inventory.json`",
            "- Score JSON: `reports/describe-check-score-2026-08-06.json`",
            "",
        ]
    )
    out = _reports_dir(dataset_dir) / "describe-check-results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["gold", "describe", "score", "all", "defects"])
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--scenario", action="append", dest="scenarios")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="write spec seeds without Gemini fill",
    )
    args = parser.parse_args()
    scenarios = args.scenarios
    if args.command in {"gold", "all"}:
        draft_gold(args.dataset_dir, scenarios, fill=not args.seed_only)
    if args.command in {"describe", "all"}:
        run_describe(args.dataset_dir, scenarios)
    if args.command in {"score", "all"}:
        score = score_all(args.dataset_dir, scenarios)
        note = write_results_note(args.dataset_dir, score)
        print(f"score → {note}")
        print(json.dumps(score["aggregate"], indent=2))
    if args.command == "defects":
        rows = defect_spot_check_list(args.dataset_dir)
        print(json.dumps(rows, indent=2))
        print(f"{len(rows)} defect claim(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
