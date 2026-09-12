"""Read-only USB telemetry from the user's existing Arduino UNO sketch.

The sketch reports autonomous or disabled fan control. This adapter never writes serial bytes,
uploads firmware, or infers DHT sample freshness from repeated printed values.
"""

from __future__ import annotations

import asyncio
import copy
import math
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import serial
from chronofy import EpistemicFilter, ExponentialDecay, TemporalFact
from fastapi import APIRouter, Request
from mcp_edge.client import DeviceClient, DeviceError
from mcp_edge.gateway import Gateway
from mcp_edge.registry import DeviceRegistry
from mcp_edge.tiers import Tier

from station_steward.local_access import require_laptop

MAX_LINE_BYTES = 512
STALE_SECONDS = 3.0
TELEMETRY_TOOL = "uno/read_telemetry"
_NUMBER = r"-?\d+(?:\.\d+)?"
_TELEMETRY = re.compile(
    rf"^#Dist:\s*(?:(?P<distance>{_NUMBER})\s*!cm|(?P<unknown>XX\s+Out of range))#"
    rf"\s*\|\s*Temp:\s*(?P<temperature>{_NUMBER})\s*C"
    rf"\s*\|\s*Hum:\s*(?P<humidity>{_NUMBER})%"
    r"\s*\|\s*Fan:\s*(?P<fan>ON|OFF)"
    r"\s*\|\s*Joy:\s*\[X:\s*(?P<x>\d+),\s*Y:\s*(?P<y>\d+),"
    r"\s*Btn:\s*(?P<button>UP|DOWN)\]$"
)
_DHT_WARNING = "Warning: Failed to read from DHT sensor!"
_FAN_DISABLED = "Fan control disabled: motor driver required."
_DHT_NOTE = (
    "The legacy sketch prints cached DHT readings without a sample timestamp or "
    "success flag. Their sample age and validity are unknown."
)


def parse_telemetry(line: str | bytes) -> dict[str, Any] | None:
    """Parse only complete legacy telemetry lines; diagnostics are not evidence."""
    if isinstance(line, bytes):
        if len(line) > MAX_LINE_BYTES:
            return None
        try:
            line = line.decode("ascii")
        except UnicodeDecodeError:
            return None
    if len(line) > MAX_LINE_BYTES:
        return None
    match = _TELEMETRY.fullmatch(line.strip())
    if not match:
        return None
    values = match.groupdict()
    temperature, humidity = float(values["temperature"]), float(values["humidity"])
    x, y = int(values["x"]), int(values["y"])
    if not all(math.isfinite(v) for v in (temperature, humidity)) or not (0 <= x <= 1023 and 0 <= y <= 1023):
        return None
    distance = float(values["distance"]) if values["distance"] is not None else None
    distance_valid = distance is not None and math.isfinite(distance) and 2 <= distance <= 400
    startup = temperature == 0 and humidity == 0
    plausible = 0 <= temperature <= 50 and 0 <= humidity <= 100
    return {
        "distance_cm": distance if distance_valid else None,
        "distance_valid": distance_valid,
        "temperature_c": temperature if plausible and not startup else None,
        "humidity_pct": humidity if plausible and not startup else None,
        "temperature_reported_c": temperature,
        "humidity_reported_pct": humidity,
        "dht_valid": None,
        "dht_age_seconds": None,
        "dht_sampled_at": None,
        "dht_status": "uninitialized_or_unknown" if startup else "cached_validity_unknown",
        "dht_note": _DHT_NOTE,
        "fan_reported": values["fan"].lower(),
        "fan_verified_spinning": None,
        "fan_control": "autonomous_legacy_firmware",
        "joystick": {"x": x, "y": y, "button": values["button"].lower()},
    }


