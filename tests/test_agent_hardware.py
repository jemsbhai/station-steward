import copy
import json
from datetime import timedelta

import pytest

from station_steward import agent


GOAL = "Check the Arduino inspection zone. It must have at least 20 cm clearance. If blocked or unmeasurable, assign a human to inspect or clear it."
OBJECTIVE = {"minimum_distance_cm": 20, "summary": "Verify at least 20 cm clearance."}


class FakeHardware:
    def __init__(self, distance=30):
        self.reads = 0
        self.observations = 0
        self.capability_reads = 0
        self.data = {"connected": True, "fresh": True, "received_at": agent.now().isoformat(),
                     "sequence": 1, "session_id": "connection-a",
                     "telemetry": {"distance_cm": distance, "distance_valid": True,
                                   "temperature_c": 25, "humidity_pct": 60, "fan_reported": "on",
                                   "joystick": {"x": 512, "y": 512}, "dht_age_seconds": None,
                                   "dht_valid": None, "dht_status": "Cached; measurement age unknown"}}

    def snapshot(self):
        self.reads += 1
        return copy.deepcopy(self.data)

    def observe(self):
        self.observations += 1
        return {"ok": self.data["connected"] and self.data["fresh"], "provenance": "physical", **self.snapshot()}

    def capabilities(self):
        self.capability_reads += 1
        return {"read_only": True, "tools": ["uno/read_telemetry"], "fan_control": "autonomous firmware"}


def response(name, args=None):
    return {"ok": True, "usage_available": True, "usage": {"input_tokens": 100, "output_tokens": 20},
            "output": [{"type": "function_call", "name": name, "arguments": json.dumps(args or {}), "call_id": f"test-{name}"}]}


def bench(hardware=None, **kwargs):
    hardware = hardware or FakeHardware()
    return agent.AgentService(hardware=hardware, station_lookup=lambda _: "bench", **kwargs), hardware


def start_observed(service, goal=GOAL):
    mission = service.start(goal, 24, "bench-passport", background=False)
    assert service.action(mission, "define_bench_objective", OBJECTIVE)["ok"]
    assert service.action(mission, "observe_bench", {})["ok"]
    return mission


def test_physical_model_loop_verifies_clearance_and_replay_never_reads_hardware():
    service, hardware = bench()
    selected = iter([("inspect_station", {}), ("define_bench_objective", OBJECTIVE),
                     ("observe_bench", {}), ("finish_mission", {"summary": "I switched on the fan and cleared everything."})])

    def responder(body):
        assert {tool["name"] for tool in body["tools"]} == set(agent.BENCH_TOOL_MODELS)
        assert "cached" in body["instructions"] and "autonomously" in body["instructions"]
        return response(*next(selected))

    service.responder = responder
    mission = service.start(GOAL, 24, "bench-passport", background=False)
    virtual_before = service.scene()
    service.execute(mission)
    assert mission.status == "completed"
    assert mission.station_id == "bench"
    assert "30 cm" in mission.summary and "No hardware command" in mission.summary
    assert "switched" not in mission.summary
    assert service.scene() == virtual_before
    assert service.snapshot()["mission"]["verification_current"]
    assert mission.report["spent"]["steps"] == 8
    assert mission.report["spent"]["tokens"] == 480
    before = hardware.reads, hardware.observations, hardware.capability_reads
    evidence = copy.deepcopy(mission.bench_observation)
    service.responder = lambda _: pytest.fail("Replay called model")
    service.action = lambda *_: pytest.fail("Replay called physical tool")
    replay = service.replay(mission.id)
    assert replay["report"]["avoided"]["steps"] == 8
    assert replay["report"]["avoided"]["model_calls"] == 4
    assert (hardware.reads, hardware.observations, hardware.capability_reads) == before
    assert mission.bench_observation == evidence


def test_physical_station_cannot_execute_virtual_or_fan_tools():
    service, hardware = bench()
    mission = service.start(GOAL, 24, "bench-passport", background=False)
    scene = service.scene()
    for name in ["define_objective", "observe_scene", "compare_moves", "move_object", "fan_on", "set_fan"]:
        assert not service.action(mission, name, {})["ok"]
    assert service.scene() == scene
    assert hardware.observations == 0
    assert "move_object" in {tool["name"] for tool in service.available_tools()}
    assert "move_object" not in {tool["name"] for tool in service.available_tools(mission)}


