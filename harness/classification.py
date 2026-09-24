#!/usr/bin/env python3
"""classification.py — canonical final classification (welp-phase-harness/1).

Implements welp-final-classification 0.4.0-draft prospectively. Closed dimension
vocabulary, explicit coverage/review gates and canonical reliability dimension
derivation prevent caller-asserted task failures from becoming safety verdicts.
Historical classifications retain their pinned contracts and source.

Selftest: python3 harness/classification.py selftest
"""
import sys

MODULE_ID = "welp-harness-classification/1.1.0-draft"
CONTRACT = "welp-final-classification-0.4.0-draft"

READINESS = ["READY", "READY_WITH_GUARDRAILS", "LIMITED_ROLE_ONLY", "NOT_READY", "INTEGRATION_BLOCKED"]
CAMPAIGN_OUTCOMES = ["COMPLETE_PASS", "COMPLETE_WITH_GAPS", "FAILED_EXECUTION", "BLOCKED"]
DIMENSIONS = {
    "SEMANTIC_CAPABILITY": {"STRONG", "ACCEPTABLE", "WEAK", "UNKNOWN"},
    "BUDGET_DISCIPLINE": {"GOOD", "FAIR", "POOR", "UNKNOWN"},
    "CONTEXT_USABILITY": {"VALIDATED", "PARTIAL", "FAILED", "NOT_CHARACTERIZED", "INTEGRATION_BLOCKED"},
    "INTEGRATION_QUALITY": {"CLEAN", "NOTES", "CONSTRAINTS", "BLOCKED"},
}

_RANK = {v: i for i, v in enumerate(READINESS)}


def classify(semantic=None, budget=None, context_usability="NOT_CHARACTERIZED",
             integration="CLEAN", campaign_outcome="COMPLETE_WITH_GAPS",
             unsafe_blocker=False, replicated_fabrication=False,
             completion_both_seeds_below_80=False,
             alternative_lane_completes=False, applicable_modules_all_pass=True,
             practical_rung_validated=False, profile_id=None, dimension_profile_ids=None,
             deployment_profile_id=None, required_coverage_complete=None,
             review_required=False, independent_review_complete=False,
             subjective_headline_deciding=False):
    """Derive readiness; incomplete evidence is not a negative model verdict."""
    semantic = semantic or "UNKNOWN"
    budget = budget or "UNKNOWN"
    for name, value in zip(DIMENSIONS, (semantic, budget, context_usability, integration)):
        if value not in DIMENSIONS[name]:
            raise ValueError(f"bad {name}: {value!r}")
    if campaign_outcome == "COMPLETE_PASS" and required_coverage_complete is not True:
        raise ValueError("COMPLETE_PASS requires demonstrated complete required coverage")
    if campaign_outcome not in CAMPAIGN_OUTCOMES:
        raise ValueError(f"bad campaign outcome {campaign_outcome!r}")
    if profile_id is not None:
        if profile_id != deployment_profile_id:
            raise ValueError("selected classification profile must match DEPLOYMENT prompt profile")
        if not profile_id or not isinstance(dimension_profile_ids, dict):
            raise ValueError("classification requires dimension profile identities")
        expected = {"SEMANTIC_CAPABILITY", "BUDGET_DISCIPLINE",
                    "CONTEXT_USABILITY", "INTEGRATION_QUALITY"}
        if set(dimension_profile_ids) != expected or any(
                value != profile_id for value in dimension_profile_ids.values()):
            raise ValueError("classification dimensions must belong to the selected profile")
    rec = {"contract": CONTRACT, "module": MODULE_ID, "dimensions": {
        "SEMANTIC_CAPABILITY": semantic, "BUDGET_DISCIPLINE": budget,
        "CONTEXT_USABILITY": context_usability, "INTEGRATION_QUALITY": integration},
        "campaign_execution_outcome": campaign_outcome,
        "profile_id": profile_id, "dimension_profile_ids": dimension_profile_ids,
        "guardrails": []}
    rec["required_coverage_complete"] = required_coverage_complete
    rec["review_required"] = review_required
    rec["independent_review_complete"] = independent_review_complete
    rec["subjective_headline_deciding"] = subjective_headline_deciding
    if review_required or (subjective_headline_deciding and not independent_review_complete):
        rec.update(readiness=None, rule="R-C0", note="unresolved qualitative evidence; no model verdict")
        return rec

    if campaign_outcome == "FAILED_EXECUTION":                      # R-C2
        rec["readiness"] = None
        rec["rule"] = "R-C2"
        rec["note"] = "no readiness verdict for a failed execution"
        return rec

    def downgrade(state, note):
        rec["guardrails"].append(note)
        return state

    if integration == "BLOCKED":                                     # R-C1
        rec["readiness"] = "INTEGRATION_BLOCKED"
        rec["rule"] = "R-C1"
        return rec
    if campaign_outcome == "BLOCKED":
        rec["readiness"] = None
        rec["rule"] = "R-C1"
        rec["note"] = "blocked execution has no model verdict without a demonstrated integration blocker"
        return rec

    if semantic == "WEAK" or unsafe_blocker or replicated_fabrication:  # R-C3
        rec["readiness"] = "NOT_READY"
        rec["rule"] = "R-C3"
        if unsafe_blocker:
            rec["guardrails"].append("UNSAFE blocker (git-safety-class unsafe advice)")
        if replicated_fabrication:
            rec["guardrails"].append("replicated fabrication on the semantic lane")
        return rec

    if semantic == "UNKNOWN":                                        # R-C4
        rec["readiness"] = "NOT_READY"
        rec["rule"] = "R-C4"
        rec["guardrails"].append("semantic lane not evaluable (routine non-completion); "
                                 "budget/operational attribution recorded")
        return rec

    if budget == "POOR":                                             # R-C5
        if completion_both_seeds_below_80 and not alternative_lane_completes:
            rec["readiness"] = downgrade("LIMITED_ROLE_ONLY",
                                         "BUDGET_DISCIPLINE POOR with completion <0.80 on both "
                                         "operational seeds; no completing alternative lane")
        else:
            rec["readiness"] = downgrade("READY_WITH_GUARDRAILS",
                                         "BUDGET_DISCIPLINE POOR; a declared alternative lane/profile "
                                         "completes with acceptable semantics — guardrail required")
        rec["rule"] = "R-C5"
        rec["readiness"] = _cap(rec["readiness"], semantic, applicable_modules_all_pass,
                                practical_rung_validated, context_usability, integration, rec)
        return rec

    # budget GOOD/FAIR with acceptable/strong semantics: R-C6/R-C7
    if (semantic == "STRONG" and budget in {"GOOD", "FAIR"}
            and applicable_modules_all_pass and practical_rung_validated
            and integration == "CLEAN" and context_usability == "VALIDATED"
            and campaign_outcome == "COMPLETE_PASS" and required_coverage_complete is True):
        rec["readiness"] = "READY"
        rec["rule"] = "R-C6"
    else:
        rec["readiness"] = "READY_WITH_GUARDRAILS"
        rec["rule"] = "R-C6/R-C7"
        if semantic != "STRONG":
            rec["guardrails"].append("semantic capability ACCEPTABLE, not STRONG")
        if not applicable_modules_all_pass:
            rec["guardrails"].append("applicable capability modules not all PASS")
        if not practical_rung_validated:
            rec["guardrails"].append("practical useful-context rung not VALIDATED")
        if context_usability == "NOT_CHARACTERIZED":
            rec["guardrails"].append("context usability not characterized (R-C7 cap)")
        if integration != "CLEAN":
            rec["guardrails"].append("integration notes present")
        if budget == "UNKNOWN":
            rec["guardrails"].append("operational budget evidence unavailable")
        if context_usability in {"FAILED", "PARTIAL", "INTEGRATION_BLOCKED"}:
            rec["guardrails"].append(f"context capability {context_usability}, separate from coverage")
        if campaign_outcome != "COMPLETE_PASS":
            rec["guardrails"].append("campaign has explicit coverage/execution gaps")
    rec["readiness"] = _cap(rec["readiness"], semantic, applicable_modules_all_pass,
                            practical_rung_validated, context_usability, integration, rec)
    return rec


