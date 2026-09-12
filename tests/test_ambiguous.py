import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from station_steward.agent import AgentService
from station_steward.ambiguous import AmbiguousConnection, AmbiguousError
from station_steward.app import create_app

AGENT = "11111111-1111-4111-8111-111111111111"
HUMAN = "22222222-2222-4222-8222-222222222222"
WORKSPACE = "33333333-3333-4333-8333-333333333333"
PROJECT = "44444444-4444-4444-8444-444444444444"
TASK = "55555555-5555-4555-8555-555555555555"
KEY = "ak_test_only_not_a_real_secret"
CONTEXT = {"goal": "Clear staging", "scene": {"provenance": "simulated", "arm_available": False, "revision": 2}}


class Provider:
    def __init__(self):
        self.requests = []
        self.task = None
        self.timeout_after_create = False
        self.post_error = None
        self.read_error = None
        self.bad_assignment = False
        self.bad_id = False

    def handle(self, request):
        assert str(request.url).startswith("https://app.ambiguous.ai/")
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        self.requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/users/me":
            return httpx.Response(200, json={"id": AGENT, "workspace_id": WORKSPACE, "display_name": "Station Steward", "type": "agent"})
        if path == "/api/users":
            return httpx.Response(200, json={"data": [{"id": HUMAN, "type": "human", "display_name": "Teammate"}, {"id": AGENT, "type": "agent", "display_name": "Agent"}]})
        if path == "/api/projects":
            return httpx.Response(200, json={"data": [{"id": PROJECT, "name": "Hackathon"}]})
        if path == "/api/tasks" and request.method == "POST":
            if self.post_error:
                return httpx.Response(self.post_error, json={"error": "private provider error body"})
            body = json.loads(request.content)
            assert "priority" not in body  # Do not accidentally apply an SLA due date.
            self.task = {**body, "id": TASK, "creator_id": AGENT}
            if self.bad_assignment:
                self.task["assignee_id"] = AGENT
            if self.timeout_after_create:
                raise httpx.ReadTimeout("private timeout detail")
            return httpx.Response(201, json={"task": {} if self.bad_id else self.task})
        if path == "/api/tasks" and request.method == "GET":
            return httpx.Response(200, json={"data": [self.task] if self.task else [], "has_more": False})
        if path == f"/api/tasks/{TASK}":
            return httpx.Response(self.read_error or 200, json={"task": self.task})
        raise AssertionError(f"Unexpected provider operation: {request.method} {path}")

    @property
    def posts(self):
        return self.requests.count(("POST", "/api/tasks"))


@pytest.fixture
def connected(tmp_path):
    provider = Provider()
    connection = AmbiguousConnection(tmp_path, httpx.MockTransport(provider.handle))
    connection.connect(KEY)
    connection.enable(HUMAN, PROJECT)
    return connection, provider


def test_key_encrypted_identity_verified_and_destination_saved(connected):
    connection, provider = connected
    assert provider.posts == 0
    state = connection.snapshot()
    assert state["identity"]["workspace_id"] == WORKSPACE
    assert len(state["people"]) == 1
    assert state["enabled"]
    assert KEY not in json.dumps(state)
    assert KEY.encode() not in connection.credentials_path.read_bytes()
    restored = AmbiguousConnection(connection.directory, httpx.MockTransport(provider.handle))
    assert restored.snapshot()["assignee"]["id"] == HUMAN
    assert restored.snapshot()["enabled"]
    with pytest.raises(AmbiguousError):
        restored.enable(AGENT, PROJECT)


def test_task_created_assigned_read_back_and_never_reposted_after_restart(connected):
    connection, provider = connected
    result = connection.deliver("mission-1", "Reconnect the arm", CONTEXT)
    assert result["verified"] and result["sent_to_ambiguous"]
    assert result["url"] == f"https://app.ambiguous.ai/tasks/{TASK}"
    assert provider.task["assignee_id"] == HUMAN
    assert provider.task["project_id"] == PROJECT
    assert "station-steward:mission-1" in provider.task["description"]
    assert "simulated workcell" in provider.task["description"]
    restored = AmbiguousConnection(connection.directory, httpx.MockTransport(provider.handle))
    assert restored.deliver("mission-1", "Do not duplicate", CONTEXT)["task_id"] == TASK
    assert provider.posts == 1
    assert KEY not in connection.journal_path.read_text()


def test_timeout_after_creation_recovers_only_by_read_and_search(connected):
    connection, provider = connected
    provider.timeout_after_create = True
    result = connection.deliver("mission-2", "Reconnect arm", CONTEXT)
    assert result["status"] == "uncertain" and not result["verified"]
    connection.deliver("mission-2", "Retry", CONTEXT)
    assert provider.posts == 1
    recovered = connection.refresh("mission-2")
    assert recovered["task_id"] == TASK and recovered["verified"]
    assert provider.posts == 1


def test_unconfirmed_timeout_without_search_match_never_creates_replacement(connected):
    connection, provider = connected
    provider.timeout_after_create = True
    connection.deliver("mission-no-match", "Reconnect arm", CONTEXT)
    provider.task = None
    assert not connection.refresh("mission-no-match")["verified"]
    assert provider.posts == 1


