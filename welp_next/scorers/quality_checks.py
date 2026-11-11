"""Quality-screen machine checks — extracted and adapted (SPEC §8 REUSE).

The machine-checkable predicates for the frozen 12-task quality screen
`fixtures/quality/welp-quality-screen-12-v1.json`
(welp-quality-screen-12 1.1.0-draft, scorer welp-quality-scorer/1).

Extraction provenance (recorded in provenance.json):
    source: welp/harness/quality.py (welp-harness-quality/1.0.0-draft), _check
    kept byte-identical in logic: every method (contains with max_chars /
    any_values / forbid, exact_tokens, three_lowercase_words, no_letter,
    json_object_exact with ordered keys, json_array_exact,
    uncertainty_or_absent with the bare-fabricated-number guard).
    adapted: the legacy CP-1 completion/budget row assembly (score_task) was
    not carried — the successor derives facets/outcomes once in
    welp_next.policy; this module is the pure content-check layer only.
Stdlib only (json, re).
"""
import json
import re


def check_methods() -> tuple[str, ...]:
    """The frozen check-method vocabulary of the extracted scorer."""
    return ("contains", "exact_tokens", "three_lowercase_words", "no_letter",
            "json_object_exact", "json_array_exact", "uncertainty_or_absent")


def evaluate_check(spec: dict, content: str) -> bool:
    """Evaluate one frozen quality-screen check spec against answer content.

    Pure and deterministic; raises ValueError for an unknown method (fixture
    defect, fail-closed) — never guesses.
    """
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


def score_quality_task(task: dict, content: str) -> dict:
    """Deterministic semantic layer for one quality-screen task.

    The caller supplies only the produced answer content; completion and
    budget facets are derived upstream. Returns the frozen check result with
    the recorded PASS/FAIL semantic.
    """
    check_pass = evaluate_check(task["check"], content)
    return {"semantic": "PASS" if check_pass else "FAIL", "check_pass": check_pass}
