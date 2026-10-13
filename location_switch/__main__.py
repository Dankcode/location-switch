import argparse
import os
import platform
import secrets
from pathlib import Path
import threading
import webbrowser

import uvicorn


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local iPhone location utility")
    parser.add_argument("--port", type=int, default=8765)
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument("--browser", action="store_true", help="Open a desktop browser")
    browser.add_argument("--no-browser", action="store_true", help="Run headless")
    parser.add_argument("--low-memory", action="store_true", help="Cache device discovery for 60 seconds")
    parser.add_argument("--tunnel", choices=["auto", "tunneld"], default="auto")
    parser.add_argument("--phone-access", action="store_true", help="Serve the phone over USB hotspot/Wi-Fi with a password")
    parser.add_argument("--auto-reveal", action="store_true", help="Request Trust and reveal Developer Mode on a single newly connected iPhone")
    parser.add_argument("--auto-mount", action="store_true", help="Download/mount the developer image when starting location simulation")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.low_memory:
        os.environ["LOCATION_DISCOVERY_TTL"] = "60"
    os.environ["LOCATION_TUNNEL"] = args.tunnel
    if args.auto_reveal:
        os.environ["LOCATION_AUTO_REVEAL"] = "1"
    if args.auto_mount:
        os.environ["LOCATION_AUTO_MOUNT"] = "1"
        os.environ.setdefault("LOCATION_COMMAND_TIMEOUT","600")
    if args.phone_access:
        key_file = Path("state/access-key")
        if not os.getenv("LOCATION_ACCESS_KEY"):
            key_file.parent.mkdir(mode=0o700, exist_ok=True)
            try:
                fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = key_file.read_text().strip()
            else:
                with os.fdopen(fd,"w") as stream:
                    key = secrets.token_urlsafe(18)
                    stream.write(key + "\n")
            os.environ["LOCATION_ACCESS_KEY"] = key
        if len(os.environ["LOCATION_ACCESS_KEY"]) < 12:
            parser.error("LOCATION_ACCESS_KEY must be at least 12 characters")
        os.environ["LOCATION_PHONE_ACCESS"] = "1"
        print("Phone panel: http://<Pi USB or Wi-Fi IP>:" + str(args.port), flush=True)
        print("Login: location. Password: LOCATION_ACCESS_KEY or state/access-key.", flush=True)
    if not args.no_browser and (args.browser or platform.system() in ("Darwin", "Windows")):
        timer = threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}"))
        timer.daemon = True
        timer.start()
    print(f"Location Switch: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run("location_switch.server:app", host="0.0.0.0" if args.phone_access else "127.0.0.1", port=args.port, workers=1, loop="asyncio", log_level="warning")


if __name__ == "__main__":
    main()
