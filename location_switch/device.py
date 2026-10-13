import asyncio
import json
import sys
from contextlib import suppress


class DeviceError(RuntimeError):
    pass


class DeviceController:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.process = None
        self.udid = None
        self.mode = "unknown"
        self.destination = None
        self.error = None
        self.stderr_task = None
        self.diagnostics = ""
        self.setup = {"state": "idle", "udid": None, "message": ""}
        self.setup_task = None
        self.setup_process = None

    async def devices(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "location_switch.worker", "list",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 12)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise DeviceError("Device discovery timed out. Unlock your iPhone and check the USB cable.")
        try:
            reply = json.loads(stdout.decode().strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise DeviceError(stderr.decode()[-1200:] or "Could not discover devices.")
        if reply.get("error") or process.returncode:
            raise DeviceError(reply.get("error", "Device discovery failed."))
        return reply["devices"]

    def status(self):
        if self.process and self.process.returncode is not None:
            self.mode = "unknown"
            self.error = "Device session ended. Reconnect and restore real location to confirm recovery."
        return {"mode": self.mode, "udid": self.udid, "destination": self.destination,
                "error": self.error, "developer_setup": self.setup.copy()}

    async def enable_developer_mode(self, udid):
        async with self.lock:
            if self.setup["state"] == "enabling":
                raise DeviceError("Developer Mode setup is already running. Wait for the iPhone to reconnect.")
            if self.mode == "spoofed":
                raise DeviceError("Restore real location before enabling Developer Mode, which may restart the iPhone.")
            if self.udid and self.udid != udid and self.mode != "real":
                raise DeviceError("Reconnect and restore the current iPhone before setting up another device.")
            await self._close()
            if self.mode == "real":
                self.udid = None
            self.mode = "unknown"
            self.error = None
            self.setup = {"state": "enabling", "udid": udid,
                          "message": "Requesting Developer Mode. Your iPhone may restart; keep it connected and unlock it after restarting."}
            self.setup_task = asyncio.create_task(self._enable_in_background(udid))
            return self.setup.copy()

    async def _enable_command(self, udid):
        self.setup_process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "location_switch.worker", "enable-developer-mode", udid,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(self.setup_process.communicate(), 180)
            try:
                result = json.loads(stdout.decode().strip().splitlines()[-1])
            except (ValueError, IndexError):
                raise DeviceError(stderr.decode(errors="replace")[-1200:] or "Developer Mode setup failed.")
            if result.get("error") or self.setup_process.returncode or result.get("enabled") is not True:
                raise DeviceError(result.get("error", "The phone did not confirm Developer Mode is enabled."))
        except asyncio.TimeoutError as exc:
            raise DeviceError("Setup timed out waiting for the iPhone. Unlock it, confirm Turn On after restarting, and press Refresh to check its status.") from exc
        finally:
            if self.setup_process.returncode is None:
                self.setup_process.kill()
                await self.setup_process.communicate()
            self.setup_process = None

    async def _enable_in_background(self, udid):
        try:
            await self._enable_command(udid)
            self.setup = {"state": "enabled", "udid": udid,
                          "message": "Developer Mode enabled and verified. Mount the developer disk image if needed before spoofing."}
        except asyncio.CancelledError:
            self.setup = {"state": "error", "udid": udid,
                          "message": "Setup interrupted. Unlock your iPhone and check Developer Mode in Settings."}
            raise
        except Exception as exc:
            self.setup = {"state": "error", "udid": udid, "message": str(exc)}

    async def _drain_stderr(self):
        while data := await self.process.stderr.read(1024):
            self.diagnostics = (self.diagnostics + data.decode(errors="replace"))[-2000:]

    async def _read(self):
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), 45)
            reply = json.loads(line)
        except (asyncio.TimeoutError, ValueError):
            raise DeviceError(self.diagnostics or "Device did not respond. Check Trust, Developer Mode, and the developer disk image.")
        if "error" in reply:
            raise DeviceError(reply["error"])
        return reply

    async def _close(self):
        if self.process:
            if self.process.returncode is None:
                self.process.stdin.close()  # worker attempts clear before teardown
                try:
                    await asyncio.wait_for(self.process.wait(), 8)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            if self.stderr_task:
                await self.stderr_task
            self.process = None

    async def change(self, udid, action, latitude=None, longitude=None, label=None):
        async with self.lock:
            if self.setup["state"] == "enabling":
                raise DeviceError("Wait for Developer Mode setup to finish before changing location.")
            if self.udid and self.udid != udid and self.mode != "real":
                raise DeviceError("Restore real location on the current device before selecting another iPhone.")
            try:
                if not self.process or self.process.returncode is not None or self.udid != udid:
                    await self._close()
                    self.udid = udid
                    self.mode = "unknown"
                    self.diagnostics = ""
                    self.process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "location_switch.worker", "serve", udid,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE)
                    self.stderr_task = asyncio.create_task(self._drain_stderr())
                    if not (await self._read()).get("ready"):
                        raise DeviceError("Device session could not start.")
                command = {"action": action, "latitude": latitude, "longitude": longitude}
                self.process.stdin.write((json.dumps(command) + "\n").encode())
                await self.process.stdin.drain()
                if not (await self._read()).get("ok"):
                    raise DeviceError("The device did not accept the command.")
                self.mode = "spoofed" if action == "set" else "real"
                self.destination = {"latitude": latitude, "longitude": longitude, "label": label} if action == "set" else None
                self.error = None
                return self.status()
            except Exception as exc:
                self.mode = "unknown"
                self.error = str(exc)
                await self._close()
                raise DeviceError(str(exc)) from exc

    async def shutdown(self):
        if self.setup_task and not self.setup_task.done():
            self.setup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.setup_task
        async with self.lock:
            if self.process and self.process.returncode is None and self.mode == "spoofed":
                with suppress(Exception):
                    self.process.stdin.write(b'{"action":"clear"}\n')
                    await self.process.stdin.drain()
                    await self._read()
            await self._close()
