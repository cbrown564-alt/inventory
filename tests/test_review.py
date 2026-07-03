"""Tests for the review experience: schema round-trip (Level 1 data),
the local review server (Level 2) and the multi-party flow (Level 3)."""

import json
import threading
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

from homeinventory.cli import main
from homeinventory.coverage import coverage_gaps, expected_for
from homeinventory.review import serve
from homeinventory.schema import Inventory, Item, Photo, Room


def _img(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), "white").save(path)


# --------------------------------------------------------------------------
# schema: review & attestation fields
# --------------------------------------------------------------------------

def test_review_fields_round_trip():
    inv = Inventory(rooms=[Room(name="Kitchen", items=[Item(
        id="KIT-001", name="TV unit", reviewed=True,
        rejected_defects=["surface scratch to top right corner"],
        defect_regions=[{"defect": "chip", "photo_id": "P001",
                         "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
        comments=[{"author": "T. Okafor", "role": "tenant",
                   "text": "that is a sticker", "at": "2026-06-10T10:00:00Z"}],
    )])])
    inv.signatures.append({"role": "landlord", "name": "C. Brown",
                           "signed_at": "2026-06-10T10:05:00Z",
                           "inventory_sha256": inv.content_sha256(), "via": "t"})
    again = Inventory.from_json(inv.to_json())
    item = again.rooms[0].items[0]
    assert item.reviewed and not item.rejected
    assert item.rejected_defects == ["surface scratch to top right corner"]
    assert item.defect_regions[0]["photo_id"] == "P001"
    assert again.signatures[0]["role"] == "landlord"
    assert again.reviewed_count() == 1


def test_from_json_tolerates_unknown_keys():
    raw = json.loads(Inventory(rooms=[Room(name="K", items=[Item(
        id="K-001", name="x")], photos=[Photo(id="P001", path="a", room="K")])
    ]).to_json())
    raw["rooms"][0]["items"][0]["future_field"] = 1
    raw["rooms"][0]["photos"][0]["future_field"] = 1
    raw["future_field"] = 1
    inv = Inventory.from_json(json.dumps(raw))
    assert inv.rooms[0].items[0].id == "K-001"


def test_content_hash_excludes_signatures():
    inv = Inventory(property_address="1 Test St")
    before = inv.content_sha256()
    inv.signatures.append({"role": "tenant", "name": "A", "signed_at": "now"})
    assert inv.content_sha256() == before
    inv.property_address = "2 Test St"
    assert inv.content_sha256() != before


# --------------------------------------------------------------------------
# level 1: the rendered report is the review tool
# --------------------------------------------------------------------------

def test_report_embeds_review_layer(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    out = tmp_path / "report"
    assert main(["build", str(cap), "-o", str(out),
                 "--backend", "offline", "--no-detect", "--no-pdf"]) == 0
    html = (out / "inventory.html").read_text(encoding="utf-8")
    assert 'id="hi-data"' in html          # embedded inventory JSON
    assert "Review docket" in html         # the instrument layer
    assert "Download reviewed inventory.json" in html


def test_report_renders_review_states(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    inv = Inventory(rooms=[Room(
        name="Kitchen",
        items=[Item(id="KIT-001", name="TV unit", reviewed=True,
                    defects=["chip to corner"], rejected_defects=["scratch"],
                    photo_ids=["P001"],
                    defect_regions=[{"defect": "chip to corner",
                                     "photo_id": "P001", "x": 0.1, "y": 0.1,
                                     "w": 0.2, "h": 0.2}],
                    comments=[{"author": "T", "role": "tenant",
                               "text": "pre-existing", "at": "2026-06-10"}]),
               Item(id="KIT-002", name="Phantom lamp", rejected=True)],
        photos=[Photo(id="P001", path="Kitchen/k1.jpg", room="Kitchen")])])
    inv.signatures.append({"role": "landlord", "name": "C. Brown",
                           "signed_at": "2026-06-10T10:00:00Z",
                           "inventory_sha256": inv.content_sha256(),
                           "via": "test"})
    from homeinventory.report import render
    out = tmp_path / "report"
    html = render(inv, cap, out, pdf=False)["html"].read_text(encoding="utf-8")
    assert "reviewer rejected" in html      # struck, not deleted
    assert 'class="region"' in html         # defect region overlay
    assert "pre-existing" in html           # tenant comment in the record
    assert "sigcard" in html                # captured signature block


# --------------------------------------------------------------------------
# levels 2 & 3: the review server
# --------------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Living Room" / "l1.jpg")
    out = tmp_path / "report"
    assert main(["build", str(cap), "-o", str(out),
                 "--backend", "offline", "--no-detect", "--no-pdf"]) == 0
    # offline+no-detect yields no items; seed one per room like a real build
    inv = Inventory.from_json((out / "inventory.json").read_text(encoding="utf-8"))
    for room in inv.rooms:
        code = "".join(c for c in room.name.upper() if c.isalpha())[:3]
        room.items.append(Item(id=f"{code}-001", name=f"{room.name} window",
                               condition="good", confidence=0.4,
                               photo_ids=[p.id for p in room.photos]))
    (out / "inventory.json").write_text(inv.to_json(), encoding="utf-8")
    httpd = serve(cap, out, port=0, share=True, backend="offline",
                  open_browser=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, httpd.review_state, out, cap
    httpd.shutdown()
    httpd.server_close()


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


def test_owner_app_and_inventory_api(server):
    base, _state, _out, _cap = server
    status, html = _get_text(base + "/")
    assert status == 200 and 'id="hi-data"' in html
    status, body = _req("GET", base + "/api/inventory")
    assert status == 200
    assert {r["name"] for r in body["inventory"]["rooms"]} == \
        {"Kitchen", "Living Room"}
    assert body["photo_src"]  # photos are exported and mapped


def test_write_back_and_rerender(server):
    base, _state, out, _cap = server
    _, body = _req("GET", base + "/api/inventory")
    inv = body["inventory"]
    item = inv["rooms"][0]["items"][0]
    item["reviewed"] = True
    item["rejected_defects"] = ["imaginary scratch"]
    status, resp = _req("PUT", base + "/api/inventory?render=1", inv)
    assert status == 200 and resp["reviewed"] == 1

    on_disk = Inventory.from_json(
        (out / "inventory.json").read_text(encoding="utf-8"))
    saved = [i for r in on_disk.rooms for i in r.items
             if i.id == item["id"]][0]
    assert saved.reviewed and saved.rejected_defects == ["imaginary scratch"]
    html = (out / "inventory.html").read_text(encoding="utf-8")
    assert "imaginary scratch" in html and "reviewer rejected" in html


def test_add_missing_item_with_photo(server):
    import base64
    base, _state, out, cap = server
    png = Path(cap / "Kitchen" / "k1.jpg").read_bytes()
    status, resp = _req("POST", base + "/api/items", {
        "room": "Kitchen", "name": "Cast-iron skillet",
        "description": "28cm, seasoned", "condition": "good",
        "photo_b64": base64.b64encode(png).decode(),
        "author": "C. Brown"})
    assert status == 200, resp
    item = resp["item"]
    assert item["added_by"] == "C. Brown" and item["reviewed"]
    assert item["id"].endswith("-002")  # continues the room sequence

    on_disk = Inventory.from_json(
        (out / "inventory.json").read_text(encoding="utf-8"))
    kitchen = [r for r in on_disk.rooms if r.name == "Kitchen"][0]
    assert any(i.name == "Cast-iron skillet" for i in kitchen.items)
    new_photo = [p for p in kitchen.photos if p.note][0]
    assert (cap / new_photo.path).exists()           # evidence in capture dir
    assert new_photo.sha256                          # hashed
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert any(f["photo_id"] == new_photo.id for f in manifest["files"])


def test_owner_sign_pins_content_hash(server):
    base, _state, out, _cap = server
    status, resp = _req("POST", base + "/api/sign",
                        {"name": "C. Brown", "role": "landlord"})
    assert status == 200
    on_disk = Inventory.from_json(
        (out / "inventory.json").read_text(encoding="utf-8"))
    sig = on_disk.signatures[-1]
    assert sig["role"] == "landlord"
    assert sig["inventory_sha256"] == on_disk.content_sha256()


def test_tenant_token_gate(server):
    base, state, _out, _cap = server
    status, _ = _get_text(base + f"/t/{state.tenant_token}")
    assert status == 200
    status, _ = _req("GET", base + "/t/not-the-token")
    assert status == 403
    status, _ = _req("POST", base + "/api/t/wrong/comments",
                     {"item_id": "X", "text": "hi"})
    assert status == 403


def test_tenant_comment_and_countersign(server):
    base, state, out, _cap = server
    t = state.tenant_token
    _, body = _req("GET", base + f"/api/t/{t}/inventory")
    item_id = body["inventory"]["rooms"][0]["items"][0]["id"]

    status, _ = _req("POST", base + f"/api/t/{t}/comments", {
        "item_id": item_id, "text": "carpet stain was already there",
        "author": "T. Okafor"})
    assert status == 200
    status, _ = _req("POST", base + f"/api/t/{t}/sign", {"name": "T. Okafor"})
    assert status == 200

    on_disk = Inventory.from_json(
        (out / "inventory.json").read_text(encoding="utf-8"))
    item = [i for r in on_disk.rooms for i in r.items if i.id == item_id][0]
    assert item.comments[-1]["role"] == "tenant"
    assert on_disk.signatures[-1]["role"] == "tenant"
    # the tenant signature pins the content including their own comments
    assert on_disk.signatures[-1]["inventory_sha256"] == \
        on_disk.content_sha256()


def test_ack_trail_is_hash_chained(server):
    import hashlib
    base, state, out, _cap = server
    t = state.tenant_token
    _, body = _req("GET", base + f"/api/t/{t}/inventory")
    item_id = body["inventory"]["rooms"][0]["items"][0]["id"]
    _req("POST", base + f"/api/t/{t}/comments",
         {"item_id": item_id, "text": "first", "author": "T"})
    _req("POST", base + f"/api/t/{t}/sign", {"name": "T"})

    lines = [json.loads(l) for l in
             (out / "acknowledgements.jsonl").read_text(encoding="utf-8")
             .strip().splitlines()]
    assert len(lines) >= 2
    prev = ""
    for rec in lines:
        assert rec["prev"] == prev
        claimed = rec.pop("sha256")
        canon = json.dumps(rec, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
        assert hashlib.sha256(canon.encode()).hexdigest() == claimed
        prev = claimed


def test_unknown_routes_and_bad_input(server):
    base, _state, _out, _cap = server
    status, _ = _req("GET", base + "/api/nope")
    assert status == 404
    status, _ = _req("POST", base + "/api/items", {"room": "Kitchen"})
    assert status == 400
    status, _ = _req("POST", base + "/api/items",
                     {"room": "Ballroom", "name": "Chandelier"})
    assert status == 400


# --------------------------------------------------------------------------
# coverage check (detector-only, no AI)
# --------------------------------------------------------------------------

def test_expected_for_merges_room_keywords():
    exp = expected_for("Bedroom 2")
    assert "door" in exp and "window" in exp and "radiator" in exp


def test_coverage_gaps_alternatives():
    gaps = coverage_gaps({"door", "window", "toilet", "sink", "shower"},
                         "Bathroom")
    assert "bathtub / shower" not in gaps        # alternative satisfied
    assert gaps == ["towel rail"]


def test_check_cli_without_detector(tmp_path, monkeypatch):
    # force the unavailable path regardless of what's installed locally
    import homeinventory.detect as detect

    class Unavailable(detect.Detector):
        def _load(self):
            self.available = False
    monkeypatch.setattr(detect, "Detector", Unavailable)

    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    assert main(["check", str(cap)]) == 2


# --------------------------------------------------------------------------
# M5a web UI: start page, browser upload, build-from-browser, spend guards,
# PDF export (docs/09-web-ui-and-capture.md)
# --------------------------------------------------------------------------

import base64      # noqa: E402
import hashlib     # noqa: E402
import time        # noqa: E402


def _start_server(cap: Path, out: Path):
    """Server exactly as `homeinventory review CAP -o OUT --backend offline
    --no-detect --no-open` would configure it (the £0 pinned command) —
    crucially WITHOUT a prior build."""
    httpd = serve(cap, out, port=0, share=False, backend="offline",
                  open_browser=False, no_detect=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", httpd


@pytest.fixture()
def fresh_server(tmp_path):
    """No inventory.json yet: capture/ exists and is empty."""
    cap = tmp_path / "capture"
    cap.mkdir()
    out = tmp_path / "report"
    base, httpd = _start_server(cap, out)
    yield base, httpd.review_state, out, cap
    httpd.shutdown()
    httpd.server_close()


def _jpeg_bytes() -> bytes:
    from io import BytesIO
    buf = BytesIO()
    Image.new("RGB", (64, 48), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _heic_bytes() -> bytes:
    # minimal ISO-BMFF header with a heic brand — enough for the sniffer;
    # upload must store bytes unmodified, so no decodable body is needed
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 64


def _upload(base, room, filename, data: bytes):
    return _req("POST", base + "/api/photos", {
        "room": room, "filename": filename,
        "photo_b64": base64.b64encode(data).decode()})


# ---- start page: both states -----------------------------------------------

def test_start_page_empty_capture(fresh_server):
    base, _state, _out, _cap = fresh_server
    status, html = _get_text(base + "/")
    assert status == 200
    assert 'id="empty-state"' in html          # empty-state instruction block
    assert "one folder per" in html            # the instruction text itself
    # build confirm control names backend+model (template assertion)
    assert 'id="btn-build"' in html
    assert 'id="build-backend"' in html
    assert "offline (no AI)" in html


def test_start_page_lists_rooms_with_counts(tmp_path):
    cap = tmp_path / "capture"
    _img(cap / "Kitchen" / "k1.jpg")
    _img(cap / "Kitchen" / "k2.jpg")
    (cap / "Living Room").mkdir()
    (cap / "Living Room" / "walk.mp4").write_bytes(b"\x00" * 32)
    out = tmp_path / "report"
    base, httpd = _start_server(cap, out)
    try:
        status, html = _get_text(base + "/")
        assert status == 200
        assert 'id="room-list"' in html and 'id="empty-state"' not in html
        assert 'data-room="Kitchen"' in html
        assert 'data-room="Living Room"' in html
        assert '<td class="n-photos">2</td>' in html    # Kitchen photos
        assert '<td class="n-videos">1</td>' in html    # Living Room video
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---- upload: sha256 round-trip, sniffed extensions, caps, traversal --------

def test_upload_roundtrip_sha256_and_sniffed_extension(fresh_server):
    base, _state, _out, cap = fresh_server
    data = _jpeg_bytes()
    # filename lies about the extension; the JPEG magic bytes must win
    status, resp = _upload(base, "Kitchen", "hob.png", data)
    assert status == 200, resp
    assert resp["stored_as"] == "hob.jpg"
    on_disk = cap / "Kitchen" / "hob.jpg"
    assert on_disk.is_file()
    sent = hashlib.sha256(data).hexdigest()
    assert resp["sha256"] == sent
    assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == sent  # unmodified


def test_upload_heic_lands_as_heic(fresh_server):
    base, _state, _out, cap = fresh_server
    data = _heic_bytes()
    status, resp = _upload(base, "Bedroom 1", "IMG_0001.jpeg", data)
    assert status == 200, resp
    assert resp["stored_as"] == "IMG_0001.heic"
    on_disk = cap / "Bedroom 1" / "IMG_0001.heic"
    assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == \
        hashlib.sha256(data).hexdigest()


def test_upload_png_sniffed(fresh_server):
    from io import BytesIO
    base, _state, _out, cap = fresh_server
    buf = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
    status, resp = _upload(base, "Kitchen", "wall", buf.getvalue())
    assert status == 200 and resp["stored_as"] == "wall.png"
    assert (cap / "Kitchen" / "wall.png").is_file()


def test_upload_unsniffable_400(fresh_server):
    base, _state, _out, cap = fresh_server
    status, resp = _upload(base, "Kitchen", "notes.txt", b"just some text")
    assert status == 400
    assert "JPEG, PNG or HEIC" in resp["error"]
    assert not list(cap.rglob("notes*"))       # nothing was written


def test_upload_traversal_400(fresh_server, tmp_path):
    base, _state, _out, cap = fresh_server
    data = _jpeg_bytes()
    for room, fname in [("../evil", "x.jpg"), ("Kitchen", "../../x.jpg"),
                        ("a/b", "x.jpg"), ("Kitchen", "..\\x.jpg"),
                        ("..", "x.jpg"), (".hidden", "x.jpg")]:
        status, resp = _upload(base, room, fname, data)
        assert status == 400, (room, fname, resp)
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "x.jpg").exists()
    assert not list(cap.rglob("x*"))           # nothing landed anywhere


def test_upload_never_clobbers(fresh_server):
    base, _state, _out, cap = fresh_server
    first, second = _jpeg_bytes(), _jpeg_bytes() + b"\x00"
    s1, r1 = _upload(base, "Kitchen", "wall.jpg", first)
    s2, r2 = _upload(base, "Kitchen", "wall.jpg", second)
    assert s1 == s2 == 200
    assert r1["stored_as"] == "wall.jpg" and r2["stored_as"] == "wall-1.jpg"
    assert (cap / "Kitchen" / "wall.jpg").read_bytes() == first   # untouched
    assert (cap / "Kitchen" / "wall-1.jpg").read_bytes() == second


def test_upload_413_over_64mib(fresh_server):
    base, _state, _out, cap = fresh_server
    # valid JPEG magic so the size cap — not the sniffer — must reject it
    data = b"\xff\xd8" + b"\x00" * (64 * 1024 * 1024)
    status, resp = _upload(base, "Kitchen", "huge.jpg", data)
    assert status == 413, resp
    assert not list(cap.rglob("huge*"))


def test_upload_header_level_413_without_reading_body(fresh_server):
    """M5a audit nit: a Content-Length over the body cap must 413 on the
    header alone (early return) and close the connection unread."""
    import socket as sock
    base, _state, _out, cap = fresh_server
    host, port = base.replace("http://", "").split(":")
    s = sock.create_connection((host, int(port)), timeout=15)
    try:
        s.sendall((
            "POST /api/photos HTTP/1.1\r\n"
            "Host: test\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {200 * 1024 * 1024}\r\n\r\n"
        ).encode())
        s.sendall(b"{")            # a token byte; the server must not wait
        data = b""
        while True:                # server must CLOSE the connection …
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    status_line = data.split(b"\r\n", 1)[0]
    assert b" 413 " in status_line + b" "      # … after answering 413
    assert b"64 MiB" in data
    assert not list(cap.rglob("*.jpg"))        # nothing was written


# ---- build-from-browser: confirm guard, progress, e2e ----------------------

def test_build_e2e_offline(fresh_server):
    """£0 end-to-end: server as `review CAP -o OUT --backend offline
    --no-detect`; upload photos; confirmed build; poll to done; rooms
    appear in /api/inventory."""
    base, state, out, _cap = fresh_server
    assert _upload(base, "Kitchen", "k1.jpg", _jpeg_bytes())[0] == 200
    assert _upload(base, "Living Room", "l1.jpg", _jpeg_bytes())[0] == 200

    # missing confirm -> 400; wrong backend named -> 400; nothing started
    status, resp = _req("POST", base + "/api/build", {})
    assert status == 400 and "confirm" in resp["error"]
    status, resp = _req("POST", base + "/api/build", {"confirm": "claude"})
    assert status == 400 and "offline" in resp["error"]
    status, resp = _req("GET", base + "/api/build")
    assert status == 200 and resp["status"] == "idle"

    # correct confirm starts the pinned £0 command — asserted as the FULL
    # spawned argument list, not just flag membership (M5a audit nit)
    status, resp = _req("POST", base + "/api/build", {"confirm": "offline"})
    assert status == 200, resp
    import sys as _sys
    with state.lock:
        cmd = state.build["cmd"]
    assert cmd == [_sys.executable, "-m", "homeinventory.cli", "build",
                   str(_cap), "-o", str(out),
                   "--backend", "offline", "--no-pdf", "--no-detect"]

    deadline = time.time() + 120
    while time.time() < deadline:
        status, resp = _req("GET", base + "/api/build")
        if resp["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert resp["status"] == "done", resp

    status, body = _req("GET", base + "/api/inventory")
    assert status == 200
    assert {r["name"] for r in body["inventory"]["rooms"]} == \
        {"Kitchen", "Living Room"}
    # "/" now serves the review app instead of the start page
    status, html = _get_text(base + "/")
    assert status == 200 and 'id="hi-data"' in html


def test_build_and_redescribe_concurrency_409(fresh_server):
    base, state, _out, _cap = fresh_server
    with state.lock:
        state.build = {"status": "running", "detail": "", "cmd": None}
    status, _ = _req("POST", base + "/api/build", {"confirm": "offline"})
    assert status == 409
    status, _ = _req("POST", base + "/api/redescribe",
                     {"room": "Kitchen", "confirm": "offline"})
    assert status == 409                        # build blocks redescribe
    with state.lock:
        state.build = {"status": "idle", "detail": "", "cmd": None}
        state.redescribe = {"status": "running", "room": "X", "detail": ""}
    status, _ = _req("POST", base + "/api/build", {"confirm": "offline"})
    assert status == 409                        # redescribe blocks build
    with state.lock:
        state.redescribe = {"status": "idle", "room": None, "detail": ""}


# ---- redescribe spend-guard retrofit ---------------------------------------

def test_redescribe_requires_confirm(server):
    base, _state, _out, _cap = server
    status, resp = _req("POST", base + "/api/redescribe", {"room": "Kitchen"})
    assert status == 400 and "confirm" in resp["error"]
    status, resp = _req("POST", base + "/api/redescribe",
                        {"room": "Kitchen", "confirm": "claude"})
    assert status == 400 and "offline" in resp["error"]
    # correct confirm still works end-to-end (offline, £0)
    status, resp = _req("POST", base + "/api/redescribe",
                        {"room": "Kitchen", "confirm": "offline"})
    assert status == 200, resp
    deadline = time.time() + 120
    while time.time() < deadline:
        _, s = _req("GET", base + "/api/redescribe")
        if s["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert s["status"] == "done", s


def test_redescribe_ui_names_backend(server):
    """Template assertion: the redescribe UI shows backend+model."""
    base, _state, _out, _cap = server
    status, html = _get_text(base + "/")
    assert status == 200
    assert "Uses backend:" in html              # label beside the button
    assert "offline (no AI)" in html            # payload backend_label


# ---- PDF export -------------------------------------------------------------

def test_pdf_export_and_serve(server):
    try:
        import weasyprint  # noqa: F401
    except Exception as e:
        pytest.skip(f"WeasyPrint not importable in this environment: {e}")
    base, _state, out, _cap = server
    status, resp = _req("POST", base + "/api/pdf", {})
    assert status == 200, resp
    assert (out / "inventory.pdf").is_file()
    req = urllib.request.Request(base + "/pdf")
    with urllib.request.urlopen(req) as r:
        assert r.status == 200
        assert r.headers.get("Content-Type") == "application/pdf"
        assert r.read(4) == b"%PDF"


def test_pdf_503_when_weasyprint_missing(server, monkeypatch):
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "weasyprint", None)  # import -> error
    base, _state, out, _cap = server
    status, resp = _req("POST", base + "/api/pdf", {})
    assert status == 503                       # never a silent 200
    assert "pip install homeinventory[pdf]" in resp["error"]
