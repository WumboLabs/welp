"""Bounded writable command executor for the M3 Agentic boundary.

Single hard rule: an untrusted process NEVER writes host disk. Each
`run` invocation executes inside an ephemeral bubblewrap namespace whose
`/workspace` is a SIZED tmpfs kernel cap (engineering bound, not science):

  HOST                                    EPHEMERAL NAMESPACE
  ------                                  -------------------
  workspace/ --ro-bind--> /seed           /workspace  tmpfs --size 8 MiB
  (owner-grant walk, modes                /tmp        tmpfs --size 64 MiB
   restored in `finally`)                 trusted launcher (python3 -I -c):
  capture files (O_NOFOLLOW 0600)           1. PR_SET_DUMPABLE=0 (fail-closed
  control pipe (candidate never                check) BEFORE any fork, so the
     holds a descriptor; /proc/<pid>/fd        candidate cannot reach the
     of the dumpable=0 launcher is             launcher's descriptors through
     unreachable from the namespace)           /proc/<pid>/fd
  suite_driver.py --ro-bind-->               2. copy /seed -> /workspace applying
     /trusted/suite_driver.py                   the ORIGINAL seed modes manifest
  after teardown: materialize_               3. write the verified-launch marker
  snapshot(files, workspace) rebuilds        4. fork/exec `/bin/sh -c CMD` under
  the exact tmpfs state on host from            NPROC 8 x AS 128 MiB
  the exported snapshot (regular files       5. sweep the pid namespace
  byte-exact sha-verified, symlink              (SIGKILL -1 x2 + reap) so no
  metadata preserved, non-regular               survivor races the export
  artifacts declined, never host             6. self-grant+read+restore every
  FIFOs)                                        owned mode-000 artifact, then
                                                export ONE snapshot frame on
                                                the PRIVATE control descriptor

Declared engineering bounds (equal for every invocation; explicit):
  - process tree:  RLIMIT_NPROC 8 x RLIMIT_AS 128 MiB = 1 GiB theoretical
    (inherited per process; the tree cannot exceed NPROC processes);
  - writable workspace: 8 MiB tmpfs (ENOSPC beyond; kernel-enforced);
  - /tmp scratch: 64 MiB tmpfs; per-file RLIMIT_FSIZE 64 MiB; NOFILE 256;
  - captures: 2 MiB per stream with honest truncation flags; RLIMIT_FSIZE
    backs the capture files against a streaming writer;
  - snapshot export: 6 MiB embedded content (32 MiB wire-frame cap, 20000
    entries); content beyond the caps is recorded as omitted and flagged
    `complete=false` (a storage violation, never silent).

Design notes (defects found and fixed during implementation):
  - The export frame rides the PRIVATE control descriptor. Because a frame
    exceeds the 64 KiB pipe buffer, the host MUST drain the control pipe
    concurrently (bounded select/read loop under the host startup ceiling) —
    reading only after process exit would deadlock the launcher inside the
    inner `timeout` and lose every export. The parser rejects multiple
    sentinels/frames, so injected control bytes cannot forge a completion.
  - The launcher is passed with `python3 -I -c` (the host scratch path is
    never mounted), the manifest on argv, and the command as argv[3] —
    `python3 -c CODE a b c` reports argv[1:] = [a, b, c].
  - materialize_snapshot walks every path component with O_NOFOLLOW dirfds,
    rejects any entry below a snapshot symlink, writes regular files BEFORE
    creating symlink entries, and requires real directories at destination:
    a model symlink can never redirect a host write.
  - Seed mode fidelity: the host walk grants owner read on its own files
    solely for the read-only bind (mode-000 seeds such as the system
    fixture's data/quotes.json are unreadable through /seed otherwise), the
    launcher applies the manifest's ORIGINAL modes inside the tmpfs, the
    launcher re-grants+restores owned mode-000 artifacts for the export, and
    the host restores the exact original modes in a finally block.
  - The sweep before export closes the snapshot race for new sessions too:
    setsid(2) cannot leave the pid namespace, so kill(-1, SIGKILL) twice
    plus reaping reaches every survivor the command forked.

Integration contract (welp_next.agentic.Sandbox.run delegates here):
    run(workspace, command, timeout_seconds, bwrap_path="bwrap",
        trusted_driver=None, mem_limit_bytes=AS_LIMIT_BYTES) -> dict

    Success/failure observation (raw-capture compatible with
    agentic.parse_suite_receipt): {ok, exit_code, stop_reason, timed_out,
    launched, stdout, stderr, stdout_truncated, stderr_truncated, wall_s,
    workspace (snapshot files dict|None), snapshot_complete, snapshot_error,
    workspace_bytes, workspace_files, storage_exceeded, seed_errors}.
    Integration faults carry harness_failure=True + error (never a model
    outcome): missing bwrap, unlaunched boundary (no marker), host-ceiling
    breach, sentinel/frame inconsistency. A command deadline at the DECLARED
    budget stays a task observation (stop_reason "timeout"; grace applies
    only after termination is initiated; fractions preserved).
    materialize_snapshot(files, dest) -> {"created_files", "created_dirs",
    "created_symlinks", "declined", "content_omitted", "bytes"}; raises
    ValueError on unsafe paths, symlink-ancestored entries, oversized or
    digest-mismatched content.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import math
import os
import re
import resource
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

# Reuse the proven M2 bounded read-back helper (welp_next.sandbox imports
# nothing from welp_next, so this is cycle-free).
from .sandbox import _read_capped, PROJECT_ROOT  # noqa: E402  (bounded capture)

BOUNDARY_MARKER = "welp-agentic-boundary-v1"
SENTINEL_PREFIX = "welp-agentic-completed"
SNAPSHOT_MAGIC = b"WELP-AGENTIC-SNAPSHOT-V1"

CAPTURE_STDERR_PATH = "/dev/.welp-capture-stderr"
STDERR_FD_TOKEN = "<host-stderr-fd>"
TRUSTED_DRIVER_MOUNT = "/trusted/suite_driver.py"

BOUNDARY_SCRATCH_ROOT = PROJECT_ROOT / "tmp" / "m3-advancement-agentic" / "sandbox"

#: Declared engineering bounds (documented, equal for all tasks; explicit).
NPROC_LIMIT = 8
AS_LIMIT_BYTES = 128 * 1024 * 1024
WORKSPACE_TMPFS_BYTES = 8 * 1024 * 1024
TMP_TMPFS_BYTES = 64 * 1024 * 1024
FSIZE_LIMIT_BYTES = 64 * 1024 * 1024
NOFILE_LIMIT = 256
TIMEOUT_KILL_GRACE_SECONDS = 5
HOST_STARTUP_GRACE_SECONDS = 30
MAX_RUN_SECONDS = 3_600.0

MAX_CAPTURE_BYTES = 2 * 1024 * 1024
SNAPSHOT_WIRE_MAX_BYTES = 32 * 1024 * 1024
SNAPSHOT_FILE_CONTENT_CAP = 4 * 1024 * 1024
SNAPSHOT_TOTAL_CONTENT_CAP = 6 * 1024 * 1024
MAX_SNAPSHOT_ENTRIES = 20_000

_SENTINEL_RE = re.compile(
    (SENTINEL_PREFIX + r" rc=(-?\d+) seed_errors=(\d+)\n").encode())


# ---------------------------------------------------------------------------
# in-namespace trusted launcher (runs as `python3 -I -c`; never a host path)
#
# argv: [-c, MODES_JSON, "/bin/sh", COMMAND]  ->  sys.argv[1:] is
# [MODES_JSON, "/bin/sh", COMMAND] for a `python3 -c` invocation.


_LAUNCHER = (
    "import base64, ctypes, hashlib, json, os, resource, signal, stat, sys, time\n"
    "libc = ctypes.CDLL(None, use_errno=True)\n"
    "if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE=0, fail-closed\n"
    "    sys.exit(126)\n"
    "MODES = json.loads(sys.argv[1]).get(\"modes\", {})\n"
    "SH, CMD = sys.argv[2], sys.argv[3]\n"
    "ctl = os.dup(2)\n"
    "os.set_inheritable(ctl, False)\n"
    "fe = os.open(" + repr(CAPTURE_STDERR_PATH) + ",\n"
    "             os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)\n"
    "os.dup2(fe, 2)\n"
    "os.close(fe)\n"
    "seed_errors = []\n"
    "def _mode(rel, st):\n"
    "    m = MODES.get(rel)\n"
    "    return m if isinstance(m, int) else (st.st_mode & 0o7777)\n"
    "os.makedirs('/workspace', exist_ok=True)\n"
    "dir_modes = {}\n"
    "stack = [('/seed', '')]\n"
    "while stack:\n"
    "    src, rel = stack.pop()\n"
    "    for entry in os.scandir(src):\n"
    "        r = rel + entry.name\n"
    "        st = entry.stat(follow_symlinks=False)\n"
    "        if entry.is_symlink():\n"
    "            os.symlink(os.readlink(entry.path), '/workspace/' + r)\n"
    "        elif stat.S_ISDIR(st.st_mode):\n"
    "            os.mkdir('/workspace/' + r, 0o700)\n"
    "            dir_modes[r] = _mode(r, st)\n"
    "            stack.append((entry.path, r + '/'))\n"
    "        elif stat.S_ISREG(st.st_mode):\n"
    "            try:\n"
    "                data = open(entry.path, 'rb').read()\n"
    "            except OSError as exc:\n"
    "                seed_errors.append([r, 'seed read: %s' % exc])\n"
    "                data = b''\n"
    "            with open('/workspace/' + r, 'wb') as stream:\n"
    "                stream.write(data)\n"
    "            os.chmod('/workspace/' + r, _mode(r, st) & 0o7777)\n"
    "        else:\n"
    "            seed_errors.append([r, 'declined non-regular seed artifact'])\n"
    "for rel in sorted(dir_modes, key=len, reverse=True):\n"
    "    os.chmod('/workspace/' + rel, dir_modes[rel] & 0o7777)\n"
    "os.write(ctl, (" + repr(BOUNDARY_MARKER) + " + ' seed_errors=%d\\n'\n"
    "          % len(seed_errors)).encode())\n"
    "resource.setrlimit(resource.RLIMIT_NPROC, (" + str(NPROC_LIMIT) + ",\n"
    "                   " + str(NPROC_LIMIT) + "))\n"
    "resource.setrlimit(resource.RLIMIT_AS, (" + str(AS_LIMIT_BYTES) + ",\n"
    "                   " + str(AS_LIMIT_BYTES) + "))\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    try:\n"
    "        os.closerange(3, " + str(NOFILE_LIMIT) + ")\n"
    "        os.execv(SH, [SH, '-c', CMD])\n"
    "    except OSError:\n"
    "        os._exit(127)\n"
    "_, status = os.waitpid(pid, 0)\n"
    "rc = os.waitstatus_to_exitcode(status)\n"
    "# Sweep the pid namespace BEFORE the export: setsid cannot leave the\n"
    "# namespace, so kill(-1, SIGKILL) x2 + reap reaches every survivor.\n"
    "for _sweep in range(2):\n"
    "    try:\n"
    "        os.kill(-1, signal.SIGKILL)\n"
    "    except ProcessLookupError:\n"
    "        pass\n"
    "    time.sleep(0.05)\n"
    "    try:\n"
    "        while True:\n"
    "            if os.waitpid(-1, os.WNOHANG)[0] == 0:\n"
    "                break\n"
    "    except ChildProcessError:\n"
    "        pass\n"
    "FILE_CAP = " + str(SNAPSHOT_FILE_CONTENT_CAP) + "\n"
    "TOTAL_CAP = " + str(SNAPSHOT_TOTAL_CONTENT_CAP) + "\n"
    "def _scan(path):\n"
    "    try:\n"
    "        return sorted(os.scandir(path), key=lambda e: e.name)\n"
    "    except PermissionError:\n"
    "        st = os.stat(path, follow_symlinks=False)\n"
    "        os.chmod(path, (st.st_mode & 0o7777) | 0o500)\n"
    "        try:\n"
    "            return sorted(os.scandir(path), key=lambda e: e.name)\n"
    "        finally:\n"
    "            os.chmod(path, st.st_mode & 0o7777)\n"
    "def _read_export(path, st):\n"
    "    try:\n"
    "        with open(path, 'rb') as stream:\n"
    "            return stream.read(FILE_CAP + 1), None\n"
    "    except OSError as exc:\n"
    "        if not isinstance(exc, PermissionError):\n"
    "            return b'', str(exc)\n"
    "        os.chmod(path, (st.st_mode & 0o7777) | 0o400)\n"
    "        try:\n"
    "            with open(path, 'rb') as stream:\n"
    "                return stream.read(FILE_CAP + 1), None\n"
    "        finally:\n"
    "            os.chmod(path, st.st_mode & 0o7777)\n"
    "files = {}\n"
    "embedded = 0\n"
    "complete = True\n"
    "stack = [('/workspace', '')]\n"
    "while stack:\n"
    "    src, rel = stack.pop()\n"
    "    try:\n"
    "        children = _scan(src)\n"
    "    except OSError as exc:\n"
    "        if rel:\n"
    "            files[rel[:-1]] = {'type': 'access_denied', 'error': str(exc)}\n"
    "            complete = False\n"
    "        continue\n"
    "    for entry in children:\n"
    "        if len(files) >= " + str(MAX_SNAPSHOT_ENTRIES) + ":\n"
    "            files['__entries_truncated__'] = True\n"
    "            complete = False\n"
    "            break\n"
    "        st = entry.stat(follow_symlinks=False)\n"
    "        if entry.is_symlink():\n"
    "            files[rel + entry.name] = {\n"
    "                'type': 'symlink', 'target': os.readlink(entry.path)}\n"
    "        elif stat.S_ISDIR(st.st_mode):\n"
    "            files[rel + entry.name] = {'type': 'dir',\n"
    "                                       'mode': st.st_mode & 0o7777}\n"
    "            stack.append((entry.path, rel + entry.name + '/'))\n"
    "        elif stat.S_ISREG(st.st_mode):\n"
    "            item = {'bytes': st.st_size, 'mode': st.st_mode & 0o7777}\n"
    "            data, err = _read_export(entry.path, st)\n"
    "            if err is not None:\n"
    "                item['content_omitted'] = True\n"
    "                item['omission'] = err\n"
    "                complete = False\n"
    "            item['sha256'] = hashlib.sha256(\n"
    "                data if len(data) <= FILE_CAP else data[:FILE_CAP]).hexdigest()\n"
    "            if err is None and (len(data) > FILE_CAP\n"
    "                                or embedded + len(data) > TOTAL_CAP):\n"
    "                item['content_omitted'] = True\n"
    "                item['omission'] = 'content exceeds snapshot cap'\n"
    "                complete = False\n"
    "            if err is None and len(data) <= FILE_CAP:\n"
    "                item['content_b64'] = base64.b64encode(data).decode('ascii')\n"
    "                embedded += len(data)\n"
    "            files[rel + entry.name] = item\n"
    "        else:\n"
    "            files[rel + entry.name] = {'type': 'special',\n"
    "                                       'mode': st.st_mode & 0o7777,\n"
    "                                       'declined': True}\n"
    "    if files.get('__entries_truncated__'):\n"
    "        break\n"
    "snapshot = {'files': files, 'complete': complete, 'embedded_bytes': embedded,\n"
    "            'seed_errors': seed_errors,\n"
    "            'caps': {'file': FILE_CAP, 'total': TOTAL_CAP,\n"
    "                     'entries': " + str(MAX_SNAPSHOT_ENTRIES) + "}}\n"
    "body = json.dumps(snapshot, separators=(',', ':')).encode()\n"
    "frame = " + repr(SNAPSHOT_MAGIC) + " + b' ' + str(len(body)).encode() + b'\\n' + body\n"
    "os.write(ctl, (" + repr(SENTINEL_PREFIX) + " + ' rc=%d seed_errors=%d\\n'\n"
    "          % (rc, len(seed_errors))).encode())\n"
    "for _off in range(0, len(frame), 1 << 16):\n"
    "    os.write(ctl, frame[_off:_off + (1 << 16)])\n"
    "sys.exit(rc if 0 <= rc <= 255 else 128 - rc)\n"
)


# ---------------------------------------------------------------------------
# host-side helpers


def _format_seconds(value: float) -> str:
    """Fraction-preserving declared deadline for timeout(1)."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _boundary_unavailable(error: str) -> dict:
    return {"ok": False, "harness_failure": True, "error": error,
            "workspace": None, "snapshot_complete": False,
            "workspace_bytes": 0, "workspace_files": 0,
            "storage_exceeded": False, "seed_errors": []}


