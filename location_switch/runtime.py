"""Launch isolated workers from either Python source or a standalone build."""
import sys


def worker_command(*args):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", *args]
    return [sys.executable, "-m", "location_switch.worker", *args]
