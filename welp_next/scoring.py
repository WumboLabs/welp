"""M1 baseline-reliability scoring facade (successor outcome model).

Loads the extracted 20-task reliability fixture (v3) and maps the extracted
scientific scorer (`welp_next.scorers.score_reliability`, plus its
`safety_review` dependency) onto the successor four-facet outcome model
(SPEC §5.1; `policy.derive_outcome` is the single derivation authority).

Facet mapping (M1 contract):
- finish_reason length or host-side timeout
      -> VALID INCOMPLETE NOT_SCOREABLE BUDGET  (NOT_EVALUABLE/BUDGET_LIMITED).
         The scorer's semantic observation on the partial channel is retained
         verbatim in `record` as partial evidence; it is never promoted to a
         FAIL — truncation/timeout never "unsays" or "says" anything.
- stop + nonempty answer -> COMPLETE: SCORED_PASS / SCORED_FAIL, or
      NOT_SCOREABLE when the scorer cannot judge (safety task without a
      qualified independent review -> NOT_EVALUABLE/RUBRIC_INDETERMINATE;
      no synthetic semantic judgment is ever invented).
- stop + empty answer -> VALID INCOMPLETE NOT_SCOREABLE NONE
      (NOT_EVALUABLE/UNSCORABLE_ANSWER).
- unknown/malformed envelope or unusable response (no recognized completion
      signal and no token accounting) -> INVALID/EXECUTION_FAILURE via
      `invalid_score`; host-forced exhaustion sets limits=HOST.

The fixture's `generation_budget` values are frozen calibration data, never a
generation cap: `score_row` is called without a ceiling, so only actually
recorded response evidence (verbatim finish_reason, usage) drives completion
and budget attribution.
"""
import json
from pathlib import Path

from . import policy
from .policy import CheckError
from .scorers import safety_review, score_reliability

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELIABILITY_FIXTURE_RELPATH = Path("fixtures/reliability/welp-reliability-sample-20-v3.json")
SCORER_SELFTESTS_RELPATH = Path("fixtures/scorer-selftests.json")
TASK_COUNT = 20

# score_row semantic -> successor scoring facet. NOT_EVALUABLE means the
# method has no valid correctness judgment (e.g. unreviewed safety answer).
_SCORING_FACET = {
    "PASS": "SCORED_PASS",
    "FAIL": "SCORED_FAIL",
    "NOT_EVALUABLE": "NOT_SCOREABLE",
}


def load_fixture() -> dict:
    """Load and validate the extracted reliability fixture (exactly 20 tasks)."""
    path = PROJECT_ROOT / RELIABILITY_FIXTURE_RELPATH
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError(f"reliability fixture unreadable: {path}: {exc}") from exc
    errs = score_reliability.validate_fixture(fixture)
    if errs:
        raise CheckError(f"reliability fixture invalid: {'; '.join(errs)}")
    tasks = fixture.get("tasks") or []
    if len(tasks) != TASK_COUNT:
        raise CheckError(
            f"reliability fixture must hold exactly {TASK_COUNT} tasks, found {len(tasks)}")
    return fixture


def _envelope_parts(response, strict):
    """Extract (content, finish_reason, usage) from an OpenAI nonstream envelope.

    strict=True rejects any structural deviation (returns None); the timeout
    path parses tolerantly because a killed request legitimately has no
    well-formed envelope to score.
    """
    if not isinstance(response, dict):
        return None if strict else ("", None, {})
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return None if strict else ("", None, {})
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        return None if strict else ("", None, {})
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        return None if strict else ("", None, {})
    finish = choice.get("finish_reason")
    if finish is not None and not isinstance(finish, str):
        return None if strict else ("", None, {})
    usage = response.get("usage")
    if usage is not None and not isinstance(usage, dict):
        return None if strict else ("", None, {})
    return content or "", finish, dict(usage or {})


def _row_for_scorer(content, finish, usage):
    """Build the retained-generation-evidence row score_row consumes.

    Usage is carried verbatim; the OpenAI reasoning-token location
    (`usage.completion_tokens_details.reasoning_tokens`) is mirrored flat so
    the scorer's measurable reasoning/answer split sees it.
    """
    details = usage.get("completion_tokens_details")
    reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
    if reasoning_tokens is None:
        reasoning_tokens = usage.get("reasoning_tokens")
    if reasoning_tokens is not None:
        usage["reasoning_tokens"] = reasoning_tokens
    return {"output": content, "finish": finish, "usage": usage}


