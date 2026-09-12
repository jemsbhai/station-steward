import asyncio
import queue
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp_edge.client import DeviceError

from station_steward.hardware import (
    MAX_LINE_BYTES, TELEMETRY_TOOL, HardwareService, hardware_router, parse_telemetry,
)


FRAME = b"#Dist: 23.4 !cm# | Temp: 28.0 C | Hum: 64.0% | Fan: ON  | Joy: [X: 512, Y: 514, Btn: UP]\r\n"
STARTUP = b"#Dist: XX Out of range# | Temp: 0.0 C | Hum: 0.0% | Fan: OFF | Joy: [X: 0, Y: 20, Btn: DOWN]\n"
WARNING = b"Warning: Failed to read from DHT sensor!\n"
FAN_DISABLED = b"Fan control disabled: motor driver required.\n"


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def now(self):
        return datetime(2026, 9, 12, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)


class FakeSerial:
    def __init__(self):
        self.incoming = queue.Queue()
        self.closed = False
        self.reads = 0
        self.writes = []

    def feed(self, data):
        self.incoming.put(data)

    def read_until(self, *, expected, size):
        assert expected == b"\n" and size == MAX_LINE_BYTES
        self.reads += 1
        try:
            result = self.incoming.get(timeout=0.02)
        except queue.Empty:
            return b""
        if isinstance(result, Exception):
            raise result
        return result

    def write(self, data):
        self.writes.append(data)
        raise AssertionError("The legacy adapter must never write to the device")

    def cancel_read(self):
        self.incoming.put(b"")

    def close(self):
        self.closed = True


def await_condition(predicate):
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Reader did not reach the expected state")


@pytest.fixture
def hardware():
    clock = Clock()
    devices = []

    def factory(**kwargs):
        assert kwargs == {"port": "COM3", "baudrate": 115200, "timeout": 0.2}
        device = FakeSerial()
        devices.append(device)
        return device

    service = HardwareService(serial_factory=factory, clock=clock.now, monotonic=lambda: clock.seconds)
    assert not devices  # Construction, snapshots and discovery never open the port.
    yield service, devices, clock
    service.disconnect()
    assert all(not device.writes for device in devices)


def test_parser_preserves_limits_and_unknown_cached_dht():
    data = parse_telemetry(FRAME)
    assert data["distance_cm"] == 23.4 and data["distance_valid"]
    assert data["temperature_c"] == 28 and data["humidity_pct"] == 64
    assert data["dht_valid"] is None and data["dht_age_seconds"] is None
    assert data["fan_reported"] == "on" and data["fan_verified_spinning"] is None
    assert data["joystick"] == {"x": 512, "y": 514, "button": "up"}
    startup = parse_telemetry(STARTUP)
    assert startup["temperature_c"] is None and startup["humidity_pct"] is None
    assert startup["temperature_reported_c"] == 0
    assert startup["distance_cm"] is None and not startup["distance_valid"]
    for value in ("0.0", "1.9", "400.1", "-1"):
        data = parse_telemetry(FRAME.replace(b"23.4", value.encode()))
        assert data["distance_cm"] is None and not data["distance_valid"]


@pytest.mark.parametrize("line", [
    b"garbage", WARNING, FAN_DISABLED, FRAME[:-10], FRAME.replace(b"28.0", b"nan"),
    FRAME.replace(b"512", b"1024"), b"\xff" + FRAME, b"x" * 513,
    FRAME + b"INJECTED", FRAME.replace(b"UP", b"SIDEWAYS"),
])
def test_malformed_or_diagnostic_lines_are_not_telemetry(line):
    assert parse_telemetry(line) is None


def test_timeouts_invalid_lines_and_warning_do_not_refresh_evidence(hardware):
    service, devices, clock = hardware
    assert not service.observe()["ok"]
    assert service.connect()["connected"]
    device = devices[-1]
    device.feed(FRAME)
    await_condition(lambda: service.snapshot()["sequence"] == 1)
    initial = service.snapshot()
    clock.seconds = 2.9
    assert service.observe()["ok"]
    device.feed(b"partial boot garbage\n")
    device.feed(WARNING)
    await_condition(lambda: service.snapshot()["dht_warning"] is not None)
    assert service.snapshot()["received_at"] == initial["received_at"]
    assert service.snapshot()["sequence"] == 1
    clock.seconds = 3.0
    assert not service.observe()["ok"] and not service.snapshot()["fresh"]
    device.feed(FRAME)
    await_condition(lambda: service.snapshot()["sequence"] == 2)
    state = service.snapshot()
    assert state["fresh"]
    assert state["dht_warning"]  # Cached values cannot clear a sensor failure warning.
    assert state["telemetry"]["dht_valid"] is None


def test_reader_handles_fragments_and_discards_whole_oversized_line(hardware):
    service, devices, _ = hardware
    service.connect()
    device = devices[-1]
    device.feed(FRAME[:30])
    device.feed(FRAME[30:])
    await_condition(lambda: service.snapshot()["sequence"] == 1)
    device.feed(b"x" * 512)
    device.feed(FRAME)  # Looks valid, but it is still the suffix of the oversized line.
    device.feed(b"\xff\xfe boot garbage\n")
    device.feed(FRAME)
    await_condition(lambda: service.snapshot()["sequence"] == 2)
    assert service.snapshot()["telemetry"]["distance_cm"] == 23.4


