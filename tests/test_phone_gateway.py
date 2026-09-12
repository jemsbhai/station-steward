import html
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from station_steward.phone_gateway import create_gateway

ORIGIN = "https://phone.example.test"
PASSPORT = {"id": "ABCDEF123456", "station": {"id": "bench"}, "expired": False,
            "last_scan": {"payloads": ["private-foreign-qr"]}}


@pytest.fixture
def gateway():
    requests = []

    def upstream(request):
        requests.append(request)
        assert request.url.host == "localhost" and request.url.port == 8765
        assert "cookie" not in request.headers and "x-forwarded-for" not in request.headers
        if request.url.path == "/api/state":
            return httpx.Response(200, json={"stations": [], "active": PASSPORT, "private": "do-not-export"})
        if request.url.path.endswith("/code.png"):
            return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})
        assert request.url.path in {"/api/passports", "/api/passports/ABCDEF123456"}
        if request.method == "POST":
            assert request.headers["origin"] == "http://localhost:8765"
        return httpx.Response(200, json=PASSPORT)

    app = create_gateway(transport=httpx.MockTransport(upstream), tunnel_lookup=lambda: ORIGIN)
    with TestClient(app, base_url=ORIGIN) as client:
        local = client.get("http://localhost/pair")
        assert local.status_code == 200
        link = html.unescape(re.search(r'href="(https://[^\"]+\?pair=[^\"]+)"', local.text).group(1))
        yield client, link, requests


def pair(client, link):
    response = client.get(link, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?view=phone"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


def test_unpaired_requests_and_tunnel_pairing_are_denied(gateway):
    client, _, requests = gateway
    for route in ["/", "/api/state", "/api/passports", "/assets/app.js"]:
        assert client.get(route).status_code == 401
    for route in ["/pair", "/pair.png"]:
        assert client.get(route).status_code == 403
        assert client.get("http://localhost" + route, headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    assert requests == []


def test_paired_state_and_passports_remove_foreign_scan_data(gateway):
    client, link, _ = gateway
    pair(client, link)
    for route in ["/api/state", "/api/passports/ABCDEF123456"]:
        response = client.get(route)
        assert response.status_code == 200
        assert "private-foreign-qr" not in response.text and "do-not-export" not in response.text
    created = client.post("/api/passports", json={"station_id": "bench"}, headers={"Origin": ORIGIN})
    assert created.status_code == 200 and created.json()["last_scan"] is None
    assert client.get("/api/passports/ABCDEF123456/code.png").content == b"png"
    assert client.post("/api/passports", json={"station_id": "bench"}, headers={"Origin": ORIGIN}).status_code == 429


@pytest.mark.parametrize("route", ["/api/agent/state", "/api/agent/missions", "/api/hardware/state", "/api/ambiguous/connection", "/api/passports/ABCDEF123456/scan", "/api/passports/ABCDEF123456/replay", "/api/state/../agent/state", "/api/passports/ABCDEF123456%2Fscan"])
def test_paired_phone_cannot_access_laptop_apis(gateway, route):
    client, link, requests = gateway
    pair(client, link)
    assert client.get(route).status_code == 404
    assert client.post(route, json={}, headers={"Origin": ORIGIN}).status_code == 404
    assert requests == []


def test_post_origin_body_and_host_boundaries(gateway):
    client, link, requests = gateway
    pair(client, link)
    for origin in [None, "https://unrelated.example", "http://localhost:8765"]:
        headers = {"Origin": origin} if origin else {}
        assert client.post("/api/passports", json={"station_id": "bench"}, headers=headers).status_code == 403
    assert client.post("/api/passports", content=b"x" * 1025, headers={"Origin": ORIGIN, "Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/passports", content=b"{}", headers={"Origin": ORIGIN, "Content-Type": "text/plain"}).status_code == 415
    assert client.get("/api/state", headers={"Host": "localhost"}).status_code == 403
    assert client.get("/?view=camera", follow_redirects=False).headers["location"] == "/?view=phone"
    assert requests == []
