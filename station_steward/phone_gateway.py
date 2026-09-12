"""Temporary paired phone display. Never proxy the privileged laptop APIs."""
from __future__ import annotations

import hmac
import html
import io
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import qrcode
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from station_steward.local_access import require_laptop

COOKIE = "station_phone"
PASSPORT = re.compile(r"/api/passports/[A-F0-9]{12}(?:/code\.png)?\Z")
PUBLIC = Path(__file__).resolve().parent.parent / "mobile" / "dist" / "client"
STATIC_EXTENSIONS = {".js", ".css", ".png", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".webp"}


def create_gateway(*, upstream="http://localhost:8765", transport=None, tunnel_lookup=None):
    app = FastAPI(title="Station Steward paired phone", docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)
    expires_at = time.monotonic() + 14400
    origin_cache = {"origin": None, "until": 0.0}
    last_created_at = -10.0

    def safe_passport(value):
        if not value:
            return None
        return {**{key: value[key] for key in ("id", "station", "created_at", "expires_at", "expired", "active", "qr_payload", "evidence", "budget") if key in value}, "last_scan": None}

    async def public_origin():
        if tunnel_lookup:
            return tunnel_lookup()
        if origin_cache["origin"] and time.monotonic() < origin_cache["until"]:
            return origin_cache["origin"]
        gateway_port = int(os.environ.get("STATION_GATEWAY_PORT", "8766"))
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                result = await client.get("http://127.0.0.1:4040/api/tunnels")
                result.raise_for_status()
                for tunnel in result.json().get("tunnels", []):
                    origin = tunnel.get("public_url", "")
                    parsed = urlsplit(origin)
                    if (tunnel.get("config", {}).get("addr") == f"http://127.0.0.1:{gateway_port}"
                            and parsed.scheme == "https" and parsed.hostname and not parsed.username
                            and not parsed.password and not parsed.query and not parsed.fragment
                            and parsed.path in {"", "/"}):
                        origin_cache.update(origin=origin.rstrip("/"), until=time.monotonic() + 10)
                        return origin_cache["origin"]
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        raise HTTPException(503, "The phone tunnel is reconnecting. Refresh this page after Wi-Fi is online.")

    @app.middleware("http")
    async def paired_access(request: Request, call_next):
        if time.monotonic() >= expires_at:
            return JSONResponse({"detail": "Pairing expired. Restart the phone gateway on the laptop."}, status_code=401)
        if request.url.path in {"/pair", "/pair.png"}:
            try:
                require_laptop(request)
                if any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")):
                    raise HTTPException(403)
            except HTTPException:
                return JSONResponse({"detail": "Open pairing on the laptop's localhost address."}, status_code=403)
        else:
            try:
                expected_host = urlsplit(await public_origin()).netloc
            except HTTPException as error:
                return JSONResponse({"detail": error.detail}, status_code=error.status_code)
            if request.headers.get("host") != expected_host:
                return JSONResponse({"detail": "Use the current phone tunnel address."}, status_code=403)
            if request.url.path == "/" and request.method == "GET" and hmac.compare_digest(request.query_params.get("pair", ""), token):
                response = RedirectResponse("/?view=phone", status_code=303)
                response.set_cookie(COOKIE, token, max_age=14400, secure=True, httponly=True, samesite="strict")
                response.headers["Cache-Control"] = "no-store"
                response.headers["Referrer-Policy"] = "no-referrer"
                return response
            if not hmac.compare_digest(request.cookies.get(COOKIE, ""), token):
                return JSONResponse({"detail": "Scan the private pairing QR on the laptop first."}, status_code=401)
        if request.method == "POST" and request.headers.get("origin") != f"https://{request.headers.get('host', '')}":
            return JSONResponse({"detail": "Use the paired phone page."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/pair", response_class=HTMLResponse)
    async def pair():
        origin = await public_origin()
        link = origin + "/?" + urlencode({"pair": token})
        return HTMLResponse("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect your phone</title>
<style>body{margin:0;background:#101923;color:#eef4ff;font:18px system-ui;display:grid;place-items:center;min-height:100vh}main{max-width:640px;padding:28px}h1{font-size:32px}img{display:block;background:white;padding:12px;max-width:80vw;height:auto}a{color:#8bd5ff;overflow-wrap:anywhere}p{line-height:1.5}</style>
<main><h1>Connect your phone</h1><p>Scan this with your Android camera. The phone can use Wi-Fi or mobile data.</p>
<img src="/pair.png" alt="Private phone pairing QR" width="330" height="330">
<p>If ngrok shows a welcome screen, choose <strong>Visit Site</strong> once.</p>
<p>Then choose <strong>Arduino bench</strong> and <strong>Show station passport</strong> on the phone.</p>
<p><a href=""" + '"' + html.escape(link, quote=True) + '"' + """>Open paired phone display</a></p>
<p>Keep the laptop camera and agent at <a href="http://localhost:8765/?view=camera">the localhost camera page</a>.</p>
<p>This QR grants phone-display access. Keep it out of public recordings.</p></main></html>""")

    @app.get("/pair.png")
    async def pairing_image():
        link = (await public_origin()) + "/?" + urlencode({"pair": token})
        output = io.BytesIO()
        qrcode.make(link).save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png")

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def phone(request: Request, path: str):
        nonlocal last_created_at
        route = "/" + path
        allowed = ((request.method == "GET" and (route == "/api/state" or PASSPORT.fullmatch(route)))
                   or (request.method == "POST" and route == "/api/passports"))
        if allowed:
            body = b""
            if request.method == "POST":
                async for chunk in request.stream():
                    body += chunk
                    if len(body) > 1024:
                        raise HTTPException(413, "Station selection is too large.")
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise HTTPException(415, "Use a station selection.")
                if time.monotonic() - last_created_at < 2:
                    raise HTTPException(429, "Wait two seconds before showing another passport.")
                last_created_at = time.monotonic()
            try:
                async with httpx.AsyncClient(base_url=upstream, transport=transport, timeout=10, trust_env=False) as client:
                    result = await client.request(request.method, route, content=body,
                                                  headers={"Origin": upstream, "Content-Type": "application/json"})
                if route == "/api/state" and result.is_success:
                    state = result.json()
                    return JSONResponse({"stations": state["stations"], "active": safe_passport(state.get("active")),
                                         "phone_url": "/?view=phone", "camera_url": "http://localhost:8765/?view=camera"})
                if result.is_success and not route.endswith("/code.png"):
                    return JSONResponse(safe_passport(result.json()), status_code=result.status_code)
                return Response(result.content, status_code=result.status_code,
                                media_type=result.headers.get("content-type", "application/json"))
            except httpx.HTTPError:
                raise HTTPException(503, "The laptop app is unavailable. Keep Station Steward running.") from None
        if request.method != "GET" or route.startswith("/api/"):
            raise HTTPException(404, "This tunnel only serves the phone display.")
        if not path:
            if request.query_params.get("view") != "phone":
                return RedirectResponse("/?view=phone", status_code=303)
            candidate = PUBLIC / "index.html"
        else:
            candidate = (PUBLIC / path).resolve()
            if not candidate.is_relative_to(PUBLIC.resolve()) or candidate.suffix not in STATIC_EXTENSIONS:
                raise HTTPException(404)
        if not candidate.is_file():
            raise HTTPException(404)
        return FileResponse(candidate)

    return app


app = create_gateway(upstream=f"http://localhost:{int(os.environ.get('STATION_PORT', '8765'))}")
