"""Physical handoffs preserve telemetry without claiming actuator verification."""

import json

import httpx
import pytest

from station_steward.ambiguous import AmbiguousConnection


AGENT = "11111111-1111-4111-8111-111111111111"
HUMAN = "22222222-2222-4222-8222-222222222222"
WORKSPACE = "33333333-3333-4333-8333-333333333333"
TASK = "55555555-5555-4555-8555-555555555555"
KEY = "ak_test_only_not_a_real_secret"


def deliver_description(tmp_path, context):
    identity = {"id": AGENT, "workspace_id": WORKSPACE, "display_name": "Station Steward", "type": "agent"}
    task = {}
    posts = []

    def provider(request):
        assert str(request.url).startswith("https://app.ambiguous.ai/")
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        if request.method == "GET" and request.url.path == "/api/users/me":
            return httpx.Response(200, json=identity)
        if request.method == "POST" and request.url.path == "/api/tasks":
            posts.append(json.loads(request.content))
            task.update(posts[-1], id=TASK, creator_id=AGENT)
            return httpx.Response(201, json={"task": task})
        if request.method == "GET" and request.url.path == f"/api/tasks/{TASK}":
            return httpx.Response(200, json={"task": task})
        raise AssertionError(f"Unexpected provider operation: {request.method} {request.url.path}")

    connection = AmbiguousConnection(tmp_path, transport=httpx.MockTransport(provider))
    connection.config = {"token": KEY, "identity": identity, "enabled": True,
                         "assignee": {"id": HUMAN, "name": "Teammate"}, "project": None}
    result = connection.deliver("hardware-wording", "Inspect the station", context)
    assert result["verified"] and result["sent_to_ambiguous"]
    assert len(posts) == 1
    assert posts[0]["assignee_id"] == HUMAN
    assert "Handoff reference: station-steward:hardware-wording" in posts[0]["description"]
    return posts[0]["description"]


def test_physical_handoff_preserves_telemetry_and_requires_fresh_bench_verification(tmp_path):
    context = {"station_id": "bench", "provenance": "physical", "goal": "Check the cooling station",
               "telemetry": {"temperature_c": 29.5, "humidity_percent": 61, "distance_cm": 17.2, "fan_commanded": True},
               "evidence": {"observed_at": "2026-09-12T19:00:00+00:00", "fresh": False}}
    description = deliver_description(tmp_path, context)
    assert "physical Arduino bench" in description and "real Arduino" in description
    assert "autonomous firmware control" in description
    assert "No agent actuator command or independently verified fan motion is claimed." in description
    assert "fresh bench observation" in description
    assert "simulated workcell" not in description and "simulator goal" not in description
    evidence = description.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(evidence) == context


@pytest.mark.parametrize("station_fields", [{"station_id": "virtual", "provenance": "simulated"}, {}])
def test_virtual_and_legacy_handoffs_keep_simulator_wording(tmp_path, station_fields):
    description = deliver_description(tmp_path, {"goal": "Clear staging", **station_fields})
    assert "simulated workcell handoff" in description
    assert "No physical hardware action is claimed." in description
    assert "simulator goal" in description
    assert "real Arduino" not in description and "fresh bench observation" not in description
