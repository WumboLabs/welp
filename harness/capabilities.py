#!/usr/bin/env python3
"""capabilities.py — canonical capability-probe module (welp-phase-harness/1).

Declares the frozen budget/lanes for the Phase-5 capability probes and maps
probe outcomes onto CP-1 semantics. Probes are executed by campaigns against
the pinned runtime; scoring and budget semantics live here so probes stop
being per-campaign script copies.

Real-work and context oracles (welp-real-work 0.2.0-draft):
  execute_tool + score_tool_recovery — frozen read-only tool simulator;
    every tool event's recorded result is validated by replaying the actual
    executor (fixtures/real_work/tool-recovery.json 0.2), and the final
    answer must be one exact structured JSON object.
  score_linux_diagnosis — two evidence-grounded diagnosis cases committed as
    structured claims and checked against a frozen evidence registry
    (fixtures/real_work/linux-diagnosis.json); contradictions fail, prose
    detail is left to blinded independent review.
  construct_multidocument + score_multidocument — the complementary
    realistic multi-document context family
    (fixtures/useful_context/multidocument.json), constructed against the
    final rendered token stream like Family A but with real memo/config/log
    documents.
  score_multi_turn_final — multi-turn correction fixture (unchanged).

Subprocess selftest oracles resolve a real interpreter via
resolve_selftest_interpreter (WELP_SELFTEST_PYTHON override, sys.executable,
PATH python3/python) so agent/AppImage wrapper environments never produce
phantom fixture failures (Granite finding M-2).

Frozen probe budgets (welp-generation-budget 0.1.0-draft):
  reasoning  frozen lane 1500 total (comparability) + operational lane 4096
             (non-binding ceiling; Qwen3.6 case: frozen FAIL_LENGTH / 4096 PASS)
  coding     frozen lane 400 (thinking-off profile) + diagnostic lane 1500
             (Bonsai case: capability present, budget-bound at 400 thinking-on)
  tools      200 total (adequate for a single structured call)

Selftest: python3 harness/capabilities.py selftest
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from welp_outcomes import derive_completion, derive_budget  # noqa: E402

MODULE_ID = "welp-harness-capabilities/1.1.0-draft"

FIXTURE_TOOL_RECOVERY = HERE.parent / "fixtures/real_work/tool-recovery.json"
FIXTURE_LINUX_DIAGNOSIS = HERE.parent / "fixtures/real_work/linux-diagnosis.json"
FIXTURE_MULTIDOCUMENT = HERE.parent / "fixtures/useful_context/multidocument.json"

PROBE_BUDGETS = {
    "reasoning": {
        "frozen_lane_generation_ceiling": 1500,
        "operational_lane_generation_ceiling": 4096,
        "rationale": "Frozen 1500 preserves cross-campaign comparability; 4096 is the declared non-starving operational ceiling selected from retained evidence (a reasoning model producing a coherent trace with no final answer at 1500 and PASS at 4096). No single reasoning score is reported: frozen-lane and operational-lane results are separate records.",
    },
    "coding": {
        "frozen_lane_generation_ceiling": 400,
        "diagnostic_lane_generation_ceiling": 1500,
        "rationale": "400 with the declared reasoning control (thinking-off) is canonical; the 1500 diagnostic lane separates budget-bound failures from capability absence (retained evidence: FAIL at 400 thinking-on, PASS at 400 thinking-off AND at 1500 thinking-on).",
    },
    "tools": {
        "frozen_lane_generation_ceiling": 200,
        "rationale": "One structured call plus a short grounded continuation; measured calls complete far below 200.",
    },
    "structured_interfaces": {
        "frozen_lane_generation_ceiling": 300,
        "rationale": "Small strict-JSON outputs; formatting margin around a <100-token reference.",
    },
}

REPORTED_FIELDS = ["semantic", "completion", "budget", "finish_reason",
                   "reasoning_tokens", "answer_tokens",
                   "time_to_first_reasoning_token", "time_to_final_answer"]


def probe_outcome(probe: str, check_pass, row: dict, lane: str = "frozen",
                  ceiling: int | None = None) -> dict:
    budgets = PROBE_BUDGETS[probe]
    cap = ceiling if ceiling is not None else (budgets.get(f"{lane}_lane_generation_ceiling")
                                                or budgets.get("frozen_lane_generation_ceiling"))
    completion = derive_completion(row.get("finish"), row.get("output") or "",
                                   row.get("usage") or {}, cap)
    budget = derive_budget(row.get("finish"), completion, row.get("output") or "",
                           bool((row.get("usage") or {}).get("reasoning_tokens")))
    semantic = "NOT_EVALUABLE"
    if completion == "COMPLETE":
        semantic = "PASS" if check_pass else "FAIL"
    return {"probe": probe, "lane": lane, "ceiling": cap, "semantic": semantic,
            "completion": completion, "budget": budget,
            "finish_reason": row.get("finish")}


def _unique_pairs(pairs):
    """object_pairs_hook that rejects duplicate JSON keys (strict parsing)."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate JSON keys")
    return dict(pairs)


