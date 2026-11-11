"""In-sandbox HelicopterBench CDP driver (runs INSIDE the bubblewrap
namespace; no host access, no external network — namespace loopback only).

Usage: python3 - <html_path> <result_path> <browser_binary>

Protocol (frozen with SPEC §4.11): load the artifact, then verify REQUIRED
BEHAVIOR through real CDP input events and the contract state object
(window.__HELICOPTER_STATE__ = {y, score, crashed, gameOver, difficulty,
distance, obstacles:[{x},...]} updated per frame; click restarts after game
over). Writes one bounded JSON record to <result_path>. Every check result
carries its evidence; environment failures are explicit. The game-over
visible-text check (methodology /2) credits only NEW rendered text that
appears exactly with the demonstrated game-over transition — wording is
irrelevant; always-visible text, hidden text and telemetry alone never
qualify.
"""
import json
import re
import sys
import time
from collections import Counter

sys.path.insert(0, "/usr/lib/python3/dist-packages")  # no-op safety

HTML_PATH, RESULT_PATH, BROWSER = sys.argv[1], sys.argv[2], sys.argv[3]

T_LOAD_SETTLE = 1.0
T_LIVELINESS = 0.8
T_FLY = 6.0
T_GRAVITY = 1.2
CDP_PORT = 9223


def _visible_lines(text):
    """Rendered-text lines normalized for game-over comparison: whitespace
    collapsed, casefolded, digits stripped. Digit stripping keeps
    continuously updating HUD/score/timer text ("distance 12 m" ->
    "distance 39 m") from masquerading as a new game-over indication; any
    genuinely new wording still differs."""
    lines = []
    for line in re.split(r"[\r\n]+", text or ""):
        norm = re.sub(r"\d+", "", re.sub(r"\s+", " ", line)).strip().lower()
        if norm:
            lines.append(norm)
    return lines


def log(record, **kwargs):
    record.update(kwargs)


