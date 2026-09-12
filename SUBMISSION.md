# Station Steward

**An agent that discovers the tools at a workstation, checks the real result, and assigns work to a human when the station cannot finish it.**

AI Tinkerers / OpenAI Agents Everywhere · Miami · September 12, 2026

[Public repository](https://github.com/jemsbhai/station-steward) · [Judge's guide](docs/JUDGING.md) · [Two-minute demo script](docs/DEMO.md) · [Build story](docs/WRITEUP.md) · [Run locally](README.md#run-locally)

## Project description

A shared workbench can have a sensor but no actuator, a missing robot arm, or an observation that is already out of date. An assistant needs to distinguish what the station can do from what a person must do next.

Station Steward brings an OpenAI tool agent to that workbench. An Android phone displays a station passport; a laptop camera scans the ordinary QR code and selects a registered environment. The agent discovers its available tools, interprets the user's goal, gathers fresh evidence, and either verifies completion or creates an assigned task in Ambiguous AI. The same application supports a real Arduino sensor bench and a simulated robotic workcell.

The physical demonstration gives the agent a concrete request: check at least 20 cm of clearance. In the recorded live run, the UNO reported 2.3 cm. The agent had a sensor but no permitted actuator, so it requested human help. The application created a real Ambiguous task, assigned it to the configured person, and read the record back to verify delivery. The result was unresolved physical work with a confirmed owner, not a false success message.

In the virtual workcell, the agent can do more: observe two cans, compare legal destinations, move them, and verify their final positions. If the arm disappears, the planned move fails and the model must respond to the changed capability. This demonstrates adaptation through two explicit tool contracts, rather than assuming every environment exposes a robot.

Pollard budgets and records model/tool calls; Chronofy checks the age of evidence; MCP-Edge connects the existing UNO telemetry to the agent. Replay inspects a historical run without making another model request, moving an object, or creating another task. The physical handoff used four model calls and four tool calls; replay reused all eight results.

## Who it is for, and why the environment matters

The intended user is a maker, lab teammate, or shared-workbench operator preparing a station for a task. Station selection tells the agent which tools are available, USB telemetry supplies current physical observations, and simulator revisions expose changes during execution. Without those inputs, the model cannot establish clearance, know whether a move is possible, or verify that its work changed the station.

The prototype's practical value is carrying the goal and evidence into the next action. When the station can act, it does so through checked tools. When it cannot, the human receives the blocker and context in a persistent work system. No user study or measured labor-saving claim is made.

## Why the Ambiguous integration is central

Human handoff is a model-selected tool with an external result. It includes the station, goal, blocker and available evidence. The app verifies the workspace and chosen assignee, records a delivery reservation before creating the task, and checks the resulting record. After an uncertain response it searches for that mission's existing task rather than blindly posting again.

This makes Ambiguous the continuation point for work the physical station cannot perform. The demonstrated workflow ends at verified assignment. A person can inspect task status, resolve the issue and start a new check; automatic resumption from a completed task is future work.

## Evidence available to reviewers

| Evidence | What it establishes |
|---|---|
| [Published live-run summary](docs/evidence/validation-summary.json) | Three real-model virtual scenarios and one real-model, real-USB, real-Ambiguous blocked-clearance scenario |
| [Validation report](docs/VALIDATION.md) | 117 offline tests, clean source installation, frontend build and TypeScript checks |
| [Agent implementation](station_steward/agent.py) | Station-specific tools, fixed objectives, checked completion, budgets and strict replay |
| [Ambiguous implementation](station_steward/ambiguous.py) | Assigned task delivery, read-back, persistent recovery and encrypted local credentials |
| [Hardware implementation](station_steward/hardware.py) | Read-only serial adapter, bounded parsing, connection sessions and measurement limitations |

The physical backend run and the successful phone/camera trial were separate validations. The virtual arm is simulated. The real motor remains disconnected from the UNO signal pin; physical actuation is not part of this build.

## What was created during the event

The new work is the Station Steward application: phone/camera station selection, simulator, model tool loop, station adapters, evidence policies, Ambiguous delivery and recovery, interface, tests and documentation. Pollard, Chronofy and MCP-Edge are pre-existing libraries pinned to public commits. The React/Vinext scaffold, supplied UI components and Arduino sketch are inherited inputs; the sketch was adapted to disable motor output. [Full attribution](README.md#built-here-built-on).

The current implementation supports a case for the general competition and Best Use of Ambiguous AI. [The judge's guide](docs/JUDGING.md) maps that case to the published criteria and distinguishes integrated tools from sponsors that are not used.
