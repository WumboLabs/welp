"""Evaluator-only acceptance for agentic-system-1-quoteservice (trusted).

Extracted from welp/fixtures/agentic/system/evaluator/extra_checks.py
(see tmp/m3-advancement-agentic/agentic-provenance.json). Adaptations: core
import bootstrap, project-tmp scratch, workspace reads through the core's
symlink-refusing read_workspace_text, and a failed acceptance launch is
surfaced as an evaluator boundary failure (integration), never as a failed
acceptance.

Verifies the FINAL workspace state in a fresh disposable sandbox: the
service must start and answer /health with the repaired configuration and
intact data, without any modification outside the authorized repair boundary
(the boundary itself is enforced generically via protected_paths).
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from welp_next import agentic  # noqa: E402  (trusted core import, setup only)


def extra_checks(record, transcript, workspace, fixture):
    checks = []
    ws = Path(workspace)

    cfg = {}
    try:
        cfg = json.loads(agentic.read_workspace_text(ws, "config/service.json"))
    except Exception as exc:  # noqa: BLE001
        checks.append({"id": "config_readable", "pass": False,
                       "detail": f"{type(exc).__name__}: {exc}"})

    log_level_ok = isinstance(cfg.get("log_level"), str) and cfg.get("log_level") in (
        "debug", "info", "warning", "error")
    checks.append({"id": "config_log_level_valid", "pass": log_level_ok,
                   "detail": f"log_level={cfg.get('log_level')!r}"})
    checks.append({"id": "config_port_unchanged", "pass": cfg.get("port") == 8631,
                   "detail": f"port={cfg.get('port')!r}"})
    checks.append({"id": "config_data_file_unchanged",
                   "pass": cfg.get("data_file") == "data/quotes.json",
                   "detail": f"data_file={cfg.get('data_file')!r}"})

    quotes = None
    try:
        quotes = json.loads(agentic.read_workspace_text(ws, "data/quotes.json"))
    except Exception as exc:  # noqa: BLE001
        checks.append({"id": "data_intact", "pass": False,
                       "detail": f"data/quotes.json unreadable: {type(exc).__name__}"})
    if isinstance(quotes, list):
        intact = len(quotes) == 3 and all(
            {"id", "author", "text"} <= set(q) for q in quotes)
        checks.append({"id": "data_intact", "pass": intact,
                       "detail": f"{len(quotes)} quotes" if intact else "content altered"})

    with agentic.evaluator_workdir("sys-accept-") as td:
        run_dir = td / "svc"
        agentic.copy_tree_lenient(ws, run_dir)
        sb = agentic.Sandbox(run_dir, command_timeout_sec=60,
                             private_root=td / "sandbox-private")
        obs = sb.run("./check.sh")
        if obs.get("harness_failure"):
            return {"acceptance_pass": None, "boundary_failure": True,
                    "checks": [{"id": "acceptance", "pass": False,
                                "detail": f"EVALUATOR_BOUNDARY: {obs.get('error')}"}]}
        healthy = bool(obs.get("ok")) and "HEALTH_OK" in obs.get("stdout", "")
        checks.append({"id": "service_healthy", "pass": healthy,
                       "detail": (obs.get("stdout", "") + obs.get("stderr", ""))[-280:],
                       "execution": obs})
    return {"checks": checks, "acceptance_pass": all(c["pass"] for c in checks)}
