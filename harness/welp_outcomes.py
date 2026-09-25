#!/usr/bin/env python3
"""welp_outcomes.py — canonical CP-1 outcome semantics (welp-phase-harness/1).

Single source of truth for task-instance outcome vocabulary and derivation
rules (contracts/welp-outcomes-0.1.0-draft.json). The reliability scorer
implements the matching logic; this module exposes the shared vocabularies,
the completion/budget derivation, and record validation so every phase module
and campaign wrapper emits identical outcome records.

Selftest: python3 harness/welp_outcomes.py selftest
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scorers"))
from score_reliability import (  # noqa: E402,F401
    SCORER_IDENTITY, SEMANTIC_VOCAB, COMPLETION_VOCAB, BUDGET_VOCAB,
    derive_completion, derive_budget, score_row, aggregate,
    _REASONING_STATES_FALSE as REASONING_STATES_FALSE,
    _REASONING_STATES_TRUE as REASONING_STATES_TRUE,
)

HARNESS_IDENTITY = "welp-phase-harness/1.0.0-draft"
MODULE_ID = "welp-harness-outcomes/1.0.0-draft"
OUTCOMES_CONTRACT = "welp-outcomes-0.1.0-draft"

ATTRIBUTION_VOCAB = {"model", "runtime", "hardware", "scorer-artifact", "protocol-limitation", "unknown"}
CLAIM_CLASSES = {"MEASURED", "DERIVED", "INFERENCE", "HYPOTHESIS", "EXTERNAL_REPORTED", "UNKNOWN"}


def validate_record(rec: dict) -> list:
    errs = []
    for axis, vocab in (("semantic", SEMANTIC_VOCAB), ("completion", COMPLETION_VOCAB), ("budget", BUDGET_VOCAB)):
        if rec.get(axis) not in vocab:
            errs.append(f"{axis}={rec.get(axis)!r} not in {sorted(vocab)}")
    if "finish_reason" not in rec:
        errs.append("finish_reason required (verbatim; null when runtime does not expose it)")
    return errs


def selftest() -> int:
    fails = []
    # completion derivation table
    cases = [
        ("length", "", None, None, "FAIL_LENGTH"),
        ("length", "partial", None, None, "FAIL_LENGTH"),
        ("stop", "answer", None, None, "COMPLETE"),
        ("stop", "", None, None, "EMPTY_ANSWER"),
        (None, "answer", {"completion_tokens": 64}, 140, "COMPLETE"),
        (None, "", {"completion_tokens": 140}, 140, "FAIL_LENGTH"),
        (None, "", {"completion_tokens": 9}, 140, "EMPTY_ANSWER"),
        (None, "", None, None, "INVALID_STOP"),
        ("error", "answer", None, None, "INVALID_STOP"),
    ]
    for finish, content, usage, cap, want in cases:
        got = derive_completion(finish, content, usage, cap)
        if got != want:
            fails.append(f"derive_completion({finish!r}, {content!r}, {usage}, {cap}) = {got}, want {want}")
    # budget derivation table
    bcases = [
        ("length", "FAIL_LENGTH", "text", False, None, "EXHAUSTED_IN_ANSWER"),
        ("length", "FAIL_LENGTH", "", True, None, "EXHAUSTED_IN_REASONING"),
        ("length", "FAIL_LENGTH", "", False, False, "EXHAUSTED_IN_ANSWER"),
        ("length", "FAIL_LENGTH", "", False, True, "UNKNOWN"),
        ("length", "FAIL_LENGTH", "", False, None, "UNKNOWN"),
        ("stop", "COMPLETE", "text", False, None, "WITHIN"),
        ("stop", "EMPTY_ANSWER", "", True, None, "WITHIN"),
        ("error", "INVALID_STOP", "x", False, None, "UNKNOWN"),
        ("length", "FAIL_LENGTH", "", False, None, "UNKNOWN"),
    ]
    for finish, completion, content, has_reas, declared, want in bcases:
        got = derive_budget(finish, completion, content, has_reas, declared)
        if got != want:
            fails.append(f"derive_budget({finish!r}, {completion!r}, {content!r}, {has_reas}, {declared}) = {got}, want {want}")
    # split override
    got = derive_budget("length", "FAIL_LENGTH", "", False, None, reasoning_tokens=512, answer_tokens=0)
    if got != "EXHAUSTED_IN_REASONING":
        fails.append(f"split budget reasoning exhausted = {got}")
    got = derive_budget("length", "FAIL_LENGTH", "partial", True, None, reasoning_tokens=400, answer_tokens=112)
    if got != "EXHAUSTED_IN_ANSWER":
        fails.append(f"split budget answer exhausted = {got}")
    # record validation
    if validate_record({"semantic": "PASS", "completion": "COMPLETE", "budget": "WITHIN", "finish_reason": "stop"}):
        fails.append("valid record rejected")
    if not validate_record({"semantic": "MAYBE", "completion": "COMPLETE", "budget": "WITHIN", "finish_reason": "stop"}):
        fails.append("invalid semantic accepted")
    if not validate_record({"semantic": "PASS", "completion": "COMPLETE", "budget": "WITHIN"}):
        fails.append("missing finish_reason accepted")
    # aggregate shape
    recs = [
        {"semantic": "PASS", "completion": "COMPLETE", "budget": "WITHIN", "finish_reason": "stop"},
        {"semantic": "FAIL", "completion": "COMPLETE", "budget": "WITHIN", "finish_reason": "stop"},
        {"semantic": "NOT_EVALUABLE", "completion": "FAIL_LENGTH", "budget": "EXHAUSTED_IN_REASONING", "finish_reason": "length"},
    ]
    ag = aggregate(recs)
    if abs(ag["completion_rate"] - 2 / 3) > 1e-9 or ag["truncation_rate"] != 1 / 3:
        fails.append(f"aggregate rates wrong: {ag}")
    if ag["semantic_clean_rate_conditional"] != 0.5 or ag["not_evaluable"] != 1:
        fails.append(f"aggregate semantic wrong: {ag}")
    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
