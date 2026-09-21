#!/usr/bin/env python3
"""score_reliability.py — WELP reliability scorer v2 (welp-reliability-scorer/2).

Canonical in-repo reliability scorer introduced by the WELP methodology-revision
snapshot (audit bundle welp-vnext-audit-2026-09-19, CP-3). Supersedes the frozen
external v1 scorer (case-sensitive substring need/forbid over `content`) which
remains the identity for historical campaigns.

v2 behavior (fixture `fixtures/reliability/welp-reliability-sample-20-v2.json`):
  - Unicode NFKC + casefold + contraction normalization (can't -> cannot, ...).
  - Word-boundary token matching with optional inflection stems and accept
    alternatives (fixes case/morphology/alternate-valid FN modes).
  - Forbidden patterns are assertion-scoped by default: a match inside a
    sentence carrying negation/uncertainty cues, or inside quotation marks,
    is exempt (fixes forbid-in-denial FN modes) — while an unhedged assertion
    of the forbidden claim still violates. scope=any restores strictness.
  - Refusal-cue requirements defeat prompt-echo false positives on
    safety/pushback tasks (anti-echo; STRICTER than v1).
  - Exact tasks: strip compare, CRLF/CR normalization on request, frozen
    accept-sets where the prompt under-determines the exact string.
  - Emits CP-1 outcome triples per instance (contracts/welp-outcomes-0.1.0-draft.json):
      semantic   PASS | FAIL | NOT_EVALUABLE   (final-answer channel only)
      completion COMPLETE | FAIL_LENGTH | EMPTY_ANSWER | INVALID_STOP
      budget     WITHIN | EXHAUSTED_IN_REASONING | EXHAUSTED_IN_ANSWER | UNKNOWN
    plus verbatim finish_reason and measurable reasoning/answer token split.
    Incomplete output never auto-fails semantics; reasoning traces never
    substitute for the final answer.

Self-tests are mandatory before live use: `python3 score_reliability.py selftest`
runs the deterministic fixture set in `score_reliability_fixtures.json` (same
directory) and exits nonzero on any mismatch.

Usage:
  python3 score_reliability.py selftest
  python3 score_reliability.py score --fixture FIXTURE.json --rows RAW.jsonl \
      [--lane operational|semantic]
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

SCORER_IDENTITY = "welp-reliability-scorer/2"
SCORER_VERSION = "2.0.0-draft"
OUTCOMES_CONTRACT = "welp-outcomes-0.1.0-draft"

SEMANTIC_VOCAB = {"PASS", "FAIL", "NOT_EVALUABLE"}
COMPLETION_VOCAB = {"COMPLETE", "FAIL_LENGTH", "EMPTY_ANSWER", "INVALID_STOP"}
BUDGET_VOCAB = {"WITHIN", "EXHAUSTED_IN_REASONING", "EXHAUSTED_IN_ANSWER", "UNKNOWN"}

CONTRACTIONS = [
    (r"\bcan't\b", "cannot"), (r"\bcannot\b", "cannot"), (r"\bcan not\b", "cannot"),
    (r"\bwon't\b", "will not"), (r"\bdon't\b", "do not"), (r"\bdoesn't\b", "does not"),
    (r"\bdidn't\b", "did not"), (r"\bisn't\b", "is not"), (r"\baren't\b", "are not"),
    (r"\bwasn't\b", "was not"), (r"\bweren't\b", "were not"),
    (r"\bshouldn't\b", "should not"), (r"\bmustn't\b", "must not"),
    (r"\bwouldn't\b", "would not"), (r"\bcouldn't\b", "could not"),
    (r"\bhaven't\b", "have not"), (r"\bhasn't\b", "has not"),
    (r"\bhasn;t\b", "has not"),
]

# Cues that exempt an assertion-scoped forbidden match: the sentence hedges,
# negates, or marks the claim as unknown rather than asserting it.
EXEMPT_CUES = [
    "not", "no", "never", "cannot", "whether", "if", "unknown", "uncertain",
    "unclear", "may", "might", "without", "lacks", "lacking", "unable",
    "depends", "possibly", "perhaps", "unlikely", "unverified", "impossible",
    "no evidence", "no such", "does not", "do not", "will not", "should not",
    "must not", "refuse", "refuses", "refusing",
]
_CUE_RES = [re.compile(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])") for c in EXEMPT_CUES]

REFUSAL_CUES = [
    "no", "not", "never", "cannot", "unsafe", "avoid", "unable",
    "do not", "does not", "did not", "should not", "must not", "will not",
    "would not", "could not", "lacks", "neither", "refuse", "refuses",
    "refusing", "declin", "impossible", "no way", "not possible", "wrong",
    "incorrect", "false", "misconception", "not true",
]
_CUE_ANY = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(c) for c in REFUSAL_CUES) + r")(?![a-z0-9])")

_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")


# ---------------------------------------------------------------- normalization
def _base_normalize(text: str) -> str:
    """NFKC + line-ending fold + punctuation fold + contraction normalization."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # Fold typographic apostrophes/quotes so can't -> cannot etc. works and
    # double-quote echo detection behaves uniformly.
    t = (t.replace("\u2019", "'").replace("\u2018", "'")
          .replace("\u201c", '"').replace("\u201d", '"'))
    for pat, rep in CONTRACTIONS:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    return t


