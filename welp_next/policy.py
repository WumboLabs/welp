"""WELP successor M1 central enforcement policy — single authority.

This module is the ONLY place where profile validity, facet→outcome
derivation, attempt resolution, section state, evidence completeness, and
fatal device/host error detection are defined (SPEC §8.1 single-authority
rule). Consumers: CLI, runner, preflight, (later) the validator.

Methodology pin for M1: ``baseline-reliability-slice/1`` — the 20-task
reliability v3 slice, seed 42, ONE request per task. This is a deliberately
limited slice; no legacy paired-lane/two-seed measurement design is
imported here.

Budget rule (SPEC invariant 1, fixed-before-testing): ``budgets`` are
preselected from a recorded qualification package. The fixture's
``generation_budget.answer_budget`` is an answer allowance observed in the
fixture corpus — it is NEVER accepted as a generation cap or as a
qualification source, and profiles must carry the before-output budget
note (``budgets.note``) recording that budgets were fixed before outputs.

Return structures (explicit):

    canonical(value) -> bytes           # sorted, compact, UTF-8 JSON
    digest(value) -> str                # sha256 hex of canonical(value)
    file_sha(path) -> str               # streamed sha256 hex of file bytes
    validate_profile(profile) -> None   # raises CheckError on any defect
    derive_outcome(execution, completion, scoring, limits) -> dict:
        {"execution": str, "completion": str, "scoring": str, "limits": str,
         "outcome": "PASS"|"FAIL"|"NOT_EVALUABLE"|"INVALID"|"NOT_RUN",
         "reason": None|"BUDGET_LIMITED"|"CEILING_EXHAUSTED"|
                   "RUBRIC_INDETERMINATE"|"UNSCORABLE_ANSWER"|
                   "EXECUTION_FAILURE"|"NOT_RUN"}
    resolved_attempt(attempts) -> dict | None
    unit_pending(attempts) -> bool
    section_state(units, interrupted=False, blocked=False) ->
        "INTERRUPTED" | "BLOCKED" | "COMPLETED_PARTIAL" | "COMPLETED"
    evidence_complete(attempt_dir) -> bool   # predicate, never raises
    fatal_device_error(text) -> bool
    fatal_error_categories(text) -> list[str]
"""

from __future__ import annotations

import hashlib
import json
import math
import shlex
from urllib.parse import urlsplit
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

# ---------------------------------------------------------------------------
# Pinned constants (single source of truth)

FRAMEWORK = "welp/1.0.0-alpha-m1"
METHODOLOGY = "baseline-reliability-slice/1"
FRAMEWORK_M2 = "welp/1.0.0-alpha-m2"
METHODOLOGY_M2 = "model-baseline/2"
METHODOLOGY_AGENTIC = "agentic-offline/1"
METHODOLOGY_AGENTIC_PRELIVE = "agentic-offline/2"
METHODOLOGY_AGENTIC_PROPOSED = "agentic-offline/3"
METHODOLOGY_DIAGNOSTIC = "deployment-diagnostic/1"
METHODOLOGY_CALIBRATION = "agentic-calibration/1"
SCORED_METHODOLOGY = "agentic/3"
SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_ATTEMPTS = 2
M1_SEED = 42
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.95

#: ``runtime.backend`` is a supplied deployment condition (SPEC §3.1/§3.2):
#: the operating agent records the executed backend identity and WELP reports
#: it verbatim. It is not an admission vocabulary — no enumeration here, only
#: a nonempty recorded identity.
MODEL_EVIDENCE_KINDS = ("REAL_MODEL", "SOFTWARE_TEST")
EVIDENCE_KINDS = (*MODEL_EVIDENCE_KINDS, "TECHNICAL_DIAGNOSTIC", "CALIBRATION")
REASONING_ARMS = ("ON", "OFF", "NOT_CONFIGURABLE")

#: Explicit baseline-coverage precommitment carried in the profile under
#: ``coverage.requirement``. ``full`` = the complete required baseline: the
#: plan may exclude no required identity and the declared meter evidence must
#: cover every required context unit BEFORE the first scored request (SPEC
#: §10.1: all native constructions pass before scored inference). ``partial``
#: keeps the historical pinned-exclusion behavior. Absent means ``partial``.
COVERAGE_REQUIREMENTS = ("full", "partial")

#: Generic qualified context-meter contract (any qualified engine; the native
#: llama.cpp ``/props`` route keeps its own historical contract). A declared
#: meter must expose the two native metadata routes — POST /apply-template
#: and POST /tokenize with llama.cpp-compatible semantics — on the serving
#: endpoint, bind hashed adapter/geometry/witness evidence files, and witness
#: token counts against the ORIGINAL retained native responses.
CONTEXT_METER_CONTRACT = "context-meter/1"
METER_WITNESS_CLASSES = ("serialization", "literal_protection", "tool_continuation")

#: Facet vocabularies (SPEC §5.1). Exactly these values, nothing else.
EXECUTION_FACETS = ("VALID", "INVALID", "NOT_RUN")
COMPLETION_FACETS = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
SCORING_FACETS = ("SCORED_PASS", "SCORED_FAIL", "NOT_SCOREABLE", "NOT_APPLICABLE")
LIMITS_FACETS = ("NONE", "BUDGET", "CEILING", "HOST")

#: Outcome classes whose execution facet is VALID (never rerun).
VALID_OUTCOMES = ("PASS", "FAIL", "NOT_EVALUABLE")

#: Profile control keys that must never reach the rendered request: identity,
#: transcript, streaming, and generation-budget/sampling channels are owned by
#: the runner from the profile's dedicated fields. ``max_completion_tokens``
#: is the OpenAI alias of ``max_tokens`` — same hazard, same rejection.
RESERVED_REQUEST_KEYS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "seed",
    }
)

#: Budget-source names that identify fixture answer allowances, never a
#: preselected qualification.
FORBIDDEN_BUDGET_SOURCES = frozenset({"answer_budget", "generation_budget"})

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PCI_ID = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
_KEY_TOKEN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_CAMPAIGN_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")

#: sanity bound for streamed hashing (never load files into memory; refuse to
#: hash absurd "files" such as a mis-pointed FIFO/proc node — regular files
#: larger than 16 TiB are treated as a profile error).
FILE_SHA_MAX_BYTES = 1 << 44
_CHUNK = 1 << 20


class CheckError(ValueError):
    """Raised for any fail-closed policy violation. ``field`` names the
    offending profile field or check name when known."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


# ---------------------------------------------------------------------------
# Canonical hashing


def canonical(value: Any) -> bytes:
    """Sorted, compact, UTF-8 JSON encoding of ``value``."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    """SHA-256 hex digest of canonical(value)."""
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: str | Path) -> str:
    """Streamed SHA-256 hex of a regular local file (1 MiB chunks; memory
    bounded regardless of artifact size). Raises CheckError when the path is
    not an existing regular file or exceeds FILE_SHA_MAX_BYTES."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError as exc:
        raise CheckError(f"artifact hashing: cannot stat {p}: {exc}") from exc
    if not _stat_regular(st):
        raise CheckError(f"artifact hashing: not a regular file: {p}")
    if st.st_size > FILE_SHA_MAX_BYTES:
        raise CheckError(
            f"artifact hashing: file exceeds {FILE_SHA_MAX_BYTES} bytes: {p}"
        )
    h = hashlib.sha256()
    try:
        with p.open("rb") as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except OSError as exc:
        raise CheckError(f"artifact hashing: read failed for {p}: {exc}") from exc
    return h.hexdigest()


def _stat_regular(st: Any) -> bool:
    import stat as _stat

    return _stat.S_ISREG(st.st_mode)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)



def is_m2(profile: dict) -> bool:
    return profile.get("framework", {}).get("methodology") == METHODOLOGY_M2


def is_diagnostic(profile: dict) -> bool:
    return profile.get("framework", {}).get("methodology") == METHODOLOGY_DIAGNOSTIC


def is_calibration(profile: dict) -> bool:
    return profile.get("framework", {}).get("methodology") == METHODOLOGY_CALIBRATION


def forward_argv(deployment: dict) -> list[str]:
    """One private transport, no configurable SSH options or remote command.

    The SSH alias targets the operator's qualified inference host configured
    in the local SSH configuration; it is deployment identity, not a public
    endpoint.
    """
    return ["/usr/bin/ssh", "-N", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-L",
            "127.0.0.1:18974:127.0.0.1:8088", "welp-inference-host"]



def task_applicability(profile: dict, task: dict) -> tuple[bool, str]:
    """Technical applicability only; never inferred from a model answer."""

    capabilities = profile.get("capabilities", {})
    for requirement in task.get("requires", []):
        if requirement == "native_tools":
            if (capabilities.get("native_tools") is not True or
                    not capabilities.get("qualification_source")):
                return False, "UNSUPPORTED: no qualified native tool interface declared"
        elif requirement == "context_meter":
            native = (profile["runtime"]["engine"]["name"] == "llama.cpp"
                      and profile["runtime"]["serve"]["echo_path"] == "/props")
            synthetic_meter = (profile.get("evidence_kind") == "SOFTWARE_TEST"
                               and capabilities.get("context_meter") is True)
            # Generic qualified meter (context-meter/1): a user-authorized,
            # engine-agnostic declaration. Admission here only recognizes the
            # declaration; the binding verification is meter_evidence_defects
            # (hashed witnesses vs original native responses) offline and the
            # live render/tokenize probe in preflight.online — never the
            # declaration alone and never an engine-name exception.
            generic_meter = context_meter_declaration(profile) is not None
            if not native and not synthetic_meter and not generic_meter:
                return False, "INTEGRATION_BLOCKED: no rendered-token context meter"
        elif requirement == "sandbox":
            if (capabilities.get("sandbox") is not True
                    or not capabilities.get("isolation_approval")):
                return False, "INTEGRATION_BLOCKED: approved isolated code executor not declared"
        else:
            _fail("task.requires", f"unknown deployment requirement {requirement!r}")
    checkpoint = task.get("context_checkpoint")
    if checkpoint is not None:
        headroom = task_budget(profile, task)["max_tokens"]
        if checkpoint + headroom > profile["runtime"]["context_capacity"]:
            return False, "UNSUPPORTED: checkpoint plus fixed generation reserve exceeds qualified capacity"
    return True, ""