class UnoTelemetryClient(DeviceClient):
    """MCP-Edge Tier 1 proxy; its only tool reads the local receive buffer."""

    def __init__(self, service: HardwareService):
        self.service = service

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{
            "name": "read_telemetry",
            "description": "Read physical UNO telemetry already received over USB. No device writes; fan mode is reported by existing firmware. DHT sample freshness is unknown.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        }]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name != "read_telemetry" or arguments:
            raise DeviceError("Only read_telemetry with no arguments is available.")
        state = self.service.snapshot()
        return {"ok": bool(state["connected"] and state["fresh"] and state["telemetry"]),
                "provenance": "physical", **state}

    async def read_resource(self, uri: str) -> Any:
        raise DeviceError("This read-only UNO proxy exposes no resources.")


class HardwareService:
    def __init__(
        self, port: str = "COM3", baudrate: int = 115200, *,
        serial_factory: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        self.port, self.baudrate = port, baudrate
        self._serial_factory = serial_factory or serial.Serial
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._connection = None
        self._thread: threading.Thread | None = None
        self._stop: threading.Event | None = None
        self._generation = 0
        self._connected = False
        self._error: str | None = None
        self._session_id = uuid.uuid4().hex
        self._sequence = 0
        self._telemetry: dict[str, Any] | None = None
        self._received_at: datetime | None = None
        self._received_monotonic: float | None = None
        self._fact: TemporalFact | None = None
        self._dht_warning: str | None = None
        self._fan_driver_required = False
        self._freshness = EpistemicFilter(
            ExponentialDecay(beta={"uno_telemetry_receipt": math.log(2) / STALE_SECONDS}, time_unit="seconds"),
            threshold=0.5,
        )
        self.registry = DeviceRegistry()
        self.registry.register("uno", UnoTelemetryClient(self), Tier.CONSTRAINED_MCU)
        self.gateway = Gateway(self.registry)

    def _new_session_locked(self):
        self._session_id = uuid.uuid4().hex
        self._sequence = 0
        self._telemetry = None
        self._received_at = self._received_monotonic = self._fact = None
        self._dht_warning = None
        self._fan_driver_required = False

    def connect(self) -> dict[str, Any]:
        with self._lifecycle:
            with self._lock:
                if self._connected:
                    return self.snapshot()
            self._disconnect()
            with self._lock:
                self._new_session_locked()
                self._generation += 1
                generation = self._generation
                self._error = None
            try:
                connection = self._serial_factory(port=self.port, baudrate=self.baudrate, timeout=0.2)
            except Exception:
                with self._lock:
                    self._error = f"Cannot open {self.port}. Close Arduino Serial Monitor and other apps using the port, check the USB connection, then reconnect."
                return self.snapshot()
            stop = threading.Event()
            thread = threading.Thread(target=self._read_loop, args=(connection, generation, stop),
                                      name="uno-read-only-telemetry", daemon=True)
            with self._lock:
                self._connection, self._stop, self._thread = connection, stop, thread
                self._connected = True
            thread.start()
            return self.snapshot()

    def _disconnect(self):
        with self._lock:
            connection, thread, stop = self._connection, self._thread, self._stop
            self._generation += 1
            self._connected = False
            self._connection = self._thread = self._stop = None
            self._new_session_locked()
        if stop:
            stop.set()
        if connection is not None:
            # cancel_read/close release a blocked read; neither sends a serial command.
            try:
                cancel = getattr(connection, "cancel_read", None)
                if cancel:
                    cancel()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1)

    def disconnect(self) -> dict[str, Any]:
        with self._lifecycle:
            self._disconnect()
            with self._lock:
                self._error = None
            return self.snapshot()

    def _read_loop(self, connection, generation: int, stop: threading.Event):
        pending = bytearray()
        discard = False
        try:
            while not stop.is_set():
                chunk = connection.read_until(expected=b"\n", size=MAX_LINE_BYTES)
                if stop.is_set():
                    break
                if not chunk:
                    stop.wait(0.01)
                    continue
                # Preserve short timeout fragments, but reject an entire oversized line.
                for byte in chunk:
                    if byte == 10:
                        if not discard:
                            self._accept_line(bytes(pending), generation)
                        pending.clear()
                        discard = False
                    elif not discard:
                        pending.append(byte)
                        if len(pending) >= MAX_LINE_BYTES:
                            pending.clear()
                            discard = True
        except Exception:
            with self._lock:
                if generation == self._generation:
                    self._connected = False
                    self._new_session_locked()
                    self._error = f"USB telemetry from {self.port} stopped. Check the cable and reconnect; close Serial Monitor if the port is busy."
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _accept_line(self, line: bytes, generation: int):
        try:
            text = line.decode("ascii").strip()
        except UnicodeDecodeError:
            return
        with self._lock:
            if generation != self._generation or not self._connected:
                return
            if text == "System Initialized.":
                self._new_session_locked()
                return
            if text == _DHT_WARNING:
                self._dht_warning = _DHT_WARNING
                return
            if text == _FAN_DISABLED:
                self._fan_driver_required = True
                return
            telemetry = parse_telemetry(text)
            if telemetry is None:
                return
            self._sequence += 1
            self._telemetry = telemetry
            self._received_at = self._clock()
            self._received_monotonic = self._monotonic()
            self._fact = TemporalFact(
                content=f"Valid legacy telemetry frame {self._sequence} received in session {self._session_id}",
                timestamp=self._received_at, fact_type="uno_telemetry_receipt",
                source=f"USB serial {self.port}",
                metadata={"session_id": self._session_id, "sequence": self._sequence,
                          "provenance": "physical", "dht_sample_freshness": "unknown"},
            )
            self._error = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            age = max(0.0, self._monotonic() - self._received_monotonic) if self._received_monotonic is not None else None
            # Chronofy evaluates receipt freshness. Monotonic elapsed time prevents a
            # wall-clock adjustment from making old USB evidence appear young again.
            fresh = bool(self._connected and self._fact and age is not None and age < STALE_SECONDS
                         and not self._freshness.needs_reacquisition(
                             [self._fact], self._fact.timestamp + timedelta(seconds=age)))
            fan_control = "disabled_driver_required" if self._fan_driver_required else "autonomous_legacy_firmware"
            telemetry = copy.deepcopy(self._telemetry)
            if telemetry is not None:
                telemetry["fan_control"] = fan_control
            return {
                "port": self.port, "baudrate": self.baudrate,
                "connected": self._connected, "fresh": fresh,
                "received_at": self._received_at.isoformat() if self._received_at else None,
                "age_seconds": round(age, 3) if age is not None else None,
                "stale_after_seconds": STALE_SECONDS,
                "sequence": self._sequence, "session_id": self._session_id,
                "telemetry": telemetry, "error": self._error,
                "fan_control": fan_control,
                "dht_warning": self._dht_warning,
                "evidence_kind": "telemetry_receipt",
                "read_only": True,
            }

    def observe(self) -> dict[str, Any]:
        return asyncio.run(self.gateway.call_tool(TELEMETRY_TOOL, {}))

    def capabilities(self) -> dict[str, Any]:
        state = self.snapshot()
        fan_disabled = state["fan_control"] == "disabled_driver_required"
        return {
            "device": "uno", "tier": "constrained_mcu", "transport": "USB serial",
            "connected": state["connected"], "provenance": "physical",
            "read_only": True, "tools": asyncio.run(self.gateway.list_tools()),
            "fan": {"control": state["fan_control"], "agent_control": False,
                    "on_at_c": None if fan_disabled else 28,
                    "off_below_c": None if fan_disabled else 27,
                    "verification": "Firmware reports fan output disabled because a motor driver is required."
                    if fan_disabled else "Firmware-reported state; rotation is not independently measured."},
            "dht": {"sample_age_known": False, "validity_known": False, "note": _DHT_NOTE},
        }


def hardware_router(service: HardwareService) -> APIRouter:
    router = APIRouter(prefix="/api/hardware", tags=["hardware"])

    @router.get("/state")
    def state():
        return service.snapshot()

    @router.post("/connect")
    def connect(request: Request):
        require_laptop(request)
        return service.connect()

    @router.post("/disconnect")
    def disconnect(request: Request):
        require_laptop(request)
        return service.disconnect()

    return router