def execute_tool(action: dict, state: dict | None = None) -> tuple[dict, dict]:
    """Advance the frozen read-only tool-recovery simulator by exactly one call.

    Pure and deterministic: no host, network, filesystem or service access;
    the input state is never mutated. Arguments are validated against the
    fixture's declared tool schemas exactly (all declared keys, no extras,
    string values), so a malformed argument payload returns an executor
    error instead of silently ignoring extras. Returns (result, new_state).
    The fixture's executor block is the single source of truth for every
    transition; campaign code must call this to produce each tool event's
    recorded result, never author observations itself.
    """
    fixture = json.loads(FIXTURE_TOOL_RECOVERY.read_text())
    executor = fixture["executor"]
    new_state = dict(executor["initial_state"] if state is None else state)
    new_state["calls"] = int(new_state.get("calls", 0)) + 1
    if new_state["calls"] > int(executor["max_calls"]):
        return {"error": executor["exhausted_error"]}, new_state
    if not isinstance(action, dict):
        return {"error": "malformed action"}, new_state
    tool = action.get("tool")
    arguments = action.get("arguments")
    if not isinstance(tool, str):
        return {"error": "tool name must be a string"}, new_state
    schema = fixture.get("tools", {}).get(tool, {}).get("schema")
    if isinstance(schema, dict) and (
            not isinstance(arguments, dict)
            or set(arguments) != set(schema)
            or not all(isinstance(arguments[key], str) for key in schema)):
        return {"error": f"malformed arguments for {tool}"}, new_state
    if tool == "read_config":
        path = arguments["path"]
        entry = executor["known_paths"].get(path)
        if entry is None:
            return {"error": f"path not readable: {path}"}, new_state
        new_state["config_read"] = True
        return {"port": entry["port"], "service": entry["service"]}, new_state
    if tool == "check_service":
        name = arguments["name"]
        entry = executor["services"].get(name)
        if entry is None:
            return {"error": f"unknown service: {name}"}, new_state
        if not new_state.get("transient_seen"):
            new_state["transient_seen"] = True
            return {"error": executor["transient_error"]}, new_state
        return {"name": name, "active": entry["active"],
                "observed_at": entry["observed_at"]}, new_state
    return {"error": f"unknown tool: {tool}"}, new_state


def score_tool_recovery(actions: list) -> dict:
    """Replay a frozen simulated tool transcript against the actual executor.

    Every tool event must record exactly tool, arguments and the result the
    model was actually shown; each recorded result is validated by
    re-executing execute_tool, and every arguments payload must match the
    fixture's declared tool schema exactly. The transcript must follow the
    frozen required order (including the recoverable transient error and its
    retry), stay within max_calls, and end in exactly one structured JSON
    object string grounded in the executor results. All failure reasons are
    collected (no early return may hide evidence) and no result is ever
    synthesized on the transcript's behalf.
    """
    fixture = json.loads(FIXTURE_TOOL_RECOVERY.read_text())
    oracle = fixture["oracle"]
    order = oracle["required_order"]
    failures = []
    replay = []
    final_parsed = None
    if not isinstance(actions, list):
        failures.append("transcript must be a list of events")
        actions = []
    if not actions:
        failures.append("empty transcript")
    tool_events, final_events = [], []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            failures.append(f"event shape {i}")
            continue
        if "final" in action:
            if set(action) != {"final"}:
                failures.append(f"event shape {i}")
            final_events.append(action)
            if i != len(actions) - 1:
                failures.append(f"final answer is not the last event ({i})")
        elif set(action) == {"tool", "arguments", "result"}:
            tool_events.append(action)
        else:
            failures.append(f"tool event must record exactly tool, arguments and result ({i})")
    if len(final_events) != 1:
        failures.append("exactly one final answer event is required")
    if len(tool_events) != len(order):
        failures.append(f"tool call count {len(tool_events)} does not match required sequence "
                        f"length {len(order)}")
    if len(tool_events) > int(oracle["max_calls"]):
        failures.append("max_calls exceeded")

    state = None
    status_success = False
    observed_config = None
    schemas = fixture.get("tools", {})
    for i, event in enumerate(tool_events):
        schema = schemas.get(event["tool"], {}).get("schema") if isinstance(event["tool"], str) else None
        if isinstance(schema, dict) and (
                not isinstance(event["arguments"], dict)
                or set(event["arguments"]) != set(schema)
                or not all(isinstance(event["arguments"][key], str) for key in schema)):
            failures.append(f"arguments violate the declared schema at call {i}")
        result, state = execute_tool({"tool": event["tool"], "arguments": event["arguments"]},
                                     state)
        recorded = event["result"]
        matches = (isinstance(recorded, dict) and recorded.keys() == result.keys()
                   and all(type(recorded[key]) is type(value) and recorded[key] == value
                           for key, value in result.items()))
        if event["tool"] == "read_config" and isinstance(result, dict) and "error" not in result:
            observed_config = result
        if event["tool"] == "check_service" and (
                observed_config is None or not isinstance(event["arguments"], dict)
                or event["arguments"].get("name") != observed_config["service"]):
            failures.append("service check must use a successfully observed configuration")
        if (event["tool"] == "check_service" and isinstance(result, dict)
                and "error" not in result):
            status_success = True
        replay.append({"index": i, "tool": event["tool"], "arguments": event["arguments"],
                       "recorded_result": recorded, "executor_result": result,
                       "matches_executor": matches})
        if not matches:
            failures.append(f"recorded result does not match executor at call {i}")
        if i < len(order) and event["tool"] != order[i]:
            failures.append(f"tool choice/order at call {i}")
    if observed_config is None:
        failures.append("successful configuration observation required")

    if final_events:
        text = final_events[0].get("final")
        if not isinstance(text, str):
            failures.append("final answer must be a JSON object string")
        else:
            try:
                final_parsed = json.loads(text, object_pairs_hook=_unique_pairs)
            except (TypeError, ValueError):
                final_parsed = None
                failures.append("final answer strict JSON")
            if isinstance(final_parsed, dict):
                if set(final_parsed) != set(oracle["final_keys_exact"]):
                    failures.append("final answer exact keys")
                else:
                    if (final_parsed["service"] != oracle["expected_service"]
                            or type(final_parsed["port"]) is not int
                            or final_parsed["port"] != oracle["expected_port"]):
                        failures.append("final answer service/port")
                    if (final_parsed["health"] != oracle["expected_health"]
                            or final_parsed["observed_at"] != oracle["expected_observed_at"]):
                        failures.append("final answer health/observed_at")
                    if observed_config is None or any(
                            final_parsed[key] != observed_config[key] for key in ("service", "port")):
                        failures.append("final service/port must be grounded in observed configuration")
            else:
                failures.append("final answer must be a JSON object")
    if (isinstance(final_parsed, dict) and final_parsed.get("health") is not None
            and not status_success):
        failures.append("health claimed without a successful executor status result")
    return {"semantic": "FAIL" if failures else "PASS", "failures": failures,
            "tool_calls": len(tool_events), "replay": replay, "final": final_parsed}


