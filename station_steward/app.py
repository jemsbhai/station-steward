from __future__ import annotations

import hashlib
import io
import math
import os
import secrets
import socket
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import qrcode
from chronofy import EpistemicFilter, ExponentialDecay, TemporalFact
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pollard import Budget, BudgetExceeded, Runtime
from pollard.meters import StepMeter, WallClockMeter
from pydantic import BaseModel
from pyzbar.pyzbar import ZBarSymbol, decode as decode_qr
from starlette.concurrency import run_in_threadpool
from station_steward.agent import AgentService, agent_router
from station_steward.ambiguous import AmbiguousConnection, ambiguous_router
from station_steward.hardware import HardwareService, hardware_router

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 4 * 1024 * 1024
MAX_PIXELS = 2_100_000
SCAN_BUDGET = 30
SESSION_SECONDS = 300
STATIONS = {
    "bench": {"id": "bench", "name": "Arduino bench", "profile": "UNO1", "policy": "DEMO1", "kind": "physical", "capabilities": ["Live distance", "Cached temperature & humidity", "Fan state · automatic firmware", "Joystick readings"], "connection": "Live USB connection checked in the agent panel"},
    "virtual": {"id": "virtual", "name": "Virtual workcell", "profile": "ARM2D1", "policy": "SIM1", "kind": "simulated", "capabilities": ["Scene observation", "Virtual pick-and-place"], "connection": "Simulator available"},
}
FRESHNESS = EpistemicFilter(
    ExponentialDecay(beta={"station_passport": math.log(2) / 30}, time_unit="seconds"),
    threshold=0.5,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def png_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def passport_code(payload: str) -> Image.Image:
    # A short session reference keeps the modules large on a phone screen.
    code = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=12, border=4)
    code.add_data(payload)
    code.make(fit=True)
    return code.make_image(fill_color="black", back_color="white").convert("RGB")


@dataclass
class Passport:
    station_id: str
    id: str = field(default_factory=lambda: secrets.token_hex(6).upper())
    created_at: datetime = field(default_factory=now_utc)
    fact: TemporalFact | None = None
    last_scan: dict | None = None
    calls: list[dict] = field(default_factory=list)
    runtime: Runtime = field(default_factory=lambda: Runtime(mode="record", meters=[StepMeter(), WallClockMeter()]))

    def __post_init__(self):
        self.run = self.runtime.run(f"passport:{self.id}", budget=Budget(steps=SCAN_BUDGET))

    @property
    def expires_at(self):
        return self.created_at + timedelta(seconds=SESSION_SECONDS)

    @property
    def payload(self):
        # Station, capabilities and policy are resolved from the session on the laptop.
        return f"SS2:{self.id}"

    def expired(self):
        return now_utc() >= self.expires_at

    def snapshot(self):
        now = now_utc()
        fresh = self.fact is not None and not self.expired() and not FRESHNESS.needs_reacquisition([self.fact], now)
        spent = self.run.report()["spent"]
        return {
            "id": self.id, "station": STATIONS[self.station_id],
            "created_at": self.created_at.isoformat(), "expires_at": self.expires_at.isoformat(),
            "expired": self.expired(), "qr_payload": self.payload,
            "evidence": {"fresh": fresh, "observed_at": self.fact.timestamp.isoformat() if self.fact else None,
                         "age_seconds": round((now - self.fact.timestamp).total_seconds(), 1) if self.fact else None,
                         "source": "camera upload received by laptop", "refresh_after_seconds": 30},
            "budget": {"limit": SCAN_BUDGET, "used": int(spent.get("steps", 0)), "remaining": max(0, SCAN_BUDGET - int(spent.get("steps", 0))),
                       "decode_seconds": round(spent.get("seconds", 0), 3)},
            "last_scan": self.last_scan,
        }


def read_frame(raw: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise HTTPException(415, "Use a PNG, JPEG or WebP camera frame.")
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(413, "Camera frame is too large. Limit it to about two megapixels.")
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "The camera frame could not be read.") from exc


