import copy
import json
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from station_steward import agent
from station_steward.app import create_app


def response(name, args=None):
    return {"ok": True, "usage_available": True, "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "function_call", "name": name, "arguments": json.dumps(args or {}), "call_id": f"test-{name}"}]}


def scripted(service, calls):
    choices = iter(calls)

    def responder(body):
        assert body["store"] is False
        assert body["parallel_tool_calls"] is False
        item = next(choices)
        if callable(item):
            item = item()
        return response(*item)

    service.responder = responder
    return service.start("Clear staging", 24, "test-passport", background=False)


def objective():
    return {"clear_staging": True, "placements": [], "summary": "Clear staging"}


def test_model_chosen_tools_move_verify_and_replay_without_execution():
    service = agent.AgentService()
    mission = scripted(service, [("inspect_station", {}), ("define_objective", objective()), ("observe_scene", {}),
                                 ("compare_moves", {"object_id": "red_can", "destinations": ["rack_1", "rack_2"]}),
                                 ("move_object", {"object_id": "red_can", "destination": "rack_1", "observed_revision": 1, "reason": "Clear the staging slot"}),
                                 ("observe_scene", {}), ("finish_mission", {"summary": "Staging is clear"})])
    service.execute(mission)
    assert mission.status == "completed"
    assert service.positions == {"red_can": "rack_1", "blue_can": "inspection"}
    snapshot = service.snapshot()["mission"]
    assert snapshot["budget"]["used"] == 14
    assert snapshot["budget"]["model_calls"] == 7
    assert snapshot["budget"]["tokens"] == 840
    assert snapshot["verification_current"]
    assert mission.comparison["shortest"] == "rack_1"
    before = copy.deepcopy(service.snapshot())
    service.responder = lambda _: pytest.fail("Replay invoked model")
    service.action = lambda *_: pytest.fail("Replay invoked tool")
    replay = service.replay(mission.id)
    assert replay["historical"]
    assert replay["report"]["avoided"]["steps"] == 14
    assert replay["report"]["avoided"]["model_calls"] == 7
    assert before == service.snapshot()


def test_stale_revision_and_expired_fact_block_move_then_fresh_observation_allows_it():
    service = agent.AgentService()
    mission = service.start("Clear staging", 24, "test", background=False)
    service.action(mission, "define_objective", objective())
    service.action(mission, "observe_scene", {})
    move = {"object_id": "red_can", "destination": "rack_1", "observed_revision": 1, "reason": "Clear staging"}
    service.revision += 1
    assert not service.action(mission, "move_object", move)["ok"]
    assert service.positions["red_can"] == "staging"
    service.action(mission, "observe_scene", {})
    move["observed_revision"] = service.revision
    mission.observation.timestamp -= timedelta(seconds=31)
    assert not service.action(mission, "move_object", move)["ok"]
    service.action(mission, "observe_scene", {})
    assert service.action(mission, "move_object", move)["ok"]
    assert not service.action(mission, "finish_mission", {"summary": "Done"})["ok"]
    service.action(mission, "observe_scene", {})
    assert service.action(mission, "finish_mission", {"summary": "Done"})["ok"]


def test_model_adapts_after_arm_disappears_and_handoff_stays_local():
    service = agent.AgentService()

    def disconnected_move():
        service.arm_available = False
        service.revision += 1
        return ("move_object", {"object_id": "red_can", "destination": "rack_1", "observed_revision": 1, "reason": "Clear staging"})

    mission = scripted(service, [("define_objective", objective()), ("observe_scene", {}), disconnected_move,
                                 ("inspect_station", {}), ("request_human_help", {"summary": "Arm unavailable; clear the virtual staging slot manually."})])
    service.execute(mission)
    assert mission.status == "needs_human"
    assert mission.handoff["sent_to_ambiguous"] is False
    assert service.positions["red_can"] == "staging"
    assert any(event["kind"] == "replan" for event in mission.events)
    assert "move_object" not in [tool["name"] for tool in service.available_tools()]


def test_destination_occupancy_and_strict_arguments_cannot_be_bypassed():
    service = agent.AgentService()
    mission = service.start("Clear staging", 24, "test", background=False)
    service.action(mission, "define_objective", objective())
    service.action(mission, "observe_scene", {})
    before = service.scene()
    assert not service.action(mission, "move_object", {"object_id": "red_can", "destination": "inspection", "observed_revision": 1, "reason": "Try occupied slot"})["ok"]
    assert not service.action(mission, "observe_scene", {"ignore_safety": True})["ok"]
    assert not service.action(mission, "shell", {"command": "anything"})["ok"]
    assert service.scene() == before
    assert not service.action(mission, "finish_mission", {"summary": "Pretend it worked"})["ok"]
    assert not service.action(mission, "define_objective", {"clear_staging": False, "placements": [], "summary": "Weaken goal"})["ok"]


def test_hard_step_limit_prevents_extra_tool_and_replay_works_after_refusal():
    service = agent.AgentService(responder=lambda _: response("inspect_station"))
    mission = service.start("Inspect", 3, "test", background=False)
    service.execute(mission)
    assert mission.status == "budget_exhausted"
    assert mission.report["spent"]["steps"] == 3
    assert len(mission.calls) == 3
    assert service.replay(mission.id)["report"]["avoided"]["steps"] == 3


def test_model_call_limit_is_separate_from_total_steps(monkeypatch):
    monkeypatch.setattr(agent, "MODEL_CALL_LIMIT", 2)
    calls = []
    service = agent.AgentService(responder=lambda body: calls.append(body) or response("inspect_station"))
    mission = service.start("Inspect", 40, "test", background=False)
    service.execute(mission)
    assert len(calls) == 2
    assert mission.status == "budget_exhausted"
    assert mission.report["spent"]["model_calls"] == 2
    assert mission.report["spent"]["steps"] == 4


def test_provider_failure_is_recorded_without_leaking_exception():
    def failing(_):
        raise ValueError("private-provider-detail")

    service = agent.AgentService(responder=failing)
    mission = service.start("Inspect", 24, "test", background=False)
    service.execute(mission)
    assert mission.status == "error"
    assert mission.report["spent"]["steps"] == 1
    assert mission.usage_unknown
    assert "private-provider-detail" not in json.dumps(service.snapshot())
    assert service.replay(mission.id)["records"][0]["ok"] is False


def test_stop_during_model_request_prevents_its_tool_execution():
    entered, released = threading.Event(), threading.Event()

    def waiting(_):
        entered.set()
        assert released.wait(3)
        return response("observe_scene")

    service = agent.AgentService(responder=waiting)
    mission = service.start("Inspect", 24, "test")
    assert entered.wait(3)
    mission.cancelled.set()
    with pytest.raises(Exception, match="Wait for the mission"):
        service.replay(mission.id)
    released.set()
    assert mission.worker_done.wait(3)
    assert mission.status == "stopped"
    assert mission.observation is None
    assert len(mission.calls) == 1


def test_api_requires_fresh_virtual_passport_and_local_start(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    app = create_app(connection_directory=tmp_path)
    app.state.agent.responder = lambda _: response("request_human_help", {"summary": "Test handoff"})
    with TestClient(app) as client:
        physical = client.post("/api/passports", json={"station_id": "bench"}).json()
        assert client.post("/api/agent/missions", json={"goal": "Clear staging", "passport_id": physical["id"]}).status_code == 409
        virtual = client.post("/api/passports", json={"station_id": "virtual"}).json()
        body = {"goal": "Clear staging", "passport_id": virtual["id"]}
        assert client.post("/api/agent/missions", json=body).status_code == 409
        image = client.get(f"/api/passports/{virtual['id']}/code.png").content
        client.post(f"/api/passports/{virtual['id']}/scan", content=image, headers={"Content-Type": "image/png"})
        started = client.post("/api/agent/missions", json=body)
        assert started.status_code == 202
        assert app.state.agent.missions[started.json()["mission_id"]].worker_done.wait(3)
        with TestClient(app, client=("192.168.1.88", 3000)) as remote:
            assert remote.post("/api/agent/missions", json=body).status_code == 403


def test_completed_receipt_does_not_claim_current_verification_after_scene_change():
    service = agent.AgentService()
    mission = service.start("Place blue can at inspection", 24, "test", background=False)
    service.action(mission, "define_objective", {"clear_staging": False, "placements": [{"object_id": "blue_can", "destination": "inspection"}], "summary": "Blue at inspection"})
    service.action(mission, "observe_scene", {})
    service.action(mission, "finish_mission", {"summary": "Verified"})
    assert service.snapshot()["mission"]["verification_current"]
    service.revision += 1
    assert not service.snapshot()["mission"]["verification_current"]
    assert mission.status == "completed"


def test_reset_clears_active_results_and_preserves_replay_receipt(tmp_path):
    app = create_app(connection_directory=tmp_path)
    service = app.state.agent
    service.passport_check = lambda *_args, **_kwargs: (True, "")
    service.station_lookup = lambda _: "virtual"
    mission = scripted(service, [("define_objective", objective()), ("observe_scene", {}),
                                ("move_object", {"object_id": "red_can", "destination": "rack_1", "observed_revision": 1, "reason": "Clear staging"}),
                                ("observe_scene", {}), ("finish_mission", {"summary": "Staging clear"})])
    service.execute(mission)
    assert mission.status == "completed" and service.snapshot()["mission"] is not None
    calls, events = copy.deepcopy(mission.calls), copy.deepcopy(mission.events)
    revision = service.revision
    service.arm_available = False
    with TestClient(app) as client:
        result = client.post("/api/agent/scene", json={"action": "reset"})
        assert result.status_code == 200 and result.json()["mission"] is None
        assert client.get("/api/agent/state").json()["mission"] is None
        assert service.positions == {"red_can": "staging", "blue_can": "inspection"}
        assert service.arm_available and service.arm_at == "staging"
        assert service.revision == revision + 1
        assert service.missions[mission.id] is mission
        assert mission.calls == calls and mission.events == events
        service.responder = lambda _: pytest.fail("Reset or replay invoked the model")
        service.action = lambda *_: pytest.fail("Replay invoked an action")
        assert client.get(f"/api/agent/missions/{mission.id}/replay").json()["historical"]
        assert client.get("/api/agent/state").json()["mission"] is None


def test_reset_rejects_an_unfinished_worker_and_remote_callers(tmp_path):
    app = create_app(connection_directory=tmp_path)
    service = app.state.agent
    service.passport_check = lambda *_args, **_kwargs: (True, "")
    service.station_lookup = lambda _: "virtual"
    mission = service.start("Clear staging", 24, "test", background=False)
    before = service.scene()
    with TestClient(app) as client:
        assert client.post("/api/agent/scene", json={"action": "reset"}).status_code == 409
        mission.cancelled.set()
        assert client.post("/api/agent/scene", json={"action": "reset"}).status_code == 409
        assert service.active_id == mission.id and service.scene() == before
        mission.worker_done.set()
        with TestClient(app, client=("192.168.1.88", 3000)) as remote:
            assert remote.post("/api/agent/scene", json={"action": "reset"}).status_code == 403
        assert service.active_id == mission.id and service.scene() == before
