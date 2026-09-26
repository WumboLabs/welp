"""Evaluator-only acceptance for the qualification mini-task (trusted)."""
import shutil
import tempfile
from pathlib import Path

import agentic


def extra_checks(record, transcript, workspace, fixture):
    ws = Path(workspace)
    with tempfile.TemporaryDirectory(prefix="qual-accept-") as td:
        run_dir = Path(td) / "w"
        agentic.copy_tree_lenient(ws, run_dir)
        sb = agentic.Sandbox(run_dir, command_timeout_sec=30)
        obs = sb.run("./run_tests.sh")
        check = {"id": "acceptance", "pass": bool(obs.get("ok")),
                 "detail": (obs.get("stdout", "") + obs.get("stderr", ""))[-280:]}
    return {"checks": [check], "acceptance_pass": check["pass"]}
