# Location Switch

A small local browser UI to set a connected iPhone's simulated GPS location to an address or coordinates, then switch back to its real GPS. Built with [pymobiledevice3](https://github.com/doronz88/pymobiledevice3), FastAPI, and plain HTML/CSS/JavaScript. This is a standalone Git repository, not a fork.

## Download for Mac or Windows

Download the appropriate ZIP from [GitHub Releases](https://github.com/Dankcode/location-switch/releases/latest): **mac-arm64** for Apple Silicon, **mac-intel** for Intel Macs, or **windows-x64** for Windows 10/11. Extract the entire ZIP, then double-click **start.command** (Mac) or **LocationSwitch.exe** (Windows). Python and dependencies are included. The local browser panel opens automatically; keep the console open. These builds are unsigned. Complete your operating system's normal approval flow if prompted.

On Windows, install [Apple Devices](https://support.apple.com/guide/devices-windows/welcome/windows) first for Apple's USB drivers, then connect, unlock and Trust the iPhone. The downloads automatically mount the developer image on first spoof when needed. Internet is required for that first download. Windows builds receive automated startup/IPC checks; physical iPhone validation on Windows is pending.

## Run from source on your Mac

Install uv, then double-click **start.command**, or from this directory run:

```sh
./start.command
```

The launcher uses [uv](https://docs.astral.sh/uv/getting-started/installation/), installs the locked dependencies if needed, and opens **http://127.0.0.1:8765**. It requires Python 3.11+ (uv can provide Python). Keep the terminal window running. If an instance is already running, use its existing browser tab rather than starting a second instance.

For **Linux / Raspberry Pi Zero 2 W**, use `./scripts/install-linux.sh`, then `./start.sh --no-browser --low-memory --phone-access --auto-reveal --auto-mount`. Read [the Pi guide](docs/raspberry-pi.md) for 64-bit OS requirements, USB OTG wiring, Safari access through USB Personal Hotspot/Wi-Fi, password setup, iOS tunnel differences and systemd startup. Pi hardware validation is pending.

## Prepare the iPhone

1. Connect it by USB, unlock it, and tap **Trust** when asked. If Trust is not prompted, connect once through Finder. Press Refresh in the app.
2. Press **Enable Dev Mode** in the app. **Xcode is not required:** the app first uses pymobiledevice3's AMFI reveal action to expose the Settings toggle, then tries its enable flow. This may restart the selected phone. Keep it connected and unlock it after the restart. The page polls progress and reports success only after Developer Mode is checked on the phone. If a passcode blocks automatic enabling, use the exposed **Settings → Privacy & Security → Developer Mode** toggle, restart, confirm **Turn On**, and press Refresh. The app does not alter your passcode. You can also enable it manually from the start (iOS 16+).
3. Mount the developer disk image once per boot if it isn't already mounted by Xcode. From this repository:

   ```sh
   uv run --frozen python -m pymobiledevice3 usbmux list
   uv run --frozen python -m pymobiledevice3 mounter auto-mount --udid YOUR_DEVICE_UDID
   ```

   Replace `YOUR_DEVICE_UDID` with the `UniqueDeviceID` from the first command. The image mount may download files and contact Apple's personalization service. iOS below 17 may require a compatible Xcode developer image. The app surfaces errors when Developer Mode or the image is missing.

The pinned upstream API uses a persistent **PreferredRsdTunnel** for iOS 17+, with its no-root transport selection on macOS. Older iOS versions use `DtSimulateLocation` over lockdown. See [upstream tunnel requirements](https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/) for other hosts and early iOS 17 limitations. On Windows or Linux with iOS 17.0–17.3.1, start a privileged `tunneld` first. In a standalone download, run `LocationSwitch.exe --pymobiledevice3 remote tunneld` (Windows, Administrator terminal) or `./LocationSwitch --pymobiledevice3 remote tunneld` (Mac, if needed). Source users can run `uv run --frozen python -m pymobiledevice3 remote tunneld`.

Developer Mode setup runs in a separate worker using the same `AmfiService.enable_developer_mode()` API as upstream's `amfi enable-developer-mode` command, including its reconnect/post-restart confirmation flow. The operation is limited to three minutes; after a timeout, check the phone's final confirmation, unlock it, and press Refresh. An already-enabled phone is detected without restarting it. Setup is disabled during an active spoof; restore first. The developer disk image remains a separate setup step. Stopping the server interrupts any pending host-side setup; check the phone's state manually afterward.

## Switch locations

1. Select the connected iPhone.
2. Search a full address (include city and country) and select the matching result, or enter **WGS84 latitude / longitude** directly.
3. Click **Spoof location**. The status changes only after pymobiledevice3 completes the set operation.
4. Click **Real location** to send the stop-simulation command. The destination fields remain ready, so you can click Use spoofed location again.

**Gentle drift** is optional: select it before pressing Spoof location for slow changes within 3 meters of the chosen coordinates, updated every 5 seconds with a maximum step of 0.5 meters. The selected destination stays fixed; the status shows the last acknowledged simulated position. Press Real location to stop drift and clear simulation, or uncheck drift and press Spoof location again for a fixed point. Drift stops on a worker error or server shutdown. This varies coordinates only; it does not add GPS accuracy, altitude or other sensor signals, and does not guarantee acceptance by third-party apps.

The connection stays open for fast subsequent switches. Initial connection/tunnel setup can take several seconds; app location updates also depend on iOS and each app's refresh behavior. The page polls session status every two seconds. Device discovery is shared, serialized and cached for 20 seconds (60 in low-memory mode); manual Refresh forces a scan. There is no guaranteed instantaneous switch across every iPhone app.

**Real location means simulation is cleared.** This tool does not read the iPhone's live GPS, and does not substitute the Mac/browser position. Status reflects command completion and connection state, not an independent measurement of the iPhone's GPS. On DVT, the clear operation sends a stop command without a device reply, matching upstream's API.

One device can be active at a time. Restore it before switching to another. If the device disconnects, status becomes unknown; reconnect and press Restore real location. Normal server shutdown attempts restoration, but unplugging, force-quitting, or a crash cannot guarantee that cleanup. Close the simulation explicitly before disconnecting. If recovery fails, restart the iPhone and check its location in Maps.

## Address search and privacy

**Show map** opens an optional [Leaflet 1.9.4](https://leafletjs.com/) map, bundled locally with its license. It is collapsed by default and the library/tiles are not loaded until you open it. Click the map to select coordinates; this does not apply a spoof until you press Spoof location. Closing it removes the map and tile layers. Map rendering runs in the browser, not on the Pi.

Viewing a map sends the visible area's tile requests to OpenStreetMap. Attribution is visible; the browser honors tile caching and no offline downloading/prefetching is provided, following the [OSM tile policy](https://operations.osmfoundation.org/policies/tiles/). Public tiles have no availability guarantee. To select a different HTTPS OSM-derived tile service without updating code, set `LOCATION_TILE_URL` to a `{z}/{x}/{y}` tile URL. Coordinate entry works without the map.

Search uses [Photon](https://github.com/komoot/photon)'s public demo API, with explicit searches, a one-request-per-second limit and an in-memory cache. It needs internet access and has no availability guarantee. Results are from [OpenStreetMap contributors](https://www.openstreetmap.org/copyright). Verify the selected address and coordinates; coverage and building precision vary. For locations in China, enter WGS84 coordinates rather than GCJ-02 or BD-09 coordinates from local map providers.

Address search text is sent to Photon. Direct coordinate entry does not use a geocoding service. The last selected destination is saved in this browser's local storage. The default Mac/local server binds to loopback. Opt-in phone mode listens on the Pi interfaces and requires a panel password. Both modes reject foreign hosts, and requires an origin check and page token for POST requests. There is no hosted service or account.

To use your own Photon endpoint without modifying code:

```sh
PHOTON_URL=http://127.0.0.1:2322/api/ ./start.command
```

## Develop and test

```sh
uv sync --extra dev --frozen
uv run --extra dev --frozen python -m pytest -q
uv run --frozen python -m uvicorn location_switch.server:app --host 127.0.0.1 --port 8765
```

Keep a single server worker: device ownership and status are process-local. Do not enable reload while a simulation is active.

Tests cover coordinate limits, mutation authorization, command dispatch, acknowledgment timing, failure state, device switching, geocoding order/cache, and search outages. Browser QA covers the disconnected state, real public-landmark search, destination selection, coordinate editing, a simulated-device set/restore flow, and mobile layout. A connected iPhone was detected late in development; the first physical set attempt was blocked by Developer Mode being off and the developer image not being mounted. See `docs/validation.md` for the current verification limits.

## Repository structure

- `location_switch/server.py`: local HTTP routes and request protection.
- `location_switch/device.py`: serialized IPC and device/session state.
- `location_switch/worker.py`: isolated persistent pymobiledevice3 connection.
- `location_switch/geocode.py`: Photon lookup, throttling and cache.
- `location_switch/static/`: UI, with no frontend build step.
- `docs/`: setup and validation notes.
- `packaging/`: standalone entry, build specification, and smoke checks.
- `.github/workflows/release.yml`: native Mac/Windows builds and release ZIPs.

The dependency is pinned to upstream Git commit `3a173489266e23b5574a89b3c152fb290b760024` for its current async API, and all dependencies are locked in `uv.lock`. This project is licensed under GPL-3.0-or-later; see `LICENSE`. pymobiledevice3 is copyright its upstream contributors, listed in its repository.