def main():
    record = {"checks": {}, "environment": {}, "evidence": {}}
    import os
    import struct
    import fcntl
    import socket
    import subprocess

    # Loopback in a fresh bubblewrap network namespace is already UP (flags
    # observed 73 = UP|LOOPBACK|RUNNING). Raise it best-effort only if down:
    # an unprivileged mapping cannot SET flags (ioctl refuses), and failure
    # to raise while DOWN is a hard environment error, never a model outcome.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ifreq = struct.pack("16sH22s", b"lo", 0, b"")
        flags = struct.unpack("16sH22s", fcntl.ioctl(sock.fileno(), 0x8913, ifreq))[1]
        if not flags & 0x1:
            fcntl.ioctl(sock.fileno(), 0x8911, struct.pack("16sH22s", b"lo", flags | 0x1, b""))
            flags = struct.unpack("16sH22s", fcntl.ioctl(sock.fileno(), 0x8913, ifreq))[1]
            if not flags & 0x1:
                raise OSError("loopback could not be raised in the namespace")
    except OSError as exc:
        record["environment_error"] = f"loopback unavailable in namespace: {exc}"
        _write(record)
        return 2

    browser = subprocess.Popen(
        [BROWSER, "--headless=new", "--no-sandbox", "--disable-gpu",
         "--disable-dev-shm-usage", "--disable-extensions", "--no-first-run",
         "--no-default-browser-check", "--disable-background-networking",
         "--host-resolver-rules=MAP * ~NOTFOUND",
         "--user-data-dir=/profile", f"--remote-debugging-port={CDP_PORT}",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={})
    ws = None
    try:
        target = None
        deadline = time.monotonic() + 20
        import urllib.request
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=2) as response:
                    pages = [t for t in json.loads(response.read()) if t.get("type") == "page"]
                if pages:
                    target = pages[0]
                    break
            except (OSError, ValueError):
                time.sleep(0.2)
        if target is None:
            record["environment_error"] = "browser CDP endpoint never became ready"
            _write(record)
            return 2

        class Ws:
            """Self-contained stdlib websocket client (RFC 6455 text frames,
            masked sends); CDP events are skipped by id."""
            def __init__(self, host, port, path):
                import base64
                self._sock = socket.create_connection((host, port), timeout=10)
                key = base64.b64encode(os.urandom(16)).decode()
                self._sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                                    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
                response = b""
                while b"\r\n\r\n" not in response:
                    response += self._sock.recv(4096)
                header, sep, leftover = response.partition(b"\r\n\r\n")
                if b" 101 " not in header.split(b"\r\n", 1)[0]:
                    raise OSError("websocket upgrade refused")
                self._buf = leftover  # frame bytes that arrived with the handshake
                self._id = 0

            def send(self, payload):
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
                self._sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

            def _read_exact(self, count):
                while len(self._buf) < count:
                    chunk = self._sock.recv(65536)
                    if not chunk:
                        raise OSError("closed")
                    self._buf += chunk
                out, self._buf = self._buf[:count], self._buf[count:]
                return out

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
                    raise OSError("closed by peer")
                if opcode in (0x9, 0xA):
                    return self.recv()
                return json.loads(payload.decode())

            events = []

            def call(self, method, params=None, timeout=20.0):
                self._id += 1
                mid = self._id
                self.send({"id": mid, "method": method, "params": params or {}})
                deadline = time.monotonic() + timeout
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError(method)
                    m = self.recv()
                    if m.get("id") == mid:
                        if "error" in m:
                            raise RuntimeError(f"CDP {method}: {m['error']}")
                        return m.get("result", {})
                    if m.get("method") == "Runtime.exceptionThrown":
                        details = (m.get("params", {}).get("exceptionDetails") or {})
                        text = (details.get("exception", {}).get("description")
                                or details.get("text") or "exception")
                        self.events.append(text[:300])

        url = target.get("webSocketDebuggerUrl") or ""
        rest = url.split("://", 1)[1] if "://" in url else ""
        ws_path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
        ws = Ws("127.0.0.1", CDP_PORT, ws_path)
        record["environment"]["browser"] = "launched-in-namespace"

        exceptions = []

        def evaluate(expression):
            return ws.call("Runtime.evaluate", {"expression": expression,
                                                "returnByValue": True, "awaitPromise": False})

        ws.call("Runtime.enable")
        ws.call("Page.enable")
        # drain events in a background-ish manner: collect exceptions when seen
        def pump(deadline):
            while time.monotonic() < deadline:
                ws._sock.settimeout(max(0.05, deadline - time.monotonic()))
                try:
                    m = ws.recv()
                except (socket.timeout, TimeoutError):
                    return
                if m.get("method") == "Runtime.exceptionThrown":
                    details = (m.get("params", {}).get("exceptionDetails") or {})
                    text = details.get("exception", {}).get("description") or details.get("text") or "exception"
                    exceptions.append(text[:300])

        ws.call("Page.navigate", {"url": "file:///work/game.html"})
        record["evidence"]["ws_events_buffered"] = True
        time.sleep(T_LOAD_SETTLE)
        pump(time.monotonic() + 0.2)
        # Take control immediately: hold the mouse so the helicopter flies;
        # every flight check then runs on a LIVE game, not a crashed one.
        ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 300, "y": 150,
                                             "button": "left", "clickCount": 1})
        time.sleep(0.5)

        def state():
            result = evaluate(
                "JSON.stringify((function(){var s=window.__HELICOPTER_STATE__;"
                "if(!s)return null;return {y:s.y,vy:s.vy,score:s.score,crashed:s.crashed,"
                "gameOver:s.gameOver,difficulty:s.difficulty,distance:s.distance,"
                "obstacles:(s.obstacles||[]).length, first_obstacle_x:(s.obstacles&&s.obstacles[0]&&s.obstacles[0].x), speed:s.speed}})())")
            value = result.get("result", {}).get("value")
            try:
                return json.loads(value) if value else None
            except (TypeError, ValueError):
                return None

        def screenshot():
            data = ws.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            import base64 as b64
            return b64.b64decode(data.get("data", ""))

        canvas = evaluate("!!document.querySelector('canvas')").get("result", {}).get("value")
        record["checks"]["canvas_present"] = bool(canvas)
        s0 = state()
        record["checks"]["state_contract_present"] = s0 is not None
        if s0 is None:
            # Contract-dependent mechanics are behaviorally unverifiable
            # without the frozen state contract and stay unevaluable (never
            # falsely failed). Contract-independent launch/render evidence is
            # still scored, so instrumentation compliance remains
            # distinguishable from demonstrated functionality (SPEC §4.11
            # admission check A): missing telemetry never reports a gameplay
            # mechanic as broken.
            frame_a = screenshot()
            pump(time.monotonic() + T_LIVELINESS)
            frame_b = screenshot()
            record["checks"]["load_exceptions"] = exceptions[:20]
            record["checks"]["no_runtime_exceptions"] = not exceptions
            record["checks"]["animation_liveliness"] = frame_a != frame_b
            record["checks"]["frames_differ_while_idle"] = frame_a != frame_b
            record["evidence"]["liveliness_frame_bytes"] = [len(frame_a), len(frame_b)]
            _write(record)
            return 0

        # liveliness: frames change while flying (animation loop running)
        frame_a = screenshot()
        pump(time.monotonic() + T_LIVELINESS)
        frame_b = screenshot()
        record["checks"]["animation_liveliness"] = frame_a != frame_b
        record["evidence"]["liveliness_frame_bytes"] = [len(frame_a), len(frame_b)]

        # score accrues during flight (still holding the mouse)
        score0 = s0.get("score")
        time.sleep(2.5)
        s1 = state()
        record["checks"]["score_accrues"] = bool(s1 and isinstance(s1.get("score"), (int, float))
                                                 and s1["score"] > score0)
        record["evidence"]["score_samples"] = [score0, s1 and s1.get("score")]

        # difficulty progression and moving obstacles during play
        record["checks"]["obstacles_present"] = bool(s1 and (s1.get("obstacles") or 0) >= 1)
        difficulty0 = s1 and s1.get("difficulty")
        obstacle_positions = [s0.get("first_obstacle_x"), s1 and s1.get("first_obstacle_x")]
        time.sleep(2.5)
        s2 = state()
        record["checks"]["difficulty_increases"] = bool(
            s2 and isinstance(difficulty0, (int, float)) and s2.get("difficulty", 0) > difficulty0)
        record["checks"]["obstacles_advance"] = bool(
            s2 and s1 and s1.get("first_obstacle_x") is not None
            and s2.get("first_obstacle_x") is not None
            and s2.get("first_obstacle_x") != s1.get("first_obstacle_x"))
        speeds = [s.get("speed") for s in (s0, s1, s2) if s]
        if len(speeds) >= 2 and all(isinstance(v, (int, float)) for v in speeds[-2:]):
            record["checks"]["speed_increases"] = speeds[-1] > speeds[0]
            record["evidence"]["speed_samples"] = speeds
        else:
            record["checks"]["speed_increases"] = False
        record["evidence"]["difficulty_samples"] = [difficulty0, s2 and s2.get("difficulty")]
        record["evidence"]["obstacle_x_samples"] = obstacle_positions + [s2 and s2.get("first_obstacle_x")]

        # controls: release -> gravity descends; press again -> ascent
        def metrics():
            s = state()
            return s and s.get("y")
        def crashed_now():
            s = state()
            return bool(s and (s.get("crashed") or s.get("gameOver")))

        def restart_and_fly():
            ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 300, "y": 200,
                                                 "button": "left", "clickCount": 1})
            ws.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 300, "y": 200,
                                                 "button": "left", "clickCount": 1})
            time.sleep(0.25)
            ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 300, "y": 150,
                                                 "button": "left", "clickCount": 1})

        def ensure_flying():
            if crashed_now():
                restart_and_fly()

        # Controls are measured from a FRESH restart (early cave is wide:
        # blind input windows cannot silently crash into narrowed geometry).
        # Any mid-measurement crash triggers a restart and a redo.
        gravity_result = None
        for _attempt in range(3):
            ensure_flying()
            y_before_release = metrics()
            ws.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 300, "y": 150,
                                                 "button": "left", "clickCount": 1})
            time.sleep(0.7)
            y_released = metrics()
            if crashed_now():
                continue
            if isinstance(y_before_release, (int, float)) and \
                    isinstance(y_released, (int, float)):
                gravity_result = y_released > y_before_release + 1
            break
        record["checks"]["gravity_causes_descent"] = bool(gravity_result)
        record["evidence"]["gravity_samples"] = [y_before_release, y_released]

        ascent_result = None
        trajectory = []
        for _attempt in range(3):
            ensure_flying()
            trajectory = []
            for _step in range(7):
                time.sleep(0.25)
                s = state()
                trajectory.append([s and s.get("y"), s and s.get("vy"),
                                   bool(s and (s.get("crashed") or s.get("gameOver")))])
                if trajectory[-1][2]:
                    break
            if trajectory and not trajectory[-1][2] and len(trajectory) >= 5:
                first, last = trajectory[1], trajectory[-1]
                if None not in (first[0], last[0]) \
                        and all(isinstance(v, (int, float)) for v in (first[0], last[0])):
                    ascent_result = last[0] < first[0] - 1
                    break
            # crashed mid-window: restart and retry (fresh cave is wide)
        record["checks"]["input_causes_ascent"] = bool(ascent_result)
        record["checks"]["controls_state_numeric"] = gravity_result is not None and ascent_result is not None
        record["evidence"]["hold_trajectory"] = trajectory

        # collision: release and fall until the game registers a crash.
        # v2 game-over visible-indication sampling (corrected lexical
        # detector, SPEC §4.11 methodology /2): capture the rendered-text
        # multiset immediately BEFORE the forced collision. Only text that
        # becomes visible exactly with the demonstrated game-over transition
        # can earn the check — always-visible text (in the before-set),
        # hidden text (never rendered into innerText) and fabricated
        # telemetry alone (no rendered change) never qualify.
        game_over_text_before = (evaluate(
            "(document.body?document.body.innerText:'')")
            .get("result", {}).get("value") or "")
        ws.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 300, "y": 150,
                                             "button": "left", "clickCount": 1})
        crashed = False
        for _ in range(30):
            time.sleep(0.3)
            s = state()
            if s is None:
                break
            if s.get("crashed") or s.get("gameOver"):
                crashed = True
                break
        record["checks"]["collision_produces_game_over"] = crashed
        record["evidence"]["exceptions_total"] = len(exceptions)
        record["checks"]["no_runtime_exceptions"] = not exceptions
        record["checks"]["load_exceptions"] = exceptions[:20]

        if crashed:
            state_before_click = state() or {}
            inner = evaluate("document.body.innerText").get("result", {}).get("value") or ""
            record["evidence"]["game_over_text_sample"] = inner[:200]
            record["evidence"]["game_over_text_before"] = game_over_text_before[:200]
            # The 4-point check: NEW rendered text that appeared exactly with
            # the observed game-over transition. Wording is irrelevant ("GAME
            # OVER", "SYSTEM FAILURE / Collision Detected", ...); unrelated
            # text visible before the crash, hidden text, and telemetry
            # values alone cannot satisfy it.
            new_lines = sorted((Counter(_visible_lines(inner))
                                - Counter(_visible_lines(game_over_text_before))).elements())
            record["evidence"]["game_over_new_visible_text"] = new_lines[:8]
            record["checks"]["game_over_visible_text"] = bool(new_lines)
            # restart: a click restarts after game over; sample fast (gravity
            # would crash a freshly restarted helicopter on its own)
            ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 300, "y": 200,
                                                 "button": "left", "clickCount": 1})
            ws.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 300, "y": 200,
                                                 "button": "left", "clickCount": 1})
            time.sleep(0.3)
            s3 = state()
            s_before_click = state_before_click or {}
            # Restart evidence: the click yields a LIVE fresh state whose
            # score is far below the crashed run's final score.
            record["checks"]["restart_resets"] = bool(
                s3 and not s3.get("crashed") and not s3.get("gameOver")
                and isinstance(s3.get("score"), (int, float))
                and isinstance(s_before_click.get("score"), (int, float))
                and s3["score"] < s_before_click["score"])
            ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 300, "y": 150,
                                                 "button": "left", "clickCount": 1})
            record["evidence"]["post_restart_state"] = {k: s3.get(k) for k in ("score", "distance", "crashed")} if s3 else None
        import base64 as _b64
        record["evidence"]["review_screenshots_b64"] = [
            _b64.b64encode(screenshot()).decode() for _ in range(3)]
        _write(record)
        return 0
    except Exception as exc:  # environment/protocol failure: explicit, never a model verdict
        record["environment_error"] = f"{type(exc).__name__}: {exc}"
        _write(record)
        return 2
    finally:
        if ws is not None:
            try:
                ws._sock.close()
            except OSError:
                pass
        browser.terminate()
        try:
            browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            browser.kill()


def _write(record):
    bounded = json.dumps(record)[:200000]
    with open(RESULT_PATH, "w") as handle:
        handle.write(bounded)


if __name__ == "__main__":
    sys.exit(main())
