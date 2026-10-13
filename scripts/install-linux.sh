#!/bin/sh
# Run on the Pi as your normal user. Installs system USB support and locked Python dependencies.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ "$(uname -s)" != Linux ]; then
    printf '%s\n' 'This installer is for Linux. On macOS use uv sync --frozen.'
    exit 1
fi
case "$(uname -m)" in
    aarch64|x86_64) ;;
    *) printf '%s\n' 'Use a 64-bit Linux OS. Pi Zero 2: Raspberry Pi OS Lite (64-bit).'; exit 1 ;;
esac
if [ "$(id -u)" = 0 ]; then
    printf '%s\n' 'Run as your normal user, not root; sudo is used only for system packages.'
    exit 1
fi
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev git usbmuxd libimobiledevice-utils libusb-1.0-0 libssl-dev build-essential pkg-config avahi-daemon
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
python3 -m venv .bootstrap
.bootstrap/bin/python -m pip install 'uv>=0.8,<1'
.bootstrap/bin/uv sync --frozen --no-dev
sudo systemctl start usbmuxd
sudo modprobe ipheth
printf '%s\n' 'Installed. Connect the unlocked iPhone through a USB OTG data adapter and tap Trust.' './start.sh --no-browser --low-memory --phone-access --auto-reveal'
