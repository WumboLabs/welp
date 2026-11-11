"""Capability-guided selection and reporting (SPEC §4.2/§4.5; assignment 2026-11-05).

This module derives a transparent capability profile from evidence WELP already
computed. It owns selection/prioritization language only:

- It never changes scoring, outcomes, coverage or advancement decisions.
- It introduces no thresholds, confidence values or model classification.
- Recommendations are advisory; they cannot authorize execution or convert a
  FAIL into PASS, a budget-limited answer into incompetence, or synthetic
  evidence into scientific credit. Human-directed (EXPLORATORY) selection is
  reported without silently overriding the recorded standard eligibility.

Input is the ``m3.decisions`` envelope (baseline evidence + ``advancement``
witness-bound decisions). Output is the derived capability-guidance envelope
and a deterministic Markdown rendering. Stdlib only.
"""
from __future__ import annotations

from . import advancement, policy

SCHEMA = "welp.capability-guidance/1"

#: Advanced capability sections and their baseline coverage categories.
SECTION_CATEGORY = {"coding": "coding", "reasoning": "reasoning",
                    "long-context": "context", "tool-use": "tool_use"}

_APPLICABILITY = ("UNSUPPORTED", "NOT_TESTED", "EVALUATED")
_RECOMMENDATION_KINDS = ("EVIDENCE_GUIDED", "HUMAN_DIRECTED", "BUDGET_POSTPONED")

_BUDGET_POSTPONEMENT_MARKER = "resource-budget prioritization"


def _fail(field: str, message: str) -> None:
    raise policy.CheckError(f"{field}: {message}", field=field)


def _section_scores(effective: dict, task_categories: dict, category: str) -> dict:
    """Split one category's original per-unit observations into strengths,
    weaknesses and explicitly uncertain observations. Only valid completed
    semantic verdicts count as strengths or weaknesses; budget-limited and
    unreviewed/indeterminate answers are retained as uncertain, never as
    incompetence."""
    strengths: list[str] = []
    weaknesses: list[str] = []
    uncertain: list[str] = []
    for uid, category_of in task_categories.items():
        if category_of != category:
            continue
        row = effective.get(uid)
        if row is None:
            uncertain.append(uid)
            continue
        if row.get("execution") == "VALID" and row.get("limits") == "NONE" \
                and row.get("scoring") == "SCORED_PASS":
            strengths.append(uid)
        elif row.get("execution") == "VALID" and row.get("limits") == "NONE" \
                and row.get("scoring") == "SCORED_FAIL":
            weaknesses.append(uid)
        else:
            uncertain.append(uid)
    return {"strengths": sorted(strengths), "weaknesses": sorted(weaknesses),
            "uncertain": sorted(uncertain)}


