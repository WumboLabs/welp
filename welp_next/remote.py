"""Optional operating-agent utility for safely draining its owned local runner.

Not scientific admission. WELP never uses this module to contact an inference
host, fingerprint SSH, inspect a GPU or verify the owner's deployment claims.
"""
import math
import os
from pathlib import Path
import signal
import subprocess
import time

from . import policy


def process(pid):
    """Current owned-process identity for safe teardown, not historical admission."""
    p = Path('/proc') / str(pid)
    exe = str((p / 'exe').resolve(strict=True))
    return {'pid': pid, 'uid': p.stat().st_uid, 'executable': exe,
            'executable_sha256': policy.file_sha(exe),
            'argv': [os.fsdecode(x) for x in (p / 'cmdline').read_bytes().split(b'\0') if x],
            'start_ticks': (p / 'stat').read_text().rsplit(')', 1)[1].split()[19]}


def drain_owned_runner(child, identity, timeout):
    """Drain a current owned Popen incarnation before its owner stops inference.

    This is a destructive-action ownership check, not a scientific model gate.
    """
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not math.isfinite(timeout) or timeout <= 0):
        raise policy.CheckError('teardown.timeout: positive finite allowance required')
    until = time.monotonic() + timeout
    forced = False

    def owned():
        observed = process(child.pid)
        fields = ('pid', 'uid', 'executable', 'executable_sha256', 'argv', 'start_ticks')
        if (identity.get('pid') != child.pid or identity.get('uid') != os.getuid()
                or any(observed.get(k) != identity.get(k) for k in fields)
                or os.getpgid(child.pid) != child.pid):
            raise policy.CheckError('teardown.ownership: runner incarnation/group changed')

    if child.poll() is None:
        owned()
        child.send_signal(signal.SIGINT)
    reserve = min(2.0, timeout / 2)
    try:
        out, err = child.communicate(timeout=max(0, until-time.monotonic()-reserve))
    except subprocess.TimeoutExpired:
        forced = True
        if child.poll() is None:
            owned()
            os.killpg(child.pid, signal.SIGKILL)
        try:
            out, err = child.communicate(timeout=max(0, until-time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise policy.CheckError('teardown.quiescence: owned runner did not drain') from exc
    return {'quiescent': True, 'forced': forced,
            'failure_class': 'CONTROLLED_TEARDOWN_TIMEOUT' if forced else None,
            'pid': child.pid, 'start_ticks': identity['start_ticks'],
            'returncode': child.returncode, 'stdout': out, 'stderr': err}
