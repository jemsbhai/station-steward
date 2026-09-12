"""Explicit live API check; no camera, physical hardware or active app state touched."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from station_steward.agent import AgentService, openai_response


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["clear", "sort", "arm_disconnect"], default="clear")
    args = parser.parse_args()
    service = AgentService()
    changed = False

    def live(body):
        global changed
        response = openai_response(body)
        # For this scenario, remove the capability after the model plans a move.
        if args.scenario == "arm_disconnect" and not changed and any(item.get("name") == "move_object" for item in response.get("output", [])):
            service.arm_available = False
            service.revision += 1
            changed = True
        return response

    service.responder = live
    goal = "Put the blue can in rack 1 and the red can in rack 2. Leave staging empty." if args.scenario == "sort" else "Prepare the virtual station for handoff. Clear staging using the shortest legal move."
    mission = service.start(goal, 24, "isolated-api-check", background=False)
    service.execute(mission)
    state = service.snapshot()
    before = json.dumps(state["scene"], sort_keys=True)
    replay = service.replay(mission.id)
    assert before == json.dumps(service.snapshot()["scene"], sort_keys=True)
    result = {"scenario": args.scenario, "status": mission.status, "summary": mission.summary,
              "objective": mission.objective, "budget": state["mission"]["budget"], "objects": state["scene"]["objects"],
              "actions": [event for event in mission.events if event["kind"] != "model"],
              "replay_avoided": replay["report"]["avoided"], "scene_unchanged_by_replay": True}
    output = Path(__file__).resolve().parents[1] / "artifacts" / f"agent-live-{args.scenario}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    expected = "needs_human" if args.scenario == "arm_disconnect" else "completed"
    sys.exit(0 if mission.status == expected else 1)