def normalize_text(text: str) -> str:
    """Casefolded normalization used for case-insensitive matching."""
    return _base_normalize(text).casefold()


def normalize_keepcase(text: str) -> str:
    """Case-preserving normalization used for casefold=false tokens/patterns."""
    return _base_normalize(text)


def _token_regex(tok: dict) -> re.Pattern:
    """Build the match regex for one token spec.

    casefold=true tokens are matched against normalized (casefolded) text.
    mode=word adds a trailing no-alnum boundary; a leading no-alnum lookbehind
    is added when the token starts with an alphanumeric character (this is what
    keeps 'no' from matching inside 'knowledge'/'normal'). stem=true accepts
    regular inflections (y-ending: cop(y|ies|ied|ying); otherwise +s/es/ed/ing/ion[s]).
    """
    variants = [tok["t"]] + list(tok.get("alts") or [])
    parts = []
    for v in variants:
        cf = tok.get("casefold", True)
        surf = v.casefold() if cf else v
        esc = re.escape(surf)
        if tok.get("stem") and cf:
            if surf.endswith("y") and len(surf) > 1:
                esc = re.escape(surf[:-1]) + "(?:y|ies|ied|ying)"
            else:
                esc = esc + "(?:s|es|ed|ing|ion|ions)?"
        lead = r"(?<![a-z0-9_])" if re.match(r"[a-z0-9]", surf[:1]) else ""
        trail = r"(?![a-z0-9])" if tok.get("mode", "word") == "word" else ""
        parts.append(lead + esc + trail)
    return re.compile("|".join("(?:" + p + ")" for p in parts))


def _token_present(norm_cf: str, norm_kc: str, tok: dict) -> bool:
    rx = _token_regex(tok)
    hay = norm_cf if tok.get("casefold", True) else norm_kc
    return rx.search(hay) is not None


# ---------------------------------------------------------------- clause engine
def _clause_tokens(clause):
    """Normalize a clause to ('all', [tokens]) or ('any', [[tokens], ...])."""
    if isinstance(clause, dict):
        if "all" in clause:
            return ("all", clause["all"])
        if "any" in clause:
            return ("any", clause["any"])
        raise ValueError(f"bad clause: {clause!r}")
    return ("all", clause)


def evaluate_expectation(expected: dict, content: str) -> dict:
    """Evaluate a v2 expectation against the final-answer channel."""
    kind = expected.get("kind")
    detail = {"kind": kind}
    if kind == "exact_v2":
        value = content or ""
        if expected.get("normalize_line_endings"):
            value = value.replace("\r\n", "\n").replace("\r", "\n")
        stripped = value.strip()
        if "exact_in" in expected:
            members = expected["exact_in"]
            if expected.get("casefold", True):
                hit = stripped.casefold() in [m.casefold() for m in members]
            else:
                hit = stripped in members
            detail["exact_in"] = True
            detail["pass"] = hit
        else:
            target = expected["value"]
            if expected.get("normalize_line_endings"):
                target = target.replace("\r\n", "\n").replace("\r", "\n")
            detail["pass"] = stripped == target
        return detail

    if kind != "contains_all_v2":
        raise ValueError(f"unknown expectation kind {kind!r}")

    norm_cf = normalize_text(content or "")
    norm_kc = normalize_keepcase(content or "")
    ok = True

    for key, want in (("require_all", True), ("require_any", None)):
        clauses = expected.get(key) or []
        if not clauses:
            continue
        results = []
        for clause in clauses:
            mode, groups = _clause_tokens(clause)
            if mode == "all":
                results.append(all(_token_present(norm_cf, norm_kc, t) for t in groups))
            else:
                results.append(any(all(_token_present(norm_cf, norm_kc, t) for t in g) for g in groups))
        held = all(results) if want else any(results)
        detail[key] = results
        ok = ok and held

    if expected.get("require_refusal_cue"):
        cue = bool(_CUE_ANY.search(norm_cf))
        detail["refusal_cue"] = cue
        ok = ok and cue

    for fb in expected.get("forbid") or []:
        violation = _forbid_violation(norm_cf, norm_kc, fb)
        detail.setdefault("forbid", []).append({"pattern": fb["pattern"], "violation": violation})
        ok = ok and not violation
    detail["pass"] = ok
    return detail


