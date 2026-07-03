"""M5b phone guided-capture server: token gate, room creation, guide
single-source, upload contract (shared with M5a via webbase), progress,
coverage check, £0 end-to-end build. See docs/09-web-ui-and-capture.md."""

import base64
import hashlib
import json
import threading
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from homeinventory.capture import serve_capture
from homeinventory.cli import main
from homeinventory.guide import PER_ROOM_SHOTS, WHOLE_PROPERTY_SHOTS
from homeinventory.schema import Inventory


def _img(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), "white").save(path)


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _heic_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 64


def _req(method, url, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def _get_text(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read().decode("utf-8")


@pytest.fixture()
def cap_server(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    httpd = serve_capture(cap, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, httpd.capture_state, cap
    httpd.shutdown()
    httpd.server_close()


def _upload(base, token, room, filename, data: bytes):
    return _req("POST", f"{base}/api/c/{token}/photos", {
        "room": room, "filename": filename,
        "photo_b64": base64.b64encode(data).decode()})


# ---- token gate (mirrors test_tenant_token_gate) ---------------------------

def test_capture_token_gate(cap_server):
    base, state, _cap = cap_server
    status, _ = _get_text(base + f"/c/{state.token}")
    assert status == 200
    status, _ = _req("GET", base + "/c/not-the-token")
    assert status == 403
    status, _ = _req("GET", base + "/api/c/not-the-token/progress")
    assert status == 403
    status, _ = _req("POST", base + "/api/c/not-the-token/photos",
                     {"room": "Kitchen", "filename": "x.jpg", "photo_b64": ""})
    assert status == 403
    status, _ = _req("POST", base + "/api/c/not-the-token/rooms",
                     {"name": "Evil"})
    assert status == 403
    status, _ = _req("GET", base + "/")          # no ungated pages at all
    assert status == 404


# ---- room list + creation ---------------------------------------------------

def test_room_creation_and_listing(cap_server):
    base, state, cap = cap_server
    t = state.token
    status, resp = _req("POST", f"{base}/api/c/{t}/rooms",
                        {"name": "Bedroom 1"})
    assert status == 200, resp
    assert (cap / "Bedroom 1").is_dir()
    assert {r["name"] for r in resp["rooms"]} == {"Bedroom 1", "Kitchen"}
    # idempotent — creating again is not an error
    status, _ = _req("POST", f"{base}/api/c/{t}/rooms", {"name": "Bedroom 1"})
    assert status == 200
    # page lists both rooms
    _, html = _get_text(f"{base}/c/{t}")
    assert 'data-room="Kitchen"' in html and 'data-room="Bedroom 1"' in html


def test_room_creation_traversal_400(cap_server, tmp_path):
    base, state, cap = cap_server
    t = state.token
    for bad in ["../evil", "a/b", "..", ".hidden", "a\\b", ""]:
        status, resp = _req("POST", f"{base}/api/c/{t}/rooms", {"name": bad})
        assert status == 400, (bad, resp)
    assert not (tmp_path / "evil").exists()
    assert set(d.name for d in cap.iterdir() if d.is_dir()) == {"Kitchen"}


# ---- guide: one source, two surfaces ----------------------------------------

def test_guide_categories_on_both_surfaces(cap_server, capsys):
    assert main(["guide"]) == 0
    stdout = capsys.readouterr().out
    base, state, _cap = cap_server
    status, html = _get_text(f"{base}/c/{state.token}")
    assert status == 200
    for shot in PER_ROOM_SHOTS:
        assert shot["label"] in stdout        # printed guide
        assert shot["label"] in html          # rendered room page
    for shot in WHOLE_PROPERTY_SHOTS:
        assert shot in stdout
        assert shot in html


def test_capture_page_template_hooks(cap_server):
    base, state, _cap = cap_server
    _, html = _get_text(f"{base}/c/{state.token}")
    # camera control: plain file input, not getUserMedia/PWA
    assert 'capture="environment"' in html
    assert 'accept="image/*"' in html
    assert "getUserMedia" not in html
    # tick-off tally hooks (client-side localStorage)
    assert 'class="tick"' in html
    assert 'data-cat="' in html
    assert 'id="tally"' in html
    assert "localStorage" in html
    assert 'id="room-list"' in html


# ---- upload: same webbase contract as M5a ----------------------------------

def test_upload_roundtrip_sha256_and_room_count(cap_server):
    base, state, cap = cap_server
    t = state.token
    data = _jpeg_bytes()
    status, resp = _upload(base, t, "Kitchen", "hob.png", data)  # lying ext
    assert status == 200, resp
    assert resp["stored_as"] == "hob.jpg"                # sniffed, not trusted
    on_disk = cap / "Kitchen" / "hob.jpg"
    sent = hashlib.sha256(data).hexdigest()
    assert resp["sha256"] == sent
    assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == sent
    assert resp["room_photos"] == 2                      # k1.jpg + this one


def test_upload_heic_lands_as_heic(cap_server):
    base, state, cap = cap_server
    data = _heic_bytes()
    status, resp = _upload(base, state.token, "Kitchen", "IMG_1.jpeg", data)
    assert status == 200, resp
    assert resp["stored_as"] == "IMG_1.heic"
    assert hashlib.sha256(
        (cap / "Kitchen" / "IMG_1.heic").read_bytes()).hexdigest() == \
        hashlib.sha256(data).hexdigest()


def test_upload_no_clobber(cap_server):
    base, state, cap = cap_server
    t = state.token
    first, second = _jpeg_bytes(), _jpeg_bytes() + b"\x00"
    s1, r1 = _upload(base, t, "Kitchen", "wall.jpg", first)
    s2, r2 = _upload(base, t, "Kitchen", "wall.jpg", second)
    assert s1 == s2 == 200
    assert r1["stored_as"] == "wall.jpg" and r2["stored_as"] == "wall-1.jpg"
    assert (cap / "Kitchen" / "wall.jpg").read_bytes() == first


def test_upload_unsniffable_and_traversal_400(cap_server):
    base, state, cap = cap_server
    t = state.token
    status, _ = _upload(base, t, "Kitchen", "x.txt", b"not an image")
    assert status == 400
    status, _ = _upload(base, t, "../evil", "x.jpg", _jpeg_bytes())
    assert status == 400
    status, _ = _upload(base, t, "Kitchen", "../x.jpg", _jpeg_bytes())
    assert status == 400
    assert not list(cap.rglob("x*"))


def test_upload_413_over_64mib(cap_server):
    base, state, cap = cap_server
    data = b"\xff\xd8" + b"\x00" * (64 * 1024 * 1024)
    status, resp = _upload(base, state.token, "Kitchen", "huge.jpg", data)
    assert status == 413, resp
    assert not list(cap.rglob("huge*"))


# ---- progress ---------------------------------------------------------------

def test_progress_counts(cap_server):
    base, state, _cap = cap_server
    t = state.token
    assert _upload(base, t, "Kitchen", "a.jpg", _jpeg_bytes())[0] == 200
    assert _req("POST", f"{base}/api/c/{t}/rooms", {"name": "Study"})[0] == 200
    assert _upload(base, t, "Study", "b.jpg", _jpeg_bytes())[0] == 200

    status, resp = _req("GET", f"{base}/api/c/{t}/progress")
    assert status == 200
    counts = {r["name"]: r["photos"] for r in resp["rooms"]}
    assert counts == {"Kitchen": 2, "Study": 1}          # k1.jpg + a.jpg / b.jpg
    assert resp["total_photos"] == 3


# ---- coverage check: real gaps, and unavailable is never a silent pass ------

def test_check_room_reports_real_gaps(cap_server, monkeypatch):
    import homeinventory.detect as detect

    class FakeDetector(detect.Detector):
        def detect(self, image_path, crops_dir=None):
            return [detect.Detection(label="window", confidence=0.9,
                                     box=(0, 0, 10, 10))]
    monkeypatch.setattr(detect, "Detector", FakeDetector)

    base, state, _cap = cap_server
    status, resp = _req("POST", f"{base}/api/c/{state.token}/check",
                        {"room": "Kitchen"})
    assert status == 200, resp
    assert resp["status"] == "checked"
    # a real coverage verdict: window satisfied, kitchen expectations missing
    assert "window" not in resp["gaps"]
    for expected in ("door", "sink", "tap", "oven / stove", "smoke alarm"):
        assert expected in resp["gaps"]


def test_check_room_detector_unavailable_is_reported(cap_server, monkeypatch):
    import homeinventory.detect as detect

    class Unavailable(detect.Detector):
        def _load(self):
            self.available = False
    monkeypatch.setattr(detect, "Detector", Unavailable)

    base, state, _cap = cap_server
    status, resp = _req("POST", f"{base}/api/c/{state.token}/check",
                        {"room": "Kitchen"})
    assert status == 200
    assert resp["status"] == "unavailable"               # never a silent pass
    assert "NOT checked" in resp["detail"]
    assert "gaps" not in resp                            # no fake empty verdict


def test_check_room_missing_room_404(cap_server):
    base, state, _cap = cap_server
    status, _ = _req("POST", f"{base}/api/c/{state.token}/check",
                     {"room": "Ballroom"})
    assert status == 404


# ---- £0 end-to-end: phone uploads then an offline build ---------------------

def test_capture_then_offline_build_e2e(cap_server, tmp_path):
    base, state, cap = cap_server
    t = state.token
    # one newly created room + the existing one, ≥2 photos each way
    assert _req("POST", f"{base}/api/c/{t}/rooms", {"name": "Study"})[0] == 200
    assert _upload(base, t, "Kitchen", "k2.jpg", _jpeg_bytes())[0] == 200
    assert _upload(base, t, "Study", "s1.jpg", _jpeg_bytes())[0] == 200
    assert _upload(base, t, "Study", "s2.jpg", _jpeg_bytes())[0] == 200

    out = tmp_path / "report"
    rc = main(["build", str(cap), "-o", str(out),
               "--backend", "offline", "--no-detect", "--no-pdf"])
    assert rc == 0
    inv = Inventory.from_json((out / "inventory.json").read_text(encoding="utf-8"))
    assert {r.name for r in inv.rooms} == {"Kitchen", "Study"}
    kitchen = next(r for r in inv.rooms if r.name == "Kitchen")
    study = next(r for r in inv.rooms if r.name == "Study")
    assert len(kitchen.photos) == 2 and len(study.photos) == 2