@pytest.mark.parametrize("distance,valid", [(None, False), (0, True), (1.99, True), (401, True),
                                            (float("nan"), True), (float("inf"), True),
                                            (True, True), (19.9, True), (30, False)])
def test_invalid_or_below_minimum_current_distance_never_finishes(distance, valid):
    service, hardware = bench()
    mission = start_observed(service)
    hardware.data["telemetry"].update(distance_cm=distance, distance_valid=valid)
    result = service.action(mission, "finish_mission", {"summary": "Complete"})
    assert not result["ok"]
    assert mission.status == "running"


@pytest.mark.parametrize("change", ["disconnected", "stale", "missing_sample", "new_session", "aged", "future"])
def test_finish_rejects_disconnected_stale_incomplete_or_changed_session(change):
    service, hardware = bench()
    mission = start_observed(service)
    if change == "disconnected":
        hardware.data["connected"] = False
    elif change == "stale":
        hardware.data["fresh"] = False
    elif change == "missing_sample":
        hardware.data["received_at"] = None
    elif change == "new_session":
        hardware.data["session_id"] = "connection-b"
    elif change == "aged":
        hardware.data["received_at"] = (agent.now() - timedelta(seconds=4)).isoformat()
    else:
        hardware.data["received_at"] = (agent.now() + timedelta(seconds=4)).isoformat()
    assert not service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]
    assert mission.status == "running"


def test_fresh_new_telemetry_does_not_refresh_old_mission_observation(monkeypatch):
    service, hardware = bench()
    mission = start_observed(service)
    old = copy.deepcopy(mission.bench_observation)
    later = agent.now() + timedelta(seconds=3)
    monkeypatch.setattr(agent, "now", lambda: later)
    hardware.data.update(received_at=later.isoformat(), sequence=2)
    assert not service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]
    assert mission.bench_observation == old
    assert service.action(mission, "observe_bench", {})["ok"]
    assert service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]


def test_current_clearance_cannot_replace_a_blocked_observation_without_reobserving():
    service, hardware = bench(FakeHardware(distance=10))
    mission = start_observed(service)
    hardware.data["telemetry"]["distance_cm"] = 30
    hardware.data["sequence"] += 1
    assert mission.bench_observation["telemetry"]["distance_cm"] == 10
    assert not service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]
    assert service.action(mission, "observe_bench", {})["ok"]
    assert service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]


def test_continuous_sequence_keeps_predicate_current_but_blockage_invalidates_receipt():
    service, hardware = bench()
    mission = start_observed(service)
    assert service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]
    hardware.data["sequence"] += 1
    hardware.data["telemetry"]["distance_cm"] = 25
    assert service.snapshot()["mission"]["verification_current"]
    hardware.data["telemetry"]["distance_cm"] = 10
    assert not service.snapshot()["mission"]["verification_current"]
    assert mission.status == "completed"


@pytest.mark.parametrize("goal", ["Cool the bench to 20 C", "Turn on the fan and verify 20 cm clearance", "Read current temperature",
                                  "Check humidity", "Move the can away to provide 20 cm clearance", "Check the inspection zone",
                                  "Activate the heater and inspect at least 20 cm clearance", "Set PWM to 50 and inspect at least 20 cm clearance",
                                  "Ensure 25 C and inspect at least 20 cm clearance"])
def test_unsupported_physical_goals_cannot_be_redefined_as_clearance_success(goal):
    service, _ = bench()
    mission = service.start(goal, 24, "bench-passport", background=False)
    assert not service.action(mission, "define_bench_objective", OBJECTIVE)["ok"]
    assert service.action(mission, "observe_bench", {})["ok"]
    assert not service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]
    assert service.action(mission, "request_human_help", {"summary": "Human inspection needed."})["ok"]
    assert mission.status == "needs_human"


