# Arduino bench

Station Steward reads a real Arduino UNO over USB while the arm demonstration runs in a separate, explicitly simulated workcell. The laptop exposes the UNO through the MCP-Edge tool `uno/read_telemetry`. It does not send serial commands, upload firmware, or control the motor.

## Current hardware and firmware

The bench uses an UNO, DHT11 temperature/humidity sensor, and ultrasonic distance sensor. The supplied sketch also reads analog joystick inputs. The available fan is a bare two-wire DC motor; a suitable motor driver has not been established. **Keep the motor disconnected and leave `FAN_DRIVER_CONNECTED = false`.** An external battery does not make a direct motor connection to an I/O pin appropriate. See Arduino's [UNO R3 specifications](https://docs.arduino.cc/hardware/uno-rev3/) and [motor control guide](https://docs.arduino.cc/learn/electronics/transistor-motor-control/).

Use [`hardware/station_bench/station_bench.ino`](../hardware/station_bench/station_bench.ino). With its default configuration, D7 remains an input and receives no `digitalWrite` calls; sensing and serial output continue. A suitable driver and power arrangement must be selected for the actual motor ratings before enabling the fan branch. This guide does not specify a replacement circuit without those details.

The updated sketch compiled for Arduino UNO using 6,250 bytes of program storage and 504 bytes of dynamic memory. At the time of this write-up, it had **not been uploaded or verified on the board**. Compilation does not establish which firmware is running.

[`hardware/legacy_bench/legacy_bench.ino`](../hardware/legacy_bench/legacy_bench.ino) preserves the earlier supplied sketch for reference. It uses D3 and enables autonomous fan output; it is not the default setup for the present hardware.

## Pin map

| Component signal | UNO pin | Behavior |
|---|---|---|
| DHT11 data | D2 | DHT library input |
| Ultrasonic trigger | D9 | Trigger pulse |
| Ultrasonic echo | D10 | Echo duration, bounded timeout |
| Joystick X | A0 | Analog reading |
| Joystick Y | A1 | Analog reading |
| Joystick button | D4 | Internal pull-up; LOW means pressed |
| Future fan driver control | D7 | Disabled by default; leave the motor disconnected |
| USB serial | USB connector | 115200 baud |

Confirm the sensor module's own power and ground markings before wiring it. A module with onboard components can differ from a bare sensor. The pin map describes signal connections, not a motor power circuit.

## Upload and connect

1. Keep the bare motor disconnected. Confirm the updated sketch still has `FAN_DRIVER_CONNECTED = false`.
2. In Station Steward, disconnect the Arduino connection. Close Arduino Serial Monitor and any other program holding the serial port.
3. Open the updated sketch in Arduino IDE, select the UNO board and its actual port, install the required `DHT.h` library if needed, and verify before uploading.
4. After a successful upload, optionally inspect the output at **115200 baud**. Expect `System Initialized.` followed by `Fan control disabled: motor driver required.`. Close Serial Monitor afterward.
5. Start the local app using the [README](../README.md), then connect the Arduino from the laptop interface. The service defaults to `COM3`; use `./start-local.ps1 -SerialPort COM5` for another port, or set `STATION_SERIAL_PORT` when launching Uvicorn directly.
6. Confirm live distance/joystick readings. Do not infer that the update is installed from a successful connection alone: the adapter reports disabled fan mode only after receiving its diagnostic in the current session.

Disconnect Station Steward again before subsequent uploads. Reset, disconnect, reconnect, and read failures invalidate the old observation session.

## What the readings establish

An example telemetry line is:

```text
#Dist: 23.4 !cm# | Temp: 28.0 C | Hum: 64.0% | Fan: ON  | Joy: [X: 512, Y: 514, Btn: UP]
```

This illustrates the protocol, not a verified current measurement or enabled fan state.

- **Distance:** the adapter accepts finite readings from 2 through 400 cm. A timeout, out-of-range reading, or invalid value becomes unknown. The sensor reports range along its beam; it does not identify an object or certify that an entire workspace is clear.
- **Temperature/humidity:** the sketch attempts DHT reads on a 1,500 ms schedule but repeatedly prints cached values. It provides no successful-sample timestamp. Both startup values at zero are displayed as unknown, and nonzero values still have unknown sample age and validity. `Warning: Failed to read from DHT sensor!` remains visible; repeated cached values cannot clear it or prove sensor recovery.
- **Fan:** `ON`/`OFF` is a firmware-reported state, not measured rotation, airflow, or RPM. Disabled firmware reports `fan_control: disabled_driver_required`. Older firmware is classified as autonomous until the disabled diagnostic is observed. Its enabled branch turns on at or above 28°C and off below 27°C; the laptop has no fan-control tool.
- **Joystick:** raw X/Y readings and button state are available as telemetry. They do not by themselves establish a user approval or robot command.

Chronofy evaluates **telemetry receipt freshness**, separately from the unknown DHT sample age. A complete valid frame must have arrived less than three seconds ago in the current connected session. Malformed lines, startup messages, and warnings do not refresh that evidence. The serial reader uses bounded lines and rejects oversized input.

## Small physical demonstration

Use a minimum-clearance task such as **“Verify at least 20 cm of clearance.”** Place a flat target about 10 cm in front of the sensor: a valid reading below the threshold should block verification. Move it to about 30 cm and obtain a fresh observation before verifying again. Removing the target entirely may produce an out-of-range reading; unknown is not a successful clearance check.

Keep the virtual arm's simulated status visible. The physical bench demonstration establishes sensing, evidence freshness, and task adaptation; it does not demonstrate physical arm motion or agent-controlled fan actuation.

Parser, session, freshness, diagnostic, gateway, and read-only behavior are covered by [`tests/test_hardware.py`](../tests/test_hardware.py). Those software tests do not replace checking the actual wiring and readings.
