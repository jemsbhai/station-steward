"""Explicit live model + USB integration check; optional real Ambiguous task delivery.

This directly selects the bench for an isolated backend check. It does not claim a
new camera scan and must run while the main app is stopped to keep one journal owner.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from station_steward.agent import AgentService
from station_steward.ambiguous import AmbiguousConnection
from station_steward.hardware import HardwareService


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-handoff", action="store_true", help="Use the enabled saved destination; may create a real task.")
    args = parser.parse_args()
    hardware = HardwareService()
    connection = AmbiguousConnection(ROOT / ".local") if args.live_handoff else None
    if connection and not connection.snapshot()["enabled"]:
        raise SystemExit("Enable the intended Ambiguous destination first.")
    try:
        hardware.connect()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if hardware.snapshot()["fresh"] and time.monotonic() > deadline - 3:
                break
            time.sleep(.1)
        if not hardware.snapshot()["fresh"]:
            raise SystemExit("No fresh physical telemetry; no live agent test started.")
        service = AgentService(hardware=hardware, station_lookup=lambda _: "bench",
                               handoff_sink=connection.deliver if connection else None,
                               handoff_enabled=lambda: bool(connection and connection.snapshot()["enabled"]))
        mission = service.start("Check the Arduino inspection zone. It must have at least 20 cm clearance. If blocked or unmeasurable, assign a human to inspect or clear it.",
                                24, "direct-bench-integration-check", background=False)
        service.execute(mission)
        # Make replay callbacks fatal; even USB observation/discovery is forbidden.
        hardware.observe = lambda: (_ for _ in ()).throw(AssertionError("Replay observed hardware"))
        hardware.capabilities = lambda: (_ for _ in ()).throw(AssertionError("Replay queried hardware"))
        replay = service.replay(mission.id)
        result = {"validation": "direct backend model + physical USB check; no camera scan performed",
                  "mission": service.snapshot()["mission"], "replay_avoided": replay["report"]["avoided"],
                  "hardware_commands": 0, "live_handoff_enabled": args.live_handoff}
        (ROOT / "artifacts" / "agent-live-bench.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"status": mission.status, "summary": mission.summary, "handoff": mission.handoff,
                          "budget": result["mission"]["budget"], "replay_avoided": result["replay_avoided"]}))
        if mission.status not in {"completed", "needs_human"}:
            raise SystemExit(1)
        if args.live_handoff and mission.status == "needs_human" and not mission.handoff.get("verified"):
            raise SystemExit(2)
    finally:
        hardware.disconnect()