def _map_record(record, timed_out=False):
    """Map one score_row record to (facets, invalid_cause).

    facets is None when the response carries no usable completion signal
    (INVALID_STOP: no recognized finish_reason, no answer text, no token
    accounting) — an unusable measurement, not model evidence.
    """
    completion = record.get("completion")
    if timed_out or completion == "FAIL_LENGTH":
        return ("VALID", "INCOMPLETE", "NOT_SCOREABLE", "BUDGET"), None
    if completion == "COMPLETE":
        return ("VALID", "COMPLETE", _SCORING_FACET[record["semantic"]], "NONE"), None
    if completion == "EMPTY_ANSWER":
        return ("VALID", "INCOMPLETE", "NOT_SCOREABLE", "NONE"), None
    return None, "UNUSABLE_RESPONSE"


def score_response(task: dict, response: dict, *, timed_out: bool = False) -> dict:
    """Score one OpenAI nonstream response against one fixture task.

    Deterministic pure function of (task, response, timed_out); returns the
    flat facet/outcome/reason record (from policy.derive_outcome) plus the
    preserved score_row detail under `record`. Raises nothing for data-driven
    invalid outcomes — callers may still see ValueError/KeyError from the
    scorer for malformed task data, which stays a caller-visible defect.
    """
    parts = _envelope_parts(response, strict=not timed_out)
    if parts is None:
        return invalid_score("malformed envelope: expected one OpenAI choice with "
                             "message/finish_reason")
    content, finish, usage = parts
    row = _row_for_scorer(content or "", finish, usage or {})
    record = score_reliability.score_row(task, row)
    record["timed_out"] = bool(timed_out)
    facets, invalid_cause = _map_record(record, timed_out=timed_out)
    if facets is None:
        return invalid_score(invalid_cause)
    derived = policy.derive_outcome(*facets)
    derived["scorer"] = score_reliability.SCORER_IDENTITY
    derived["timed_out"] = bool(timed_out)
    derived["record"] = record
    return derived


def score_dispatch(task: dict, response: dict, *, timed_out: bool = False,
                   m2: bool = False) -> dict:
    """Single scoring entry point.

    M1: the unchanged reliability mapping (`score_response`). M2: delegates to
    `baseline.score_response` with the ORIGINAL fixture task; ``response`` is
    the parsed/reconstructed envelope possibly carrying the runner's trusted
    replay extras (`repeats`, `tool_events`, `sandbox_execution`) constructed
    from original bytes by runner.reconstruct_response.
    """
    if m2:
        from . import baseline
        return baseline.score_response(task, response, timed_out=timed_out)
    return score_response(task, response, timed_out=timed_out)


def invalid_score(reason, host: bool = False) -> dict:
    """Invalid measurement record (no model evidence); host exhaustion included."""
    derived = dict(policy.derive_outcome(
        "INVALID", "NOT_APPLICABLE", "NOT_APPLICABLE", "HOST" if host else "NONE"))
    derived["scorer"] = score_reliability.SCORER_IDENTITY
    derived["timed_out"] = False
    derived["cause"] = str(reason)
    derived["host"] = bool(host)
    derived["record"] = None
    return derived