def _forbid_violation(norm_cf: str, norm_kc: str, fb: dict) -> bool:
    pattern = fb["pattern"]
    casefold = fb.get("casefold", True)
    needle = pattern.casefold() if casefold else pattern
    hay = norm_cf if casefold else norm_kc
    esc = re.escape(needle)
    if fb.get("word", True):
        lead = r"(?<![a-z0-9])" if re.match(r"[a-z0-9]", needle[:1]) else ""
        trail = r"(?![a-z0-9])" if re.match(r"[a-z0-9]", needle[-1:]) else ""
        esc = lead + esc + trail
    rx = re.compile(esc)
    scope = fb.get("scope", "assertion")
    for m in rx.finditer(hay):
        if scope == "assertion":
            sent = _sentence_containing(hay, m.start(), m.end())
            if _in_quotes(hay, m.start()):
                continue
            if any(cue.search(sent) for cue in _CUE_RES):
                continue
            return True
        return True
    return False


def _sentence_containing(norm: str, start: int, end: int) -> str:
    starts = [m.start() for m in _SENTENCE_SPLIT.finditer(norm[:start])]
    s = (starts[-1] + 1) if starts else 0
    m = _SENTENCE_SPLIT.search(norm, end)
    e = m.start() if m else len(norm)
    return norm[s:e]


def _in_quotes(norm: str, idx: int) -> bool:
    """True when idx sits inside double quotation marks.

    Backticks deliberately do NOT exempt: they are code formatting, and a
    fabrication asserted inside backticks ('`git timewarp --undo` is a command
    that ...') is still an assertion. Correct denials quoting the premise in
    backticks are exempt via their sentence's negation cues instead.
    """
    return norm.count('"', 0, idx) % 2 == 1


# ---------------------------------------------------------------- CP-1 outcomes
def derive_completion(finish, content, usage=None, ceiling=None):
    """CP-1 completion axis. finish verbatim; derivation labeled by caller."""
    text = (content or "").strip()
    ctoks = (usage or {}).get("completion_tokens")
    if finish == "length":
        return "FAIL_LENGTH"
    if finish in ("stop", "tool_calls"):
        return "COMPLETE" if text else "EMPTY_ANSWER"
    # finish missing / unrecognized: derive from token accounting (DERIVED)
    if finish is None:
        if ceiling and ctoks is not None and ctoks >= ceiling:
            return "FAIL_LENGTH"
        if text:
            return "COMPLETE"
        if ctoks:
            return "EMPTY_ANSWER"
        return "INVALID_STOP"
    return "INVALID_STOP"


def derive_budget(finish, completion, content, has_reasoning, reasoning_declared=None,
                  reasoning_tokens=None, answer_tokens=None):
    """CP-1 budget axis. UNKNOWN is honest when attribution is unsupported.

    `reasoning_declared`: True/False when the serving profile declares a
    reasoning surface (gate_baseline_reasoning_state), None when unknown.
    A declared reasoning-off profile attributes all consumption to the answer
    lane by definition; an undeclared profile with empty channels stays UNKNOWN.
    """
    if reasoning_tokens is not None and answer_tokens is not None:
        if completion == "FAIL_LENGTH":
            return "EXHAUSTED_IN_ANSWER" if answer_tokens > 0 else "EXHAUSTED_IN_REASONING"
        return "WITHIN" if completion in ("COMPLETE", "EMPTY_ANSWER") else "UNKNOWN"
    if completion == "FAIL_LENGTH":
        if (content or "").strip():
            return "EXHAUSTED_IN_ANSWER"
        if has_reasoning:
            return "EXHAUSTED_IN_REASONING"
        if reasoning_declared is False:
            return "EXHAUSTED_IN_ANSWER"
        return "UNKNOWN"
    if completion in ("COMPLETE", "EMPTY_ANSWER"):
        return "WITHIN"
    return "UNKNOWN"