def decode_frame(image: Image.Image, expected: str) -> dict:
    payloads = []
    method_used = "grayscale"
    try:
        gray = ImageOps.grayscale(image)
        for method, frame in [("grayscale", gray), ("autocontrast", ImageOps.autocontrast(gray))]:
            decoded = decode_qr(frame, symbols=[ZBarSymbol.QRCODE])
            payloads = sorted({symbol.data.decode("utf-8", errors="replace") for symbol in decoded})
            method_used = method
            if payloads:
                break
    except Exception:
        return {"payload": "", "payloads": [], "complete": False, "verified": False, "reason": "decoder_error", "method": method_used}
    complete = bool(payloads)
    verified = payloads == [expected]
    reason = "matched" if verified else "multiple_codes" if len(payloads) > 1 else "different_passport" if complete else "unreadable"
    return {"payload": payloads[0] if len(payloads) == 1 else "", "payloads": payloads,
            "complete": complete, "verified": verified, "reason": reason, "method": method_used}


def lan_base() -> str:
    configured = os.environ.get("STATION_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("8.8.8.8", 80))
            address = connection.getsockname()[0]
    except OSError:
        address = "127.0.0.1"
    return f"http://{address}:{os.environ.get('STATION_PORT', '8765')}"


class CreatePassport(BaseModel):
    station_id: str


def create_app(*, connection_directory: Path | None = None, hardware_service=None) -> FastAPI:
    hardware = hardware_service if hardware_service is not None else HardwareService(port=os.environ.get("STATION_SERIAL_PORT", "COM3"), baudrate=115200)

    @asynccontextmanager
    async def lifespan(app):
        yield
        hardware.disconnect()

    app = FastAPI(title="Station Steward local companion", lifespan=lifespan)
    app.state.hardware = hardware
    app.state.sessions = {}
    app.state.active_id = None
    app.state.lock = threading.RLock()

    @app.middleware("http")
    async def local_headers(request: Request, call_next):
        # Browser writes must originate on this local app; no permissive CORS.
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Open this action from the Station Steward page."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def get_session(session_id: str, *, active=False, allow_expired=False) -> Passport:
        session = app.state.sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Passport not found. Show a new passport on your phone.")
        if active and session_id != app.state.active_id:
            raise HTTPException(409, "A newer passport is active. Refresh and scan the current one.")
        if session.expired() and not allow_expired:
            raise HTTPException(410, "Passport expired. Show a new one on your phone.")
        return session

    @app.get("/api/state")
    def state():
        with app.state.lock:
            session = app.state.sessions.get(app.state.active_id)
            return {"stations": list(STATIONS.values()), "active": session.snapshot() if session else None,
                    "phone_url": lan_base() + "/?view=phone", "camera_url": f"http://localhost:{os.environ.get('STATION_PORT', '8765')}/?view=camera"}

    @app.get("/api/join.png")
    def join_code():
        return Response(png_bytes(qrcode.make(lan_base() + "/?view=phone").convert("RGB")), media_type="image/png")

    @app.post("/api/passports")
    def new_passport(body: CreatePassport):
        if body.station_id not in STATIONS:
            raise HTTPException(422, "Choose a registered station.")
        with app.state.lock:
            if len(app.state.sessions) >= 100:
                # Bounded demo memory; discard oldest session, never mutate a receipt.
                app.state.sessions.pop(next(iter(app.state.sessions)))
            session = Passport(body.station_id)
            previous = app.state.sessions.get(app.state.active_id)
            if previous is not None:
                previous.fact = None
            app.state.sessions[session.id] = session
            app.state.active_id = session.id
            return session.snapshot()

    @app.get("/api/passports/{session_id}")
    def passport_state(session_id: str):
        with app.state.lock:
            session = get_session(session_id, allow_expired=True)
            result = session.snapshot()
            result["active"] = session_id == app.state.active_id
            return result

    @app.get("/api/passports/{session_id}/code.png")
    def passport_png(session_id: str):
        with app.state.lock:
            session = get_session(session_id, active=True)
            return Response(png_bytes(passport_code(session.payload)), media_type="image/png")

    def execute_scan(session_id: str, raw: bytes, received_at: datetime):
        with app.state.lock:
            session = get_session(session_id, active=True)
            image = read_frame(raw)
            args = {"session_id": session.id, "frame_sha256": hashlib.sha256(raw).hexdigest(),
                    "received_at_ms": int(received_at.timestamp() * 1000), "decoder_profile": "zbar-qr-v1"}

            def decode_and_verify(_):
                result = decode_frame(image, session.payload)
                result["matched"] = result["verified"]
                # Persist expiry during decoding in the same outcome as the match.
                if session.expired():
                    result.update(verified=False, reason="expired")
                return result

            try:
                node = session.run.tool_call("qr.decode", args, fn=decode_and_verify)
            except BudgetExceeded as exc:
                raise HTTPException(429, "This passport's scan budget is used. Show a new passport to start a new session.") from exc
            session.calls.append(args)
            result = dict(node.result)
            result.update(received_at=received_at.isoformat(), node_id=node.id)
            session.last_scan = result
            session.fact = TemporalFact(content=f"Passport for {session.station_id} observed", timestamp=received_at,
                                        fact_type="station_passport", source="camera_upload_received", source_quality=1,
                                        metadata={"session_id": session.id, "pollard_node_id": node.id}) if result["verified"] else None
            return {"scan": result, "passport": session.snapshot()}

    @app.post("/api/passports/{session_id}/scan")
    async def scan(session_id: str, request: Request):
        if request.headers.get("content-type", "").split(";")[0] not in {"image/png", "image/jpeg", "image/webp"}:
            raise HTTPException(415, "Send a camera image.")
        received_at = now_utc()
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_UPLOAD:
                raise HTTPException(413, "Camera upload exceeds 4 MB.")
        return await run_in_threadpool(execute_scan, session_id, bytes(raw), received_at)

    @app.get("/api/passports/{session_id}/replay")
    def replay(session_id: str):
        with app.state.lock:
            session = get_session(session_id, allow_expired=True)
            runtime = Runtime(store=session.runtime.store, mode="replay", meters=[StepMeter(), WallClockMeter()])
            run = runtime.run(f"passport:{session.id}")

            def forbidden(_):
                raise RuntimeError("Historical replay must not invoke the decoder.")

            records = []
            for args in session.calls:
                node = run.tool_call("qr.decode", args, fn=forbidden)
                records.append({"node_id": node.id, "received_at_ms": args["received_at_ms"], **node.result})
            return {"historical": True, "records": records, "report": run.report(),
                    "live_evidence_refreshed": False, "hardware_commands": 0}

    def check_agent_passport(session_id: str, *, require_fresh=False):
        with app.state.lock:
            session = app.state.sessions.get(session_id)
            if not session or session_id != app.state.active_id or session.expired():
                return False, "Select and scan the current station passport before starting a mission."
            if require_fresh and not session.snapshot()["evidence"]["fresh"]:
                return False, "Scan the station QR again to refresh its observation before starting."
            return True, ""

    def station_lookup(session_id):
        with app.state.lock:
            return get_session(session_id, active=True).station_id

    app.state.ambiguous = AmbiguousConnection(connection_directory or ROOT / ".local")
    app.state.agent = AgentService(passport_check=check_agent_passport, handoff_sink=app.state.ambiguous.deliver,
                                   handoff_enabled=lambda: app.state.ambiguous.snapshot()["enabled"],
                                   hardware=hardware, station_lookup=station_lookup)
    app.include_router(agent_router(app.state.agent))
    app.include_router(hardware_router(hardware))
    app.include_router(ambiguous_router(app.state.ambiguous, app.state.agent.sync_handoff))

    @app.get("/{path:path}")
    def static_page(path: str):
        public = ROOT / "mobile" / "dist" / "client"
        candidate = (public / path).resolve()
        if not candidate.is_relative_to(public.resolve()):
            raise HTTPException(404)
        if not path or path in {"phone", "camera"}:
            candidate = public / "index.html"
        if not candidate.is_file():
            raise HTTPException(404, "Page unavailable. Build the mobile interface first.")
        return FileResponse(candidate)

    return app


app = create_app()