def _seed_manifest_and_grant(root: Path) -> tuple[dict, list]:
    """Record ORIGINAL modes for every entry and grant owner access on the
    host's own regular files/dirs solely so the read-only bind can serve
    bytes (mode-000 seeds are unreadable through /seed otherwise). Symlinks
    are recorded but never chmod-ed (chmod would follow them) and never
    opened. Returns (modes manifest, granted path list)."""
    modes: dict[str, int] = {}
    granted: list[str] = []
    stack = [(Path(root), "")]
    while stack:
        current, prefix = stack.pop()
        with os.scandir(current) as entries:
            children = sorted(entries, key=lambda e: e.name)
        for entry in children:
            rel = prefix + entry.name
            st = entry.stat(follow_symlinks=False)
            if entry.is_symlink():
                continue
            if stat.S_ISDIR(st.st_mode):
                modes[rel] = st.st_mode & 0o7777
                if (st.st_mode & 0o500) != 0o500:
                    os.chmod(entry.path, (st.st_mode & 0o7777) | 0o500)
                    granted.append(entry.path)
                stack.append((Path(entry.path), rel + "/"))
            elif stat.S_ISREG(st.st_mode):
                modes[rel] = st.st_mode & 0o7777
                if not st.st_mode & stat.S_IRUSR:
                    os.chmod(entry.path, (st.st_mode & 0o7777) | 0o400)
                    granted.append(entry.path)
            # other types: left untouched; the launcher declines them
    return {"modes": modes}, granted