def _performance_timing_gaps(timing: dict) -> list[str]:
    """Required serving measurements, never a speed/quality threshold."""
    gaps = []
    for name in ("prompt", "generation"):
        value = timing.get("tokens_per_second", {}).get(name)
        if not _is_num(value) or not math.isfinite(value) or value <= 0:
            gaps.append(name + "_throughput")
    latency = timing.get("latency_seconds")
    if not _is_num(latency) or not math.isfinite(latency) or latency <= 0:
        gaps.append("latency")
    usage = timing.get("usage")
    if not isinstance(usage, dict) or any(
        not _is_int(usage.get(k)) or usage[k] <= 0
        for k in ("prompt_tokens", "completion_tokens")
    ):
        gaps.append("token_usage")
    ttft = timing.get("ttft_seconds")
    if timing.get("streaming") and (
        not _is_num(ttft) or not _is_num(latency) or not 0 <= ttft <= latency
    ):
        gaps.append("ttft")
    return gaps


def performance_gaps(score: dict, profile: dict, task: dict) -> list[str]:
    path = Path(score.get("path", ""))
    try:
        if task.get("repetitions", 1) > 1:
            receipt = json.loads((path / "repetitions.json").read_bytes())
            timings = [r["timings"] for r in receipt["repeats"]]
            if len(timings) != task["repetitions"]:
                return ["required_repetitions"]
        else:
            timings = [json.loads((path / "conditions.json").read_bytes())["timings"]]
    except (OSError, ValueError, KeyError, TypeError):
        return ["original_timing_observations"]
    gaps = [f"repeat-{i}:{field}" for i, timing in enumerate(timings, 1)
            for field in _performance_timing_gaps(timing or {})]
    from . import observation
    memory = any(observation.device_memory(profile, observation.read_snapshot(profile, path, name))
                 is not None for name in observation.NAMES)
    if not memory:
        gaps.append("memory_consumption")
    return gaps


def baseline_coverage(fixture: dict, units: dict, profile: dict) -> dict:
    """Every fixed applicable identity is required, not an overall percentage.

    Negative scored answers satisfy evidence coverage. Budgets, unreviewed
    answers and missing measurements remain separate from correctness scores.
    """
    if not isinstance(units, dict):
        _fail("coverage.units", "expected unit id to attempt-list mapping")
    categories = {}
    for task in fixture["tasks"]:
        category = task["category"]
        row = categories.setdefault(category, {
            "planned": 0, "applicable": 0, "measured": 0, "scored": 0,
            "pass": 0, "fail": 0, "budget_limited": 0, "indeterminate": 0,
            "excluded": {}, "missing": [], "unscored": []})
        row["planned"] += 1
        applicable, reason = task_applicability(profile, task)
        uid = task["id"]
        if not applicable:
            row["excluded"][uid] = reason
            continue
        row["applicable"] += 1
        score = resolved_attempt(units.get(uid, []))
        if score is None or score.get("execution") != "VALID":
            row["missing"].append(uid)
            continue
        row["measured"] += 1
        if category == "performance":
            gaps = performance_gaps(score, profile, task)
            if gaps:
                row["measured"] -= 1
                row["missing"].append(uid)
                row.setdefault("measurement_gaps", {})[uid] = gaps
            continue
        if score.get("scoring") in ("SCORED_PASS", "SCORED_FAIL"):
            row["scored"] += 1
            row["pass" if score["scoring"] == "SCORED_PASS" else "fail"] += 1
        else:
            row["unscored"].append(uid)
            if score.get("reason") in ("BUDGET_LIMITED", "CEILING_EXHAUSTED"):
                row["budget_limited"] += 1
            else:
                row["indeterminate"] += 1
    for category, row in categories.items():
        if not row["applicable"]:
            state = "UNSUPPORTED_OR_NON_EVALUABLE"
        elif row["missing"]:
            state = "PARTIALLY_COMPLETE"
        elif row["unscored"] or row["excluded"]:
            state = "COMPLETE_WITH_DOCUMENTED_LIMITATIONS"
        else:
            state = "COMPLETE"
        row["status"] = state
        row["minimum_measurement_coverage_met"] = bool(row["applicable"]) and not row["missing"]
        row["minimum_scoring_coverage_met"] = bool(row["applicable"]) and not row["missing"] and not row["unscored"]
        if category == "performance":
            row["minimum_scoring_coverage_met"] = None
    states = {r["status"] for r in categories.values()}
    overall = ("PARTIALLY_COMPLETE" if "PARTIALLY_COMPLETE" in states else
               "COMPLETE_WITH_DOCUMENTED_LIMITATIONS" if states - {"COMPLETE"} else "COMPLETE")
    return {"status": overall, "categories": categories,
            "rule": "Every fixed applicable task identity; one result per identity, no duplicated credit",
            "classification": None, "advancement": "NOT_CALIBRATED"}


# ---------------------------------------------------------------------------
# Coverage precommitment and the generic qualified context meter


def coverage_requirement(profile: dict) -> str:
    """The profile's explicit baseline-coverage precommitment.

    Absent (all historical profiles) means ``partial``: excluded identities
    are pinned in the run identity exactly as before. ``full`` additionally
    requires the complete required baseline before the first scored request.
    """
    requirement = (profile.get("coverage") or {}).get("requirement", "partial")
    if requirement not in COVERAGE_REQUIREMENTS:
        _fail("coverage.requirement", f"must be one of {COVERAGE_REQUIREMENTS}")
    return requirement


def exclusion_cause(reason: str) -> str:
    """Precise plan cause for an excluded identity: an integration gap in the
    qualified deployment, an unsupported model/runtime condition, or an
    unclassified reason. Never silently merged."""
    if isinstance(reason, str) and reason.startswith("INTEGRATION_BLOCKED"):
        return "integration"
    if isinstance(reason, str) and reason.startswith("UNSUPPORTED"):
        return "unsupported"
    return "unclassified"


def context_meter_declaration(profile: dict) -> dict | None:
    """The declared generic qualified context meter, or None. A legacy boolean
    ``capabilities.context_meter`` is NOT a declaration: it keeps only its
    historical native-llama.cpp / SOFTWARE_TEST meanings."""
    declaration = (profile.get("capabilities") or {}).get("context_meter")
    return declaration if isinstance(declaration, dict) else None


def _validate_file_reference(value: Any, field: str) -> None:
    ref = _mapping(value, field)
    _abs_path(ref.get("path"), field + ".path")
    _hex64(ref.get("sha256"), field + ".sha256")


def _validate_meter_declaration(declaration: dict) -> None:
    """Structural validation only (stable for historical reconstruction);
    content verification runs at admission in meter_evidence_defects."""
    if declaration.get("contract") != CONTEXT_METER_CONTRACT:
        _fail("capabilities.context_meter.contract",
              f"must be {CONTEXT_METER_CONTRACT!r}")
    for key in ("adapter", "geometry_evidence"):
        _validate_file_reference(declaration.get(key),
                                 f"capabilities.context_meter.{key}")
    witnesses = declaration.get("witnesses")
    if not isinstance(witnesses, list) or not witnesses:
        _fail("capabilities.context_meter.witnesses", "must be a nonempty list")
    for index, witness in enumerate(witnesses):
        field = f"capabilities.context_meter.witnesses[{index}]"
        witness = _mapping(witness, field)
        _nonempty_str(witness.get("name"), field + ".name")
        if witness.get("class") not in METER_WITNESS_CLASSES:
            _fail(field + ".class", f"must be one of {METER_WITNESS_CLASSES}")
        _validate_file_reference(witness.get("request"), field + ".request")
        _validate_file_reference(witness.get("response"), field + ".response")
        _int_at_least(witness.get("meter_tokens"), 1, field + ".meter_tokens")


def _meter_json(path: str) -> tuple[Any, str | None]:
    try:
        return json.loads(Path(path).read_bytes()), None
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return None, str(exc)


def _meter_file_defects(reference: Any, name: str) -> list[str]:
    """Hashed-evidence check: the declared file must exist and hash-match."""
    if not isinstance(reference, dict):
        return [f"meter.{name}.reference"]
    path, sha = reference.get("path"), reference.get("sha256")
    if not isinstance(path, str) or not path.strip() or not _HEX64.fullmatch(str(sha)):
        return [f"meter.{name}.identity"]
    try:
        if file_sha(path) != sha:
            return [f"meter.{name}.sha256"]
    except (OSError, ValueError):
        return [f"meter.{name}.unreadable"]
    return []


def _witness_native_prompt_tokens(raw: bytes) -> int | None:
    """``usage.prompt_tokens`` from one ORIGINAL retained response body: a
    JSON envelope, or an SSE stream whose frames carry usage (last wins)."""
    def _from_usage(usage):
        if isinstance(usage, dict) and _is_int(usage.get("prompt_tokens")) \
                and usage["prompt_tokens"] > 0:
            return usage["prompt_tokens"]
        return None

    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        envelope = None
    if isinstance(envelope, dict):
        value = _from_usage(envelope.get("usage"))
        if value is not None:
            return value
    value = None
    for line in raw.splitlines():
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            frame = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(frame, dict):
            candidate = _from_usage(frame.get("usage"))
            if candidate is not None:
                value = candidate
    return value


