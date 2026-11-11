"""Evaluator-only acceptance for agentic-repository-1-notes-cli.

TRUSTED evaluator code. Extracted from
welp/fixtures/agentic/repository/evaluator/extra_checks.py (adaptations
documented in tmp/m3-advancement-agentic/agentic-provenance.json: core import
bootstrap, project-tmp scratch, trusted suite driver). Both suites run
through the core's isolated stdlib-unittest driver OUTSIDE the candidate
import path (a candidate unittest.py cannot shadow the runner; a candidate
os._exit(0) cannot fake a pass because the frozen per-test and summary
receipts are mandatory). The agent-facing ./run_tests.sh stays the model's
own verification channel only. Hidden tests are copied into the fresh
acceptance namespace only after the agent's sandbox is gone.

Trusted frozen minimums: tests/test_notes.py defines exactly 4 tests;
evaluator/hidden_tests/test_acceptance.py defines exactly 7 tests.
"""
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from welp_next import agentic  # noqa: E402  (trusted core import, setup only)

MINIMUM_VISIBLE = 4
MINIMUM_HIDDEN = 7


def extra_checks(record, transcript, workspace, fixture):
    checks = []
    ws = Path(workspace)
    with agentic.evaluator_workdir("repo-accept-") as td:
        visible = td / "visible"
        agentic.copy_tree_lenient(ws, visible)
        sb = agentic.Sandbox(visible, command_timeout_sec=60,
                             private_root=td / "sandbox-private-visible")
        receipt = agentic.run_trusted_suite(sb, "/workspace/tests", "/workspace",
                                            minimum=MINIMUM_VISIBLE)
        if receipt.get("boundary_failure"):
            return {"acceptance_pass": None, "boundary_failure": True,
                    "checks": [{"id": "acceptance", "pass": False,
                                "detail": f"EVALUATOR_BOUNDARY: {receipt['detail']}"}]}
        checks.append({"id": "visible_tests_pass", "pass": bool(receipt["trusted"]),
                       "detail": receipt["detail"], "execution": receipt["execution"],
                       "minimum_tests": MINIMUM_VISIBLE})

        hid = td / "hidden"
        agentic.copy_tree_lenient(ws, hid)
        shutil.copytree(fixture.evaluator / "hidden_tests", hid / "hidden_tests")
        sb2 = agentic.Sandbox(hid, command_timeout_sec=60,
                              private_root=td / "sandbox-private-hidden")
        receipt2 = agentic.run_trusted_suite(sb2, "/workspace/hidden_tests", "/workspace",
                                             minimum=MINIMUM_HIDDEN)
        if receipt2.get("boundary_failure"):
            return {"acceptance_pass": None, "boundary_failure": True,
                    "checks": [{"id": "acceptance", "pass": False,
                                "detail": f"EVALUATOR_BOUNDARY: {receipt2['detail']}"}]}
        checks.append({"id": "hidden_acceptance_pass", "pass": bool(receipt2["trusted"]),
                       "detail": receipt2["detail"], "execution": receipt2["execution"],
                       "minimum_tests": MINIMUM_HIDDEN})
    return {"checks": checks, "acceptance_pass": all(c["pass"] for c in checks)}