def _multi_turn_content_failures(value):
    """Content-level failure list for the multi-turn oracle (used by both the
    strict path and the supplementary lenient content probe)."""
    fixture = json.loads((HERE.parent / "fixtures/real_work/multi-turn-correction.json").read_text())
    oracle = fixture["oracle"]
    failures = []
    if not isinstance(value, dict) or set(value) != set(oracle["exact_keys"]):
        failures.append("exact object keys")
        return failures
    if value["service"] != oracle["service"]:
        failures.append("service retention")
    if type(value["port"]) is not int or value["port"] != oracle["port"]:
        failures.append("correction not incorporated")
    if value["health"] is not None:
        failures.append("absent health evidence fabricated")
    return failures


def score_multi_turn_final(content: str) -> dict:
    """Evaluate corrected facts, absent evidence and strict JSON on final turn."""
    failures = []
    try:
        value = json.loads(content, object_pairs_hook=_unique_pairs)
    except (TypeError, ValueError):
        value = None
        failures.append("strict JSON")
    failures.extend(_multi_turn_content_failures(value))
    out = {"semantic": "PASS" if not failures else "FAIL", "failures": failures}
    if value is None:
        # Format failed: separately expose whether the underlying content was
        # correct (diagnostic only; the strict failure stands).
        probe = lenient_json_probe(content, _multi_turn_content_failures)
        out["content_probe"] = {k: v for k, v in probe.items()
                                if k != "fenced_content_failures" or v is not None}
    return out


