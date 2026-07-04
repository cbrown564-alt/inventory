"""Build progress snapshots for the web journey.

The review app polls ``work/build-progress.json`` while a background build
runs so the UI can show staged copy (*watching your video → found 10 rooms →
drafting Kitchen 3/10*) instead of subprocess stdout.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class BuildProgress:
    status: str = "idle"          # idle | running | done | failed
    stage: str = ""               # segmenting | segmented | describing | rendering
    detail: str = ""
    rooms_found: int = 0
    room_index: int = 0
    room_total: int = 0
    room_name: str = ""

    @classmethod
    def load(cls, path: Path) -> "BuildProgress":
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: data[k] for k in asdict(cls()).keys()
                          if k in data})
        except (json.JSONDecodeError, TypeError, KeyError):
            return cls()

    def write(self, path: Optional[Path]) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def start(self, path: Optional[Path]) -> None:
        self.status = "running"
        self.stage = "starting"
        self.detail = "Preparing your report…"
        self.write(path)

    def segmenting(self, path: Optional[Path]) -> None:
        self.stage = "segmenting"
        self.detail = "Watching your video…"
        self.write(path)

    def segmented(self, path: Optional[Path], n_rooms: int) -> None:
        self.stage = "segmented"
        self.rooms_found = n_rooms
        self.room_total = n_rooms
        self.detail = f"Found {n_rooms} room{'s' if n_rooms != 1 else ''}"
        self.write(path)

    def describing(self, path: Optional[Path], index: int, total: int,
                   room_name: str) -> None:
        self.stage = "describing"
        self.room_index = index
        self.room_total = total
        self.room_name = room_name
        self.detail = f"Drafting {room_name} ({index}/{total})"
        self.write(path)

    def rendering(self, path: Optional[Path]) -> None:
        self.stage = "rendering"
        self.detail = "Building your report…"
        self.write(path)

    def done(self, path: Optional[Path]) -> None:
        self.status = "done"
        self.stage = "done"
        self.detail = "Your report is ready"
        self.write(path)

    def failed(self, path: Optional[Path], detail: str) -> None:
        self.status = "failed"
        self.stage = "failed"
        self.detail = detail
        self.write(path)
