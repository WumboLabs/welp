"""Multi-Document controlled-context science — extracted and adapted (SPEC §8).

Deterministic construction and the strict JSON oracle for the frozen fixture
`fixtures/useful_context/multidocument.json` (welp-useful-context-family-
multidocument 0.1.0-draft).

Extraction provenance (recorded in provenance.json):
    source: welp/harness/capabilities.py (welp-harness-capabilities/1.1.0-draft)
    kept byte-identical in logic: strict duplicate-key-rejecting JSON parse,
    frozen filler templates and the forbidden-substring redraw guard, the
    separated occupancy/placement knob solver (_multidoc_placement,
    construct_multidocument including the infeasible-tail diagnostic) and
    score_multidocument (version precedence, exact integer typing, source
    alias resolution, absent fact null, lenient fenced probe as diagnostic
    only).
    adapted: fixture path now resolves inside the successor workspace; probe
    outcome/budget tables and unrelated legacy probes were not carried.
Stdlib only (json, re, random).
"""
import json
import random
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_MULTIDOCUMENT = PROJECT_ROOT / "fixtures/useful_context/multidocument.json"

_MULTIDOC_OCCUPANCY_PREFERRED_PCT = 99.0
_MULTIDOC_OCCUPANCY_HARD_PCT = 97.0
_MULTIDOC_PLACEMENT_PREFERRED_PP = 0.25
_MULTIDOC_PLACEMENT_HARD_PP = 0.50

# Frozen realistic filler: unrelated operational log lines. Integer ranges are
# bounded (1-2 digit counts and clock values, 3-digit series keys, 6-digit
# checkpoint ids) and every line is redrawn until it avoids the fixture's
# forbidden substrings, so filler can never carry question facts or decoys.
_MULTIDOC_FILLER_TEMPLATES = [
    "batch-sync worker {w} checkpoint {n} written ({s}.{t}s)",
    "metrics relay scraped {k} series segments in {s}.{t}ms",
    "objectstore lifecycle pass moved chunk {n} to cold tier",
    "auth service rotated token-signing key set {k} (no user impact)",
    "backup verify checked segment {n} (ok)",
]


def _load_fixture() -> dict:
    return json.loads(FIXTURE_MULTIDOCUMENT.read_text(encoding="utf-8"))