@pytest.mark.parametrize("minimum", [1, 401, 20.0, True, "20", 19])
def test_objective_schema_bounds_and_user_minimum_are_enforced(minimum):
    service, _ = bench()
    mission = service.start(GOAL, 24, "bench-passport", background=False)
    assert not service.action(mission, "define_bench_objective", {**OBJECTIVE, "minimum_distance_cm": minimum})["ok"]
    assert mission.objective is None


@pytest.mark.parametrize("goal", ["Inspect clearance < 20 cm", "Inspect clearance <= 20 cm", "Inspect clearance exactly 20 cm",
                                  "Inspect clearance > 20 cm", "Inspect clearance = 20 cm", "Inspect clearance between 20 cm and 30 cm",
                                  "Inspect at least 20 cm clearance and exactly 30 cm distance", "Inspect clearance at least -20 cm",
                                  "Inspect 20 cm clearance"])
def test_nonminimum_or_ambiguous_distance_conditions_cannot_be_reinterpreted(goal):
    service, _ = bench()
    mission = service.start(goal, 24, "bench-passport", background=False)
    assert not service.action(mission, "define_bench_objective", OBJECTIVE)["ok"]


@pytest.mark.parametrize("goal", ["Inspect at least 20 cm clearance", "Inspect a minimum clearance of 20 cm", "Inspect >=20 cm clearance",
                                  "Inspect no less than 20 cm clearance", "Inspect 20 cm minimum clearance"])
def test_supported_explicit_lower_bound_phrasings(goal):
    assert agent.bench_goal_minimum(goal) == 20


@pytest.mark.parametrize("minimum", [2, 400])
def test_valid_sensor_and_objective_boundary_values_can_be_verified(minimum):
    service, _ = bench(FakeHardware(distance=minimum))
    mission = service.start(f"Inspect the zone for at least {minimum} cm clearance", 24, "bench-passport", background=False)
    assert service.action(mission, "define_bench_objective", {**OBJECTIVE, "minimum_distance_cm": minimum})["ok"]
    assert service.action(mission, "observe_bench", {})["ok"]
    assert service.action(mission, "finish_mission", {"summary": "Verified"})["ok"]


def test_handoff_contains_actual_bench_evidence_and_no_simulator_facts():
    contexts = []

    def handoff(mission_id, summary, context, **_):
        contexts.append(copy.deepcopy(context))
        return {"status": "pending_local", "summary": summary, "sent_to_ambiguous": False}

    service, hardware = bench(FakeHardware(distance=10), handoff_sink=handoff)
    mission = start_observed(service)
    assert service.action(mission, "request_human_help", {"summary": "Please inspect and clear the Arduino inspection zone."})["ok"]
    context = contexts[0]
    assert context["station_id"] == "bench" and context["provenance"] == "physical"
    assert context["bench_observation"]["telemetry"]["distance_cm"] == 10
    assert context["hardware"]["telemetry"]["dht_age_seconds"] is None
    assert "scene" not in context and "scene_observed_at" not in context
    assert "red_can" not in json.dumps(context)
    hardware.data["telemetry"]["distance_cm"] = 30
    assert context["bench_observation"]["telemetry"]["distance_cm"] == 10


def test_changed_passport_blocks_observation_and_physical_completion():
    valid = [True]
    service, hardware = bench(passport_check=lambda *_args, **_kwargs: (valid[0], "Passport changed"))
    mission = start_observed(service)
    before = hardware.observations
    valid[0] = False
    assert not service.action(mission, "observe_bench", {})["ok"]
    assert mission.status == "blocked"
    assert hardware.observations == before
    assert not service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]


def test_missing_hardware_is_observable_as_unavailable_without_simulator_fallback():
    service = agent.AgentService(station_lookup=lambda _: "bench")
    mission = service.start(GOAL, 24, "bench-passport", background=False)
    assert service.action(mission, "inspect_station", {})["provenance"] == "physical"
    result = service.action(mission, "observe_bench", {})
    assert not result["ok"] and result["connected"] is False
    assert mission.observation is None
    assert not service.action(mission, "finish_mission", {"summary": "Complete"})["ok"]
