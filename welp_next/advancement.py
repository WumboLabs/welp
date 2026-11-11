"""Deterministic capability-specific advancement decisions (SPEC §4.2, §12).

Official decisions bind reconstructed finalized baseline evidence to the
operator-accepted, versioned diagnostic-witness definition below. Predictive
validity and execution authorization are separate. The generic calculator's
caller-supplied rules/prerequisites remain SOFTWARE_TEST-only approval inputs.
Sections remain independent: coding, reasoning, long-context and tool-use.

Scientific honesty rules implemented here:

- **No invented thresholds.** No numeric Agentic budget or population passing
  percentage is inferred. Accepted diagnostic witnesses use the fixed inventory
  and named semantic evidence; caller source/acceptance strings are not approval.
- **Existing disposition vocabulary only** (SPEC §4.2): ``ADVANCE``,
  ``NOT_ELIGIBLE``, ``DEFERRED``, ``NOT_APPLICABLE``, ``EXPLORATORY``.
  ``INTEGRATION_BLOCKED`` is runtime-owned and never derived here. No
  aggregate percentage is computed anywhere.
- **Unresolved evidence defers; definitive negatives decide.** While
  required evidence is incomplete — absent category, unmeasured identities,
  budget-limited or indeterminate unscored results, unresolved critical
  prerequisites — no threshold can judge, so the section stays ``DEFERRED``
  without a semantic verdict. A rule is decisively unsatisfied (and the
  section ``NOT_ELIGIBLE``) only when its criteria could not be met even if
  every missing/unscored result resolved favorably, or when a critical
  prerequisite is resolved false with its cited evidence. Resource-limited
  results are always named as retained findings, never semantic failures.
- **Measurements versus semantics.** Evidence counts follow the §10.1
  coverage semantics: a scored incorrect answer satisfies measurement
  coverage (a valid negative); missing or absent categories can never
  silently count as success.
- **Evidence-class binding.** A rule admits only the evidence class it is
  bound to; ``SOFTWARE_TEST`` rules can never admit ``REAL_MODEL`` evidence
  (or vice versa).
- **Scheduling is not eligibility.** Priorities order only which eligible
  sections consume the remaining workload budget; a priority can never turn
  an unmet criterion into an advance. Budget exhaustion defers an otherwise
  eligible section without recording a semantic failure; the evaluation that
  would have applied is preserved in ``standard_eligibility``.
- **Exploratory is separate and attributed.** An operator authorization must
  name the section explicitly and carry an operator identity, an
  authorization reference and the research reason; the resulting
  ``EXPLORATORY`` decision is never ordinary eligibility and preserves the
  standard evaluation (including scientific failures) in the record.
- **Unknown prerequisites stay unresolved.** A critical prerequisite without
  an explicit resolution defers the rule; absence is never success.

Fail-closed input validation raises ``policy.CheckError``. Decisions are
deterministic: identical (content-equal) inputs produce byte-identical
canonical JSON. Stdlib only; no legacy imports.
"""
from __future__ import annotations

from fractions import Fraction

from . import policy

#: Envelope schema identifier for the returned decision record.
SCHEMA = "welp.advancement-decisions/1"

#: Advanced capability sections (SPEC §4.1) in their fixed decision order.
SECTIONS = ("coding", "reasoning", "long-context", "tool-use")

#: Category status vocabulary produced by ``policy.baseline_coverage`` (§10.1).
_CATEGORY_STATUS = ("COMPLETE", "COMPLETE_WITH_DOCUMENTED_LIMITATIONS",
                    "PARTIALLY_COMPLETE", "UNSUPPORTED_OR_NON_EVALUABLE")

_RULE_REQUIRED_KEYS = ("rule_id", "sections", "evidence_class", "source",
                       "acceptance", "required_categories")
_RULE_OPTIONAL_KEYS = ("critical_prerequisites",)
_RULE_KEYS = frozenset(_RULE_REQUIRED_KEYS) | frozenset(_RULE_OPTIONAL_KEYS)

#: Explicit criterion vocabulary. Every deciding number must appear here and
#: in the rule; nothing is defaulted (SPEC §12.1: no values invented).
_CRITERION_INT_KEYS = ("min_measured", "min_scored", "min_passes")
_CRITERION_RATE_KEYS = ("min_pass_rate",)
_CRITERION_FLAG_KEYS = ("require_complete_measurement", "require_complete_scoring")
_CRITERION_KEYS = frozenset(_CRITERION_INT_KEYS) | frozenset(_CRITERION_RATE_KEYS) \
    | frozenset(_CRITERION_FLAG_KEYS)

_EXPLORATORY_KEYS = ("operator", "authorization", "reason")

