"""Controlled Context Family A science — extracted and adapted (SPEC §8 REUSE).

Deterministic construction and the canonical ambiguity-safe answer oracle for
the frozen fixture `fixtures/useful_context/family-a.json`
(welp-useful-context-family-a 1.3.0-draft, contract welp-context-0.2.0-draft).

Extraction provenance (recorded in provenance.json):
    source: welp/harness/context.py (welp-harness-context/1.2.0-draft)
    kept byte-identical in logic: depth/occupancy gate constants, fact and
    oracle constants, the full regex guard set, placement_errors /
    placement_preflight / construct_family_a, the prompt-echo and segment
    helpers, _synthesis_gate and score_family_a.
    adapted: fixture path now resolves inside the successor workspace; legacy
    campaign machinery (welp_outcomes completion/budget derivation,
    rung_outcome lane/reserve assembly, context_summary, provider execution
    boundaries, selftest) was not carried — the successor derives outcomes
    once in welp_next.policy from the four facets; the oracle here provides
    the six gates plus review_required/review_reasons exactly as before.
Stdlib only (json, re, random).
"""
import json
import random
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FAMILY_A = PROJECT_ROOT / "fixtures/useful_context/family-a.json"

REQUIRED_DEPTHS_PCT = [2.0, 25.0, 50.0, 75.0, 95.0]
PLACEMENT_PREFERRED_PP = 0.25
PLACEMENT_HARD_PP = 0.50
OCCUPANCY_PREFERRED_PCT = 99.0
OCCUPANCY_HARD_PCT = 97.0

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
MORE_COUNT = 412
LESS_COUNT = 388
_NUMERIC_COMPARISON_RE = re.compile(
    r"^(20\d{2})\s*\(\s*(\d+)\s*(?:containers?)?\s+vs\.?\s*"
    r"(\d+)\s*(?:containers?)?\s+in\s+(20\d{2})\s*\)$", re.I)

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


def _load_fixture() -> dict:
    return json.loads(FIXTURE_FAMILY_A.read_text(encoding="utf-8"))


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
    if usable_tokens < 1024 or max_attempts < 1:
        raise ValueError("invalid usable context or preflight bound")
    construction = _load_fixture()["construction"]
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
            # attempts/token_offsets recorded (extraction adaptation) so the
            # successor evidence retains the exact measured stream positions.
            # Successor convention: the attempt ledger key is "attempts"
            # (same ledger the multidocument family returns and the
            # evidence builder consumes); legacy called it "preflight".
            return {"content": content, "filler_words": n, "positions": positions,
                    "token_offsets": dict(offsets), "rendered_tokens": total,
                    "attempts": attempts}
        next_n = max(len(facts) + 1, round(n * (0.992 * usable_tokens) / total))
        positions = [max(0, min(next_n - 1, round(
            pos * next_n / n + (f["depth"] * total - offsets[f["target"]])
            * next_n / total)))
            for pos, f in zip(positions, facts)]
        n = next_n
    raise ValueError(f"Controlled Context (Family A) placement/occupancy failed "
                     f"after {max_attempts} attempts")


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
    # A fully anchored numeric comparison has an unambiguous claimed answer:
    # the initial year. Never accept a bare pair of years/counts or prose
    # containing additional claims; those still require blinded review.
    numeric = _NUMERIC_COMPARISON_RE.fullmatch(t)
    if numeric:
        first_year, first_count, second_count, second_year = numeric.groups()
        if {first_year, second_year} != {MORE_YEAR, LESS_YEAR}:
            return False, False
        facts = {MORE_YEAR: MORE_COUNT, LESS_YEAR: LESS_COUNT}
        if (int(first_count), int(second_count)) != (
                facts[first_year], facts[second_year]):
            return False, False
        return first_year == MORE_YEAR and int(first_count) > int(second_count), False
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
