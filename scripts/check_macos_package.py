"""Smoke-test the bundled backend without a development Python or source checkout."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
executable = ROOT / "build/Agent Sessions.app/Contents/Resources/backend/agent-sessions-server"
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]

with tempfile.TemporaryDirectory() as directory:
    process = subprocess.Popen([str(executable), "--demo", "--port", str(port)], cwd=directory,
        env={**os.environ, "PATH": "/usr/bin:/bin"}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode())
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/sessions", timeout=1) as response:
                    data = json.load(response)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        assert data["scope"] == "Demo data" and len(data["sessions"]) == 6
        assert data["version"] == (ROOT / "VERSION").read_text().strip()
        assert data["analytics"]["demo"] and not data["analytics"]["configured"]
        for path in ("/", "/app.js", "/sessions.mjs", "/analytics.mjs", "/styles.css"):
            with urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                assert response.status == 200 and response.read()
        print("Bundled Mac runtime serves fictional sessions and dashboard assets without external Python.")
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stderr.close()