_COVERAGE_COUNTS = ("planned", "applicable", "measured", "scored", "pass",
                    "fail", "budget_limited", "indeterminate")


# ---------------------------------------------------------------------------
# Fail-closed input validation


def _fail(field: str, message: str) -> None:
    raise policy.CheckError(f"{field}: {message}", field=field)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(field, "must be a nonempty string")
    return value


def _str_list(value: object, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        _fail(field, "must be a list of strings")
    out: list[str] = []
    for item in value:
        out.append(_nonempty_str(item, field))
    if len(set(out)) != len(out):
        _fail(field, "must not contain duplicate entries")
    return out


def _validate_coverage(coverage: object) -> dict:
    """Validate the ``policy.baseline_coverage`` shape and its §10.1 semantic
    invariants. Malformed or self-contradictory coverage fails closed: a
    hand-cooked row can never claim success the producer would not emit."""
    if not isinstance(coverage, dict):
        _fail("coverage", "must be the dict result of policy.baseline_coverage")
    _nonempty_str(coverage.get("status"), "coverage.status")
    categories = coverage.get("categories")
    if not isinstance(categories, dict):
        _fail("coverage.categories", "must be a category-name to row mapping")
    for name in sorted(categories):
        row = categories[name]
        field = f"coverage.categories.{name}"
        if not isinstance(row, dict):
            _fail(field, "must be an object")
        for key in _COVERAGE_COUNTS:
            value = row.get(key)
            if not _is_int(value) or value < 0:
                _fail(f"{field}.{key}", "must be a nonnegative integer")
        for key in ("missing", "unscored"):
            _str_list(row.get(key), f"{field}.{key}")
        excluded = row.get("excluded")
        if not isinstance(excluded, dict):
            _fail(f"{field}.excluded", "must be a unit-id to reason mapping")
        for uid, reason in sorted(excluded.items()):
            _nonempty_str(uid, f"{field}.excluded key")
            _nonempty_str(reason, f"{field}.excluded[{uid}]")
        status = row.get("status")
        if status not in _CATEGORY_STATUS:
            _fail(f"{field}.status", f"must be one of {_CATEGORY_STATUS}")
        measured_met = row.get("minimum_measurement_coverage_met")
        if not isinstance(measured_met, bool):
            _fail(f"{field}.minimum_measurement_coverage_met", "must be a boolean")
        scoring_met = row.get("minimum_scoring_coverage_met")
        if scoring_met is not None and not isinstance(scoring_met, bool):
            _fail(f"{field}.minimum_scoring_coverage_met",
                  "must be a boolean or null (performance)")
        # Semantic invariants (§10.1): measurement coverage is exact — every
        # applicable identity is measured or explicitly missing.
        if row["applicable"] != row["measured"] + len(row["missing"]):
            _fail(field, "measured plus missing must equal applicable identities")
        if row["planned"] < row["applicable"] + len(excluded):
            _fail(field, "planned undercounts applicable plus excluded identities")
        if (row["applicable"] == 0) != (status == "UNSUPPORTED_OR_NON_EVALUABLE"):
            _fail(field, "UNSUPPORTED_OR_NON_EVALUABLE must match zero applicable identities")
        if measured_met != (bool(row["applicable"]) and not row["missing"]):
            _fail(f"{field}.minimum_measurement_coverage_met",
                  "inconsistent with measured/missing identities")
        if name == "performance":
            if row["scored"] or row["unscored"] or scoring_met is not None:
                _fail(field, "performance is measured, never scored (SPEC §10.1)")
        else:
            if row["pass"] + row["fail"] != row["scored"]:
                _fail(field, "pass plus fail must equal scored")
            if row["scored"] + len(row["unscored"]) != row["measured"]:
                _fail(field, "scored plus unscored must equal measured")
            if row["budget_limited"] + row["indeterminate"] != len(row["unscored"]):
                _fail(field, "budget_limited plus indeterminate must equal unscored")
            if scoring_met != (bool(row["applicable"]) and not row["missing"]
                               and not row["unscored"]):
                _fail(f"{field}.minimum_scoring_coverage_met",
                      "inconsistent with measured/missing/unscored identities")
    return categories


def _validate_rules(rules: object) -> list[dict]:
    """Validate the declarative rule format; return normalized rules sorted by
    ``rule_id`` (deterministic evaluation and citation order)."""
    if rules is None:
        return []
    if not isinstance(rules, (list, tuple)):
        _fail("advancement.rules", "must be a list of rule objects")
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for index, rule in enumerate(rules):
        field = f"advancement.rules[{index}]"
        if not isinstance(rule, dict):
            _fail(field, "must be an object")
        unknown = sorted(set(rule) - _RULE_KEYS)
        if unknown:
            _fail(field, f"unknown key(s) {unknown}; rule keys are exactly {sorted(_RULE_KEYS)}")
        absent = [key for key in _RULE_REQUIRED_KEYS if key not in rule]
        if absent:
            _fail(field, f"missing required key(s) {absent}")
        rule_id = _nonempty_str(rule["rule_id"], f"{field}.rule_id")
        if rule_id in seen_ids:
            _fail(field, f"duplicate rule_id {rule_id!r}")
        seen_ids.add(rule_id)
        sections = _str_list(rule["sections"], f"{field}.sections")
        if not sections:
            _fail(f"{field}.sections", "must bind at least one section")
        for section in sections:
            if section not in SECTIONS:
                _fail(f"{field}.sections",
                      f"unknown section {section!r}; must be one of {SECTIONS}")
        evidence_class = rule["evidence_class"]
        if evidence_class not in policy.MODEL_EVIDENCE_KINDS:
            _fail(f"{field}.evidence_class",
                  f"must be one of {policy.MODEL_EVIDENCE_KINDS}")
        source = _nonempty_str(rule["source"], f"{field}.source")
        acceptance = _nonempty_str(rule["acceptance"], f"{field}.acceptance")
        required = rule["required_categories"]
        if not isinstance(required, dict) or not required:
            _fail(f"{field}.required_categories",
                  "must be a nonempty category to criterion mapping")
        criteria: dict[str, dict] = {}
        for category in sorted(required):
            criterion = required[category]
            cfield = f"{field}.required_categories[{category}]"
            _nonempty_str(category, cfield + " (category name)")
            if not isinstance(criterion, dict) or not criterion:
                _fail(cfield, "must be a nonempty explicit criterion object")
            unknown = sorted(set(criterion) - _CRITERION_KEYS)
            if unknown:
                _fail(cfield,
                      f"unknown criterion key(s) {unknown}; criterion keys are "
                      f"exactly {sorted(_CRITERION_KEYS)}")
            checked: dict[str, object] = {}
            for key in _CRITERION_INT_KEYS:
                if key in criterion:
                    value = criterion[key]
                    if not _is_int(value) or value < 1:
                        _fail(f"{cfield}.{key}", "must be an integer >= 1")
                    checked[key] = value
            for key in _CRITERION_RATE_KEYS:
                if key in criterion:
                    value = criterion[key]
                    if not _is_num(value) or not 0 < value <= 1:
                        _fail(f"{cfield}.{key}", "must be a number in (0, 1]")
                    checked[key] = value
            for key in _CRITERION_FLAG_KEYS:
                if key in criterion:
                    if criterion[key] is not True:
                        _fail(f"{cfield}.{key}", "must be true; omit an unrequired constraint")
                    checked[key] = criterion[key]
            criteria[category] = checked
        prerequisites = rule.get("critical_prerequisites", [])
        normalized.append({
            "rule_id": rule_id,
            "sections": [s for s in SECTIONS if s in sections],
            "evidence_class": evidence_class,
            "source": source,
            "acceptance": acceptance,
            "required_categories": criteria,
            "critical_prerequisites": _str_list(
                prerequisites, f"{field}.critical_prerequisites"),
        })
    return sorted(normalized, key=lambda rule: rule["rule_id"])


def _validate_priorities(priorities: object) -> dict | None:
    """Priorities affect scheduling order only — never eligibility."""
    if priorities is None:
        return None
    if not isinstance(priorities, dict):
        _fail("advancement.priorities", "must be a section-name to integer mapping")
    checked: dict[str, int] = {}
    for section, value in sorted(priorities.items()):
        if section not in SECTIONS:
            _fail(f"advancement.priorities[{section!r}]",
                  f"unknown section; must be one of {SECTIONS}")
        if not _is_int(value):
            _fail(f"advancement.priorities[{section!r}]", "must be an integer")
        checked[section] = value
    return checked


def _validate_budget(remaining_budget: object) -> int | None:
    if remaining_budget is None:
        return None
    if not _is_int(remaining_budget) or remaining_budget < 0:
        _fail("advancement.remaining_budget", "must be a nonnegative integer or null")
    return remaining_budget


def _validate_exploratory(exploratory: object) -> dict:
    """Explicit per-section operator authorization: an operator identity, an
    authorization reference and the research reason. A bare section list
    silently implies authorization and is rejected — the exception must stay
    bounded and attributed."""
    if exploratory is None:
        return {}
    if not isinstance(exploratory, dict):
        _fail("advancement.exploratory",
              "must be a section-name to {operator, authorization, reason} "
              "mapping; implicit authorization is not accepted")
    checked: dict[str, dict] = {}
    for section, record in sorted(exploratory.items()):
        if section not in SECTIONS:
            _fail(f"advancement.exploratory[{section!r}]",
                  f"unknown section; must be one of {SECTIONS}")
        field = f"advancement.exploratory[{section!r}]"
        if not isinstance(record, dict):
            _fail(field, "must be an object")
        unknown = sorted(set(record) - set(_EXPLORATORY_KEYS))
        if unknown:
            _fail(field, f"unknown key(s) {unknown}; keys are exactly "
                         f"{list(_EXPLORATORY_KEYS)}")
        entry = {}
        for key in _EXPLORATORY_KEYS:
            if key not in record:
                _fail(field, f"missing required key '{key}'")
            entry[key] = _nonempty_str(record[key], f"{field}.{key}")
        checked[section] = entry
    return {section: checked[section] for section in SECTIONS
            if section in checked}


def _validate_prerequisites(prerequisites: object) -> dict:
    """Prerequisite resolutions: ``True``/``False`` or a
    ``{"resolved": bool, "detail": str}`` record whose detail cites the
    resolved evidence. An unlisted name stays unresolved (never success)."""
    if prerequisites is None:
        return {}
    if not isinstance(prerequisites, dict):
        _fail("advancement.prerequisites",
              "must be a prerequisite-name to resolution mapping")
    checked: dict[str, dict] = {}
    for name, value in sorted(prerequisites.items()):
        _nonempty_str(name, "advancement.prerequisites key")
        field = f"advancement.prerequisites[{name!r}]"
        if isinstance(value, bool):
            checked[name] = {"resolved": value,
                             "detail": "operator boolean resolution"}
        elif isinstance(value, dict):
            unknown = sorted(set(value) - {"resolved", "detail"})
            if unknown:
                _fail(field, f"unknown key(s) {unknown}; keys are ['detail', 'resolved']")
            if not isinstance(value.get("resolved"), bool):
                _fail(field + ".resolved", "must be a boolean")
            detail = "operator resolution record"
            if "detail" in value:
                detail = _nonempty_str(value["detail"], field + ".detail")
            checked[name] = {"resolved": value["resolved"], "detail": detail}
        else:
            _fail(field, "must be a boolean or a {resolved, detail} object")
    return checked


# ---------------------------------------------------------------------------
# Rule evaluation (deterministic; three-state; citations retained)


def _unresolved_note(row: dict) -> str:
    parts = []
    if row["unscored"]:
        parts.append(f"{len(row['unscored'])} unscored results (budget-limited "
                     f"{row['budget_limited']}, indeterminate "
                     f"{row['indeterminate']}): "
                     + ", ".join(sorted(row["unscored"])))
    if row["missing"]:
        parts.append(f"{len(row['missing'])} unmeasured identities: "
                     + ", ".join(sorted(row["missing"])))
    return ("may still resolve: " + "; ".join(parts)) if parts \
        else "no resolvable evidence remains"


def _evaluate_criterion(key: str, required: object, row: dict) -> tuple[bool, bool, str]:
    """Evaluate one explicitly configured criterion against a coverage row.

    Returns ``(met, definitive, detail)``. When unmet, ``definitive`` marks a
    provable violation: the criterion could not be met even if every missing
    or unscored result later resolved favorably. Otherwise the violation is
    unresolved — incomplete evidence cannot be judged (§10.1). Absence and
    zero are never success.
    """
    if key == "min_measured":
        met = row["measured"] >= required
        detail = f"measured {row['measured']} against required {required}"
        if not met:
            definitive = row["applicable"] < required
            detail += ("; even measuring every applicable identity, at most "
                       f"{row['applicable']} could be measured"
                       if definitive else f"; {_unresolved_note(row)}")
            return met, definitive, detail
        return met, True, detail
    if key == "min_scored":
        met = row["scored"] >= required
        detail = f"scored {row['scored']} against required {required}"
        if not met:
            best = row["scored"] + len(row["unscored"]) + len(row["missing"])
            definitive = best < required
            detail += ("; even if every unscored/unmeasured result resolved "
                       f"favorably, at most {best} could be scored"
                       if definitive else f"; {_unresolved_note(row)}")
            return met, definitive, detail
        return met, True, detail
    if key == "min_passes":
        met = row["pass"] >= required
        detail = f"pass {row['pass']} against required {required}"
        if not met:
            best = row["pass"] + len(row["unscored"]) + len(row["missing"])
            definitive = best < required
            detail += ("; even if every unscored/unmeasured result resolved "
                       f"favorably, at most {best} passes achievable"
                       if definitive else f"; {_unresolved_note(row)}")
            return met, definitive, detail
        return met, True, detail
    if key == "min_pass_rate":
        # Fraction(str(...)) keeps the configured decimal exact: an explicit
        # 0.8 is exactly 4/5, never the binary-float 0.8000...0044 that would
        # reject an exact 4/5 boundary.
        threshold = Fraction(str(required))
        met = bool(row["scored"]) and Fraction(row["pass"], row["scored"]) >= threshold
        detail = f"pass rate {row['pass']}/{row['scored']} against required {required!r}"
        if not met:
            best_pass = row["pass"] + len(row["unscored"]) + len(row["missing"])
            best_scored = row["scored"] + len(row["unscored"]) + len(row["missing"])
            definitive = best_scored == 0 or \
                Fraction(best_pass, best_scored) < threshold
            detail += ("; even if every unscored/unmeasured result resolved "
                       f"favorably the rate could not exceed "
                       f"{best_pass}/{best_scored}"
                       if definitive else
                       f"; {_unresolved_note(row)}")
            return met, definitive, detail
        return met, True, detail
    if key == "require_complete_measurement":
        met = row["minimum_measurement_coverage_met"] is True
        detail = "measurement coverage complete"
        if not met:
            detail = ("measurement coverage incomplete; missing unit "
                      "identities: " + ", ".join(sorted(row["missing"])))
            return met, False, detail
        return met, True, detail
    if key == "require_complete_scoring":
        met = row["minimum_scoring_coverage_met"] is True
        detail = "scoring coverage complete"
        if not met:
            detail = ("scoring coverage incomplete; unscored unit identities: "
                      + ", ".join(sorted(row["unscored"]))
                      + f" (budget-limited {row['budget_limited']}, "
                      f"indeterminate {row['indeterminate']})")
            return met, False, detail
        return met, True, detail
    _fail("advancement.rules", f"unhandled criterion key {key!r}")  # unreachable


def _evaluate_rule(rule: dict, categories: dict, evidence_kind: str,
                   resolutions: dict) -> dict:
    """Evaluate one normalized rule into a full citation record.

    ``outcome``: ``matched`` (all criteria met, prerequisites resolved),
    ``definitive`` (a provable violation — evidence-class mismatch, a
    criterion unreachable even with favorable resolution, a required category
    carrying exclusion evidence of zero applicable measurements, or a
    prerequisite resolved false with cited evidence), ``unresolved``
    (incomplete evidence — absent category, unmeasured identities,
    budget-limited or indeterminate unscored results — or an unresolved
    prerequisite: no threshold can judge), or ``inapplicable`` (every
    required category carries exclusion evidence of zero applicable
    measurements: the section cannot meaningfully apply).
    """
    record: dict = {
        "rule_id": rule["rule_id"],
        "source": rule["source"],
        "acceptance": rule["acceptance"],
        "evidence_class": rule["evidence_class"],
        "bound": rule["evidence_class"] == evidence_kind,
        "criteria": [],
        "prerequisites": [],
        "matched": False,
        "evaluable": False,
        "outcome": "unresolved",
        "reason": "",
    }
    if not record["bound"]:
        record["outcome"] = "definitive"
        record["reason"] = (
            "evidence-class binding mismatch: rule bound to "
            f"{rule['evidence_class']}, baseline evidence is {evidence_kind}; "
            "a bound rule never admits the other evidence class")
        return record
    definitive_failures: list[str] = []
    unresolved_failures: list[str] = []
    absent_categories: list[str] = []
    unsupported_categories: list[str] = []
    for category in sorted(rule["required_categories"]):
        criterion = rule["required_categories"][category]
        row = categories.get(category)
        if row is None:
            absent_categories.append(category)
            for key in sorted(criterion):
                record["criteria"].append({
                    "category": category, "criterion": key, "met": False,
                    "detail": ("category absent from coverage; absence is "
                               "never success and cannot be judged")})
            unresolved_failures.append(
                f"category '{category}' absent from coverage (cannot be judged)")
            continue
        if not row["applicable"]:
            unsupported_categories.append(category)
            for key in sorted(criterion):
                record["criteria"].append({
                    "category": category, "criterion": key, "met": False,
                    "detail": ("no applicable measurements ("
                               + row["status"]
                               + "); exclusion is never success")})
            definitive_failures.append(
                f"category '{category}' has no applicable measurements "
                f"({row['status']})")
            continue
        for key in sorted(criterion):
            met, definitive, detail = _evaluate_criterion(key, criterion[key], row)
            record["criteria"].append(
                {"category": category, "criterion": key, "met": met,
                 "detail": detail})
            if not met:
                note = f"{category}:{key} unmet ({detail})"
                (definitive_failures if definitive
                 else unresolved_failures).append(note)
    for name in rule["critical_prerequisites"]:
        resolution = resolutions.get(name)
        if resolution is None:
            record["prerequisites"].append(
                {"name": name, "resolved": None,
                 "detail": ("no resolution provided; unresolved critical "
                            "prerequisites defer, never silently pass")})
            unresolved_failures.append(
                f"critical prerequisite '{name}' unresolved (no resolution "
                "provided)")
            continue
        resolved = bool(resolution["resolved"])
        record["prerequisites"].append(
            {"name": name, "resolved": resolved, "detail": resolution["detail"]})
        if not resolved:
            definitive_failures.append(
                f"critical prerequisite '{name}' resolved false "
                f"({resolution['detail']})")
    record["evaluable"] = not absent_categories and not unsupported_categories
    if absent_categories:
        # Missing evidence can never be judged; only another, already
        # definitive failure outranks the unresolved state.
        record["outcome"] = "definitive" if definitive_failures else "unresolved"
    elif set(rule["required_categories"]) == set(unsupported_categories):
        record["outcome"] = "inapplicable"
    elif definitive_failures:
        record["outcome"] = "definitive"
    elif unresolved_failures:
        record["outcome"] = "unresolved"
    else:
        record["matched"] = True
        record["outcome"] = "matched"
    record["reason"] = {
        "matched": "all criteria met and critical prerequisites resolved",
        "definitive": "; ".join(definitive_failures),
        "unresolved": "; ".join(unresolved_failures),
        "inapplicable": "; ".join(definitive_failures)
        or "no applicable measurements",
    }[record["outcome"]]
    return record


def _category_citation(category: str, row: dict) -> dict:
    return {
        "category": category,
        "status": row["status"],
        "applicable": row["applicable"],
        "measured": row["measured"],
        "scored": row["scored"],
        "pass": row["pass"],
        "fail": row["fail"],
        "budget_limited": row["budget_limited"],
        "indeterminate": row["indeterminate"],
        "missing": sorted(row["missing"]),
        "unscored": sorted(row["unscored"]),
        "excluded": [{"id": uid, "reason": row["excluded"][uid]}
                     for uid in sorted(row["excluded"])],
    }


# ---------------------------------------------------------------------------
# Public decision entry point


def decide(coverage, rules=None, *, evidence_kind, priorities=None,
           remaining_budget=None, exploratory=None, prerequisites=None) -> dict:
    """Generic calculator; external approval values cannot activate real science."""
    if evidence_kind == "REAL_MODEL":
        _validate_rules(rules)
        _validate_prerequisites(prerequisites)
        rules, prerequisites = None, None
    return _decide(coverage, rules, evidence_kind=evidence_kind,
                   priorities=priorities, remaining_budget=remaining_budget,
                   exploratory=exploratory, prerequisites=prerequisites)


def _decide(coverage, rules=None, *, evidence_kind, priorities=None,
           remaining_budget=None, exploratory=None, prerequisites=None) -> dict:
    """Deterministic per-section advancement decisions (SPEC §4.2).

    ``coverage`` is the ``policy.baseline_coverage`` result. This private
    calculator receives either explicit SOFTWARE_TEST inputs or the fixed
    accepted definition and reconstructed witnesses from ``bound_decisions``.
    ``evidence_kind`` is the baseline's evidence class. ``priorities`` order
    scheduling only; ``remaining_budget`` bounds how many actionable sections
    may start; ``exploratory`` maps explicitly authorized sections to their
    ``{operator, authorization, reason}`` records; ``prerequisites`` resolves
    named critical prerequisites. Returns a JSON-compatible envelope with one
    decision per section in :data:`SECTIONS`.
    """
    categories = _validate_coverage(coverage)
    if evidence_kind not in policy.MODEL_EVIDENCE_KINDS:
        _fail("advancement.evidence_kind",
              f"must be one of {policy.MODEL_EVIDENCE_KINDS}")
    normalized_rules = _validate_rules(rules)
    priority_map = _validate_priorities(priorities)
    budget = _validate_budget(remaining_budget)
    authorizations = _validate_exploratory(exploratory)
    resolutions = _validate_prerequisites(prerequisites)

    calibration_reason = (
        "advanced-section eligibility thresholds are not calibrated (SPEC "
        "§12.1) and no advancement rule is configured for this section; no "
        "threshold is invented")

    decisions: dict[str, dict] = {}
    actionable: list[str] = []
    for section in SECTIONS:
        section_rules = [rule for rule in normalized_rules
                         if section in rule["sections"]]
        evaluations = [_evaluate_rule(rule, categories, evidence_kind,
                                      resolutions)
                       for rule in section_rules]
        matched = [record for record in evaluations if record["outcome"] == "matched"]
        definitive = [record for record in evaluations
                      if record["outcome"] == "definitive"]
        unresolved = [record for record in evaluations
                      if record["outcome"] == "unresolved"]
        if not section_rules:
            standard_decision, standard_reason = "DEFERRED", calibration_reason
        elif all(record["outcome"] == "inapplicable" for record in evaluations):
            cited_categories = sorted({category
                                       for rule in section_rules
                                       for category in rule["required_categories"]})
            standard_decision = "NOT_APPLICABLE"
            standard_reason = (
                "section cannot meaningfully apply to this model+profile: "
                + "; ".join(
                    f"required category '{name}' has no applicable measurements"
                    for name in cited_categories))
        elif matched:
            cited = "', '".join(record["rule_id"] for record in matched)
            standard_decision = "ADVANCE"
            standard_reason = (
                f"advancement criteria satisfied by configured rule '{cited}'; "
                "evidence and rule citations recorded")
        elif definitive and not unresolved:
            standard_decision = "NOT_ELIGIBLE"
            standard_reason = ("configured rule criteria definitively "
                               "unsatisfied: " + "; ".join(
                                   f"rule '{record['rule_id']}': {record['reason']}"
                                   for record in definitive))
            if any(record["budget_limited"] or record["indeterminate"]
                   for record in (categories[name]
                                  for rule in section_rules
                                  for name in rule["required_categories"]
                                  if name in categories)):
                standard_reason += ("; resource-limited and indeterminate "
                                    "results are retained findings, not "
                                    "semantic failures")
        else:
            standard_decision = "DEFERRED"
            standard_reason = ("advancement unresolved without a semantic "
                               "verdict (SPEC §4.2): " + "; ".join(
                                   f"rule '{record['rule_id']}': {record['reason']}"
                                   for record in unresolved))
        authorization = authorizations.get(section)
        if authorization is not None:
            decision = "EXPLORATORY"
            reason = (
                "operator-authorized exploratory run outside standard "
                "eligibility (SPEC §4.2, §12.1); operator "
                f"'{authorization['operator']}'; authorization "
                f"'{authorization['authorization']}'; research reason: "
                f"'{authorization['reason']}'; separately classified, never "
                f"ordinary advancement; standard eligibility: {standard_decision}")
            actionable.append(section)
        else:
            decision, reason = standard_decision, standard_reason
            if decision == "ADVANCE":
                actionable.append(section)
        rule_citations = [
            {"rule_id": record["rule_id"], "source": record["source"],
             "acceptance": record["acceptance"],
             "evidence_class": record["evidence_class"],
             "bound": record["bound"],
             "matched": record["matched"], "outcome": record["outcome"],
             "reason": record["reason"], "criteria": record["criteria"],
             "prerequisites": record["prerequisites"]}
            for record in evaluations]
        cited = sorted({entry["category"]
                        for record in evaluations
                        for entry in record["criteria"]})
        decisions[section] = {
            "section": section,
            "decision": decision,
            "reason": reason,
            "evidence_kind": evidence_kind,
            "standard_eligibility": {"decision": standard_decision,
                                     "reason": standard_reason},
            "exploratory_authorization": dict(authorization) if authorization else None,
            "rules": rule_citations,
            "evidence_citations": [_category_citation(name, categories[name])
                                   for name in cited if name in categories],
            "scheduling": {"priority": (priority_map or {}).get(section),
                           "scheduled_position": None},
        }

    # Scheduling: priorities order only which actionable sections consume the
    # workload budget; eligibility was already fixed above.
    def _order(section: str) -> tuple:
        priority = (priority_map or {}).get(section)
        return (0, -priority, SECTIONS.index(section)) if priority is not None \
            else (1, 0, SECTIONS.index(section))

    scheduled = sorted(actionable, key=_order)
    for position, section in enumerate(scheduled, start=1):
        decisions[section]["scheduling"]["scheduled_position"] = position
    for section in (scheduled[budget:] if budget is not None else ()):
        postponed = decisions[section]
        postponed["decision"] = "DEFERRED"
        postponed["reason"] = (
            "postponed under documented resource-budget prioritization (SPEC "
            "§4.2): workload budget exhausted before scheduling; recorded "
            "without a semantic verdict; standard eligibility preserved")

    return {
        "schema": SCHEMA,
        "evidence_kind": evidence_kind,
        "inputs": {
            "priorities": priority_map,
            "remaining_budget": budget,
            "exploratory": authorizations,
        },
        "decisions": decisions,
    }


# Versioned definition accepted by the operator's RTX 5070 qualification and
# calibration assignment, 2026-10-22, for diagnostic claims only. This grants
# neither numeric budgets nor predictive validity nor GPU execution authority.
WITNESS_VERSION = "capability-witness/2"
WITNESS_ACCEPTANCE = "HUMAN_ACCEPTED 2026-10-22; SPEC §10.3 diagnostic claims only"
WITNESSES = {
    "coding": (("coding-generation-01",), ("repository-timeout-01",)),
    "reasoning": (("reasoning-correctness-01",),
                  ("reasoning-evidence-01",),
                  ("reasoning-consistency-01",),
                  ("document-synthesis-01",
                   "linux-diagnosis-startup-invalid-config",
                   "linux-diagnosis-stale-config-bind-failure")),
    "long-context": (("context-family-a-v2-8192-seed-42",),
                     ("context-family-a-v2-8192-seed-314159",),
                     ("context-multidocument-v2-8192-seed-42",)),
    "tool-use": (("tool-permission-01",), ("tool-selection-01",),
                 ("tool-recovery-01",)),
}
AGENTIC_CONTROLS = ("tool-permission-01", "untrusted-content-01",
                    "multi-turn-correction-01")


def witness_resolution(scores, groups):
    """Conjunction of disjunctions; only valid semantic negatives are false."""
    values = []
    for group in groups:
        observations = [scores.get(uid) or {} for uid in group]
        verdicts = [row.get("scoring") if row.get("execution") == "VALID"
                    and row.get("limits") == "NONE" else None
                    for row in observations]
        values.append(True if "SCORED_PASS" in verdicts else
                      False if all(v == "SCORED_FAIL" for v in verdicts) else None)
    return False if False in values else None if None in values else True


def bound_decisions(evidence, *, rule_version=WITNESS_VERSION, priorities=None,
                    remaining_budget=None, exploratory=None):
    """Official entry: evidence comes only from m3.baseline_evidence.

    No acceptance, category counts, scores or prerequisite resolutions are
    accepted as operator input; the fixed versioned definition is authority.
    """
    coverage, scores = evidence["coverage"], evidence["effective_scores"]
    fixture = evidence["task_categories"]
    categories = {"coding": "coding", "reasoning": "reasoning",
                  "long-context": "context", "tool-use": "tool_use"}
    analysis = {}
    rules, resolutions = [], {}
    supported = rule_version == WITNESS_VERSION
    for section, groups in WITNESSES.items():
        category = categories[section]
        ids = [uid for uid, cat in fixture.items() if cat == category]
        measured = bool(ids) and all(
            (scores.get(uid) or {}).get("execution") == "VALID" for uid in ids)
        result = witness_resolution(scores, groups)
        analysis[section] = {
            "measurement_complete": measured, "witness": result,
            "required_witness_groups": [list(group) for group in groups],
            "observations": {uid: {
                "attempt_id": (scores.get(uid) or {}).get("attempt_id"),
                "execution": (scores.get(uid) or {}).get("execution"),
                "scoring": (scores.get(uid) or {}).get("scoring"),
                "limits": (scores.get(uid) or {}).get("limits")}
                for uid in ids}}
        if not supported:
            continue
        names = [section + "-measurement", section + "-witness"]
        # Missing measurements are unresolved, not negative capability evidence.
        if measured:
            resolutions[names[0]] = {"resolved": True, "detail": "all pinned category identities measured"}
        if result is not None:
            resolutions[names[1]] = {"resolved": result,
                                     "detail": "reconstructed named witness evidence"}
        rules.append({
            "rule_id": WITNESS_VERSION + "/" + section, "sections": [section],
            "evidence_class": evidence["evidence_kind"], "source": "SPEC.md §10.3",
            "acceptance": WITNESS_ACCEPTANCE,
            "required_categories": {category: {"require_complete_measurement": True}},
            "critical_prerequisites": names})
    software = evidence["evidence_kind"] == "SOFTWARE_TEST"
    # Only this evidence-bound entry uses the fixed accepted real-model rules.
    # Generic caller-supplied approval/prerequisite values cannot reach this path.
    decisions = _decide(coverage, rules if supported else None,
                       evidence_kind=evidence["evidence_kind"],
                       priorities=priorities, remaining_budget=remaining_budget,
                       exploratory=exploratory, prerequisites=resolutions)
    return {"rule_version": rule_version, "definition_sha256": policy.digest({
                "version": WITNESS_VERSION, "witnesses": WITNESSES,
                "source_sha256": policy.file_sha(__file__),
                "acceptance": WITNESS_ACCEPTANCE,
                "methodology": policy.METHODOLOGY_M2}),
            "acceptance": WITNESS_ACCEPTANCE, "candidate_analysis": analysis,
            "result": decisions,
            "scientific_admission": ("SOFTWARE_TEST_ONLY" if software else
                "HUMAN_ACCEPTED diagnostic method; execution separately gated")
                if supported else "DEFERRED; unsupported rule version"}
