"""One isolated, persistent device connection; newline-delimited JSON IPC."""
import asyncio
import json
import sys
import os
import platform
import threading
from contextlib import AsyncExitStack, suppress


def emit(value):
    print(json.dumps(value), flush=True)


async def command_reader():
    if platform.system() != "Windows":
        reader = asyncio.StreamReader()
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        return reader, transport
    # Windows console/anonymous stdin handles cannot use connect_read_pipe.
    # A daemon reader lets disconnect/shutdown exit even while stdin is blocked.
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()

    def pump():
        try:
            for line in sys.stdin.buffer:
                loop.call_soon_threadsafe(reader.feed_data, line)
            loop.call_soon_threadsafe(reader.feed_eof)
        except (OSError, RuntimeError):
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(reader.feed_eof)

    threading.Thread(target=pump, daemon=True).start()
    return reader, None


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
                               "version": info.get("ProductVersion", "unknown"), "ready": bool(lockdown.paired),
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
        amfi = AmfiService(lockdown)
        await amfi.reveal_developer_mode_option_in_ui()
        try:
            await amfi.enable_developer_mode()
        except DeviceHasPasscodeSetError as exc:
            raise RuntimeError("The Developer Mode toggle has been revealed without Xcode. A passcode blocks automatic enabling: open Settings → Privacy & Security → Developer Mode, turn it on, restart, and confirm Turn On. Your passcode has not been changed.") from exc
    # The AMFI flow reconnects internally; independently verify the selected phone.
    async with await create_using_usbmux(serial=udid, autopair=False) as lockdown:
        if not await lockdown.get_developer_mode_status():
            raise RuntimeError("Developer Mode is still off. Confirm Turn On after the restart, unlock your iPhone, and press Refresh.")
    emit({"enabled": True})


async def reveal_developer_mode(udid):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.amfi import AmfiService
    async with await create_using_usbmux(serial=udid, autopair=False) as lockdown:
        await AmfiService(lockdown).reveal_developer_mode_option_in_ui()
    emit({"revealed":True})


async def pair_device(udid):
    from pymobiledevice3.lockdown import create_using_usbmux
    async with await create_using_usbmux(serial=udid,autopair=True,pair_timeout=120) as lockdown:
        if not lockdown.paired:
            raise RuntimeError("Unlock the iPhone and tap Trust, then retry pairing.")
    emit({"paired":True})


async def serve(udid):
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.simulate_location import DtSimulateLocation

    async with AsyncExitStack() as stack:
        dvt = None
        lockdown = await stack.enter_async_context(await create_using_usbmux(serial=udid, autopair=False))
        if lockdown.has_developer_mode and not await lockdown.get_developer_mode_status():
            raise RuntimeError("Developer Mode is off. Enable Settings → Privacy & Security → Developer Mode, restart, confirm Turn On, then unlock and reconnect your iPhone.")
        if int(lockdown.product_version.split(".")[0]) >= 17:
            from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
            provider = await open_developer_provider(stack, udid, lockdown.product_version)
            dvt = await prepare_dvt(stack,provider,udid,lockdown.product_version)
            location = await stack.enter_async_context(LocationSimulation(dvt))
        else:
            if os.getenv("LOCATION_AUTO_MOUNT") == "1":
                from pymobiledevice3.services.mobile_image_mounter import auto_mount
                from pymobiledevice3.exceptions import AlreadyMountedError
                emit({"progress":"Preparing developer image…"})
                with suppress(AlreadyMountedError):
                    await auto_mount(lockdown)
            location = DtSimulateLocation(lockdown)
        emit({"ready": True})
        reader, transport = await command_reader()
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
            if transport is not None:
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


async def prepare_dvt(stack, provider, udid, version):
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.exceptions import InvalidServiceError, AlreadyMountedError
    try:
        return await stack.enter_async_context(DvtProvider(provider))
    except InvalidServiceError as exc:
        if os.getenv("LOCATION_AUTO_MOUNT") != "1":
            raise RuntimeError("Developer location service unavailable. Mount the developer disk image using the mounter auto-mount command in README.md, then retry.") from exc
    from pymobiledevice3.services.mobile_image_mounter import auto_mount
    emit({"progress":"Preparing developer image. First setup may take several minutes."})
    with suppress(AlreadyMountedError):
        await auto_mount(provider)
    await stack.aclose()  # stop the old userspace stack before opening a new tunnel
    provider = await open_developer_provider(stack,udid,version)
    return await stack.enter_async_context(DvtProvider(provider))


async def open_developer_provider(stack, udid, version):
    """Early iOS 17 on Linux requires tunneld; newer iOS uses the root-free tunnel."""
    from packaging.version import Version
    transport = os.getenv("LOCATION_TUNNEL", "auto")
    if transport not in ("auto", "tunneld"):
        raise RuntimeError("LOCATION_TUNNEL must be auto or tunneld")
    early_non_mac = platform.system() in ("Linux", "Windows") and Version(version) < Version("17.4")
    if transport == "tunneld" or early_non_mac:
        from pymobiledevice3.tunneld.api import get_tunneld_device_by_udid
        provider = await get_tunneld_device_by_udid(udid)
        if provider is None:
            raise RuntimeError("No tunnel for this iPhone. Start pymobiledevice3 remote tunneld on this host, then retry.")
        stack.push_async_callback(provider.close)
        return provider
    from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
    return await stack.enter_async_context(PreferredRsdTunnel(serial=udid, autopair=False))


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if args[0] == "list":
            operation = discover()
        elif args[0] == "enable-developer-mode":
            operation = enable_developer_mode(args[1])
        elif args[0] == "reveal-developer-mode":
            operation = reveal_developer_mode(args[1])
        elif args[0] == "pair":
            operation = pair_device(args[1])
        else:
            operation = serve(args[1])
        asyncio.run(operation)
    except Exception as exc:
        emit({"error": f"{type(exc).__name__}: {exc}"})
        sys.exit(1)


if __name__ == "__main__":
    main()