def test_bad_success_id_remains_uncertain_and_can_be_recovered(connected):
    connection, provider = connected
    provider.bad_id = True
    result = connection.deliver("mission-bad-id", "Reconnect arm", CONTEXT)
    assert result["status"] == "uncertain"
    assert connection.refresh("mission-bad-id")["verified"]
    assert provider.posts == 1


def test_readback_failure_does_not_claim_verified_creation(connected):
    connection, provider = connected
    provider.read_error = 503
    result = connection.deliver("mission-read-failed", "Reconnect arm", CONTEXT)
    assert result["status"] == "created_unverified"
    assert result["sent_to_ambiguous"] and not result["verified"]
    provider.read_error = None
    assert connection.refresh("mission-read-failed")["verified"]
    assert provider.posts == 1


def test_wrong_assignment_is_not_accepted_as_verified(connected):
    connection, provider = connected
    provider.bad_assignment = True
    result = connection.deliver("mission-wrong", "Reconnect arm", CONTEXT)
    assert result["status"] == "needs_review" and not result["verified"]


def test_provider_denial_sanitized_and_not_retried(connected):
    connection, provider = connected
    provider.post_error = 403
    result = connection.deliver("mission-denied", "Reconnect arm", CONTEXT)
    assert result["status"] == "not_sent"
    assert "private provider" not in result["error"]
    connection.deliver("mission-denied", "Do not retry", CONTEXT)
    assert provider.posts == 1


def test_handoff_is_inside_pollard_and_replay_never_writes(connected):
    connection, provider = connected

    def response(_):
        return {"ok": True, "usage_available": True, "usage": {"input_tokens": 1, "output_tokens": 1},
                "output": [{"type": "function_call", "name": "request_human_help", "call_id": "handoff", "arguments": json.dumps({"summary": "Reconnect virtual arm"})}]}

    service = AgentService(responder=response, handoff_sink=connection.deliver, handoff_enabled=lambda: True)
    mission = service.start("Clear staging", 24, "test", background=False)
    service.execute(mission)
    assert mission.handoff["verified"]
    assert mission.status == "needs_human"
    assert mission.report["spent"]["steps"] == 2
    before = service.scene()
    service.replay(mission.id)
    assert provider.posts == 1 and service.scene() == before
    provider.task["status"] = "done"
    service.sync_handoff(connection.refresh(mission.id))
    assert mission.handoff["remote_status"] == "done"
    assert mission.status == "needs_human"  # A human task status is not simulator evidence.


def test_budget_stops_external_task_before_callback(connected):
    connection, provider = connected
    service = AgentService(responder=lambda _: {"ok": True, "usage_available": True, "usage": {"input_tokens": 1, "output_tokens": 1},
                          "output": [{"type": "function_call", "name": "request_human_help", "call_id": "one", "arguments": '{"summary":"Help"}'}]}, handoff_sink=connection.deliver)
    mission = service.start("Help", 1, "test", background=False)
    service.execute(mission)
    assert mission.status == "budget_exhausted"
    assert provider.posts == 0


def test_connection_routes_reject_phone_and_never_echo_key(tmp_path):
    app = create_app(connection_directory=tmp_path)
    provider = Provider()
    app.state.ambiguous.transport = httpx.MockTransport(provider.handle)
    with TestClient(app, client=("192.168.1.88", 1234)) as remote:
        assert remote.post("/api/ambiguous/connect", json={"key": KEY}).status_code == 403
        assert remote.get("/api/ambiguous/connection").status_code == 403
    with TestClient(app) as local:
        response = local.post("/api/ambiguous/connect", json={"key": KEY})
        assert response.status_code == 200
        assert KEY not in response.text
        assert local.post("/api/ambiguous/destination", json={"assignee_id": HUMAN, "project_id": PROJECT}).json()["enabled"]
        assert local.post("/api/ambiguous/disconnect", json={}).json()["connected"] is False
        assert not app.state.ambiguous.credentials_path.exists()
    assert provider.posts == 0


def test_unreadable_journal_blocks_writes(tmp_path):
    (tmp_path / "ambiguous-handoffs.json").write_text("not-json")
    provider = Provider()
    connection = AmbiguousConnection(tmp_path, httpx.MockTransport(provider.handle))
    connection.connect(KEY)
    with pytest.raises(AmbiguousError, match="handoff log"):
        connection.enable(HUMAN, PROJECT)
    assert provider.posts == 0


def test_stop_during_identity_check_prevents_new_task(connected):
    connection, provider = connected
    stopped = threading.Event()
    original = provider.handle

    def stop_after_identity(request):
        result = original(request)
        if request.url.path == "/api/users/me":
            stopped.set()
        return result

    connection.transport = httpx.MockTransport(stop_after_identity)
    result = connection.deliver("mission-stopped", "Help", CONTEXT, cancelled=stopped.is_set)
    assert result["status"] == "cancelled"
    assert provider.posts == 0


def test_untrusted_hostname_cannot_use_privileged_loopback_routes(tmp_path):
    app = create_app(connection_directory=tmp_path)
    with TestClient(app, base_url="http://rebound.example:8765", client=("127.0.0.1", 1234)) as client:
        assert client.post("/api/ambiguous/disconnect", json={}, headers={"Origin": "http://rebound.example:8765"}).status_code == 403
        assert client.post("/api/agent/scene", json={"action": "toggle_arm"}, headers={"Origin": "http://rebound.example:8765"}).status_code == 403
