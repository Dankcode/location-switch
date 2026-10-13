import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from location_switch import server
from location_switch.device import DeviceController, DeviceError
from location_switch.geocode import Geocoder


@pytest.fixture
def client(monkeypatch):
    controller = DeviceController()
    monkeypatch.setattr(server, "controller", controller)
    with TestClient(server.app, base_url="http://localhost") as client:
        yield client


def headers():
    return {"Origin": "http://localhost", "X-Location-Token": server.TOKEN}


def test_cross_origin_and_missing_token_cannot_change_device(client):
    target = {"udid": "00000000-00000000"}
    assert client.post("/api/restore", json=target).status_code == 403
    assert client.post("/api/restore", json=target, headers={**headers(), "Origin": "https://elsewhere.example"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


@pytest.mark.parametrize("coordinates", [{"latitude":91,"longitude":0}, {"latitude":0,"longitude":181}, {"latitude":"NaN","longitude":0}])
def test_invalid_coordinates_never_reach_device(client, coordinates):
    assert client.post("/api/spoof", json={"udid":"00000000-00000000", **coordinates}, headers=headers()).status_code == 422


def test_device_failure_reported_without_false_success(client, monkeypatch):
    monkeypatch.setattr(server.controller, "change", AsyncMock(side_effect=DeviceError("Developer Mode required")))
    response = client.post("/api/spoof", json={"udid":"00000000-00000000", "latitude":0, "longitude":0}, headers=headers())
    assert response.status_code == 503
    assert "Developer Mode" in response.json()["detail"]


def test_spoof_and_restore_pass_correct_actions(client, monkeypatch):
    change = AsyncMock(return_value={"mode":"real"})
    monkeypatch.setattr(server.controller, "change", change)
    assert client.post("/api/spoof", json={"udid":"00000000-00000000", "latitude":12.3, "longitude":45.6, "label":"Test City"}, headers=headers()).status_code == 200
    assert change.call_args.args == ("00000000-00000000", "set", 12.3, 45.6, "Test City")
    assert client.post("/api/restore", json={"udid":"00000000-00000000"}, headers=headers()).status_code == 200
    assert change.call_args.args == ("00000000-00000000", "clear")


async def test_controller_waits_for_ack_and_failure_sets_unknown(monkeypatch):
    controller = DeviceController()
    controller.udid = "device-a"
    process = AsyncMock()
    process.returncode = None
    process.stdin.write = lambda value: None
    controller.process = process
    gate = asyncio.Event()
    async def read():
        await gate.wait()
        return {"ok": True}
    monkeypatch.setattr(controller, "_read", read)
    task = asyncio.create_task(controller.change("device-a", "set", 1, 2, "Test"))
    await asyncio.sleep(0)
    assert controller.mode == "unknown"
    gate.set()
    assert (await task)["mode"] == "spoofed"
    monkeypatch.setattr(controller, "_read", AsyncMock(side_effect=DeviceError("Disconnected")))
    monkeypatch.setattr(controller, "_close", AsyncMock())
    with pytest.raises(DeviceError):
        await controller.change("device-a", "clear")
    assert controller.mode == "unknown"


async def test_cannot_abandon_active_device():
    controller = DeviceController()
    controller.udid = "device-a"
    controller.mode = "spoofed"
    with pytest.raises(DeviceError, match="Restore"):
        await controller.change("device-b", "set", 1, 2)


async def test_photon_coordinates_and_cache(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"features":[{"geometry":{"coordinates":[45.6,12.3]}, "properties":{"name":"Test place", "city":"Test City"}}]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    geocoder = Geocoder()
    results = await geocoder.search("Test place")
    assert results[0] == {"label":"Test place, Test City", "latitude":12.3, "longitude":45.6}
    assert await geocoder.search("test PLACE") == results
    assert len(calls) == 1


def test_address_outage_supports_manual_fallback(client, monkeypatch):
    monkeypatch.setattr(server.geocoder, "search", AsyncMock(side_effect=httpx.ConnectError("offline")))
    response = client.post("/api/search", json={"query":"Test City"}, headers=headers())
    assert response.status_code == 502
    assert "coordinates" in response.json()["detail"]