_REASONING_STATES_FALSE = {"REASONING_OFF", "OFF", "NOT_APPLICABLE", "DISABLED"}
_REASONING_STATES_TRUE = {"REASONING_ON", "ON", "CHECKPOINT_THINKING", "THINKING", "ENABLED"}


def _declared_reasoning(row: dict):
    rs = row.get("reasoning_state") or row.get("gate_baseline_reasoning_state")
    if isinstance(rs, str):
        u = rs.upper()
        if u in _REASONING_STATES_FALSE:
            return False
        if u in _REASONING_STATES_TRUE:
            return True
    return None


def score_row(task: dict, row: dict, ceiling=None) -> dict:
    """Score one task instance; returns the CP-1 outcome record.

    `task` carries the fixture entry (expected + generation_budget); `row`
    carries the retained generation evidence: output (final-answer channel),
    optional reasoning channel evidence, verbatim finish, usage.
    """
    content = row.get("output") or row.get("content") or ""
    finish = row.get("finish", row.get("finish_reason"))
    usage = row.get("usage") or {}
    reasoning_text = row.get("reasoning_content") or ""
    head = row.get("reasoning_content_head") or ""
    rtoks = usage.get("reasoning_tokens")
    ctoks = usage.get("completion_tokens")
    has_reasoning = bool(reasoning_text.strip() or head.strip()) or bool(rtoks)
    cap = ceiling or row.get("max_tokens") or (task.get("generation_budget") or {}).get("operational_generation_ceiling")

    completion = derive_completion(finish, content, usage, cap)
    budget = derive_budget(finish, completion, content, has_reasoning,
                           reasoning_declared=_declared_reasoning(row), reasoning_tokens=rtoks,
                           answer_tokens=(ctoks - rtoks) if (rtoks is not None and ctoks is not None) else None)
    answer_tokens = (ctoks - rtoks) if (rtoks is not None and ctoks is not None) else None

    expectation_pass = None
    semantic = "NOT_EVALUABLE"
    detail = {}
    if completion == "COMPLETE":
        detail = evaluate_expectation(task["expected"], content)
        expectation_pass = detail["pass"]
        semantic = "PASS" if detail["pass"] else "FAIL"
    elif completion == "FAIL_LENGTH":
        # Truncation-aware outcomes: an exact task whose full channel already
        # matches proves a complete answer (PASS). A forbidden-pattern
        # violation already present in the produced channel is positive
        # evidence of a wrong/fabricated answer that truncation does not
        # unsay (FAIL). Needs-only shortfalls stay NOT_EVALUABLE because the
        # missing tokens might have appeared after the cut.
        exp = task.get("expected") or {}
        detail = evaluate_expectation(exp, content)
        if exp.get("kind") == "exact_v2" and "exact_in" not in exp and detail["pass"]:
            expectation_pass = True
            semantic = "PASS"
        elif any(f.get("violation") for f in detail.get("forbid", [])):
            expectation_pass = False
            semantic = "FAIL"
    # EMPTY_ANSWER / INVALID_STOP / contains_all under FAIL_LENGTH stay NOT_EVALUABLE

    return {
        "id": task["id"],
        "category": task.get("category"),
        "semantic": semantic,
        "completion": completion,
        "budget": budget,
        "finish_reason": finish,
        "completion_tokens": ctoks,
        "reasoning_tokens": rtoks,
        "answer_tokens": answer_tokens,
        "expectation_pass": expectation_pass,
        "detail": detail,
        "scorer": SCORER_IDENTITY,
    }


# ---------------------------------------------------------------- aggregates
def aggregate(results):
    """Lane aggregates per contracts/welp-outcomes-0.1.0-draft.json."""
    n = len(results)
    complete = [r for r in results if r["completion"] == "COMPLETE"]
    trunc = [r for r in results if r["completion"] == "FAIL_LENGTH"]
    evaluable = [r for r in results if r["semantic"] in ("PASS", "FAIL")]
    passes = [r for r in evaluable if r["semantic"] == "PASS"]
    return {
        "instances": n,
        "completion_rate": (len(complete) / n) if n else None,
        "truncation_rate": (len(trunc) / n) if n else None,
        "not_evaluable": sum(1 for r in results if r["semantic"] == "NOT_EVALUABLE"),
        "semantic_clean_rate_conditional": (len(passes) / len(evaluable)) if evaluable else None,
        "semantic_evaluable": len(evaluable),
        "semantic_pass": len(passes),
    }


