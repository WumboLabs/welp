"""Evaluator-only acceptance for the qualification mini-task (trusted).

Extracted from welp/fixtures/agentic/qualification/evaluator/extra_checks.py
(see tmp/m3-advancement-agentic/agentic-provenance.json). Adaptations: core
import bootstrap, project-tmp scratch, and the trusted acceptance suite runs
through the core's isolated suite driver (stdlib unittest outside the
candidate import path; the frozen visible tests are mandatory, so a candidate
unittest.py shadow or os._exit(0) cannot fake a pass). The agent-facing
./run_tests.sh stays the model's own verification channel only.

Trusted frozen minimum: tests/test_greet.py defines exactly 2 tests.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from welp_next import agentic  # noqa: E402  (trusted core import, setup only)

MINIMUM_TESTS = 2


def extra_checks(record, transcript, workspace, fixture):
    ws = Path(workspace)
    with agentic.evaluator_workdir("qual-accept-") as td:
        run_dir = td / "w"
        agentic.copy_tree_lenient(ws, run_dir)
        sb = agentic.Sandbox(run_dir, command_timeout_sec=30,
                             private_root=td / "sandbox-private")
        receipt = agentic.run_trusted_suite(sb, "/workspace/tests", "/workspace",
                                            minimum=MINIMUM_TESTS)
    if receipt.get("boundary_failure"):
        return {"acceptance_pass": None, "boundary_failure": True,
                "checks": [{"id": "acceptance", "pass": False,
                            "detail": f"EVALUATOR_BOUNDARY: {receipt['detail']}"}]}
    check = {"id": "acceptance", "pass": bool(receipt["trusted"]),
             "detail": receipt["detail"], "execution": receipt["execution"],
             "minimum_tests": MINIMUM_TESTS}
    return {"checks": [check], "acceptance_pass": check["pass"]}
