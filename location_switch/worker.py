"""One isolated, persistent device connection; newline-delimited JSON IPC."""
import asyncio
import json
import sys
from contextlib import AsyncExitStack, suppress


def emit(value):
    print(json.dumps(value), flush=True)


async def discover():
    from pymobiledevice3.usbmux import list_devices
    from pymobiledevice3.lockdown import create_using_usbmux

    result = []
    seen = set()
    for device in await list_devices():
        if device.serial in seen:
            continue
        seen.add(device.serial)
        try:
            async with await create_using_usbmux(
                serial=device.serial, autopair=False, connection_type=device.connection_type
            ) as lockdown:
                info = lockdown.short_info
                developer_mode = None
                with suppress(Exception):
                    developer_mode = not lockdown.has_developer_mode or await lockdown.get_developer_mode_status()
                result.append({"udid": device.serial, "name": info.get("DeviceName", "iPhone"),
                               "version": info.get("ProductVersion", "unknown"), "ready": True,
                               "developer_mode": developer_mode})
        except Exception as exc:
            result.append({"udid": device.serial, "name": "Untrusted iPhone", "version": "unknown",
                           "ready": False, "error": str(exc)})
    emit({"devices": result})


async def enable_developer_mode(udid):
    """Use the same AMFI flow as upstream's amfi enable-developer-mode CLI."""
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.amfi import AmfiService
    from pymobiledevice3.exceptions import DeviceHasPasscodeSetError

    async with await create_using_usbmux(serial=udid, autopair=False) as lockdown:
        if not lockdown.has_developer_mode or await lockdown.get_developer_mode_status():
            emit({"enabled": True})
            return
        try:
            await AmfiService(lockdown).enable_developer_mode()
        except DeviceHasPasscodeSetError as exc:
            raise RuntimeError("iOS refused automatic enabling because a passcode is set. Enable Developer Mode in Settings → Privacy & Security, restart, and confirm Turn On. Your passcode has not been changed.") from exc
    # The AMFI flow reconnects internally; independently verify the selected phone.
    async with await create_using_usbmux(serial=udid, autopair=False) as lockdown:
        if not await lockdown.get_developer_mode_status():
            raise RuntimeError("Developer Mode is still off. Confirm Turn On after the restart, unlock your iPhone, and press Refresh.")
    emit({"enabled": True})


async def serve(udid):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    from pymobiledevice3.services.simulate_location import DtSimulateLocation
    from pymobiledevice3.exceptions import InvalidServiceError

    async with AsyncExitStack() as stack:
        dvt = None
        lockdown = await stack.enter_async_context(await create_using_usbmux(serial=udid, autopair=False))
        if lockdown.has_developer_mode and not await lockdown.get_developer_mode_status():
            raise RuntimeError("Developer Mode is off. Enable Settings → Privacy & Security → Developer Mode, restart, confirm Turn On, then unlock and reconnect your iPhone.")
        if int(lockdown.product_version.split(".")[0]) >= 17:
            provider = await stack.enter_async_context(PreferredRsdTunnel(serial=udid, autopair=False))
            try:
                dvt = await stack.enter_async_context(DvtProvider(provider))
            except InvalidServiceError as exc:
                raise RuntimeError("Developer location service unavailable. Mount the developer disk image using the mounter auto-mount command in README.md, then retry.") from exc
            location = await stack.enter_async_context(LocationSimulation(dvt))
        else:
            location = DtSimulateLocation(lockdown)
        emit({"ready": True})
        reader = asyncio.StreamReader()
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        disconnected = asyncio.create_task(dvt.dtx.wait_disconnected()) if dvt else None
        simulated = False
        try:
            while True:
                read = asyncio.create_task(reader.readline())
                pending = {read, disconnected} if disconnected else {read}
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if disconnected and disconnected.done():
                    read.cancel()
                    with suppress(asyncio.CancelledError):
                        await read
                    raise ConnectionError("iPhone developer session disconnected")
                line = await read
                if not line:
                    break
                command = json.loads(line)
                if command["action"] == "set":
                    await asyncio.wait_for(location.set(command["latitude"], command["longitude"]), 20)
                    simulated = True
                elif command["action"] == "clear":
                    await asyncio.wait_for(location.clear(), 20)
                    simulated = False
                else:
                    raise ValueError("Unknown action")
                emit({"ok": True})
        finally:
            transport.close()
            if disconnected:
                disconnected.cancel()
                with suppress(asyncio.CancelledError):
                    await disconnected
            if simulated:
                try:
                    await asyncio.wait_for(location.clear(), 5)
                except Exception as exc:
                    print(f"Could not restore location on exit: {exc}", file=sys.stderr)


if __name__ == "__main__":
    try:
        if sys.argv[1] == "list":
            operation = discover()
        elif sys.argv[1] == "enable-developer-mode":
            operation = enable_developer_mode(sys.argv[2])
        else:
            operation = serve(sys.argv[2])
        asyncio.run(operation)
    except Exception as exc:
        emit({"error": f"{type(exc).__name__}: {exc}"})
        sys.exit(1)