def test_disabled_fan_diagnostic_persists_without_refresh_and_resets_per_session(hardware):
    service, devices, clock = hardware
    service.connect()
    device = devices[-1]
    device.feed(FRAME)
    await_condition(lambda: service.snapshot()["sequence"] == 1)
    original = service.snapshot()
    assert original["telemetry"]["fan_control"] == "autonomous_legacy_firmware"
    clock.seconds = 3.1
    device.feed(FAN_DISABLED)
    await_condition(lambda: service.snapshot()["fan_control"] == "disabled_driver_required")
    disabled = service.snapshot()
    assert disabled["sequence"] == original["sequence"]
    assert disabled["received_at"] == original["received_at"] and not disabled["fresh"]
    assert disabled["telemetry"]["fan_control"] == "disabled_driver_required"
    capabilities = service.capabilities()
    assert capabilities["fan"]["control"] == "disabled_driver_required"
    assert capabilities["fan"]["on_at_c"] is None
    assert not capabilities["fan"]["agent_control"]
    assert [tool["name"] for tool in capabilities["tools"]] == [TELEMETRY_TOOL]
    device.feed(WARNING)
    device.feed(STARTUP)
    await_condition(lambda: service.snapshot()["sequence"] == 2)
    assert service.observe()["telemetry"]["fan_control"] == "disabled_driver_required"
    assert service.snapshot()["dht_warning"]
    device.feed(b"System Initialized.\n")
    await_condition(lambda: service.snapshot()["session_id"] != original["session_id"])
    assert service.capabilities()["fan"]["control"] == "autonomous_legacy_firmware"
    assert service.snapshot()["telemetry"] is None
    device.feed(FAN_DISABLED)
    await_condition(lambda: service.snapshot()["fan_control"] == "disabled_driver_required")
    service.disconnect()
    service.connect()
    assert service.capabilities()["fan"]["control"] == "autonomous_legacy_firmware"


def test_reset_disconnect_reconnect_invalidate_previous_session(hardware):
    service, devices, _ = hardware
    service.connect()
    devices[-1].feed(FRAME)
    await_condition(lambda: service.snapshot()["sequence"] == 1)
    old = service.observe()
    devices[-1].feed(b"System Initialized.\n")
    await_condition(lambda: service.snapshot()["session_id"] != old["session_id"])
    reset = service.snapshot()
    assert reset["connected"] and not reset["fresh"] and reset["telemetry"] is None
    devices[-1].feed(STARTUP)
    await_condition(lambda: service.snapshot()["sequence"] == 1)
    assert service.observe()["ok"]  # Stream is live; DHT and distance remain unknown.
    assert service.snapshot()["telemetry"]["temperature_c"] is None
    disconnected = service.disconnect()
    assert not disconnected["connected"] and not disconnected["fresh"]
    assert disconnected["telemetry"] is None and devices[-1].closed
    service.connect()
    assert len(devices) == 2 and service.snapshot()["telemetry"] is None
    assert service.snapshot()["session_id"] != disconnected["session_id"]


def test_read_failure_closes_port_invalidates_evidence_and_can_reconnect(hardware):
    service, devices, _ = hardware
    service.connect()
    device = devices[-1]
    device.feed(FRAME)
    await_condition(lambda: service.snapshot()["fresh"])
    device.feed(OSError("device removed"))
    await_condition(lambda: not service.snapshot()["connected"])
    assert service.snapshot()["telemetry"] is None
    assert "reconnect" in service.snapshot()["error"]
    assert device.closed
    assert service.connect()["connected"]


def test_locked_port_is_actionable_without_exposing_exception():
    def locked(**kwargs):
        raise PermissionError("private driver traceback")

    service = HardwareService(serial_factory=locked)
    state = service.connect()
    assert not state["connected"] and not state["fresh"]
    assert "Close Arduino Serial Monitor" in state["error"]
    assert "private" not in state["error"]
    service.disconnect()


def test_gateway_discovery_routing_and_no_actuation_surface(hardware):
    service, devices, _ = hardware
    calls = []
    original = service.gateway.call_tool

    async def routed(name, arguments):
        calls.append((name, arguments))
        return await original(name, arguments)

    service.gateway.call_tool = routed
    capabilities = service.capabilities()
    assert [tool["name"] for tool in capabilities["tools"]] == [TELEMETRY_TOOL]
    assert capabilities["read_only"] and not capabilities["fan"]["agent_control"]
    assert not devices
    assert service.observe()["provenance"] == "physical"
    assert calls == [(TELEMETRY_TOOL, {})]
    with pytest.raises(DeviceError):
        asyncio.run(original("uno/set_fan", {}))
    with pytest.raises(DeviceError):
        asyncio.run(original(TELEMETRY_TOOL, {"fan": "on"}))


def test_router_connection_controls_require_laptop(hardware):
    service, devices, _ = hardware
    app = FastAPI()
    app.include_router(hardware_router(service))
    client = TestClient(app)
    assert client.get("/api/hardware/state").status_code == 200
    assert not devices
    assert client.post("/api/hardware/connect", json={}).json()["connected"]
    assert client.post("/api/hardware/disconnect", json={}).json()["connected"] is False
    remote = TestClient(app, client=("192.168.1.50", 1234))
    assert remote.post("/api/hardware/connect", json={}).status_code == 403
    assert remote.post("/api/hardware/disconnect", json={}).status_code == 403
    assert remote.get("/api/hardware/state").status_code == 200
