"""Practical-context unit preparation and offline validation (M2 baseline).

Prepares the two frozen controlled-context families (Family A 1.3.0-draft,
Multi-Document 0.1.0-draft) under practical-context/2: Family A at
3072 / 4096 / 8192 and Multi-Document at 6144 / 8192 prompt tokens.
Validates observed construction offline, rigorously, before inference.

Scientific honesty rules implemented here:
- No approximate word counts are ever presented as tokenized context: the
  construction uses a caller-supplied ``measure`` callback backed by the
  native /apply-template + /tokenize metadata (identical special-token
  behavior to inference), and every retained measurement lands in the
  construction evidence the runner saves.
- Construction geometry is hard-gated before inference: occupancy 97–100 %
  and per-fact/document placement error <= 0.5 pp; any failure aborts the
  context unit with a CheckError before a request exists.
- Seeds are FILLER-construction seeds only; the qualified inference sampling
  configuration is the profile's and is never touched here.
- Family A seeds are the fixture-authorized {42, 314159}; the multidocument
  fixture pins construction.seed=42 and no second seed is authorized — a
  second multidocument seed is infeasible by fixture, never silently skipped.
- Offline validation byte-reconstructs the final context from the recorded
  filler geometry and seed, re-derives depths/occupancy/placement from the
  recorded token evidence, and checks the question block byte-identity.
Stdlib only (hashlib, json); raises welp_next.policy.CheckError.
"""
import hashlib
import json
import math
import time
import urllib.request

from . import policy
from .scorers import context_family_a, context_multidocument

SCHEDULE_VERSION = "practical-context/2"
FAMILY_A_SEEDS = (42, 314159)
MULTIDOCUMENT_SEEDS = (42,)
FAMILIES = {
    "family_a": {
        "fixture": "fixtures/useful_context/family-a.json",
        "checkpoints": (3072, 4096, 8192),
        "seeds": FAMILY_A_SEEDS,
        "seed_rationale": "fixture seeds: [42, 314159] (authorized pair)",
    },
    "multidocument": {
        "fixture": "fixtures/useful_context/multidocument.json",
        "checkpoints": (6144, 8192),
        "seeds": MULTIDOCUMENT_SEEDS,
        "seed_rationale": ("fixture pins construction.seed=42; no second seed is "
                           "authorized by the frozen fixture"),
    },
}
_MEASURE_METHOD = "native_apply_template_tokenize"
_MARKER_PREFIX = " "  # legacy-frozen locate prefix for marker token probes
_MEASURE_TIMEOUT_SECONDS = 30


def _post_json(profile: dict, path: str, payload: dict, *, deadline=None):
    """One metadata POST to the qualified serving endpoint (no inference).

    /apply-template renders and /tokenize counts; both are native metadata
    paths with identical special-token behavior to inference. This runs at
    execution time only, never offline.
    """
    url = profile["runtime"]["serve"]["endpoint"].rstrip("/") + path
    body = policy.canonical(payload)
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    timeout = _MEASURE_TIMEOUT_SECONDS if deadline is None else min(
        _MEASURE_TIMEOUT_SECONDS, deadline-time.monotonic())
    if timeout <= 0:
        raise TimeoutError("task deadline exhausted before native metadata")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("task deadline exhausted during native metadata")
    return json.loads(raw.decode("utf-8"))


def _locate(ids: list, target: list) -> int:
    """Legacy-frozen marker location: first subsequence match of the marker
    token ids in the final rendered stream, tolerant of a tokenizer fusing
    the leading space (up to three dropped leading ids)."""
    width = len(target)
    for skip in range(min(3, width - 1) + 1):
        needle = target[skip:]
        if not needle:
            continue
        matches = [i for i in range(len(ids) - len(needle) + 1)
                   if ids[i:i + len(needle)] == needle]
        if len(matches) == 1:
            return matches[0] - skip
    raise policy.CheckError(
        "measure: marker token ids not found in the final rendered stream")


