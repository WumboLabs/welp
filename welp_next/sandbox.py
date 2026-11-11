"""Disposable isolated execution boundary for generated code (SPEC §8 G).

Every byte of model-generated code runs ONLY inside a bounded bubblewrap
sandbox: isolated mount namespace (the host root is never mounted — only the
read-only runtime trees a Python interpreter needs), isolated
pid/network/ipc/user namespaces, minimal /proc and /dev, no environment
inheritance (``--clearenv``), a fixed deterministic Python environment, and a
hard wall-clock ``timeout`` under the caller's task budget (fail-closed).

Isolation layout inside the sandbox:
- ``/work``  read-only bind of a fresh disposable work directory holding the
  frozen candidate/tests tree. Generated code cannot modify, remove or add
  anything under ``/work`` — test or candidate tampering is structurally
  impossible, which is the frozen "reject test changes" gate.
- ``/tmp``   fresh tmpfs scratch (HOME/TMPDIR); it never touches the host
  tmp and evaporates with the namespace. Host-side working directories are
  created under ``PROJECT_ROOT/tmp/m2-model-baseline/sandbox`` — never the
  system /tmp.
- Captures: this host process opens both capture files (regular, ``0600``,
  ``O_NOFOLLOW``) in its own private scratch directory BEFORE launch, passes
  those descriptors to the sandbox as stdout/stderr, and afterwards reads
  the SAME descriptors back with a hard byte cap. There is no ``/out``
  mount and no writable capture directory inside the sandbox; the only
  capture path exposed there is a bind of the host-opened stderr inode
  itself, so a generated program cannot replace a capture with a symlink
  (the host never reopens any capture name after launch) and no read can
  escape the deadline (the cap bounds the read itself, not a whole-file
  read).

CPU/address-space/file-size/fd limits are inherited before boundary launch;
the process-count limit is applied inside the new user namespace so unrelated
host-UID processes cannot exhaust it. A host-side timeout also bounds startup.
Captured output is bounded twice: RLIMIT_FSIZE caps the stream files and the
read-back cap bounds what this module ever returns.

The record this module returns is the ONLY thing scoring consumes. It
preserves the exact executable/generated-code/test identities (sha-256 of
every file written plus the canonical argv) and never carries any
elapsed-time field, so offline reconstruction from saved evidence is
deterministic for the same model output. The canonical argv redacts the
random host work directory to its stable sandbox mount point (``/work``);
the launch-status descriptor number is recorded as a fixed placeholder.

Honesty rules:
- ``available: false`` is an integration condition (boundary not usable,
  bwrap launch denied, namespace setup failure, frozen executable missing)
  — never a model finding. Launch status travels on a separate control
  descriptor (the sandbox stderr until the frozen launcher redirects it):
  ``bwrap``/``timeout`` setup diagnostics and the launcher marker share that
  pipe, and the candidate never holds a descriptor to it, so captured model
  output can neither forge nor erase a launch. The launcher writes the
  marker only AFTER it has resolved the frozen executable to an absolute,
  existing, executable file — a missing interpreter fails with no marker.
- A response with no extractable code block is a deterministic decisive
  format failure for the task, reported through ``extracted.found: false``
  (available boundary, nothing executed).
Stdlib only (json, math, os, re, resource, shutil, subprocess, tempfile).
"""
import json
import math
import os
import re
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT / "tmp" / "m2-model-baseline" / "sandbox"

# Fail-closed bound: any larger requested timeout is a caller defect, not a
# clamp target. The task budget owner passes its own value.
MAX_TIMEOUT_SECONDS = 600
_TIMEOUT_KILL_GRACE_SECONDS = 5
# Host-side ceiling on the whole bwrap lifecycle (startup + run + kill grace).
_HOST_STARTUP_GRACE_SECONDS = 30
# Read-back cap per captured stream; RLIMIT_FSIZE bounds the files too.
_MAX_CAPTURE_BYTES = 2 * 1024 * 1024
# Cap on the boundary control channel (bwrap/timeout diagnostics + marker).
_MAX_CONTROL_BYTES = 4096
#: Written by the frozen launcher to the boundary control descriptor after
#: the frozen executable has been verified; its absence proves the boundary
#: itself failed (integration, never model data). The candidate never holds
#: the control descriptor, so it cannot forge or erase the marker.
BOUNDARY_MARKER = "welp-sandbox-boundary-v1"