def _unique_pairs(pairs):
    """object_pairs_hook that rejects duplicate JSON keys (strict parsing)."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate JSON keys")
    return dict(pairs)


def lenient_json_probe(content, checker=None):
    """Diagnostic only: whether the underlying content parses and the content
    checks pass once a single surrounding code fence is tolerated. It never
    changes the strict semantic result, because a mandatory parser
    requirement is never silently overridden. `checker(value)` returns a list
    of content-failure strings exactly as the strict path would."""
    out = {"fenced_parse": None, "fenced_content_failures": None}
    if not isinstance(content, str):
        return out
    m = re.fullmatch(r"\s*```[a-zA-Z0-9_-]*\s*\n(.*)\n```\s*", content, re.DOTALL)
    if not m:
        return out
    try:
        value = json.loads(m.group(1), object_pairs_hook=_unique_pairs)
    except (TypeError, ValueError):
        out["fenced_parse"] = False
        return out
    out["fenced_parse"] = True
    if callable(checker):
        try:
            out["fenced_content_failures"] = checker(value)
        except Exception:
            out["fenced_content_failures"] = None
    return out


def resolve_source_alias(cited, known_ids):
    """Resolve one cited source reference to the unique frozen source it can
    only mean, or None.

    Source grounding requires the right evidence, not one exact registry
    string: an exact frozen id always resolves, and so does an unambiguous
    word-boundary extension or truncation of exactly one frozen id. A
    citation matching several frozen ids, a glued form with no word
    boundary, or nothing at all resolves to None and keeps failing
    mechanically — ambiguity is never guessed.
    """
    if not isinstance(cited, str) or not cited:
        return None
    known = [s for s in known_ids if isinstance(s, str) and s]
    if cited in known:
        return cited
    c = cited.lower()

    def boundary_prefix(inner, outer):
        return outer.startswith(inner) and len(outer) > len(inner) \
            and not outer[len(inner)].isalnum()

    matches = {s for s in known
               if s.lower() == c
               or boundary_prefix(s.lower(), c)
               or boundary_prefix(c, s.lower())}
    return matches.pop() if len(matches) == 1 else None


def _multidoc_placement(depths_pct: dict, targets_pct: dict) -> dict:
    """Absolute placement error of each document vs its frozen target depth."""
    errs = [abs(depths_pct[doc_id] - target_pct) for doc_id, target_pct in targets_pct.items()]
    max_err = max(errs)
    return {"pass": max_err <= _MULTIDOC_PLACEMENT_HARD_PP, "max_error_pp": round(max_err, 3),
            "preferred": max_err <= _MULTIDOC_PLACEMENT_PREFERRED_PP,
            "hard": max_err <= _MULTIDOC_PLACEMENT_HARD_PP}


def construct_multidocument(usable_tokens: int, measure, max_attempts: int = 30,
                            seed: int | None = None) -> dict:
    """Place whole realistic documents across the final rendered stream.

    Mirrors construct_family_a: positions are selected against the FINAL
    rendered/tokenized stream before any inference. measure(content) must
    return (final_token_count, {document_id: token_start_of_offset_marker})
    with the pinned chat template and identical special-token behavior to
    inference; the caller retains each attempt as preflight evidence. The
    seed argument is optional and defaults to the fixture's frozen seed, so
    construct_multidocument(usable_tokens, measure) is fully deterministic.
    Fails before inference if occupancy (97-100%, preferred >=99%) or
    per-document placement (hard 0.50pp) cannot be met within max_attempts.

    The solver keeps the two bounded knobs separate. The document multiset
    fixes the rendered token count for a given filler-line count n, so n is
    the occupancy knob and never disturbs existing placements (new filler
    slots only extend the tail); each document's slot follows a measured
    error step (error_tokens / mean_tokens_per_line). Slots stay strictly
    ordered because documents are whole entries.
    """
    if usable_tokens < 1024 or max_attempts < 1:
        raise ValueError("invalid usable context or preflight bound")
    fixture = _load_fixture()
    construction = fixture["construction"]
    doc_targets = construction["documents"]
    doc_text = {d["id"]: f"[document: {d['id']}]\n{d['text']}" for d in fixture["documents"]}
    markers = {d["id"]: d["offset_marker"] for d in doc_targets}
    targets_pct = {d["id"]: 100.0 * d["target_depth"] for d in doc_targets}
    forbidden = construction.get("filler_forbidden_substrings", [])
    seed = int(construction["seed"]) if seed is None else int(seed)
    if len(set(markers.values())) != len(markers) or len(set(markers)) != len(doc_targets):
        raise ValueError("fixture offset markers must be unique per document")
    order = [d["id"] for d in sorted(doc_targets, key=lambda d: d["target_depth"])]

    def make_filler(rng, count):
        lines = []
        for i in range(count):
            template = _MULTIDOC_FILLER_TEMPLATES[i % len(_MULTIDOC_FILLER_TEMPLATES)]
            for _try in range(100):
                line = template.format(w=rng.randint(1, 16), n=rng.randint(100000, 999999),
                                       s=rng.randint(0, 9), t=rng.randint(0, 9),
                                       k=rng.randint(100, 999))
                if not any(bad in line for bad in forbidden):
                    break
            else:
                raise ValueError("filler generation could not avoid forbidden substrings")
            lines.append(line)
        return lines

    def project(want, ceiling):
        """Strictly increasing integer slots, top-clamped to the ceiling."""
        out = [min(int(round(want[did])), ceiling) for did in order]
        for i in range(1, len(out)):
            out[i] = max(out[i], out[i - 1] + 1)
        for i in range(len(out)):
            out[i] = min(out[i], ceiling - (len(out) - 1 - i))
        for i in range(1, len(out)):
            out[i] = max(out[i], out[i - 1] + 1)
        return {did: out[i] for i, did in enumerate(order)}

    n = max(len(order) + 1, usable_tokens // 6)
    positions = {did: max(0, min(n - 1, int(targets_pct[did] / 100 * n))) for did in order}
    attempts = []
    for _ in range(max_attempts):
        rng = random.Random(seed)
        filler = make_filler(rng, n)
        doc_at = {positions[did]: did for did in order}
        fill = iter(filler)
        lines = []
        for i in range(n):
            if i in doc_at:
                lines.extend(doc_text[doc_at[i]].split("\n"))
            else:
                lines.append(next(fill))
        content = "\n".join(lines) + "\n" + construction["question_block"]
        total, offsets = measure(content)
        if (not isinstance(total, int) or total <= 0 or
                set(offsets) != set(markers) or
                any(not isinstance(x, int) or x < 0 or x >= total for x in offsets.values())):
            raise ValueError("invalid final-rendered token measurement")
        if any(bad in "\n".join(filler) for bad in forbidden):
            raise ValueError("filler leaked a forbidden substring")
        depths = {did: 100.0 * offsets[did] / total for did in markers}
        placement = _multidoc_placement(depths, targets_pct)
        occupancy = 100.0 * total / usable_tokens
        attempts.append({"rendered_tokens": total, "occupancy_pct": occupancy,
                         "depths_pct": depths, "placement": placement})
        if _MULTIDOC_OCCUPANCY_HARD_PCT <= occupancy <= 100.0 and placement["pass"]:
            # slots/token_offsets recorded (extraction adaptation) so the
            # successor evidence retains the exact offline-reconstructible
            # filler geometry and measured stream positions.
            return {"content": content, "rendered_tokens": total,
                    "documents": [{"id": did, "start": offsets[did], "depth_pct": depths[did]}
                                  for did in markers],
                    "slots": dict(positions), "token_offsets": dict(offsets),
                    "occupancy_pct": occupancy, "filler_lines": n, "seed": seed,
                    "attempts": attempts}
        # --- bounded placement/occupancy update (separated knobs) ---
        c = total / n  # mean rendered tokens per filler-line slot
        next_n = max(len(order) + 1, round(
            n * (_MULTIDOC_OCCUPANCY_PREFERRED_PCT / 100.0 * usable_tokens) / total))
        headroom = max(0, int((usable_tokens - total) / c) - 1)
        tail_id = order[-1]
        # bulk rescale to the next slot geometry plus a measured error step
        want = {did: positions[did] * next_n / n
                + (targets_pct[did] - depths[did]) * next_n / 100.0
                for did in order}
        next_positions = project(want, next_n - 1)
        tail_want = int(round(want[tail_id]))
        if tail_want > next_n - 1 and headroom:
            grow = min(tail_want - (next_n - 1), headroom)
            next_n += grow
            headroom -= grow
            next_positions = project(want, next_n - 1)
        if (next_positions[tail_id] == next_n - 1 and tail_want > next_n - 1
                and headroom <= 0 and positions[tail_id] == n - 1
                and depths[tail_id] < targets_pct[tail_id]):
            fixed_tail_tokens = total - offsets[tail_id]
            min_usable = int(-(-fixed_tail_tokens
                               // (1.0 - targets_pct[tail_id] / 100.0))) + 1
            raise ValueError(
                "multidocument placement infeasible at usable_tokens="
                f"{usable_tokens}: tail document {tail_id!r} pinned at the final slot "
                f"reaches {depths[tail_id]:.2f}% vs target {targets_pct[tail_id]:.1f}%; "
                f"its trailing mass (~{fixed_tail_tokens:.0f} tokens: body after the "
                f"marker plus question block) needs usable_tokens >= {min_usable}")
        positions, n = next_positions, next_n
    raise ValueError(f"multidocument placement/occupancy failed after {max_attempts} attempts")


def score_multidocument(content: str) -> dict:
    """Score the multidocument family answer.

    One strict JSON object (no Markdown, duplicate keys rejected) with the
    exact key set; current values must come from the authoritative
    configuration revision (version precedence, not newest-date), the
    superseded value must be the older one, the conflicting replica claim
    must cite its actual source document, the log timestamp must be exact,
    and the absent health-probe fact must be null. Any JSON key order and
    whitespace is valid; integer fields reject string encodings.
    """
    fixture = _load_fixture()
    oracle = fixture["oracle"]

    def content_failures(value):
        failures = []
        if not isinstance(value, dict) or set(value) != set(oracle["exact_keys"]):
            failures.append("exact object keys")
            return failures
        integer_keys = set(oracle.get("integer_keys_exact", []))
        doc_ids = [d["id"] for d in fixture.get("documents", [])
                   if isinstance(d, dict) and isinstance(d.get("id"), str)]
        for key, expected in oracle["expected_values"].items():
            got = value[key]
            if expected is None:
                if got is not None:
                    failures.append(f"{key}: absent fact must be null")
            elif key in integer_keys:
                if type(got) is not int or got != expected:
                    failures.append(f"{key}: wrong value or type")
            elif isinstance(expected, str) and expected in doc_ids:
                if resolve_source_alias(got if isinstance(got, str) else "",
                                        doc_ids) != expected:
                    failures.append(f"{key}: wrong value")
            elif got != expected:
                failures.append(f"{key}: wrong value")
        return failures

    failures = []
    try:
        value = json.loads(content, object_pairs_hook=_unique_pairs)
    except (TypeError, ValueError):
        value = None
        failures.append("strict JSON")
    failures.extend(content_failures(value))
    out = {"semantic": "PASS" if not failures else "FAIL", "failures": failures}
    if value is None:
        # Format failed: separately expose whether the underlying content was
        # correct (diagnostic only; the strict failure stands).
        probe = lenient_json_probe(content, content_failures)
        out["content_probe"] = {k: v for k, v in probe.items()
                                if k != "fenced_content_failures" or v is not None}
    return out