def _restore_modes(root: Path, manifest: dict, granted: list) -> None:
    """Restore exact original modes (best effort; the caller owns the tree)."""
    modes = manifest.get("modes", {})
    for path in granted:
        rel = str(Path(path).relative_to(root))
        mode = modes.get(rel)
        if isinstance(mode, int):
            try:
                os.chmod(path, mode)
            except OSError:
                pass


def _parse_control(control: bytes, proc_rc: int, host_killed: bool,
                   capture: str, deadline_exhausted: bool) -> dict:
    """Parse the private control stream into the observation."""
    if host_killed:
        return _boundary_unavailable("harness_failure: boundary exceeded host-side ceiling")
    marker_at = control.find(BOUNDARY_MARKER.encode())
    if marker_at < 0:
        return _boundary_unavailable(
            "harness_failure: sandbox boundary failed to launch (integration): "
            f"exit {proc_rc}: {(capture or control.decode('utf-8', 'replace'))[:400]}")
    sentinels = _SENTINEL_RE.findall(control)
    if len(sentinels) > 1:
        return _boundary_unavailable(
            "harness_failure: multiple completion sentinels on the control "
            "channel (inconsistent boundary)")
    if not sentinels:
        # Declared deadline consumed the whole budget (the launcher never
        # reached the export): a TASK observation, never a harness failure.
        if deadline_exhausted and proc_rc in (124, 137):
            return {"ok": False, "launched": True, "exit_code": proc_rc,
                    "stop_reason": "timeout", "timed_out": True,
                    "error": "command deadline; no workspace export",
                    "workspace": None, "snapshot_complete": False,
                    "snapshot_error": "deadline consumed before completion export",
                    "workspace_bytes": 0, "workspace_files": 0,
                    "storage_exceeded": False, "seed_errors": []}
        return _boundary_unavailable(
            f"harness_failure: boundary terminated without completion sentinel "
            f"(integration): exit {proc_rc}")
    rc = int(sentinels[0][0])
    seed_error_count = int(sentinels[0][1])
    tail = control[_SENTINEL_RE.search(control).end():]
    snapshot = None
    snapshot_error = None
    frame_at = tail.find(SNAPSHOT_MAGIC)
    if frame_at < 0:
        snapshot_error = "no snapshot frame after completion sentinel"
    else:
        header = tail[frame_at:tail.find(b"\n", frame_at) + 1]
        m = re.fullmatch(re.escape(SNAPSHOT_MAGIC) + rb" (\d+)\n", header)
        if not m:
            snapshot_error = "malformed snapshot frame header"
        else:
            length = int(m.group(1))
            body = tail[len(header):len(header) + length]
            if len(body) != length:
                snapshot_error = "truncated snapshot frame"
            else:
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    snapshot_error = f"undecodable snapshot: {exc}"
                else:
                    if not isinstance(parsed, dict) \
                            or not isinstance(parsed.get("files"), dict):
                        snapshot_error = "snapshot frame is not a files object"
                    else:
                        snapshot = parsed
    if snapshot_error and host_killed:
        return _boundary_unavailable(
            "harness_failure: inconsistent control channel under the host "
            f"ceiling: {snapshot_error}")
    files = (snapshot or {}).get("files") or {}
    used_bytes = sum(int(e.get("bytes", 0)) for e in files.values()
                     if isinstance(e, dict) and e.get("type") != "symlink"
                     and e.get("bytes") is not None)
    complete = bool(snapshot.get("complete")) if snapshot else False
    storage_exceeded = snapshot is None or not complete
    seed_errors = (snapshot or {}).get("seed_errors")
    if seed_errors is None or len(seed_errors) != seed_error_count:
        seed_errors = seed_errors if isinstance(seed_errors, list) else []
        if seed_error_count:
            snapshot_error = snapshot_error or "seed error count mismatch"
    obs = {
        "ok": rc == 0 and snapshot is not None and storage_exceeded is False,
        "exit_code": rc, "launched": True,
        "stop_reason": None,
        "timed_out": False,
        "workspace": files if snapshot is not None else None,
        "snapshot_complete": complete,
        "snapshot_error": snapshot_error,
        "workspace_bytes": used_bytes,
        "workspace_files": sum(1 for e in files.values() if isinstance(e, dict)),
        "storage_exceeded": storage_exceeded,
        "seed_errors": seed_errors,
    }
    return obs


