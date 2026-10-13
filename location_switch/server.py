import secrets
from contextlib import asynccontextmanager
from pathlib import Path

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


@asynccontextmanager
async def lifespan(app):
    yield
    await controller.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def local_requests(request: Request, call_next):
    if request.method == "POST":
        expected = f"{request.url.scheme}://{request.headers.get('host')}"
        if request.headers.get("origin") != expected or request.headers.get("x-location-token") != TOKEN:
            return JSONResponse({"detail": "Open the app locally and try again."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
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
async def devices():
    return {"devices": await controller.devices()}


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


app.mount("/static", StaticFiles(directory=ROOT), name="static")
