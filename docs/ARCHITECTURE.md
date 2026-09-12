# Architecture

Station Steward is one Python service and a statically built React interface. The laptop serves the phone display, camera page and API from the same origin. Hardware remains attached to the laptop; only model requests and enabled Ambiguous operations require remote services.

## Station selection and agent loop

A passport contains a short `SS2:<session reference>` payload. The backend resolves it to a registered station. A camera upload must decode to the active passport, and its receipt must be fresh when a mission starts. The passport proves a matching session reference was decoded; it does not prove physical equipment identity, connectivity or permission to actuate it.

Each mission owns a Pollard run, a fixed goal, a station ID, a call budget, recorded events and an observation. The OpenAI Responses loop requests exactly one function call at a time. Application code validates the tool name and arguments, executes it through the station adapter, records the result, and sends that result back to the model. Tool errors remain visible evidence for the next decision. They are not converted into success.

The model receives tool results and concise instructions, not credentials. The activity log displays selected tools and short action summaries; it does not expose private chain-of-thought.

| Station | Tool surface |
|---|---|
| Virtual | `inspect_station`, `define_objective`, `observe_scene`, `compare_moves`, `move_object`, `finish_mission`, `request_human_help` |
| Physical | `inspect_station`, `define_bench_objective`, `observe_bench`, `finish_mission`, `request_human_help` |

The physical allowlist is enforced again when a tool executes. A fabricated tool call cannot use the simulator to satisfy a physical goal. Losing the virtual arm removes its move capability and also causes any already-planned move to fail the execution check.

## What completion means

The virtual simulator has four named slots and two cans. An objective fixes required placements and/or empty staging. A move needs an available arm, an empty destination, and a fresh observation of the exact current scene revision. Every move advances the revision. Completion requires observing again and satisfying the entire objective.

The physical station supports an explicit integer minimum-clearance objective from 2 through 400 cm. A conservative goal parser accepts a stated lower bound, such as “at least 20 cm,” and declines upper bounds, equalities, mixed unsupported actions and ambiguous conditions. This prevents the model from rewriting a harder or different goal as an easy minimum. Temperature conditions and motor actuation are unsupported.

Physical completion needs both the mission's recorded observation and the latest sample to be fresh, from the same USB session, valid, and above the fixed minimum. The backend generates the measured-clearance result itself. A persuasive model summary cannot bypass this check. Verification is a point-in-time result along the ultrasonic beam, not a continuous safety guarantee for an entire work area.

## Three independent evidence clocks

| Evidence | Rule | Invalidated by |
|---|---|---|
| QR receipt | Under 30 seconds old at mission start; passport expires after five minutes | Failed scan, newer passport, expiry |
| Virtual scene | Under 30 seconds old and matching revision | Movement, position swap, arm-state change, age |
| USB telemetry | Under three seconds old and current connection session | Disconnect, reset, receive error, missing valid frames, age |

Chronofy supplies the decay/filter checks. The USB reader also uses monotonic elapsed time so a wall-clock adjustment cannot make an old receipt young again. Its timestamp is reception time, not an authenticated MCU measurement timestamp.

DHT values are different: the supplied sketch prints a cached reading repeatedly. It has no successful-sample timestamp. A fresh serial line therefore does **not** make temperature/humidity fresh. Diagnostic messages and malformed lines never refresh measurement evidence. A DHT failure remains visible because the legacy protocol cannot prove recovery.

## Pollard accounting and replay

The mission budget defaults to 24 combined model/tool steps, with a separate hard ceiling of ten model calls. Provider token totals and elapsed time are recorded. Token totals are accounting rather than a hard spending limit; no money or physical-energy savings are asserted.

Model and tool callbacks return error envelopes so failures are also charged. One worker owns the Pollard run; interface polling reads snapshots. Stop prevents later actions, but it cannot retract a provider request already sent. Scene resets and replay wait for the mission worker to finish.

Replay creates a strict replay runtime over the original store and exact payload sequence. Every possible live callback is replaced with a function that raises if invoked. A replay neither reads the current Arduino nor writes an Ambiguous task. It does not refresh an observation or make the historical result current.

The local virtual optimization feature compares straight-line distances to legal candidate slots without moving. Those comparisons are recorded for inspection and replay. They are not a learned trajectory optimizer or a physical energy model.

## Read-only MCP-Edge adapter

The UNO keeps running its existing text-stream sketch at 115200 baud. `HardwareService` owns the serial connection and bounded reader. A `UnoTelemetryClient` implements MCP-Edge's `DeviceClient`, is registered as a constrained MCU, and exposes `uno/read_telemetry` through the real `Gateway`.

Only complete, bounded numeric/enumerated records become telemetry. The reader accepts no arbitrary instructions and never calls `Serial.write`. It has no firmware uploader, command queue, offline actuation buffer or motor control tool. Reset diagnostics start a new observation session. The updated disabled-fan diagnostic is session-scoped.

## Ambiguous delivery and recovery

The localhost setup flow verifies the credential's identity and workspace, lists available humans/projects, and stores the chosen destination. Before a handoff, it verifies identity again. Task descriptions contain the actual station's goal, blocker and evidence; physical handoffs do not include simulator positions as physical facts.

Delivery follows this sequence:

1. Look up the stable mission ID in the local delivery journal.
2. Reserve a delivery record durably before sending a task-creation request.
3. Create one assigned task with an exact mission reference in its description.
4. Save the returned ID and read the task back.
5. Verify task ID, reference, creator, assignee and project before displaying verified delivery.

The API does not document an idempotency key for task creation. An existing journal record therefore never triggers another POST, even after a timeout or restart. If a request's outcome is uncertain, status recovery searches for the exact reference and original creator; it does not manufacture a replacement task. Corrupt journal state fails closed for new writes. This favors a visibly unresolved handoff over silent duplicates, rather than claiming exactly-once delivery across every failure mode.

Task status checks are user-triggered reads. Marking an Ambiguous task done does not complete the station's objective. A person must resolve the issue and the station must obtain fresh evidence in a new mission. Incoming task processing and parent/subtask synchronization are not implemented.

## Storage and access boundary

- Raw camera frames are decoded locally and not stored or sent to the model.
- QR sessions, missions and simulator state are bounded process memory and reset on restart.
- The Ambiguous key is encrypted with Windows DPAPI for the current account.
- The delivery journal persists task metadata under ignored `.local/` storage.
- Model/provider credentials are excluded from tool payloads and API responses.
- Browser write requests require the local origin; privileged settings and controls also require a loopback client and literal localhost hostname.

These controls are for a trusted local demonstration, not multi-user internet authentication. A public source repository is not a public deployment of the running application.