def measure_factory(profile: dict, messages: list, markers: dict, client=None):
    """Build the native measure callback and its retained identity metadata.

    ``messages`` is the task's frozen message list with the LAST user entry
    carrying the placeholder content; ``markers`` maps each construction
    marker (fact target / document id) to its offset-marker string. The
    returned measure(content) renders the exact request messages (the
    profile's reasoning controls ride along, exactly as request_body merges
    them), tokenizes the rendered stream, and returns
    (total_tokens, {marker: token_start}).

    ``client`` optionally substitutes the (render, tokenize) pair for
    offline construction regression; production always uses the endpoint
    via :func:`token_client`.

    measure_meta is bound to the profile HERE — engine identity, artifact
    sha-256 and template sha-256 are copied from the profile, so construction
    evidence can never claim a tokenizer the qualified deployment does not
    use. validate_construction re-checks that equality offline.
    """
    engine = profile["runtime"]["engine"]
    render, tokenize = client if client is not None else token_client(profile)
    prefix_ids = {name: tokenize(_MARKER_PREFIX + marker, add_special=False)
                  for name, marker in markers.items()}

    def measure(content: str):
        rendered_messages = [dict(m) for m in messages]
        rendered_messages[-1] = {**rendered_messages[-1], "content": content}
        prompt = render(rendered_messages)
        ids = tokenize(prompt)
        offsets = {name: _locate(ids, target) for name, target in prefix_ids.items()}
        meta["final_measurement"] = {
            "render_request": {"messages": rendered_messages, **profile["reasoning"]["controls"]},
            "render_response": {"prompt": prompt},
            "tokenize_request": {"content": prompt, "add_special": True, "parse_special": True},
            "tokenize_response": {"tokens": ids},
            "marker_tokens": prefix_ids}
        return len(ids), offsets

    meta = {
        "method": _MEASURE_METHOD,
        "engine": f"{engine['name']}/{engine['version']}",
        "model_sha256": profile["model"]["artifact"]["sha256"],
        "template_sha256": profile["model"]["tokenizer_chat_template"]["sha256"],
        "apply_template_path": "/apply-template",
        "tokenize_path": "/tokenize",
        "tokenize_add_special": True,
        "tokenize_parse_special": True,
        "marker_locate_prefix": _MARKER_PREFIX,
    }
    return measure, meta


def token_client(profile: dict):
    """The two native metadata callables (render, tokenize) for a profile.

    ``tokenize(text, add_special=True)`` mirrors the native /tokenize
    contract; marker prefix probes call it with add_special=False.
    """
    controls = profile["reasoning"]["controls"]

    def render(rendered_messages):
        return _post_json(profile, "/apply-template",
                          {"messages": rendered_messages, **controls})["prompt"]

    def tokenize(text, add_special=True):
        return _post_json(profile, "/tokenize",
                          {"content": text, "add_special": add_special, "parse_special": True})["tokens"]

    return render, tokenize


def measure_native_request(profile: dict, body: dict, *, deadline=None) -> dict:
    """Meter the exact Agentic conversation AND tools; no generation or edits."""
    payload = {"messages": body["messages"], "add_generation_prompt": True,
               **profile["reasoning"]["controls"]}
    for key in ("tools", "tool_choice"):
        if key in body:
            payload[key] = body[key]
    timeout = {} if deadline is None else {"deadline": deadline}
    rendered = _post_json(profile, "/apply-template", payload, **timeout)
    if not isinstance(rendered, dict) or not isinstance(rendered.get("prompt"), str):
        raise policy.CheckError("calibration.context: native rendered prompt unavailable")
    token_request = {"content": rendered["prompt"], "add_special": True, "parse_special": True}
    tokenized = _post_json(profile, "/tokenize", token_request, **timeout)
    ids = tokenized.get("tokens") if isinstance(tokenized, dict) else None
    if not isinstance(ids, list) or any(type(n) is not int or n < 0 for n in ids):
        raise policy.CheckError("calibration.context: native token IDs unavailable")
    return {"method": "native_apply_template_tokenize_with_tools",
            "request_sha256": policy.digest(body), "render_request": payload,
            "render_response": rendered, "tokenize_request": token_request,
            "tokenize_response": tokenized, "input_tokens": len(ids),
            "context_capacity": profile["runtime"]["context_capacity"]}


def _fixture_digest(relpath: str) -> str:
    return policy.file_sha(policy.PROJECT_ROOT / relpath)


def family_fixture(family: str) -> dict:
    """Load the frozen family fixture (single source of the question block)."""
    path = policy.PROJECT_ROOT / FAMILIES[family]["fixture"]
    return json.loads(path.read_text(encoding="utf-8"))


def question_block(family: str) -> str:
    fixture = family_fixture(family)
    return fixture["construction"]["question_block"]


