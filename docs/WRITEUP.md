# Hackathon writeup

## Idea

Station Steward explores a practical question: how should an agent behave when the physical environment cannot do what a user asks?

The early concept was a small robotic drinks station. The available hardware changed, so the prototype became an adaptive workstation agent using an existing laptop camera, Android screen, Arduino UNO, ultrasonic sensor, DHT11 and joystick, plus a virtual workcell. The important behavior survived that change: discover what is available, gather fresh evidence, choose feasible tools, verify the result, and assign remaining work to a human.

The project does not claim adaptation to arbitrary unknown hardware. It uses two registered adapters with explicit tool contracts. That bounded scope makes the demo inspectable: changing the station changes what the agent is allowed to do, and changing the evidence can invalidate its plan.

## What was built

The laptop runs a Python API and serves a mobile-friendly interface. The Android phone displays a QR station passport; the laptop camera decodes it and selects the station profile. A real OpenAI Responses function-calling loop operates over that station's tool surface.

The virtual workcell has two objects and discrete slots. The agent can clear staging, place cans in requested racks, compare legal move distances and verify placements. The physical bench exposes a read-only MCP-Edge tool for the UNO's telemetry. It can verify an explicit minimum ultrasonic clearance, but it cannot invent a manipulator or send a fan command through a sketch with no serial command parser.

Pollard supplies the mission budget, usage accounting, recording and replay. Chronofy supplies freshness policies. Ambiguous supplies persistent human work: the agent creates a task in the configured workspace, assigns it, includes evidence and reads it back.

## Why Ambiguous matters here

The handoff is an action in the agent's tool loop, with a real external result. A physical obstruction remains unresolved even if the model can explain it. Creating an assigned task makes that unfinished work visible to the person who can handle it.

The integration verifies the destination identity, stores credentials locally, checks the created record and preserves delivery state across restart. If a creation request times out, the application searches for its exact mission reference rather than automatically posting another task. Completing a task is a human report; station verification still requires new evidence.

This is the project's contribution toward **Best Use of Ambiguous AI**: a demonstrated transition from a real sensor reading to persistent assigned human work. It does not claim an award, guaranteed eligibility, a dedicated agent identity, or an incoming-task workflow that has not been implemented.

## Results

- The phone-to-laptop QR path worked on actual screens and a real camera.
- Three live virtual OpenAI checks cleared staging, sorted cans and adapted after an arm disappeared.
- A live physical check measured 2.3 cm against a 20 cm goal and created/read back an assigned Ambiguous task.
- That physical run used four model calls and four tools. Replay reused every result without live callbacks.
- 117 offline tests covered normal behavior and failures; TypeScript and the production frontend build passed.
- The D7 sketch with motor output disabled compiled for the UNO. It was not uploaded during the recorded validation.

These are separate pieces of evidence. A synthetic QR round trip is not a camera trial; a simulated movement is not physical actuation; a task receipt is not proof a person cleared the bench. [Validation](VALIDATION.md) records those distinctions.

## Decisions and lessons

**Ordinary QR worked better for the available screens.** MultiSpecQR was tried in the early concept, then removed after glare and reflection problems. A short black-and-white code and a dark-screen delayed capture made the device loop usable.

**Fresh transport is not fresh measurement.** The sketch repeatedly prints cached DHT values. A new serial line cannot establish when the temperature was last measured or whether the sensor recovered from a failure. The interface preserves that uncertainty instead of turning every upload into a new temperature fact.

**Firmware automation is not model agency.** The original fan hysteresis is a fixed rule. The model's decisions occur above the hardware adapter, and the writeup keeps those roles distinct. The actual motor turned out to be a bare two-wire device; it was disconnected from the UNO signal pin, and the updated sketch leaves output disabled pending a proper driver.

**A useful failure is part of the product.** Missing capabilities, unknown distance, expired observations, exhausted budgets and uncertain task delivery are visible outcomes. The backend does not permit a completion claim merely because the model sounds confident.

**Replay is valuable only if it cannot repeat side effects.** A judge or developer can inspect a historical run without sending another task or touching hardware. Recorded results remain historical; replay does not make them current.

## What predates the hackathon

Pollard, Chronofy and MCP-Edge are existing libraries, explicitly credited and pinned in the repository. React/Vinext, the Sites scaffold, UI components and QR libraries are also dependencies. The supplied Arduino sketch is adapted existing input. Hackathon work is the integration application, station-specific agent behavior, policies, simulator, hardware proxy, human handoff path, interface and tests.

## Next steps

The next meaningful improvements are an explicit timestamped/acknowledged firmware protocol, a properly rated motor driver before any physical command, an Ambiguous agent identity and shared project, and an incoming mission workflow that waits for human resolution and verifies again. CopilotKit and Exa are possible later integrations, not hidden dependencies of the current result.

The broader objective is a station agent whose capabilities and claims remain aligned with its environment. This prototype demonstrates that idea across two bounded environments and one real human-work system.
