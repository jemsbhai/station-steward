# Judge's guide

**Start with one result:** a real bench reported 2.3 cm against a 20 cm goal. The agent could not clear the obstruction, so it created and verified an assigned Ambiguous task. Then replay reproduced the recorded outcome without issuing another task.

Read [the project description](../SUBMISSION.md), run [the demonstration](DEMO.md), or inspect [the evidence](VALIDATION.md). The public evidence contains selected results; private workspace/task identifiers and credentials are excluded.

## How to evaluate the agent

The model chooses the next available tool and responds to its result. Application code enforces the fixed objective, capability, freshness and budget constraints. The virtual objective is the model's displayed interpretation of the request; its semantic correctness still deserves user review. The physical clearance objective additionally requires an explicitly parsed minimum from the user's goal. A run can end in verified completion, a human handoff, a budget stop, cancellation or error. Successful delivery of a handoff does not mean the physical objective has been achieved.

| Published criterion | What this project demonstrates | Inspect |
|---|---|---|
| Core Requirements & Functionality | Real QR station selection; completed virtual placement workflows; real USB observation leading to created and verified human work | [Live results](VALIDATION.md#recorded-live-checks--september-12-2026), [public receipts summary](evidence/validation-summary.json) |
| Innovation & Theme Alignment | The surrounding station determines the tool surface. Losing the arm changes execution; fresh physical readings determine whether a clearance claim is valid | [Agent](../station_steward/agent.py), [station contracts](ARCHITECTURE.md#station-selection-and-agent-loop) |
| Technical Execution & Integration | One tool loop connects model, simulation, MCP-Edge telemetry, Chronofy evidence and Ambiguous delivery. Limits, stale state, disconnects and uncertain writes have explicit behavior | [Architecture](ARCHITECTURE.md), [agent tests](../tests/test_agent.py), [hardware/agent tests](../tests/test_agent_hardware.py), [delivery tests](../tests/test_ambiguous.py) |
| Usefulness & Agentic Experience | A workbench operator gets a verified result or an assigned next action with context. Visible tool activity, stop controls and replay make the run inspectable | [Demo](DEMO.md), [handoff context tests](../tests/test_ambiguous_hardware.py), [interface](../mobile/app/page.tsx) |

The official rubric scores each criterion from 1 to 5. Its example surfaces are not separate tracks, and adding sponsor names is not a scoring criterion. This guide maps evidence to those criteria; it does not assign the project a score. [Official overview](https://github.com/CopilotKit/agents-everywhere-starter-kit/blob/main/hackathon-overview.md).

## Best Use of Ambiguous AI: the case

The central interaction is **physical evidence → capability gap → assigned human work → verified delivery**.

| Integration detail | Why it matters |
|---|---|
| The model invokes `request_human_help` | The handoff follows the agent's attempt to satisfy the current goal |
| Goal, station, blocker and evidence travel together | The assignee has context for the next action |
| A selected human and optional project determine the destination | Work goes to a configured person rather than a generic notification stream |
| Created task is read back and checked | The UI distinguishes verified delivery from a request that may have failed |
| A durable mission reference supports recovery | A timeout or restart does not automatically cause another task-creation request |
| Replay cannot invoke the delivery callback | Inspecting the demonstration cannot resend the work |

These behaviors exist in [the integration](../station_steward/ambiguous.py) and are covered by [delivery tests](../tests/test_ambiguous.py). The blocked-clearance path was also exercised against the actual service. Live setup used a human API identity in one configured workspace. Dedicated agent identity, incoming task execution and automatic continuation after human resolution are future work.

## Pollard, Chronofy and optimization

Pollard puts model and tool steps in the same recorded mission budget, with a separate model-call ceiling. Failed calls are accounted for, and replay reuses recorded results under callbacks that fail if live execution is attempted. Token usage is reported; there is no hard dollar or token cap.

Chronofy checks independent QR, simulator and USB observation clocks. A current QR scan cannot make an old sensor value current. Simulator revisions also invalidate observations after a change.

The optimization demonstration is a concrete `compare_moves` tool: it compares straight-line distances to legal virtual destinations without moving, so the agent can choose a shorter permitted move. Pollard records those comparisons for review. This is a local candidate comparison, not a benchmark of global robot planning or energy savings.

## Published awards and current integration scope

The Miami portal was checked on September 12, 2026. It lists global first, second and third place, plus Best Use of Ambiguous AI and Best Use of CopilotKit. OpenRouter appears as a sponsor without a separate published prize in that list. Award stacking and additional qualification terms were not established by the inspected portal. [Official prize list](https://miami.aitinkerers.org/hackathons/h_Q1ZYJsSw3Cc).

| Award or sponsor | Current project position |
|---|---|
| Global competition | The physical and simulated workflows provide evidence across the four general criteria |
| Best Use of Ambiguous AI | Actual assigned tasks, verified read-back, durable recovery and a real physical handoff |
| Best Use of CopilotKit | CopilotKit is not integrated; a React interface alone does not establish its use |
| OpenAI | Actual Responses API function-calling agent, used in all four recorded live scenarios |
| OpenRouter / Exa | Not integrated; no use or separate prize is claimed |

## Provenance and review limits

The app and its integration behavior were created for this event. Existing libraries, scaffold, UI components and supplied firmware are identified in [the attribution](../README.md#built-here-built-on). This follows the handbook's distinction between a new event project and reusable components. [Miami handbook](https://miami.aitinkerers.org/hackathons/h_Q1ZYJsSw3Cc/handbook).

The project demonstrates two registered environments, not arbitrary hardware discovery. The arm is virtual, physical control is disabled, and clearance is a point-in-time ultrasonic reading along one beam. The implementation and evidence make these boundaries explicit so reviewers can reproduce the actual result.
