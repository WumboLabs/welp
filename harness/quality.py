#!/usr/bin/env python3
"""quality.py — canonical quality-screen phase module (welp-phase-harness/1).

Scores the 12-task quality screen (fixtures/quality/welp-quality-screen-12-v1.json)
with machine-checkable predicates and CP-1 outcome records. Replaces the
per-campaign scorer copies whose predicates lived only in script code while the
fixture carried prose descriptions.

Selftest: python3 harness/quality.py selftest
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from welp_outcomes import derive_completion, derive_budget  # noqa: E402

MODULE_ID = "welp-harness-quality/1.0.0-draft"
FIXTURE = HERE.parent / "fixtures/quality/welp-quality-screen-12-v1.json"


def _check(spec: dict, content: str) -> bool:
    method = spec["method"]
    text = (content or "").strip()
    if method == "contains":
        if len(text) > spec.get("max_chars", 10 ** 6):
            return False
        if "any_values" in spec:
            if not any(v in text for v in spec["any_values"]):
                return False
        if not all(v in text for v in spec.get("values", [])):
            return False
        return not any(f in text for f in spec.get("forbid", []))
    if method == "exact_tokens":
        return text.split() == spec["tokens"]
    if method == "three_lowercase_words":
        words = text.split()
        if len(words) != 3 or not all(w.islower() for w in words):
            return False
        if any(re.search(r"[^\w\s]", w) for w in words):
            return False
        return spec["content"] in text
    if method == "no_letter":
        if len(text) <= spec.get("min_chars", 0):
            return False
        return spec["letter"] not in text.lower()
    if method == "json_object_exact":
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return False
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return False
        return obj == spec["keys"] and list(obj.keys()) == list(spec["keys"].keys())
    if method == "json_array_exact":
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return False
        try:
            arr = json.loads(m.group(0))
        except Exception:
            return False
        return arr == spec["value"]
    if method == "uncertainty_or_absent":
        low = text.casefold()
        if any(m in low for m in spec["uncertainty_markers"]):
            return True
        # A bare fabricated number (any digit) without an uncertainty marker fails.
        return not re.search(r"[0-9]", text)
    raise ValueError(f"unknown check method {method!r}")


def score_task(task: dict, row: dict, ceiling=None) -> dict:
    content = row.get("output") or ""
    finish = row.get("finish", row.get("finish_reason"))
    usage = row.get("usage") or {}
    cap = ceiling or row.get("max_tokens") or task.get("answer_budget") * 4
    completion = derive_completion(finish, content, usage, cap)
    budget = derive_budget(finish, completion, content, bool(usage.get("reasoning_tokens")))
    semantic, check_pass = "NOT_EVALUABLE", None
    if completion == "COMPLETE":
        check_pass = _check(task["check"], content)
        semantic = "PASS" if check_pass else "FAIL"
    return {"id": task["id"], "semantic": semantic, "completion": completion,
            "budget": budget, "finish_reason": finish, "check_pass": check_pass}


def selftest() -> int:
    fx = json.loads(FIXTURE.read_text())
    tasks = {t["id"]: t for t in fx["tasks"]}
    fails = []

    def run(qid, output, finish="stop", usage=None):
        return score_task(tasks[qid], {"output": output, "finish": finish, "usage": usage or {"completion_tokens": 20}})

    r = run("Q01", "100")
    if r["semantic"] != "PASS":
        fails.append("Q01 basic")
    r = run("Q01", "The boiling point of water is 100 degrees Celsius at sea level, officially speaking.")
    if r["semantic"] != "FAIL":
        fails.append("Q01 must enforce max_chars (verbose fail)")
    r = run("Q02", '{"name": "Ridgeline", "count": 7}')
    if r["semantic"] != "PASS":
        fails.append("Q02 exact object")
    r = run("Q02", 'Here it is: {"name": "Ridgeline", "count": 8}')
    if r["semantic"] != "FAIL":
        fails.append("Q02 wrong value")
    r = run("Q05", "NOT STATED")
    if r["semantic"] != "PASS":
        fails.append("Q05 absent-info")
    r = run("Q06", "nitrogen is the air")
    if r["semantic"] != "FAIL":
        fails.append("Q06 four words must fail")
    r = run("Q06", "Nitrogen is air.")
    if r["semantic"] != "FAIL":
        fails.append("Q06 uppercase/punctuation must fail")
    r = run("Q06", "nitrogen mostly yes")
    if r["semantic"] != "PASS":
        fails.append("Q06 three lowercase words")
    r = run("Q07", "kite kite kite kite kite")
    if r["semantic"] != "PASS":
        fails.append("Q07")
    r = run("Q09", "[3, 8, 15]")
    if r["semantic"] != "PASS":
        fails.append("Q09 array")
    r = run("Q10", "0")
    if r["semantic"] != "PASS":
        fails.append("Q10 zero moons")
    r = run("Q11", "UNKNOWN")
    if r["semantic"] != "PASS":
        fails.append("Q11 uncertainty marker")
    r = run("Q11", "As of January 1, 2027, exactly 6,000 exoplanets.")
    if r["semantic"] != "FAIL":
        fails.append("Q11 fabricated number must fail")
    r = run("Q12", "Rain falls, and drops drip.")
    if r["semantic"] != "PASS":
        fails.append("Q12 e-free sentence")
    r = run("Q12", "The rain in Spain.")
    if r["semantic"] != "FAIL":
        fails.append("Q12 must catch 'e' (recorded qwen3.6 failure shape)")
    # Q12 empty-at-cap (recorded Mellum2 Thinking): budget artifact, not lexical
    r = run("Q12", "", finish="length", usage={"completion_tokens": 64, "reasoning_tokens": 64})
    if r["semantic"] != "NOT_EVALUABLE" or r["completion"] != "FAIL_LENGTH" or r["budget"] != "EXHAUSTED_IN_REASONING":
        fails.append(f"Q12 empty-at-cap must be budget artifact: {r}")

    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
