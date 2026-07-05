"""Smoke tests for evals/eval_hero_cover.py (no report fixture required)."""

import json
import pathlib
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))
import eval_hero_cover  # noqa: E402


def _write_grey_jpeg(path: pathlib.Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (64, 48), color=value).save(path, format="JPEG")


def _synthetic_report(tmp_path: pathlib.Path) -> pathlib.Path:
    report = tmp_path / "report"
    frames_dir = report / "work" / "frames" / "Room A_seg00"
    frames_dir.mkdir(parents=True)
    paths = []
    for i, val in enumerate([40, 120, 200], start=1):
        fn = f"clip_f00000{i}.jpg"
        p = frames_dir / fn
        _write_grey_jpeg(p, val)
        paths.append(p)

    inv = {
        "rooms": [{
            "name": "Room A",
            "photos": [
                {
                    "id": f"P00{i}",
                    "path": str(p),
                    "source_video": "clip.MOV",
                    "hero": 1 if i == 2 else None,
                }
                for i, p in enumerate(paths, start=1)
            ],
        }],
    }
    (report / "inventory.json").write_text(json.dumps(inv), encoding="utf-8")
    return report


def test_load_rooms_walkthrough_order(tmp_path):
    report = _synthetic_report(tmp_path)
    rooms = eval_hero_cover.load_rooms(report)
    assert [name for name, _ in rooms] == ["Room A"]
    assert len(rooms[0][1]) == 3


def test_eval_writes_html_and_metrics(tmp_path):
    report = _synthetic_report(tmp_path)
    out = tmp_path / "hero-contact-classical.html"
    gold = {
        "rooms": {
            "Room A": {
                "top": ["clip_f000002.jpg", "clip_f000003.jpg", "clip_f000001.jpg"],
                "bottom": ["clip_f000001.jpg", "clip_f000002.jpg"],
                "notes": "test",
            },
        },
    }
    gold_path = tmp_path / "hero-gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    rooms = eval_hero_cover.load_rooms(report)
    room_entries = {}
    all_metrics = {}
    for name, frames in rooms:
        entries, metrics = eval_hero_cover.build_room_entries(report, frames)
        room_entries[name] = entries
        all_metrics[name] = metrics

    per_room = {}
    for name, entries in room_entries.items():
        metrics = all_metrics[name]
        per_room[name] = eval_hero_cover.evaluate_room(
            scorer="classical",
            entries=entries,
            metrics=metrics,
            gold_room=gold["rooms"].get(name),
        )
        by_scorer = sorted(
            entries,
            key=lambda e: eval_hero_cover.scorer_sort_key(
                "classical", metrics[e["name"]], gated=e.get("gated_out", False),
            ),
            reverse=True,
        )
        scorer_rank = {e["name"]: i + 1 for i, e in enumerate(by_scorer)}
        for e in entries:
            e["metrics"] = metrics[e["name"]]
            e["scorer_rank"] = scorer_rank[e["name"]]

    summary = eval_hero_cover.aggregate_metrics(per_room)

    eval_hero_cover.render_html(
        html_path=out,
        report_dir=report,
        scorer="classical",
        rooms=rooms,
        room_data=room_entries,
        metrics_summary=summary,
        gold=gold["rooms"],
    )

    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "Room A" in text
    assert "★" in text
    assert summary["n_rooms"] == 1
    assert "top1_hit_rate" in summary


def test_gold_rank_map():
    gold = {"top": ["a.jpg", "b.jpg", "c.jpg"], "bottom": ["y.jpg", "z.jpg"]}
    ranks = eval_hero_cover.gold_rank_map(gold, 10)
    assert ranks["a.jpg"] == 1.0
    assert ranks["c.jpg"] == 3.0
    assert ranks["y.jpg"] == 9.0
    assert ranks["z.jpg"] == 10.0
