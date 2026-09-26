"""Evaluator-only acceptance for agentic-repository-1-notes-cli.

TRUSTED evaluator code. Runs the agent's final workspace in FRESH disposable
sandboxes (the agent's edited program is untrusted and never executes in the
runner process). Hidden tests are copied in only after the agent's sandbox is
gone; the agent can never read them.
"""
import shutil
import tempfile
from pathlib import Path

import agentic


def extra_checks(record, transcript, workspace, fixture):
    checks = []
    ws = Path(workspace)
    with tempfile.TemporaryDirectory(prefix="repo-accept-") as td:
        td = Path(td)
        run_dir = td / "visible"
        agentic.copy_tree_lenient(ws, run_dir)
        sb = agentic.Sandbox(run_dir, command_timeout_sec=60)
        obs = sb.run("./run_tests.sh")
        tail = (obs.get("stdout", "") + obs.get("stderr", ""))[-280:]
        checks.append({"id": "visible_tests_pass", "pass": bool(obs.get("ok")),
                       "detail": f"rc={obs.get('exit_code')} :: {tail}"})

        hid = td / "hidden"
        agentic.copy_tree_lenient(ws, hid)
        shutil.copytree(fixture.evaluator / "hidden_tests", hid / "hidden_tests")
        sb2 = agentic.Sandbox(hid, command_timeout_sec=60)
        obs2 = sb2.run("python3 -m unittest discover -s hidden_tests -v")
        tail2 = (obs2.get("stdout", "") + obs2.get("stderr", ""))[-280:]
        checks.append({"id": "hidden_acceptance_pass", "pass": bool(obs2.get("ok")),
                       "detail": f"rc={obs2.get('exit_code')} :: {tail2}"})
    return {"checks": checks, "acceptance_pass": all(c["pass"] for c in checks)}
