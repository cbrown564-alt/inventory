#!/usr/bin/env python3
"""Stage owner-generated Omni clips into the video fixture directory.

Generation runs on the Gemini Omni subscription surface (no metered endpoint,
dataset.json ``generation_policy``), so clips arrive as browser downloads named
by the model from the prompt's opening words, not by clip id. That naming is
lossy: it collapses the VU-4 ladder rungs and the VU-5 counterfactual pair,
which are exactly the rows whose whole value is that they differ. The mapping
is therefore written down here, with the evidence that fixed each ambiguous
one, rather than resolved by hand at copy time and forgotten.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from evals.synthetic.build_video_tasks import DEFAULT_DATASET

#: Clip id -> downloaded filename, for the 2026-08-04 owner batch.
#:
#: Four names are unambiguous (one clip per room in the batch). The other four
#: were resolved from the footage:
#:
#: * VU-5 push/hold — frame 120 and frame 239 of ``...-2.mp4`` are still framed
#:   from the doorway with the door edge in shot; the unsuffixed file has moved
#:   past the storage baskets and ends on the rear floor and lower rear wall.
#:   Presence of the occluded surface is the pair's defining difference, so
#:   this is a direct read, not an inference.
#: * VU-4 slow/ordinary — identical 10.005 s takes of the same pivot, so pace
#:   shows up as how far the pivot travels. Phase-correlated cumulative pan is
#:   85 px for ``Cloakroom_walkthrough_video`` against 161 px for
#:   ``Handheld_video_walkthrough_cloak…``; the slower sweep is the slow rung.
BATCH_2026_08_04 = {
    "VU-1.RP-003": "Kitchen_walkthrough_smartphone_v…_202608040008.mp4",
    "VU-1.RP-024": "Home_office_walkthrough_video_202608040008.mp4",
    "VU-2.RP-014-transit": "Hallway_walkthrough_video_202608040009.mp4",
    "VU-3.RP-021-narrated": "Smartphone_walkthrough_stairs_la…_202608040009.mp4",
    "VU-4.RP-022-slow": "Cloakroom_walkthrough_video_202608040009.mp4",
    "VU-4.RP-022-ordinary": "Handheld_video_walkthrough_cloak…_202608040009.mp4",
    "VU-5.RP-019-push": "Smartphone_walkthrough_utility_c…_202608040009.mp4",
    "VU-5.RP-019-hold": "Smartphone_walkthrough_utility_c…_202608040009-2.mp4",
    # VU-4.RP-022-hurried is absent: the take was generated and rejected by the
    # owner on sight (unstable physics, hallucinated scene content). No file
    # was kept, so there is nothing to stage and nothing to hash.
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(source_dir: Path, dataset_dir: Path, mapping: dict[str, str],
          dry_run: bool = False) -> list[tuple[str, Path]]:
    target_dir = dataset_dir / "video" / "google" / "gemini-omni"
    staged: list[tuple[str, Path]] = []
    for clip_id, filename in mapping.items():
        source = source_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"{clip_id}: {source} is missing")
        target = target_dir / f"{clip_id}.mp4"
        if target.is_file() and _sha256(target) != _sha256(source):
            raise FileExistsError(
                f"{clip_id}: {target} already holds a different clip. A staged "
                "clip is immutable once its hash is in the ledger; reject it "
                "explicitly before restaging."
            )
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        staged.append((clip_id, target))
    return staged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    staged = stage(args.source_dir, args.dataset_dir, BATCH_2026_08_04, args.dry_run)
    for clip_id, target in staged:
        print(f"{'would stage' if args.dry_run else 'staged'} {clip_id} -> {target}")
    print(f"{len(staged)} clip(s); VU-4.RP-022-hurried not staged (owner rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