def run(workspace, command: str, timeout_seconds: float, bwrap_path: str = "bwrap",
        trusted_driver: str | None = None,
        mem_limit_bytes: int = AS_LIMIT_BYTES) -> dict:
    """Execute `command` in a bounded ephemeral namespace against a private
    tmpfs copy of `workspace`; return the Sandbox.run-shaped observation plus
    the exported workspace snapshot (see module docstring)."""
    workspace = Path(workspace)
    if not isinstance(command, str) or not command.strip():
        return _boundary_unavailable("harness_failure: empty command refused")
    if (not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= MAX_RUN_SECONDS):
        return _boundary_unavailable(
            f"harness_failure: timeout_seconds must lie in (0, {MAX_RUN_SECONDS}]")
    if not (Path(bwrap_path).is_absolute()
            and Path(bwrap_path).is_file()
            and os.access(bwrap_path, os.X_OK)) \
            and shutil.which(bwrap_path) is None:
        return _boundary_unavailable(
            "harness_failure: bwrap not available; refusing to execute agent "
            "actions unsandboxed")
    if not workspace.is_dir():
        return _boundary_unavailable(
            f"harness_failure: workspace seed missing: {workspace}")
    if Path(workspace).resolve() == Path("/"):
        return _boundary_unavailable("harness_failure: refusing / as workspace")

    BOUNDARY_SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    private = Path(tempfile.mkdtemp(prefix="boundary-", dir=BOUNDARY_SCRATCH_ROOT))
    manifest, granted = _seed_manifest_and_grant(workspace)
    fd_out = fd_err = ctl_r = ctl_w = None
    proc = None
    host_killed = False
    started = time.monotonic()
    try:
        driver_path = None
        if trusted_driver:
            driver_path = private / "suite_driver.py"
            driver_path.write_text(trusted_driver, encoding="utf-8")
        fd_out = os.open(private / "stdout",
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        fd_err = os.open(private / "stderr",
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        ctl_r, ctl_w = os.pipe()
        seconds = float(timeout_seconds)
        host_ceiling = seconds + TIMEOUT_KILL_GRACE_SECONDS + HOST_STARTUP_GRACE_SECONDS
        argv = [
            "timeout", "-k", str(TIMEOUT_KILL_GRACE_SECONDS),
            _format_seconds(seconds),
            bwrap_path,
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
            "--size", str(TMP_TMPFS_BYTES), "--tmpfs", "/tmp",
            "--size", str(WORKSPACE_TMPFS_BYTES), "--tmpfs", "/workspace",
            "--ro-bind", str(workspace), "/seed",
            "--bind-fd", STDERR_FD_TOKEN, CAPTURE_STDERR_PATH,
            "--chdir", "/workspace",
        ]
        if driver_path is not None:
            argv += ["--ro-bind", str(driver_path), TRUSTED_DRIVER_MOUNT]
        argv += [
            "--setenv", "PATH", "/usr/bin:/bin:/usr/sbin:/sbin",
            "--setenv", "HOME", "/tmp",
            "--setenv", "TMPDIR", "/tmp",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "LC_ALL", "C.UTF-8",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONHASHSEED", "0",
            "--",
            "python3", "-I", "-c", _LAUNCHER,
            json.dumps(manifest, separators=(",", ":")),
            "/bin/sh", command,
        ]
        spawn_argv = [str(fd_err) if p == STDERR_FD_TOKEN else p for p in argv]

        def _limits():
            cpu = int(math.ceil(seconds)) + TIMEOUT_KILL_GRACE_SECONDS
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            as_limit = min(int(mem_limit_bytes), AS_LIMIT_BYTES) \
                if mem_limit_bytes else AS_LIMIT_BYTES
            resource.setrlimit(resource.RLIMIT_AS, (as_limit, as_limit))
            resource.setrlimit(resource.RLIMIT_FSIZE,
                               (FSIZE_LIMIT_BYTES, FSIZE_LIMIT_BYTES))
            resource.setrlimit(resource.RLIMIT_NOFILE, (NOFILE_LIMIT, NOFILE_LIMIT))

        try:
            proc = subprocess.Popen(
                spawn_argv, stdin=subprocess.DEVNULL,
                stdout=fd_out, stderr=ctl_w, pass_fds=(ctl_w, fd_err),
                preexec_fn=_limits, start_new_session=True)
        except (OSError, subprocess.SubprocessError) as exc:
            return _boundary_unavailable(
                f"harness_failure: boundary spawn failed: {exc}")
        os.close(ctl_w)
        ctl_w = None
        # Drain the private control pipe CONCURRENTLY: the exported frame
        # exceeds the pipe buffer, so read-after-exit would deadlock the
        # launcher and lose the snapshot.
        control = bytearray()
        deadline = started + host_ceiling
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                host_killed = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            readable, _, _ = select.select([ctl_r], [], [], min(remaining, 0.25))
            if readable:
                chunk = os.read(ctl_r, 1 << 16)
                if not chunk:
                    break
                control += chunk
                if len(control) > SNAPSHOT_WIRE_MAX_BYTES:
                    host_killed = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
        try:
            proc_rc = proc.wait(timeout=HOST_STARTUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            host_killed = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc_rc = proc.wait()
        while True:
            readable, _, _ = select.select([ctl_r], [], [], 0.1)
            if not readable:
                break
            chunk = os.read(ctl_r, 1 << 16)
            if not chunk:
                break
            control += chunk
            if len(control) > SNAPSHOT_WIRE_MAX_BYTES:
                break
        stdout, stdout_trunc = _read_capped(fd_out, MAX_CAPTURE_BYTES)
        stderr, stderr_trunc = _read_capped(fd_err, MAX_CAPTURE_BYTES)
        if host_killed and BOUNDARY_MARKER.encode() not in bytes(control):
            obs = _boundary_unavailable(
                "harness_failure: sandbox boundary did not terminate within "
                "the host-side startup ceiling (integration)")
        else:
            obs = _parse_control(bytes(control), proc_rc, host_killed, stderr,
                                 time.monotonic() - started >= seconds)
        obs["stdout"] = stdout
        obs["stderr"] = stderr
        obs["stdout_truncated"] = stdout_trunc
        obs["stderr_truncated"] = stderr_trunc
        obs["wall_s"] = round(time.monotonic() - started, 3)
        return obs
    except OSError as exc:
        return _boundary_unavailable(f"harness_failure: {exc}")
    finally:
        _restore_modes(workspace, manifest, granted)
        for fd in (ctl_r, ctl_w, fd_out, fd_err):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(private, ignore_errors=True)


# ---------------------------------------------------------------------------
# host-side snapshot materialization (nofollow dirfd walk; links LAST)


def _chain_dirfd(base_fd: int, parts: list[str]) -> int:
    """Walk real directory components under base_fd with O_NOFOLLOW, creating
    missing components (0700) and REPLACING stale non-directory host nodes
    (previous materializations own the destination tree; a model symlink can
    never redirect a host write because every open is O_NOFOLLOW). Returns
    the dirfd of the final component (caller closes)."""
    fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=base_fd)
    for part in parts:
        try:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=fd)
        except OSError:
            try:
                st = os.stat(part, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                st = None
            if st is not None and stat.S_ISDIR(st.st_mode):
                os.close(fd)
                raise
            if st is not None:
                os.unlink(part, dir_fd=fd)
            os.mkdir(part, 0o700, dir_fd=fd)
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=fd)
        os.close(fd)
        fd = next_fd
    return fd


def _clear_non_dir(dir_fd: int, name: str) -> None:
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(st.st_mode):
        raise ValueError(f"materialize_snapshot: {name!r} exists as a directory")
    os.unlink(name, dir_fd=dir_fd)


def materialize_snapshot(files: dict, dest,
                         total_cap: int = SNAPSHOT_TOTAL_CONTENT_CAP) -> dict:
    """Rebuild the exported tmpfs state at host `dest` after namespace
    teardown. Regular files are recreated byte-exact (base64, sha-verified)
    via O_NOFOLLOW dirfd walks; directory and symlink METADATA is preserved
    verbatim (host tooling never follows model-planted links); symlink
    entries are created LAST and no entry may live below a symlink; non-
    regular artifacts are DECLINED — recorded, never created on host (no
    host FIFOs). Raises ValueError on unsafe paths, symlink-ancestored
    entries, oversized or digest-mismatched content, or malformed entries."""
    dest = Path(dest)
    if not isinstance(files, dict):
        raise ValueError("materialize_snapshot: files must be a dict")
    dirs: dict[str, int] = {}
    regulars: dict[str, tuple[int, bytes]] = {}
    links: dict[str, str] = {}
    declined: list[str] = []
    omitted: list[str] = []
    total = 0
    for rel, entry in files.items():
        if not isinstance(rel, str) or not rel or rel.endswith("/") \
                or rel.startswith("/") or ".." in rel.split("/") \
                or "" in rel.split("/") or "\x00" in rel:
            raise ValueError(f"materialize_snapshot: unsafe path {rel!r}")
        if not isinstance(entry, dict):
            raise ValueError(f"materialize_snapshot: malformed entry {rel!r}")
        kind = entry.get("type")
        if kind == "dir":
            dirs[rel] = int(entry.get("mode", 0o700)) & 0o7777
        elif kind == "symlink":
            target = entry.get("target")
            if not isinstance(target, str):
                raise ValueError(
                    f"materialize_snapshot: symlink {rel!r} without target")
            links[rel] = target
        elif kind in ("special", "access_denied"):
            declined.append(rel)
        elif entry.get("content_b64") is None:
            if entry.get("content_omitted"):
                omitted.append(rel)
                continue
            raise ValueError(
                f"materialize_snapshot: entry {rel!r} carries no content")
        else:
            data = base64.b64decode(entry["content_b64"], validate=True)
            if entry.get("sha256") is not None \
                    and hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError(f"materialize_snapshot: sha mismatch for {rel!r}")
            total += len(data)
            if total > total_cap:
                raise ValueError("materialize_snapshot: exported content exceeds cap")
            regulars[rel] = (int(entry.get("mode", 0o644)) & 0o7777, data)
    # No entry may live below a symlink entry (host writes must never be
    # redirected through a model-planted link).
    for rel in list(dirs) + list(regulars) + list(links):
        parts = rel.split("/")
        for depth in range(1, len(parts)):
            ancestor = "/".join(parts[:depth])
            if ancestor in links:
                raise ValueError(
                    f"materialize_snapshot: {rel!r} lies below symlink {ancestor!r}")
    base_fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for rel in sorted(dirs, key=len):
            fd = _chain_dirfd(base_fd, rel.split("/"))
            os.close(fd)
        # 1. real directory chains (0700 until the mode pass)
        for rel in sorted(set(dirs) | set(regulars) | set(links), key=len):
            parts = rel.split("/")[:-1]
            if parts:
                fd = _chain_dirfd(base_fd, parts)
                os.close(fd)
        # 2. regular files byte-exact, BEFORE any symlink exists
        for rel, (mode, data) in sorted(regulars.items()):
            parts = rel.split("/")
            pfd = _chain_dirfd(base_fd, parts[:-1]) if parts[:-1] else \
                os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=base_fd)
            try:
                name = parts[-1]
                _clear_non_dir(pfd, name)
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                             | os.O_NOFOLLOW, 0o600, dir_fd=pfd)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.chmod(name, mode, dir_fd=pfd, follow_symlinks=False)
            finally:
                os.close(pfd)
        # 3. symlink entries last (final component only; ancestors real)
        for rel, target in sorted(links.items()):
            parts = rel.split("/")
            pfd = _chain_dirfd(base_fd, parts[:-1]) if parts[:-1] else \
                os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=base_fd)
            try:
                _clear_non_dir(pfd, parts[-1])
                os.symlink(target, parts[-1], dir_fd=pfd)
            finally:
                os.close(pfd)
        # 4. directory modes, deepest first
        for rel in sorted(dirs, key=len, reverse=True):
            parts = rel.split("/")
            pfd = _chain_dirfd(base_fd, parts[:-1]) if parts[:-1] else \
                os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=base_fd)
            try:
                os.chmod(parts[-1], dirs[rel], dir_fd=pfd, follow_symlinks=False)
            finally:
                os.close(pfd)
    finally:
        os.close(base_fd)
    return {"created_files": len(regulars), "created_dirs": len(dirs),
            "created_symlinks": len(links), "declined": declined,
            "content_omitted": omitted, "bytes": total}