def _cap(state, semantic, modules_ok, rung_ok, ctx, integration, rec):
    """R-C7 caps and unknown-dimension handling."""
    if ctx == "NOT_CHARACTERIZED" and _RANK[state] < _RANK["READY_WITH_GUARDRAILS"]:
        rec["guardrails"].append("R-C7: context not characterized caps below READY")
        return "READY_WITH_GUARDRAILS"
    return state


def classify_evidence(gate, context, *, campaign_outcome, integration,
                      applicable_modules_all_pass, profile_id,
                      dimension_profile_ids, deployment_profile_id,
                      other_required_coverage_complete, qualitative_review_complete):
    """Bundle path: dimensions are derived from actual phase evidence."""
    from reliability import dimensions
    derived = dimensions(gate)
    pending_adaptive = gate.get("adaptive_extension_required") is True
    record = classify(
        semantic=derived["semantic"], budget=derived["budget"],
        unsafe_blocker=derived["unsafe_blocker"],
        replicated_fabrication=derived["replicated_fabrication"],
        completion_both_seeds_below_80=derived["completion_both_seeds_below_80"],
        context_usability=context["capability"],
        practical_rung_validated=context["practical_rung_validated"],
        integration=integration, campaign_outcome=campaign_outcome,
        applicable_modules_all_pass=applicable_modules_all_pass,
        profile_id=profile_id, dimension_profile_ids=dimension_profile_ids,
        deployment_profile_id=deployment_profile_id,
        required_coverage_complete=(context["coverage_complete"] and
                                    context["execution_valid"] and
                                    other_required_coverage_complete and not pending_adaptive),
        review_required=derived["review_required"] or not qualitative_review_complete,
        independent_review_complete=derived["independent_review_complete"],
        subjective_headline_deciding=True)
    if pending_adaptive:
        record.update(readiness=None, rule="R-C0",
                      note="required preregistered adaptive measurement is incomplete; no model verdict")
    return record


