from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, Mock

import pytest

from location_switch.device import DeviceController
from location_switch.__main__ import main
from location_switch.worker import open_developer_provider


async def test_discovery_is_cached_and_manual_refresh_bypasses_it(monkeypatch):
    controller = DeviceController()
    discover = AsyncMock(return_value=[{"udid":"test-device"}])
    monkeypatch.setattr(controller, "_discover", discover)
    assert await controller.devices() == await controller.devices()
    discover.assert_awaited_once()
    await controller.devices(force=True)
    assert discover.await_count == 2


async def test_concurrent_discovery_shares_one_worker(monkeypatch):
    import asyncio
    controller = DeviceController()
    discover = AsyncMock(return_value=[])
    monkeypatch.setattr(controller, "_discover", discover)
    await asyncio.gather(controller.devices(), controller.devices())
    discover.assert_awaited_once()


@pytest.mark.parametrize("host", ["Linux", "Windows"])
@pytest.mark.parametrize("version,transport,uses_daemon", [("17.3.1","auto",True),("17.4","auto",False),("27.0.1","auto",False),("27.0.1","tunneld",True)])
async def test_tunnel_routing_and_selected_device(monkeypatch, host, version, transport, uses_daemon):
    import location_switch.worker as worker
    import pymobiledevice3.remote.rsd_tunnel as tunnel
    import pymobiledevice3.tunneld.api as daemon
    monkeypatch.setattr(worker.platform, "system", lambda:host)
    monkeypatch.setenv("LOCATION_TUNNEL", transport)
    provider = AsyncMock()
    provider.__aenter__.return_value = provider
    preferred = Mock(return_value=provider)
    get = AsyncMock(return_value=provider)
    monkeypatch.setattr(tunnel, "PreferredRsdTunnel", preferred)
    monkeypatch.setattr(daemon, "get_tunneld_device_by_udid", get)
    async with AsyncExitStack() as stack:
        assert await open_developer_provider(stack,"test-device",version) is provider
    if uses_daemon:
        get.assert_awaited_once_with("test-device")
        provider.close.assert_awaited_once()
        preferred.assert_not_called()
    else:
        preferred.assert_called_once_with(serial="test-device",autopair=False)
        get.assert_not_awaited()


def test_headless_linux_and_low_memory_cli(monkeypatch):
    import location_switch.__main__ as entry
    monkeypatch.setattr(entry.platform,"system",lambda:"Linux")
    run = Mock()
    browser = Mock()
    monkeypatch.setattr(entry.uvicorn,"run",run)
    monkeypatch.setattr(entry.webbrowser,"open",browser)
    monkeypatch.setenv("LOCATION_DISCOVERY_TTL","20")
    monkeypatch.setenv("LOCATION_TUNNEL","auto")
    main(["--no-browser","--low-memory","--port","8799","--tunnel","tunneld"])
    import os
    assert os.environ["LOCATION_DISCOVERY_TTL"] == "60"
    assert os.environ["LOCATION_TUNNEL"] == "tunneld"
    browser.assert_not_called()
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 8799
    assert run.call_args.kwargs["workers"] == 1


def test_invalid_port_fails_before_server_starts():
    with pytest.raises(SystemExit):
        main(["--port","0"])


def test_phone_mode_uses_private_persistent_key_and_network_listener(monkeypatch,tmp_path):
    import location_switch.__main__ as entry
    import os
    monkeypatch.chdir(tmp_path)
    for name in ("LOCATION_PHONE_ACCESS","LOCATION_ACCESS_KEY","LOCATION_AUTO_REVEAL","LOCATION_AUTO_MOUNT","LOCATION_COMMAND_TIMEOUT","LOCATION_TUNNEL"):
        monkeypatch.delenv(name,raising=False)
    run = Mock()
    monkeypatch.setattr(entry.uvicorn,"run",run)
    main(["--no-browser","--phone-access","--auto-reveal","--auto-mount"])
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    key_file=tmp_path/'state/access-key'
    assert len(key_file.read_text().strip()) >= 12
    if os.name != "nt":
        assert key_file.stat().st_mode & 0o777 == 0o600
    assert os.environ["LOCATION_AUTO_REVEAL"] == "1"
    assert os.environ["LOCATION_AUTO_MOUNT"] == "1"
    assert os.environ["LOCATION_COMMAND_TIMEOUT"] == "600"
    key=key_file.read_text()
    monkeypatch.delenv("LOCATION_ACCESS_KEY")
    main(["--no-browser","--phone-access"])
    assert key_file.read_text() == key


