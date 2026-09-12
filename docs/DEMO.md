# Two-minute demonstration

## Prepare before presenting

- Start the laptop app and confirm the model key is configured.
- Connect Android to the same reachable network and open the phone display.
- Connect UNO telemetry and place a flat target where the ultrasonic reading is stable.
- Keep the bare motor disconnected. Leave the updated sketch's driver flag false.
- Enable Ambiguous handoffs to a person who can open the destination workspace.
- Open that workspace in another tab. The demo creates real assigned tasks.

## 0:00–0:20 — State the problem

“An agent should know what this station can actually do. If equipment is missing or evidence is stale, it should adapt and make unfinished work visible to a person.”

Show the real bench and the separate virtual workcell. Explain that the phone QR selects a registered environment; it is not proof that a motor or sensor works.

## 0:20–0:50 — Let the agent act in simulation

Show and scan a **Virtual workcell** passport. Run **Clear staging**. Point to capability discovery, observation, legal destination comparison, movement and final verification in the activity log. These are model-selected tool calls over the actual simulator state.

For an alternate run, disconnect the virtual arm after starting. The planned move must fail, and the model should adapt or request help. Do not claim a physical robot moved.

## 0:50–1:25 — Give the same agent physical evidence

Show and scan an **Arduino bench** passport. Place the target around 10 cm away and run **Check 20 cm clearance**. The tool list changes to physical inspection; it contains no simulator movement or motor command.

The model reads actual UNO telemetry. A blocked or unmeasurable condition should lead to a human handoff. Open the resulting Ambiguous task and show the assignment, blocker, evidence and read-back status.

## 1:25–1:45 — Resolve and verify

Move the target to around 30 cm, keeping a reflecting surface in the beam. Obtain a fresh scan and run a new mission. A valid fresh reading meeting the goal can complete it. Marking the task done alone does not prove clearance.

This is a proposed live demonstration sequence. The recorded hackathon evidence verifies the blocked physical handoff; it does not claim this passing physical step was performed in that recorded check.

## 1:45–2:00 — Show budget and replay

Show model/tool counts and the mission budget. Replay the recorded mission: no new model calls, hardware observations, moves or Ambiguous tasks. If time permits, start a separate four-step run to demonstrate the budget stopping unfinished work.

## Useful fallback paths

| Symptom | Response |
|---|---|
| Phone cannot connect | Reopen the displayed phone URL; use the same reachable network/hotspot |
| QR glare | Dark-screen delayed scan, slight phone tilt, lower brightness if washed out |
| Scan aged | Rescan and start within 30 seconds |
| COM port busy | Close Serial Monitor/Plotter; reconnect from the app |
| Distance unknown | Position a flat target in range; unknown is not clear |
| DHT warning | Show the warning and cached-value limitation; clearance uses ultrasonic data |
| Slow model calls | Respect the freshness refusal; re-observation consumes budget |
| Ambiguous request uncertain | Use Check task status; do not blindly repeat a new mission to resend |

If hardware is unavailable, present the working virtual flow and clearly disclose that limitation. If a provider is unavailable, show a labeled recorded result; do not present replay as live execution.
