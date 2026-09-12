# Station Steward: verified work—or an assigned next step

## Idea

Someone preparing a shared bench or workcell needs a result: clear staging, put supplies in the right place, or verify enough clearance for the next task. The available equipment may cover only part of that work. An arm can disconnect, an object can move after inspection, and a live sensor connection can still carry an old measurement.

An agent therefore has two responsibilities: use the capabilities that are actually present, and make unresolved work actionable. Explaining that an object is blocking the station does not remove it or give anyone responsibility for doing so. **Station Steward connects capability discovery, fresh observations, bounded execution and human assignment.**

The early concept was a small robotic drinks station. The available hardware changed, so the prototype became an adaptive workstation agent using an existing laptop camera, Android screen, Arduino UNO with sensor/joystick telemetry, and a virtual workcell. The resulting product question is concrete: can the same agent application respond appropriately when its tools and environment change?

The project does not claim adaptation to arbitrary unknown hardware. It uses two registered adapters with explicit tool contracts. That bounded scope makes the demo inspectable: changing the station changes what the agent is allowed to do, and changing the evidence can invalidate its plan.

## What was built

The laptop runs a Python API and serves a mobile-friendly interface. The Android phone displays a QR station passport; the laptop camera decodes it and selects the station profile. A real OpenAI Responses function-calling loop operates over that station's tool surface.

The virtual workcell has two objects and discrete slots. The agent can clear staging, place cans in requested racks, compare legal move distances and verify placements. The physical bench exposes a read-only MCP-Edge tool for the UNO's telemetry. It can verify an explicit minimum ultrasonic clearance, but it cannot invent a manipulator or send a fan command through a sketch with no serial command parser.

Pollard supplies the mission budget, usage accounting, recording and replay. Chronofy supplies freshness policies. Ambiguous supplies persistent human work: the agent creates a task in the configured workspace, assigns it, includes evidence and reads it back.

## What the agent chooses—and what the application enforces

The model selects tools across multiple turns and receives their actual results. It can choose a legal destination, encounter a changed scene, re-observe, reconsider a rejected action, or request human help. The application supplies the tools and checks whether each action may succeed.

| Model decisions | Application checks |
|---|---|
| Interpret a supported goal into an objective | The objective cannot be weakened later to manufacture success |
| Discover capabilities and select the next tool | Each station has its own allowlist; physical missions cannot invoke simulated movement |
| Re-observe after a change or expired observation | Chronofy freshness and simulator revision checks reject obsolete evidence |
| Compare destinations and choose a virtual move | Destination occupancy, arm availability and the observed revision are checked before movement |
| Attempt completion or request human help | Completion requires the actual objective to pass verification; a confident sentence is insufficient |
| Request an assigned Ambiguous task | The configured destination, delivery status and returned task record are checked |

## Why Ambiguous matters here

When a station can sense an obstruction but cannot remove it, the next useful action is to give that work to someone who can. The handoff is an action in the agent's tool loop with a real external result: a persistent task containing an assignee, the original goal and supporting station evidence. The operator can follow that record instead of copying a chat explanation into another system.

The integration verifies the connected identity and workspace, stores credentials locally with Windows encryption, checks the created record and preserves delivery reservations across restart. If a creation request times out, recovery searches for its exact mission reference rather than automatically posting another task.

A task receipt proves delivery, not that a person cleared the bench. The app can read the existing task's status, but it does not yet wait for human resolution and resume the mission. A person's completion report would still require a fresh station check.

This is the project's case for **Best Use of Ambiguous AI**: a demonstrated transition from a real sensor reading to assigned human work, with confirmation that the assignment exists. The live check used a human API identity; a dedicated agent identity has not been provisioned. Prize eligibility and awards are not claimed.

## Results

In the recorded physical check, the UNO reported **2.3 cm** against a **20 cm minimum-clearance goal**. The agent requested human clearance, created a task assigned to the configured person in Ambiguous, and successfully read it back. The station mission remained **needs human**.

