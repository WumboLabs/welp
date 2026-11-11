"""HelicopterBench extraction and scoring (SPEC §4.11, methodology
helicopterbench/2, operator-approved 2026-11-08).

Deterministic submission extraction (frozen contract) and the objective
100-point score mapping from the browser verification record. The rubric is
a pure function over the verification record: no source inspection, no AI
judge, no manual visual review. The single final score is the normalized
mechanical total — ``final_score = mechanical_points / 90 * 100`` computed
from the exact mechanical total and rounded to one decimal place — with the
original mechanical points and category-level evidence kept visible.

Methodology ``helicopterbench/1`` (the same 90-point mechanical rubric plus
a 10-point review-only visual/playability category) is a preserved
historical method: its accepted 2026-11-07 campaign evidence, including the
34/90 mechanical outcome and the pending visual review, is immutable and is
never rescored under v2 (a v2 conversion such as 34 → 37.8 is illustrative
only).

v2 game-over detection (corrected lexical detector): the 4-point check is
measured by the in-sandbox driver as NEW visible text that becomes rendered
exactly with the demonstrated game-over transition; always-visible text,
hidden text and telemetry alone never qualify
(see ``heli_cdp_driver``). The check key is unchanged, so preserved
verification records score identically under both methodologies.
"""
import re
import json

FENCED_HTML = re.compile(r"```html\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)

METHODOLOGY_VERSION = "helicopterbench/2"
MECHANICAL_MAX = 90

# Frozen mechanical rubric (methodology helicopterbench/2): the same 14
# subchecks and category weights as the accepted 90-point mechanical rubric.
# The 10-point review-only visual/playability category of methodology /1 is
# retired; screenshots remain evidence-only.
RUBRIC = {
    "launch_and_rendering": {
        "points": 20,
        "subchecks": {"no_runtime_exceptions": 8, "canvas_present": 6,
                      "animation_liveliness": 6}},
    "controls_and_physics": {
        "points": 20,
        "subchecks": {"input_causes_ascent": 7, "gravity_causes_descent": 7,
                      "controls_state_numeric": 6}},
    "obstacles_and_collision": {
        "points": 20,
        "subchecks": {"obstacles_present": 7, "obstacles_advance": 6,
                      "collision_produces_game_over": 7}},
    "score_failure_restart": {
        "points": 15,
        "subchecks": {"score_accrues": 7, "game_over_visible_text": 4,
                      "restart_resets": 4}},
    "course_and_difficulty": {
        "points": 15,
        "subchecks": {"difficulty_increases": 8, "speed_increases": 7}},
}
CORE_KEYS = ("no_runtime_exceptions", "canvas_present", "animation_liveliness",
             "input_causes_ascent", "gravity_causes_descent",
             "collision_produces_game_over", "restart_resets", "score_accrues")


def extract_artifact(content: str) -> tuple[bytes | None, dict]:
    """Frozen extraction: first fenced html block; else the whole reply when
    it is itself an HTML document. Returns (artifact bytes|None, decision)."""
    if not isinstance(content, str) or not content.strip():
        return None, {"method": "none", "reason": "empty submission"}
    match = FENCED_HTML.search(content)
    if match:
        artifact = match.group(1).encode()
        return artifact, {"method": "fenced_html_block", "block": 1,
                          "chars": len(match.group(1))}
    trimmed = content.strip()
    if trimmed.startswith("<") and "</html>" in trimmed.lower():
        return trimmed.encode(), {"method": "whole_reply", "chars": len(trimmed)}
    return None, {"method": "none",
                  "reason": "completed reply contains no extractable HTML artifact"}


def normalize_score(mechanical_points):
    """Objective final score on the 100-point scale, computed from the exact
    mechanical total and rounded to one decimal place. Per-category values
    are never independently rounded and summed. None (technical invalid /
    nothing submitted) stays None."""
    if mechanical_points is None:
        return None
    return round(mechanical_points / MECHANICAL_MAX * 100, 1)


def rubric_score(record: dict) -> dict:
    """Objective 100-point result from one verification record (pure
    function; methodology helicopterbench/2). Environment errors and
    unevaluable checks are technical findings, never model failures."""
    if "environment_error" in record:
        return {"mechanical_points": None, "mechanical_max": MECHANICAL_MAX,
                "final_score": None, "class": "TECHNICAL_INVALID",
                "environment_error": record["environment_error"],
                "note": "browser verification environment malfunction; "
                        "no model-quality conclusion may be drawn"}
    checks = record.get("checks") or {}
    categories, awarded = {}, 0
    for category, spec in RUBRIC.items():
        detail = {}
        earned = 0
        for check, points in spec["subchecks"].items():
            passed = checks.get(check)
            if passed is True:
                detail[check] = {"pass": True, "points": points}
                earned += points
            elif passed is False:
                detail[check] = {"pass": False, "points": 0}
            else:
                # absent: never executed (e.g. early exit) — unevaluable
                detail[check] = {"pass": None, "points": 0,
                                 "unevaluable": True}
        categories[category] = {"points": earned, "max": spec["points"],
                                "subchecks": detail}
        awarded += earned
    core = {key: checks.get(key) for key in CORE_KEYS}
    if all(v is True for v in core.values()):
        game_class = "FUNCTIONAL_PLAYABLE"
    elif any(v is True for v in core.values()):
        game_class = "PARTIAL"
    else:
        game_class = "NONFUNCTIONAL"
    return {"mechanical_points": awarded, "mechanical_max": MECHANICAL_MAX,
            "final_score": normalize_score(awarded), "class": game_class,
            "categories": categories, "core": core}


def sha256_hex(artifact: bytes) -> str:
    import hashlib
    return hashlib.sha256(artifact).hexdigest()


def submission_record(content) -> dict:
    """Scoring record for the generation attempt (heli_submission scorer):
    completed-with-extractable-artifact VALID; completed-without-artifact is
    a valid artifact-deficiency FAIL; budget/empty dispositions are handled
    by the shared generation semantics before this scorer runs."""
    artifact, decision = extract_artifact(content)
    sha = sha256_hex(artifact) if artifact is not None else None
    semantic = "PASS" if artifact is not None else "FAIL"
    return {"semantic": semantic,
            "extraction": decision,
            "artifact_sha256": sha,
            "artifact_bytes": len(artifact) if artifact is not None else 0,
            "_facets": ("VALID", "COMPLETE", "SCORED_PASS", "NONE") if artifact is not None
                       else ("VALID", "COMPLETE", "SCORED_FAIL", "NONE")}
