"""Validate packaged UI and isolated IPC dispatch without an attached phone."""
import json
import os
import tempfile
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

task_state = tempfile.TemporaryDirectory()
os.environ["LOCATION_DATA_DIR"] = task_state.name
exe = str(Path(sys.argv[1]).resolve())
subprocess.run([exe, '--help'], check=True, stdout=subprocess.DEVNULL, timeout=60)
subprocess.run([exe, '--pymobiledevice3', '--help'], check=True, stdout=subprocess.DEVNULL, timeout=60)
# Invalid worker input must return worker JSON, never open another UI/server.
worker = subprocess.run([exe, '--worker', 'serve'], capture_output=True, timeout=60)
assert worker.returncode == 1
assert 'error' in json.loads(worker.stdout.decode().strip().splitlines()[-1])
process = subprocess.Popen([exe, '--no-browser', '--port', '18765'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read().decode(errors='replace'))
        try:
            with urlopen('http://127.0.0.1:18765/', timeout=1) as response:
                assert b'Location Switch' in response.read()
            with urlopen('http://127.0.0.1:18765/static/vendor/leaflet/leaflet.js', timeout=1) as response:
                assert response.status == 200
            print('Packaged CLI, worker IPC, UI, and map assets passed.')
            break
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError('Packaged server did not become ready')
finally:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
