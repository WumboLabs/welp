#!/usr/bin/env python3
"""admission.py — canonical runtime admission module (welp-phase-harness/1).

Codifies the Bonsai lesson (protocol/WELP.md, methodology revision 2026-09-19):
"it loaded, therefore admitted" is prohibited. BASIC admission covers stock
architecture/runtime/artifact; ENHANCED_SEMANTIC admission adds the
known-answer battery whenever a custom quant type, custom fork/runtime,
activation transform, custom kernel, new/unusual architecture, speculative/MTP
component, materially unusual template, or an in-profile multimodal projector
is part of the tested surface. Full admission redesign remains planned P2 work;
this module is the binding minimum for methodology-revision-era campaigns.

Selftest: python3 harness/admission.py selftest
"""
import sys

MODULE_ID = "welp-harness-admission/1.0.0-draft"

ENHANCED_TRIGGERS = [
    "custom_quant_type",
    "custom_fork_runtime",
    "activation_transform",
    "custom_kernel",
    "unusual_architecture",
    "speculative_or_mtp_component",
    "materially_unusual_template",
    "multimodal_projector_in_profile",
]

ADMISSION_LEVELS = ("BASIC", "ENHANCED_SEMANTIC")

KNOWN_ANSWER_BATTERY = {
    "factual": "one stable known-answer factual probe with a frozen exact/accept-set check",
    "reasoning_smoke": "one short reasoning probe requiring a final answer, frozen ceiling",
    "strict_structured_output": "one strict JSON/verbatim-format probe with exact-shape check",
    "absent_information_grounding": "one absent-evidence probe requiring explicit NOT STATED-class refusal",
}


def admission_level(profile_flags) -> str:
    """profile_flags: iterable of trigger names (or empty for stock surfaces)."""
    flags = set(profile_flags or [])
    unknown = flags - set(ENHANCED_TRIGGERS)
    if unknown:
        raise ValueError(f"unknown profile flags: {sorted(unknown)}")
    return "ENHANCED_SEMANTIC" if flags else "BASIC"


def admission_record(profile_flags, battery_results=None):
    level = admission_level(profile_flags)
    rec = {"level": level, "module": MODULE_ID,
           "triggers": sorted(set(profile_flags or []))}
    if level == "ENHANCED_SEMANTIC":
        if not battery_results:
            rec["admitted"] = False
            rec["reason"] = "ENHANCED_SEMANTIC requires the known-answer battery results"
        else:
            missing = sorted(set(KNOWN_ANSWER_BATTERY) - set(battery_results))
            failed = sorted(k for k, v in battery_results.items() if v is not True)
            rec["admitted"] = not missing and not failed
            if missing:
                rec["reason"] = f"battery incomplete: missing {missing}"
            elif failed:
                rec["reason"] = f"battery failed: {failed}"
            else:
                rec["reason"] = "battery passed"
    else:
        rec["admitted"] = True
        rec["reason"] = "BASIC admission (stock surface)"
    return rec


def selftest() -> int:
    fails = []
    if admission_level([]) != "BASIC" or admission_level(None) != "BASIC":
        fails.append("stock surface must be BASIC")
    for trigger in ENHANCED_TRIGGERS:
        if admission_level([trigger]) != "ENHANCED_SEMANTIC":
            fails.append(f"trigger {trigger} must force ENHANCED_SEMANTIC")
    try:
        admission_level(["nonsense_flag"])
        fails.append("unknown flag must raise")
    except ValueError:
        pass
    rec = admission_record(["custom_fork_runtime"])
    if rec["admitted"]:
        fails.append("ENHANCED_SEMANTIC without battery must not admit")
    rec = admission_record(["custom_fork_runtime"], {k: True for k in KNOWN_ANSWER_BATTERY})
    if not rec["admitted"]:
        fails.append(f"full battery must admit: {rec}")
    rec = admission_record(["custom_quant_type"], {"factual": True, "reasoning_smoke": True})
    if rec["admitted"] or "battery incomplete" not in rec["reason"]:
        fails.append(f"incomplete battery must not admit: {rec}")
    rec = admission_record([], {"factual": True})
    if not rec["admitted"]:
        fails.append("BASIC ignores battery; must admit")
    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