That run used **four model calls, four tool calls and 5,371 reported tokens**. Pollard replay reused all eight recorded results without another model call, hardware observation or task creation. The physical check selected the bench directly in an isolated backend run; it did not claim a new camera scan. The phone-to-laptop QR loop was separately confirmed using the actual screens and camera.

- The phone-to-laptop QR path worked on actual screens and a real camera.
- Three live virtual OpenAI checks cleared staging, sorted cans and adapted after an arm disappeared.
- All four recorded checks passed replay verification without executing live callbacks.
- 117 offline tests covered normal behavior and failures; TypeScript and the production frontend build passed.
- The D7 sketch with motor output disabled compiled for the UNO. It was not uploaded during the recorded validation.

These are separate pieces of evidence. A synthetic QR round trip is not a camera trial; a simulated movement is not physical actuation; a task receipt is not proof a person cleared the bench. A live passing physical-clearance mission is not claimed. [Validation](VALIDATION.md) and the [public evidence summary](evidence/validation-summary.json) record those distinctions.

## Budgets, comparison and replay

Pollard gives each mission a shared model/tool step budget, with a default of **24 combined calls** and a separate hard ceiling of **10 model calls**. The interface exposes expenditure and reported token usage. Exhausting the allowance is a visible stopped outcome; the agent cannot keep taking unbounded actions until it finds a convenient answer. Token usage is accounted for, but hard token and dollar ceilings are not implemented.

The virtual `compare_moves` tool evaluates legal candidate destinations by simulated travel distance without moving an object. It lets the model choose a shorter move when the goal permits that choice. These are simulator units, not measured electricity use or physical robot efficiency. Generalized prompt/model optimization and percentage cost savings have not been demonstrated.

Replay serves a separate purpose: inspect what happened without doing it again. Pollard reuses recorded outcomes while live callbacks are disabled. Replaying an assigned-task result cannot create another task, and replaying a sensor result cannot make that observation current. The eight avoided calls in the physical replay describe that historical run, not a general savings benchmark.

## Decisions and lessons

**Ordinary QR worked better for the available screens.** MultiSpecQR was tried in the early concept, then removed after glare and reflection problems. A short black-and-white code and a dark-screen delayed capture made the device loop usable.

**Fresh transport is not fresh measurement.** The sketch repeatedly prints cached DHT values. A new serial line cannot establish when the temperature was last measured or whether the sensor recovered from a failure. The interface preserves unknown sample age and displays failure warnings. Physical clearance verification instead requires valid observed and current distance samples, both less than three seconds old and from the same USB session.

**Firmware automation is not model agency.** The original fan hysteresis is a fixed rule. The model's decisions occur above the hardware adapter, and the writeup keeps those roles distinct. The actual motor turned out to be a bare two-wire device; it was disconnected from the UNO signal pin, and the updated sketch leaves output disabled pending a proper driver.

**A useful failure is part of the product.** Missing capabilities, unknown distance, expired observations, exhausted budgets and uncertain task delivery are visible outcomes. The backend does not permit a completion claim merely because the model sounds confident.

**Replay is valuable only if it cannot repeat side effects.** A judge or developer can inspect a historical run without sending another task or touching hardware. Recorded results remain historical; replay does not make them current.

## What predates the hackathon

Pollard, Chronofy and MCP-Edge are existing libraries, explicitly credited and pinned in the repository. React/Vinext, the Sites scaffold, UI components and QR libraries are also dependencies. The supplied Arduino sketch is adapted existing input. Hackathon work is the integration application, station-specific agent behavior, policies, simulator, hardware proxy, human handoff path, interface and tests.

## Next steps

The next meaningful improvements are an explicit timestamped/acknowledged firmware protocol, a properly rated motor driver before any physical command, an Ambiguous agent identity and shared project, and an incoming mission workflow that waits for human resolution and verifies again. CopilotKit, Exa and OpenRouter are possible later integrations; none is part of the demonstrated result.

The broader objective is a station agent whose capabilities and claims remain aligned with its environment. This prototype demonstrates that idea across two bounded environments and one real human-work system.