def construct_context_unit(family: str, checkpoint_tokens: int, seed: int,
                           measure, max_attempts: int = 30) -> dict:
    """Run the frozen deterministic construction at one checkpoint.

    ``measure(content)`` must return ``(total_tokens, {marker: token_start})``
    from the native /apply-template + /tokenize metadata path. The returned
    dict carries the final content and the full attempt ledger; geometry
    failures raise before any inference exists.
    """
    if family == "family_a":
        return context_family_a.construct_family_a(
            checkpoint_tokens, seed, measure, max_attempts=max_attempts)
    if family == "multidocument":
        return context_multidocument.construct_multidocument(
            checkpoint_tokens, measure, max_attempts=max_attempts, seed=seed)
    raise policy.CheckError(f"unknown context family: {family!r}")


def _char_offsets(content: str, markers: list[str]) -> dict[str, int]:
    offsets = {}
    for marker in markers:
        count = content.count(marker)
        if count != 1:
            raise policy.CheckError(
                f"context marker {marker!r} appears {count} times in the constructed "
                "context (expected exactly once)")
        offsets[marker] = content.index(marker)
    return offsets


def _reconstruct_content(family: str, seed: int, filler_count: int,
                         positions: dict[str, int]) -> str:
    """Byte-exact offline rebuild of the constructed context.

    The constructions are pure functions of (seed, filler_count, positions):
    filler generation consumes random.Random(seed) in a fixed order and the
    frozen facts/documents are overlaid at the recorded slots. Recorded by
    prepare_task exactly so validate_preparation never needs a tokenizer.
    """
    import random

    if family == "family_a":
        fixture = context_family_a._load_fixture()
        construction = fixture["construction"]
        facts = construction["inserted_facts"]
        pool = construction["word_pool"]
        rng = random.Random(seed)
        words = [rng.choice(pool) for _ in range(filler_count)]
        for fact in facts:
            words[positions[fact["target"]]] = fact["text"]
        return " ".join(words) + "\n" + construction["question_block"]
    fixture = context_multidocument._load_fixture()
    construction = fixture["construction"]
    doc_targets = construction["documents"]
    doc_text = {d["id"]: f"[document: {d['id']}]\n{d['text']}" for d in fixture["documents"]}
    forbidden = construction.get("filler_forbidden_substrings", [])
    rng = random.Random(seed)
    templates = context_multidocument._MULTIDOC_FILLER_TEMPLATES
    filler = []
    for i in range(filler_count):
        template = templates[i % len(templates)]
        for _try in range(100):
            line = template.format(w=rng.randint(1, 16), n=rng.randint(100000, 999999),
                                   s=rng.randint(0, 9), t=rng.randint(0, 9),
                                   k=rng.randint(100, 999))
            if not any(bad in line for bad in forbidden):
                break
        else:
            raise policy.CheckError("offline filler reconstruction hit the forbidden redraw bound")
        filler.append(line)
    doc_at = {positions[d["id"]]: d["id"] for d in doc_targets}
    lines = []
    fill = iter(filler)
    for i in range(filler_count):
        if i in doc_at:
            lines.extend(doc_text[doc_at[i]].split("\n"))
        else:
            lines.append(next(fill))
    return "\n".join(lines) + "\n" + construction["question_block"]


def _markers(family: str) -> list[str]:
    if family == "family_a":
        return [f["target"] for f in
                context_family_a._load_fixture()["construction"]["inserted_facts"]]
    return [d["offset_marker"] for d in
            context_multidocument._load_fixture()["construction"]["documents"]]


def build_construction_evidence(family: str, checkpoint_tokens: int, seed: int,
                                result: dict, measure_meta: dict | None) -> dict:
    """Assemble the retained construction evidence for the runner to save."""
    spec = FAMILIES[family]
    content = result["content"]
    filler_key = "filler_words" if family == "family_a" else "filler_lines"
    if family == "family_a":
        positions = {fact["target"]: pos for fact, pos in zip(
            context_family_a._load_fixture()["construction"]["inserted_facts"],
            result["positions"])}
    else:
        positions = dict(result["slots"])
    final = result["attempts"][-1]
    token_offsets = {str(k): int(v) for k, v in result["token_offsets"].items()}
    depths = final["depths_pct"]
    evidence = {
        "kind": "constructed_context",
        "schedule": SCHEDULE_VERSION,
        "family": family,
        "fixture": spec["fixture"],
        "fixture_sha256": _fixture_digest(spec["fixture"]),
        "checkpoint_tokens": checkpoint_tokens,
        "usable_tokens": checkpoint_tokens,
        "seed": seed,
        "seed_scope": "filler-construction seed only; inference sampling remains "
                      "profile-defined and is never overridden",
        "max_attempts": len(result["attempts"]),
        "construction": {
            "reconstruction": {"filler_count": result[filler_key], "positions": positions},
            "filler_count": result[filler_key],
        },
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_bytes": len(content.encode("utf-8")),
        "char_offsets": _char_offsets(content, _markers(family)),
        "rendered_tokens": final["rendered_tokens"],
        "token_offsets": token_offsets,
        "depths_pct": depths,
        "occupancy_pct": final["occupancy_pct"],
        "placement": final["placement"],
        "attempts": result["attempts"],
        "gates": {
            "occupancy": {
                "value_pct": final["occupancy_pct"],
                "hard_pass": 97.0 <= final["occupancy_pct"] <= 100.0,
                "preferred": final["occupancy_pct"] >= 99.0,
                "hard_band": [97.0, 100.0],
            },
            "placement": final["placement"],
        },
    }
    meta = dict(measure_meta or {})
    meta.setdefault("method", _MEASURE_METHOD)
    evidence["measure_meta"] = meta
    return evidence


