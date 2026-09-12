# Two-minute demonstration script

Lead with the physical obstruction becoming an assigned Ambiguous task. Use the virtual workcell as the short second example of the same agent adapting to different tools. This is a recording/presentation guide, not a claim that a video has been produced.

## Prepare before presenting

- Start the laptop app and confirm the model key is configured.
- Connect Android to the same reachable network and open the phone display.
- Connect UNO telemetry and place a flat target where the ultrasonic reading is stable.
- Keep the bare motor disconnected. Leave the updated sketch's driver flag false.
- Enable Ambiguous handoffs to a person who can open the destination workspace.
- Open that workspace in another tab. The demo creates real assigned tasks.
- Rehearse the actual workflow. Model and network latency vary; the timings below describe a two-minute edited presentation. Label any cuts or sped-up waits, and never substitute replay for a supposedly live action.

## 0:00–0:15 — Put the problem in the room

“This bench has a sensor, but no robot that can clear it. Station Steward discovers what the station can do, checks the goal against fresh evidence, and assigns the rest to a person.”

Show the UNO, a flat target and the phone. Establish that the arm shown later is simulated. The phone QR selects a registered environment; it does not prove that equipment works.

## 0:15–0:45 — Give the agent a physical goal

Select **Arduino bench** on the phone, scan its passport, and run **Check 20 cm clearance** promptly. Keep a flat target around 10 cm away so the actual displayed reading is stable and below the goal.

“The model chooses its tools. This station exposes a real USB observation, but no move or motor command. The backend checks fresh evidence against the original goal.”

Show the tool activity and measured distance. Quote the reading actually on screen; **2.3 cm was the recorded validation run, not a guaranteed reading in the next run**.

## 0:45–1:15 — Show the real Ambiguous result

Open the task from the mission's handoff link. Show the assignee, original goal, blocker and physical evidence. Return to the app's verified delivery status.

“The obstruction is still here. What changed is that the unfinished work now has an owner and a persistent record. We read the task back to verify delivery; uncertain requests can be recovered without automatically posting duplicates.”

Only say the task was delivered when the real result confirms it. A local pending handoff or uncertain request is a different outcome.

## 1:15–1:35 — Make the run inspectable

Show the current run's model/tool counts and **Replay mission**.

“Pollard bounds and records this mission. Replay reuses its recorded results without another model call or task. Chronofy keeps old evidence from being treated as current.”

The validated physical run used four model calls and four tools. A new run can use different counts. Replay is historical inspection, not fresh verification of the bench.

## 1:35–2:00 — Show adaptation and the result

Show a clearly labeled second interaction with **Virtual workcell → Clear staging**: capability discovery, destination comparison, movement and verified placement. A short arm-disconnect example can show the model responding when a planned action becomes unavailable. Use an actual recorded interaction if the full run does not fit; label its environment and any edit.

“With a virtual arm, this agent can move and verify. With a real sensor and no actuator, it hands off. The environment determines which actions are possible, and evidence determines which results can be claimed.”

End on the resulting station state or verified task, with the public repository visible. The strongest takeaway is the complete goal-to-outcome interaction.

## Optional extended checks after the pitch

- Move the physical target to around 30 cm, rescan and start a new clearance mission. Fresh valid measurements satisfying the goal can complete it. This passing branch has controlled-sample test coverage; the published live physical run established the blocked handoff.
- Marking the task done alone does not verify clearance. Human resolution needs a new station observation and mission; automatic resumption is not implemented.
- Try a separate four-step mission budget. Show the stop and remaining work without claiming the goal completed.
- In simulation, use a goal with more than one permitted destination and inspect `compare_moves`. Its distances are virtual candidate comparisons, not real robot energy measurements.

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
