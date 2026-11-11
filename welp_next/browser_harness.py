"""HelicopterBench browser verification harness (SPEC §4.11).

Runs a submitted HTML5 helicopter game inside a disposable bubblewrap
sandbox and verifies REQUIRED GAMEPLAY BEHAVIOR through the Chrome DevTools
Protocol — never source inspection. Isolation: isolated mount namespace
(host root never mounted; only read-only runtime trees), isolated
user/pid/ipc namespaces, isolated NETWORK namespace (loopback is raised
inside the namespace; no external network exists at all), fresh tmpfs for
the browser profile, no environment inheritance, and a hard host-side
wall-clock timeout (fail-closed). A small self-contained CDP driver runs
INSIDE the same namespace, launches the browser binary itself, drives real
input events, samples game state and frames, and writes one bounded JSON
result to a host-opened capture file.

The frozen submission contract requires an instrumentation hook:
``window.__HELICOPTER_STATE__`` with {y, vy?, score, crashed, gameOver,
difficulty, distance, obstacles:[{x}...]} updated per frame, and restart on
a click after game over. This makes every required mechanic mechanically
verifiable for ANY conforming implementation without reading its source.
Visual quality/playability (the 10-point category) is qualitative-review
only; the harness only records screenshot evidence for it.

All environment failures (browser missing, sandbox denied, driver timeout)
return an explicit environment-error record — a technical INVALID, never a
model outcome.
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

DRIVER_PATH = Path(__file__).resolve().parent / "heli_cdp_driver.py"

BROWSER_CANDIDATES = ("brave-browser-stable", "brave-browser", "chromium",
                      "chromium-browser", "google-chrome-stable", "google-chrome")

# Frozen observation schedule (seconds, wall clock inside the namespace):
T_LOAD_SETTLE = 1.0
T_LIVELINESS_WINDOW = 0.8
T_FLY_WINDOW = 6.0          # score/difficulty/obstacle observation window
T_GRAVITY_SAMPLE = 1.2      # held vs released altitude sampling


def find_browser():
    for name in BROWSER_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Minimal RFC 6455 WebSocket client (stdlib only; text frames, masked sends)


class WsClient:
    def __init__(self, host, port, path="/"):
        import base64
        import socket
        self._sock = socket.create_connection((host, port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self._sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self._sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise OSError("websocket upgrade refused")
        self._buf = b""
        self._next_id = 0

    def send(self, payload: dict):
        data = json.dumps(payload).encode()
        header = bytearray([0x81])
        length = len(data)
        mask = os.urandom(4)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self._sock.sendall(bytes(header) + masked)

    def _read_exact(self, count):
        while len(self._buf) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise OSError("websocket closed")
            self._buf += chunk
        result, self._buf = self._buf[:count], self._buf[count:]
        return result

    def recv(self):
        first = self._read_exact(2)
        opcode = first[0] & 0x0F
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        payload = self._read_exact(length)
        if opcode == 0x8:
            raise OSError("websocket closed by peer")
        if opcode == 0x9:  # ping -> handled implicitly by not crashing
            return self.recv()
        return json.loads(payload.decode())

    def call(self, method, params=None, timeout=15.0):
        self._next_id += 1
        message_id = self._next_id
        self.send({"id": message_id, "method": method,
                   "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"CDP call timed out: {method}")
            message = self.recv()
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"CDP error {method}: {message['error']}")
                return message.get("result", {})
            # events are dropped here; the driver enables them separately


# ---------------------------------------------------------------------------
# Sandbox launch


import socket  # noqa: E402  (used above and below)


def verify_game(html_bytes: bytes, *, browser_binary: str,
                work_root: Path, timeout_seconds: float = 120.0,
                driver_source: str | None = None) -> dict:
    """Verify one submitted artifact; returns the frozen verification record.
    Environment failures return {'environment_error': reason} — never a
    model outcome."""
    if driver_source is None:
        driver_source = DRIVER_PATH.read_text()
    # Resolve the browser to its REAL file (brave/chromium are often
    # /usr/bin symlinks into /opt); its resource directory is bound read-only
    # at the IDENTICAL path so internal relative lookups keep working.
    resolved = Path(shutil.which(browser_binary) or browser_binary)
    real = Path(os.path.realpath(resolved))
    browser_binary = str(real)
    browser_dir = str(real.parent)
    scratch = Path(tempfile.mkdtemp(dir=work_root, prefix="heli-verify-"))
    result_path = scratch / "verification-result.json"
    result_fd = os.open(result_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    work = scratch / "work"
    work.mkdir()
    (work / "game.html").write_bytes(html_bytes)
    driver_file = scratch / "driver.py"
    driver_file.write_text(driver_source)
    profile = scratch / "browser-profile"
    profile.mkdir()
    argv = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/sbin", "/sbin",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--ro-bind", "/etc/fonts", "/etc/fonts",
        "--ro-bind", browser_dir, browser_dir,
        "--ro-bind", str(work), "/work",
        "--bind", str(profile), "/profile",
        "--bind-fd", str(result_fd), "/out/result.json",
        "--chdir", "/tmp",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/tmp",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONUNBUFFERED", "1",
        "--",
        "python3", "-",
        "/work/game.html", "/out/result.json", browser_binary,
    ]
    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv, input=driver_source.encode(), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=timeout_seconds, cwd=str(scratch),
            pass_fds=(result_fd,), env={"PATH": "/usr/bin"})
        elapsed = time.monotonic() - start
    except subprocess.TimeoutExpired:
        os.close(result_fd)
        return {"environment_error": f"verification timeout after {timeout_seconds}s",
                "sandbox": "bwrap"}
    os.close(result_fd)
    if not result_path.exists():
        return {"environment_error": "verification produced no result capture",
                "sandbox": "bwrap", "returncode": completed.returncode}
    try:
        record = json.loads(result_path.read_text())
    except ValueError:
        return {"environment_error": "unreadable verification result", "sandbox": "bwrap"}
    record["sandbox"] = "bwrap"
    record["isolation"] = {"mount": "host-root-not-mounted", "network": "namespace-loopback-only",
                           "environment": "cleared", "pid_ipc_uts": "namespaced"}
    record["elapsed_seconds"] = round(elapsed, 3)
    return record