def guidance(value: dict) -> dict:
    """Derive the capability-guidance envelope from one ``m3.decisions`` value.

    Fail-closed on shape; every derived field cites the section decision,
    witness analysis or coverage row it came from. Pure: same input yields
    byte-identical output.
    """
    if not isinstance(value, dict) or value.get("methodology") != advancement.WITNESS_VERSION \
            or not isinstance(value.get("baseline"), dict) \
            or not isinstance(value.get("decisions"), dict):
        _fail("capability.input", "m3.decisions envelope required")
    result = value["decisions"].get("result") or {}
    if result.get("schema") != advancement.SCHEMA:
        _fail("capability.input", "advancement decisions envelope required")
    decisions = result.get("decisions") or {}
    analysis = value["decisions"].get("candidate_analysis") or {}
    baseline = value["baseline"]
    coverage = baseline.get("coverage") or {}
    categories = coverage.get("categories") or {}
    effective = baseline.get("effective_scores") or {}
    task_categories = baseline.get("task_categories") or {}

    capabilities: dict[str, dict] = {}
    for section in advancement.SECTIONS:
        decision = decisions.get(section)
        if not isinstance(decision, dict):
            _fail("capability.decisions", f"missing decision for {section}")
        category = SECTION_CATEGORY[section]
        row = categories.get(category)
        if row is None:
            applicability, measurement = "NOT_TESTED", None
        elif not row.get("applicable"):
            applicability, measurement = "UNSUPPORTED", row
        elif row.get("measured"):
            applicability, measurement = "EVALUATED", row
        else:
            applicability, measurement = "NOT_TESTED", row
        observed = analysis.get(section) or {}
        witness = observed.get("witness")
        standard = decision.get("standard_eligibility") or {}
        if decision["decision"] == "EXPLORATORY":
            kind = "HUMAN_DIRECTED"
        elif decision["decision"] == "DEFERRED" and _BUDGET_POSTPONEMENT_MARKER \
                in (decision.get("reason") or ""):
            kind = "BUDGET_POSTPONED"
        else:
            kind = "EVIDENCE_GUIDED"
        capabilities[section] = {
            "baseline_category": category,
            "applicability": applicability,
            "witness": witness,
            "measurement_complete": bool(observed.get("measurement_complete")),
            "recommendation": decision["decision"],
            "recommendation_kind": kind,
            "reason": decision["reason"],
            "standard_eligibility": {"decision": standard.get("decision"),
                                     "reason": standard.get("reason")},
            "human_directed": decision["decision"] == "EXPLORATORY",
            "required_witness_groups": observed.get("required_witness_groups") or [],
            "measurement": None if measurement is None else {
                key: measurement.get(key) for key in
                ("applicable", "measured", "scored", "pass", "fail",
                 "budget_limited", "indeterminate")},
            **_section_scores(effective, task_categories, category),
        }

    fail_total = sum((c.get("fail") or 0) for c in categories.values())
    budget_total = sum((c.get("budget_limited") or 0) for c in categories.values())
    indeterminate_total = sum((c.get("indeterminate") or 0) for c in categories.values())
    return {
        "schema": SCHEMA,
        "rule_version": value["decisions"].get("rule_version"),
        "acceptance": value["decisions"].get("acceptance"),
        "evidence_kind": result.get("evidence_kind"),
        "advisory_only": True,
        "grants_no_execution_authority": True,
        "baseline_negatives_retained": True,
        "deferred_is_not_failed": True,
        "unsupported_is_not_model_failure": True,
        "baseline_negative_counts": {"fail": fail_total,
                                     "budget_limited": budget_total,
                                     "indeterminate": indeterminate_total},
        "capabilities": capabilities,
    }


def render(envelope: dict) -> str:
    """Deterministic Markdown rendering of one guidance envelope."""
    if envelope.get("schema") != SCHEMA:
        _fail("capability.render", "capability-guidance envelope required")
    lines = [
        "# Capability guidance (advisory)",
        "",
        "Selection and prioritization only. Recommendations never authorize",
        "execution, never change scores or outcomes, and never convert",
        "budget-limited or uncertain observations into demonstrated",
        "incompetence. A deferred capability is not a failed capability; an",
        "unsupported interface is not a model-quality failure. Baseline",
        "negatives remain part of the scientific record.",
        "",
        f"Rule version: `{envelope.get('rule_version')}` ({envelope.get('acceptance')}).",
        "",
        "| Capability | Baseline | Applicability | Witness | Recommendation | Basis |",
        "|---|---|---|---|---|---|",
    ]
    for section, cap in envelope["capabilities"].items():
        witness = ("PASS" if cap["witness"] is True else
                   "NEGATIVE" if cap["witness"] is False else "UNRESOLVED")
        lines.append(
            f"| {section} | {cap['baseline_category']} | {cap['applicability']} | "
            f"{witness} | {cap['recommendation']} | {cap['recommendation_kind']} |")
    counts = envelope["baseline_negative_counts"]
    lines += [
        "",
        f"Baseline negatives retained: {counts['fail']} FAIL, "
        f"{counts['budget_limited']} budget-limited, "
        f"{counts['indeterminate']} indeterminate.",
        "",
    ]
    for section, cap in envelope["capabilities"].items():
        lines.append(f"## {section}")
        lines.append("")
        lines.append(f"- Recommendation: **{cap['recommendation']}** "
                     f"({cap['recommendation_kind']}); advisory only.")
        lines.append(f"- Reason: {cap['reason']}")
        if cap["human_directed"]:
            lines.append(f"- Human-directed selection recorded; standard "
                         f"eligibility remains "
                         f"**{cap['standard_eligibility']['decision']}** and is "
                         "not overridden.")
        lines.append(f"- Strengths (valid PASS): "
                     f"{', '.join(cap['strengths']) or 'none'}")
        lines.append(f"- Weaknesses (valid FAIL): "
                     f"{', '.join(cap['weaknesses']) or 'none'}")
        lines.append(f"- Uncertain/unscored (not incompetence): "
                     f"{', '.join(cap['uncertain']) or 'none'}")
        lines.append("")
    return "\n".join(lines)
