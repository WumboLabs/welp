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


def probe_outcome(probe: str, check_pass, row: dict, lane: str = "frozen") -> dict:
    budgets = PROBE_BUDGETS[probe]
    cap = budgets.get(f"{lane}_lane_generation_ceiling") or budgets.get("frozen_lane_generation_ceiling")
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


def selftest() -> int:
    fails = []
    r = probe_outcome("reasoning", True, {"output": "...final answer...", "finish": "stop"})
    if r["ceiling"] != 1500 or r["semantic"] != "PASS":
        fails.append(f"frozen reasoning lane: {r}")
    r = probe_outcome("reasoning", True, {"output": "...final answer...", "finish": "stop"}, lane="operational")
    if r["ceiling"] != 4096:
        fails.append("operational reasoning lane must be 4096")
    # Qwen3.6 case: no final answer at 1500 -> FAIL_LENGTH/NOT_EVALUABLE on frozen lane;
    # the same completed behavior at 4096 is a PASS on the operational lane.
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
    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