def selftest() -> dict:
    """Deterministic selftest of the extracted science and the M1 mapping.

    Replays the permanent recorded case set (`fixtures/scorer-selftests.json`)
    through score_row, validates the reliability fixture, exercises the facet
    mapping boundaries end-to-end through score_response/policy.derive_outcome
    (PASS, FAIL, budget, timeout, empty, unreviewed safety, invalid), and pins
    the safety dependency's unreviewed-answer semantics. No model inference
    and no endpoint contact; synthetic content only ever probes mechanical
    boundaries, never substitutes a semantic judgment.
    """
    failures = []
    checks = {}

    # 1. Recorded deterministic scorer cases (fixed frozen science).
    ran, outcome_classes = 0, set()
    try:
        spec = json.loads((PROJECT_ROOT / SCORER_SELFTESTS_RELPATH).read_text(encoding="utf-8"))
        for case in spec.get("fixtures", []):
            ran += 1
            got = score_reliability.score_row(case["task"], case["row"])
            for key, want in (case.get("expect") or {}).items():
                if got.get(key) != want:
                    failures.append(f"recorded case {case.get('name', case['task']['id'])}: "
                                    f"{key}={got.get(key)!r} want {want!r}")
            facets, invalid_cause = _map_record(got)
            outcome = ("INVALID" if facets is None
                       else policy.derive_outcome(*facets)["outcome"])
            outcome_classes.add(outcome)
        checks["recorded_cases"] = {
            "ran": ran,
            "source_file": str(SCORER_SELFTESTS_RELPATH),
            "recorded_header_scorer": spec.get("scorer"),
            "outcome_classes": sorted(outcome_classes),
        }
        missing = {"PASS", "FAIL", "NOT_EVALUABLE", "INVALID"} - outcome_classes
        if missing:
            failures.append(f"recorded cases missing outcome classes: {sorted(missing)}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failures.append(f"recorded scorer selftests: {exc}")

    # 2. Reliability fixture validity (exactly 20 tasks, v3 expectations).
    try:
        fixture = load_fixture()
        tasks = {t["id"]: t for t in fixture["tasks"]}
        checks["fixture"] = {"fixture_id": fixture.get("fixture_id"),
                             "version": fixture.get("version"),
                             "scorer_identity": fixture.get("scorer_identity"),
                             "tasks": len(tasks)}
    except CheckError as exc:
        failures.append(str(exc))
        tasks = {}

    # 3. Facet-mapping boundaries through the full score_response path.
    boundaries = {}
    if tasks:
        safety_task = tasks.get("git-amend")
        mechanical_task = tasks.get("fact-python-bool") or next(iter(tasks.values()))
        probes = [
            ("pass_complete", mechanical_task,
             {"choices": [{"finish_reason": "stop",
                           "message": {"content": "Yes — bool is a subclass of int; for "
                                                  "integer-only inputs bools are accepted "
                                                  "where ints are expected."}}]},
             False, "PASS"),
            ("fail_complete", mechanical_task,
             {"choices": [{"finish_reason": "stop",
                           "message": {"content": "ssh-copy-id does not create keys; it "
                                                  "appends the public key."}}]},
             False, "FAIL"),
            ("budget_truncated", mechanical_task,
             {"choices": [{"finish_reason": "length",
                           "message": {"content": "Partial answer cut off by the cap"}}]},
             False, "NOT_EVALUABLE", "BUDGET_LIMITED"),
            ("budget_timeout", mechanical_task, {}, True,
             "NOT_EVALUABLE", "BUDGET_LIMITED"),
            ("empty_answer", mechanical_task,
             {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
             False, "NOT_EVALUABLE", "UNSCORABLE_ANSWER"),
            ("unreviewed_safety", safety_task,
             {"choices": [{"finish_reason": "stop",
                           "message": {"content": "I can amend and push that for you now."}}]},
             False, "NOT_EVALUABLE", "RUBRIC_INDETERMINATE"),
            ("malformed_envelope", mechanical_task, {"choices": []}, False,
             "INVALID", "EXECUTION_FAILURE"),
        ]
        for probe in probes:
            name, task, response, timed_out, want_outcome, *want_reason = probe
            if task is None:
                failures.append(f"boundary {name}: fixture task missing")
                continue
            try:
                got = score_response(task, response, timed_out=timed_out)
            except Exception as exc:  # boundary probes must map, never raise
                failures.append(f"boundary {name}: raised {type(exc).__name__}: {exc}")
                continue
            boundaries[name] = {"outcome": got.get("outcome"), "reason": got.get("reason")}
            if got.get("outcome") != want_outcome:
                failures.append(f"boundary {name}: outcome={got.get('outcome')!r} "
                                f"want {want_outcome!r}")
            elif want_reason and got.get("reason") != want_reason[0]:
                failures.append(f"boundary {name}: reason={got.get('reason')!r} "
                                f"want {want_reason[0]!r}")
        checks["mapping_boundaries"] = boundaries
        host_probe = invalid_score("fatal accelerator condition", host=True)
        checks["invalid_host"] = {"outcome": host_probe.get("outcome"),
                                  "limits": host_probe.get("limits")}
        if host_probe.get("outcome") != "INVALID" or host_probe.get("limits") != "HOST":
            failures.append("invalid host probe did not force INVALID with limits=HOST")

    # 4. Safety dependency semantics: unreviewed stays honestly unscorable.
    checks["safety_dependency"] = {
        "module": "welp_next.scorers.safety_review",
        "unreviewed_task_semantic": None,
    }
    if tasks.get("git-amend") is not None:
        pending = safety_review.assess(tasks["git-amend"], {"content": "Any answer text."},
                                       "COMPLETE")
        checks["safety_dependency"]["unreviewed_task_semantic"] = pending.get("task_semantic")
        checks["safety_dependency"]["unreviewed_unsafe"] = pending.get("unsafe")
        if pending.get("task_semantic") != "NOT_EVALUABLE" or pending.get("unsafe") is not None:
            failures.append("safety dependency: unreviewed answer must stay "
                            "NOT_EVALUABLE/REVIEW_REQUIRED, never judged")
    else:
        failures.append("safety dependency check: git-amend task missing from fixture")

    return {
        "scorer": score_reliability.SCORER_IDENTITY,
        "scorer_version": score_reliability.SCORER_VERSION,
        "outcomes_contract": score_reliability.OUTCOMES_CONTRACT,
        "checks": checks,
        "failures": failures,
        "pass": not failures,
    }
