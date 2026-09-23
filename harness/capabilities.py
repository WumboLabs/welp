#!/usr/bin/env python3
"""capabilities.py — canonical capability-probe module (welp-phase-harness/1).

Declares the frozen budget/lanes for the Phase-5 capability probes and maps
probe outcomes onto CP-1 semantics. Probes are executed by campaigns against
the pinned runtime; scoring and budget semantics live here so probes stop
being per-campaign script copies.

Frozen probe budgets (welp-generation-budget 0.1.0-draft):
  reasoning  frozen lane 1500 total (comparability) + operational lane 4096
             (non-binding ceiling; Qwen3.6 case: frozen FAIL_LENGTH / 4096 PASS)
  coding     frozen lane 400 (thinking-off profile) + diagnostic lane 1500
             (Bonsai case: capability present, budget-bound at 400 thinking-on)
  tools      200 total (adequate for a single structured call)

Selftest: python3 harness/capabilities.py selftest
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from welp_outcomes import derive_completion, derive_budget  # noqa: E402

MODULE_ID = "welp-harness-capabilities/1.0.0-draft"

PROBE_BUDGETS = {
    "reasoning": {
        "frozen_lane_generation_ceiling": 1500,
        "operational_lane_generation_ceiling": 4096,
        "rationale": "Frozen 1500 preserves cross-campaign comparability; 4096 is the declared non-starving operational ceiling selected from retained evidence (a reasoning model producing a coherent trace with no final answer at 1500 and PASS at 4096). No single reasoning score is reported: frozen-lane and operational-lane results are separate records.",
    },
    "coding": {
        "frozen_lane_generation_ceiling": 400,
        "diagnostic_lane_generation_ceiling": 1500,
        "rationale": "400 with the declared reasoning control (thinking-off) is canonical; the 1500 diagnostic lane separates budget-bound failures from capability absence (retained evidence: FAIL at 400 thinking-on, PASS at 400 thinking-off AND at 1500 thinking-on).",
    },
    "tools": {
        "frozen_lane_generation_ceiling": 200,
        "rationale": "One structured call plus a short grounded continuation; measured calls complete far below 200.",
    },
    "structured_interfaces": {
        "frozen_lane_generation_ceiling": 300,
        "rationale": "Small strict-JSON outputs; formatting margin around a <100-token reference.",
    },
}

REPORTED_FIELDS = ["semantic", "completion", "budget", "finish_reason",
                   "reasoning_tokens", "answer_tokens",
                   "time_to_first_reasoning_token", "time_to_final_answer"]


def probe_outcome(probe: str, check_pass, row: dict, lane: str = "frozen",
                  ceiling: int | None = None) -> dict:
    budgets = PROBE_BUDGETS[probe]
    cap = ceiling if ceiling is not None else (budgets.get(f"{lane}_lane_generation_ceiling")
                                                or budgets.get("frozen_lane_generation_ceiling"))
    completion = derive_completion(row.get("finish"), row.get("output") or "",
                                   row.get("usage") or {}, cap)
    budget = derive_budget(row.get("finish"), completion, row.get("output") or "",
                           bool((row.get("usage") or {}).get("reasoning_tokens")))
    semantic = "NOT_EVALUABLE"
    if completion == "COMPLETE":
        semantic = "PASS" if check_pass else "FAIL"
    return {"probe": probe, "lane": lane, "ceiling": cap, "semantic": semantic,
            "completion": completion, "budget": budget,
            "finish_reason": row.get("finish")}


def score_tool_recovery(actions: list[dict]) -> dict:
    """Replay a frozen read-only simulated tool transcript, not real system calls."""
    fixture = json.loads((HERE.parent / "fixtures/real_work/tool-recovery.json").read_text())
    oracle = fixture["oracle"]
    order = oracle["required_order"]
    failures = []
    if not isinstance(actions, list) or len(actions) != len(order) + 1:
        return {"semantic": "FAIL", "failures": ["wrong action count"]}
    for i, tool in enumerate(order):
        action = actions[i]
        if not isinstance(action, dict) or action.get("tool") != tool:
            failures.append(f"tool choice/order {i}")
            continue
        args = action.get("arguments")
        wanted = {"path": "/etc/example/app.conf"} if i == 0 else {"name": "example.service"}
        if args != wanted:
            failures.append(f"arguments {i}")
        if set(action) != {"tool", "arguments"}:
            failures.append(f"tool action shape {i}")
    final = actions[-1]
    if not isinstance(final, dict) or set(final) != {"final"}:
        failures.append("missing final answer or extra call")
    else:
        text = final["final"]
        if (not isinstance(text, str) or "8452" not in text
                or "is active" not in text.lower() or "not active" in text.lower()):
            failures.append("ungrounded or incomplete final answer")
    return {"semantic": "FAIL" if failures else "PASS", "failures": failures,
            "tool_calls": len(actions) - 1,
            "simulated_results": [fixture["tools"]["read_config"]["response"],
                                  {"error": fixture["tools"]["check_service"]["error_first"]},
                                  fixture["tools"]["check_service"]["response"]]}


def score_multi_turn_final(content: str) -> dict:
    """Evaluate corrected facts, absent evidence and strict JSON on final turn."""
    fixture = json.loads((HERE.parent / "fixtures/real_work/multi-turn-correction.json").read_text())
    oracle = fixture["oracle"]
    failures = []

    def unique_pairs(pairs):
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("duplicate JSON keys")
        return dict(pairs)

    try:
        value = json.loads(content, object_pairs_hook=unique_pairs)
    except (TypeError, ValueError):
        value = None
        failures.append("strict JSON")
    if not isinstance(value, dict) or set(value) != set(oracle["exact_keys"]):
        failures.append("exact object keys")
    else:
        if value["service"] != oracle["service"]:
            failures.append("service retention")
        if type(value["port"]) is not int or value["port"] != oracle["port"]:
            failures.append("correction not incorporated")
        if value["health"] is not None:
            failures.append("absent health evidence fabricated")
    return {"semantic": "PASS" if not failures else "FAIL", "failures": failures}


def selftest_repository_fixture() -> list[str]:
    """Exercise only the trusted frozen baseline/reference, never model code."""
    import subprocess
    import tempfile

    fixture = json.loads((HERE.parent / "fixtures/real_work/repository-timeout.json").read_text())
    failures = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, source in fixture["repository"].items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
        baseline = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
        if baseline.returncode == 0 or "test_zero_is_explicit" not in baseline.stderr:
            failures.append("repository fixture baseline must fail at explicit zero")
        source = (root / "app/config.py").read_text()
        if source.count("return timeout or DEFAULT_TIMEOUT") != 1:
            failures.append("repository fixture baseline source changed")
        else:
            (root / "app/config.py").write_text(
                source.replace("return timeout or DEFAULT_TIMEOUT",
                               "return DEFAULT_TIMEOUT if timeout is None else timeout"))
            reference = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            if reference.returncode != 0 or "Ran 4 tests" not in reference.stderr:
                failures.append("repository fixture reference does not pass all tests")
        if (root / "tests/test_config.py").read_text() != fixture["repository"]["tests/test_config.py"]:
            failures.append("repository fixture tests changed")
    return failures


def selftest() -> int:
    fails = []
    r = probe_outcome("reasoning", True, {"output": "...final answer...", "finish": "stop"})
    if r["ceiling"] != 1500 or r["semantic"] != "PASS":
        fails.append(f"frozen reasoning lane: {r}")
    r = probe_outcome("reasoning", True, {"output": "...final answer...", "finish": "stop"}, lane="operational")
    if r["ceiling"] != 4096:
        fails.append("operational reasoning lane must be 4096")
    # Answerless reasoning at the frozen cap is not a semantic failure.
    r = probe_outcome("reasoning", None, {"output": "", "finish": "length",
                                          "usage": {"completion_tokens": 1500, "reasoning_tokens": 1500}})
    if r["semantic"] != "NOT_EVALUABLE" or r["budget"] != "EXHAUSTED_IN_REASONING":
        fails.append(f"reasoning frozen starvation: {r}")
    # Bonsai coding case: 400 thinking-on truncated, 400 thinking-off complete pass
    r = probe_outcome("coding", None, {"output": "", "finish": "length",
                                       "usage": {"completion_tokens": 400, "reasoning_tokens": 400}})
    if r["semantic"] != "NOT_EVALUABLE":
        fails.append("coding truncation must be NOT_EVALUABLE (budget artifact)")
    r = probe_outcome("coding", True, {"output": "def moving_sum...", "finish": "stop"})
    if r["ceiling"] != 400 or r["semantic"] != "PASS":
        fails.append(f"coding frozen lane: {r}")
    r = probe_outcome("tools", True, {"output": "calling get_temperature", "finish": "tool_calls"})
    if r["completion"] != "COMPLETE" or r["budget"] != "WITHIN":
        fails.append(f"tools tool_calls completion: {r}")
    for probe, b in PROBE_BUDGETS.items():
        if not b.get("rationale"):
            fails.append(f"{probe} missing budget rationale")
    actions = [
        {"tool": "read_config", "arguments": {"path": "/etc/example/app.conf"}},
        {"tool": "check_service", "arguments": {"name": "example.service"}},
        {"tool": "check_service", "arguments": {"name": "example.service"}},
        {"final": "example.service is active on port 8452."},
    ]
    if score_tool_recovery(actions)["semantic"] != "PASS":
        fails.append("valid sequential recovery must pass")
    if score_tool_recovery(actions[:1] + actions[2:])["semantic"] != "FAIL":
        fails.append("skipping failure must fail")
    if score_tool_recovery(actions[:-1] + [{"final": "example.service is active."}])["semantic"] != "FAIL":
        fails.append("ungrounded final must fail")
    if score_tool_recovery([actions[0], {**actions[1], "arguments": {"name": "other"}},
                            *actions[2:]])["semantic"] != "FAIL":
        fails.append("wrong tool arguments must fail")
    for text, want in [
        ('{\"health\": null, \"port\": 8652, \"service\": \"example.service\"}', "PASS"),
        ('{\"health\": \"active\", \"port\": 8652, \"service\": \"example.service\"}', "FAIL"),
        ('{\"health\": null, \"port\": 8452, \"service\": \"example.service\"}', "FAIL"),
        ('{\"health\": null, \"port\": 8652, \"port\": 8652, \"service\": \"example.service\"}', "FAIL"),
        ('```json\\n{\"health\": null, \"port\": 8652, \"service\": \"example.service\"}\\n```', "FAIL"),
    ]:
        if score_multi_turn_final(text)["semantic"] != want:
            fails.append(f"multi-turn oracle mismatch: {text}")
    fails.extend(selftest_repository_fixture())
    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
