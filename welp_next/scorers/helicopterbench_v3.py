"""HelicopterBench scoring, methodology ``helicopterbench/3`` (prospective,
owner-approved 2026-11-11): the true native 100-point mechanical rubric plus
the independent human playtesting channel.

The rubric keeps the SAME 14 behavioral subchecks, the SAME frozen extraction
contract and the SAME browser-verification isolation as the accepted
methodologies /1 and /2 (``welp_next.scorers.helicopterbench`` and the
in-sandbox CDP driver, which remain frozen and untouched); only the weights
change, so the rubric is natively 100-point:

    launch_and_rendering   20: no_runtime_exceptions 8, canvas_present 6,
                               animation_liveliness 6
    controls_and_physics   20: input_causes_ascent 7, gravity_causes_descent 7,
                               controls_state_numeric 6
    obstacles_and_collision 20: obstacles_present 7, obstacles_advance 6,
                               collision_produces_game_over 7
    score_failure_restart  20: score_accrues 10, game_over_visible_text 5,
                               restart_resets 5
    course_and_difficulty  20: difficulty_increases 10, speed_increases 10

The single final score IS the exact earned mechanical total out of 100:
``normalize_score`` is the identity on earned points — there is no
normalization of a 90-point raw total and no per-category rounding. The
pure-function scoring discipline of /2 is preserved unchanged: environment
errors and unevaluable checks are technical findings, never model failures.

Human playtesting (SPEC §4.11 /3) is a SEPARATE acceptance channel implemented
by ``welp_next.heli_review``: it never enters this automated score, is never
averaged with it and never overwrites automated results. The automated
14-check verifier stays independent of it.
"""
from .helicopterbench import (CORE_KEYS, extract_artifact, sha256_hex,  # noqa: F401
                              submission_record)

METHODOLOGY_VERSION = "helicopterbench/3"
MECHANICAL_MAX = 100

# Frozen mechanical rubric (methodology helicopterbench/3): the same 14
# subchecks as /1 //2 in the same category order, re-weighted so every
# category is worth exactly 20 and the total is natively 100.
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
        "points": 20,
        "subchecks": {"score_accrues": 10, "game_over_visible_text": 5,
                      "restart_resets": 5}},
    "course_and_difficulty": {
        "points": 20,
        "subchecks": {"difficulty_increases": 10, "speed_increases": 10}},
}


def normalize_score(mechanical_points):
    """The v3 rubric is natively 100-point: the final score is the exact
    earned total (float) with no normalization. None (technical invalid /
    nothing submitted) stays None."""
    if mechanical_points is None:
        return None
    return float(mechanical_points)


def rubric_score(record: dict) -> dict:
    """Objective 100-point result from one verification record (pure
    function; methodology helicopterbench/3). Environment errors and
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
