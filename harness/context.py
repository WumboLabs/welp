#!/usr/bin/env python3
"""context.py — canonical useful-context phase module (welp-phase-harness/1).

Implements CP-4 (protocol/context-scaling.md C3, methodology revision
2026-09-19): standardized 512-token output reserve, verbatim finish capture
requirements, CP-1 outcome records per request, rung dispositions including
BUDGET_LIMITED, and the depth-set/placement contract (2/25/50/75/95 with
0.25 pp preferred / 0.50 pp hard error).

Selftest: python3 harness/context.py selftest
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from welp_outcomes import derive_completion, derive_budget  # noqa: E402

MODULE_ID = "welp-harness-context/1.0.0-draft"
FIXTURE_FAMILY_A = HERE.parent / "fixtures/useful_context/family-a.json"

REQUIRED_DEPTHS_PCT = [2.0, 25.0, 50.0, 75.0, 95.0]
PLACEMENT_PREFERRED_PP = 0.25
PLACEMENT_HARD_PP = 0.50
OCCUPANCY_PREFERRED_PCT = 99.0
OCCUPANCY_HARD_PCT = 97.0

RESERVE_CONTRACT = "welp-generation-budget-0.1.0-draft"
GATE_ANSWER_BUDGET = 256
STANDARD_RESERVE_TOKENS = 512


def standardized_reserve(gate_answer_budget: int = GATE_ANSWER_BUDGET) -> int:
    """reserve = max(512, 2 x gate answer budget) — the one documented rule."""
    return max(512, 2 * gate_answer_budget)


def placement_errors(depths_pct):
    """Absolute errors vs the required depth set. depths_pct: {label: pct}."""
    required = sorted(REQUIRED_DEPTHS_PCT)
    observed = sorted(depths_pct.values())
    if len(observed) != len(required):
        return None, f"expected {len(required)} placed targets, got {len(observed)}"
    errs = [abs(o - r) for o, r in zip(observed, required)]
    return max(errs), None


def placement_preflight(depths_pct):
    err, problem = placement_errors(depths_pct)
    if problem:
        return {"pass": False, "error": problem}
    hard_ok = err <= PLACEMENT_HARD_PP
    pref_ok = err <= PLACEMENT_PREFERRED_PP
    return {"pass": hard_ok, "max_error_pp": round(err, 3),
            "preferred": pref_ok, "hard": hard_ok}


def rung_outcome(gates: dict, finish, content: str, usage: dict = None,
                 reserve: int = STANDARD_RESERVE_TOKENS):
    """Assemble the CP-1 outcome + rung disposition for one useful-context request.

    gates: {"exact_retrieval": bool, "synthesis": bool, "decoy_resistance": bool,
            "absent_information": bool, "retrieval_95": bool, "instruction_compliance": bool}
    A gate left None (not evaluated because no answer exists) stays None.
    """
    completion = derive_completion(finish, content, usage, reserve)
    has_reasoning = bool((usage or {}).get("reasoning_tokens"))
    budget = derive_budget(finish, completion, content, has_reasoning)

    answered = content.strip() != ""
    gate_values = {k: (v if answered else None) for k, v in gates.items()}
    evaluated = [v for v in gate_values.values() if v is not None]

    if completion == "COMPLETE":
        all_pass = all(gate_values.values())
        rung = "VALIDATED" if all_pass else "FAILED"
        semantic = "PASS" if all_pass else "FAIL"
    elif completion == "FAIL_LENGTH":
        # Bonsai 65K rule: strong retrieval/synthesis evidence with a starved
        # answer is BUDGET_LIMITED, never a retrieval failure; without any
        # usable answer the gates are simply not evaluable. A forbidden
        # assertion in the produced channel (decoy containment) keeps the
        # semantic FAIL evidence — truncation does not unsay it.
        strong = (gates.get("exact_retrieval") or gates.get("synthesis")) is True and answered
        rung = "BUDGET_LIMITED" if strong else "NOT_EVALUABLE"
        semantic = "FAIL" if _forbidden_asserted(gates) else "NOT_EVALUABLE"
    else:  # EMPTY_ANSWER / INVALID_STOP
        rung = "BUDGET_LIMITED" if completion == "EMPTY_ANSWER" else "INVALID_REQUEST"
        semantic = "NOT_EVALUABLE"

    return {
        "rung": rung,
        "semantic": semantic,
        "completion": completion,
        "budget": budget,
        "finish_reason": finish,
        "gates": gate_values,
        "reserve_tokens": reserve,
    }


def _forbidden_asserted(gates: dict) -> bool:
    # A decoy containment in a produced channel is positive evidence of a
    # wrong answer even when truncated.
    return gates.get("decoy_resistance") is False


def selftest() -> int:
    fails = []
    if standardized_reserve() != 512:
        fails.append(f"reserve rule: {standardized_reserve()}")
    if standardized_reserve(300) != 600:
        fails.append("reserve rule must be max(512, 2x budget)")

    pf = placement_preflight({"a": 1.99, "b": 24.99, "c": 49.89, "d": 74.84, "e": 94.944})
    if not (pf["pass"] and pf["preferred"]):
        fails.append(f"placement preflight should pass preferred: {pf}")
    pf = placement_preflight({"a": 2.4, "b": 25.0, "c": 50.0, "d": 75.0, "e": 95.0})
    if not (pf["pass"] and not pf["preferred"]):
        fails.append(f"0.4pp error should pass hard not preferred: {pf}")
    pf = placement_preflight({"a": 2.7, "b": 25.0, "c": 50.0, "d": 75.0, "e": 95.0})
    if pf["pass"]:
        fails.append("0.7pp error must fail hard bound")
    pf = placement_preflight({"a": 2.0, "b": 25.0, "c": 50.0, "d": 75.0})
    if pf["pass"]:
        fails.append("four-depth set must fail preflight (post-completion campaign practice)")

    all_pass = {"exact_retrieval": True, "synthesis": True, "decoy_resistance": True,
                "absent_information": True, "retrieval_95": True, "instruction_compliance": True}
    r = rung_outcome(all_pass, "stop", "1. TR-8842-QX ...", {"completion_tokens": 75})
    if r["rung"] != "VALIDATED" or r["semantic"] != "PASS" or r["budget"] != "WITHIN":
        fails.append(f"validated rung: {r}")

    # Bonsai 65K seed-42 shape: empty answer, 512 consumed, finish unavailable (ctx pre-revision)
    r = rung_outcome({"exact_retrieval": None, "synthesis": None, "decoy_resistance": True,
                      "absent_information": None, "retrieval_95": None, "instruction_compliance": None},
                     None, "", {"completion_tokens": 512})
    if r["completion"] != "FAIL_LENGTH" or r["semantic"] != "NOT_EVALUABLE":
        fails.append(f"bonsai empty-truncated shape: {r}")
    if r["rung"] not in ("BUDGET_LIMITED", "NOT_EVALUABLE"):
        fails.append(f"bonsai rung must not be FAILED: {r}")

    # BUDGET_LIMITED with strong retrieval evidence in a partial answer
    r = rung_outcome({"exact_retrieval": True, "synthesis": True, "decoy_resistance": True,
                      "absent_information": None, "retrieval_95": None, "instruction_compliance": None},
                     "length", "1. TR-8842-QX\n2. 2027", {"completion_tokens": 512})
    if r["rung"] != "BUDGET_LIMITED" or r["semantic"] != "NOT_EVALUABLE":
        fails.append(f"budget-limited rung: {r}")

    # Completed answer violating a gate -> FAILED, semantic FAIL
    r = rung_outcome({**all_pass, "absent_information": False}, "stop",
                     "1. TR-8842-QX ...\n3. TR-9999", {"completion_tokens": 90})
    if r["rung"] != "FAILED" or r["semantic"] != "FAIL":
        fails.append(f"failed gate rung: {r}")

    # Decoy asserted in a truncated channel -> semantic FAIL evidence retained
    r = rung_outcome({"exact_retrieval": True, "synthesis": None, "decoy_resistance": False,
                      "absent_information": None, "retrieval_95": None, "instruction_compliance": None},
                     "length", "1. TR-8842-QX; loading dock code TR-3319-WD", {"completion_tokens": 512})
    if r["semantic"] != "FAIL" or r["rung"] != "BUDGET_LIMITED":
        fails.append(f"decoy-in-truncated must keep FAIL evidence: {r}")

    # fixture sanity
    fx = json.loads(FIXTURE_FAMILY_A.read_text())
    if fx["construction"]["depths_required"] != [0.02, 0.25, 0.50, 0.75, 0.95]:
        fails.append("family A must carry the five contract depths")
    if fx["generation_budget"]["reserve_tokens"] != standardized_reserve():
        fails.append("family A reserve must equal the standardized reserve")

    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
