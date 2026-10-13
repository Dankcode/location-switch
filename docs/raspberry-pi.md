# Linux / Raspberry Pi Zero 2 W

Target: **Raspberry Pi OS Lite 64-bit**, Python 3.11+, iPhone over USB. The Zero 2 W has a 64-bit Cortex-A53 CPU and 512 MB RAM ([specifications](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)). Use it as a headless server and open the UI in Safari on the connected iPhone, or in a laptop browser. No desktop, Chromium, Xcode, Docker, Node.js, or local map/geocoding server is needed on the Pi.

This repository now has portable POSIX launch/install scripts, single-worker headless mode, cached discovery, early-iOS-17 Linux tunnel routing, and a user systemd service. **Physical Pi runtime, USB stability and memory use have not yet been validated.** Linux ARM64/Python 3.11 and 3.13 dependency resolution was checked against the exact lockfile, including prebuilt AV, cryptography, qh3, and pydantic-core wheels. That verifies package availability, not hardware performance. An Ubuntu test workflow is provided for future pushes; it has not been dispatched from this local repository.

## Connect the phone

- Power the Pi using its power port and a suitable supply.
- The Zero 2 W has **micro-USB**, not USB-C. Use its **USB data/OTG port**, a micro-USB OTG host adapter and a USB-A-to-USB-C data cable to the iPhone. Do not configure this port as a USB gadget at the same time.
- A powered USB hub may be necessary if iPhone charging causes undervoltage, disconnects, or reboots. Verify USB discovery with `lsusb` before debugging the app.
- Unlock the iPhone and Trust the Pi. Pair records are host-specific: trusting your Mac does not pair your Pi.

## Install

Copy the source to `~/location-switch` on the Pi, excluding the Mac `.venv`, `.bootstrap`, caches and `.git` directories. For example, from this repo on your Mac, replace the SSH destination with your actual Pi user/host:

```sh
rsync -av --exclude .venv --exclude .bootstrap --exclude .git --exclude __pycache__ --exclude .pytest_cache ./ pi@raspberrypi.local:location-switch/
```

On the Pi, as your normal user:

```sh
cd ~/location-switch
./scripts/install-linux.sh
./start.sh --no-browser --low-memory --phone-access --auto-reveal --auto-mount
```

The installer targets Debian/Raspberry Pi OS. It uses sudo for apt and usbmuxd, installs uv into a local bootstrap environment, and installs the locked app dependencies into `.venv`. It refuses a 32-bit OS so ARM dependencies can use existing wheels. usbmuxd is commonly udev-activated; the installer starts it without trying to enable its static systemd unit.

Allow time for installation on the small CPU. The upstream dependency set is broad even though this app only imports the location/device APIs it uses. Keep space on the SD card for the Python environment, package caches and developer image downloads. If a native package must compile, low-memory builds may need temporary swap; prefer the verified wheel path rather than building AV/FFmpeg locally.

## Open in Safari on the same iPhone

