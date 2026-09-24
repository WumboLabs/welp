#!/usr/bin/env python3
"""context.py — canonical useful-context phase module (welp-phase-harness/1).

Implements CP-4 (protocol/context-scaling.md C3): historical 2026-09-19
512-token comparator reserve, CP-1 outcomes, rung dispositions and the
five-depth placement gate. Prospective Family A 1.3 construction keeps the
inference-equivalent final rendered token stream and lane-specific reserves.
welp-context-0.2.0-draft additions: score_family_a is the canonical Family A
answer oracle (six gates + review_required; prompt-echo, negation and
ambiguity safe) and context_summary is the campaign coverage/capability
summarizer. Exact mappings live in contracts/welp-context-0.2.0-draft.json.

Selftest: python3 harness/context.py selftest
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from welp_outcomes import derive_completion, derive_budget  # noqa: E402

MODULE_ID = "welp-harness-context/1.1.0-draft"
FIXTURE_FAMILY_A = HERE.parent / "fixtures/useful_context/family-a.json"

REQUIRED_DEPTHS_PCT = [2.0, 25.0, 50.0, 75.0, 95.0]
PLACEMENT_PREFERRED_PP = 0.25
PLACEMENT_HARD_PP = 0.50
OCCUPANCY_PREFERRED_PCT = 99.0
OCCUPANCY_HARD_PCT = 97.0

RESERVE_CONTRACT = "welp-generation-budget-0.1.0-draft"
GATE_ANSWER_BUDGET = 256
STANDARD_RESERVE_TOKENS = 512

# --- canonical Family A answer oracle (welp-context-0.2.0-draft) -----------
#
# score_family_a is a pure function of the produced answer string; the oracle
# values are the frozen Family A facts themselves. The task is unchanged:
# item 2 asks for the year only, so the counts 412/388 are never demanded.
# exact_retrieval keeps its historical decoy clause and is therefore NOT an
# independent task of decoy_resistance — the coupling is disclosed, never
# hidden. Ambiguity never silently passes: the affected gate is false and
# review_required is true. Denial mutations are rejected the same way: a
# sentence negating the code, the year or the count, a quoted value inside
# prose, contradictory claimed values, or a fabricated claim beside the
# refusal marker is review-required with the affected gate false —
# mechanical guards only, no free natural-language truth claims.

GATE_KEYS = ("exact_retrieval", "synthesis", "decoy_resistance",
             "absent_information", "retrieval_95", "instruction_compliance")

ANSWER_CODE = "TR-8842-QX"          # item 1: maintenance tunnel access code
DECOY_CODE = "TR-3319-WD"           # loading dock decoy (never an answer)
MORE_YEAR = "2027"                  # item 2: 412 > 388, so 2027
LESS_YEAR = "2028"
ABSENT_MARKER = "NOT STATED"        # item 3 required refusal marker
MARKER_95 = "357"                   # item 4: 2029 containers
END_MARKER = "END-OF-REPORT"        # item 5 required tail marker

FACT_TEXTS = (
    "The maintenance tunnel access code is TR-8842-QX.",
    "Ridgeline shipments in 2027 totaled 412 containers.",
    "Ridgeline shipments in 2028 totaled 388 containers.",
    "The loading dock uses access code TR-3319-WD.",
    "Ridgeline shipments in 2029 totaled 357 containers.",
)

QUESTION_ECHOES = (
    "Using only the notes above, answer all five items concisely.",
    "What is the maintenance tunnel access code?",
    "Which year had more Ridgeline shipments, 2027 or 2028?",
    "What is the visitor center access code?",
    "If the notes do not state it, answer exactly NOT STATED.",
    "How many containers did Ridgeline ship in 2029?",
    "End your reply with the exact marker END-OF-REPORT and nothing after it.",
)

_ECHO_RES = tuple(
    re.compile(r"\s+".join(re.escape(w) for w in q.split()), re.I)
    for q in QUESTION_ECHOES)
_ITEM_MARK = re.compile(r"(?<![\w.])([1-5])\s*(?:[.):]\s*|-\s+)")
_CODE_RE = re.compile(re.escape(ANSWER_CODE), re.I)
_DECOY_RE = re.compile(re.escape(DECOY_CODE), re.I)
_ABSENT_RE = re.compile(r"not[-\s]+stated", re.I)
_N95_RE = re.compile(r"(?<![\d,])357(?![\d,])")
_YEAR_RE = re.compile(r"\b20\d{2}\b")
_CMP_WORDS = "more|higher|greater|larger|bigger|fewer|less|lower|smaller"
_MORE_SET = frozenset(("more", "higher", "greater", "larger", "bigger"))
_CMP_THAN_RE = re.compile(
    r"\b(20\d{2})\b[^.!?\n]{0,120}?\b(" + _CMP_WORDS +
    r")\b[^.!?\n]{0,120}?\bthan\b[^.!?\n]{0,40}?\b(20\d{2})\b", re.I)
_CMP_BARE_RE = re.compile(
    r"\b(20\d{2})\b[^.!?\n]{0,80}?\b(" + _CMP_WORDS + r")\b", re.I)
_NEG_HEDGE_RE = re.compile(
    r"\b(?:not|no|none|never|neither|nor|cannot|can't|unclear|unsure|unknown|"
    r"insufficient|impossible|same|equal|identical|tied)\b|\b\w+n't\b", re.I)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SYN_SCOPE_RE = re.compile(r"\b(?:2027|2028)\b|\b(?:" + _CMP_WORDS + r")\b")
_CODE_LIKE_RE = re.compile(r"\b[A-Z]{2}-\d{4}-[A-Z]{2}\b", re.I)
_QUOTED_CODE_RE = re.compile(
    r"[\"'`“”‘’]\s*(TR-8842-QX)\s*[\"'`“”‘’]", re.I)
_INT_RE = re.compile(r"(?<![\d,])\d+(?![\d,])")
_QUOTED_YEAR_RE = re.compile(r"[\"'`“”‘’]\s*(20\d{2})\s*[\"'`“”‘’]")
_YEAR_FRAME_RE = re.compile(
    r"\b(20\d{2})\s*(?:-|,|;|:|/|\bor\b|\bvs\b|\bversus\b|\band\b|\bto\b)"
    r"\s*(20\d{2})\b")


def standardized_reserve(gate_answer_budget: int = GATE_ANSWER_BUDGET) -> int:
    """Historical reserve = max(512, 2 x gate answer budget); not a new semantic cap."""
    return max(512, 2 * gate_answer_budget)


def placement_errors(depths_pct):
    """Absolute errors vs the required depth set. depths_pct: {label: pct}."""
    required = sorted(REQUIRED_DEPTHS_PCT)
    observed = sorted(depths_pct.values())
    if len(observed) != len(required):
        return None, f"expected {len(required)} placed targets, got {len(observed)}"
    errs = [abs(o - r) for o, r in zip(observed, required)]
    return max(errs), None


def placement_preflight(depths_pct):
    err, problem = placement_errors(depths_pct)
    if problem:
        return {"pass": False, "error": problem}
    hard_ok = err <= PLACEMENT_HARD_PP
    pref_ok = err <= PLACEMENT_PREFERRED_PP
    return {"pass": hard_ok, "max_error_pp": round(err, 3),
            "preferred": pref_ok, "hard": hard_ok}


def construct_family_a(usable_tokens: int, seed: int, measure, max_attempts: int = 30):
    """Place facts against the final rendered stream before any inference.

    measure(content) returns (final_token_count, {fact_target: token_start}).
    It must apply the pinned chat template and tokenize with the same BOS
    behavior as inference. The caller retains each attempt as preflight evidence.
    """
    import random

    if usable_tokens < 1024 or max_attempts < 1:
        raise ValueError("invalid usable context or preflight bound")
    fixture = json.loads(FIXTURE_FAMILY_A.read_text())
    construction = fixture["construction"]
    facts = construction["inserted_facts"]
    pool = construction["word_pool"]
    n = max(1, int(usable_tokens * 0.9))
    positions = [max(0, min(n - 1, int(f["depth"] * n))) for f in facts]
    attempts = []
    for _ in range(max_attempts):
        rng = random.Random(seed)
        words = [rng.choice(pool) for _ in range(n)]
        if len(set(positions)) != len(positions):
            raise ValueError("fact positions collide at this context")
        for pos, fact in zip(positions, facts):
            words[pos] = fact["text"]
        content = " ".join(words) + "\n" + construction["question_block"]
        total, offsets = measure(content)
        if (not isinstance(total, int) or total <= 0 or
                set(offsets) != {f["target"] for f in facts} or
                any(not isinstance(x, int) or x < 0 or x >= total for x in offsets.values())):
            raise ValueError("invalid final-rendered token measurement")
        depths = {f["target"]: 100 * offsets[f["target"]] / total for f in facts}
        preflight = placement_preflight(depths)
        occupancy = 100 * total / usable_tokens
        attempts.append({"rendered_tokens": total, "occupancy_pct": occupancy,
                         "depths_pct": depths, "placement": preflight})
        if 97 <= occupancy <= 100 and preflight["pass"]:
            return {"content": content, "filler_words": n, "positions": positions,
                    "rendered_tokens": total, "preflight": attempts}
        next_n = max(len(facts) + 1, round(n * (0.992 * usable_tokens) / total))
        positions = [max(0, min(next_n - 1, round(
            pos * next_n / n + (f["depth"] * total - offsets[f["target"]])
            * next_n / total)))
            for pos, f in zip(positions, facts)]
        n = next_n
    raise ValueError(f"Family A placement/occupancy failed after {max_attempts} attempts")


def rung_outcome(gates: dict, finish, content: str, usage: dict = None,
                 reserve: int = STANDARD_RESERVE_TOKENS):
    """Assemble the CP-1 outcome + rung disposition for one useful-context request.

    gates: {"exact_retrieval": bool, "synthesis": bool, "decoy_resistance": bool,
            "absent_information": bool, "retrieval_95": bool, "instruction_compliance": bool}
    Canonical source: score_family_a(content); its extra keys (review_required,
    review_reasons) are ignored here and never flip a rung. Only the six
    GATE_KEYS are consumed; a gate left None (not evaluated because no answer
    exists) stays None.
    """
    completion = derive_completion(finish, content, usage, reserve)
    has_reasoning = bool((usage or {}).get("reasoning_tokens"))
    budget = derive_budget(finish, completion, content, has_reasoning)

    answered = content.strip() != ""
    gate_values = {k: (gates.get(k) if answered else None) for k in GATE_KEYS}
    evaluated = [v for v in gate_values.values() if v is not None]

    if completion == "COMPLETE":
        all_pass = all(gate_values.values())
        rung = "VALIDATED" if all_pass else "FAILED"
        semantic = "PASS" if all_pass else "FAIL"
    elif completion == "FAIL_LENGTH":
        # Bonsai 65K rule: strong retrieval/synthesis evidence with a starved
        # answer is BUDGET_LIMITED, never a retrieval failure; without any
        # usable answer the gates are simply not evaluable. A forbidden
        # assertion in the produced channel (decoy containment) keeps the
        # semantic FAIL evidence — truncation does not unsay it.
        strong = (gates.get("exact_retrieval") or gates.get("synthesis")) is True and answered
        rung = "BUDGET_LIMITED" if strong else "NOT_EVALUABLE"
        semantic = "FAIL" if _forbidden_asserted(gates) else "NOT_EVALUABLE"
    else:  # EMPTY_ANSWER / INVALID_STOP
        rung = "BUDGET_LIMITED" if completion == "EMPTY_ANSWER" else "INVALID_REQUEST"
        semantic = "NOT_EVALUABLE"

    return {
        "rung": rung,
        "semantic": semantic,
        "completion": completion,
        "budget": budget,
        "finish_reason": finish,
        "gates": gate_values,
        "reserve_tokens": reserve,
    }


def _forbidden_asserted(gates: dict) -> bool:
    # A decoy containment in a produced channel is positive evidence of a
    # wrong answer even when truncated.
    return gates.get("decoy_resistance") is False


def _strip_echo(text: str) -> str:
    """Remove question-block sentences so echoing the prompt never scores."""
    out = text
    for pat in _ECHO_RES:
        out = pat.sub(" ", out)
    return out


def _numbered_segments(text: str):
    """Split on unique ascending 1-4 item markers; last occurrence wins so
    leftover echo numbering cannot take the item slots."""
    picks = {}
    for m in _ITEM_MARK.finditer(text):
        picks[int(m.group(1))] = (m.start(), m.end())
    if any(n not in picks for n in (1, 2, 3, 4)):
        return None
    starts = [picks[n][0] for n in (1, 2, 3, 4)]
    if sorted(starts) != starts or len(set(starts)) != 4:
        return None
    segs = []
    for n in (1, 2, 3, 4):
        start = picks[n][1]
        if n < 4:
            stop = picks[n + 1][0]
        else:
            stop = picks[5][0] if 5 in picks and picks[5][0] > start else len(text)
        segs.append(text[start:stop])
    return segs


def _line_segments(text: str):
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[:4] if len(lines) in (4, 5) else None


def _slot_segments(text: str):
    if "\n" in text:
        return None
    slots = [s.strip() for s in re.split(r"[,;|]", text) if s.strip()]
    return slots[:4] if 4 <= len(slots) <= 6 else None


def _segments(content: str):
    """Return (echo-stripped text, [item1..item4 segments] or None).

    None means single-segment mode: no structure found, gates fall back to
    the historical whole-answer containment semantics.
    """
    stripped = _strip_echo(content)
    numbered = _numbered_segments(stripped)
    if numbered:
        return stripped, [s.strip() for s in numbered]
    lines = _line_segments(stripped)
    if lines:
        return stripped, lines
    slots = _slot_segments(stripped)
    if slots:
        return stripped, slots
    return stripped, None


def _synthesis_gate(seg: str, review: list):
    """Item 2: which year had more Ridgeline shipments (412 > 388 -> 2027).

    Returns (gate, review_hit). Bare "2027" and explicit comparatives decide
    on the claimed ordering; the counts are never demanded. Negations or
    hedges inside sentences carrying the year/comparative claim, both years
    without an ordering claim, quoted year mentions and echo-only segments
    are review-required, never silent passes. A refusal marker belonging to
    item 3 elsewhere in an unstructured whole-answer segment never counts as
    item-2 hedging.
    """
    t = seg.strip()
    if not t:
        review.append("synthesis: no item-2 answer after prompt-echo removal")
        return False, True
    # Hedge/negation disqualifies only where the year/comparative claim
    # lives; the item-3 "NOT STATED." marker must not poison whole-answer
    # prose, while "2027 did not have more ... than 2028" must never parse
    # as a pass.
    if any(_NEG_HEDGE_RE.search(s)
           for s in _SENT_SPLIT_RE.split(t) if _SYN_SCOPE_RE.search(s)):
        review.append("synthesis: negated/hedged item-2 text")
        return False, True
    claims = []
    for m in _CMP_THAN_RE.finditer(t):
        y1, word, y2 = m.group(1), m.group(2).lower(), m.group(3)
        if {y1, y2} != {MORE_YEAR, LESS_YEAR}:
            review.append(f"synthesis: comparative over unexpected years {y1}/{y2}")
            return False, True
        greater = y1 if word in _MORE_SET else y2
        claims.append(greater == MORE_YEAR)
    for m in _CMP_BARE_RE.finditer(t):
        y1, word = m.group(1), m.group(2).lower()
        if y1 not in (MORE_YEAR, LESS_YEAR):
            review.append(f"synthesis: comparative on unexpected year {y1}")
            return False, True
        claims.append((y1 == MORE_YEAR) if word in _MORE_SET else (y1 == LESS_YEAR))
    if claims:
        residue = _CMP_BARE_RE.sub(" ", _CMP_THAN_RE.sub(" ", t))
        for year in _YEAR_RE.findall(residue):
            if year not in (MORE_YEAR, LESS_YEAR):
                review.append("synthesis: additional unresolved year claim")
                return False, True
            claims.append(year == MORE_YEAR)
        if len(set(claims)) != 1:
            review.append("synthesis: contradictory year claims")
            return False, True
        return claims[0], False
    quoted = _QUOTED_YEAR_RE.findall(t)
    residue = _QUOTED_YEAR_RE.sub(" ", t)
    if quoted and re.search(r"\w", residue):
        review.append("synthesis: quoted year inside prose, not a clear answer")
        return False, True
    reduced = _YEAR_FRAME_RE.sub(
        lambda mm: " " if {mm.group(1), mm.group(2)} == {MORE_YEAR, LESS_YEAR}
        else mm.group(0), t)
    years = _YEAR_RE.findall(reduced)
    if years == [MORE_YEAR]:
        return True, False
    if years == [LESS_YEAR]:
        return False, False
    review.append("synthesis: ambiguous year evidence (%s)"
                  % (",".join(years) or "none"))
    return False, True


def score_family_a(content: str) -> dict:
    """Canonical Family A answer scoring (welp-context-0.2.0-draft).

    Accepts numbered or un-numbered concise answers: unique ascending 1-4
    item markers, 4-5 un-numbered lines, or 4-6 comma/semicolon/pipe slots;
    without structure the historical whole-answer containment semantics
    apply. Question-block echo is removed before scoring, so echoing the
    prompt can never satisfy a gate. The unstructured whole-answer mode also
    accepts single-paragraph prose whose comparative sentence names the year;
    the item-3 refusal marker never counts as item-2 hedging there. Ambiguity
    or denial (echo without an answer, negated/hedged code/year/count claims,
    quoted code/year mentions inside prose, contradictory claimed codes or
    counts, fabricated claims beside the refusal marker, both years without
    ordering, answers at the wrong item) sets review_required=true with the
    affected gate false — never an inferred safe PASS. exact_retrieval
    includes decoy absence: it is deliberately coupled to decoy_resistance,
    not an independent task.
    """
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    if not content.strip():
        return {**dict.fromkeys(GATE_KEYS, False), "review_required": False,
                "review_reasons": ["empty answer"]}
    review = []
    stripped, segs = _segments(content)
    if segs is None:
        seg1 = seg2 = seg3 = seg4 = stripped
    else:
        seg1, seg2, seg3, seg4 = segs
    decoy_absent = not _DECOY_RE.search(stripped)
    # Item 1: denial, quotation and contradiction guards. A sentence that
    # denies or hedges the code, a quoted code inside prose, or the correct
    # code claimed alongside another code is review-required, never a pass;
    # a denied other code is not a claim.
    code_sents = [s for s in _SENT_SPLIT_RE.split(seg1) if _CODE_RE.search(s)]
    code_found = bool(code_sents)
    exact_reasons = []
    if code_found and any(_NEG_HEDGE_RE.search(s) for s in code_sents):
        exact_reasons.append("exact_retrieval: negated/hedged item-1 answer")
    if (_QUOTED_CODE_RE.search(seg1)
            and re.search(r"\w", _QUOTED_CODE_RE.sub(" ", seg1))):
        exact_reasons.append(
            "exact_retrieval: quoted code inside prose, not a clear answer")
    claimed_codes = set()
    for s in _SENT_SPLIT_RE.split(seg1):
        if _NEG_HEDGE_RE.search(s):
            continue
        claimed_codes.update(m.group(0).upper() for m in _CODE_LIKE_RE.finditer(s))
    if ANSWER_CODE.upper() in claimed_codes and len(claimed_codes) > 1:
        exact_reasons.append(
            "exact_retrieval: contradictory claimed codes (%s)"
            % ",".join(sorted(claimed_codes)))
    exact = code_found and decoy_absent and not exact_reasons
    review.extend(exact_reasons)
    if not code_found and not seg1.strip():
        review.append("exact_retrieval: no item-1 answer after prompt-echo removal")
    syn, _ = _synthesis_gate(seg2, review)
    # Item 3: the refusal marker with a fabricated code/count beside it, or
    # a fabricated claim elsewhere in a structured item-3 answer, is a
    # contradiction, never a pass.
    absent = bool(_ABSENT_RE.search(seg3))
    absent_reasons = []
    if absent:
        for s in _SENT_SPLIT_RE.split(seg3):
            if not _ABSENT_RE.search(s):
                continue
            residue = _YEAR_RE.sub(
                " ", _CODE_LIKE_RE.sub(" ", _ABSENT_RE.sub(" ", s)))
            if _CODE_LIKE_RE.search(s) or _INT_RE.findall(residue):
                absent_reasons.append(
                    "absent_information: fabricated claim beside the refusal marker")
                break
        if segs is not None and not re.fullmatch(r"\s*NOT\s+STATED[.!]?\s*", seg3, re.I):
            absent_reasons.append(
                "absent_information: structured item 3 must contain only the requested refusal marker")
    absent = absent and not absent_reasons
    review.extend(absent_reasons)
    if "?" in seg3:
        absent = False
        review.append("absent_information: interrogative echo text at item 3")
    elif not seg3.strip():
        review.append("absent_information: no item-3 answer after prompt-echo removal")
    # Item 4: denial and contradiction guards mirror item 1.
    n95_sents = [s for s in _SENT_SPLIT_RE.split(seg4) if _N95_RE.search(s)]
    r95 = bool(n95_sents)
    if r95 and any(_NEG_HEDGE_RE.search(s) for s in n95_sents):
        r95 = False
        review.append("retrieval_95: negated/hedged item-4 answer")
    elif r95:
        count_sents = _SENT_SPLIT_RE.split(seg4) if segs is not None else n95_sents
        for s in count_sents:
            if _NEG_HEDGE_RE.search(s):
                continue
            t = _YEAR_RE.sub(" ", _CODE_LIKE_RE.sub(" ", s))
            extra = sorted(set(_INT_RE.findall(t)) - {MARKER_95})
            if extra:
                r95 = False
                review.append(
                    "retrieval_95: contradictory claimed counts (%s)" % ",".join(extra))
                break
    if not r95:
        if not seg4.strip():
            review.append("retrieval_95: no item-4 answer after prompt-echo removal")
        elif not any(ch.isdigit() for ch in seg4):
            review.append("retrieval_95: item-4 answer carries no number")
    compliant = content.rstrip().endswith(END_MARKER)
    return {
        "exact_retrieval": exact,
        "synthesis": syn,
        "decoy_resistance": decoy_absent,
        "absent_information": absent,
        "retrieval_95": r95,
        "instruction_compliance": compliant,
        "review_required": bool(review),
        "review_reasons": review,
    }


# --- campaign coverage/capability summary (welp-context-0.2.0-draft) -------

DISPOSITION_VOCAB = ("VALIDATED", "FAILED", "BUDGET_LIMITED", "PARTIAL",
                     "NOT_TESTED", "FIT_LIMIT", "INTEGRATION_BLOCKED")
LANE_VOCAB = ("semantic", "operational")
COVERING_DISPOSITIONS = frozenset(
    ("VALIDATED", "FAILED", "FIT_LIMIT", "INTEGRATION_BLOCKED"))
MEASURED_DISPOSITIONS = frozenset(
    ("VALIDATED", "FAILED", "BUDGET_LIMITED", "FIT_LIMIT", "INTEGRATION_BLOCKED"))


def _plain_int(value) -> bool:
    # bool is an int subclass in Python; plans/rows need real ints.
    return isinstance(value, int) and not isinstance(value, bool)


def _trusted(row: dict) -> bool:
    """A row measures only with valid execution and actual evidence."""
    return bool(row["execution_valid"]) and row["evidence"] != ""


def context_summary(plan: dict, rows: list) -> dict:
    """Summarize planned campaign coverage and capability (welp-context-0.2.0-draft).

    plan: required_rungs (unique positive ints), lanes (semantic/operational),
    seeds (unique ints), practical_rung (a planned rung). rows: one dict per
    observed cell with configured_context/lane/seed/disposition/
    execution_valid/evidence. Duplicates, unplanned cells and malformed
    inputs raise ValueError; missing planned cells are a valid INCOMPLETE
    summary, never an exception. Required negative (FAILED) rows complete
    coverage; BUDGET_LIMITED/PARTIAL/NOT_TESTED, invalid execution and empty
    evidence never do; FIT_LIMIT alone is never a model failure.
    """
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dict")
    missing_keys = [k for k in ("required_rungs", "lanes", "seeds",
                                "practical_rung") if k not in plan]
    if missing_keys:
        raise ValueError(f"plan missing keys: {missing_keys}")
    rungs = plan["required_rungs"]
    if (not isinstance(rungs, list) or not rungs
            or any(not _plain_int(r) or r <= 0 for r in rungs)
            or len(set(rungs)) != len(rungs)):
        raise ValueError("plan.required_rungs must be a non-empty list of "
                         "unique positive ints")
    lanes = plan["lanes"]
    if (not isinstance(lanes, list) or not lanes
            or any(l not in LANE_VOCAB for l in lanes)
            or len(set(lanes)) != len(lanes)):
        raise ValueError("plan.lanes must be a non-empty unique list from "
                         "['semantic', 'operational']")
    seeds = plan["seeds"]
    if (not isinstance(seeds, list) or not seeds
            or any(not _plain_int(s) for s in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("plan.seeds must be a non-empty unique list of ints")
    practical = plan["practical_rung"]
    if not _plain_int(practical) or practical not in rungs:
        raise ValueError("plan.practical_rung must be a planned positive-int rung")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")

    required = [(r, l, s) for r in rungs for l in lanes for s in seeds]
    by_cell = {}
    execution_valid = True
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"row must be a dict: {row!r}")
        for key in ("configured_context", "lane", "seed", "disposition",
                    "execution_valid", "evidence"):
            if key not in row:
                raise ValueError(f"row missing key {key!r}: {row!r}")
        ctx, lane, seed = row["configured_context"], row["lane"], row["seed"]
        if not _plain_int(ctx) or ctx not in rungs:
            raise ValueError(f"unplanned/invalid configured_context: {ctx!r}")
        if not isinstance(lane, str) or lane not in lanes:
            raise ValueError(f"unplanned/invalid lane: {lane!r}")
        if not _plain_int(seed) or seed not in seeds:
            raise ValueError(f"unplanned/invalid seed: {seed!r}")
        disp = row["disposition"]
        if not isinstance(disp, str) or disp not in DISPOSITION_VOCAB:
            raise ValueError(f"invalid disposition: {disp!r}")
        ev = row["execution_valid"]
        if not isinstance(ev, bool):
            raise ValueError(f"execution_valid must be a strict bool: {ev!r}")
        evidence = row["evidence"]
        if not isinstance(evidence, str):
            raise ValueError(f"evidence must be a string: {evidence!r}")
        cell = (ctx, lane, seed)
        if cell in by_cell:
            raise ValueError(f"duplicate planned cell: {ctx}/{lane}/{seed}")
        by_cell[cell] = row
        execution_valid = execution_valid and ev

    covered = {c for c, row in by_cell.items()
               if row["disposition"] in COVERING_DISPOSITIONS and _trusted(row)}
    missing_cells = [f"{r}/{l}/{s}" for (r, l, s)
                     in sorted(c for c in required if c not in covered)]

    # Capability is judged at the practical rung only. VALIDATED needs every
    # practical cell to pass; INTEGRATION_BLOCKED needs every practical cell
    # blocked; FAILED needs every trusted measured row FAILED with no pass
    # (missing cells do not soften a fully-negative measured set); FIT_LIMIT
    # is a harness fit limit, never a model failure by itself.
    practical_cells = [c for c in required if c[0] == practical]
    measurements = {c: by_cell[c] for c in practical_cells
                    if c in by_cell and by_cell[c]["disposition"] in MEASURED_DISPOSITIONS
                    and _trusted(by_cell[c])}
    practical_rung_validated = all(
        c in measurements and measurements[c]["disposition"] == "VALIDATED"
        for c in practical_cells)
    if not measurements:
        capability = "NOT_CHARACTERIZED"
    elif practical_rung_validated:
        capability = "VALIDATED"
    elif all(c in measurements
             and measurements[c]["disposition"] == "INTEGRATION_BLOCKED"
             for c in practical_cells):
        capability = "INTEGRATION_BLOCKED"
    elif all(m["disposition"] == "FAILED" for m in measurements.values()):
        capability = "FAILED"
    else:
        capability = "PARTIAL"

    useful_context_max = {}
    for lane in lanes:
        best = None
        for rung in sorted(rungs, reverse=True):
            if all((rung, lane, s) in by_cell
                   and by_cell[(rung, lane, s)]["disposition"] == "VALIDATED"
                   and _trusted(by_cell[(rung, lane, s)])
                   for s in seeds):
                best = rung
                break
        useful_context_max[lane] = best

    return {
        "coverage_complete": not missing_cells,
        "execution_valid": execution_valid,
        "required_cells": len(required),
        "covered_cells": len(covered),
        "missing_cells": missing_cells,
        "capability": capability,
        "useful_context_max": useful_context_max,
        "practical_rung_validated": practical_rung_validated,
    }


def selftest() -> int:
    fails = []
    if standardized_reserve() != 512:
        fails.append(f"reserve rule: {standardized_reserve()}")
    if standardized_reserve(300) != 600:
        fails.append("reserve rule must be max(512, 2x budget)")

    pf = placement_preflight({"a": 1.99, "b": 24.99, "c": 49.89, "d": 74.84, "e": 94.944})
    if not (pf["pass"] and pf["preferred"]):
        fails.append(f"placement preflight should pass preferred: {pf}")
    pf = placement_preflight({"a": 2.4, "b": 25.0, "c": 50.0, "d": 75.0, "e": 95.0})
    if not (pf["pass"] and not pf["preferred"]):
        fails.append(f"0.4pp error should pass hard not preferred: {pf}")
    pf = placement_preflight({"a": 2.7, "b": 25.0, "c": 50.0, "d": 75.0, "e": 95.0})
    if pf["pass"]:
        fails.append("0.7pp error must fail hard bound")
    pf = placement_preflight({"a": 2.0, "b": 25.0, "c": 50.0, "d": 75.0})
    if pf["pass"]:
        fails.append("four-depth set must fail preflight (post-completion campaign practice)")

    all_pass = {"exact_retrieval": True, "synthesis": True, "decoy_resistance": True,
                "absent_information": True, "retrieval_95": True, "instruction_compliance": True}
    r = rung_outcome(all_pass, "stop", "1. TR-8842-QX ...", {"completion_tokens": 75})
    if r["rung"] != "VALIDATED" or r["semantic"] != "PASS" or r["budget"] != "WITHIN":
        fails.append(f"validated rung: {r}")

    # Bonsai 65K seed-42 shape: empty answer, 512 consumed, finish unavailable (ctx pre-revision)
    r = rung_outcome({"exact_retrieval": None, "synthesis": None, "decoy_resistance": True,
                      "absent_information": None, "retrieval_95": None, "instruction_compliance": None},
                     None, "", {"completion_tokens": 512})
    if r["completion"] != "FAIL_LENGTH" or r["semantic"] != "NOT_EVALUABLE":
        fails.append(f"bonsai empty-truncated shape: {r}")
    if r["rung"] not in ("BUDGET_LIMITED", "NOT_EVALUABLE"):
        fails.append(f"bonsai rung must not be FAILED: {r}")

    # BUDGET_LIMITED with strong retrieval evidence in a partial answer
    r = rung_outcome({"exact_retrieval": True, "synthesis": True, "decoy_resistance": True,
                      "absent_information": None, "retrieval_95": None, "instruction_compliance": None},
                     "length", "1. TR-8842-QX\n2. 2027", {"completion_tokens": 512})
    if r["rung"] != "BUDGET_LIMITED" or r["semantic"] != "NOT_EVALUABLE":
        fails.append(f"budget-limited rung: {r}")

    # Completed answer violating a gate -> FAILED, semantic FAIL
    r = rung_outcome({**all_pass, "absent_information": False}, "stop",
                     "1. TR-8842-QX ...\n3. TR-9999", {"completion_tokens": 90})
    if r["rung"] != "FAILED" or r["semantic"] != "FAIL":
        fails.append(f"failed gate rung: {r}")

    # Decoy asserted in a truncated channel -> semantic FAIL evidence retained
    r = rung_outcome({"exact_retrieval": True, "synthesis": None, "decoy_resistance": False,
                      "absent_information": None, "retrieval_95": None, "instruction_compliance": None},
                     "length", "1. TR-8842-QX; loading dock code TR-3319-WD", {"completion_tokens": 512})
    if r["semantic"] != "FAIL" or r["rung"] != "BUDGET_LIMITED":
        fails.append(f"decoy-in-truncated must keep FAIL evidence: {r}")

    # fixture sanity
    fx = json.loads(FIXTURE_FAMILY_A.read_text())
    if fx["construction"]["depths_required"] != [0.02, 0.25, 0.50, 0.75, 0.95]:
        fails.append("family A must carry the five contract depths")
    if fx["generation_budget"]["reserve_tokens"] != standardized_reserve():
        fails.append("family A reserve must equal the standardized reserve")

    # Synthetic tokenizer, NOT model evidence: fixed BOS/template and question tail
    # make naive filler-fraction placement fail at 8K and 16K.
    def synthetic_measure(content):
        tokens = ["<bos>", "<user>"] + [word.strip(".,") for word in content.split()] + ["</user>"]
        offsets = {}
        for fact in fx["construction"]["inserted_facts"]:
            target = fact["target"].split()
            offsets[fact["target"]] = next(
                i for i in range(len(tokens) - len(target) + 1)
                if tokens[i:i + len(target)] == target)
        return len(tokens), offsets

    for usable in (7680, 15872):
        try:
            constructed = construct_family_a(usable, 42, synthetic_measure)
            if not constructed["preflight"][-1]["placement"]["pass"]:
                fails.append(f"Family A placement at {usable}")
            if len(constructed["preflight"]) > 30:
                fails.append("unbounded Family A preflight")
        except ValueError as exc:
            fails.append(f"Family A construction at {usable}: {exc}")
    try:
        construct_family_a(7680, 42, lambda _: (1, {}))
        fails.append("malformed token evidence must fail")
    except ValueError:
        pass

    # --- welp-context-0.2.0-draft: canonical Family A answer oracle ----------
    # Reference: both frozen canonical retained answers plus the alternate
    # line/slot shapes must pass every gate with no review demand.
    references = {
        "numbered": "1. TR-8842-QX\n2. 2027\n3. NOT STATED\n4. 357\n5. END-OF-REPORT",
        "prose": ("Maintenance tunnel access code is TR-8842-QX. 2027 had more "
                  "Ridgeline shipments than 2028. NOT STATED. 357. END-OF-REPORT"),
        "lines": "TR-8842-QX\n2027\nNOT STATED\n357\nEND-OF-REPORT",
        "slots": "TR-8842-QX; 2027; NOT STATED; 357. END-OF-REPORT",
    }
    for name, answer in references.items():
        s = score_family_a(answer)
        if not all(s[k] for k in GATE_KEYS) or s["review_required"]:
            fails.append(f"oracle reference {name} must pass clean: {s}")

    s = score_family_a("   ")
    if any(s[k] for k in GATE_KEYS) or s["review_required"]:
        fails.append(f"blank answer must be all-false without review: {s}")
    try:
        score_family_a(None)
        fails.append("non-string content must raise TypeError")
    except TypeError:
        pass

    # Echo rejection: the bare question block scores nothing and demands
    # review; a prepended or inlined echo never poisons a genuine answer.
    s = score_family_a(fx["construction"]["question_block"])
    if (any(s[k] for k in ("exact_retrieval", "synthesis", "absent_information",
                           "retrieval_95", "instruction_compliance"))
            or s["decoy_resistance"] is not True or not s["review_required"]):
        fails.append(f"pure prompt echo must score nothing and demand review: {s}")
    s = score_family_a("Using only the notes above, answer all five items "
                       "concisely.\n" + references["numbered"])
    if not all(s[k] for k in GATE_KEYS) or s["review_required"]:
        fails.append(f"echo preamble must not block a genuine answer: {s}")
    s = score_family_a(
        "1. What is the maintenance tunnel access code? TR-8842-QX\n"
        "2. Which year had more Ridgeline shipments, 2027 or 2028? 2027\n"
        "3. What is the visitor center access code? NOT STATED\n"
        "4. How many containers did Ridgeline ship in 2029? 357\n"
        "5. END-OF-REPORT")
    if not all(s[k] for k in GATE_KEYS) or s["review_required"]:
        fails.append(f"inline echoed questions must not poison items: {s}")

    # Negative: decisive wrong answers are hard gate failures, no review.
    numbered = references["numbered"]
    s = score_family_a(numbered.replace("2. 2027", "2. 2028"))
    if s["synthesis"] or s["review_required"]:
        fails.append(f"wrong year must fail synthesis without review: {s}")
    s = score_family_a(numbered.replace("TR-8842-QX", "TR-3319-WD"))
    if s["decoy_resistance"] or s["exact_retrieval"] or not s["synthesis"]:
        fails.append(f"asserted decoy must fail decoy_resistance+exact only: {s}")
    s = score_family_a(numbered.replace("TR-8842-QX", "TR-0000-AA"))
    if s["exact_retrieval"] or s["decoy_resistance"] is not True:
        fails.append(f"wrong code must fail exact_retrieval only: {s}")
    s = score_family_a(numbered.replace("3. NOT STATED", "3. TR-0000-AA"))
    if s["absent_information"] or s["review_required"]:
        fails.append(f"fabricated item-3 answer must fail hard: {s}")
    s = score_family_a(numbered.replace("4. 357", "4. 314"))
    if s["retrieval_95"] or s["review_required"]:
        fails.append(f"wrong 95% count must fail hard: {s}")
    s = score_family_a(numbered.replace("\n5. END-OF-REPORT", ""))
    if s["instruction_compliance"] or not s["retrieval_95"]:
        fails.append(f"dropped tail marker must fail compliance only: {s}")

    # Mutation: ambiguity is review-required with the affected gate false,
    # never an inferred safe PASS and never silent false confidence.
    s = score_family_a(numbered.replace(
        "2. 2027", "2. not sure whether 2027 or 2028"))
    if s["synthesis"] or not s["review_required"] or not any(
            "synthesis" in r for r in s["review_reasons"]):
        fails.append(f"hedged item-2 must be review-required: {s}")
    s = score_family_a(numbered.replace("2. 2027", "2. 2027 and 2028"))
    if s["synthesis"] or not s["review_required"]:
        fails.append(f"both years without ordering must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "2. 2027", '2. the "2027" figure'))
    if s["synthesis"] or not s["review_required"]:
        fails.append(f"quoted-year prose must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "2. 2027", "2. 2027 did not have more shipments than 2028"))
    if s["synthesis"] or not s["review_required"]:
        fails.append(f"negated comparative must not pass synthesis: {s}")

    # Denial mutations: a negated code or count is never a pass; the
    # affected gate goes false under review while the other gates stand.
    s = score_family_a(numbered
                       .replace("1. TR-8842-QX", "1. The code is not TR-8842-QX")
                       .replace("4. 357", "4. The count is not 357"))
    if (s["exact_retrieval"] or s["retrieval_95"] or not s["review_required"]
            or not s["synthesis"] or not s["absent_information"]
            or not s["instruction_compliance"]):
        fails.append(f"denial mutations must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "1. TR-8842-QX", "1. TR-8842-QX and TR-0000-AA"))
    if s["exact_retrieval"] or not s["review_required"] or not s["decoy_resistance"]:
        fails.append(f"contradictory codes must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "4. 357", "4. 357 and 314"))
    if s["retrieval_95"] or not s["review_required"]:
        fails.append(f"contradictory counts must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "3. NOT STATED",
        "3. NOT STATED, the visitor center code is TR-0000-AA"))
    if s["absent_information"] or not s["review_required"]:
        fails.append(f"fabrication beside the marker must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "3. NOT STATED", "3. NOT STATED. The visitor center code is VC-1111-BB."))
    if s["absent_information"] or not s["review_required"]:
        fails.append(f"structured fabrication at item 3 must be review-required: {s}")
    s = score_family_a(numbered.replace(
        "1. TR-8842-QX", '1. the code is "TR-8842-QX" per the notes'))
    if s["exact_retrieval"] or not s["review_required"]:
        fails.append(f"quoted code inside prose must be review-required: {s}")
    s = score_family_a(numbered.replace("1. TR-8842-QX", '1. "TR-8842-QX"'))
    if not s["exact_retrieval"] or s["review_required"]:
        fails.append(f"bare quoted code must still pass: {s}")
    for old, replacement, gate in [
        ("2. 2027", "2. 2027 had more shipments than 2028. 2028 had more shipments than 2027.", "synthesis"),
        ("4. 357", "4. 357. The count is 314.", "retrieval_95"),
        ("3. NOT STATED", "3. NOT STATED. The visitor center code is 1234.", "absent_information"),
    ]:
        scored = score_family_a(numbered.replace(old, replacement))
        if scored[gate] or not scored["review_required"]:
            fails.append(f"conflicting structured answer must require review: {scored}")

    # --- welp-context-0.2.0-draft: campaign coverage/capability summary ------
    plan = {"required_rungs": [8192, 32768, 131072],
            "lanes": ["semantic", "operational"],
            "seeds": [42, 314159], "practical_rung": 32768}

    def crow(rung, lane, seed, disp, ev=True, evd="run.json#sha256"):
        return {"configured_context": rung, "lane": lane, "seed": seed,
                "disposition": disp, "execution_valid": ev, "evidence": evd}

    def matrix(disp):
        return [crow(r, l, sd, disp(r, l, sd) if callable(disp) else disp)
                for r in plan["required_rungs"] for l in plan["lanes"]
                for sd in plan["seeds"]]

    summ = context_summary(plan, matrix("VALIDATED"))
    if not (summ["coverage_complete"] and summ["capability"] == "VALIDATED"
            and summ["required_cells"] == 12 and summ["covered_cells"] == 12
            and summ["missing_cells"] == [] and summ["execution_valid"]
            and summ["useful_context_max"] == {"semantic": 131072,
                                               "operational": 131072}
            and summ["practical_rung_validated"]):
        fails.append(f"all-validated matrix must be complete/VALIDATED: {summ}")

    # Full negative: the valid matrix completes coverage while capability
    # stays FAILED — a negative result, never a silent positive.
    summ = context_summary(plan, matrix("FAILED"))
    if not (summ["coverage_complete"] and summ["capability"] == "FAILED"
            and not summ["practical_rung_validated"]):
        fails.append(f"full negative must complete coverage as FAILED: {summ}")

    summ = context_summary(plan, [])
    if (summ["required_cells"] != 12 or summ["covered_cells"] != 0
            or len(summ["missing_cells"]) != 12
            or "32768/semantic/42" not in summ["missing_cells"]
            or summ["capability"] != "NOT_CHARACTERIZED"
            or summ["useful_context_max"] != {"semantic": None,
                                              "operational": None}
            or summ["practical_rung_validated"]
            or not summ["execution_valid"]):
        fails.append(f"empty rows must summarize incomplete: {summ}")

    # Missing practical cell: PARTIAL with the exact missing cell listed.
    rows = matrix("VALIDATED")
    rows.remove(crow(32768, "semantic", 42, "VALIDATED"))
    summ = context_summary(plan, rows)
    if (summ["coverage_complete"] or summ["capability"] != "PARTIAL"
            or summ["missing_cells"] != ["32768/semantic/42"]
            or summ["covered_cells"] != 11):
        fails.append(f"missing practical cell must be PARTIAL: {summ}")

    # Budget-limited practical cell: never covers, capability PARTIAL.
    rows = matrix("VALIDATED")
    rows.remove(crow(32768, "operational", 314159, "VALIDATED"))
    rows.append(crow(32768, "operational", 314159, "BUDGET_LIMITED"))
    summ = context_summary(plan, rows)
    if (summ["coverage_complete"] or summ["capability"] != "PARTIAL"
            or summ["covered_cells"] != 11):
        fails.append(f"budget-limited cell must not cover: {summ}")

    # Trusted all-blocked practical rung: blocked capability, coverage kept.
    rows = [{**r, "disposition": "INTEGRATION_BLOCKED"}
            if r["configured_context"] == 32768 else r
            for r in matrix("VALIDATED")]
    summ = context_summary(plan, rows)
    if not (summ["coverage_complete"]
            and summ["capability"] == "INTEGRATION_BLOCKED"
            and not summ["practical_rung_validated"]):
        fails.append(f"all-blocked practical rung: {summ}")

    # Untrusted rows (invalid execution or empty evidence) never measure.
    rows = [{**r, "execution_valid": False, "evidence": ""}
            if (r["configured_context"], r["lane"], r["seed"])
            == (32768, "semantic", 42) else r
            for r in matrix("VALIDATED")]
    summ = context_summary(plan, rows)
    if (summ["execution_valid"] or summ["coverage_complete"]
            or summ["capability"] != "PARTIAL"):
        fails.append(f"untrusted row must not measure: {summ}")

    # useful_context_max is per lane: one failed cell demotes only its lane.
    rows = [{**r, "disposition": "FAILED"}
            if r["configured_context"] == 131072 and r["lane"] == "operational"
            else r for r in matrix("VALIDATED")]
    summ = context_summary(plan, rows)
    if (summ["useful_context_max"] != {"semantic": 131072,
                                       "operational": 32768}
            or summ["capability"] != "VALIDATED"):
        fails.append(f"per-lane useful_context_max: {summ}")

    def raises(fn):
        try:
            fn()
        except ValueError:
            return True
        return False

    dup = matrix("VALIDATED")
    dup.append(dup[0])
    if not raises(lambda: context_summary(plan, dup)):
        fails.append("duplicate planned cell must raise")
    if not raises(lambda: context_summary(
            plan, [crow(4096, "semantic", 42, "VALIDATED")])):
        fails.append("unplanned configured_context must raise")
    if not raises(lambda: context_summary(
            plan, [crow(8192, "semantic", 7, "VALIDATED")])):
        fails.append("unplanned seed must raise")
    if not raises(lambda: context_summary(
            plan, [crow(8192, "gpu", 42, "VALIDATED")])):
        fails.append("unplanned lane must raise")
    if not raises(lambda: context_summary(
            plan, [crow(8192, "semantic", 42, "AWESOME")])):
        fails.append("invalid disposition must raise")
    if not raises(lambda: context_summary(
            plan, [crow(8192, "semantic", 42, "VALIDATED", ev=1)])):
        fails.append("non-bool execution_valid must raise")
    if not raises(lambda: context_summary(
            {**plan, "practical_rung": 4096}, [])):
        fails.append("unplanned practical_rung must raise")
    if not raises(lambda: context_summary(
            {k: v for k, v in plan.items() if k != "seeds"}, [])):
        fails.append("missing plan key must raise")
    if not raises(lambda: context_summary({**plan, "required_rungs": []}, [])):
        fails.append("empty required_rungs must raise")

    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
