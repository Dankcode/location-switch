import secrets
import os
import base64
import binascii
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .device import DeviceController, DeviceError
from .geocode import Geocoder

ROOT = Path(__file__).parent / "static"
controller = DeviceController()
geocoder = Geocoder()
TOKEN = secrets.token_urlsafe(32)
PHONE_ACCESS = os.getenv("LOCATION_PHONE_ACCESS") == "1"
ACCESS_KEY = os.getenv("LOCATION_ACCESS_KEY", "")
if PHONE_ACCESS and len(ACCESS_KEY) < 12:
    raise ValueError("Phone access requires a control-panel password of at least 12 characters")
TILE_URL = os.getenv("LOCATION_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
tile_origin = urlsplit(TILE_URL)
if tile_origin.scheme != "https" or not tile_origin.netloc or not all(f"{{{key}}}" in TILE_URL for key in ("z", "x", "y")):
    raise ValueError("LOCATION_TILE_URL must be an HTTPS tile URL with {z}, {x}, and {y} placeholders")


@asynccontextmanager
async def lifespan(app):
    import asyncio
    monitor = None
    if os.getenv("LOCATION_AUTO_REVEAL") == "1":
        async def watch_devices():
            while True:
                try:
                    await controller.devices()
                except Exception:
                    pass
                await asyncio.sleep(20)
        monitor = asyncio.create_task(watch_devices())
    try:
        yield
    finally:
        if monitor:
            monitor.cancel()
            from contextlib import suppress
            with suppress(asyncio.CancelledError):
                await monitor
        await controller.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"] if PHONE_ACCESS else ["127.0.0.1", "localhost"])


def local_phone_host(host):
    import psutil
    names = {"localhost", "127.0.0.1", "::1", socket.gethostname().lower(), socket.gethostname().lower() + ".local"}
    for addresses in psutil.net_if_addrs().values():
        names.update(address.address.split('%')[0].lower() for address in addresses if address.family in (socket.AF_INET, socket.AF_INET6))
    return host.lower() in names


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if PHONE_ACCESS:
        try:
            host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
            if not local_phone_host(host):
                return JSONResponse({"detail":"Invalid control-panel host."}, status_code=400)
            scheme, credentials = request.headers.get("authorization", "").split(" ",1)
            user, password = base64.b64decode(credentials, validate=True).decode().split(":",1)
            authorized = scheme.lower() == "basic" and secrets.compare_digest(user.encode(),b"location") and secrets.compare_digest(password.encode(),ACCESS_KEY.encode())
        except (ValueError, UnicodeError, binascii.Error):
            authorized = False
        if not authorized:
            return JSONResponse({"detail":"Control-panel login required."},status_code=401,headers={"WWW-Authenticate":'Basic realm="Location Switch", charset="UTF-8"'})
    if request.method == "POST":
        expected = f"{request.url.scheme}://{request.headers.get('host')}"
        if request.headers.get("origin") != expected or request.headers.get("x-location-token") != TOKEN:
            return JSONResponse({"detail": "Open the app locally and try again."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "public, max-age=604800" if request.url.path.startswith("/static/vendor/") else "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = f"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data: https://{tile_origin.netloc}; frame-ancestors 'none'; base-uri 'none'"
    return response


@app.exception_handler(DeviceError)
async def device_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503)


class Target(BaseModel):
    udid: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9-]+$")


class Destination(Target):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    label: str = Field(default="Manual coordinates", max_length=500)


class Search(BaseModel):
    query: str = Field(min_length=3, max_length=250)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (ROOT / "index.html").read_text().replace("__TOKEN__", TOKEN)


@app.get("/api/devices")
async def devices(refresh: bool = False):
    return {"devices": await controller.devices(force=refresh)}


@app.get("/api/config")
async def config():
    return {"tile_url": TILE_URL, "discovery_interval": max(20, controller.discovery_ttl)}


@app.get("/api/status")
async def status():
    return controller.status()


@app.post("/api/search")
async def search(data: Search):
    if len(data.query.strip()) < 3:
        raise HTTPException(422, "Enter at least three characters.")
    try:
        return {"results": await geocoder.search(data.query.strip())}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(502, "Address search is unavailable. Try again or enter WGS84 coordinates directly.")


@app.post("/api/spoof")
async def spoof(data: Destination):
    return await controller.change(data.udid, "set", data.latitude, data.longitude, data.label)


@app.post("/api/restore")
async def restore(data: Target):
    return await controller.change(data.udid, "clear")


@app.post("/api/developer-mode/enable", status_code=202)
async def enable_developer_mode(data: Target):
    return await controller.enable_developer_mode(data.udid)


@app.post("/api/device/pair", status_code=202)
async def pair_device(data:Target):
    return await controller.pair_device(data.udid)


app.mount("/static", StaticFiles(directory=ROOT), name="static")
