"""Room segmentation: the pure parts (normalisation, dotenv). The VLM pass
itself is validated against real footage — see the spike record in docs/11."""

import os

from homeinventory.dotenv import load_dotenv
from homeinventory.segment import Segment, _normalise


def test_normalise_forces_contiguity_and_merges_same_room():
    segs = _normalise([
        Segment("Hallway", 0.0, 30.0),
        Segment("Kitchen", 34.0, 90.0),          # 4s gap -> midpoint seam
        Segment("kitchen", 90.0, 120.0),         # same room, case-insensitive
        Segment("Living Room", 118.0, 200.0),    # 2s overlap -> midpoint seam
    ], duration_s=210.0)
    assert [s.room for s in segs] == ["Hallway", "Kitchen", "Living Room"]
    assert segs[0].start_s == 0.0
    assert segs[0].end_s == segs[1].start_s == 32.0
    assert segs[1].end_s == segs[2].start_s == 119.0
    assert segs[-1].end_s == 210.0               # snapped to duration


def test_normalise_drops_empty_and_survives_garbage():
    segs = _normalise([Segment("Kitchen", 50.0, 50.0)], duration_s=60.0)
    assert [s.room for s in segs] == ["Property"]  # honest fallback, full span
    assert segs[0].start_s == 0.0 and segs[0].end_s == 60.0


def test_load_dotenv_sets_without_overriding(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "# comment\nANTHROPIC_API_KEY='sk-test'\nHI_EXISTING=file\n\nBAD LINE\n",
        encoding="utf-8")
    monkeypatch.setenv("HI_EXISTING", "env-wins")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    n = load_dotenv(tmp_path)
    assert n == 1
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"   # quotes stripped
    assert os.environ["HI_EXISTING"] == "env-wins"        # never overridden
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_load_dotenv_walks_up_from_subdir(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HI_FROM_PARENT=yes\n", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.delenv("HI_FROM_PARENT", raising=False)
    assert load_dotenv(sub) == 1
    assert os.environ["HI_FROM_PARENT"] == "yes"
    monkeypatch.delenv("HI_FROM_PARENT", raising=False)