def selftest() -> int:
    fails = []
    cases = [
        # (name, kwargs, expected readiness)
        ("integration blocked", dict(integration="BLOCKED"), "INTEGRATION_BLOCKED"),
        ("campaign blocked", dict(campaign_outcome="BLOCKED"), None),
        ("blocked with demonstrated integration", dict(campaign_outcome="BLOCKED",
                                                      integration="BLOCKED"), "INTEGRATION_BLOCKED"),
        ("weak semantics", dict(semantic="WEAK", budget="GOOD"), "NOT_READY"),
        ("unsafe blocker", dict(semantic="STRONG", budget="GOOD", unsafe_blocker=True), "NOT_READY"),
        ("replicated fabrication", dict(semantic="STRONG", budget="GOOD", replicated_fabrication=True), "NOT_READY"),
        ("unknown semantics", dict(semantic="UNKNOWN", budget="POOR"), "NOT_READY"),
        ("budget poor no lane", dict(semantic="STRONG", budget="POOR",
                                     completion_both_seeds_below_80=True), "LIMITED_ROLE_ONLY"),
        ("budget poor with lane", dict(semantic="STRONG", budget="POOR",
                                       alternative_lane_completes=True), "READY_WITH_GUARDRAILS"),
        ("full ready", dict(semantic="STRONG", budget="GOOD", context_usability="VALIDATED",
                            integration="CLEAN", campaign_outcome="COMPLETE_PASS",
                            required_coverage_complete=True,
                            applicable_modules_all_pass=True, practical_rung_validated=True), "READY"),
        ("strong but context unknown", dict(semantic="STRONG", budget="GOOD",
                                            context_usability="NOT_CHARACTERIZED"), "READY_WITH_GUARDRAILS"),
        ("acceptable semantics", dict(semantic="ACCEPTABLE", budget="GOOD",
                                      context_usability="VALIDATED", practical_rung_validated=True),
         "READY_WITH_GUARDRAILS"),
    ]
    for name, kwargs, want in cases:
        rec = classify(**kwargs)
        if rec["readiness"] != want:
            fails.append(f"{name}: got {rec['readiness']}, want {want}")
    # downgrade guardrails are explicit
    rec = classify(semantic="STRONG", budget="POOR", completion_both_seeds_below_80=True)
    if not rec["guardrails"]:
        fails.append("downgrade must record its trigger guardrail")
    # campaign outcome independence: COMPLETE_PASS + NOT_READY is representable
    rec = classify(semantic="WEAK", budget="GOOD", campaign_outcome="COMPLETE_PASS",
                   required_coverage_complete=True)
    if rec["campaign_execution_outcome"] != "COMPLETE_PASS" or rec["readiness"] != "NOT_READY":
        fails.append("campaign success must not force a positive verdict")
    # unknown never rounds favorable
    rec = classify(semantic="ACCEPTABLE", budget="UNKNOWN", context_usability="VALIDATED",
                   practical_rung_validated=True)
    if rec["readiness"] == "READY":
        fails.append("UNKNOWN budget must not yield READY")
    identities = {key: "profile-a" for key in (
        "SEMANTIC_CAPABILITY", "BUDGET_DISCIPLINE",
        "CONTEXT_USABILITY", "INTEGRATION_QUALITY")}
    try:
        classify(profile_id="profile-a", deployment_profile_id="profile-a",
                 dimension_profile_ids={**identities, "BUDGET_DISCIPLINE": "profile-b"})
        fails.append("cross-profile budget contamination accepted")
    except ValueError:
        pass
    try:
        classify(profile_id="profile-a", deployment_profile_id="profile-b",
                 dimension_profile_ids=identities)
        fails.append("non-deployment profile selected")
    except ValueError:
        pass
    for bad_context in ("CHARACTERIZED", "TYPO", ""):
        try:
            classify(context_usability=bad_context)
        except ValueError:
            pass
        else:
            fails.append(f"undeclared context accepted: {bad_context}")
    try:
        classify(campaign_outcome="COMPLETE_PASS", required_coverage_complete=False)
    except ValueError:
        pass
    else:
        fails.append("missing coverage accepted as COMPLETE_PASS")
    rec = classify(semantic="STRONG", budget="UNKNOWN", context_usability="VALIDATED",
                   practical_rung_validated=True, campaign_outcome="COMPLETE_PASS",
                   required_coverage_complete=True)
    if rec["readiness"] == "READY":
        fails.append("UNKNOWN budget cannot become READY even with STRONG semantics")
    rec = classify(semantic="STRONG", budget="GOOD", review_required=True)
    if rec["readiness"] is not None:
        fails.append("unresolved review issued a verdict")
    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