def meter_evidence_defects(profile: dict) -> list[str]:
    """Offline verification of a declared generic context meter. Accepts no
    asserted verdict: every declared file must exist and hash-match, each
    witness's meter count must equal the native ``usage.prompt_tokens`` of
    the SAME hashed original response, witness requests must carry the
    profile's model/sampler/reasoning contract, and the geometry records must
    be passed native constructions bound to this deployment's engine/artifact/
    template identity. No endpoint contact; the live compatibility probe runs
    in preflight.online."""
    declaration = context_meter_declaration(profile)
    if declaration is None:
        return []
    defects = []

    def check(name, ok):
        if not ok:
            defects.append("meter." + name)

    check("contract", declaration.get("contract") == CONTEXT_METER_CONTRACT)
    for key in ("adapter", "geometry_evidence"):
        defects.extend(_meter_file_defects(declaration.get(key), key))
    witnesses = declaration.get("witnesses")
    if not isinstance(witnesses, list) or not witnesses:
        check("witnesses", False)
        return defects
    model_id = profile["runtime"]["serve"]["model_id"]
    samplers = sampling_settings(profile)
    controls = profile["reasoning"]["controls"]
    classes = set()
    for index, witness in enumerate(witnesses):
        prefix = f"witness[{index}]"
        if not isinstance(witness, dict):
            check(prefix, False)
            continue
        if isinstance(witness.get("class"), str):
            classes.add(witness["class"])
        for key in ("request", "response"):
            defects.extend(_meter_file_defects(witness.get(key), f"{prefix}.{key}"))
        request, error = _meter_json(str((witness.get("request") or {}).get("path", "")))
        if error is not None or not isinstance(request, dict):
            check(prefix + ".request.body", False)
        else:
            check(prefix + ".request.model", request.get("model") == model_id)
            for key, want in samplers.items():
                if key in request:
                    check(f"{prefix}.request.sampling.{key}", request[key] == want)
            for key, want in controls.items():
                check(f"{prefix}.request.control.{key}", request.get(key) == want)
        response = witness.get("response")
        if isinstance(response, dict):
            try:
                raw = Path(response["path"]).read_bytes()
            except (OSError, ValueError):
                raw = None
            native_tokens = _witness_native_prompt_tokens(raw) if raw is not None else None
            check(prefix + ".parity",
                  native_tokens is not None
                  and witness.get("meter_tokens") == native_tokens)
        else:
            check(prefix + ".response.reference", False)
    check("witness.classes", {
        # serialization + literal/control-token protection are mandatory for
        # every qualified meter; the tool-continuation witness is required
        # only when the qualified profile actually declares native tools.
        "serialization", "literal_protection",
        *({"tool_continuation"} if (profile.get("capabilities") or {}).get("native_tools") is True else set()),
    } <= classes)
    defects.extend(_geometry_rows_defects(profile, declaration))
    return defects


def _geometry_rows_defects(profile: dict, declaration: dict) -> list[str]:
    """Every geometry record must be a passed native construction bound to
    this deployment's engine/artifact/template identity."""
    reference = declaration.get("geometry_evidence")
    if not isinstance(reference, dict):
        return ["meter.geometry.reference"]
    rows, error = _meter_json(str(reference.get("path", "")))
    if error is not None or not isinstance(rows, list) or not rows:
        return ["meter.geometry.records"]
    defects = []
    engine = profile["runtime"]["engine"]
    expected_meta = {
        "engine": f"{engine['name']}/{engine['version']}",
        "model_sha256": profile["model"]["artifact"]["sha256"],
        "template_sha256": profile["model"]["tokenizer_chat_template"]["sha256"],
    }
    for index, row in enumerate(rows):
        prefix = f"meter.geometry[{index}]"
        if not isinstance(row, dict) or not isinstance(row.get("unit_id"), str):
            defects.append(prefix + ".unit_id")
            continue
        evidence = row.get("evidence")
        prepared = row.get("prepared")
        construction = (prepared or {}).get("construction") if isinstance(prepared, dict) else None
        meta = (evidence or {}).get("measure_meta") if isinstance(evidence, dict) else None
        gates = (evidence or {}).get("gates") if isinstance(evidence, dict) else None
        if not isinstance(evidence, dict) or evidence.get("kind") != "constructed_context":
            defects.append(prefix + ".evidence")
            continue
        if not isinstance(construction, dict) or not isinstance(meta, dict):
            defects.append(prefix + ".identity")
            continue
        for field, want in expected_meta.items():
            if meta.get(field) != want:
                defects.append(f"{prefix}.{field}")
        rendered = evidence.get("rendered_tokens")
        occupancy = evidence.get("occupancy_pct")
        if (construction.get("rendered_tokens") != rendered
                or not _is_int(rendered) or rendered <= 0
                or not _is_num(occupancy) or not math.isfinite(occupancy)
                or not 97.0 <= occupancy <= 100.0):
            defects.append(prefix + ".occupancy")
        if not ((gates or {}).get("occupancy") or {}).get("hard_pass") \
                or not ((gates or {}).get("placement") or {}).get("pass"):
            defects.append(prefix + ".gates")
    return defects


def geometry_coverage_defects(profile: dict, fixture: dict) -> list[str]:
    """Bind the declared geometry evidence to THIS fixture's required context
    units and re-validate each record with the unchanged M2 predicate
    (baseline.validate_preparation): byte-exact reconstruction, geometry
    re-derivation from the recorded token evidence, gates, and the retained
    tokenizer identity bound to this deployment. Also checks the CURRENT
    completion reserve against the qualified capacity for every recorded
    construction. Offline; no endpoint. Without a declared meter there is
    nothing to bind — an empty list lets the native/synthetic route prove
    geometry live before the first scored generation."""
    required = {task["id"]: task for task in fixture["tasks"]
                if "context_meter" in (task.get("requires") or [])}
    if not required:
        return []
    declaration = context_meter_declaration(profile)
    if declaration is None:
        return []
    reference = declaration.get("geometry_evidence")
    rows, error = _meter_json(str((reference or {}).get("path", ""))) \
        if isinstance(reference, dict) else (None, "missing")
    if error is not None or not isinstance(rows, list):
        return ["meter.geometry.records"]
    qualified = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("unit_id"), str):
            qualified.setdefault(row["unit_id"], row)
    defects = []
    from . import baseline
    capacity = profile["runtime"]["context_capacity"]
    for uid, task in sorted(required.items()):
        row = qualified.get(uid)
        if row is None:
            defects.append(f"meter.geometry.coverage: {uid} has no qualified native construction")
            continue
        prepared = row.get("prepared")
        evidence = row.get("evidence")
        if not isinstance(prepared, dict) or not isinstance(evidence, dict):
            defects.append(f"meter.geometry.coverage: {uid} record is incomplete")
            continue
        try:
            baseline.validate_preparation(profile, task, prepared, evidence)
        except CheckError as exc:
            defects.append(f"meter.geometry.validation: {uid}: {exc}")
            continue
        rendered = evidence.get("rendered_tokens")
        reserve = task_budget(profile, task)["max_tokens"]
        if _is_int(rendered) and rendered + reserve > capacity:
            defects.append(f"meter.geometry.capacity: {uid} rendered {rendered} plus "
                           f"generation reserve {reserve} exceeds qualified capacity {capacity}")
    return defects

# ---------------------------------------------------------------------------
# Profile validation (structural + internal-consistency, fail-closed)


def _fail(field: str, message: str) -> None:
    raise CheckError(f"{field}: {message}", field=field)


def _mapping(container: Any, field: str) -> dict:
    if not isinstance(container, dict):
        _fail(field, "must be a JSON object")
    return container


def _at(profile: dict, dotted: str) -> Any:
    cur: Any = profile
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _need(profile: dict, dotted: str, field: str | None = None) -> Any:
    value = _at(profile, dotted)
    if value is None:
        _fail(field or dotted, "required field missing")
    return value


def _nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(field, "must be a nonempty string")
    return value


def _abs_path(value: Any, field: str) -> str:
    _nonempty_str(value, field)
    if not value.startswith("/"):
        _fail(field, f"must be an absolute local path, got {value!r}")
    return value


def _hex64(value: Any, field: str) -> str:
    _nonempty_str(value, field)
    if not _HEX64.match(value):
        _fail(field, "must be a 64-char lowercase hex SHA-256")
    return value


def _int_at_least(value: Any, minimum: int, field: str) -> int:
    if not _is_int(value) or value < minimum:
        _fail(field, f"must be an integer >= {minimum}")
    return value


