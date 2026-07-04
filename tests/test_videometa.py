"""Video-evidence plumbing: frame→timestamp mapping, ranged video serving.

The review UI's walkthrough spine (docs/13) depends on three contracts:
keyframe filenames encode their source frame index, /video/<rel> serves
capture videos with HTTP Range support, and the review payload carries
``videos`` + ``photo_time``.
"""

from __future__ import annotations

import threading
import urllib.request

import pytest

from homeinventory.review import serve
from homeinventory.schema import Inventory, Photo, Room
from homeinventory.videometa import (frame_index, load_segments,
                                     video_payload)


def test_frame_index_parses_ingest_filenames():
    assert frame_index("work/frames/Hallway/hallway_f000036.jpg") == 36
    assert frame_index("/abs/path/walk_f012345.JPG") == 12345
    assert frame_index("Kitchen/plain-photo.jpg") is None


def test_load_segments_reads_ingest_cache(tmp_path):
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    (seg_dir / "walk.json").write_text(
        '{"segments": [{"room": "Hallway", "start_s": 0, "end_s": 12.5},'
        ' {"room": "Kitchen", "start_s": 12.5, "end_s": 90}]}',
        encoding="utf-8")
    segs = load_segments(tmp_path, "walk")
    assert [s["room"] for s in segs] == ["Hallway", "Kitchen"]
    assert segs[1]["start"] == 12.5
    assert load_segments(tmp_path, "missing") == []


def test_video_payload_without_cv2_or_videos_degrades(tmp_path):
    inv = Inventory(rooms=[Room(name="Kitchen", photos=[
        Photo(id="P001", path="Kitchen/k1.jpg", room="Kitchen")])])
    videos, photo_time = video_payload(inv, tmp_path, tmp_path / "work",
                                       "", {})
    assert videos == {} and photo_time == {}


@pytest.fixture()
def video_server(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    cap = tmp_path / "capture"
    room = cap / "Kitchen"
    room.mkdir(parents=True)
    vid = room / "kitchen.mp4"
    w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"),
                        10.0, (64, 48))
    for i in range(30):                       # 3 seconds at 10 fps
        frame = np.full((48, 64, 3), i * 8 % 255, dtype=np.uint8)
        w.write(frame)
    w.release()

    out = tmp_path / "report"
    out.mkdir()
    photos = out / "photos"
    photos.mkdir()
    inv = Inventory(rooms=[Room(name="Kitchen", photos=[
        Photo(id="P001", path=str(tmp_path / "work/frames/Kitchen/"
                                  "kitchen_f000020.jpg"),
              room="Kitchen", source_video="kitchen.mp4")])])
    (out / "inventory.json").write_text(inv.to_json(), encoding="utf-8")
    (photos / "P001.jpg").write_bytes(b"\xff\xd8\xff\xdbfake")

    httpd = serve(cap, out, port=0, backend="offline", open_browser=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, vid
    httpd.shutdown()
    httpd.server_close()


def test_payload_maps_frames_to_walkthrough_seconds(video_server):
    import json
    base, _vid = video_server
    with urllib.request.urlopen(base + "/api/inventory") as r:
        body = json.loads(r.read().decode("utf-8"))
    assert "Kitchen/kitchen.mp4" in body["videos"]
    meta = body["videos"]["Kitchen/kitchen.mp4"]
    assert meta["src"] == "/video/Kitchen/kitchen.mp4"
    assert meta["fps"] == pytest.approx(10.0, abs=0.5)
    assert meta["duration"] == pytest.approx(3.0, abs=0.5)
    # frame 20 at 10 fps = 2.0 s into the footage
    assert body["photo_time"]["P001"]["t"] == pytest.approx(2.0, abs=0.2)


def test_video_route_serves_ranges(video_server):
    base, vid = video_server
    size = vid.stat().st_size

    req = urllib.request.Request(base + "/video/Kitchen/kitchen.mp4")
    with urllib.request.urlopen(req) as r:
        assert r.status == 200
        assert r.headers["Accept-Ranges"] == "bytes"
        assert int(r.headers["Content-Length"]) == size

    req = urllib.request.Request(base + "/video/Kitchen/kitchen.mp4",
                                 headers={"Range": "bytes=10-19"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206
        assert r.headers["Content-Range"] == f"bytes 10-19/{size}"
        assert len(r.read()) == 10

    # suffix range: the last 5 bytes
    req = urllib.request.Request(base + "/video/Kitchen/kitchen.mp4",
                                 headers={"Range": "bytes=-5"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206
        assert r.headers["Content-Range"] == \
            f"bytes {size - 5}-{size - 1}/{size}"

    # unsatisfiable start
    req = urllib.request.Request(base + "/video/Kitchen/kitchen.mp4",
                                 headers={"Range": f"bytes={size + 9}-"})
    try:
        urllib.request.urlopen(req)
        assert False, "expected 416"
    except urllib.error.HTTPError as e:
        assert e.code == 416


def test_video_route_rejects_traversal_and_non_videos(video_server):
    base, _vid = video_server
    for path in ("/video/../secrets.mp4", "/video/Kitchen/nope.mp4",
                 "/video/Kitchen/kitchen.txt"):
        try:
            urllib.request.urlopen(base + path)
            assert False, f"expected 404 for {path}"
        except urllib.error.HTTPError as e:
            assert e.code == 404