async def test_auto_setup_pairs_untrusted_single_phone_once(monkeypatch):
    import asyncio
    monkeypatch.setenv("LOCATION_AUTO_REVEAL","1")
    controller=DeviceController()
    controller.discovery_ttl=0
    monkeypatch.setattr(controller,"_discover",AsyncMock(return_value=[{"udid":"test-phone","ready":False}]))
    pair=AsyncMock()
    monkeypatch.setattr(controller,"pair_device",pair)
    await controller.devices()
    await controller.devices()
    pair.assert_awaited_once_with("test-phone")


async def test_auto_setup_reveals_without_enabling_or_rebooting(monkeypatch):
    monkeypatch.setenv("LOCATION_AUTO_REVEAL","1")
    controller=DeviceController()
    controller.discovery_ttl=0
    monkeypatch.setattr(controller,"_discover",AsyncMock(return_value=[{"udid":"test-phone","ready":True,"developer_mode":False}]))
    reveal=AsyncMock()
    enable=AsyncMock()
    monkeypatch.setattr(controller,"_reveal",reveal)
    monkeypatch.setattr(controller,"enable_developer_mode",enable)
    await controller.devices()
    await controller.devices()
    reveal.assert_awaited_once_with("test-phone")
    enable.assert_not_awaited()
    assert controller.setup["state"] == "manual"


async def test_pair_worker_waits_for_trust(monkeypatch):
    from location_switch.worker import pair_device
    import pymobiledevice3.lockdown
    lockdown=AsyncMock()
    lockdown.paired=True
    lockdown.__aenter__.return_value=lockdown
    create=AsyncMock(return_value=lockdown)
    monkeypatch.setattr(pymobiledevice3.lockdown,"create_using_usbmux",create)
    await pair_device("test-phone")
    create.assert_awaited_once_with(serial="test-phone",autopair=True,pair_timeout=120)


async def test_missing_dvt_auto_prepares_and_reopens_tunnel(monkeypatch):
    import location_switch.worker as worker
    import pymobiledevice3.services.mobile_image_mounter as mounter
    from pymobiledevice3.exceptions import InvalidServiceError
    monkeypatch.setenv("LOCATION_AUTO_MOUNT","1")
    stack=AsyncMock()
    dvt=object()
    stack.enter_async_context.side_effect=[InvalidServiceError("missing","test-phone","27.0.1"),dvt]
    provider=Mock(product_version="27.0.1")
    mount=AsyncMock()
    reopen=AsyncMock(return_value=Mock(product_version="27.0.1"))
    monkeypatch.setattr(mounter,"auto_mount",mount)
    monkeypatch.setattr(worker,"open_developer_provider",reopen)
    assert await worker.prepare_dvt(stack,provider,"test-phone","27.0.1") is dvt
    mount.assert_awaited_once_with(provider)
    stack.aclose.assert_awaited_once()
    reopen.assert_awaited_once_with(stack,"test-phone","27.0.1")


async def test_auto_prepare_is_opt_in(monkeypatch):
    from location_switch.worker import prepare_dvt
    from pymobiledevice3.exceptions import InvalidServiceError
    monkeypatch.delenv("LOCATION_AUTO_MOUNT",raising=False)
    stack=AsyncMock()
    stack.enter_async_context.side_effect=InvalidServiceError("missing","test-phone","27.0.1")
    with pytest.raises(RuntimeError,match="Mount the developer disk image"):
        await prepare_dvt(stack,Mock(product_version="27.0.1"),"test-phone","27.0.1")
    stack.aclose.assert_not_awaited()


async def test_worker_progress_does_not_become_false_success():
    controller=DeviceController()
    controller.process=AsyncMock()
    controller.process.stdout.readline.side_effect=[b'{"progress":"Preparing image"}\n',b'{"ready":true}\n']
    assert await controller._read() == {"ready":True}
    assert controller.operation_message == "Preparing image"
    assert controller.mode == "unknown"


def test_frozen_worker_command_uses_executable_dispatch(monkeypatch):
    import location_switch.runtime as runtime
    monkeypatch.setattr(runtime.sys, 'frozen', True, raising=False)
    assert runtime.worker_command('list') == [runtime.sys.executable, '--worker', 'list']


async def test_windows_reader_handles_commands_and_eof(monkeypatch):
    import io
    import asyncio
    import location_switch.worker as worker
    monkeypatch.setattr(worker.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(worker.sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'{"action":"clear"}\n')))
    reader, transport = await worker.command_reader()
    assert transport is None
    assert await asyncio.wait_for(reader.readline(), 2) == b'{"action":"clear"}\n'
    assert await asyncio.wait_for(reader.readline(), 2) == b''