USB device control and network access are separate. A cable alone does not give Safari a route to the Pi. The intended same-cable route is **iPhone Personal Hotspot over USB**, using Linux's `ipheth` Ethernet driver. The installer loads that driver. This path needs pairing/Trust and a carrier plan that supports Personal Hotspot ([Apple's hotspot guidance](https://support.apple.com/en-us/119837), [Linux ipheth driver](https://github.com/torvalds/linux/blob/master/drivers/net/usb/ipheth.c)). Its behavior with this exact Pi/iOS combination is still hardware-test pending.

One-time setup:

1. Start the supplied service or the full command above. Choose a panel password by placing at least 12 characters in `state/access-key` and making it private (`chmod 600 state/access-key`); if omitted, first startup creates a random key there. The login username is **location**. Read/save this password during installation so you can log in from the phone later. `LOCATION_ACCESS_KEY` can override it for a manually started instance.
2. Connect the iPhone to the OTG host adapter. Unlock it. With `--auto-reveal`, the Pi monitors devices and requests pairing when exactly one untrusted phone is connected; tap **Trust** and enter the phone's passcode. It then reveals the Developer Mode toggle without Xcode. On shared Wi-Fi you can also use the panel's **Pair iPhone** button.
3. On the iPhone, enable **Settings → Personal Hotspot → Allow Others to Join**. Keep a current Raspberry Pi OS/kernel for the USB Ethernet driver. NetworkManager normally obtains an address automatically. If needed, inspect `nmcli device status` and use `sudo nmcli device connect INTERFACE` for the actual iPhone USB Ethernet interface.
4. In Safari open **http://raspberrypi.local:8765** (use your Pi's actual hostname) or **http://PI_USB_IP:8765**. During installation, find its addresses with `hostname -I` or `nmcli -g IP4.ADDRESS device show INTERFACE`. Do not use `127.0.0.1` on the iPhone—that address refers to the phone itself. Hostname discovery over USB varies; the Pi's actual USB IP is the fallback.
5. Log in as **location** with the panel password. Finish Developer Mode in Settings if a passcode blocks automatic enabling; restart and confirm Turn On. Reconnect/enable hotspot again after restarting. Press **Spoof location** once ready; `--auto-mount` downloads/mounts the missing developer image on this first attempt and reports progress. Use Wi-Fi for the initial image download if you want to avoid cellular data use.

After one-time Trust, Developer Mode, network and password setup, later connections reuse pairing records and the cached image. The service starts with the Pi; a reconnect still needs the phone unlocked and hotspot/network available. Apple still requires the on-device confirmations—this does not silently bypass them. Automatic setup never reboots a phone merely because it was plugged in; the **Enable Dev Mode** button can request a reboot when supported.

If USB Personal Hotspot is unavailable, put the iPhone and Pi on the same Wi-Fi network and open the Pi's Wi-Fi address in Safari. The USB cable still carries the location-control connection. No public hosted service is required.

The phone-access option listens on the Pi's interfaces and protects every route with a password, the existing page token and the origin check. It accepts only the Pi's own interface addresses/hostname. The local Mac/default launcher remains loopback-only. Phone access is for a direct USB/private network; it is not an internet-facing deployment.

### Optional laptop access

For a loopback-only Pi instance, use an SSH tunnel from your laptop:

```sh
ssh -N -L 8766:127.0.0.1:8765 pi@raspberrypi.local
```

Open **http://127.0.0.1:8766** on the laptop. This also works with phone mode but still requires the panel password.

## Prepare iOS

The service handles Trust requests, toggle reveal, and image preparation. These manual diagnostic commands are also available from the repository on the Pi:

```sh
.venv/bin/python -m pymobiledevice3 usbmux list
.venv/bin/python -m pymobiledevice3 lockdown pair --udid YOUR_DEVICE_UDID
.venv/bin/python -m pymobiledevice3 mounter auto-mount --udid YOUR_DEVICE_UDID
```

Tap Trust when pairing asks. Use **Enable Dev Mode** in the app to reveal the Settings toggle without Xcode. If a passcode blocks automatic enabling, finish it on the phone, restart, confirm Turn On, unlock and press Refresh. Mount the developer disk image after enabling; `auto-mount` downloads/personalizes the appropriate image and can take time. The Pi needs internet access for this and address searches.

Transport support follows [upstream's iOS support matrix](https://doronz88.github.io/pymobiledevice3/guides/ios17-tunnels/):

| iOS | Linux transport |
| --- | --- |
| Below 17 | lockdown developer service |
| 17.0–17.3.1 | Privileged local tunneld required |
| 17.4+ | Root-free in-process userspace tunnel by default |

For early iOS 17 only, keep a local daemon running in another SSH session:

```sh
sudo .venv/bin/python -m pymobiledevice3 remote tunneld
```

The app routes early iOS 17 to that daemon automatically. For newer iOS you can explicitly reuse a local daemon with `./start.sh --no-browser --low-memory --tunnel tunneld`. The app connects only to the exact selected UDID.

## Start at login / boot

The supplied user service assumes the source is in `~/location-switch` and enables phone access, connection-time pairing/toggle reveal and automatic image preparation:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/location-switch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now location-switch
```

For startup without an SSH login, optionally run `sudo loginctl enable-linger "$USER"`. Check logs with `journalctl --user -u location-switch -f`; stop with `systemctl --user stop location-switch`. Stop a manually started instance before starting the service, to free port 8765. SIGINT shutdown attempts to restore an active spoof before exit.

## Memory and status behavior

- One HTTP worker and one active location worker; no frontend build/runtime process.
- Discovery is serialized and cached for 60 seconds in low-memory mode. All browser clients share that cache. Manual Refresh bypasses it. Normal mode uses 20 seconds.
- The status endpoint is cheap and polled every two seconds. Hidden tabs pause polling.
- The optional **Show map** loads the bundled Leaflet library and OSM tiles only on demand. Closing the map removes its DOM and tile layers. It uses no server-side renderer, no tile prefetching, and no WebGL.
- Device-list changes may take up to the cache interval to appear; the active developer session separately monitors disconnection. Manual Refresh gives an immediate new scan.

No specific RAM/CPU ceiling is promised until tested on your Pi. To inspect actual use, run `ps -eo pid,rss,cmd | sort -nk2 | tail` and `free -h` during a spoof session. Set `LOCATION_COMMAND_TIMEOUT` (seconds, default 90, or 600 with `--auto-mount`) if the Pi needs more connection time. Map tiles are best-effort; coordinates and spoof controls remain usable when tiles are unavailable.