# Frozen resource bounds for every sandboxed process tree (documented, equal
# for all tasks; engineering safety bounds, never model-performance gates).
RLIMIT_ADDRESS_SPACE_BYTES = 2 * 1024**3
RLIMIT_CPU_GRACE_SECONDS = _TIMEOUT_KILL_GRACE_SECONDS
RLIMIT_NPROC = 64
RLIMIT_FSIZE_BYTES = 64 * 1024**2
RLIMIT_NOFILE = 256

_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)[ \t]*\r?\n(.*?)\r?\n?```", re.DOTALL)
_PYTHON_FENCE_LANGS = {"python", "python3", "py"}

# Path of the candidate stderr capture inside the sandbox: a bind of the
# host-opened stderr file descriptor (one inode, not a writable directory),
# used only by the frozen launcher to re-point the candidate stderr.
_SANDBOX_STDERR = "/dev/.welp-capture-stderr"
# Canonical-argv placeholder standing in for the launch-status descriptor
# number, so the recorded argv is deterministic across runs.
_STDERR_FD_TOKEN = "<host-stderr-fd>"

# In-sandbox frozen launcher: resolves the frozen executable (execv does not
# search PATH; it is exec'd only after the resolved file is verified to
# exist and be executable, so a missing interpreter fails BEFORE any launch
# marker), re-points the candidate stderr at _SANDBOX_STDERR, reports the
# verified launch on the private control descriptor (which the candidate
# never holds), then execs the frozen command verbatim (same pid, same argv
# tail). Exit 127 = frozen executable/capture bind unavailable (integration);
# exit 126 = kernel refused exec of a verified executable (residual, exotic).
_LAUNCHER = (
    "import os, sys, resource\n"
    "_a = sys.argv[1:]\n"
    "_e = _a[0]\n"
    "if not os.path.isabs(_e):\n"
    "    _h = None\n"
    "    for _d in os.get_exec_path():\n"
    "        _p = os.path.join(_d, _e)\n"
    "        if os.path.isfile(_p) and os.access(_p, os.X_OK):\n"
    "            _h = _p\n"
    "            break\n"
    "    if _h is None:\n"
    "        sys.exit(127)\n"
    "    _e = _h\n"
    "elif not (os.path.isfile(_e) and os.access(_e, os.X_OK)):\n"
    "    sys.exit(127)\n"
    "try:\n"
    "    _fe = os.open(" + repr(_SANDBOX_STDERR) + ","
    " os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)\n"
    "except OSError:\n"
    "    sys.exit(127)\n"
    "resource.setrlimit(resource.RLIMIT_NPROC, (" + str(RLIMIT_NPROC) + ", " + str(RLIMIT_NPROC) + "))\n"
    "_c = os.dup(2)\n"
    "os.set_inheritable(_c, False)\n"
    "os.dup2(_fe, 2)\n"
    "os.write(_c, " + repr((BOUNDARY_MARKER + "\n").encode()) + ")\n"
    "try:\n"
    "    os.execv(_e, _a)\n"
    "except OSError:\n"
    "    os._exit(126)\n"
)


def _record(available, executed=False, reason=None, argv=None, exit_code=None,
            stdout="", stderr="", timed_out=False, extracted=None,
            output_truncated=None):
    out = {"available": bool(available), "executed": bool(executed),
           "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
           "timed_out": bool(timed_out),
           "extracted": extracted or {"found": False, "fence": None,
                                      "detail": "not attempted"}}
    if reason is not None:
        out["reason"] = str(reason)
    if argv is not None:
        out["argv"] = list(argv)
    if output_truncated is not None:
        out["output_truncated"] = output_truncated
    return out


def extract_code(content: str) -> dict:
    """Deterministic fenced-code extraction from a model answer.

    Rule (frozen): prefer the first fenced block explicitly tagged python /
    python3 / py; otherwise, if the answer contains exactly one fenced block,
    use it; otherwise nothing is extracted and the task's format gate fails
    deterministically. The exact rule and chosen fence are recorded so
    offline reconstruction derives identical bytes.
    """
    if not isinstance(content, str):
        return {"found": False, "fence": None, "detail": "no string content"}
    blocks = [(m.group(1).lower(), m.group(2)) for m in _FENCE_RE.finditer(content)]
    if not blocks:
        return {"found": False, "fence": None, "detail": "no fenced code block"}
    for lang, code in blocks:
        if lang in _PYTHON_FENCE_LANGS:
            return {"found": True, "fence": lang or None,
                    "detail": "first python-tagged fence", "code": code}
    if len(blocks) == 1:
        lang, code = blocks[0]
        return {"found": True, "fence": lang or None,
                "detail": "single untagged fence", "code": code}
    return {"found": False, "fence": None,
            "detail": f"{len(blocks)} untagged fenced blocks, no python tag"}


def _safe_relpath(name) -> str:
    if (not isinstance(name, str) or not name or name.startswith("/")
            or ".." in Path(name).parts or Path(name).is_absolute()
            or Path(name).drive or "\x00" in name):
        raise ValueError(f"unsafe sandbox file path: {name!r}")
    return name


def _set_rlimits(timeout_seconds: float) -> None:
    """Pre-exec child limits: the whole bwrap tree inherits these."""
    cpu = int(math.ceil(timeout_seconds)) + RLIMIT_CPU_GRACE_SECONDS
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS,
                       (RLIMIT_ADDRESS_SPACE_BYTES, RLIMIT_ADDRESS_SPACE_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE,
                       (RLIMIT_FSIZE_BYTES, RLIMIT_FSIZE_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (RLIMIT_NOFILE, RLIMIT_NOFILE))


def _bwrap_argv(workdir: Path, inner_argv: list[str],
                timeout_seconds: float) -> list[str]:
    seconds = int(math.ceil(timeout_seconds))
    return [
        "bwrap",
        "--unshare-all",          # pid, net, ipc, user, uts — no network, no host processes
        "--die-with-parent",
        "--new-session",
        "--clearenv",             # no inherited environment, credentials or tokens
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/sbin", "/sbin",
        "--proc", "/proc",        # fresh procfs of the sandbox pid namespace
        "--dev", "/dev",          # minimal fresh devtmpfs, no host devices
        "--tmpfs", "/tmp",        # disposable scratch; never the host tmp
        # Candidate stderr capture: a bind of the host-opened descriptor (a
        # single inode, exposed at one fixed path) — never a writable host
        # directory, so no sandbox path aliases a host file and the captured
        # stream cannot be replaced by a symlink.
        "--bind-fd", _STDERR_FD_TOKEN, _SANDBOX_STDERR,
        "--chdir", "/work",
        "--ro-bind", str(workdir), "/work",   # candidate/tests: read-only, untouchable
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/tmp",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "PYTHONHASHSEED", "0",          # deterministic run to run
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONUNBUFFERED", "1",
        "--",
        "timeout", "-k", str(_TIMEOUT_KILL_GRACE_SECONDS), str(seconds),
        "python3", "-c", _LAUNCHER,
        *inner_argv,
    ]


def canonical_argv(argv: list[str], workdir: Path) -> list[str]:
    """Stable-record form of the argv: the random host scratch path is
    redacted to its fixed sandbox mount point so scoring reconstruction is
    deterministic for the same model output. The launch-status descriptor
    number already appears as its fixed placeholder token."""
    return ["/work" if p == str(workdir) else p for p in argv]


def bwrap_usable() -> tuple[bool, str | None]:
    """Cheap presence pre-check; real usability is only ever OBSERVED by
    actually running the boundary (probe / _run_files), never assumed."""
    if shutil.which("bwrap") is None:
        return False, "bwrap executable not found"
    return True, None


def _read_capped(fd: int, limit: int = _MAX_CAPTURE_BYTES, *, rewind=True) -> tuple[str, bool]:
    """Read at most ``limit + 1`` bytes, rewinding regular captures only."""
    if rewind:
        os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    truncated = len(data) > limit
    return data[:limit].decode("utf-8", errors="replace"), truncated


def _run_files(files: dict[str, str], inner_argv: list[str],
               timeout_seconds: float) -> dict:
    ok, reason = bwrap_usable()
    if not ok:
        return _record(False, reason=reason)
    if (not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise ValueError(
            f"timeout_seconds must be in (0, {MAX_TIMEOUT_SECONDS}], got {timeout_seconds!r}")
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="run-", dir=WORKSPACE_ROOT))
    # Private host-side capture scratch; it is never mounted as a directory,
    # so the candidate has no path to it inside the sandbox.
    capdir = Path(tempfile.mkdtemp(prefix="run-cap-", dir=WORKSPACE_ROOT))
    host_timeout = timeout_seconds + _TIMEOUT_KILL_GRACE_SECONDS + _HOST_STARTUP_GRACE_SECONDS
    fd_out = fd_err = ctl_r = ctl_w = None
    try:
        for name, text in files.items():
            target = workdir / _safe_relpath(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        # Host-opened capture descriptors: regular files created before
        # launch, passed to the sandbox as stdout/stderr and read back from
        # the SAME descriptors with a hard byte cap — the host never reopens
        # a capture name after launch, so no candidate-controlled path is
        # ever resolved on the host filesystem.
        fd_out = os.open(capdir / "stdout",
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        fd_err = os.open(capdir / "stderr",
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        # Boundary control channel: carries bwrap/timeout diagnostics plus
        # the launcher's verified-launch marker. The sandbox stderr points
        # here until the launcher redirects it to the captured stderr inode,
        # so the candidate never holds a descriptor to this pipe.
        ctl_r, ctl_w = os.pipe()
        argv = _bwrap_argv(workdir, inner_argv, timeout_seconds)
        spawn_argv = [str(fd_err) if p == _STDERR_FD_TOKEN else p for p in argv]
        try:
            proc = subprocess.run(
                spawn_argv, stdin=subprocess.DEVNULL,
                stdout=fd_out, stderr=ctl_w, pass_fds=(ctl_w, fd_err),
                timeout=host_timeout,
                preexec_fn=lambda: _set_rlimits(timeout_seconds),
                start_new_session=True)
        except subprocess.TimeoutExpired:
            # The boundary itself hung (bwrap startup, not the model's run —
            # the inner `timeout` would already have fired). subprocess.run
            # killed the bwrap child; the sandbox pid namespace dies with it.
            # Integration condition, never model evidence.
            return _record(False, reason="bwrap boundary did not terminate within the "
                                         "host-side startup ceiling (integration)")
        os.close(ctl_w)
        ctl_w = None
        control, _ = _read_capped(ctl_r, _MAX_CONTROL_BYTES, rewind=False)
        stdout, stdout_trunc = _read_capped(fd_out)
        stderr, stderr_trunc = _read_capped(fd_err)
        if BOUNDARY_MARKER not in control:
            # The launcher never reported a verified launch: bwrap/namespace
            # denial, mount failure, missing runtime or missing frozen
            # executable — an integration condition, never model evidence
            # (the candidate cannot write this channel, so it cannot fake a
            # missing interpreter into model data either).
            diagnostic = stderr.strip() or control.strip()
            return _record(
                False, reason="sandbox boundary failed to launch (integration): "
                              f"exit {proc.returncode}: "
                              + diagnostic.strip()[:400])
        timed_out = proc.returncode in (124, 137)
        return _record(True, executed=True,
                       argv=canonical_argv(argv, workdir),
                       exit_code=proc.returncode, stdout=stdout, stderr=stderr,
                       timed_out=timed_out,
                       output_truncated={"stdout": stdout_trunc, "stderr": stderr_trunc})
    except OSError as exc:
        return _record(False, reason=f"sandbox boundary execution failed: {exc}")
    finally:
        for fd in (ctl_r, ctl_w, fd_out, fd_err):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(capdir, ignore_errors=True)


def probe() -> dict:
    """OBSERVED in-sandbox interpreter self-check for integration use only.

    Actually executes the boundary (never just a which() lookup) and reports
    whether the launcher marker appeared and the interpreter ran cleanly.
    Returns the same record shape with available/executed flags and no model
    data.
    """
    return _run_files({}, ["python3", "-c", "print('welp-sandbox-ok')"],
                      min(30, MAX_TIMEOUT_SECONDS))


def execute_probe(check: dict, submission_text: str, *, timeout_seconds: float) -> dict:
    """Run the frozen task oracle against extracted generated code.

    check: the task's frozen check block.
      - kind "python_unittest": writes the extracted code to check["entry"]
        (default solution.py) plus the frozen trusted test module, then runs
        ["python3", "-B", "-m", "unittest", <module>].
      - kind "python_unittest_discover": overlays the extracted code onto the
        frozen repository files at check["target"], then runs check["command"].
    submission_text: the FULL final assistant message; extraction happens
    here so offline reconstruction derives identical bytes.

    The record preserves the exact generated-code/test identities (byte
    content and sha-256 of every file the harness wrote, plus the canonical
    argv) so the report can independently verify the extraction/oracle
    binding without any host execution. It carries no elapsed-time field;
    stdout/stderr are preserved verbatim as evidence (unittest writes its
    result stream — including the final OK — to stderr; the captured
    descriptors are read back verbatim, bounded, and scoring never parses
    their timing lines).
    """
    if not isinstance(check, dict) or check.get("kind") not in (
            "python_unittest", "python_unittest_discover"):
        raise ValueError(f"unsupported sandbox check kind: {check.get('kind')!r}")
    extraction = extract_code(submission_text)
    code = extraction.get("code")
    if not extraction["found"]:
        # Deterministic decisive format failure for the task; the boundary is
        # fine, there is simply nothing admissible to execute.
        return _record(True, executed=False, reason="no admissible code block",
                       extracted=extraction)
    extraction = dict(extraction)
    if check["kind"] == "python_unittest":
        entry = _safe_relpath(check.get("entry", "solution.py"))
        module = check.get("module", "test_submission")
        files = {entry: code, f"{module}.py": check["tests"]}
        command = ["python3", "-B", "-m", "unittest", module]
    else:
        repository = dict(check["repository"])
        target = _safe_relpath(check["target"])
        repository[target] = code
        files = repository
        command = list(check["command"])
    record = _run_files(files, command, timeout_seconds)
    record["extracted"] = extraction
    # Exact harness identities: candidate code, every frozen file, command.
    import hashlib
    record["harness"] = {
        "kind": check["kind"],
        "command": command,
        "boundary_marker": BOUNDARY_MARKER,
        "readonly_work": True,
        "entry": entry if check["kind"] == "python_unittest" else None,
        "module": module if check["kind"] == "python_unittest" else None,
        "target": target if check["kind"] == "python_unittest_discover" else None,
        "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "code": code,
        "files_sha256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                         for name, text in sorted(files.items())},
    }
    return record


def no_code_found(record: dict) -> bool:
    """Whether an execute_probe record is the deterministic decisive
    'no admissible code block' format failure (available boundary, nothing
    executed, extraction exhaustively negative) — a model finding, never an
    integration condition."""
    return bool(record and record.get("available") and not record.get("executed")
                and record.get("reason") == "no admissible code block")


def tests_pass(record: dict) -> bool | None:
    """Deterministic mechanical verdict from an execute_probe record.

    True iff the boundary executed the harness and unittest reported OK with
    exit code 0. unittest writes its result stream to STDERR, so the frozen
    OK marker is searched across the combined captured streams. None means
    the execution itself is not usable as evidence (boundary unavailable,
    never launched, or an exit-code/marker split) — an integration condition
    the caller must map to INVALID, never to a model outcome.

    A record with ``timed_out`` reports False (the harness produced no
    completed OK within its budget); that flag itself is the resource-
    exhaustion fact, and mapping it to the BUDGET outcome — never to a
    semantic FAIL — is owned by the scoring layer, not here.
    """
    if not isinstance(record, dict) or not record.get("available") or not record.get("executed"):
        return None
    if record.get("timed_out"):
        return False
    combined = "\n".join((record.get("stdout") or "", record.get("stderr") or ""))
    ok_line = re.search(r"^OK\b", combined, re.M)
    exit_ok = record.get("exit_code") == 0
    if exit_ok != bool(ok_line):
        # unittest keeps exit code and the OK marker in lockstep; a split is
        # a harness/execution defect, not model evidence.
        return None
    return bool(exit_ok and ok_line)


def main() -> int:  # pragma: no cover - integration helper
    """Sandbox boundary probe; exit 0 iff the boundary executed cleanly."""
    result = probe()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("available") and result.get("executed") and result.get("exit_code") == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
