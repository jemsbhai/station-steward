"""The actual camera/passport API must select the physical agent tools."""
import json

from fastapi.testclient import TestClient

from station_steward.app import create_app
from station_steward.hardware import HardwareService


def test_scanned_bench_passport_selects_physical_tools_without_serial_or_external_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-only")
    hardware = HardwareService(serial_factory=lambda **_: (_ for _ in ()).throw(AssertionError("Unexpected serial open")))
    app = create_app(connection_directory=tmp_path, hardware_service=hardware)
    requests = []

    def response(body):
        requests.append(body)
        return {"ok": True, "usage_available": True, "usage": {"input_tokens": 5, "output_tokens": 5},
                "output": [{"type": "function_call", "call_id": "test-handoff", "name": "request_human_help",
                            "arguments": json.dumps({"summary": "Reconnect Arduino USB before inspecting the bench."})}]}

    app.state.agent.responder = response
    with TestClient(app) as client:
        passport = client.post("/api/passports", json={"station_id": "bench"}).json()
        body = {"goal": "Check at least 20 cm clearance", "passport_id": passport["id"]}
        assert client.post("/api/agent/missions", json=body).status_code == 409
        # Synthetic QR round trip tests API routing, not physical camera behavior.
        png = client.get(f"/api/passports/{passport['id']}/code.png").content
        assert client.post(f"/api/passports/{passport['id']}/scan", content=png, headers={"Content-Type": "image/png"}).json()["scan"]["verified"]
        started = client.post("/api/agent/missions", json=body)
        assert started.status_code == 202
        mission = app.state.agent.missions[started.json()["mission_id"]]
        assert mission.worker_done.wait(3)
        state = client.get("/api/agent/state").json()
        assert state["mission"]["station_id"] == "bench"
        assert state["mission"]["handoff"]["status"] == "pending_local"
        assert "observe_bench" in {x["name"] for x in requests[0]["tools"]}
        assert "move_object" not in {x["name"] for x in requests[0]["tools"]}
        assert client.get(f"/api/agent/missions/{mission.id}/replay").json()["historical"]