def validate_construction(profile: dict, original_task: dict, prepared_task: dict,
                          evidence: dict) -> None:
    """Rigorous offline validation of an observed context construction.

    Raises policy.CheckError on any defect; returns None when the prepared
    task is byte-justified by the evidence. No endpoint, no tokenizer.
    """
    name = "validate_preparation"
    if not isinstance(evidence, dict) or evidence.get("kind") != "constructed_context":
        raise policy.CheckError(f"{name}: evidence is not a constructed_context record")
    family = evidence.get("family")
    if family not in FAMILIES:
        raise policy.CheckError(f"{name}: unknown family {family!r}")
    spec = FAMILIES[family]
    checkpoint = evidence.get("checkpoint_tokens")
    checkpoints = spec["checkpoints"]
    if (checkpoint not in checkpoints or evidence.get("schedule") != SCHEDULE_VERSION
            or original_task.get("context_schedule") != SCHEDULE_VERSION):
        raise policy.CheckError(f"{name}: family/checkpoint/schedule outside the fixed "
                                f"{SCHEDULE_VERSION} schedule for {family}: {checkpoints}")
    if (family != original_task.get("family") or
            checkpoint != original_task.get("context_checkpoint") or
            evidence.get("seed") != original_task.get("seed")):
        raise policy.CheckError(f"{name}: construction is not the pinned family/checkpoint/seed")
    if evidence.get("usable_tokens") != checkpoint:
        raise policy.CheckError(f"{name}: usable_tokens must equal the checkpoint target")
    seed = evidence.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed not in spec["seeds"]:
        raise policy.CheckError(
            f"{name}: seed {seed!r} not authorized for {family} ({spec['seed_rationale']})")
    if evidence.get("seed_scope") is None:
        raise policy.CheckError(f"{name}: seed_scope must record the filler-only seed rule")
    if evidence.get("fixture") != spec["fixture"] or evidence.get("fixture_sha256") != \
            _fixture_digest(spec["fixture"]):
        raise policy.CheckError(f"{name}: fixture identity mismatch for {family}")

    meta = evidence.get("measure_meta") or {}
    if meta.get("method") != _MEASURE_METHOD:
        raise policy.CheckError(
            f"{name}: measure_meta.method must be {_MEASURE_METHOD} "
            "(native /apply-template + /tokenize metadata; approximate word counts "
            "are never accepted as tokenized context)")
    for field in ("engine", "model_sha256", "template_sha256"):
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            raise policy.CheckError(f"{name}: measure_meta.{field} missing — the retained "
                                    "tokenizer identity is mandatory evidence")
    for field in ("model_sha256", "template_sha256"):
        value = meta.get(field)
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise policy.CheckError(f"{name}: measure_meta.{field} is not a sha-256 hex digest")
    # The retained tokenizer identity must BE the qualified deployment's, not
    # merely well-formed: engine, artifact and template bind to the profile.
    engine = profile["runtime"]["engine"]
    expected_meta = {
        "engine": f"{engine['name']}/{engine['version']}",
        "model_sha256": profile["model"]["artifact"]["sha256"],
        "template_sha256": profile["model"]["tokenizer_chat_template"]["sha256"],
    }
    for field, expected in expected_meta.items():
        if meta.get(field) != expected:
            raise policy.CheckError(
                f"{name}: measure_meta.{field} does not match the qualified profile "
                f"(expected {expected!r}, got {meta.get(field)!r})")

    # Byte-exact offline reconstruction from (seed, filler_count, positions).
    reconstruction = (evidence.get("construction") or {}).get("reconstruction") or {}
    filler_count = reconstruction.get("filler_count")
    positions = reconstruction.get("positions")
    if not isinstance(filler_count, int) or filler_count < 1 or not isinstance(positions, dict):
        raise policy.CheckError(f"{name}: construction.reconstruction geometry missing")
    expected_content = _reconstruct_content(family, seed, filler_count, positions)
    digest = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()
    if digest != evidence.get("content_sha256"):
        raise policy.CheckError(f"{name}: evidence content_sha256 does not match the "
                                "deterministic offline reconstruction")
    prepared_content = _prepared_user_content(prepared_task)
    if hashlib.sha256(prepared_content.encode("utf-8")).hexdigest() != digest:
        raise policy.CheckError(f"{name}: prepared task content does not match the "
                                "validated construction bytes")
    if evidence.get("content_bytes") != len(prepared_content.encode("utf-8")):
        raise policy.CheckError(f"{name}: content_bytes mismatch")

    # Frozen question block byte-identity and single-occurrence markers.
    qb = question_block(family)
    if not prepared_content.endswith(qb):
        raise policy.CheckError(f"{name}: constructed context does not end with the frozen "
                                "question block byte-identically")
    for marker in _markers(family):
        count = prepared_content.count(marker)
        if count != 1:
            raise policy.CheckError(f"{name}: marker {marker!r} occurs {count} times "
                                    "(expected exactly once)")
    char_offsets = evidence.get("char_offsets") or {}
    if set(char_offsets) != set(_markers(family)):
        raise policy.CheckError(f"{name}: char_offsets inventory mismatch")
    for marker, offset in char_offsets.items():
        if not isinstance(offset, int) or prepared_content.index(marker) != offset:
            raise policy.CheckError(f"{name}: char offset for {marker!r} does not match "
                                    "the prepared content")

    # Geometry re-derivation from the recorded token evidence. Every recorded
    # numeric must be present and finite: a NaN/inf silently passes
    # difference comparisons, so finiteness is checked explicitly, first.
    def _finite(value, what):
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise policy.CheckError(f"{name}: {what} must be a finite number, "
                                    f"got {value!r}")
        return value

    rendered = _finite(evidence.get("rendered_tokens"), "rendered_tokens")
    if not isinstance(rendered, int) or rendered <= 0:
        raise policy.CheckError(f"{name}: rendered_tokens must be a positive measured count")
    token_offsets = evidence.get("token_offsets") or {}
    marker_keys = (_markers(family) if family == "family_a" else
                   [d["id"] for d in context_multidocument._load_fixture()["construction"]["documents"]])
    if set(token_offsets) != set(marker_keys):
        raise policy.CheckError(f"{name}: token_offsets inventory mismatch")
    for marker, offset in token_offsets.items():
        _finite(offset, f"token offset for {marker!r}")
        if not isinstance(offset, int) or not 0 <= offset < rendered:
            raise policy.CheckError(f"{name}: token offset for {marker!r} outside the "
                                    "measured stream")
    depths = {marker: 100.0 * offset / rendered for marker, offset in token_offsets.items()}
    recorded_depths = evidence.get("depths_pct") or {}
    if set(recorded_depths) != set(marker_keys):
        raise policy.CheckError(f"{name}: depths_pct inventory mismatch")
    for marker, value in depths.items():
        recorded = _finite(recorded_depths.get(marker), f"recorded depth for {marker!r}")
        if abs(recorded - value) > 1e-6:
            raise policy.CheckError(f"{name}: recorded depth for {marker!r} inconsistent with "
                                    "token offsets")
    occupancy = 100.0 * rendered / checkpoint
    recorded_occupancy = _finite(evidence.get("occupancy_pct"), "occupancy_pct")
    if abs(recorded_occupancy - occupancy) > 1e-6:
        raise policy.CheckError(f"{name}: recorded occupancy inconsistent with "
                                f"rendered_tokens/checkpoint ({occupancy:.3f}%)")
    if not 97.0 <= occupancy <= 100.0:
        raise policy.CheckError(f"{name}: occupancy {occupancy:.3f}% outside the hard band "
                                "[97, 100] — construction must abort before inference")
    if family == "family_a":
        placement = context_family_a.placement_preflight(depths)
    else:
        targets = {d["id"]: 100.0 * d["target_depth"] for d in
                   context_multidocument._load_fixture()["construction"]["documents"]}
        placement = context_multidocument._multidoc_placement(depths, targets)
    if not placement["pass"]:
        raise policy.CheckError(f"{name}: placement gate failed ({placement}) — construction "
                                "must abort before inference")
    recorded_placement = evidence.get("placement") or {}
    recorded_error = _finite(recorded_placement.get("max_error_pp"),
                             "recorded placement max_error_pp")
    if abs(recorded_error - placement["max_error_pp"]) > 1e-3:
        raise policy.CheckError(f"{name}: recorded placement error inconsistent with token "
                                "offsets")
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list) or not attempts or \
            attempts[-1].get("rendered_tokens") != rendered:
        raise policy.CheckError(f"{name}: attempt ledger must be non-empty and end at the "
                                "rendered measurement")
    gates = evidence.get("gates") or {}
    if not (gates.get("occupancy") or {}).get("hard_pass") or \
            not (gates.get("placement") or {}).get("pass"):
        raise policy.CheckError(f"{name}: recorded gates must both pass")

    # Prepared task identity: everything except the context message content
    # and the added construction block is byte-identical to the original.
    _validate_prepared_identity(original_task, prepared_task)
    construction_block = prepared_task.get("construction")
    if not isinstance(construction_block, dict):
        raise policy.CheckError(f"{name}: prepared context task must carry its construction "
                                "metadata block")
    expected_block = {"family": family, "checkpoint_tokens": checkpoint, "seed": seed,
                      "filler_count": filler_count, "rendered_tokens": rendered}
    if construction_block != expected_block:
        raise policy.CheckError(f"{name}: prepared construction metadata differs from observed geometry")
    observed = meta.get("final_measurement", {})
    ids = observed.get("tokenize_response", {}).get("tokens")
    render_request = {"messages": prepared_task["messages"], **profile["reasoning"]["controls"]}
    prompt = observed.get("render_response", {}).get("prompt")
    if (observed.get("render_request") != render_request or not isinstance(prompt, str)
            or observed.get("tokenize_request") != {"content": prompt, "add_special": True, "parse_special": True}
            or not isinstance(ids, list) or len(ids) != rendered
            or any(type(token) is not int or token < 0 for token in ids)):
        raise policy.CheckError(f"{name}: original final rendered/tokenized observation missing or inconsistent")
    targets = observed.get("marker_tokens", {})
    if set(targets) != set(marker_keys) or any(
            _locate(ids, targets[key]) != offset for key, offset in token_offsets.items()):
        raise policy.CheckError(f"{name}: token positions do not reproduce from saved token stream")