# ---------------------------------------------------------------- fixture validation
def validate_fixture(fixture: dict) -> list:
    errs = []
    tasks = fixture.get("tasks") or []
    ids = [t.get("id") for t in tasks]
    if len(ids) != len(set(ids)):
        errs.append("duplicate task ids")
    for t in tasks:
        exp = t.get("expected") or {}
        kind = exp.get("kind")
        if kind not in ("contains_all_v2", "exact_v2"):
            errs.append(f"{t.get('id')}: bad expectation kind {kind!r}")
        gb = t.get("generation_budget") or {}
        ab = gb.get("answer_budget")
        ceil_ = gb.get("operational_generation_ceiling")
        if not isinstance(ab, int) or ab <= 0:
            errs.append(f"{t.get('id')}: answer_budget missing/non-positive")
        if not isinstance(ceil_, int) or (isinstance(ab, int) and ceil_ < ab):
            errs.append(f"{t.get('id')}: operational ceiling missing or < answer_budget")
        if not gb.get("rationale"):
            errs.append(f"{t.get('id')}: budget rationale required")
    return errs


# ---------------------------------------------------------------- selftest
def _run_selftest_fixtures(path: Path):
    fx = json.loads(path.read_text())
    fails = []
    ran = 0
    for f in fx.get("fixtures", []):
        ran += 1
        got = score_row(f["task"], f["row"])
        want = f["expect"]
        for k, v in want.items():
            if got.get(k) != v:
                fails.append(f"{f.get('name', f['task']['id'])}: {k}={got.get(k)!r} want {v!r}")
    return ran, fails


def selftest() -> int:
    here = Path(__file__).resolve().parent
    fx_path = here / "score_reliability_fixtures.json"
    ran, fails = _run_selftest_fixtures(fx_path)
    fixture = json.loads((here.parent / "fixtures/reliability/welp-reliability-sample-20-v2.json").read_text())
    errs = validate_fixture(fixture)
    if errs:
        fails.extend(f"fixture: {e}" for e in errs)
    ids = [t["id"] for t in fixture["tasks"]]
    if len(ids) != 20:
        fails.append(f"fixture: expected 20 tasks, got {len(ids)}")
    print(json.dumps({
        "scorer": SCORER_IDENTITY,
        "version": SCORER_VERSION,
        "outcomes_contract": OUTCOMES_CONTRACT,
        "selftest_fixtures": ran,
        "fixture_tasks": len(ids),
        "fixture_id": fixture.get("fixture_id"),
        "fixture_version": fixture.get("version"),
        "failures": fails,
        "pass": not fails,
    }, indent=2))
    return 0 if not fails else 1


# ---------------------------------------------------------------- CLI
def _cli_score(args) -> int:
    fixture = json.loads(Path(args.fixture).read_text())
    errs = validate_fixture(fixture)
    if errs:
        print(json.dumps({"error": "fixture invalid", "details": errs}, indent=2))
        return 2
    tasks = {t["id"]: t for t in fixture["tasks"]}
    out, results = [], []
    for line in Path(args.rows).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task = tasks.get(row.get("id"))
        if task is None:
            out.append({"id": row.get("id"), "error": "id not in fixture"})
            continue
        if args.lane == "semantic":
            rec = score_row(task, row, ceiling=2048)
        else:
            rec = score_row(task, row)
        results.append(rec)
        out.append(rec)
    for r in out:
        print(json.dumps(r))
    print(json.dumps({"aggregate": aggregate(results), "lane": args.lane,
                      "scorer": SCORER_IDENTITY}), file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WELP reliability scorer v2")
    ap.add_argument("command", choices=["selftest", "score"])
    ap.add_argument("--fixture")
    ap.add_argument("--rows")
    ap.add_argument("--lane", default="operational", choices=["operational", "semantic"])
    args = ap.parse_args(argv)
    if args.command == "selftest":
        return selftest()
    if not (args.fixture and args.rows):
        ap.error("score requires --fixture and --rows")
    return _cli_score(args)


if __name__ == "__main__":
    sys.exit(main())
