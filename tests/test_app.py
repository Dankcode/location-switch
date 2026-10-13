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


async def test_developer_mode_off_blocks_location_session(monkeypatch):
    from location_switch.worker import serve
    import pymobiledevice3.lockdown
    lockdown = AsyncMock()
    lockdown.has_developer_mode = True
    lockdown.__aenter__.return_value = lockdown
    lockdown.get_developer_mode_status.return_value = False
    monkeypatch.setattr(pymobiledevice3.lockdown, "create_using_usbmux", AsyncMock(return_value=lockdown))
    with pytest.raises(RuntimeError, match="Developer Mode is off"):
        await serve("test-device-0001")


def test_developer_mode_endpoint_is_protected_and_targets_selected_phone(client, monkeypatch):
    enable = AsyncMock(return_value={"state":"enabling", "udid":"test-device-0001", "message":"Restarting"})
    monkeypatch.setattr(server.controller, "enable_developer_mode", enable)
    target = {"udid":"test-device-0001"}
    assert client.post("/api/developer-mode/enable", json=target).status_code == 403
    assert client.post("/api/developer-mode/enable", json={"udid":"bad;command"}, headers=headers()).status_code == 422
    response = client.post("/api/developer-mode/enable", json=target, headers=headers())
    assert response.status_code == 202
    assert response.json()["state"] == "enabling"
    enable.assert_awaited_once_with("test-device-0001")


async def test_setup_stays_pending_until_verified_and_blocks_location_changes(monkeypatch):
    controller = DeviceController()
    gate = asyncio.Event()
    async def enable(udid):
        assert udid == "test-device-0001"
        await gate.wait()
    monkeypatch.setattr(controller, "_enable_command", enable)
    result = await controller.enable_developer_mode("test-device-0001")
    assert result["state"] == "enabling"
    with pytest.raises(DeviceError, match="already running"):
        await controller.enable_developer_mode("test-device-0001")
    with pytest.raises(DeviceError, match="setup to finish"):
        await controller.change("test-device-0001", "set", 1, 2)
    gate.set()
    await controller.setup_task
    assert controller.status()["developer_setup"]["state"] == "enabled"
    assert controller.udid is None  # setup alone does not reserve a location session


async def test_setup_failure_and_active_spoof_guard(monkeypatch):
    controller = DeviceController()
    controller.mode = "spoofed"
    with pytest.raises(DeviceError, match="Restore"):
        await controller.enable_developer_mode("test-device-0001")
    controller.mode = "unknown"
    monkeypatch.setattr(controller, "_enable_command", AsyncMock(side_effect=DeviceError("Passcode is set")))
    await controller.enable_developer_mode("test-device-0001")
    await controller.setup_task
    assert controller.setup["state"] == "error"
    assert "Passcode" in controller.setup["message"]


async def test_setup_worker_already_enabled_does_not_restart(monkeypatch):
    from location_switch.worker import enable_developer_mode
    import pymobiledevice3.lockdown
    from pymobiledevice3.services.amfi import AmfiService
    lockdown = AsyncMock()
    lockdown.has_developer_mode = True
    lockdown.__aenter__.return_value = lockdown
    lockdown.get_developer_mode_status.return_value = True
    monkeypatch.setattr(pymobiledevice3.lockdown, "create_using_usbmux", AsyncMock(return_value=lockdown))
    enable = AsyncMock()
    monkeypatch.setattr(AmfiService, "enable_developer_mode", enable)
    reveal = AsyncMock()
    monkeypatch.setattr(AmfiService, "reveal_developer_mode_option_in_ui", reveal)
    await enable_developer_mode("test-device-0001")
    enable.assert_not_awaited()
    reveal.assert_not_awaited()


async def test_setup_worker_passcode_error_explains_manual_path(monkeypatch):
    from location_switch.worker import enable_developer_mode
    import pymobiledevice3.lockdown
    from pymobiledevice3.services.amfi import AmfiService
    from pymobiledevice3.exceptions import DeviceHasPasscodeSetError
    lockdown = AsyncMock()
    lockdown.has_developer_mode = True
    lockdown.__aenter__.return_value = lockdown
    lockdown.get_developer_mode_status.return_value = False
    monkeypatch.setattr(pymobiledevice3.lockdown, "create_using_usbmux", AsyncMock(return_value=lockdown))
    monkeypatch.setattr(AmfiService, "enable_developer_mode", AsyncMock(side_effect=DeviceHasPasscodeSetError()))
    reveal = AsyncMock()
    monkeypatch.setattr(AmfiService, "reveal_developer_mode_option_in_ui", reveal)
    with pytest.raises(RuntimeError, match="revealed without Xcode"):
        await enable_developer_mode("test-device-0001")
    reveal.assert_awaited_once()


@pytest.mark.parametrize("verified", [True, False])
async def test_setup_worker_verifies_after_upstream_enable(monkeypatch, verified):
    from location_switch.worker import enable_developer_mode
    import pymobiledevice3.lockdown
    from pymobiledevice3.services.amfi import AmfiService
    lockdown = AsyncMock()
    lockdown.has_developer_mode = True
    lockdown.__aenter__.return_value = lockdown
    lockdown.get_developer_mode_status.side_effect = [False, verified]
    create = AsyncMock(return_value=lockdown)
    monkeypatch.setattr(pymobiledevice3.lockdown, "create_using_usbmux", create)
    enable = AsyncMock()
    monkeypatch.setattr(AmfiService, "enable_developer_mode", enable)
    reveal = AsyncMock()
    monkeypatch.setattr(AmfiService, "reveal_developer_mode_option_in_ui", reveal)
    if verified:
        await enable_developer_mode("test-device-0001")
    else:
        with pytest.raises(RuntimeError, match="still off"):
            await enable_developer_mode("test-device-0001")
    enable.assert_awaited_once()
    reveal.assert_awaited_once()
    assert create.await_count == 2
    create.assert_awaited_with(serial="test-device-0001", autopair=False)


async def test_shutdown_cancels_pending_setup(monkeypatch):
    controller = DeviceController()
    gate = asyncio.Event()
    async def enable(udid):
        await gate.wait()
    monkeypatch.setattr(controller, "_enable_command", enable)
    await controller.enable_developer_mode("test-device-0001")
    await asyncio.sleep(0)
    await controller.shutdown()
    assert controller.setup_task.cancelled()
    assert controller.setup["state"] == "error"