def lenient_json_probe(content, checker=None):
    """Area-B diagnostic (model-agentic revision): whether the underlying
    content parses and the content checks pass once a single surrounding code
    fence is tolerated. SUPPLEMENTARY ONLY: it never changes the strict
    semantic result, because a mandatory parser requirement is never silently
    overridden (welp protocol hardening II). `checker(value)` returns a list
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
    word-boundary extension or truncation of exactly one frozen id (the
    lfm2.5 hardening-validation campaign's "journal_excerpt" for
    "journal"). A citation matching several frozen ids, a glued form with no
    word boundary, or nothing at all resolves to None and keeps failing
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


def score_linux_diagnosis(case_id: str, content: str) -> dict:
    """Score one linux-diagnosis case against its frozen evidence registry.

    The answer is one strict JSON object committing to structured claims:
    root_cause (kind + supporting source ids + detail), proposed_repair
    (action_class + detail + destructive flag), present_health and executed.
    The mechanical layer fails contradictions — unsupported or contradicted
    cause kinds, citations outside the supporting sources, missing required
    evidence, non-safe repairs, asserted present health, any claimed
    execution — not keyword bags. The free-text detail fields are
    necessary-but-not-sufficient and belong to blinded independent review.
    """
    fixture = json.loads(FIXTURE_LINUX_DIAGNOSIS.read_text())
    case = next((c for c in fixture["cases"] if c["case_id"] == case_id), None)
    if case is None:
        return {"semantic": "FAIL", "failures": [f"unknown case: {case_id}"]}
    oracle = case["oracle"]
    failures = []
    try:
        value = json.loads(content, object_pairs_hook=_unique_pairs)
    except (TypeError, ValueError):
        value = None
        failures.append("strict JSON")
    if not isinstance(value, dict) or set(value) != set(oracle["answer_keys_exact"]):
        failures.append("exact answer keys")
        value = value if isinstance(value, dict) else {}
    if value.get("case_id") != case_id:
        failures.append("case_id mismatch")
    supported = oracle["supported_causes"]
    cause = value.get("root_cause")
    if not isinstance(cause, dict) or set(cause) != {"kind", "source_ids", "detail"}:
        failures.append("root_cause shape")
    else:
        kind = cause["kind"]
        if not isinstance(kind, str) or kind not in supported:
            failures.append(f"unsupported or contradicted cause: {kind!r}")
        else:
            sources = supported[kind]["sources"]
            required = supported[kind].get("required_sources", sources)
            ids = cause["source_ids"]
            if not isinstance(ids, list) or not all(isinstance(s, str) for s in ids):
                failures.append("root_cause source_ids shape")
            else:
                frozen_sources = list(oracle["source_ids"])
                resolved = []
                unresolved = []
                for s in ids:
                    target = resolve_source_alias(s, frozen_sources)
                    if target is None:
                        unresolved.append(s)
                    else:
                        resolved.append(target)
                if unresolved:
                    failures.append(f"unknown source ids: {sorted(set(unresolved))}")
                if not set(resolved).issubset(sources):
                    failures.append(f"cited sources do not support {kind}")
                missing = [s for s in required
                           if s not in resolved and
                           resolve_source_alias(s, ids) is None]
                if missing:
                    failures.append(f"missing required evidence citations: {missing}")
        if not isinstance(cause.get("detail"), str) or not cause["detail"].strip():
            failures.append("root_cause detail must be non-empty prose")
    repair = value.get("proposed_repair")
    if not isinstance(repair, dict) or set(repair) != {"action_class", "detail", "destructive"}:
        failures.append("proposed_repair shape")
    else:
        action_class = repair.get("action_class")
        rating = oracle["repair_classes"].get(action_class) if isinstance(action_class, str) else None
        if rating != "safe":
            failures.append(f"proposed repair is not safe: {repair.get('action_class')!r} "
                            f"({rating or 'unknown class'})")
        if repair.get("destructive") is not False:
            failures.append("destructive flag must be false for a safe diagnosis repair")
        if not isinstance(repair.get("detail"), str) or not repair["detail"].strip():
            failures.append("proposed_repair detail must be non-empty prose")
    if value.get("present_health") != oracle["present_health_expected"]:
        failures.append(f"present_health must be {oracle['present_health_expected']!r}: "
                        "no current-health evidence is provided")
    if value.get("executed") != []:
        failures.append("executed must be empty: this is a diagnosis task, nothing may be executed")
    return {"semantic": "PASS" if not failures else "FAIL", "failures": failures}


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
    ordered because documents are whole entries. When the tail document
    needs slots beyond the occupancy-preferred count, n grows toward the
    100% ceiling; a tail target still short when pinned at the final slot
    with no occupancy headroom left is structurally infeasible at this
    context — its fixed trailing mass (own body after the marker plus the
    question block) exceeds the budget — and is reported with the measured
    minimum usable_tokens instead of silently exhausting attempts.
    """
    import random

    if usable_tokens < 1024 or max_attempts < 1:
        raise ValueError("invalid usable context or preflight bound")
    fixture = json.loads(FIXTURE_MULTIDOCUMENT.read_text())
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
            return {"content": content, "rendered_tokens": total,
                    "documents": [{"id": did, "start": offsets[did], "depth_pct": depths[did]}
                                  for did in markers],
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
    fixture = json.loads(FIXTURE_MULTIDOCUMENT.read_text())
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


def resolve_selftest_interpreter(executable=None, override=None,
                                 search_path=True):
    """Resolve a real Python interpreter for subprocess selftest oracles.

    sys.executable can name an agent/AppImage wrapper binary rather than a
    Python interpreter, which breaks `python -m unittest` subprocess oracles
    with fixture failures that do not exist (Granite finding M-2). Resolution
    order: explicit override (WELP_SELFTEST_PYTHON at call sites), the
    running interpreter's executable, then PATH python3/python. Every
    candidate must actually execute a trivial isolated CPython 3 program;
    the first candidate that qualifies wins. Raises RuntimeError when none
    qualifies — the selftest fails clearly instead of reporting phantom
    fixture failures. Never hardcodes a user-specific path and never falls
    back to a shell.
    """
    import os
    import shutil
    import subprocess

    candidates = [override, executable if executable is not None else sys.executable]
    if search_path:
        for name in ("python3", "python"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            probe = subprocess.run(
                [candidate, "-I", "-c", "import sys; print(sys.version_info[0])"],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.strip().startswith("3"):
            return candidate
    raise RuntimeError(
        "no working Python interpreter available for selftest subprocess "
        "oracles (checked sys.executable and PATH python3/python); set "
        "WELP_SELFTEST_PYTHON to a real interpreter")


def selftest_repository_fixture() -> list[str]:
    """Exercise only the trusted frozen baseline/reference, never model code."""
    import subprocess
    import tempfile

    fixture = json.loads((HERE.parent / "fixtures/real_work/repository-timeout.json").read_text())
    failures = []
    python = resolve_selftest_interpreter(
        override=os.environ.get("WELP_SELFTEST_PYTHON"))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, source in fixture["repository"].items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        command = [python, "-m", "unittest", "discover", "-s", "tests"]
        baseline = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
        if baseline.returncode == 0 or "test_zero_is_explicit" not in baseline.stderr:
            failures.append("repository fixture baseline must fail at explicit zero")
        source = (root / "app/config.py").read_text()
        if source.count("return timeout or DEFAULT_TIMEOUT") != 1:
            failures.append("repository fixture baseline source changed")
        else:
            (root / "app/config.py").write_text(
                source.replace("return timeout or DEFAULT_TIMEOUT",
                               "return DEFAULT_TIMEOUT if timeout is None else timeout"))
            reference = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=10)
            if reference.returncode != 0 or "Ran 4 tests" not in reference.stderr:
                failures.append("repository fixture reference does not pass all tests")
        if (root / "tests/test_config.py").read_text() != fixture["repository"]["tests/test_config.py"]:
            failures.append("repository fixture tests changed")
    return failures


def selftest() -> int:
    fails = []
    r = probe_outcome("reasoning", True, {"output": "...final answer...", "finish": "stop"})
    if r["ceiling"] != 1500 or r["semantic"] != "PASS":
        fails.append(f"frozen reasoning lane: {r}")
    r = probe_outcome("reasoning", True, {"output": "...final answer...", "finish": "stop"}, lane="operational")
    if r["ceiling"] != 4096:
        fails.append("operational reasoning lane must be 4096")
    # Answerless reasoning at the frozen cap is not a semantic failure.
    r = probe_outcome("reasoning", None, {"output": "", "finish": "length",
                                          "usage": {"completion_tokens": 1500, "reasoning_tokens": 1500}})
    if r["semantic"] != "NOT_EVALUABLE" or r["budget"] != "EXHAUSTED_IN_REASONING":
        fails.append(f"reasoning frozen starvation: {r}")
    # Bonsai coding case: 400 thinking-on truncated, 400 thinking-off complete pass
    r = probe_outcome("coding", None, {"output": "", "finish": "length",
                                       "usage": {"completion_tokens": 400, "reasoning_tokens": 400}})
    if r["semantic"] != "NOT_EVALUABLE":
        fails.append("coding truncation must be NOT_EVALUABLE (budget artifact)")
    r = probe_outcome("coding", True, {"output": "def moving_sum...", "finish": "stop"})
    if r["ceiling"] != 400 or r["semantic"] != "PASS":
        fails.append(f"coding frozen lane: {r}")
    r = probe_outcome("tools", True, {"output": "calling get_temperature", "finish": "tool_calls"})
    if r["completion"] != "COMPLETE" or r["budget"] != "WITHIN":
        fails.append(f"tools tool_calls completion: {r}")
    for probe, b in PROBE_BUDGETS.items():
        if not b.get("rationale"):
            fails.append(f"{probe} missing budget rationale")
    # --- tool recovery: trusted references drive the ACTUAL simulator ---
    def tool_reference_transcript(final_text=None):
        state, events, learned = None, [], {}
        for i, tool in enumerate(json.loads(
                FIXTURE_TOOL_RECOVERY.read_text())["oracle"]["required_order"]):
            if tool == "read_config":
                arguments = {"path": next(iter(json.loads(
                    FIXTURE_TOOL_RECOVERY.read_text())["executor"]["known_paths"]))}
            else:
                arguments = {"name": learned.get("service")}
            result, state = execute_tool({"tool": tool, "arguments": arguments}, state)
            if isinstance(result, dict) and "error" not in result:
                learned.update(result)
            events.append({"tool": tool, "arguments": arguments, "result": result})
        grounded = {"service": learned["service"], "port": learned["port"],
                    "health": "active" if learned["active"] else "inactive",
                    "observed_at": learned["observed_at"]}
        events.append({"final": json.dumps(grounded) if final_text is None else final_text})
        return events

    if score_tool_recovery(tool_reference_transcript())["semantic"] != "PASS":
        fails.append("tool recovery: executor-driven reference must pass")
    reversed_order_final = json.dumps({
        "observed_at": "2026-09-23T00:00:00Z", "health": "active",
        "port": 8452, "service": "example.service"}, indent=2)
    if score_tool_recovery(tool_reference_transcript(reversed_order_final))["semantic"] != "PASS":
        fails.append("tool recovery: alternate JSON order/whitespace must pass")
    ref = tool_reference_transcript()
    if score_tool_recovery([])["semantic"] != "FAIL":
        fails.append("tool recovery: empty transcript must fail")
    if score_tool_recovery(ref[:2] + [ref[-1]])["semantic"] != "FAIL":
        fails.append("tool recovery: skipping the transient retry must fail")
    fabricated = json.loads(json.dumps(ref))
    fabricated[1]["result"] = {"name": "example.service", "active": True,
                               "observed_at": "2026-09-23T00:00:00Z"}
    if score_tool_recovery(fabricated)["semantic"] != "FAIL":
        fails.append("tool recovery: fabricated success result must fail")
    wrong_args = json.loads(json.dumps(ref))
    wrong_args[2]["arguments"] = {"name": "other"}
    if score_tool_recovery(wrong_args)["semantic"] != "FAIL":
        fails.append("tool recovery: wrong service argument must fail")
    extra_arg = json.loads(json.dumps(ref))
    extra_arg[0]["arguments"] = {"path": "/etc/example/app.conf", "mode": "raw"}
    if score_tool_recovery(extra_arg)["semantic"] != "FAIL":
        fails.append("tool recovery: undeclared argument key must fail")
    malformed_tool = tool_reference_transcript()
    malformed_tool[0]["tool"] = []
    malformed_tool[0]["result"] = {"error": "tool name must be a string"}
    if score_tool_recovery(malformed_tool)["semantic"] != "FAIL":
        fails.append("tool recovery: non-string tool name must fail without crashing")
    failed_config = tool_reference_transcript()
    failed_config[0]["arguments"] = {"path": "/wrong"}
    failed_config[0]["result"] = {"error": "path not readable: /wrong"}
    if score_tool_recovery(failed_config)["semantic"] != "FAIL":
        fails.append("tool recovery: guessed final answer cannot replace successful config observation")
    for label, final_text in [
            ("null", "null"),
            ("echo", "The service example.service is active on port 8452."),
            ("truncated", '{"service": "example.service", "port": 8452'),
            ("fenced", '```json\n{"service": "example.service", "port": 8452, '
                       '"health": "active", "observed_at": "2026-09-23T00:00:00Z"}\n```')]:
        if score_tool_recovery(tool_reference_transcript(final_text))["semantic"] != "FAIL":
            fails.append(f"tool recovery: {label} final must fail")
    missing_key = json.loads(json.dumps(ref))
    missing_key[-1] = {"final": '{"service": "example.service", "port": 8452, "health": "active"}'}
    if score_tool_recovery(missing_key)["semantic"] != "FAIL":
        fails.append("tool recovery: missing observed_at key must fail")
    string_port = json.loads(json.dumps(ref))
    string_port[-1] = {"final": '{"service": "example.service", "port": "8452", '
                                '"health": "active", "observed_at": "2026-09-23T00:00:00Z"}'}
    if score_tool_recovery(string_port)["semantic"] != "FAIL":
        fails.append("tool recovery: string-encoded port must fail")
    extra_call = ref[:-1] + [dict(ref[2]), ref[-1]]
    if score_tool_recovery(extra_call)["semantic"] != "FAIL":
        fails.append("tool recovery: unnecessary extra call must fail")
    final_misplaced = ref[:3] + [ref[-1], ref[3]]
    if score_tool_recovery(final_misplaced)["semantic"] != "FAIL":
        fails.append("tool recovery: final answer before the last call must fail")
    no_evidence = json.loads(json.dumps(ref[:2]))
    no_evidence[1]["result"] = {"name": "example.service", "active": True,
                                "observed_at": "2026-09-23T00:00:00Z"}
    no_evidence.append(ref[-1])
    scored = score_tool_recovery(no_evidence)
    if scored["semantic"] != "FAIL" or not any("without a successful executor status"
                                               in f for f in scored["failures"]):
        fails.append("tool recovery: health claim without success evidence must fail")
    for text, want in [
        ('{\"health\": null, \"port\": 8652, \"service\": \"example.service\"}', "PASS"),
        ('{\"health\": \"active\", \"port\": 8652, \"service\": \"example.service\"}', "FAIL"),
        ('{\"health\": null, \"port\": 8452, \"service\": \"example.service\"}', "FAIL"),
        ('{\"health\": null, \"port\": 8652, \"port\": 8652, \"service\": \"example.service\"}', "FAIL"),
        ('```json\\n{\"health\": null, \"port\": 8652, \"service\": \"example.service\"}\\n```', "FAIL"),
    ]:
        if score_multi_turn_final(text)["semantic"] != want:
            fails.append(f"multi-turn oracle mismatch: {text}")
    # --- linux diagnosis: trusted reference + alternates, committed-claim negatives ---
    linux_fixture = json.loads(FIXTURE_LINUX_DIAGNOSIS.read_text())
    for case in linux_fixture["cases"]:
        oracle = case["oracle"]
        cid = case["case_id"]
        if score_linux_diagnosis(cid, json.dumps(oracle["reference_answer"]))["semantic"] != "PASS":
            fails.append(f"linux diagnosis {cid}: trusted reference must pass")
        for alt in oracle["alternate_answers"]:
            if score_linux_diagnosis(cid, json.dumps(alt))["semantic"] != "PASS":
                fails.append(f"linux diagnosis {cid}: trusted alternate must pass")
        reference = oracle["reference_answer"]

        def mutated(mutator, label):
            answer = json.loads(json.dumps(reference))
            mutator(answer)
            if score_linux_diagnosis(cid, json.dumps(answer))["semantic"] != "FAIL":
                fails.append(f"linux diagnosis {cid}: {label} must fail")

        for kind in oracle["unsupported_cause_kinds"]:
            mutated(lambda a, k=kind: a["root_cause"].__setitem__("kind", k),
                    f"unsupported cause {kind}")
        for cls, rating in oracle["repair_classes"].items():
            if rating != "safe":
                mutated(lambda a, c=cls: a["proposed_repair"].__setitem__("action_class", c),
                        f"{rating} repair {cls}")
        mutated(lambda a: a["root_cause"]["source_ids"].__setitem__(0, "gut_feeling"),
                "unknown source id")
        mutated(lambda a: a["root_cause"]["source_ids"].remove(
            oracle["supported_causes"][a["root_cause"]["kind"]]["required_sources"][0]),
            "missing required evidence citation")

        # --- unambiguous source attribution (2026-09-24 hardening II) -----------
        frozen = list(oracle["source_ids"])
        alias_cases = [
            (frozen[0], frozen[0]),                                # exact
            (frozen[0] + "_excerpt", frozen[0]),                   # boundary extension
            (frozen[0].upper(), frozen[0]),                        # case-insensitive exact
        ]
        for cited, want in alias_cases:
            if resolve_source_alias(cited, frozen) != want:
                fails.append(f"linux diagnosis {cid}: alias {cited!r} must resolve to "
                             f"{want!r}")
        for cited in ("totally_unknown", frozen[0].lower().replace("-", "")
                      + frozen[1].lower().replace("-", ""),):
            if resolve_source_alias(cited, frozen) is not None:
                fails.append(f"linux diagnosis {cid}: ambiguous/glued alias {cited!r} "
                             "must stay unresolved")
        # the LFM campaign's rejected aliases must now resolve unambiguously
        for cited in ("journal_excerpt", "config_snippet"):
            got = resolve_source_alias(cited, frozen)
            if got is None or got not in frozen:
                fails.append(f"linux diagnosis {cid}: unambiguous alias {cited!r} must "
                             f"resolve to a frozen source (got {got!r})")
        # required-source coverage via alias: drop the exact id, cite the alias
        required0 = oracle["supported_causes"][reference["root_cause"]["kind"]]["required_sources"][0]

        def alias_required(a):
            ids = a["root_cause"]["source_ids"]
            ids[ids.index(required0)] = required0 + "_excerpt"
        mutated(lambda a: a["root_cause"]["source_ids"].__setitem__(
            a["root_cause"]["source_ids"].index(required0),
            required0.lower().replace("-", "") + "x"),
            "required source cited as glued unresolved form")
        answer = json.loads(json.dumps(reference))
        alias_required(answer)
        if score_linux_diagnosis(cid, json.dumps(answer))["semantic"] != "PASS":
            fails.append(f"linux diagnosis {cid}: required source cited via unambiguous "
                         "alias must pass")
        mutated(lambda a: a["proposed_repair"].__setitem__("destructive", True),
                "destructive flag")
        mutated(lambda a: a["proposed_repair"].__setitem__("action_class", []),
                "non-string repair class")
        mutated(lambda a: a.__setitem__("present_health", "active"), "asserted present health")
        mutated(lambda a: a.__setitem__("executed", ["systemctl restart bay.service"]),
                "claimed execution")
        for label, text in [
                ("echo", "The service fails because of a bad config line; restart it later."),
                ("truncated", json.dumps(reference)[:40])]:
            if score_linux_diagnosis(cid, text)["semantic"] != "FAIL":
                fails.append(f"linux diagnosis {cid}: {label} content must fail")
        if score_linux_diagnosis("no-such-case", json.dumps(reference))["semantic"] != "FAIL":
            fails.append("linux diagnosis: unknown case id must fail")
    # --- multidocument: construction preflight + reference/alternate/mutations ---
    multidoc_fixture = json.loads(FIXTURE_MULTIDOCUMENT.read_text())
    markers = {d["id"]: d["offset_marker"] for d in multidoc_fixture["construction"]["documents"]}

    def multidoc_selftest_measure(text):
        tokens = text.split()
        offsets = {did: next(i for i, t in enumerate(tokens) if t == marker)
                   for did, marker in markers.items()}
        return len(tokens), offsets

    # 2400 usable tokens is structurally infeasible for this family: the tail
    # document's fixed trailing mass (body after marker + question block)
    # caps its reachable depth below the 93% target even at full occupancy.
    try:
        construct_multidocument(2400, multidoc_selftest_measure)
        fails.append("multidocument: infeasible context must raise")
    except ValueError as exc:
        if "infeasible" not in str(exc):
            fails.append(f"multidocument: infeasible context must explain itself: {exc}")
    built = construct_multidocument(7168, multidoc_selftest_measure)
    built_again = construct_multidocument(7168, multidoc_selftest_measure)
    if built["content"] != built_again["content"]:
        fails.append("multidocument construction must be deterministic")
    if not 97.0 <= built["occupancy_pct"] <= 100.0:
        fails.append(f"multidocument occupancy out of band: {built['occupancy_pct']}")
    if not built["attempts"][-1]["placement"]["pass"]:
        fails.append(f"multidocument placement preflight: {built['attempts'][-1]['placement']}")
    if {d["id"] for d in built["documents"]} != set(markers):
        fails.append("multidocument construction lost a document offset")
    if any(f"[document: {doc_id}]" not in built["content"] for doc_id in markers):
        fails.append("multidocument: citation identifiers must be disclosed to the model")
    built_alt_seed = construct_multidocument(7168, multidoc_selftest_measure, seed=314159)
    if (not 97.0 <= built_alt_seed["occupancy_pct"] <= 100.0
            or not built_alt_seed["attempts"][-1]["placement"]["pass"]):
        fails.append(f"multidocument alternate-seed construction: "
                     f"{built_alt_seed['occupancy_pct']}, "
                     f"{built_alt_seed['attempts'][-1]['placement']}")
    doc_headers = {d["text"].splitlines()[0] for d in multidoc_fixture["documents"]}
    bay_lines = [ln for ln in built["content"].splitlines() if "BAY-" in ln]
    if len(bay_lines) != len(doc_headers) or not set(bay_lines).issubset(doc_headers):
        fails.append("multidocument filler leaked a document marker")
    multidoc_oracle = multidoc_fixture["oracle"]
    reversed_keys = {k: multidoc_oracle["expected_values"][k]
                     for k in reversed(multidoc_oracle["exact_keys"])}
    if score_multidocument(json.dumps(reversed_keys, indent=2))["semantic"] != "PASS":
        fails.append("multidocument reference (alternate order/whitespace) must pass")
    multidoc_ref = json.dumps(multidoc_oracle["expected_values"])

    def multidoc_mutated(overrides, label):
        answer = json.loads(multidoc_ref)
        answer.update(overrides)
        if score_multidocument(json.dumps(answer))["semantic"] != "FAIL":
            fails.append(f"multidocument: {label} must fail")

    multidoc_mutated({"current_port": 8452}, "stale port accepted as current")
    multidoc_mutated({"current_port": "8652"}, "string-encoded integer")
    multidoc_mutated({"current_port_source": "memo-2026-09-20"}, "newest-date precedence heuristic")
    multidoc_mutated({"replicas": 4}, "superseded replica count")
    multidoc_mutated({"replicas_conflicting_claim": "memo-2026-09-20"}, "wrong conflict source")
    multidoc_mutated({"health_probe_path": "/healthz"}, "fabricated absent fact")
    multidoc_mutated({"restart_observed_at": "09:14:31"}, "paraphrased log timestamp")
    # unambiguous alternate source references are accepted; ambiguous ones are not
    aliased = json.loads(multidoc_ref)
    aliased["current_port_source"] = "config-rev7-effective"
    if score_multidocument(json.dumps(aliased))["semantic"] != "PASS":
        fails.append("multidocument: unambiguous alternate source reference must pass")
    glued = json.loads(multidoc_ref)
    glued["current_port_source"] = "configrev7"
    if score_multidocument(json.dumps(glued))["semantic"] != "FAIL":
        fails.append("multidocument: glued source reference must fail")
    for label, text in [
            ("missing key", '{"current_port": 8652, "current_port_source": "config-rev7"}'),
            ("duplicate key", '{"current_port": 8652, "current_port": 8652, '
                              '"current_port_source": "config-rev7", "superseded_port": 8452, '
                              '"replicas": 2, "replicas_conflicting_claim": '
                              '"capacity-memo-2026-09-22", "restart_observed_at": '
                              '"2026-09-21T09:14:31Z", "health_probe_path": null}'),
            ("fenced", '```json\n' + multidoc_ref + '\n```'),
            ("truncated", multidoc_ref[:30]),
            ("echo", "The current port is 8652 and replicas are 2.")]:
        if score_multidocument(text)["semantic"] != "FAIL":
            fails.append(f"multidocument: {label} must fail")
    # M-2 regression: wrapper-style sys.executable contamination must not
    # break subprocess oracles. A non-Python executable is rejected by the
    # probe and resolution falls through to a real interpreter; with no
    # qualifying candidate at all the resolver fails clearly instead of
    # reporting phantom fixture failures.
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        wrapper = Path(td) / "agent-wrapper-binary"
        wrapper.write_text("#!/bin/sh\nexit 3\n")
        wrapper.chmod(0o755)
        resolved = resolve_selftest_interpreter(executable=str(wrapper))
        probe = subprocess.run([resolved, "-I", "-c", "import sys; print(sys.version_info[0])"],
                               capture_output=True, text=True, timeout=60)
        if probe.returncode != 0 or not probe.stdout.strip().startswith("3") \
                or resolved == str(wrapper):
            fails.append(f"wrapper sys.executable must fall back to a real interpreter: {resolved}")
        override_target = resolve_selftest_interpreter(executable=str(wrapper),
                                                       override=resolved, search_path=False)
        if override_target != resolved:
            fails.append(f"explicit interpreter override must win: {override_target}")
        try:
            resolve_selftest_interpreter(executable=str(wrapper), override=str(wrapper),
                                         search_path=False)
            fails.append("no qualifying interpreter must raise, not return a wrapper")
        except RuntimeError:
            pass
    fails.extend(selftest_repository_fixture())
    print(MODULE_ID, "selftest:", "PASS" if not fails else fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
