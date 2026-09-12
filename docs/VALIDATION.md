# Validation and evidence

This document separates observed results from suggested demonstrations. It intentionally omits private workspace IDs, task links, account details and local machine paths.

## Recorded live checks — September 12, 2026

| Scenario | Real services/devices | Result | Model calls | Tool calls | Reported tokens |
|---|---|---|---:|---:|---:|
| Clear virtual staging | OpenAI + discrete simulator | Completed | 7 | 7 | 10,947 |
| Sort virtual cans | OpenAI + discrete simulator | Completed | 8 | 8 | 13,992 |
| Arm disconnected after planning | OpenAI + discrete simulator | Needs human; no move; local handoff | 7 | 7 | 10,389 |
| Physical minimum clearance | OpenAI + real UNO USB + Ambiguous | 2.3 cm below 20 cm; assigned task created and read back | 4 | 4 | 5,371 |

The physical check directly selected the bench in an isolated backend run. It did not claim a new camera scan. The real phone display/laptop camera QR loop was separately confirmed during device trials. The passing physical-clearance branch is tested with controlled hardware samples; a live passing physical mission is not claimed here.

All four recorded checks verified replay without executing live callbacks. The physical check's replay avoided all eight recorded calls and did not create a duplicate task. These counts describe calls avoided for the same historical replay, not a general cost-saving benchmark.

[Machine-readable public summary](evidence/validation-summary.json)

## Offline verification

The full Windows suite passed **117 tests**. Coverage includes:

- Actual QR encoder/decoder round trips, rotation/blur, multiple-code ambiguity, invalid images, expiry and superseded sessions.
- Combined step and model-call ceilings, charged failure envelopes and cancellation.
- Exact simulator revisions, occupancy, fixed objectives and post-action verification.
- Serial framing, malformed input, reset/disconnect sessions, stale receipts, startup values, DHT uncertainty and disabled-fan diagnostics.
- Station-specific tool allowlists and rejection of unsupported or reinterpreted physical goals.
- Physical observed/current samples meeting the same explicit minimum.
- Windows-encrypted credential storage, identity verification, task read-back, duplicate prevention, timeout recovery and localhost restrictions.
- Replay with callbacks that fail if a live operation is attempted.

Ordinary tests use mocked model/provider responses and controlled serial transports. They do not call paid model APIs, create real tasks or open COM3. Synthetic image tests do not establish physical camera performance.

TypeScript checking and the static frontend build passed. The motor-disabled D7 sketch compiled for `arduino:avr:uno` using 6,250 bytes of program storage and 504 bytes of dynamic memory; compilation is not an upload or physical actuation test.

## Clean publication check

The initial public commit, `52cfe5b6499fa35129e3f1ca4923674a2829ef2c`, was exported with Git into a separate directory. That copy contained no ignored credentials, generated frontend output, sibling library checkouts or private run records.

| Check | Result |
|---|---|
| New Python environment; install `requirements-dev.txt` | Passed, including all three pinned public Git dependencies |
| `npm ci --include=optional` | Passed from the committed lockfile |
| Offline Python suite | 117 passed |
| Production frontend build on Node 24 | Passed on rerun |
| TypeScript after the build | Passed; generated route declarations resolved automatically |

The first frontend build completed its output stages but exited with a Windows/libuv shutdown assertion. Repeating the same build command succeeded with exit code 0; no source patch or runtime change was required. This records both attempts rather than presenting the first as a clean exit. No live provider or hardware calls were part of this fresh-install check.

## Reproducing checks

From the repository root after installing dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd mobile
npm run build
npx tsc --noEmit
```

The full suite's DPAPI checks require Windows. Native ZBar and cross-platform credential storage are additional work for other operating systems.

Run the build before the TypeScript check on a fresh checkout: Vinext generates the route declarations used by the type checker.

Explicit live checks:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_agent.py --scenario clear
.\.venv\Scripts\python.exe scripts/smoke_agent.py --scenario sort
.\.venv\Scripts\python.exe scripts/smoke_agent.py --scenario arm_disconnect
# Stop the main app first; this opens the physical port read-only.
.\.venv\Scripts\python.exe scripts/smoke_bench.py
# This additionally uses the enabled workspace and may create a real task.
.\.venv\Scripts\python.exe scripts/smoke_bench.py --live-handoff
```

Live scripts require a configured OpenAI key and consume API credit. The bench script uses the current hardware condition, so its outcome may be completion or a handoff. It defaults to COM3. The optional handoff flag requires the encrypted local destination to be enabled. Do not run it concurrently with the main app: the serial port and delivery journal should have one process owner.

Raw receipts are written under ignored `artifacts/`; bench receipts may contain private workspace/task metadata. The public summary uses only selected result fields. Do not publish raw receipts as if they were redacted.

## Not established

Physical arm motion, agent-controlled motor actuation, RPM/airflow feedback, DHT measurement freshness, arbitrary environment support, public internet deployment, incoming Ambiguous missions, generalized cost optimization, and sponsor prize eligibility are not verified capabilities of this prototype.