def _scan_reserved_controls(node: Any, path: str) -> None:
    """Reject reserved request keys anywhere inside reasoning.controls."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key in RESERVED_REQUEST_KEYS:
                _fail(
                    f"{path}.{key}",
                    f"profile control overrides reserved request key "
                    f"'{key}'; request identity, transcript, streaming, "
                    f"generation budget and sampling are runner-owned",
                )
            _scan_reserved_controls(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _scan_reserved_controls(item, f"{path}[{i}]")


def _validate_profile_id(profile: dict) -> None:
    profile_id = _nonempty_str(_need(profile, "profile_id"), "profile_id")
    if not _KEY_TOKEN.match(profile_id) or ".." in profile_id:
        _fail(
            "profile_id",
            "lowercase-hyphen convention; segments of [a-z0-9.]; got "
            f"{profile_id!r}",
        )
    model_key = _nonempty_str(_need(profile, "model.model_key"), "model.model_key")
    if not profile_id.startswith(model_key + "-"):
        _fail("profile_id", f"must start with model key {model_key!r}")
    arm = _need(profile, "reasoning.arm")
    arm_token = str(arm).lower().replace("_", "-")
    date_part = profile_id[-10:]
    try:
        datetime.strptime(date_part, "%Y-%m-%d")
    except ValueError:
        _fail("profile_id", "must end with a valid YYYY-MM-DD date")
    suffix = f"-{arm_token}-{date_part}"
    if not profile_id.endswith(suffix):
        _fail("profile_id", f"must end with {suffix!r} for reasoning.arm")
    device_backend = profile_id[len(model_key) + 1:-len(suffix)]
    if not device_backend:
        _fail("profile_id", "missing <device-backend> segment before reasoning arm")


def _validate_campaign_root(profile: dict) -> None:
    campaign_id = _nonempty_str(_need(profile, "campaign_id"), "campaign_id")
    if not _CAMPAIGN_ID.match(campaign_id):
        _fail("campaign_id", "lowercase-hyphen convention")
    root = _abs_path(_need(profile, "campaign_root"), "campaign_root")
    normalized = PurePosixPath(root)
    if normalized.name != campaign_id:
        _fail(
            "campaign_root",
            f"must be the full campaign directory ending in campaign_id "
            f"{campaign_id!r}, got {root!r}",
        )


def _validate_sampling(profile: dict) -> None:
    sampling = _mapping(_need(profile, "sampling"), "sampling")
    # sampling is spread into the request body: temperature/top_p/seed are
    # the legitimate sampler keys here; any other reserved request
    # identity/transcript/budget key is rejected offline (named).
    for key in sampling:
        if key in RESERVED_REQUEST_KEYS - {"temperature", "top_p", "seed"}:
            _fail(
                f"sampling.{key}",
                f"sampling overrides reserved request key '{key}'; request "
                f"identity, transcript, streaming and generation budget are "
                f"runner-owned (only temperature/top_p/seed are valid here)",
            )
    temperature = sampling.get("temperature")
    if not _is_num(temperature) or not (0.0 <= float(temperature) <= 2.0):
        _fail("sampling.temperature", "must be a number in [0, 2]")
    top_p = sampling.get("top_p")
    if not _is_num(top_p) or not (0.0 < float(top_p) <= 1.0):
        _fail("sampling.top_p", "must be a number in (0, 1]")
    seed = _need(profile, "sampling.seed")
    if not _is_int(seed):
        _fail("sampling.seed", "must be an integer")
    if not is_m2(profile) and not is_diagnostic(profile) and not is_calibration(profile) and seed != M1_SEED:
        _fail("sampling.seed", f"M1 methodology pins seed {M1_SEED}")
    if is_m2(profile) or is_diagnostic(profile) or is_calibration(profile) or float(temperature) != DEFAULT_TEMPERATURE or float(top_p) != DEFAULT_TOP_P:
        # Deviations from methodology defaults require recorded qualification
        # support: an explicit source path inside the sampling record.
        source = sampling.get("qualification_source")
        if not isinstance(source, str) or not source.startswith("/"):
            _fail(
                "sampling.qualification_source",
                f"sampling deviates from the methodology defaults "
                f"({DEFAULT_TEMPERATURE}/{DEFAULT_TOP_P}); an absolute "
                f"qualification_source path recording that deviation is "
                f"required",
            )


def _validate_budgets(profile: dict) -> None:
    import math

    budgets = _mapping(_need(profile, "budgets"), "budgets")
    _int_at_least(budgets.get("max_tokens"), 1, "budgets.max_tokens")
    timeout = budgets.get("timeout_seconds")
    if (
        not _is_num(timeout)
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        _fail(
            "budgets.timeout_seconds",
            "must be a finite number > 0 (NaN/Infinity rejected)",
        )
    source = budgets.get("qualification_source")
    _nonempty_str(source, "budgets.qualification_source")
    if source.strip().lower() in FORBIDDEN_BUDGET_SOURCES:
        _fail(
            "budgets.qualification_source",
            "fixture answer_budget/generation_budget is an answer allowance, "
            "never a preselected generation-budget source",
        )
    note = budgets.get("note")
    _nonempty_str(note, "budgets.note")
    overrides = budgets.get("by_category", {})
    if not isinstance(overrides, dict) or (overrides and not is_m2(profile)):
        _fail("budgets.by_category", "M2 category budget object required")
    for category, values in overrides.items():
        if not isinstance(category, str) or not isinstance(values, dict):
            _fail("budgets.by_category", "category names map to budget objects")
        if set(values) - {"max_tokens", "timeout_seconds"}:
            _fail("budgets.by_category", "only token and time limits may be overridden")
        if "max_tokens" in values:
            _int_at_least(values["max_tokens"], 1, "budgets.by_category.max_tokens")
        seconds = values.get("timeout_seconds", timeout)
        if not _is_num(seconds) or not math.isfinite(seconds) or seconds <= 0:
            _fail("budgets.by_category.timeout_seconds", "finite positive deadline required")


def task_budget(profile: dict, task: dict) -> dict:
    """Fixed qualified category budget; no data-dependent ceiling changes."""
    budgets = dict(profile["budgets"])
    overrides = budgets.get("by_category", {}).get(task.get("category"), {})
    budgets.update(overrides)
    return budgets


def _validate_serve(profile: dict) -> None:
    serve = _mapping(_need(profile, "runtime.serve"), "runtime.serve")
    endpoint = _nonempty_str(serve.get("endpoint"), "runtime.serve.endpoint")
    _validate_local_endpoint(endpoint)
    _nonempty_str(serve.get("model_id"), "runtime.serve.model_id")
    echo_path = _nonempty_str(serve.get("echo_path"), "runtime.serve.echo_path")
    if not echo_path.startswith("/") or echo_path.startswith("//"):
        _fail(
            "runtime.serve.echo_path",
            "must be an absolute endpoint-relative path beginning with '/'",
        )
    if any(c in echo_path for c in "?# \t\r\n"):
        _fail("runtime.serve.echo_path", "must be a plain path without query/fragment/whitespace")


def _validate_local_endpoint(endpoint: str) -> None:
    from urllib.parse import urlsplit

    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https"):
        _fail("runtime.serve.endpoint", f"scheme must be http/https, got {endpoint!r}")
    host = (parts.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        _fail(
            "runtime.serve.endpoint",
            f"local (loopback) endpoints only, got host {host!r}",
        )
    if "@" in parts.netloc:
        _fail("runtime.serve.endpoint", "userinfo is not allowed in the endpoint")
    if parts.query or parts.fragment:
        _fail("runtime.serve.endpoint", "query/fragment not allowed in the endpoint")


def validate_profile(profile: dict) -> None:
    """Full structural + internal-consistency validation. Raises CheckError
    naming the offending field on the first defect; returns None when valid.

    Known framework/methodology pairs are checked together. M1 remains the
    accepted reliability slice; M2 fixes the complete Model inventory.
    SOFTWARE_TEST requires full structure and artifact; REAL_MODEL also
    requires hardware evidence and qualification provenance.
    """
    _mapping(profile, "profile")
    schema_version = _need(profile, "schema_version")
    if not _is_int(schema_version) or schema_version != SCHEMA_VERSION:
        _fail("schema_version", f"must be {SCHEMA_VERSION}")

    framework = _mapping(_need(profile, "framework"), "framework")
    version = _nonempty_str(framework.get("version"), "framework.version")
    methodology = _nonempty_str(framework.get("methodology"), "framework.methodology")
    if (version, methodology) not in (
        (FRAMEWORK, METHODOLOGY), (FRAMEWORK_M2, METHODOLOGY_M2),
        (FRAMEWORK_M2, METHODOLOGY_DIAGNOSTIC), (FRAMEWORK_M2, METHODOLOGY_CALIBRATION)
    ):
        _fail("framework.version", "unknown framework/methodology pair")

    evidence_kind = _nonempty_str(_need(profile, "evidence_kind"), "evidence_kind")
    if evidence_kind not in EVIDENCE_KINDS:
        _fail("evidence_kind", f"must be one of {EVIDENCE_KINDS}")
    real = evidence_kind == "REAL_MODEL"
    if (is_diagnostic(profile) != (evidence_kind == "TECHNICAL_DIAGNOSTIC")):
        _fail("evidence_kind", "technical diagnostics require their disjoint methodology/evidence kind")
    if evidence_kind == "CALIBRATION" and not is_calibration(profile):
        _fail("evidence_kind", "calibration evidence requires its disjoint methodology")
    if is_calibration(profile) and evidence_kind not in ("CALIBRATION", "SOFTWARE_TEST"):
        _fail("evidence_kind", "calibration cannot supply Model science or protocol diagnostics")

    _validate_profile_id(profile)
    _validate_campaign_root(profile)

    model = _mapping(_need(profile, "model"), "model")
    model_key = _nonempty_str(model.get("model_key"), "model.model_key")
    if not _KEY_TOKEN.match(model_key) or ".." in model_key:
        _fail("model.model_key", "lowercase key token ([a-z0-9.-])")
    artifact = _mapping(_need(profile, "model.artifact"), "model.artifact")
    _abs_path(artifact.get("path"), "model.artifact.path")
    _nonempty_str(artifact.get("format"), "model.artifact.format")
    _nonempty_str(artifact.get("revision"), "model.artifact.revision")
    _hex64(artifact.get("sha256"), "model.artifact.sha256")
    template = _mapping(
        _need(profile, "model.tokenizer_chat_template"),
        "model.tokenizer_chat_template",
    )
    _nonempty_str(template.get("source"), "model.tokenizer_chat_template.source")
    _hex64(
        template.get("sha256"), "model.tokenizer_chat_template.sha256"
    )
    template_path = template.get("path")
    if template_path is not None:
        _abs_path(template_path, "model.tokenizer_chat_template.path")

    runtime = _mapping(_need(profile, "runtime"), "runtime")
    engine = _mapping(_need(profile, "runtime.engine"), "runtime.engine")
    _nonempty_str(engine.get("name"), "runtime.engine.name")
    _nonempty_str(engine.get("version"), "runtime.engine.version")
    # Supplied deployment condition, reported verbatim (SPEC §3.1); never an
    # admission vocabulary. Only a nonempty recorded identity is required.
    _nonempty_str(_need(profile, "runtime.backend"), "runtime.backend")
    _validate_serve(profile)
    _int_at_least(
        _need(profile, "runtime.context_capacity"), 1, "runtime.context_capacity"
    )

    # Hardware, transport and owner qualification records are supplied conditions,
    # not an OS/process attestation contract. Preserve them without launch gates.
    for key in ("hardware", "deployment", "qualification", "environment"):
        if key in profile and not isinstance(profile[key], dict):
            _fail(key, "optional condition metadata must be an object")

    reasoning = _mapping(_need(profile, "reasoning"), "reasoning")
    arm = _nonempty_str(reasoning.get("arm"), "reasoning.arm")
    if arm not in REASONING_ARMS:
        _fail("reasoning.arm", f"must be one of {REASONING_ARMS}")
    controls = reasoning.get("controls")
    if controls is None:
        _fail("reasoning.controls", "required (may be an empty object)")
    if not isinstance(controls, dict):
        _fail("reasoning.controls", "must be a JSON object")
    _scan_reserved_controls(controls, "reasoning.controls")

    _validate_sampling(profile)
    for key in set(controls) & set(profile["sampling"]):
        if key != "qualification_source":
            _fail(f"reasoning.controls.{key}", "cannot override a fixed sampler parameter")

    context = _mapping(_need(profile, "context"), "context")
    target = _int_at_least(context.get("target"), 1, "context.target")
    capacity = _need(profile, "runtime.context_capacity")
    if target > capacity:
        _fail(
            "context.target",
            f"context target {target} exceeds runtime.context_capacity "
            f"{capacity}",
        )

    _validate_budgets(profile)

    capabilities = profile.get("capabilities")
    if capabilities is not None:
        _mapping(capabilities, "capabilities")
        meter = capabilities.get("context_meter")
        if isinstance(meter, dict):
            if evidence_kind != "REAL_MODEL":
                _fail("capabilities.context_meter",
                      "a declared generic context meter requires REAL_MODEL evidence")
            _validate_meter_declaration(meter)
    coverage = profile.get("coverage")
    if coverage is not None:
        _mapping(coverage, "coverage")
        if coverage.get("requirement", "partial") not in COVERAGE_REQUIREMENTS:
            _fail("coverage.requirement", f"must be one of {COVERAGE_REQUIREMENTS}")



# ---------------------------------------------------------------------------
# Serving-endpoint admission echo (single authority; used by preflight.online
# and by offline report validation of the SAVED observed echo)


#: Exact-echo contract; native llama.cpp uses observed /props below.
ECHO_FIELDS = (
    "artifact_sha256",
    "engine",
    "backend",
    "device",
    "sampling",
    "reasoning",
    "context_capacity",
    "serve_sha256",
)


def sampling_settings(profile: dict) -> dict:
    """Actual sampler parameters; qualification provenance is not an API parameter."""
    validate_profile(profile)
    return {key: value for key, value in profile["sampling"].items()
            if key != "qualification_source"}


def expected_echo(profile: dict) -> dict:
    """The canonical expected admission echo for ``profile``: exact values
    the serving stack must return. Fields the profile does not carry
    (hardware.device on a SOFTWARE_TEST profile) are omitted."""
    validate_profile(profile)
    expected: dict = {
        "artifact_sha256": profile["model"]["artifact"]["sha256"],
        "serve_sha256": profile["runtime"]["serve"].get("sha256"),
        "backend": profile["runtime"]["backend"],
        "engine": {
            "name": profile["runtime"]["engine"]["name"],
            "version": profile["runtime"]["engine"]["version"],
        },
        "sampling": sampling_settings(profile),
        "reasoning": {
            "arm": profile["reasoning"]["arm"],
            "controls": profile["reasoning"]["controls"],
        },
        "context_capacity": profile["runtime"]["context_capacity"],
    }
    device = (profile.get("hardware") or {}).get("device")
    if device:
        expected["device"] = {
            "name": device["name"],
            "pci_id": device["pci_id"],
            "driver_version": device["driver_version"],
        }
    return expected


ADMISSION_VERSION = "scientific-protocol/1"
ATTEMPT_ACCOUNTING = "generation-dispatch/1"


def scientific_configuration(profile: dict) -> dict:
    """Conditions which must remain compatible within one scientific sample.

    Full supplied profiles are retained separately. Paths, server incarnations,
    OS/build versions and transport binaries are not scientific identities.
    The GPU backend is a supplied deployment condition per
    SPEC §3.2 (recorded verbatim, e.g. CUDA/HIP/Vulkan/CPU/Metal) — it is
    recorded in the profile, bound into every attempt's
    profile-revision digest and reported in the conditions annex, but it is
    not one of §3.3's material scientific identities (artifact, template,
    reasoning, samplers, context, interfaces, budgets).
    """
    artifact = profile["model"]["artifact"]
    budgets = profile["budgets"]
    return {
        "framework": profile["framework"], "evidence_kind": profile["evidence_kind"],
        "model_key": profile["model"]["model_key"],
        "artifact": {key: artifact.get(key) for key in ("sha256", "format", "revision", "quantization")},
        "template_sha256": profile["model"]["tokenizer_chat_template"]["sha256"],
        "engine": profile["runtime"]["engine"]["name"],
        "model_id": profile["runtime"]["serve"]["model_id"],
        "context_capacity": profile["runtime"]["context_capacity"],
        "context": profile["context"], "reasoning": profile["reasoning"],
        "sampling": sampling_settings(profile),
        "coverage": {"requirement": coverage_requirement(profile)},
        "budgets": {key: budgets[key] for key in ("max_tokens", "timeout_seconds", "by_category") if key in budgets},
        "capabilities": profile.get("capabilities", {}),
    }


def compatible_profiles(left: dict, right: dict) -> bool:
    return scientific_configuration(left) == scientific_configuration(right)


def recorded_profile(config: dict, conditions: dict) -> dict:
    """Check attribution against the actual, hash-bound attempt conditions."""
    profile = conditions.get("profile", config["profile"])
    if (conditions.get("profile_revision") != digest(profile)
            or not compatible_profiles(profile, config["profile"])):
        raise CheckError("evidence.profile_revision: incompatible or changed attempt conditions")
    return profile


def _generic_meter_defects(profile: dict, echo: object) -> list[str]:
    """Generic qualified-meter route checks on the OBSERVED (or saved) echo.

    Template-agnostic by contract: no reasoning markup is forced (model-native
    reasoning representation is the qualification's business — the historical
    llama.cpp ``<think>`` suffix checks stay untouched on their own route).
    Verified here: the live adapter echo's retained NATIVE template identity,
    the NATIVE context geometry, the probe echo identity, real token IDs,
    render/tokenize determinism, and the LIVE REPLAY of every retained
    qualification witness — each original witness request re-serialized
    through the live meter must reproduce the count that the offline
    verification bound to that request's original native response. The same
    predicate runs at admission and offline finalization over the saved echo."""
    defects = []

    def check(name, ok):
        if not ok:
            defects.append("serve.meter." + name)

    if not isinstance(echo, dict):
        return ["serve.meter.body"]
    configuration = echo.get("configuration")
    probe = echo.get("meter_probe")
    if not isinstance(configuration, dict) or not isinstance(probe, dict):
        return ["serve.meter.observations.missing"]
    native_props = configuration.get("native_props")
    settings = (native_props or {}).get("default_generation_settings") if \
        isinstance(native_props, dict) else None
    check("template.identity", isinstance(native_props, dict)
          and isinstance(native_props.get("chat_template"), str)
          and hashlib.sha256(native_props["chat_template"].encode()).hexdigest() ==
          profile["model"]["tokenizer_chat_template"]["sha256"])
    check("context.geometry", isinstance(settings, dict)
          and type(settings.get("n_ctx")) is int
          and settings["n_ctx"] == profile["runtime"]["context_capacity"])
    expected_request = {"messages": [{"role": "user",
                                      "content": "WELP preflight template rendering only."}],
                        **profile["reasoning"]["controls"]}
    prompt = (probe.get("render_response") or {}).get("prompt")
    tokens = (probe.get("tokenize_response") or {}).get("tokens")
    check("render.echo", probe.get("request") == expected_request
          and isinstance(prompt, str) and bool(prompt))
    check("tokenize", isinstance(tokens, list) and bool(tokens)
          and all(type(token) is int for token in tokens)
          and probe.get("tokenize_request") == {"content": prompt,
                                                "add_special": True, "parse_special": True})
    repeat_prompt = (probe.get("repeat_render_response") or {}).get("prompt")
    repeat_tokens = (probe.get("repeat_tokenize_response") or {}).get("tokens")
    check("determinism", probe.get("repeat_render_response") is not None
          and probe.get("repeat_tokenize_response") is not None
          and repeat_prompt == prompt and repeat_tokens == tokens)
    witnesses = (context_meter_declaration(profile) or {}).get("witnesses") or []
    replay = probe.get("witness_replay")
    check("witness.replay", isinstance(replay, list) and len(replay) == len(witnesses))
    if isinstance(replay, list):
        declared = {w.get("name"): w for w in witnesses if isinstance(w, dict)}
        seen = set()
        for row in replay:
            if not isinstance(row, dict):
                check("witness.replay.row", False)
                continue
            name = row.get("name") if isinstance(row.get("name"), str) else None
            seen.add(name)
            witness = declared.get(name)
            row_prompt = (row.get("render_response") or {}).get("prompt")
            row_tokens = (row.get("tokenize_response") or {}).get("tokens")
            check(f"witness.replay.{name}", witness is not None
                  and row.get("request_sha256") == (witness.get("request") or {}).get("sha256")
                  and isinstance(row_prompt, str) and bool(row_prompt)
                  and isinstance(row_tokens, list) and bool(row_tokens)
                  and all(type(token) is int for token in row_tokens)
                  and row.get("tokenize_request") == {"content": row_prompt,
                                                      "add_special": True, "parse_special": True}
                  and row.get("live_tokens") == witness.get("meter_tokens"))
        check("witness.replay.names", seen == set(declared))
    return defects


def protocol_defects(profile: dict, echo: object) -> list[str]:
    """Scientific endpoint checks only; never claim independent GPU attestation."""
    if not isinstance(echo, dict) or echo.get("admission_version") != ADMISSION_VERSION:
        return ["serve.protocol.observation"]
    native = profile["runtime"]["engine"]["name"] == "llama.cpp"
    if context_meter_declaration(profile) is not None:
        # Declared generic qualified meter: this route applies to ANY engine
        # (llama.cpp included when the operator declares a meter) and checks
        # model-native reasoning representation — no forced markup.
        observed = echo.get("configuration")
        expected = expected_echo(profile)
        keys = ("artifact_sha256", "sampling", "reasoning", "context_capacity")
        defects = ["serve.echo." + key for key in keys
                   if not isinstance(observed, dict) or observed.get(key) != expected[key]]
        defects.extend(_generic_meter_defects(profile, echo))
        return defects
    if not native:
        observed = echo.get("configuration")
        expected = expected_echo(profile)
        keys = ("artifact_sha256", "sampling", "reasoning", "context_capacity")
        return ["serve.echo." + key for key in keys
                if not isinstance(observed, dict) or observed.get(key) != expected[key]]
    props, probe = echo.get("props"), echo.get("template_probe")
    if not isinstance(props, dict) or not isinstance(probe, dict):
        return ["serve.native.observations.missing"]
    defects = []
    def check(name, ok):
        if not ok:
            defects.append("serve.native." + name)
    serve = profile["runtime"]["serve"]
    model_id = serve["model_id"]
    check("model.identity", model_id in (props.get("model_alias"), props.get("model_path")))
    template = props.get("chat_template")
    check("template.identity", isinstance(template, str) and
          hashlib.sha256(template.encode()).hexdigest() == profile["model"]["tokenizer_chat_template"]["sha256"])
    settings = props.get("default_generation_settings") or {}
    check("context", settings.get("n_ctx") == profile["runtime"]["context_capacity"])
    params = settings.get("params") or {}
    for key, want in sampling_settings(profile).items():
        got = params.get(key)
        check("sampling." + key,
              type(got) is int and got == want if type(want) is int else
              type(got) in (int, float) and type(want) in (int, float)
              and math.isclose(got, want, rel_tol=0, abs_tol=1e-7))
    expected_probe = {"messages": [{"role": "user", "content": "WELP preflight template rendering only."}],
                      **profile["reasoning"]["controls"]}
    prompt = (probe.get("response") or {}).get("prompt")
    arm = profile["reasoning"]["arm"]
    suffix = "<think>\n" if arm == "ON" else "<think>\n\n</think>\n\n"
    check("reasoning", probe.get("request") == expected_probe and isinstance(prompt, str)
          and (arm not in ("ON", "OFF") or prompt.endswith(suffix)))
    tokens = (echo.get("tokenizer_probe") or {}).get("tokens")
    check("tokenizer", isinstance(tokens, list) and bool(tokens)
          and all(type(token) is int for token in tokens))
    return defects

def _native_llama_defects(profile: dict, echo: object) -> list[str]:
    """Validate saved native /props, template rendering and local process facts.

    These are separately attributed observations, not a fabricated server echo.
    The same predicate runs at admission and offline finalization.
    """
    defects = []

    def check(name, ok):
        if not ok:
            defects.append("serve.native." + name)

    if not isinstance(echo, dict):
        return ["serve.native.body"]
    props = echo.get("props")
    proc = echo.get("process")
    probe = echo.get("template_probe")
    if not all(isinstance(x, dict) for x in (props, proc, probe)):
        return ["serve.native.observations.missing"]
    engine = profile["runtime"]["engine"]
    serve = profile["runtime"]["serve"]
    check("engine.identity", bool(engine.get("path")) and
          bool(re.fullmatch(r"[0-9a-f]{64}", str(engine.get("sha256", "")))) and
          proc.get("executable") == engine.get("path") and
          proc.get("executable_sha256") == engine.get("sha256") and
          props.get("build_info") == engine["version"])
    check("process.pid", proc.get("pid") == serve.get("pid") and serve.get("pid") is not None)
    try:
        argv = shlex.split(serve["command"])
    except ValueError:
        argv = []
    check("process.command", bool(argv) and proc.get("argv") == argv and
          argv[0] == engine.get("path"))
    model_path = (profile["deployment"]["model_path"] if "deployment" in profile
                  else profile["model"]["artifact"]["path"])
    check("model.path", props.get("model_path") == model_path and
          (serve["model_id"] == model_path or (
              "deployment" in profile and serve["model_id"] == props.get("model_alias"))))
    template = props.get("chat_template")
    check("template.identity", isinstance(template, str) and
          hashlib.sha256(template.encode()).hexdigest() ==
          profile["model"]["tokenizer_chat_template"]["sha256"])
    settings = props.get("default_generation_settings") or {}
    check("context", isinstance(settings, dict) and
          type(settings.get("n_ctx")) is int and
          settings["n_ctx"] == profile["runtime"]["context_capacity"] and
          props.get("total_slots") == 1)
    params = settings.get("params", {}) if isinstance(settings, dict) else {}
    for key, want in sampling_settings(profile).items():
        got = params.get(key) if isinstance(params, dict) else None
        # llama.cpp serializes float32 sampler values; seed/integer identity is exact.
        ok = (type(got) is int and got == want) if type(want) is int else (
            type(got) in (float, int) and type(want) in (float, int) and
            math.isclose(got, want, rel_tol=0, abs_tol=1e-7))
        check("sampling." + key, ok)
    arm = profile["reasoning"]["arm"]
    controls = {"chat_template_kwargs": {"enable_thinking": arm == "ON"}}
    expected_probe = {"messages": [{"role": "user",
                                    "content": "WELP preflight template rendering only."}],
                      **controls}
    rendered = probe.get("response", {})
    prompt = rendered.get("prompt") if isinstance(rendered, dict) else None
    suffix = "<think>\n" if arm == "ON" else "<think>\n\n</think>\n\n"
    check("reasoning", arm in ("ON", "OFF") and
          profile["reasoning"]["controls"] == controls and
          probe.get("request") == expected_probe and isinstance(prompt, str) and
          prompt.endswith(suffix) and "--jinja" in argv and
          any(argv[i:i+2] == ["--reasoning", arm.lower()] for i in range(len(argv))))
    port = 8088 if "deployment" in profile else urlsplit(serve["endpoint"]).port
    listeners = proc.get("listeners", [])
    check("endpoint.owner", isinstance(listeners, list) and any(
        isinstance(row, dict) and row.get("local_address") ==
        f"0100007F:{port:04X}" and row.get("state") == "0A"
        for row in listeners) if port is not None else False)
    libraries = proc.get("backend_libraries", [])
    if "deployment" in profile:
        check("remote", not remote_observation_defects(profile, echo.get("deployment"), full=True))
        check("remote.process", proc == ((echo.get("deployment") or {}).get("remote") or {}).get("process"))
        remote_props = ((echo.get("deployment") or {}).get("remote") or {}).get("props", {})
        check("remote.props", all(props.get(k) == remote_props.get(k) for k in (
            "build_info", "model_path", "model_alias", "chat_template", "total_slots",
            "default_generation_settings")))
    else:
        check("backend", profile["runtime"]["backend"] == "HIP" and
              isinstance(libraries, list) and any(
                  isinstance(p, str) and Path(p).parent == Path(engine.get("path", "")).parent and
                  Path(p).name.startswith("libggml-hip.so") for p in libraries))
    return defects


def remote_observation_defects(profile: dict, observation: object, *, full=False) -> list[str]:
    """Shared live/offline remote attribution and safety predicates, not approvals."""
    if not isinstance(observation, dict):
        return ["deployment.observation.missing"]
    defects = []

    def check(name, ok):
        if not ok:
            defects.append("deployment." + name)

    d = profile["deployment"]
    remote = observation.get("remote") or {}
    if (not isinstance(remote, dict) or not isinstance(observation.get("tunnel"), dict) or
            not isinstance(remote.get("process"), dict) or not isinstance(remote.get("model"), dict) or
            not isinstance(remote.get("host"), dict) or any(
                not isinstance(remote.get(key), list) or
                any(not isinstance(row, dict) for row in remote[key])
                for key in ("devices", "compute_processes", "kernel"))):
        return ["deployment.observation.schema"]
    proc = remote.get("process") or {}
    tunnel = observation.get("tunnel") or {}
    check("hosts", observation.get("execution_host") == d["execution_host"] and
          remote.get("hostname") == d["inference_host"] and
          remote.get("boot_id_sha256") == d["boot_id_sha256"] and
          remote.get("uid") == d["remote_uid"])
    start, end = (observation.get(k) for k in ("requested_at", "received_at"))
    measured = remote.get("observed_at")
    check("freshness", all(_is_num(x) and math.isfinite(x) for x in (start, end, measured)) and
          0 <= end - start <= 120 and start - 5 <= measured <= end + 5)
    nonce = observation.get("nonce")
    check("collector", observation.get("collector") == "authenticated-ssh/1" and
          isinstance(nonce, str) and len(nonce) == 48 and remote.get("nonce") == nonce)
    check("tunnel.identity", tunnel.get("pid") == d["tunnel"]["pid"] and
          tunnel.get("start_ticks") == d["tunnel"]["start_ticks"] and
          tunnel.get("uid") == 1000 and tunnel.get("executable") == "/usr/bin/ssh" and
          tunnel.get("executable_sha256") == d["ssh_sha256"] and
          tunnel.get("argv") == forward_argv(d))
    check("tunnel.listener", any(row.get("local_address") == "0100007F:4A1E" and
          row.get("state") == "0A" for row in tunnel.get("listeners", []) if isinstance(row, dict)))
    engine, serve = profile["runtime"]["engine"], profile["runtime"]["serve"]
    check("server.identity", proc.get("pid") == serve["pid"] and
          proc.get("start_ticks") == d["server_start_ticks"] and
          proc.get("uid") == d["remote_uid"] and proc.get("executable") == engine["path"] and
          proc.get("executable_sha256") == engine["sha256"] and
          proc.get("argv") == shlex.split(serve["command"]))
    check("server.listener", any(row.get("local_address") == "0100007F:1F98" and
          row.get("state") == "0A" for row in proc.get("listeners", []) if isinstance(row, dict)))
    libs = proc.get("library_sha256", {})
    check("libraries", isinstance(libs, dict) and bool(libs) and
          any(Path(p).name == "libggml-cuda.so.0.27.0" for p in libs) and
          any(Path(p).name == "libllama-server-impl.so" for p in libs) and
          all(Path(p).parent == Path(engine["path"]).parent and
              d["library_sha256"].get(p) == sha for p, sha in libs.items()) and
          all(not Path(p).name.startswith("libggml") or Path(p).name.endswith(".0.27.0")
              for p in libs) and
          sorted(libs) == sorted(proc.get("backend_libraries", [])))
    model = remote.get("model") or {}
    check("model.identity", model.get("path") == d["model_path"] and model.get("mapped") is True and
          model.get("stat") == d["model_stat"] and
          (not full or model.get("sha256") == profile["model"]["artifact"]["sha256"]))
    pci = profile["hardware"]["device"]["pci_id"]
    devices = remote.get("devices", [])
    gpu = next((x for x in devices if x.get("pci_id") == pci), {}) if isinstance(devices, list) else {}
    check("gpu.identity", gpu.get("name") == profile["hardware"]["device"]["name"] and
          gpu.get("driver_version") == profile["hardware"]["device"]["driver_version"] and
          pci == "0000:0a:00.0" and proc.get("cuda_visible_device_pci") == pci and
          proc.get("ptx_jit_disabled") is True)
    check("gpu.safety", gpu.get("power_limit_w") == 200 and gpu.get("enforced_power_limit_w") == 200 and
          _is_num(gpu.get("temperature_c")) and gpu["temperature_c"] < 80 and
          _is_int(gpu.get("vram_free_bytes")) and gpu["vram_free_bytes"] > 256 << 20)
    compute = remote.get("compute_processes")
    check("gpu.owner", isinstance(compute, list) and
          any(x.get("pid") == serve["pid"] and x.get("pci_id") == pci for x in compute) and
          all((x.get("pci_id") != pci or x.get("pid") == serve["pid"]) and
              (x.get("pid") != serve["pid"] or x.get("pci_id") == pci) for x in compute))
    host = remote.get("host") or {}
    check("host.memory", _is_int(host.get("mem_available_bytes")) and
          host["mem_available_bytes"] >= 2 << 30)
    kernel = remote.get("kernel")
    check("kernel", isinstance(kernel, list) and not any(
          re.search(r"NV_ERR|NVRM.*Xid|GPU.*reset|fallen off|out of memory|oom.kill|page allocation failure",
                    str(x.get("message", "")), re.I) for x in kernel))
    return defects



def echo_defects(profile: dict, echo: object) -> list[str]:
    """Named defects in an OBSERVED echo versus the profile. Extra unknown
    keys in the echo body are tolerated (only the eight identity fields are
    compared); compared sub-objects must match exactly. Defect names look
    like ``serve.echo.<field>.missing`` / ``serve.echo.<field>.mismatch``.
    Empty list == valid echo."""
    if isinstance(echo, dict) and echo.get("admission_version") == ADMISSION_VERSION:
        return protocol_defects(profile, echo)
    if (profile["runtime"]["engine"]["name"] == "llama.cpp" and
            profile["runtime"]["serve"]["echo_path"] == "/props"):
        return _native_llama_defects(profile, echo)
    expected = expected_echo(profile)
    if not isinstance(echo, dict):
        return ["serve.echo.body.not_object"]
    defects: list[str] = []
    for field in ECHO_FIELDS:
        if field not in expected:
            continue
        want = expected[field]
        if field not in echo:
            defects.append(f"serve.echo.{field}.missing")
            continue
        got = echo[field]
        if field == "context_capacity":
            ok = isinstance(got, int) and not isinstance(got, bool) and got == want
        elif isinstance(want, dict):
            ok = isinstance(got, dict) and got == want
        else:
            ok = isinstance(got, str) and got == want
        if not ok:
            defects.append(f"serve.echo.{field}.mismatch")
    return defects


def validate_echo(profile: dict, echo: object) -> None:
    """Fail-closed echo validation against ``profile``.

    Two consumers, one authority: (1) preflight.online on the genuinely
    observed HTTP echo before anything is admitted; (2) offline report
    validation re-checking the SAVED admission echo (conditions.preflight /
    admission['echo']) against the pinned profile — no endpoint contact.
    Raises CheckError naming every defect; returns None when the echo
    matches exactly."""
    defects = echo_defects(profile, echo)
    if defects:
        raise CheckError(
            "admission echo invalid: " + ", ".join(defects), field=defects[0]
        )


# ---------------------------------------------------------------------------
# Facet → outcome derivation (SPEC §5.1; derived ONCE, here)


def _check_facet(value: Any, vocab: tuple[str, ...], field: str) -> str:
    if not isinstance(value, str) or value not in vocab:
        _fail(field, f"must be one of {vocab}")
    return value


def derive_outcome(execution: str, completion: str, scoring: str, limits: str) -> dict:
    """Derive the single primary outcome from the four recorded facets.

    Enforcement rules (fail-closed, CheckError on violation):
      * facets must use the exact §5.1 vocabularies;
      * limits=HOST forces execution=INVALID (host exhaustion is never a
        model measurement) — a contradictory pair is rejected;
      * execution=NOT_RUN requires the inert completion/scoring/limits
        values (NOT_APPLICABLE/NOT_APPLICABLE/NONE).

    Derivation: INVALID→INVALID/EXECUTION_FAILURE; NOT_RUN→NOT_RUN/NOT_RUN;
    VALID + COMPLETE + SCORED_FAIL→FAIL requires a complete substantive
    answer validly judged incorrect. Incomplete answers cannot carry
    SCORED_PASS/SCORED_FAIL. Budget/ceiling exhaustion with an incomplete
    answer is NOT_EVALUABLE; a complete subjective unjudged answer is
    RUBRIC_INDETERMINATE; an empty answer is UNSCORABLE_ANSWER.
    reason=None.
    """
    execution = _check_facet(execution, EXECUTION_FACETS, "execution")
    completion = _check_facet(completion, COMPLETION_FACETS, "completion")
    scoring = _check_facet(scoring, SCORING_FACETS, "scoring")
    limits = _check_facet(limits, LIMITS_FACETS, "limits")

    if limits == "HOST" and execution != "INVALID":
        _fail(
            "execution",
            "limits=HOST forces execution=INVALID; recorded facets "
            f"contradict ({execution=})",
        )
    if execution == "NOT_RUN" and (
        completion != "NOT_APPLICABLE" or scoring != "NOT_APPLICABLE" or limits != "NONE"
    ):
        _fail(
            "execution",
            "NOT_RUN requires inert facets "
            "(completion=NOT_APPLICABLE, scoring=NOT_APPLICABLE, limits=NONE)",
        )

    result = {
        "execution": execution,
        "completion": completion,
        "scoring": scoring,
        "limits": limits,
    }

    if execution == "INVALID":
        result["outcome"] = "INVALID"
        result["reason"] = "EXECUTION_FAILURE"
        return result
    if execution == "NOT_RUN":
        result["outcome"] = "NOT_RUN"
        result["reason"] = "NOT_RUN"
        return result

    # execution == VALID
    if limits == "CEILING":
        if completion == "INCOMPLETE" and scoring == "NOT_SCOREABLE":
            result["outcome"] = "NOT_EVALUABLE"
            result["reason"] = "CEILING_EXHAUSTED"
            return result
        _fail("limits", "CEILING requires completion=INCOMPLETE, scoring=NOT_SCOREABLE")
    if completion == "COMPLETE" and scoring in ("SCORED_PASS", "SCORED_FAIL"):
        result["outcome"] = "PASS" if scoring == "SCORED_PASS" else "FAIL"
        result["reason"] = None
        return result
    if completion == "INCOMPLETE" and scoring in ("SCORED_PASS", "SCORED_FAIL"):
        _fail("facets", "incomplete task cannot carry a completed correctness judgment")
    if completion == "INCOMPLETE" and scoring == "NOT_SCOREABLE":
        if limits == "BUDGET":
            result["outcome"] = "NOT_EVALUABLE"
            result["reason"] = "BUDGET_LIMITED"
        elif limits == "NONE":
            result["outcome"] = "NOT_EVALUABLE"
            result["reason"] = "UNSCORABLE_ANSWER"
        else:  # limits == "HOST" handled above
            result["outcome"] = "NOT_EVALUABLE"
            result["reason"] = "UNSCORABLE_ANSWER"
        return result
    if completion == "COMPLETE" and scoring == "NOT_SCOREABLE":
        result["outcome"] = "NOT_EVALUABLE"
        result["reason"] = "RUBRIC_INDETERMINATE"
        return result
    _fail(
        "facets",
        f"unsupported facet combination for the M1 methodology: "
        f"execution={execution}, completion={completion}, scoring={scoring}, "
        f"limits={limits}",
    )


# ---------------------------------------------------------------------------
# Attempt resolution / unit / section state


def _row_outcome(row: dict) -> str | None:
    outcome = row.get("outcome")
    if outcome is None:
        score = row.get("score")
        if isinstance(score, dict):
            outcome = score.get("outcome")
    return outcome if isinstance(outcome, str) else None


def resolved_attempt(attempts: list[dict]) -> dict | None:
    """Fixed precedence: the LAST finalized attempt whose outcome is a VALID
    execution (PASS/FAIL/NOT_EVALUABLE — a legitimate negative is never
    rerun); otherwise the LAST finalized INVALID attempt; otherwise None.
    Rows with finalized=False (in-flight interruptions) are ignored — they
    are provenance, never resolution input."""
    last_valid: dict | None = None
    last_invalid: dict | None = None
    for row in attempts:
        if not isinstance(row, dict) or row.get("finalized") is not True:
            continue
        outcome = _row_outcome(row)
        if outcome in VALID_OUTCOMES:
            last_valid = row
        elif outcome == "INVALID":
            last_invalid = row
    return last_valid if last_valid is not None else last_invalid


def unit_pending(attempts: list[dict]) -> bool:
    """True while the unit still owes execution: no finalized VALID attempt
    and fewer than MAX_ATTEMPTS finalized INVALID attempts. In-flight
    (non-finalized) rows are ignored for the count — an interrupted in-flight
    attempt may be retried without charging the invalid-attempt bound; all
    attempts remain recorded."""
    if not isinstance(attempts, list):
        _fail("attempts", "must be a list of attempt rows")
    valid = False
    invalid = 0
    for row in attempts:
        if not isinstance(row, dict) or row.get("finalized") is not True:
            continue
        outcome = _row_outcome(row)
        if outcome in VALID_OUTCOMES:
            valid = True
        elif outcome == "INVALID":
            invalid += 1
    return not valid and invalid < MAX_ATTEMPTS


def safety_stopped(units: dict[str, list[dict]]) -> bool:
    """A durable fatal observation stops recovery even if its marker was not written."""
    return any(row.get("fatal_device_condition") or
               (row.get("finalized") and row.get("limits") == "HOST")
               for rows in units.values() for row in rows)


def section_state(units: dict[str, list[dict]], interrupted: bool = False, blocked: bool = False) -> str:
    """Exactly one terminal state for a section (SPEC §5.2).

    Fatal safety stops are INTERRUPTED; failed environmental admission is
    BLOCKED; otherwise pending work is INTERRUPTED and exhausted invalid
    attempts yield COMPLETED_PARTIAL. Without gaps, COMPLETED applies to any
    mix of PASS/FAIL/NOT_EVALUABLE. M1 assigns no model classification.
    """
    if not isinstance(units, dict):
        _fail("units", "must be a mapping of unit id -> attempt list")
    if interrupted:
        return "INTERRUPTED"
    if blocked:
        return "BLOCKED"
    gaps = False
    for unit_id, attempts in units.items():
        if unit_pending(attempts):
            return "INTERRUPTED"
        resolved = resolved_attempt(attempts)
        if resolved is None:
            gaps = True
            continue
        outcome = _row_outcome(resolved)
        if outcome in ("INVALID", "NOT_RUN"):
            gaps = True
    if gaps:
        return "COMPLETED_PARTIAL"
    return "COMPLETED"


# ---------------------------------------------------------------------------
# Evidence completeness (the shared predicate)


REQUIRED_EVIDENCE_FILES = (
    "request.json",
    "response.raw",
    "conditions.json",
    "score.json",
    "attempt.json",
)
#: files covered by attempt.json.files (attempt.json itself is the commit
#: record, not a member of its own map)
HASHED_EVIDENCE_FILES = (
    "request.json",
    "response.raw",
    "conditions.json",
    "score.json",
)


def evidence_complete(attempt_dir: Path) -> bool:
    """Predicate: is ``attempt_dir`` a finalized, fully intact attempt?

    Verifies: all five required files exist and parse; attempt.json has
    finalized=true, unit_id, attempt_id, profile_revision (64-hex) and a
    ``files`` map covering EXACTLY the four hashed evidence files with
    matching streamed SHA-256s; attempt_id equals the directory name;
    conditions.json is an object carrying profile_revision (equal to the
    attempt's), request_limits (object), evidence_kind (known kind) and
    preflight.echo (object — its CONTENT is validated offline by
    preflight-side policy.validate_echo against the pinned profile);
    score.json carries the four facets plus an outcome that derive_outcome
    re-derives identically, and binds the same
    unit_id/attempt_id/profile_revision. Returns False (never raises) on
    any defect, including missing/malformed score facets or conditions
    structure."""
    d = Path(attempt_dir)
    for name in REQUIRED_EVIDENCE_FILES:
        if not (d / name).is_file():
            return False
    try:
        attempt = json.loads((d / "attempt.json").read_text(encoding="utf-8"))
        request = json.loads((d / "request.json").read_text(encoding="utf-8"))
        conditions = json.loads((d / "conditions.json").read_text(encoding="utf-8"))
        score = json.loads((d / "score.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(attempt, dict) or not isinstance(score, dict):
        return False
    if not isinstance(request, (dict, list)):
        return False
    if not isinstance(conditions, dict):
        return False
    if attempt.get("finalized") is not True:
        return False
    unit_id = attempt.get("unit_id")
    attempt_id = attempt.get("attempt_id")
    profile_revision = attempt.get("profile_revision")
    if not isinstance(unit_id, str) or not unit_id:
        return False
    if not isinstance(attempt_id, str) or attempt_id != d.name:
        return False
    if not isinstance(profile_revision, str) or not _HEX64.match(profile_revision):
        return False
    # conditions.json required structure (fail closed, not merely parsed)
    if not isinstance(conditions.get("profile_revision"), str) or (
        conditions["profile_revision"] != profile_revision
    ):
        return False
    if not isinstance(conditions.get("request_limits"), dict):
        return False
    if conditions.get("evidence_kind") not in EVIDENCE_KINDS:
        return False
    preflight_cond = conditions.get("preflight")
    if not isinstance(preflight_cond, dict) or not isinstance(
        preflight_cond.get("echo"), dict
    ):
        return False
    files = attempt.get("files")
    if not isinstance(files, dict) or not set(HASHED_EVIDENCE_FILES) <= set(files):
        return False
    if any(not isinstance(name, str) or Path(name).name != name or name in (".", "..")
           for name in files):
        return False
    extended = preflight_cond.get("methodology") == METHODOLOGY_M2 or set(files) != set(HASHED_EVIDENCE_FILES)
    if extended and set(files) != {p.name for p in d.iterdir()
                                   if p.is_file() and p.name != "attempt.json"}:
        return False
    for name in files:
        recorded = files[name]
        if not isinstance(recorded, str) or not _HEX64.match(recorded):
            return False
        try:
            if file_sha(d / name) != recorded:
                return False
        except CheckError:
            return False
    methodology = attempt.get("methodology")
    if methodology not in (None, METHODOLOGY, METHODOLOGY_M2,
                           METHODOLOGY_AGENTIC, METHODOLOGY_AGENTIC_PRELIVE,
                           METHODOLOGY_AGENTIC_PROPOSED, METHODOLOGY_DIAGNOSTIC,
                           METHODOLOGY_CALIBRATION, SCORED_METHODOLOGY):
        return False
    if methodology == METHODOLOGY_M2:
        if "preparation.json" not in files:
            return False
        try:
            prepared = json.loads((d / "preparation.json").read_bytes())
            if (prepared["unit_id"] != unit_id or prepared["attempt_id"] != attempt_id
                    or prepared["profile_revision"] != profile_revision
                    or not isinstance(prepared["prepared_task"], dict)
                    or "construction_evidence" not in prepared
                    or prepared["prepared_sha256"] != digest(prepared["prepared_task"])):
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
    # score.json binding + re-derivation
    if (
        score.get("unit_id") != unit_id
        or score.get("attempt_id") != attempt_id
        or score.get("profile_revision") != profile_revision
    ):
        return False
    facets = score.get("facets") if isinstance(score.get("facets"), dict) else score
    try:
        derived = derive_outcome(
            facets.get("execution"),
            facets.get("completion"),
            facets.get("scoring"),
            facets.get("limits"),
        )
    except (CheckError, AttributeError, TypeError):
        return False
    if score.get("outcome") != derived["outcome"]:
        return False
    if "reason" in score and score.get("reason") != derived["reason"]:
        return False
    return True


# ---------------------------------------------------------------------------
# Fatal device/host error text detection


_FATAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("cuda_oom", r"cuda.{0,60}out of memory|out of memory.{0,60}cuda|\bcuda_oom\b"),
    (
        "cuda_error",
        r"\bcuda(error)?\b.{0,60}\b(error|fault|assert|illegal|unlaunch|"
        r"initialization)\b|\b(error|fault|assert|illegal).{0,60}\bcuda\b",
    ),
    ("nvidia_xid", r"\bxid\b"),
    ("device_assert", r"device[- ]side assert|device assert|illegal memory access"),
    (
        "hip",
        r"\bhip(error|err)?\b.{0,60}\b(out of memory|error|fault|alloc|allocation|"
        r"deinit|loss|lost)\b|hiperror|hipoutofmemory|hipallocation|"
        r"\bhip\b.{0,40}\boom\b",
    ),
    (
        "vulkan_device_lost",
        r"device ?lost|vk_?error_?device_?lost|vulkan.{0,24}device.{0,24}lost|"
        r"vk_error_out_of_(?:device|host)_memory",
    ),
    (
        "amdgpu_reset_fault_ras",
        r"amdgpu.{0,60}(reset|fault|ras)|(reset|fault|ras).{0,60}amdgpu|"
        r"\bgpu reset\b|\bvm fault\b|\bpage fault\b",
    ),
    (
        "ras_ecc",
        r"\bras\b.{0,40}uncorrectable|uncorrectable.{0,40}\bras\b|"
        r"\becc\b.{0,24}(error|uncorrectable)|uncorrectable\s+ecc",
    ),
    (
        "host_oom",
        r"\bout of memory\b|\boom\b|std::bad_alloc|bad_alloc|"
        r"cannot allocate memory",
    ),
)

_COMPILED_FATAL = tuple(
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _FATAL_PATTERNS
)


def fatal_error_categories(text: str) -> list[str]:
    """Categories of fatal device/host conditions matched in ``text``
    (server-side HTTP error text — parent calls this only on error text,
    never on model prose). Empty list when nothing fatal matches."""
    if not isinstance(text, str) or not text:
        return []
    return [name for name, rx in _COMPILED_FATAL if rx.search(text)]


def fatal_device_error(text: str) -> bool:
    """True when ``text`` (HTTP error text from the serving stack) matches a
    fatal accelerator device-safety or host-resource condition (SPEC §5.2):
    CUDA OOM/Xid, HIP allocation failure/device loss, Vulkan device loss,
    amdgpu reset/fault/RAS, ECC uncorrectable, host OOM. Ordinary model
    prose and non-fatal HTTP errors do not match."""
    return bool(fatal_error_categories(text))


# ---------------------------------------------------------------------------
# Campaign-bound execution activation (corrected 2026-11-08)
#
# The gated live routes (scored Agentic `agentic/3`; live calibration
# contrast `agentic-calibration/1`) are authorized by a recorded
# campaign-directory activation file — never by mutating module source
# state. The former source-delta gate (temporarily editing module flags)
# exposed concurrent importers to a temporarily authorized process and
# made unrelated test/CLI behavior depend on edit timing. Fail-closed: a
# missing record, a wrong campaign/methodology binding, or a malformed
# shape means inactive; no caller argument can substitute for the record.

ACTIVATION_FILENAME = "campaign-activation.json"


def campaign_activation(campaign_root, expected_campaign, expected_methodology):
    """Verified campaign-activation record, or None (fail-closed inactive).

    The record must bind exactly one campaign and one gated methodology,
    name the activated sections, and carry operator attribution:
    ``{"activation": <gate id>, "campaign": <id>, "methodology": <pin>,
    "sections": [<str>...], "operator": <str>, "authorized_utc": <str>}``.
    """
    path = Path(campaign_root or "") / ACTIVATION_FILENAME
    try:
        record = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("campaign") != expected_campaign:
        return None
    if record.get("methodology") != expected_methodology:
        return None
    if (not isinstance(record.get("sections"), list) or not record["sections"]
            or not all(isinstance(s, str) and s for s in record["sections"])):
        return None
    if not isinstance(record.get("operator"), str) or not record["operator"]:
        return None
    if not isinstance(record.get("authorized_utc"), str) or not record["authorized_utc"]:
        return None
    return record