def _prepared_user_content(prepared_task: dict) -> str:
    messages = (prepared_task or {}).get("messages")
    if not isinstance(messages, list) or not messages:
        raise policy.CheckError("validate_preparation: prepared task has no messages")
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user" or not isinstance(
            last.get("content"), str):
        raise policy.CheckError("validate_preparation: prepared task must end with a user "
                                "string message")
    return last["content"]


def _validate_prepared_identity(original_task: dict, prepared_task: dict) -> None:
    for key, value in original_task.items():
        if key == "messages":
            continue
        if prepared_task.get(key) != value:
            raise policy.CheckError(
                f"validate_preparation: prepared task changed field {key!r} — only the "
                "context content and construction metadata may differ")
    extra = set(prepared_task) - set(original_task) - {"construction"}
    if extra:
        raise policy.CheckError(
            f"validate_preparation: prepared task added unexpected fields {sorted(extra)}")
    original_messages = original_task.get("messages") or []
    prepared_messages = prepared_task.get("messages") or []
    if len(original_messages) != len(prepared_messages):
        raise policy.CheckError("validate_preparation: message count changed")
    # Byte-exact message identity: ONLY the last message (the constructed
    # user content) may differ, and only in its content. System bytes and
    # every other message are preserved verbatim.
    for index, (orig, prep) in enumerate(zip(original_messages, prepared_messages)):
        if not isinstance(orig, dict) or not isinstance(prep, dict):
            raise policy.CheckError("validate_preparation: message shapes changed")
        is_last = index == len(original_messages) - 1
        if is_last:
            if (orig.get("role") != "user" or prep.get("role") != "user"
                    or set(prep) - set(orig)
                    or not isinstance(prep.get("content"), str)):
                raise policy.CheckError(
                    "validate_preparation: only the final user message content may "
                    "change for the constructed context")
            continue
        if orig != prep:
            raise policy.CheckError(
                f"validate_preparation: message {index} bytes changed — the system "
                "prompt and all non-final messages are preserved verbatim")
