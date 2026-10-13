import asyncio
import json
import os
import time
from contextlib import suppress
from .runtime import worker_command


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
        self.discovery_lock = asyncio.Lock()
        self.discovery_cache = None
        self.discovery_time = 0
        self.discovery_ttl = float(os.getenv("LOCATION_DISCOVERY_TTL", "20"))
        self.revealed_devices = set()
        self.pairing_attempted = set()
        self.operation_message = None

    async def devices(self, force=False):
        async with self.discovery_lock:
            if not force and self.discovery_cache is not None and time.monotonic() - self.discovery_time < self.discovery_ttl:
                return self.discovery_cache
            self.discovery_cache = await self._discover()
            self.pairing_attempted.intersection_update(device["udid"] for device in self.discovery_cache)
            if os.getenv("LOCATION_AUTO_REVEAL") == "1" and len(self.discovery_cache) == 1:
                device = self.discovery_cache[0]
                if not device.get("ready") and device["udid"] not in self.pairing_attempted and self.setup["state"] not in ("enabling","pairing"):
                    self.pairing_attempted.add(device["udid"])
                    try:
                        await self.pair_device(device["udid"])
                    except DeviceError as exc:
                        self.setup = {"state":"error","udid":device["udid"],"message":str(exc)}
                if device.get("ready") and device.get("developer_mode") is False and device["udid"] not in self.revealed_devices:
                    try:
                        await self._reveal(device["udid"])
                    except Exception as exc:
                        self.setup = {"state":"error","udid":device["udid"],"message":str(exc)}
                    else:
                        self.revealed_devices.add(device["udid"])
                        self.setup = {"state":"manual","udid":device["udid"],"message":"Developer Mode toggle revealed. Enable it in Settings → Privacy & Security, restart, and confirm Turn On. Xcode is not required."}
            self.discovery_time = time.monotonic()
            return self.discovery_cache

    async def _reveal(self, udid):
        async with self.lock:
            if self.mode == "spoofed" or self.setup["state"] in ("enabling","pairing"):
                raise DeviceError("Finish the active device operation before setup.")
            process = await asyncio.create_subprocess_exec(
                *worker_command("reveal-developer-mode", udid),
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(),30)
                reply = json.loads(stdout.decode().strip().splitlines()[-1])
                if process.returncode or reply.get("revealed") is not True:
                    raise DeviceError(reply.get("error") or stderr.decode(errors="replace")[-1000:] or "Could not reveal Developer Mode.")
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()

    async def _discover(self):
        process = await asyncio.create_subprocess_exec(
            *worker_command("list"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
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
                "error": self.error, "developer_setup": self.setup.copy(), "operation_message":self.operation_message}

    async def enable_developer_mode(self, udid):
        return await self._start_setup(udid,"enable-developer-mode")

    async def pair_device(self,udid):
        return await self._start_setup(udid,"pair")

    async def _start_setup(self, udid, action):
        async with self.lock:
            if self.setup["state"] in ("enabling","pairing"):
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
            self.setup = {"state": "pairing" if action == "pair" else "enabling", "udid": udid,
                          "message": "Unlock your iPhone and tap Trust to pair with this host." if action == "pair" else "Requesting Developer Mode. Your iPhone may restart; keep it connected and unlock it after restarting."}
            self.setup_task = asyncio.create_task(self._enable_in_background(udid,action))
            return self.setup.copy()

    async def _enable_command(self, udid, action="enable-developer-mode"):
        self.setup_process = await asyncio.create_subprocess_exec(
            *worker_command(action, udid),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(self.setup_process.communicate(), 180)
            try:
                result = json.loads(stdout.decode().strip().splitlines()[-1])
            except (ValueError, IndexError):
                raise DeviceError(stderr.decode(errors="replace")[-1200:] or "Developer Mode setup failed.")
            if result.get("error") or self.setup_process.returncode or result.get("paired" if action == "pair" else "enabled") is not True:
                raise DeviceError(result.get("error", "The phone did not confirm Developer Mode is enabled."))
        except asyncio.TimeoutError as exc:
            if action == "pair":
                raise DeviceError("Pairing timed out. Unlock your iPhone, tap Trust, and retry.") from exc
            raise DeviceError("Setup timed out waiting for the iPhone. Unlock it, confirm Turn On after restarting, and press Refresh to check its status.") from exc
        finally:
            if self.setup_process.returncode is None:
                self.setup_process.kill()
                await self.setup_process.communicate()
            self.setup_process = None

    async def _enable_in_background(self, udid, action="enable-developer-mode"):
        try:
            if action == "pair":
                await self._enable_command(udid,"pair")
            else:
                await self._enable_command(udid)
            self.discovery_cache = None
            self.setup = {"state": "paired" if action == "pair" else "enabled", "udid": udid,
                          "message": "iPhone paired. Press Refresh to check Developer Mode." if action == "pair" else "Developer Mode enabled and verified. Mount the developer disk image if needed before spoofing."}
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
            while True:
                line = await asyncio.wait_for(self.process.stdout.readline(), float(os.getenv("LOCATION_COMMAND_TIMEOUT", "90")))
                reply = json.loads(line)
                if not reply.get("progress"):
                    break
                self.operation_message = reply["progress"]
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
            if self.setup["state"] in ("enabling","pairing"):
                raise DeviceError("Wait for Developer Mode setup to finish before changing location.")
            if self.udid and self.udid != udid and self.mode != "real":
                raise DeviceError("Restore real location on the current device before selecting another iPhone.")
            try:
                self.operation_message = "Connecting to iPhone…"
                if not self.process or self.process.returncode is not None or self.udid != udid:
                    await self._close()
                    self.udid = udid
                    self.mode = "unknown"
                    self.diagnostics = ""
                    self.process = await asyncio.create_subprocess_exec(
                        *worker_command("serve", udid),
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
            finally:
                self.operation_message = None

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
