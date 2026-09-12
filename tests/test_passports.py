from datetime import timedelta
from io import BytesIO

import pytest
import qrcode
from fastapi.testclient import TestClient
from PIL import Image, ImageFilter

import station_steward.app as module


@pytest.fixture
def client(tmp_path):
    with TestClient(module.create_app(connection_directory=tmp_path)) as test_client:
        yield test_client


def create(client, station="bench"):
    response = client.post("/api/passports", json={"station_id": station})
    assert response.status_code == 200
    return response.json()


def scan(client, session_id, image):
    return client.post(f"/api/passports/{session_id}/scan", content=image, headers={"Content-Type": "image/png"})


def qr_bytes(payload):
    return module.png_bytes(qrcode.make(payload).convert("RGB"))


def test_real_library_roundtrip_and_receipt_replay(client, monkeypatch):
    session = create(client)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    code = Image.open(BytesIO(raw)).convert("RGB")
    assert {color for _, color in code.getcolors()} == {(0, 0, 0), (255, 255, 255)}
    assert code.size == (348, 348)
    # Embed the code in a wider frame to exercise image-based detection.
    camera_like_frame = Image.new("RGB", (640, 480), "white")
    camera_like_frame.paste(Image.open(BytesIO(raw)), (135, 55))
    response = scan(client, session["id"], module.png_bytes(camera_like_frame))
    assert response.status_code == 200
    result = response.json()
    assert result["scan"]["payload"] == session["qr_payload"]
    assert result["scan"]["verified"]
    assert result["passport"]["budget"]["used"] == 1
    assert result["passport"]["evidence"]["fresh"]
    observed = result["passport"]["evidence"]["observed_at"]
    monkeypatch.setattr(module, "decode_frame", lambda *_: pytest.fail("Replay called live decoder"))
    replay = client.get(f"/api/passports/{session['id']}/replay").json()
    assert replay["historical"] and replay["records"][0]["verified"]
    assert replay["report"]["avoided"]["steps"] == 1
    assert replay["live_evidence_refreshed"] is False
    assert client.get(f"/api/passports/{session['id']}").json()["evidence"]["observed_at"] == observed


def test_unreadable_frame_clears_previous_verification(client):
    session = create(client)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    assert scan(client, session["id"], raw).json()["passport"]["evidence"]["fresh"]
    result = scan(client, session["id"], module.png_bytes(Image.new("RGB", (640, 480), "white"))).json()
    assert not result["scan"]["verified"]
    assert result["scan"]["payload"] == ""
    assert result["scan"]["reason"] == "unreadable"
    assert result["passport"]["budget"]["used"] == 2
    assert not result["passport"]["evidence"]["fresh"]


@pytest.mark.parametrize("payload", ["SS2:000000000000", "https://example.com/?view=phone", b"\xff\xfe\xfd"])
def test_foreign_qr_rejected(client, payload):
    session = create(client)
    result = scan(client, session["id"], qr_bytes(payload)).json()
    assert result["scan"]["complete"]
    assert not result["scan"]["verified"]
    assert result["scan"]["reason"] == "different_passport"
    assert not result["passport"]["evidence"]["fresh"]


@pytest.mark.parametrize("same_code", [False, True])
def test_distinct_codes_rejected_but_identical_reflections_allowed(client, same_code):
    session = create(client)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    code = Image.open(BytesIO(raw))
    other = code if same_code else Image.open(BytesIO(qr_bytes("SS2:000000000000")))
    frame = Image.new("RGB", (900, 500), "white")
    frame.paste(code, (40, 40))
    frame.paste(other, (480, 40))
    result = scan(client, session["id"], module.png_bytes(frame)).json()
    assert result["scan"]["verified"] is same_code
    assert result["scan"]["reason"] == ("matched" if same_code else "multiple_codes")


