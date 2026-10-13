"""Standalone entry; workers reuse this executable without spawning another UI."""
import multiprocessing
import os
from pathlib import Path
import runpy
import sys


def main():
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    if args and args[0] == "--worker":
        from location_switch.worker import main as worker_main
        worker_main(args[1:])
        return
    if args and args[0] == "--pymobiledevice3":
        sys.argv = [sys.argv[0], *args[1:]]
        runpy.run_module("pymobiledevice3", run_name="__main__")
        return
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        else:
            base = Path.home() / "Library/Application Support"
        state = Path(os.environ["LOCATION_DATA_DIR"]) if os.getenv("LOCATION_DATA_DIR") else base / "Location Switch"
        state.mkdir(parents=True, exist_ok=True)
        os.chdir(state)
        if "--auto-mount" not in args:
            args.append("--auto-mount")
    from location_switch.__main__ import main as app_main
    app_main(args)


if __name__ == "__main__":
    main()