def test_rotated_slightly_blurred_qr_can_be_read(client):
    session = create(client)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    frame = Image.open(BytesIO(raw)).rotate(12, expand=True, fillcolor="white").filter(ImageFilter.GaussianBlur(0.6))
    assert scan(client, session["id"], module.png_bytes(frame)).json()["scan"]["verified"]


def test_expired_and_superseded_sessions_rejected(client):
    old = create(client)
    raw = client.get(f"/api/passports/{old['id']}/code.png").content
    current = create(client, "virtual")
    assert scan(client, old["id"], raw).status_code == 409
    assert scan(client, current["id"], raw).json()["scan"]["reason"] == "different_passport"
    client.app.state.sessions[current["id"]].created_at -= timedelta(seconds=301)
    assert scan(client, current["id"], raw).status_code == 410


def test_scan_budget_prevents_extra_decoder_call(client, monkeypatch):
    monkeypatch.setattr(module, "SCAN_BUDGET", 1)
    session = create(client)
    raw = module.png_bytes(Image.new("RGB", (100, 100), "white"))
    assert scan(client, session["id"], raw).status_code == 200
    monkeypatch.setattr(module, "decode_frame", lambda *_: pytest.fail("Over-budget decoder called"))
    assert scan(client, session["id"], raw).status_code == 429
    assert client.get(f"/api/passports/{session['id']}").json()["budget"]["used"] == 1


def test_chronofy_expires_success_without_refreshing_timestamp(client):
    session = create(client)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    assert scan(client, session["id"], raw).json()["scan"]["verified"]
    stored = client.app.state.sessions[session["id"]]
    stored.fact.timestamp -= timedelta(seconds=31)
    assert not client.get(f"/api/passports/{session['id']}").json()["evidence"]["fresh"]


def test_invalid_and_oversized_frames_rejected(client):
    session = create(client)
    assert scan(client, session["id"], b"not an image").status_code == 422
    assert scan(client, session["id"], b"x" * (module.MAX_UPLOAD + 1)).status_code == 413
    large = module.png_bytes(Image.new("RGB", (2000, 1500), "white"))
    assert scan(client, session["id"], large).status_code == 413
    assert client.get(f"/api/passports/{session['id']}").json()["budget"]["used"] == 0


def test_cross_origin_write_and_unknown_station_rejected(client):
    assert client.post("/api/passports", json={"station_id": "bench"}, headers={"Origin": "https://unrelated.example"}).status_code == 403
    assert client.post("/api/passports", json={"station_id": "invented-device"}).status_code == 422


def test_backend_cannot_execute_physical_commands(client):
    response = client.post("/api/fan/on", json={})
    assert response.status_code in {404, 405}
    state = client.get("/api/state").json()
    assert {station["id"] for station in state["stations"]} == {"bench", "virtual"}
    hardware = client.get("/api/hardware/state").json()
    assert hardware["read_only"] and not hardware["connected"]


def test_expiry_during_decode_is_preserved_in_replay(client, monkeypatch):
    session = create(client)
    stored = client.app.state.sessions[session["id"]]
    original = module.decode_frame

    def decode_then_expire(*args):
        result = original(*args)
        stored.created_at -= timedelta(seconds=301)
        return result

    monkeypatch.setattr(module, "decode_frame", decode_then_expire)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    live = scan(client, session["id"], raw).json()
    replay = client.get(f"/api/passports/{session['id']}/replay").json()
    assert live["scan"]["matched"] and not live["scan"]["verified"]
    assert live["scan"]["reason"] == replay["records"][0]["reason"] == "expired"
    assert not replay["records"][0]["verified"]


def test_station_switch_invalidates_old_evidence(client):
    session = create(client)
    raw = client.get(f"/api/passports/{session['id']}/code.png").content
    assert scan(client, session["id"], raw).json()["passport"]["evidence"]["fresh"]
    create(client, "virtual")
    old = client.get(f"/api/passports/{session['id']}").json()
    assert not old["active"] and not old["evidence"]["fresh"]
