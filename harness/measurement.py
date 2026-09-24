#!/usr/bin/env python3
"""measurement.py — canonical LLMGauge evidence import + repetition summarization
(welp-phase-harness/1).

Implements welp-measurement 0.1.0-draft: a minimal, read-only WELP-side
import/compatibility layer over EXISTING LLMGauge producer formats —
`llmgauge.localmaxxing_benchmark.v1` (llama-bench speed module with companion
raw evidence) and `llmgauge.result.v0` (native run results, bounded single-run
import) — plus deterministic repetition summarization. The practical-suite
role is retained: suite/prompt-level evidence imports under the same identity
discipline; this module is not speed-only.

Fail-closed rules (contract, section import):
  - Missing source metadata is NEVER satisfied by the caller's expected value;
    unavailable = explicit noncomparability.
  - A qualification sidecar may fill an absent field ONLY through immutable,
    digest-pinned references whose actual values are re-verified here.
  - Full source/raw referenced hashes are verified (producer fingerprint
    recomputation, file digests, referenced raw artifacts, transcript digest).
  - Unknown optional producer fields are tolerated.
  - No retrospective outlier removal, no cross-workload/policy pooling, no
    IID confidence intervals. TTFT stays a benchmark proxy, never direct
    deployment TTFT. Stream-first-token, final-first-output and end-to-end
    channels stay separate.

Primary evidence path (format source):
  research/model-evaluations/lfm2.5-8b-a1b/
    lfm2.5-8b-a1b-rtx5070-welp-prospective-retest-2-2026-09-23/localmaxxing-artifact

Selftest: python3 harness/measurement.py selftest
CLI:      python3 harness/measurement.py import SOURCE EXPECTED_JSON
          python3 harness/measurement.py summarize INPUT_JSON
"""
import hashlib
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path

MODULE_ID = "welp-harness-measurement/1.0.0-draft"
CONTRACT = "welp-measurement-0.1.0-draft"

PRODUCER_LOCALMAXXING = "llmgauge.localmaxxing_benchmark.v1"
PRODUCER_RESULT = "llmgauge.result.v0"
METHOD_LOCALMAXXING = "localmaxxing-llama-cpp-v1"

STATUS_COMPATIBLE = "COMPATIBLE"
STATUS_NON_COMPARABLE = "NON_COMPARABLE"

AVAILABLE = "available"
ABSENT = "absent"
UNAVAILABLE = "unavailable"

DEFAULT_CV_FLAG_THRESHOLD = 0.10

# Native metric boundary/units per producer schema. Units are part of the
# producer's metric definition; an importer expectation that contradicts them
# is a unit-definition mismatch, never silently reinterpreted.
NATIVE_METRIC_UNITS = {
    PRODUCER_LOCALMAXXING: {
        "tok_s_out": "tok/s",
        "tok_s_prefill": "tok/s",
        "tok_s_total": "tok/s",
        "ttft_ms": "ms",
        "peak_total_vram_mib": "MiB",
        "mean_power_w": "W",
    },
    PRODUCER_RESULT: {
        "generation_tps": "tok/s",
        "prompt_eval_tps": "tok/s",
        "peak_vram_mib": "MiB",
    },
}

LOCALMAXXING_COMPANION_FILES = (
    "execution-evidence.json",
    "ttft-evidence.json",
    "telemetry-evidence.json",
    "localmaxxing-submission-receipt.json",
)

# Axis -> path inside the producer record. None path = the producer schema has
# no field for this axis; demanding it is always explicit noncomparability.
_LOCALMAXXING_AXES = {
    "model.hf_id": ("model", "hf_id"),
    "model.revision": ("model", "revision"),
    "model.quantization": ("model", "quantization"),
    "model.profile": ("model", "profile"),
    "model.local_reference": ("model", "local_reference"),
    "engine.name": ("engine", "name"),
    "engine.version": ("engine", "version"),
    "engine.backend": ("engine", "backend"),
    "engine.executable": ("engine", "executable"),
    "hardware.gpu_name": ("hardware", "gpuName"),
    "hardware.hw_class": ("hardware", "hwClass"),
    "hardware.cpu": ("hardware", "cpu"),
    "hardware.os": ("hardware", "os"),
    "hardware.vram_gb": ("hardware", "vramGb"),
    "hardware.ram_gb": ("hardware", "ramGb"),
    "hardware.gpu_count": ("hardware", "gpuCount"),
    "runtime.device": ("runtime", "device"),
    "runtime.flash_attention_requested": ("runtime", "flash_attention_requested"),
    "runtime.gpu_layers_requested": ("runtime", "gpu_layers_requested"),
    "runtime.gpu_placement": ("runtime", "gpu_placement"),
    "runtime.kv_offload": ("runtime", "kv_offload"),
    "runtime.kv_cache_type_k": ("runtime", "kv_cache", "type_k"),
    "runtime.kv_cache_type_v": ("runtime", "kv_cache", "type_v"),
    "runtime.load_mode": ("runtime", "load_mode"),
    "runtime.logical_batch": ("runtime", "logical_batch"),
    "runtime.physical_ubatch": ("runtime", "physical_ubatch"),
    "runtime.main_gpu": ("runtime", "main_gpu"),
    "runtime.split_mode": ("runtime", "split_mode"),
    "workload.prompt_tokens": ("workload", "prompt_tokens"),
    "workload.output_tokens": ("workload", "output_tokens"),
    "workload.batch_size": ("workload", "batch_size"),
    "workload.repetitions": ("workload", "repetitions"),
    "workload.warmup_repetitions": ("workload", "warmup_repetitions"),
    "workload.sampling": ("workload", "sampling"),
    "workload.context_length": ("workload", "context_length"),  # optional producer field; sidecar-filled when absent
    "command_provenance": ("command_provenance",),
}

_RESULT_AXES = {
    "model.model_id": ("model", "model_id"),
    "model.model_profile": ("model", "model_profile"),
    "model.quant": ("model", "quant"),
    "model.quantization": ("model", "provenance", "filename"),
    "model.hf_id": ("model", "model_id"),
    "engine.backend": ("runtime", "backend"),
    "engine.version": ("runtime", "backend_provenance", "reported_version"),
    "runtime.ctx_size": ("runtime", "ctx_size"),
    "runtime.max_tokens": ("runtime", "max_tokens"),
    "runtime.temperature": ("runtime", "temperature"),
    "runtime.top_p": ("runtime", "top_p"),
    "runtime.top_k": ("runtime", "top_k"),
    "runtime.min_p": ("runtime", "min_p"),
    "runtime.seed": ("runtime", "seed"),
    "runtime.gpu_layers": ("runtime", "gpu_layers"),
    "runtime.kv_offload": ("runtime", "kv_offload"),
    "runtime.kv_cache_type_k": ("runtime", "cache_type_k"),
    "runtime.kv_cache_type_v": ("runtime", "cache_type_v"),
    "runtime.flash_attention": ("runtime", "flash_attn"),
    "runtime.reasoning_mode": ("runtime", "reasoning_mode"),
    "workload.suite_id": ("suite", "suite_id"),
    "workload.suite_only": ("suite", "only"),
    "workload.prompt_count": ("suite", "prompt_count"),
    "workload.context_length": ("runtime", "ctx_size"),
    # result.v0 carries NO hardware facts: these axes are sidecar-fillable only
    "hardware.gpu_name": None,
    "hardware.hw_class": None,
}

# The complete preregistered comparison identity per producer. An import whose
# `expected` lacks any of these axes is NON_COMPARABLE (an implicit don't-care
# is never allowed); an axis demanded here but unverifiable from the source —
# natively OR through a verified digest-pinned sidecar — is likewise
# NON_COMPARABLE. Structural unavailability in the native format is never a
# reason to omit an axis from the gate: cache_regime and timing_boundary have
# no native field and are satisfied only through a verified pinned sidecar;
# workload.context_length is natively optional in the localmaxxing format
# (mapped when present) and natively pinned via runtime.ctx_size for
# result.v0; result.v0 hardware axes are sidecar-only.
REQUIRED_EXPECTED_AXES = {
    PRODUCER_LOCALMAXXING: (
        "artifact_sha256",
        "model_artifact_sha256",
        "metric_units",
        "cache_regime",
        "timing_boundary",
        "model.hf_id",
        "model.quantization",
        "model.revision",
        "model.local_reference",
        "engine.name",
        "engine.version",
        "engine.backend",
        "hardware.gpu_name",
        "hardware.hw_class",
        "runtime.gpu_placement",
        "runtime.gpu_layers_requested",
        "runtime.kv_offload",
        "runtime.kv_cache_type_k",
        "runtime.kv_cache_type_v",
        "workload.prompt_tokens",
        "workload.output_tokens",
        "workload.batch_size",
        "workload.context_length",
        "workload.repetitions",
        "workload.warmup_repetitions",
    ),
    PRODUCER_RESULT: (
        "artifact_sha256",
        "model_artifact_sha256",
        "metric_units",
        "cache_regime",
        "timing_boundary",
        "model.model_id",
        "engine.backend",
        "hardware.gpu_name",
        "hardware.hw_class",
        "workload.suite_id",
        "workload.prompt_count",
        "workload.context_length",
        "runtime.ctx_size",
        "runtime.max_tokens",
        "runtime.temperature",
        "runtime.top_p",
        "runtime.gpu_layers",
        "runtime.kv_offload",
        "runtime.kv_cache_type_k",
        "runtime.kv_cache_type_v",
        "runtime.flash_attention",
        "runtime.seed",
    ),
}

ALLOWED_EXPECTED_TOP_LEVEL = {
    "artifact_sha256", "artifact_fingerprint", "model_artifact_sha256",
    "cache_regime", "timing_boundary", "repetition_structure", "metric_units",
    "qualification_sidecar",
}
KNOWN_EXPECTED_SECTIONS = ("model", "engine", "hardware", "runtime", "workload")


class MeasurementError(ValueError):
    """Deterministic policy/usage error (summarize, CLI input)."""


# ---------------------------------------------------------------------------
# Repetition summarization
# ---------------------------------------------------------------------------

def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MeasurementError(f"{where}: not a finite number: {value!r}")
    if not math.isfinite(value):
        raise MeasurementError(f"{where}: nonfinite value: {value!r}")
    if value < 0:
        raise MeasurementError(f"{where}: negative observation: {value!r}")
    return float(value)


def _stat_block(values, measured, lane):
    """Deterministic descriptive statistics. values = every raw observation in
    execution order (including designated warmups); stats cover measured only."""
    n = len(measured)
    mean = statistics.fmean(measured) if n else None
    if n >= 2:
        sd = statistics.stdev(measured)        # sample sd (n-1)
        cv = sd / mean if mean != 0 else None  # mean 0 -> cv not establishable
    else:
        sd = None
        cv = None
    return {
        "lane": lane,
        "n": n,
        "raw_values": list(values),
        "mean": mean,
        "sample_sd": sd,
        "sample_sd_note": None if sd is not None else "undefined at n<2",
        "median": statistics.median(measured) if n else None,
        "min": min(measured) if n else None,
        "max": max(measured) if n else None,
        "cv": cv,
    }


def summarize_repetitions(values, policy):
    """Deterministic repetition summary under a preregistered policy.

    values: flat list of observations in execution order (batch-major), or a
    dict {"warmed": [...], "cold": [...]} when policy declares a separately
    measured cold process-startup lane ("cold_start").
    policy keys:
      metric, unit, workload            labels (recorded)
      channel                           "end_to_end" | "stream_first_token" |
                                        "final_first_output" (default end_to_end);
                                        channels are never pooled
      warmup                            designated leading warmup observations of
                                        the FIRST batch excluded from stats
                                        (default 0); further warmups come from
                                        batch_warmups; exclusion is batch-major
      measured_per_batch                expected measured observations per
                                        batch (default 5; prospective default
                                        policy is 1 warmup + 5 measured)
      max_batches                       preregistered batch count, 1 or 2
                                        (default 1; 2 = exactly one additional
                                        batch MAY run, but ONLY on a first-batch
                                        variance trigger; afterward ALL
                                        observations are retained and reported
                                        with a residual flag — no favorable
                                        selection; a trigger with only the first
                                        batch present yields lane status
                                        "pending_additional_batch")
      batch_warmups                     optional explicit warmup count per batch
                                        (each removes that batch's leading
                                        observations only)
      cv_flag_threshold                 preregistered variance-flag trigger
                                        (default 0.10; explicit None disables)
      cold_start                        {"warmup": int, "measured_per_batch": int}
    """
    if not isinstance(policy, dict):
        raise MeasurementError("policy: must be a JSON object")
    for key in policy:
        if key not in (
            "metric", "unit", "workload", "channel", "warmup",
            "measured_per_batch", "max_batches", "batch_warmups",
            "cv_flag_threshold", "cold_start",
        ):
            raise MeasurementError(f"policy: unknown key {key!r}")

    channel = policy.get("channel", "end_to_end")
    if channel not in ("end_to_end", "stream_first_token", "final_first_output"):
        raise MeasurementError(f"policy.channel: unsupported channel {channel!r}")
    warmup = policy.get("warmup", 0)
    per_batch = policy.get("measured_per_batch", 5)
    max_batches = policy.get("max_batches", 1)
    if not isinstance(warmup, int) or isinstance(warmup, bool) or warmup < 0:
        raise MeasurementError("policy.warmup: must be a non-negative integer")
    if not isinstance(per_batch, int) or isinstance(per_batch, bool) or per_batch < 1:
        raise MeasurementError("policy.measured_per_batch: must be a positive integer")
    if not isinstance(max_batches, int) or isinstance(max_batches, bool) \
            or max_batches not in (1, 2):
        raise MeasurementError("policy.max_batches: must be integer 1 or 2 "
                               "(exactly one preregistered additional batch maximum)")
    threshold = policy.get("cv_flag_threshold", DEFAULT_CV_FLAG_THRESHOLD)
    if threshold is not None and (
        isinstance(threshold, bool) or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold) or threshold <= 0
    ):
        raise MeasurementError("policy.cv_flag_threshold: must be a positive finite number or null")

    def _lane_summary(obs, lane_policy, lane_name):
        obs = list(obs)
        if not obs:
            raise MeasurementError(f"{lane_name}: no observations")
        obs = [_number(v, f"{lane_name}[{i}]") for i, v in enumerate(obs)]
        bw = lane_policy.get("batch_warmups")
        if bw is not None:
            if (not isinstance(bw, list) or not bw
                    or any(not isinstance(b, int) or isinstance(b, bool) or b < 0 for b in bw)):
                raise MeasurementError(f"{lane_name}: batch_warmups must be a list of non-negative integers")
            executed = len(bw)
            if executed > lane_policy["max_batches"]:
                raise MeasurementError(
                    f"{lane_name}: {executed} executed batches exceed the preregistered "
                    f"maximum of {lane_policy['max_batches']}; unpreregistered batches are rejected")
            expected_len = sum(bw) + lane_policy["measured_per_batch"] * executed
            if len(obs) != expected_len:
                raise MeasurementError(
                    f"{lane_name}: expected {expected_len} observations "
                    f"(warmups {bw} + {lane_policy['measured_per_batch']}/batch), got {len(obs)}")
            warmups = bw
        else:
            single = lane_policy["warmup"] + lane_policy["measured_per_batch"]
            if len(obs) == single:
                executed, warmups = 1, [lane_policy["warmup"]]
            elif (lane_policy["max_batches"] == 2
                  and len(obs) == lane_policy["warmup"] + lane_policy["measured_per_batch"] * 2):
                # second batch repeats no warmup by default
                executed, warmups = 2, [lane_policy["warmup"], 0]
            else:
                allowed = [single] + ([lane_policy["warmup"] + lane_policy["measured_per_batch"] * 2]
                                      if lane_policy["max_batches"] == 2 else [])
                raise MeasurementError(
                    f"{lane_name}: got {len(obs)} observations; allowed lengths under the "
                    f"preregistered policy: {allowed} (1 warmup + 5 measured default shape)")

        # batch-major exclusion: each batch consumes warmup + measured_per_batch;
        # warmup count b removes the FIRST observations of batch b only
        cursor = 0
        warmup_values = []
        measured_chunks = []
        for count in warmups:
            warmup_values.extend(obs[cursor:cursor + count])
            measured_chunks.append(
                obs[cursor + count:cursor + count + lane_policy["measured_per_batch"]])
            cursor += count + lane_policy["measured_per_batch"]
        measured = [value for chunk in measured_chunks for value in chunk]
        if not measured:
            raise MeasurementError(f"{lane_name}: no measured observations after warmup exclusion")

        # preregistered variance-trigger extension: a second batch is legitimate
        # ONLY when max_batches=2 was preregistered AND the FIRST batch's CV
        # exceeded the threshold; otherwise the extension is rejected outright
        executed = len(warmups)
        extension_allowed = lane_policy["max_batches"] == 2 and threshold is not None
        first_batch = measured_chunks[0]
        if len(first_batch) >= 2:
            first_mean = statistics.fmean(first_batch)
            first_cv = statistics.stdev(first_batch) / first_mean if first_mean != 0 else None
        else:
            first_cv = None
        first_triggered = first_cv is not None and threshold is not None and first_cv > threshold
        if executed == 2 and not (extension_allowed and first_triggered):
            raise MeasurementError(
                f"{lane_name}: second batch executed without a preregistered "
                f"variance trigger (requires max_batches=2 AND first-batch cv > "
                f"{threshold}); untriggered extensions are rejected")
        # triggered but the preregistered additional batch has not run yet
        pending = executed == 1 and extension_allowed and first_triggered

        block = _stat_block(obs, measured, lane_name)
        cv = block["cv"]
        if threshold is not None and cv is not None:
            triggered, evaluated = cv > threshold, True
        else:
            triggered, evaluated = False, False
        block.update({
            "status": "pending_additional_batch" if pending else "complete",
            "extension_note": (
                "first-batch variance trigger fired; the preregistered additional "
                "batch is REQUIRED before any gate decision uses this summary"
            ) if pending else None,
            "measured_values": list(measured),
            "warmup_values": warmup_values,
            "warmup_excluded": len(warmup_values),
            "warmup_exclusion_rule": "preregistered designated samples only, "
                                     "batch-major; no retrospective outlier removal",
            "first_batch": {
                "measured_values": list(first_batch),
                "cv": first_cv,
                "variance_trigger": first_triggered,
            },
            "batches": {
                "preregistered_max": lane_policy["max_batches"],
                "executed": executed,
                "warmups_per_batch": warmups,
                "reported": "all executed batches pooled; no favorable selection",
            },
            "variance_flag": {
                "triggered": triggered,
                "evaluated": evaluated,
                "threshold": threshold,
                "rule": "cv > threshold on the reported observation set; "
                        "preregistered policy trigger only",
            },
            "residual_flag": (
                {"triggered": triggered, "rule": "pooled cv still above the "
                 "threshold after the preregistered extension; all observations "
                 "retained and reported"}
                if executed == 2 else None),
            "additional_batch_policy": (
                "exactly one additional batch preregistered; executed only on a "
                "first-batch variance trigger; all observations then retained "
                "and reported with a residual flag"
                if lane_policy["max_batches"] == 2 else "none preregistered"),
            "outlier_removal": "none",
            "pooling": "single workload and policy only; different workloads or "
                       "policies are never pooled",
            "confidence_interval": "none; IID confidence intervals unsupported",
        })
        return block

    lane_policy = {
        "warmup": warmup,
        "measured_per_batch": per_batch,
        "max_batches": max_batches,
        "batch_warmups": policy.get("batch_warmups"),
    }
    cold_policy = policy.get("cold_start")
    if cold_policy is not None:
        if not isinstance(cold_policy, dict):
            raise MeasurementError("policy.cold_start: must be an object")
        if not isinstance(values, dict):
            raise MeasurementError(
                "values: with policy.cold_start, use {\"warmed\": [...], \"cold\": [...]}")
        unexpected = sorted(set(values) - {"warmed", "cold"})
        missing = sorted({"warmed", "cold"} - set(values))
        if unexpected or missing:
            raise MeasurementError(
                f"values: cold-start form requires exactly both lanes 'warmed' and "
                f"'cold' (missing: {missing}, unexpected: {unexpected})")
        for key, req in (("warmup", False), ("measured_per_batch", True)):
            v = cold_policy.get(key, 0)
            if not isinstance(v, int) or isinstance(v, bool) or v < (1 if req else 0):
                raise MeasurementError(f"policy.cold_start.{key}: invalid")
        warmed = _lane_summary(values["warmed"], lane_policy, "warmed")
        cold = _lane_summary(
            values["cold"],
            {"warmup": cold_policy.get("warmup", 0),
             "measured_per_batch": cold_policy["measured_per_batch"],
             "max_batches": 1, "batch_warmups": None},
            "cold_process_startup")
    else:
        if isinstance(values, dict):
            raise MeasurementError(
                "values: dict form requires policy.cold_start")
        warmed = _lane_summary(values, lane_policy, "warmed")
        cold = None

    return {
        "metric": policy.get("metric"),
        "unit": policy.get("unit"),
        "channel": channel,
        "workload": policy.get("workload"),
        "policy": {
            "warmup": warmup,
            "measured_per_batch": per_batch,
            "max_batches": max_batches,
            "cv_flag_threshold": threshold,
        },
        "warmed": warmed,
        "cold_start": cold,
        "cold_start_note": None if cold is None else \
            "cold process-startup lane measured and reported separately; never pooled",
    }


# ---------------------------------------------------------------------------
# Shared verification helpers
# ---------------------------------------------------------------------------

def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _producer_fingerprint(artifact):
    """LocalMaxxing producer fingerprint: sha256 over canonical JSON with the
    `fingerprint` member omitted (llmgauge.core.localmaxxing.fingerprint)."""
    copy = dict(artifact)
    copy.pop("fingerprint", None)
    return hashlib.sha256(_canonical_json(copy).encode("utf-8")).hexdigest()


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_positive(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def _values_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(a) and math.isfinite(b) and a == b
    if type(a) is not type(b):
        return False
    return a == b


_MISSING = object()


def _deep_get(record, path):
    cursor = record
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return _MISSING
        cursor = cursor[part]
    return cursor


def _json_pointer(doc, pointer):
    """Resolve an RFC 6901-style JSON pointer; returns _MISSING when absent."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return _MISSING
    cursor = doc
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cursor, dict):
            if token not in cursor:
                return _MISSING
            cursor = cursor[token]
        elif isinstance(cursor, list):
            if not token.isdigit() or int(token) >= len(cursor):
                return _MISSING
            cursor = cursor[int(token)]
        else:
            return _MISSING
    return cursor


def _load_json(path, reasons, label):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        reasons.append(f"schema: cannot read {label} at {path.name}: {exc}")
        return None


def _resolve_under(base, relative):
    """Resolve a source-relative reference with containment; never escapes base."""
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_llmgauge(source, expected):
    """Import LLMGauge producer evidence read-only and judge comparability.

    source: path to a benchmark artifact file/directory
            (llmgauge.localmaxxing_benchmark.v1) or a run result file/directory
            (llmgauge.result.v0).
    expected: the COMPLETE preregistered comparison identity (see
    REQUIRED_EXPECTED_AXES and the contract). Sections model/engine/hardware/
    runtime/workload hold dotted axis keys; required top-level keys:
    artifact_sha256 (source bytes pin), model_artifact_sha256 (model artifact
    identity pin), cache_regime and timing_boundary (no native producer field —
    satisfied only through the verified digest-pinned sidecar), and metric_units
    (boundary/units). workload.context_length is required: an optional native
    localmaxxing field (matched when present), runtime.ctx_size for result.v0;
    result.v0 hardware axes are sidecar-only. Missing caller axes and
    unverifiable source facts are both NON_COMPARABLE — never implicit
    don't-care, and structural unavailability never relaxes the gate.
    Optional: artifact_fingerprint, repetition_structure, qualification_sidecar
    (digest-pinned).

    Returns {status: COMPATIBLE|NON_COMPARABLE, reasons: [...],
             metrics: {...}, provenance: {...}}. NON_COMPARABLE is reported,
             never raised: unavailability is evidence about the source.
    """
    source = Path(source)
    expected = expected if isinstance(expected, dict) else {}
    out = {
        "status": STATUS_COMPATIBLE,
        "reasons": [],
        "metrics": {},
        "provenance": {
            "import": {"module": MODULE_ID, "contract": CONTRACT,
                       "read_only": True},
        },
    }
    reasons = out["reasons"]

    if not source.exists():
        out["status"] = STATUS_NON_COMPARABLE
        reasons.append(f"schema: source not found: {source}")
        return out
    if source.is_dir():
        if (source / "benchmark.json").is_file():
            source_file = source / "benchmark.json"
        elif (source / "llmgauge-result.json").is_file():
            source_file = source / "llmgauge-result.json"
        else:
            out["status"] = STATUS_NON_COMPARABLE
            reasons.append("schema: source directory has neither benchmark.json "
                           "nor llmgauge-result.json")
            return out
    else:
        source_file = source
    base_dir = source_file.parent
    out["provenance"]["source_path"] = str(source_file)
    try:
        out["provenance"]["source_sha256"] = _sha256_file(source_file)
    except OSError as exc:
        out["status"] = STATUS_NON_COMPARABLE
        reasons.append(f"hash: source file unreadable: {exc}")
        return out

    record = _load_json(source_file, reasons, "source JSON")
    if record is None or not isinstance(record, dict):
        out["status"] = STATUS_NON_COMPARABLE
        if not reasons:
            reasons.append("schema: source JSON is not an object")
        return out

    schema = record.get("schema_version")
    out["provenance"]["producer_schema"] = schema
    if schema not in (PRODUCER_LOCALMAXXING, PRODUCER_RESULT):
        out["status"] = STATUS_NON_COMPARABLE
        reasons.append(f"schema: unsupported producer schema_version {schema!r}; "
                       f"supported: {PRODUCER_LOCALMAXXING}, {PRODUCER_RESULT}")
        return out
    # complete preregistered comparison identity: missing caller axes are
    # NON_COMPARABLE, never an implicit don't-care
    for axis in REQUIRED_EXPECTED_AXES[schema]:
        if "." in axis:
            section, key = axis.split(".", 1)
            wanted = expected.get(section)
            if not isinstance(wanted, dict) or key not in wanted:
                reasons.append(
                    f"schema: expected comparison identity incomplete — {axis} "
                    f"is a required preregistered axis but the caller's expected "
                    f"value is missing")
        elif axis == "metric_units":
            if not isinstance(expected.get("metric_units"), dict) or not expected["metric_units"]:
                reasons.append(
                    "schema: expected comparison identity incomplete — metric_units "
                    "(metric boundary/units) is required and must be a non-empty object")
        elif axis not in expected:
            reasons.append(
                f"schema: expected comparison identity incomplete — {axis} is a "
                f"required preregistered axis but the caller's expected value is missing")
    # unknown expected keys reject (a typo must never be silently ignored)
    for key in sorted(expected):
        if key in KNOWN_EXPECTED_SECTIONS:
            if not isinstance(expected[key], dict):
                reasons.append(f"axis: expected section {key} must be an object")
            continue
        if key not in ALLOWED_EXPECTED_TOP_LEVEL:
            reasons.append(f"axis: unknown expected key {key!r} — expected keys are "
                           f"never ignored; typos or unsupported axes are rejected")
    if reasons:
        out["status"] = STATUS_NON_COMPARABLE
        return out
    if schema == PRODUCER_LOCALMAXXING:
        _import_localmaxxing(record, source_file, base_dir, expected, out)
    else:
        _import_result(record, base_dir, expected, out)
    if reasons:
        out["status"] = STATUS_NON_COMPARABLE
    return out


def _verify_sidecar(expected, base_dir, out, reasons):
    """Verify an evidenced qualification sidecar; returns {axis: value} for
    fields whose immutable references verified, {} otherwise."""
    spec = expected.get("qualification_sidecar")
    verified = {}
    if spec is None:
        return verified
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), (str, Path)):
        reasons.append("sidecar: qualification_sidecar requires a path")
        return verified
    sidecar_path = Path(spec["path"])
    if not sidecar_path.is_absolute():
        sidecar_path = base_dir / sidecar_path
    if not sidecar_path.is_file():
        reasons.append(f"sidecar: sidecar file not found: {sidecar_path.name}")
        return verified
    provenance = out["provenance"].setdefault("sidecar", {})
    provenance["path"] = sidecar_path.name
    wanted_sha = spec.get("expected_sha256")
    if not isinstance(wanted_sha, str) or not wanted_sha:
        reasons.append("sidecar: expected_sha256 pin is required — an unpinned "
                       "qualification sidecar is not an immutable reference")
        return verified
    try:
        sidecar_sha = _sha256_file(sidecar_path)
    except OSError as exc:
        reasons.append(f"sidecar: sidecar file unreadable: {exc}")
        return verified
    provenance["sha256"] = sidecar_sha
    if sidecar_sha != wanted_sha:
        reasons.append("sidecar: sidecar sha256 mismatch — qualification record "
                       "is not the pinned immutable reference")
        return verified
    sidecar = _load_json(sidecar_path, reasons, "qualification sidecar")
    if not isinstance(sidecar, dict) or not isinstance(sidecar.get("fields"), dict):
        if not reasons:
            reasons.append("sidecar: sidecar JSON must be an object with a fields object")
        return verified
    provenance["schema"] = sidecar.get("sidecar")
    filled, rejected = {}, []
    for axis, entry in sorted(sidecar["fields"].items()):
        if not isinstance(entry, dict) or "value" not in entry \
                or not isinstance(entry.get("evidence"), dict):
            rejected.append(f"{axis}: malformed sidecar entry")
            continue
        evidence = entry["evidence"]
        ref = evidence.get("path")
        ref_path = _resolve_under(base_dir, ref) if isinstance(ref, str) else None
        if ref_path is None or not ref_path.is_file():
            rejected.append(f"{axis}: evidence reference missing or escapes "
                            f"the source tree: {ref!r}")
            continue
        try:
            ref_sha = _sha256_file(ref_path)
        except OSError:
            rejected.append(f"{axis}: evidence file unreadable: {ref}")
            continue
        pinned = evidence.get("sha256")
        if not isinstance(pinned, str) or ref_sha != pinned:
            rejected.append(f"{axis}: evidence sha256 mismatch for {ref} "
                            f"(reference is not immutable at the pinned digest)")
            continue
        evidence_doc = _load_json(ref_path, [], f"sidecar evidence {ref}")
        if evidence_doc is None:
            rejected.append(f"{axis}: evidence file is not valid JSON: {ref}")
            continue
        actual = _json_pointer(evidence_doc, evidence.get("json_pointer"))
        if actual is _MISSING:
            rejected.append(f"{axis}: json_pointer {evidence.get('json_pointer')!r} "
                            f"does not resolve in {ref}")
            continue
        if not _values_equal(actual, entry["value"]):
            rejected.append(f"{axis}: sidecar value {entry['value']!r} contradicts "
                            f"the referenced actual value {actual!r}")
            continue
        filled[axis] = entry["value"]
    provenance["verified_fields"] = sorted(filled)
    for line in rejected:
        reasons.append(f"sidecar: {line}")
    provenance["rejected_fields"] = [line.split(":", 1)[0] for line in rejected]
    return filled


def _check_metric_units(expected, producer_schema, reasons):
    wanted = expected.get("metric_units")
    if not isinstance(wanted, dict):
        return
    native = NATIVE_METRIC_UNITS[producer_schema]
    for metric, unit in sorted(wanted.items()):
        if metric not in native:
            reasons.append(f"unit: metric unit expectation for unknown metric "
                           f"{metric!r} (native metrics: {sorted(native)})")
        elif unit != native[metric]:
            reasons.append(f"unit: {metric} expected unit {unit!r} contradicts the "
                           f"native producer definition {native[metric]!r}")


def _summarize(values, policy):
    try:
        return summarize_repetitions(values, policy)
    except MeasurementError as exc:
        return {"error": str(exc)}


def _import_localmaxxing(artifact, source_file, base_dir, expected, out):
    reasons = out["reasons"]
    provenance = out["provenance"]
    if artifact.get("artifact_version") != 1 or artifact.get("method") != METHOD_LOCALMAXXING:
        reasons.append(f"schema: unsupported localmaxxing artifact_version/method: "
                       f"{artifact.get('artifact_version')!r}/{artifact.get('method')!r}")
    # --- full-source hash verification -------------------------------------
    recorded_fp = artifact.get("fingerprint")
    recomputed = _producer_fingerprint(artifact)
    fingerprint_ok = isinstance(recorded_fp, str) and recorded_fp == recomputed
    provenance["artifact_fingerprint"] = recorded_fp
    provenance["fingerprint_verified"] = fingerprint_ok
    if "artifact_fingerprint" in expected and expected["artifact_fingerprint"] != recorded_fp:
        reasons.append(f"hash: artifact_fingerprint expected "
                       f"{expected['artifact_fingerprint']!r}, source has {recorded_fp!r}")
    if not fingerprint_ok:
        reasons.append("hash: producer fingerprint mismatch — artifact bytes are "
                       "not the sealed measurement record")
    if "artifact_sha256" in expected and expected["artifact_sha256"] != out["provenance"]["source_sha256"]:
        reasons.append(f"hash: artifact file sha256 expected "
                       f"{expected['artifact_sha256']!r}, source file has "
                       f"{out['provenance']['source_sha256']!r}")

    # --- full source directory digests + companion raw evidence ------------
    raw_files = {}
    try:
        entries = sorted(p for p in base_dir.iterdir() if p.is_file())
    except OSError:
        entries = []
    if len(entries) > 64:
        reasons.append("raw: source directory exceeds the bounded file inventory (64)")
        entries = entries[:64]
    for path in entries:
        try:
            raw_files[path.name] = {"sha256": _sha256_file(path)}
        except OSError:
            raw_files[path.name] = {"sha256": UNAVAILABLE}
    provenance["raw_files"] = raw_files

    exec_doc = _load_json(base_dir / "execution-evidence.json", [], "execution evidence") \
        if (base_dir / "execution-evidence.json").is_file() else None
    warmup_evidence = ABSENT
    raw_contradictions = []
    actual_prompt_tokens = _MISSING
    if exec_doc is None:
        raw_contradictions.append(
            "repetition raw evidence pin missing — execution-evidence.json is "
            "required to verify every measured repetition against its actual "
            "pp/tg rows (sealed aggregate values alone cannot pin the raw record)")
    elif not isinstance(exec_doc, dict):
        raw_contradictions.append("execution-evidence.json is not an object")
    else:
        raw_files.setdefault("execution-evidence.json", {})["cross_checked"] = True
        if isinstance(exec_doc.get("runtime"), dict):
            if exec_doc["runtime"] != artifact.get("runtime"):
                raw_contradictions.append(
                    "execution-evidence runtime block contradicts the artifact runtime")
        else:
            raw_contradictions.append("execution-evidence.json has no runtime block")
        if exec_doc.get("engine_version") != artifact.get("engine", {}).get("version"):
            raw_contradictions.append(
                "execution-evidence engine_version contradicts the artifact engine")
        if exec_doc.get("exit_status") != 0:
            raw_contradictions.append(
                f"execution-evidence exit_status {exec_doc.get('exit_status')!r} "
                f"is not a successful measurement run")
        warmup_raw = exec_doc.get("warmup_stdout")
        if isinstance(warmup_raw, str) and warmup_raw.strip():
            try:
                warmup_rows = json.loads(warmup_raw)
                if not warmup_rows:
                    raw_contradictions.append("execution-evidence warmup_stdout is empty")
                else:
                    warmup_evidence = AVAILABLE
            except json.JSONDecodeError:
                raw_contradictions.append("execution-evidence warmup_stdout is not JSON")

        # positional repetition pin: repetition i must be exactly one prefill row
        # (n_prompt=workload.prompt_tokens, n_gen=0) and one decode row
        # (n_prompt=0, n_gen=workload.output_tokens) whose avg_ts equal the
        # sealed measurement pair; per-row engine config must match the artifact
        # runtime. Set membership cannot prove this: swaps and duplicates would
        # pass it, positional identity cannot.
        measurements = artifact.get("measurements")
        repetitions = _deep_get(artifact, ("workload", "repetitions"))
        prompt_tokens = _deep_get(artifact, ("workload", "prompt_tokens"))
        output_tokens = _deep_get(artifact, ("workload", "output_tokens"))
        rows = exec_doc.get("measured_stdout")
        if not isinstance(rows, list) or not rows:
            raw_contradictions.append("execution-evidence.json has no measured_stdout rows")
        else:
            if isinstance(repetitions, int) and not isinstance(repetitions, bool) \
                    and len(rows) != repetitions:
                raw_contradictions.append(
                    f"measured_stdout holds {len(rows)} repetitions but the artifact "
                    f"preregisters {repetitions}")
            runtime = artifact.get("runtime") if isinstance(artifact.get("runtime"), dict) else {}
            config_pairs = (
                ("n_batch", ("logical_batch",), "logical_batch"),
                ("n_ubatch", ("physical_ubatch",), "physical_ubatch"),
                ("type_k", ("kv_cache", "type_k"), "kv_cache_type_k"),
                ("type_v", ("kv_cache", "type_v"), "kv_cache_type_v"),
                ("n_gpu_layers", ("gpu_layers_requested",), "gpu_layers_requested"),
                ("split_mode", ("split_mode",), "split_mode"),
                ("main_gpu", ("main_gpu",), "main_gpu"),
                ("load_mode", ("load_mode",), "load_mode"),
            )
            for index, row in enumerate(rows):
                try:
                    parsed = json.loads(row) if isinstance(row, str) else row
                except json.JSONDecodeError:
                    raw_contradictions.append(f"measured_stdout[{index}] is not JSON")
                    continue
                if not isinstance(parsed, list) or len(parsed) != 2 \
                        or not all(isinstance(item, dict) for item in parsed):
                    raw_contradictions.append(
                        f"measured_stdout[{index}] is not exactly one prefill row and "
                        f"one decode row")
                    continue
                pp = parsed[0] if parsed[0].get("n_gen") == 0 else parsed[1]
                tg = parsed[1] if pp is parsed[0] else parsed[0]
                if pp is tg or tg.get("n_prompt") != 0 or pp.get("n_gen") != 0:
                    raw_contradictions.append(
                        f"measured_stdout[{index}] rows are not an unambiguous "
                        f"pp(n_gen=0)/tg(n_prompt=0) pair")
                    continue
                if prompt_tokens is not _MISSING and pp.get("n_prompt") != prompt_tokens:
                    raw_contradictions.append(
                        f"measured_stdout[{index}] prefill row n_prompt "
                        f"{pp.get('n_prompt')!r} contradicts the artifact workload "
                        f"prompt_tokens {prompt_tokens!r}")
                elif prompt_tokens is not _MISSING:
                    actual_prompt_tokens = pp.get("n_prompt")
                if output_tokens is not _MISSING and tg.get("n_gen") != output_tokens:
                    raw_contradictions.append(
                        f"measured_stdout[{index}] decode row n_gen "
                        f"{tg.get('n_gen')!r} contradicts the artifact workload "
                        f"output_tokens {output_tokens!r}")
                if isinstance(_deep_get(artifact, ("runtime", "kv_offload")), bool) \
                        and bool(pp.get("no_kv_offload")) == _deep_get(artifact, ("runtime", "kv_offload")):
                    raw_contradictions.append(
                        f"measured_stdout[{index}] no_kv_offload contradicts the "
                        f"artifact runtime kv_offload")
                for row_field, path, _label in config_pairs:
                    want = _deep_get(artifact, ("runtime",) + path)
                    if want is _MISSING:
                        continue  # absent sealed field is an axis-availability matter
                    if pp.get(row_field) != want or tg.get(row_field) != want:
                        raw_contradictions.append(
                            f"measured_stdout[{index}] {row_field} contradicts the "
                            f"artifact runtime {path[-1]} {want!r}")
                measurement = measurements[index] if isinstance(measurements, list) \
                    and index < len(measurements) and isinstance(measurements[index], dict) else None
                if measurement is None:
                    continue  # count/finiteness handled by availability checks
                if prompt_tokens is not _MISSING and pp.get("avg_ts") != measurement.get("tok_s_prefill"):
                    raw_contradictions.append(
                        f"measured_stdout[{index}] prefill avg_ts {pp.get('avg_ts')!r} "
                        f"does not equal the sealed tok_s_prefill "
                        f"{measurement.get('tok_s_prefill')!r} for repetition {index}")
                if output_tokens is not _MISSING and tg.get("avg_ts") != measurement.get("tok_s_out"):
                    raw_contradictions.append(
                        f"measured_stdout[{index}] decode avg_ts {tg.get('avg_ts')!r} "
                        f"does not equal the sealed tok_s_out "
                        f"{measurement.get('tok_s_out')!r} for repetition {index}")
    ttft_doc = _load_json(base_dir / "ttft-evidence.json", [], "ttft evidence") \
        if (base_dir / "ttft-evidence.json").is_file() else None
    if isinstance(artifact.get("ttft"), dict):
        if not isinstance(ttft_doc, dict):
            raw_contradictions.append(
                "ttft raw evidence pin missing — ttft-evidence.json is required "
                "to verify the sealed ttft samples")
        else:
            raw_files.setdefault("ttft-evidence.json", {})["cross_checked"] = True
            if ttft_doc.get("samples_ms") != artifact["ttft"].get("samples_ms"):
                raw_contradictions.append(
                    "ttft-evidence.json samples contradict the artifact ttft samples")
    for line in raw_contradictions:
        reasons.append(f"raw: companion evidence contradiction — {line}")

    sidecar_values = _verify_sidecar(expected, base_dir, out, reasons)

    # model artifact identity: the sealed benchmark authenticates benchmark
    # bytes, NOT the model artifact; the model file digest is verifiable only
    # through an immutable, digest-pinned sidecar reference (e.g. a model
    # manifest), never from the benchmark record itself
    if "model_artifact_sha256" in expected:
        actual = sidecar_values.get("model_artifact_sha256", _MISSING)
        if actual is _MISSING:
            reasons.append(
                "availability: model_artifact_sha256 is unavailable in the source — "
                "the producer record identifies the model artifact only by "
                "name/revision/quantization; its file digest must be verified "
                "through a digest-pinned qualification sidecar")
        elif not _values_equal(actual, expected["model_artifact_sha256"]):
            reasons.append(
                f"axis: model_artifact_sha256 expected "
                f"{expected['model_artifact_sha256']!r}, sidecar-verified source "
                f"value is {actual!r}")
        else:
            provenance["model_artifact_sha256"] = {
                "value": actual, "verification": "sidecar_verified"}

    # sidecar-fillable required axes with no native producer field:
    # cache_regime (cache-reuse policy) and timing_boundary (measured window).
    # Structural unavailability never relaxes the gate: absent => explicit
    # noncomparability, a verified pinned sidecar is the only satisfaction path.
    _TOP_LEVEL_SIDECAR_AXES = (
        "cache_regime",
        "timing_boundary",
    )
    _TOP_LEVEL_AXIS_NOTES = {
        "cache_regime": "the producer schema carries no explicit cache-reuse-regime "
                        "field; cache policy cannot be confirmed from the artifact bytes alone",
        "timing_boundary": "the producer schema carries no explicit timing-boundary "
                           "field; the measured window must be verified from pinned evidence",
    }
    for axis in _TOP_LEVEL_SIDECAR_AXES:
        if axis not in expected:
            continue
        actual = sidecar_values.get(axis, _MISSING)
        if actual is _MISSING:
            reasons.append(
                f"availability: {axis} is unavailable in the source — "
                f"{_TOP_LEVEL_AXIS_NOTES[axis]}; a digest-pinned qualification "
                f"sidecar is the only verification path")
        elif not _values_equal(actual, expected[axis]):
            reasons.append(
                f"axis: {axis} expected {expected[axis]!r}, sidecar-verified "
                f"source value is {actual!r}")
        else:
            provenance[axis] = {"value": actual, "verification": "sidecar_verified"}

    # --- identity / cache / workload axes -----------------------------------
    wanted_sections = {
        section: expected[section]
        for section in ("model", "engine", "hardware", "runtime", "workload")
        if isinstance(expected.get(section), dict)
    }
    for section, wanted in sorted(wanted_sections.items()):
        for key, want in sorted(wanted.items()):
            axis = f"{section}.{key}"
            path = _LOCALMAXXING_AXES.get(axis)
            if path is None:
                reasons.append(f"axis: unknown expected axis {axis} for "
                               f"{PRODUCER_LOCALMAXXING}")
                continue
            actual = _deep_get(artifact, path)
            if actual is None:  # explicit producer null = field not represented
                actual = _MISSING
            if actual is _MISSING and axis in sidecar_values:
                actual = sidecar_values[axis]
            if actual is _MISSING:
                reasons.append(
                    f"availability: {axis} is unavailable in the source — missing "
                    f"metadata is not satisfied by the expected value {want!r}; where "
                    f"the native format omits this field, a digest-pinned "
                    f"qualification sidecar is the only verification path")
                continue
            if not _values_equal(actual, want):
                reasons.append(f"axis: {axis} expected {want!r}, source has {actual!r}")
    _check_metric_units(expected, PRODUCER_LOCALMAXXING, reasons)

    # --- measurement availability -------------------------------------------
    workload = artifact.get("workload") if isinstance(artifact.get("workload"), dict) else {}
    repetitions = workload.get("repetitions")
    measurements = artifact.get("measurements")
    availability = {
        "measurements": AVAILABLE,
        "warmup_evidence": warmup_evidence,
        "cold_start": ABSENT,                       # no cold lane in this producer method
        "background_load_telemetry": UNAVAILABLE,   # set below
        "ttft": UNAVAILABLE,                        # set below
        "hardware": AVAILABLE if _deep_get(artifact, ("hardware", "gpuName")) is not _MISSING else UNAVAILABLE,
        "kv_cache_config": AVAILABLE if _deep_get(artifact, ("runtime", "kv_cache")) is not _MISSING else ABSENT,
        "cache_regime": AVAILABLE if "cache_regime" in sidecar_values else ABSENT,
        "timing_boundary": AVAILABLE if "timing_boundary" in sidecar_values else ABSENT,
        "context_length": AVAILABLE if _deep_get(artifact, ("workload", "context_length")) is not _MISSING
                          or "workload.context_length" in sidecar_values else ABSENT,
        "actual_prompt_tokens": AVAILABLE if actual_prompt_tokens is not _MISSING and raw_files.get(
            "execution-evidence.json", {}).get("cross_checked") else ABSENT,
    }
    if not isinstance(measurements, list) or not measurements:
        reasons.append("availability: no measured repetitions in the artifact")
        measurements = []
        availability["measurements"] = UNAVAILABLE
    elif not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        reasons.append("availability: workload.repetitions is unavailable or invalid "
                       "— the measured count cannot be checked against the "
                       "preregistered repetition policy")
        availability["measurements"] = UNAVAILABLE
    elif len(measurements) != repetitions:
        reasons.append(f"availability: missing observations — workload.repetitions "
                       f"is {repetitions} but {len(measurements)} measured repetitions "
                       f"are present")
        availability["measurements"] = UNAVAILABLE
    else:
        for index, item in enumerate(measurements):
            if not isinstance(item, dict) or not item:
                reasons.append(f"availability: measurement[{index}] is not a "
                               f"non-empty object")
                availability["measurements"] = UNAVAILABLE
                break
            for key, value in sorted(item.items()):
                if not _finite_positive(value):
                    reasons.append(f"availability: measurement[{index}].{key} is "
                                   f"missing or nonfinite: {value!r}")
                    availability["measurements"] = UNAVAILABLE

    def _mean_consistent(name, values, aggregate_key):
        aggregate = artifact.get("aggregate", {})
        if not isinstance(artifact.get("aggregate"), dict) or aggregate_key not in aggregate:
            return
        if len(values) and all(_finite_positive(v) for v in values):
            if aggregate[aggregate_key] != statistics.fmean(values):
                reasons.append(f"consistency: aggregate {aggregate_key} is not the "
                               f"arithmetic mean of the {name}")

    _mean_consistent("output measurements", [m.get("tok_s_out") for m in measurements
                                             if isinstance(m, dict)], "tok_s_out")
    _mean_consistent("prefill measurements", [m.get("tok_s_prefill") for m in measurements
                                              if isinstance(m, dict)], "tok_s_prefill")
    combined = artifact.get("combined_measurements")
    ttft = artifact.get("ttft") if isinstance(artifact.get("ttft"), dict) else None
    if combined is not None:
        if (not isinstance(combined, list) or not combined
                or not all(_finite_positive(v) for v in combined)):
            reasons.append("availability: combined_measurements contains missing or "
                           "nonfinite values")
        else:
            _mean_consistent("combined measurements", combined, "tok_s_total")
    telemetry = artifact.get("telemetry") if isinstance(artifact.get("telemetry"), dict) else None
    if telemetry is not None and telemetry.get("available"):
        samples = telemetry.get("samples")
        if isinstance(samples, list) and samples and all(isinstance(s, dict) for s in samples):
            powers = [s.get("power_draw_w") for s in samples]
            memories = [s.get("memory_used_mib") for s in samples]
            if not all(_finite_positive_or_zero(v) for v in powers + memories):
                reasons.append("availability: telemetry samples contain missing or "
                               "nonfinite values")
            else:
                availability["background_load_telemetry"] = AVAILABLE
                if telemetry.get("mean_power_w") != statistics.fmean(powers) or \
                        telemetry.get("peak_total_vram_mib") != max(memories):
                    reasons.append("consistency: telemetry aggregates do not match "
                                   "the telemetry samples")
        else:
            reasons.append("availability: telemetry declares availability without samples")
    if ttft is not None:
        samples = ttft.get("samples_ms")
        if isinstance(samples, list) and samples and all(_finite_positive(v) for v in samples):
            availability["ttft"] = AVAILABLE
            if ttft.get("mean_ms") != statistics.fmean(samples):
                reasons.append("consistency: ttft mean_ms is not the arithmetic mean "
                               "of the ttft samples")
        else:
            reasons.append("availability: ttft block has missing or nonfinite samples")

    # --- metrics -------------------------------------------------------------
    n = len(measurements)
    out["metrics"] = {
        "producer_schema": PRODUCER_LOCALMAXXING,
        "role": "practical_suite_measurement_module",
        "aggregate": artifact.get("aggregate") if isinstance(artifact.get("aggregate"), dict) else {},
        "summaries": {},
        "warmup_designation": {
            "excluded_by_producer_method": workload.get("warmup_repetitions"),
            "rule": "producer-method preregistered warmup; excluded before the "
                    "sealed artifact, never retrospectively",
            "warmup_evidence": warmup_evidence,
        },
        "ttft_role": "proxy_benchmark_ttft; never direct deployment TTFT",
        "evidence_availability": availability,
    }
    if availability["measurements"] == AVAILABLE and n:
        work = f"{METHOD_LOCALMAXXING}:pp{workload.get('prompt_tokens')}-og{workload.get('output_tokens')}"
        metric_policy = {"channel": "end_to_end", "workload": work, "warmup": 0,
                         "measured_per_batch": n, "max_batches": 1,
                         "cv_flag_threshold": DEFAULT_CV_FLAG_THRESHOLD}
        summaries = out["metrics"]["summaries"]
        for key, unit in (("tok_s_out", "tok/s"), ("tok_s_prefill", "tok/s")):
            values = [m.get(key) for m in measurements if isinstance(m, dict)
                      and _finite_positive(m.get(key))]
            if len(values) == n:
                summaries[key] = _summarize(values, {**metric_policy, "metric": key, "unit": unit})
        if isinstance(combined, list) and len(combined) == n and \
                all(_finite_positive(v) for v in combined):
            summaries["tok_s_total"] = _summarize(
                combined, {**metric_policy, "metric": "tok_s_total", "unit": "tok/s"})
        if availability["ttft"] == AVAILABLE:
            summaries["ttft_ms"] = _summarize(
                ttft["samples_ms"], {**metric_policy, "channel": "stream_first_token",
                                     "metric": "ttft_ms", "unit": "ms"})

    # --- provenance (native producer fields, verbatim) -----------------------
    for section in ("model", "engine", "hardware", "runtime", "workload"):
        if isinstance(artifact.get(section), dict):
            provenance[section] = artifact[section]
    provenance["command_provenance"] = artifact.get("command_provenance")
    provenance["created_at"] = artifact.get("created_at")
    if isinstance(telemetry, dict):
        provenance["telemetry_summary"] = {
            key: telemetry.get(key)
            for key in ("available", "source", "cadence_ms", "peak_total_vram_mib",
                        "mean_power_w", "peak_power_w", "peak_temperature_c",
                        "peak_utilization_gpu_pct")
            if key in telemetry
        }
    provenance["companion_files"] = sorted(
        name for name in LOCALMAXXING_COMPANION_FILES if name in raw_files)
    if sidecar_values:
        provenance["sidecar_verified_fill"] = dict(sorted(sidecar_values.items()))


def _finite_positive_or_zero(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def _import_result(record, base_dir, expected, out):
    """Bounded llmgauge.result.v0 import: identity, runtime/sampler/cache
    fields, suite/workload identity, per-task metric availability, referenced
    raw artifact hashes. Per-task metrics are single observations per prompt:
    cross-task pooling is prohibited and never performed."""
    reasons = out["reasons"]
    provenance = out["provenance"]
    run = record.get("run") if isinstance(record.get("run"), dict) else {}
    if run.get("status") != "completed":
        reasons.append(f"availability: run.status is {run.get('status')!r}, not a "
                       f"completed measurement run")
    if record.get("operation") or run.get("operation"):
        reasons.append("availability: dedicated import-result shapes carry no "
                       "native measurements")
        return
    results = record.get("results")
    if not isinstance(results, list) or not results:
        reasons.append("availability: no prompt results in the run record")
        results = []
    if expected.get("repetition_structure"):
        reasons.append(
            "availability: repetition_structure is unavailable in the source — "
            "llmgauge.result.v0 single-run results carry one observation per "
            "prompt with no warmup/repetition structure")
    _check_metric_units(expected, PRODUCER_RESULT, reasons)

    sidecar_values = _verify_sidecar(expected, base_dir, out, reasons)
    if "model_artifact_sha256" in expected:
        # result.v0 pins the model artifact through model.provenance.sha256
        actual = _deep_get(record, ("model", "provenance", "sha256"))
        if actual is None or actual is _MISSING:
            actual = sidecar_values.get("model_artifact_sha256", _MISSING)
            source_note = "model.provenance is absent or unavailable"
        else:
            source_note = None
        if actual is _MISSING:
            reasons.append(
                "availability: model_artifact_sha256 is unavailable in the source — "
                f"{source_note}; a digest-pinned qualification sidecar is the only "
                f"alternative verification path")
        elif not _values_equal(actual, expected["model_artifact_sha256"]):
            reasons.append(
                f"axis: model_artifact_sha256 expected "
                f"{expected['model_artifact_sha256']!r}, verified source value is "
                f"{actual!r}")
        else:
            provenance["model_artifact_sha256"] = {
                "value": actual,
                "verification": "model.provenance.sha256" if source_note is None
                else "sidecar_verified"}
    # sidecar-fillable required axes with no native result.v0 field:
    # cache_regime (cache-reuse policy) and timing_boundary (measured window).
    # Absent => explicit noncomparability; a verified pinned sidecar is the
    # only satisfaction path.
    for axis in ("cache_regime", "timing_boundary"):
        if axis not in expected:
            continue
        actual = sidecar_values.get(axis, _MISSING)
        if actual is _MISSING:
            reasons.append(
                f"availability: {axis} is unavailable in the source — result.v0 "
                f"carries no such native field; a digest-pinned qualification "
                f"sidecar is the only verification path")
        elif not _values_equal(actual, expected[axis]):
            reasons.append(
                f"axis: {axis} expected {expected[axis]!r}, sidecar-verified "
                f"source value is {actual!r}")
        else:
            provenance[axis] = {"value": actual, "verification": "sidecar_verified"}
    for section, wanted in sorted(
            (section, expected[section])
            for section in ("model", "engine", "hardware", "runtime", "workload")
            if isinstance(expected.get(section), dict)):
        for key, want in sorted(wanted.items()):
            axis = f"{section}.{key}"
            path = _RESULT_AXES.get(axis)
            if path is None and axis not in _RESULT_AXES:
                reasons.append(f"axis: unknown expected axis {axis} for {PRODUCER_RESULT}")
                continue
            if path is None:
                # known axis with no native result.v0 field (hardware.*):
                # sidecar fill is the only verification path
                actual = sidecar_values.get(axis, _MISSING)
                if actual is _MISSING:
                    reasons.append(
                        f"availability: {axis} is unavailable in the source — result.v0 "
                        f"carries no hardware/host facts; a digest-pinned qualification "
                        f"sidecar is the only verification path")
                    continue
                if not _values_equal(actual, want):
                    reasons.append(
                        f"axis: {axis} expected {want!r}, sidecar-verified source "
                        f"value is {actual!r}")
                else:
                    provenance.setdefault("sidecar_verified_axes", {})[axis] = actual
                continue
            actual = _deep_get(record, path)
            if actual is None:  # explicit producer null = field not represented
                actual = _MISSING
            if actual is _MISSING and axis in sidecar_values:
                actual = sidecar_values[axis]
            if actual is _MISSING:
                reasons.append(
                    f"availability: {axis} is unavailable in the source — missing "
                    f"metadata is not satisfied by the expected value {want!r}; where "
                    f"the native format omits this field, a digest-pinned "
                    f"qualification sidecar is the only verification path")
                continue
            if not _values_equal(actual, want):
                reasons.append(f"axis: {axis} expected {want!r}, source has {actual!r}")
    if "artifact_fingerprint" in expected:
        reasons.append(
            "hash: artifact_fingerprint comparison is unavailable for result.v0 "
            "in this contract version; use artifact_sha256 and the referenced-"
            "artifact digests")

    # referenced raw artifact hashes (read-only verification)
    raw_refs = {}
    broken = []
    for entry in results:
        if not isinstance(entry, dict):
            broken.append("a results entry is not an object")
            continue
        for ref_key in ("raw_prompt_path", "raw_output_path", "stderr_log_path",
                        "cleaned_output_path"):
            relative = entry.get(ref_key)
            if relative is None:
                continue
            if relative in raw_refs:
                continue
            path = _resolve_under(base_dir, relative)
            if path is None or not path.is_file():
                broken.append(f"{ref_key} reference missing or escapes the result "
                              f"directory: {relative!r}")
                raw_refs[relative] = {"sha256": UNAVAILABLE}
            else:
                raw_refs[relative] = {"sha256": _sha256_file(path)}
    transcript = record.get("transcript") if isinstance(record.get("transcript"), dict) else None
    if transcript is not None:
        relative = transcript.get("path")
        path = _resolve_under(base_dir, relative) if isinstance(relative, str) else None
        if path is None or not path.is_file():
            broken.append(f"transcript reference missing or escapes the result "
                          f"directory: {relative!r}")
        else:
            actual = _sha256_file(path)
            raw_refs.setdefault(relative, {"sha256": actual})["transcript"] = True
            if transcript.get("sha256") != actual:
                broken.append(f"transcript sha256 mismatch for {relative!r} — "
                              f"referenced raw hash does not verify")
    for line in broken:
        reasons.append(f"raw: {line}")
    provenance["raw_files"] = raw_refs
    provenance["run_fingerprint"] = {
        "value": record.get("run_fingerprint"),
        "verification": "recorded_not_recomputed (producer payload versions vary; "
                        "file and referenced-artifact digests are verified)",
    }

    metrics = {
        "producer_schema": PRODUCER_RESULT,
        "role": "practical_suite_run_evidence",
        "summary": record.get("summary") if isinstance(record.get("summary"), dict) else {},
        "per_prompt": [],
        "pooling": "per-task single observations; different prompts are different "
                   "workloads and are never pooled into one summary",
        "evidence_availability": {
            "measurements": AVAILABLE if results and not any(
                not isinstance(entry, dict) or not isinstance(entry.get("metrics"), dict)
                for entry in results) else UNAVAILABLE,
            "warmup_evidence": ABSENT,
            "cold_start": ABSENT,
            "background_load_telemetry": ABSENT,
            "ttft": ABSENT,
            "raw_referenced_artifacts": AVAILABLE if raw_refs and not broken else UNAVAILABLE,
            "kv_cache_config": AVAILABLE if _deep_get(record, ("runtime", "cache_type_k")) is not _MISSING else ABSENT,
            "hardware": AVAILABLE if "hardware.gpu_name" in sidecar_values else ABSENT,
            "cache_regime": AVAILABLE if "cache_regime" in sidecar_values else ABSENT,
            "timing_boundary": AVAILABLE if "timing_boundary" in sidecar_values else ABSENT,
            "context_length": AVAILABLE if _deep_get(record, ("runtime", "ctx_size")) is not _MISSING else ABSENT,
        },
    }
    for entry in results:
        if not isinstance(entry, dict):
            continue
        record_out = {"prompt_id": entry.get("prompt_id"),
                      "status": entry.get("status")}
        metric_values = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else {}
        for name, value in sorted(metric_values.items()):
            if value is None:
                record_out[name] = UNAVAILABLE
            elif isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and not math.isfinite(value):
                record_out[name] = f"nonfinite: {value!r}"
                reasons.append(f"availability: metrics.{name} for prompt "
                               f"{entry.get('prompt_id')!r} is nonfinite")
            else:
                record_out[name] = value
        metrics["per_prompt"].append(record_out)
    out["metrics"] = metrics

    for section in ("model", "runtime", "suite"):
        if isinstance(record.get(section), dict):
            provenance[section] = record[section]
    provenance["run"] = run
    provenance["llmgauge_version"] = record.get("llmgauge_version")
    if sidecar_values:
        provenance["sidecar_verified_fill"] = dict(sorted(sidecar_values.items()))


# ---------------------------------------------------------------------------
# CLI + selftest
# ---------------------------------------------------------------------------

def _cli_import(argv):
    if len(argv) != 2:
        print("usage: measurement.py import SOURCE EXPECTED_JSON", file=sys.stderr)
        return 2
    try:
        with open(argv[1], "r", encoding="utf-8") as handle:
            expected = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read expected JSON: {exc}", file=sys.stderr)
        return 2
    result = import_llmgauge(Path(argv[0]), expected)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == STATUS_COMPATIBLE else 1


def _cli_summarize(argv):
    if len(argv) != 1:
        print("usage: measurement.py summarize INPUT_JSON", file=sys.stderr)
        return 2
    try:
        with open(argv[0], "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or "values" not in payload:
            raise MeasurementError('input JSON must be {"values": [...], "policy": {...}}')
        summary = summarize_repetitions(payload["values"], payload.get("policy", {}))
    except (OSError, json.JSONDecodeError, MeasurementError) as exc:
        print(f"summarize failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


# --- synthetic native-shaped fixture builder (selftest only) ----------------

def _synthetic_artifact(directory, *, measurements=None, hf_id="test/example-model-GGUF",
                        engine_version="b9+deadbeef", gpu_name="Test GPU 9000",
                        kv_type_k="f16", kv_offload=True, output_tokens=128,
                        include_kv_cache=True, profile="test-profile", nan=False,
                        with_execution_evidence=True, with_ttft_evidence=True,
                        with_model_manifest=True):
    """Build a self-consistent llmgauge.localmaxxing_benchmark.v1 artifact
    directory: benchmark.json + internally consistent companion raw evidence
    (positional per-repetition pp/tg rows) + a model-manifest.json for the
    model-artifact identity pin."""
    directory.mkdir(parents=True, exist_ok=True)
    reps = 5 if measurements is None else measurements
    meas = [{"tok_s_out": 100.0 + i, "tok_s_prefill": 2000.0 + 10 * i} for i in range(reps)]
    combined = [40.0 + i for i in range(reps)]
    ttft_samples = [50.0 + i for i in range(reps)]
    if nan and meas:
        meas[0]["tok_s_out"] = float("nan")
    runtime = {
        "device": "auto", "flash_attention_requested": "auto",
        "gpu_layers_requested": -1, "gpu_placement": "full_gpu",
        **({"kv_cache": {"type_k": kv_type_k, "type_v": "f16"}} if include_kv_cache else {}),
        "kv_offload": kv_offload, "load_mode": "auto", "logical_batch": 2048,
        "main_gpu": 0, "physical_ubatch": 512, "split_mode": "layer",
    }
    artifact = {
        "schema_version": PRODUCER_LOCALMAXXING,
        "artifact_version": 1,
        "method": METHOD_LOCALMAXXING,
        "created_at": "2026-09-24T00:00:00+00:00",
        "model": {"hf_id": hf_id, "revision": "0000000000000000000000000000000000000000",
                  "local_reference": "example-model-Q6_K.gguf",
                  "quantization": "Q6_K", "profile": profile},
        "engine": {"name": "llama.cpp", "version": engine_version,
                   "backend": "cuda", "executable": "llama-bench"},
        "hardware": {"cpu": "Test CPU", "gpuCount": 1, "gpuName": gpu_name,
                     "hwClass": "DISCRETE_GPU", "os": "Test OS x86_64",
                     "ramGb": 32.0, "vramGb": 12.0},
        "workload": {"prompt_tokens": 512, "output_tokens": output_tokens,
                     "batch_size": 1, "repetitions": len(meas),
                     "warmup_repetitions": 1, "gpu_layers": -1,
                     "context_length": 32768,
                     "sampling": "llama-bench deterministic"},
        "measurements": meas,
        "aggregate": {
            "tok_s_out": statistics.fmean(m["tok_s_out"] for m in meas),
            "tok_s_prefill": statistics.fmean(m["tok_s_prefill"] for m in meas),
            "tok_s_total": statistics.fmean(combined),
        },
        "command_provenance": "llama-bench -m example-model-Q6_K.gguf -p 512 "
                              "-n 128 -b 2048 -ub 512 -ngl -1 -o json -r 1",
        "runtime": runtime,
        "combined_measurements": combined,
        "ttft": {"mean_ms": statistics.fmean(ttft_samples), "samples_ms": ttft_samples},
        "telemetry": {"available": True, "source": "nvidia-smi", "cadence_ms": 200,
                      "peak_total_vram_mib": 7000.0, "mean_power_w": 90.0,
                      "samples": [{"memory_used_mib": 7000.0, "power_draw_w": 90.0,
                                   "temperature_c": 40.0, "timestamp_monotonic": 1.0,
                                   "utilization_gpu_pct": 90.0}]},
    }
    artifact["fingerprint"] = _producer_fingerprint(artifact)
    (directory / "benchmark.json").write_text(
        json.dumps(artifact, indent=1, allow_nan=True), encoding="utf-8")
    if with_model_manifest:
        # immutable model-artifact identity reference (the benchmark record
        # itself cannot carry the model file digest)
        (directory / "model-manifest.json").write_text(json.dumps({
            "manifest": "welp-model-artifact-manifest/1",
            "path": "example-model-Q6_K.gguf",
            "size_bytes": 6951548672,
            "sha256": "aa" * 32,
        }, indent=1), encoding="utf-8")
        # immutable run-qualification reference for axes the native benchmark
        # record cannot carry (cache-reuse regime, timing boundary)
        (directory / "run-qualification.json").write_text(json.dumps({
            "qualification": "welp-run-qualification/1",
            "cache_regime": "uncached_cold_per_repetition",
            "timing_boundary": "decode_output_tokens_only_after_prefill",
        }, indent=1), encoding="utf-8")

    def bench_row(row_pp, avg_ts):
        return {
            "build_commit": "deadbeef", "build_number": 9, "cpu_info": "Test CPU",
            "gpu_info": gpu_name, "backends": "CUDA",
            "model_filename": "example-model-Q6_K.gguf",
            "model_type": "testmodel 8B Q6_K", "model_size": 6951548672,
            "n_batch": runtime["logical_batch"], "n_ubatch": runtime["physical_ubatch"],
            "n_threads": 8, "type_k": kv_type_k, "type_v": "f16",
            "n_gpu_layers": runtime["gpu_layers_requested"],
            "no_kv_offload": not kv_offload, "split_mode": runtime["split_mode"],
            "main_gpu": runtime["main_gpu"], "flash_attn": -1, "devices": "auto",
            "load_mode": runtime["load_mode"],
            "n_prompt": 512 if row_pp else 0,
            "n_gen": 0 if row_pp else output_tokens,
            "avg_ts": avg_ts,
        }

    if with_execution_evidence:
        rows = []
        for m in meas:
            rows.append(json.dumps([bench_row(True, m["tok_s_prefill"]),
                                    bench_row(False, m["tok_s_out"])]))
        execution = {
            "backend": "cuda", "engine_version": engine_version,
            "executable": "llama-bench", "exit_status": 0,
            "model_path": "example-model-Q6_K.gguf", "profile": profile,
            "runtime": runtime,
            "warmup_stdout": json.dumps([bench_row(True, 1990.0),
                                         bench_row(False, 98.0)]),
            "measured_stdout": rows,
        }
        (directory / "execution-evidence.json").write_text(
            json.dumps(execution, indent=1), encoding="utf-8")
    if with_ttft_evidence:
        (directory / "ttft-evidence.json").write_text(json.dumps({
            "command": ["llama-server", "-m", "example-model-Q6_K.gguf"],
            "repetitions": len(ttft_samples), "samples_ms": ttft_samples,
            "warmup_excluded": True,
        }, indent=1), encoding="utf-8")
    (directory / "telemetry-evidence.json").write_text(json.dumps(
        {"source": "nvidia-smi", "samples": artifact["telemetry"]["samples"]},
        indent=1), encoding="utf-8")
    return artifact


def _full_expected(directory, artifact, **overrides):
    """The complete frozen expectation for the synthetic positive case: every
    REQUIRED_EXPECTED_AXIS for the localmaxxing producer. cache_regime and
    timing_boundary have no native producer field and are satisfied through the
    digest-pinned sidecar referencing run-qualification.json; the model-artifact
    identity pin is likewise sidecar-verified; workload.context_length matches
    the native optional producer field."""
    expected = {
        "artifact_sha256": _sha256_file(directory / "benchmark.json"),
        "model_artifact_sha256": "aa" * 32,
        "cache_regime": "uncached_cold_per_repetition",
        "timing_boundary": "decode_output_tokens_only_after_prefill",
        "metric_units": {"tok_s_out": "tok/s", "tok_s_prefill": "tok/s",
                         "ttft_ms": "ms"},
        "model": {"hf_id": "test/example-model-GGUF", "quantization": "Q6_K",
                  "revision": "0000000000000000000000000000000000000000",
                  "local_reference": "example-model-Q6_K.gguf"},
        "engine": {"name": "llama.cpp", "version": "b9+deadbeef", "backend": "cuda"},
        "hardware": {"gpu_name": "Test GPU 9000", "hw_class": "DISCRETE_GPU"},
        "runtime": {"gpu_placement": "full_gpu", "gpu_layers_requested": -1,
                    "kv_offload": True, "kv_cache_type_k": "f16",
                    "kv_cache_type_v": "f16"},
        "workload": {"prompt_tokens": 512, "output_tokens": 128, "batch_size": 1,
                     "repetitions": len(artifact["measurements"]) if artifact else 5,
                     "warmup_repetitions": 1, "context_length": 32768},
        "qualification_sidecar": {
            "path": str(directory / "model-manifest-sidecar.json"),
            "expected_sha256": None,  # filled below after writing
        },
    }
    qual_sha = _sha256_file(directory / "run-qualification.json")
    sidecar = {
        "sidecar": "welp-measurement-qualification-sidecar/1",
        "fields": {
            "model_artifact_sha256": {
                "value": "aa" * 32,
                "evidence": {"path": "model-manifest.json",
                             "sha256": _sha256_file(directory / "model-manifest.json"),
                             "json_pointer": "/sha256"}},
            "cache_regime": {
                "value": "uncached_cold_per_repetition",
                "evidence": {"path": "run-qualification.json",
                             "sha256": qual_sha,
                             "json_pointer": "/cache_regime"}},
            "timing_boundary": {
                "value": "decode_output_tokens_only_after_prefill",
                "evidence": {"path": "run-qualification.json",
                             "sha256": qual_sha,
                             "json_pointer": "/timing_boundary"}},
        },
    }
    sidecar_path = directory / "model-manifest-sidecar.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=1), encoding="utf-8")
    expected["qualification_sidecar"]["expected_sha256"] = _sha256_file(sidecar_path)
    expected.update(overrides)
    return expected


def _expect_compatible(case, result):
    assert result["status"] == STATUS_COMPATIBLE, \
        f"{case}: expected COMPATIBLE, got reasons: {result['reasons']}"


def _expect_reason(case, result, prefix):
    assert result["status"] == STATUS_NON_COMPARABLE, \
        f"{case}: expected NON_COMPARABLE, got {result['status']}"
    assert any(reason.startswith(prefix) for reason in result["reasons"]), \
        f"{case}: no reason starting {prefix!r} in {result['reasons']}"


def selftest() -> int:
    fails = []
    tmp = tempfile.TemporaryDirectory(prefix="welp-measurement-selftest-")
    root = Path(tmp.name)

    def check(name, fn):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            fails.append(str(exc))
            print(f"FAIL {name}: {exc}")

    # ---- deterministic summarization ---------------------------------------
    def summary_exact():
        s = summarize_repetitions(
            [10.0, 12.0, 8.0, 11.0, 9.0],
            {"metric": "tok_s_out", "unit": "tok/s", "warmup": 1,
             "measured_per_batch": 4, "cv_flag_threshold": 0.10})
        w = s["warmed"]
        assert w["raw_values"] == [10.0, 12.0, 8.0, 11.0, 9.0]
        assert w["warmup_values"] == [10.0] and w["warmup_excluded"] == 1
        assert w["measured_values"] == [12.0, 8.0, 11.0, 9.0] and w["n"] == 4
        assert w["mean"] == 10.0 and w["median"] == 10.0
        assert w["min"] == 8.0 and w["max"] == 12.0
        assert abs(w["sample_sd"] - 1.8257418583505538) < 1e-12
        assert abs(w["cv"] - 0.18257418583505539) < 1e-12
        assert w["variance_flag"] == {"triggered": True, "evaluated": True,
                                      "threshold": 0.10,
                                      "rule": "cv > threshold on the reported observation set; "
                                              "preregistered policy trigger only"}
        assert w["outlier_removal"] == "none"
        assert w["confidence_interval"] == "none; IID confidence intervals unsupported"
        # determinism: identical inputs -> identical output
        s2 = summarize_repetitions(
            [10.0, 12.0, 8.0, 11.0, 9.0],
            {"metric": "tok_s_out", "unit": "tok/s", "warmup": 1,
             "measured_per_batch": 4, "cv_flag_threshold": 0.10})
        assert json.dumps(s, sort_keys=True) == json.dumps(s2, sort_keys=True)
    check("summarize: exact deterministic stats + warmup exclusion", summary_exact)

    def summary_cv_below():
        s = summarize_repetitions([1.0, 2.0], {"warmup": 0, "measured_per_batch": 2})
        w = s["warmed"]
        assert w["mean"] == 1.5 and abs(w["cv"] - 0.4714045207910317) < 1e-12
        s2 = summarize_repetitions([10.0, 10.5, 10.0, 10.5],
                                   {"warmup": 0, "measured_per_batch": 4})
        assert s2["warmed"]["variance_flag"]["triggered"] is False
        s3 = summarize_repetitions([10.0], {"warmup": 0, "measured_per_batch": 1})
        assert s3["warmed"]["sample_sd"] is None and s3["warmed"]["cv"] is None
        assert s3["warmed"]["variance_flag"]["evaluated"] is False
        s4 = summarize_repetitions([10.0, 10.1],
                                   {"warmup": 0, "measured_per_batch": 2,
                                    "cv_flag_threshold": None})
        assert s4["warmed"]["variance_flag"]["evaluated"] is False
        assert s4["warmed"]["variance_flag"]["threshold"] is None
    check("summarize: variance flag is preregistered-trigger only; n=1 sd undefined", summary_cv_below)

    def summary_cold_warmed():
        s = summarize_repetitions(
            {"warmed": [1.0, 0.0, 2.0, 3.0, 4.0], "cold": [0.5, 9.0, 8.0]},
            {"warmup": 1, "measured_per_batch": 4,
             "cold_start": {"warmup": 1, "measured_per_batch": 2}})
        assert s["warmed"]["n"] == 4 and s["cold_start"]["n"] == 2
        assert s["cold_start"]["lane"] == "cold_process_startup"
        assert s["cold_start"]["measured_values"] == [9.0, 8.0]
        assert s["cold_start"]["warmup_values"] == [0.5]
        pooled = [v for lane in (s["warmed"], s["cold_start"]) for v in lane["measured_values"]]
        assert sorted(pooled) == [0.0, 2.0, 3.0, 4.0, 8.0, 9.0]  # lanes reported, never merged
    check("summarize: cold-start vs warmed lanes separate", summary_cold_warmed)

    def summary_second_batch():
        values = [9.0] + [10.0, 11.0, 12.0, 13.0, 14.0] + [15.0, 16.0, 17.0, 18.0, 19.0]
        s = summarize_repetitions(values, {"warmup": 1, "measured_per_batch": 5,
                                           "max_batches": 2})
        w = s["warmed"]
        assert w["n"] == 10 and w["raw_values"] == values
        assert w["mean"] == statistics.fmean(values[1:])
        try:
            summarize_repetitions(values, {"warmup": 1, "measured_per_batch": 5})
            raise AssertionError("unpreregistered second batch accepted")
        except MeasurementError:
            pass
        try:
            summarize_repetitions(values + [1.0], {"warmup": 1, "measured_per_batch": 5,
                                                   "max_batches": 2})
            raise AssertionError("third batch accepted")
        except MeasurementError:
            pass
    check("summarize: preregistered second batch pooled, all reported; extra batch rejected", summary_second_batch)

    def summary_trigger_extension():
        # second batch accepted ONLY on a first-batch variance trigger
        values = [9.0] + [10.0, 11.0, 12.0, 13.0, 14.0] + [12.0] * 5
        s = summarize_repetitions(values, {"warmup": 1, "measured_per_batch": 5,
                                           "max_batches": 2})
        w = s["warmed"]
        assert w["status"] == "complete"
        assert w["first_batch"]["measured_values"] == [10.0, 11.0, 12.0, 13.0, 14.0]
        assert w["first_batch"]["variance_trigger"] is True   # cv ~0.13 > 0.10
        assert w["residual_flag"]["triggered"] is False       # pooled cv ~0.088 < 0.10
        # pending: trigger fired but the preregistered additional batch has not run
        pending = summarize_repetitions(
            [9.0, 1.0, 10.0, 1.0, 10.0, 1.0],
            {"warmup": 1, "measured_per_batch": 5, "max_batches": 2})
        pw = pending["warmed"]
        assert pw["status"] == "pending_additional_batch"
        assert pw["first_batch"]["variance_trigger"] is True and pw["n"] == 5
        # untriggered second batch is rejected outright
        try:
            summarize_repetitions(
                [9.0, 10.0, 10.1, 10.0, 10.1, 10.0, 11.0, 11.0, 11.0, 11.0, 11.0],
                {"warmup": 1, "measured_per_batch": 5, "max_batches": 2})
            raise AssertionError("untriggered second batch accepted")
        except MeasurementError:
            pass
        # explicit per-batch warmups exclude the first observation of EACH batch
        values = [100.0, 1.0, 10.0, 1.0, 10.0, 1.0,
                  200.0, 5.0, 5.0, 5.0, 5.0, 5.0]
        s = summarize_repetitions(values, {"batch_warmups": [1, 1],
                                           "measured_per_batch": 5, "max_batches": 2})
        w = s["warmed"]
        assert w["warmup_values"] == [100.0, 200.0], w["warmup_values"]
        assert w["measured_values"] == [1.0, 10.0, 1.0, 10.0, 1.0, 5.0, 5.0, 5.0, 5.0, 5.0]
        assert w["first_batch"]["variance_trigger"] is True
        assert w["status"] == "complete" and w["residual_flag"]["triggered"] is True
        # policy type discipline
        for policy in ({"max_batches": True}, {"max_batches": 1.0}):
            try:
                summarize_repetitions([1.0, 2.0], policy)
                raise AssertionError(f"invalid max_batches accepted: {policy!r}")
            except MeasurementError:
                pass
        # cold-start form requires exactly both lanes
        try:
            summarize_repetitions({"warmed": [1.0, 2.0]},
                                  {"cold_start": {"measured_per_batch": 1}})
            raise AssertionError("missing cold lane accepted")
        except MeasurementError:
            pass
    check("summarize: trigger-gated extension, pending status, batch-major warmups, policy discipline", summary_trigger_extension)

    def summary_rejections():
        for bad in (float("nan"), float("inf"), -1.0, True, "5", None):
            try:
                summarize_repetitions([1.0, bad], {"warmup": 0, "measured_per_batch": 2})
                raise AssertionError(f"bad value accepted: {bad!r}")
            except MeasurementError:
                pass
        for bad_values, policy in (
            ([1.0], {"warmup": 1, "measured_per_batch": 5}),
            ([], {}),
            ([1.0], {"warmup": 0, "measured_per_batch": 1, "channel": "pooled"}),
            ([1.0, 2.0], {"warmup": 0, "measured_per_batch": 2, "cold_start": {"measured_per_batch": 1}}),
            ({"warmed": [1.0]}, {}),
        ):
            try:
                summarize_repetitions(bad_values, policy)
                raise AssertionError(f"bad input accepted: {bad_values!r} {policy}")
            except MeasurementError:
                pass
    check("summarize: nonfinite/missing/invalid policy rejected", summary_rejections)

    # ---- native-compatible synthetic import ---------------------------------

    def import_compatible():
        directory = root / "compatible"
        artifact = _synthetic_artifact(directory)
        result = import_llmgauge(directory, _full_expected(directory, artifact))
        _expect_compatible("native-compatible synthetic import", result)
        assert result["provenance"]["fingerprint_verified"] is True
        assert result["provenance"]["model_artifact_sha256"] == {
            "value": "aa" * 32, "verification": "sidecar_verified"}
        assert result["metrics"]["evidence_availability"]["background_load_telemetry"] == AVAILABLE
        assert result["metrics"]["evidence_availability"]["warmup_evidence"] == AVAILABLE
        assert result["metrics"]["evidence_availability"]["cache_regime"] == AVAILABLE
        assert result["metrics"]["evidence_availability"]["timing_boundary"] == AVAILABLE
        assert result["metrics"]["evidence_availability"]["context_length"] == AVAILABLE
        assert result["metrics"]["evidence_availability"]["cold_start"] == ABSENT
        assert result["metrics"]["evidence_availability"]["actual_prompt_tokens"] == AVAILABLE
        assert result["metrics"]["ttft_role"].startswith("proxy_benchmark_ttft")
        assert result["metrics"]["summaries"]["tok_s_out"]["warmed"]["n"] == 5
        assert result["metrics"]["summaries"]["ttft_ms"]["channel"] == "stream_first_token"
        # unknown optional fields tolerated (resealed exactly as a producer would)
        artifact["some_future_optional_field"] = {"anything": [1, 2, 3]}
        artifact["fingerprint"] = _producer_fingerprint(artifact)
        (directory / "benchmark.json").write_text(json.dumps(artifact, indent=1),
                                                  encoding="utf-8")
        result2 = import_llmgauge(directory, _full_expected(directory, artifact))
        _expect_compatible("unknown optional field tolerated", result2)
    check("import: native-compatible synthetic artifact (full identity, positional raw pin, sidecar)", import_compatible)

    def import_identity_enforcement():
        directory = root / "identity-enforcement"
        artifact = _synthetic_artifact(directory)
        result = import_llmgauge(directory, {})
        _expect_reason("empty expected", result,
                       "schema: expected comparison identity incomplete")
        assert sum(1 for r in result["reasons"] if r.startswith("schema:")) >= 20
        result = import_llmgauge(directory, {"model": {"hf_id": "test/example-model-GGUF"}})
        _expect_reason("partial expected", result,
                       "schema: expected comparison identity incomplete")
        full = _full_expected(directory, artifact)
        full["artifact_fingerprint_typo"] = "x"
        result = import_llmgauge(directory, full)
        _expect_reason("unknown top-level expected key", result,
                       "axis: unknown expected key")
        full = _full_expected(directory, artifact)
        full["engine"]["versoin"] = "b9+deadbeef"  # typo'd axis key
        result = import_llmgauge(directory, full)
        _expect_reason("unknown section axis key", result,
                       "axis: unknown expected axis engine.versoin")
    check("import: complete preregistered identity required; unknown keys reject", import_identity_enforcement)

    def import_identity_mismatches():
        directory = root / "identity"
        artifact = _synthetic_artifact(directory)
        tampered = dict(artifact)
        tampered["measurements"] = [dict(m, tok_s_out=m["tok_s_out"] + 1) for m in artifact["measurements"]]
        tampered["fingerprint"] = artifact["fingerprint"]
        (directory / "benchmark.json").write_text(json.dumps(tampered, indent=1), encoding="utf-8")
        _expect_reason("fingerprint tamper",
                       import_llmgauge(directory, _full_expected(directory, artifact)), "hash:")
        full = _full_expected(directory, artifact)
        full["model"]["hf_id"] = "test/other-GGUF"
        _expect_reason("hf_id mismatch", import_llmgauge(directory, full), "axis: model.hf_id")
        full = _full_expected(directory, artifact)
        full["engine"]["version"] = "b1+other"
        _expect_reason("engine build mismatch", import_llmgauge(directory, full),
                       "axis: engine.version")
        full = _full_expected(directory, artifact)
        full["hardware"]["gpu_name"] = "Other GPU"
        _expect_reason("hardware mismatch", import_llmgauge(directory, full),
                       "axis: hardware.gpu_name")
        full = _full_expected(directory, artifact)
        full["artifact_sha256"] = "0" * 64
        _expect_reason("file digest mismatch", import_llmgauge(directory, full),
                       "hash: artifact file sha256")
        full = _full_expected(directory, artifact)
        full["model_artifact_sha256"] = "bb" * 32
        _expect_reason("model artifact sha mismatch", import_llmgauge(directory, full),
                       "axis: model_artifact_sha256")
    check("import: identity mismatches (fingerprint, model, engine, hardware, digests)", import_identity_mismatches)

    def import_cache_mismatches():
        directory = root / "cache"
        artifact = _synthetic_artifact(directory)
        full = _full_expected(directory, artifact)
        full["runtime"]["kv_cache_type_k"] = "bf16"
        _expect_reason("kv type k mismatch", import_llmgauge(directory, full),
                       "axis: runtime.kv_cache_type_k")
        full = _full_expected(directory, artifact)
        full["runtime"]["kv_offload"] = False
        _expect_reason("kv offload mismatch", import_llmgauge(directory, full),
                       "axis: runtime.kv_offload")
        full = _full_expected(directory, artifact)
        full["cache_regime"] = "cached_serving"
        _expect_reason("cache_regime mismatch vs sidecar-verified value",
                       import_llmgauge(directory, full), "axis: cache_regime")
        # sidecar stripped of the cache_regime fill: required axis unavailable
        full = _full_expected(directory, artifact)
        sidecar = json.loads((directory / "model-manifest-sidecar.json").read_text())
        del sidecar["fields"]["cache_regime"]
        (directory / "model-manifest-sidecar.json").write_text(json.dumps(sidecar, indent=1),
                                                              encoding="utf-8")
        full["qualification_sidecar"]["expected_sha256"] = _sha256_file(
            directory / "model-manifest-sidecar.json")
        _expect_reason("cache_regime unavailable without sidecar fill",
                       import_llmgauge(directory, full),
                       "availability: cache_regime")
        no_kv = root / "cache-no-kv"
        _synthetic_artifact(no_kv, include_kv_cache=False)
        result = import_llmgauge(no_kv, _full_expected(no_kv, None))
        _expect_reason("missing kv metadata not satisfied by expectation",
                       result, "availability: runtime.kv_cache_type_k")
    check("import: cache mismatches + missing-metadata discipline", import_cache_mismatches)

    def import_unit_metric_mismatches():
        directory = root / "units"
        artifact = _synthetic_artifact(directory)
        full = _full_expected(directory, artifact)
        full["metric_units"]["ttft_ms"] = "s"
        _expect_reason("unit definition mismatch", import_llmgauge(directory, full),
                       "unit: ttft_ms")
        full = _full_expected(directory, artifact)
        full["metric_units"]["mmlu_acc"] = "ratio"
        _expect_reason("unknown metric unit expectation", import_llmgauge(directory, full),
                       "unit: metric unit")
        full = _full_expected(directory, artifact)
        full["workload"]["output_tokens"] = 256
        _expect_reason("workload mismatch", import_llmgauge(directory, full),
                       "axis: workload.output_tokens")
        full = _full_expected(directory, artifact)
        full["workload"]["context_length"] = 16384
        _expect_reason("context_length native mismatch", import_llmgauge(directory, full),
                       "axis: workload.context_length")
        # context_length stripped from the native artifact: sidecar or fail
        no_ctx = root / "no-context"
        artifact = _synthetic_artifact(no_ctx)
        del artifact["workload"]["context_length"]
        artifact["fingerprint"] = _producer_fingerprint(artifact)
        (no_ctx / "benchmark.json").write_text(json.dumps(artifact, indent=1), encoding="utf-8")
        full = _full_expected(no_ctx, artifact)  # still demands context_length 32768
        _expect_reason("context_length unavailable without sidecar fill",
                       import_llmgauge(no_ctx, full),
                       "availability: workload.context_length")
    check("import: unit/metric/workload mismatches", import_unit_metric_mismatches)

    def import_repetition_availability():
        directory = root / "missing-obs"
        artifact = _synthetic_artifact(directory, measurements=4)
        artifact["workload"]["repetitions"] = 5  # preregistered 5, only 4 sealed
        artifact["fingerprint"] = _producer_fingerprint(artifact)
        (directory / "benchmark.json").write_text(json.dumps(artifact, indent=1, allow_nan=True),
                                                  encoding="utf-8")
        full = _full_expected(directory, artifact)
        full["workload"]["repetitions"] = 5
        _expect_reason("missing observation", import_llmgauge(directory, full),
                       "availability: missing observations")

        directory = root / "swap"
        artifact = _synthetic_artifact(directory)
        artifact["measurements"][0], artifact["measurements"][1] = \
            artifact["measurements"][1], artifact["measurements"][0]
        artifact["aggregate"]["tok_s_out"] = statistics.fmean(
            m["tok_s_out"] for m in artifact["measurements"])
        artifact["aggregate"]["tok_s_prefill"] = statistics.fmean(
            m["tok_s_prefill"] for m in artifact["measurements"])
        artifact["fingerprint"] = _producer_fingerprint(artifact)
        (directory / "benchmark.json").write_text(json.dumps(artifact, indent=1), encoding="utf-8")
        result = import_llmgauge(directory, _full_expected(directory, artifact))
        _expect_reason("swapped repetitions caught positionally", result,
                       "raw: companion evidence contradiction")
        assert any("does not equal the sealed" in r for r in result["reasons"]), \
            result["reasons"]

        nan_dir = root / "nonfinite"
        artifact = _synthetic_artifact(nan_dir, nan=True)
        artifact["fingerprint"] = _producer_fingerprint(artifact)
        (nan_dir / "benchmark.json").write_text(json.dumps(artifact, indent=1, allow_nan=True),
                                                encoding="utf-8")
        _expect_reason("nonfinite measurement",
                       import_llmgauge(nan_dir, _full_expected(nan_dir, artifact)),
                       "availability: measurement[0].tok_s_out")

        reps_dir = root / "reps-unavailable"
        artifact = _synthetic_artifact(reps_dir)
        del artifact["workload"]["warmup_repetitions"]
        artifact["fingerprint"] = _producer_fingerprint(artifact)
        (reps_dir / "benchmark.json").write_text(json.dumps(artifact, indent=1), encoding="utf-8")
        full = _full_expected(reps_dir, artifact)
        full["workload"]["warmup_repetitions"] = 1
        _expect_reason("warmup metadata unavailable", import_llmgauge(reps_dir, full),
                       "availability: workload.warmup_repetitions")

        no_raw = root / "no-raw-pin"
        _synthetic_artifact(no_raw, with_execution_evidence=False)
        result = import_llmgauge(no_raw, _full_expected(no_raw, None))
        _expect_reason("execution raw pin missing", result,
                       "raw: companion evidence contradiction")
        assert any("execution-evidence.json" in r for r in result["reasons"]), result["reasons"]

        no_ttft = root / "no-ttft-pin"
        _synthetic_artifact(no_ttft, with_ttft_evidence=False)
        result = import_llmgauge(no_ttft, _full_expected(no_ttft, None))
        _expect_reason("ttft raw pin missing", result,
                       "raw: companion evidence contradiction")
        assert any("ttft-evidence.json" in r for r in result["reasons"]), result["reasons"]
    check("import: missing observations, swaps, nonfinite values, raw pins, unavailable metadata", import_repetition_availability)

    def import_raw_provenance():
        directory = root / "raw-runtime"
        _synthetic_artifact(directory)
        execution = json.loads((directory / "execution-evidence.json").read_text())
        execution["runtime"]["kv_cache"]["type_k"] = "bf16"  # raw contradicts artifact
        (directory / "execution-evidence.json").write_text(json.dumps(execution), encoding="utf-8")
        _expect_reason("raw runtime contradiction", import_llmgauge(
            directory, _full_expected(directory, None)), "raw:")

        directory = root / "raw-ttft"
        artifact = _synthetic_artifact(directory)
        ttft = json.loads((directory / "ttft-evidence.json").read_text())
        ttft["samples_ms"][0] = 999.0
        (directory / "ttft-evidence.json").write_text(json.dumps(ttft), encoding="utf-8")
        _expect_reason("raw ttft contradiction", import_llmgauge(
            directory, _full_expected(directory, artifact)), "raw:")

        directory = root / "raw-sidecar"
        _synthetic_artifact(directory)
        # unpinned sidecar: expected_sha256 is required
        full = _full_expected(directory, None)
        del full["qualification_sidecar"]["expected_sha256"]
        result = import_llmgauge(directory, full)
        _expect_reason("unpinned sidecar", result,
                       "sidecar: expected_sha256 pin is required")
        assert result["provenance"].get("sidecar_verified_fill") is None and \
            result["provenance"].get("model_artifact_sha256") is None
        # sidecar evidence digest mismatch: model artifact sha unverifiable
        manifest = json.loads((directory / "model-manifest.json").read_text())
        manifest["sha256"] = "cc" * 32  # manifest mutated after pinning
        (directory / "model-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = import_llmgauge(directory, _full_expected(directory, None))
        _expect_reason("sidecar evidence mismatch", result, "sidecar:")
        assert any("model_artifact_sha256 is unavailable" in r for r in result["reasons"]), \
            result["reasons"]
    check("import: raw-evidence contradictions and unverifiable sidecar", import_raw_provenance)

    # ---- bounded llmgauge.result.v0 import -----------------------------------
    def _synthetic_result(directory, *, transcript_sha="0" * 64, status="completed"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "raw").mkdir(exist_ok=True)
        (directory / "logs").mkdir(exist_ok=True)
        (directory / "raw" / "p1.prompt.txt").write_text("prompt", encoding="utf-8")
        (directory / "raw" / "p1.txt").write_text("output", encoding="utf-8")
        (directory / "logs" / "p1.stderr.txt").write_text("stderr", encoding="utf-8")
        record = {
            "schema_version": PRODUCER_RESULT,
            "llmgauge_version": "0.78.0",
            "run": {"run_id": directory.name, "timestamp_utc": "2026-09-24T01:00:00+00:00",
                    "status": status, "result_dir": str(directory)},
            "model": {"model_id": "test/example-model-GGUF:Q6_K", "model_source": "model_profile",
                      "model_profile": "test-profile", "quant": "Q6_K",
                      "model_path": "redacted", "model_path_policy": "redacted",
                      "provenance": {"source_type": "direct_model_path", "status": "available",
                                     "filename": "example-model-Q6_K.gguf",
                                     "sha256": "bb" * 32,
                                     "public_fingerprint": "sha256:bb",
                                     "file_size_bytes": 6951548672}},
            "runtime": {"backend": "llama.cpp", "ctx_size": 8192, "max_tokens": 512,
                        "temperature": 0.2, "top_p": 0.95, "top_k": 40,
                        "min_p": None, "seed": 42, "batch_size": 512, "ubatch_size": 256,
                        "gpu_layers": 999, "kv_offload": "requested_on",
                        "cache_type_k": "f16", "cache_type_v": "f16", "flash_attn": "on"},
            "suite": {"suite_id": "test-practical-suite", "prompt_count": 1,
                      "include": "all", "only": None, "suite_version": "0.1.0"},
            "results": [{
                "prompt_id": "p1", "status": "completed",
                "metrics": {"generation_tps": 80.6, "prompt_eval_tps": 3606.3,
                            "generation_tokens": 128, "prompt_eval_tokens": 512,
                            "peak_vram_mib": None},
                "raw_prompt_path": "raw/p1.prompt.txt",
                "raw_output_path": "raw/p1.txt",
                "stderr_log_path": "logs/p1.stderr.txt",
            }],
            "summary": {"completed": 1, "failed": 0},
            "transcript": {"path": "transcript/transcript.json", "sha256": transcript_sha,
                           "schema_version": "llmgauge.transcript.v0"},
        }
        (directory / "llmgauge-result.json").write_text(json.dumps(record, indent=1),
                                                        encoding="utf-8")
        # immutable run-qualification evidence for axes result.v0 cannot carry
        (directory / "run-qualification.json").write_text(json.dumps({
            "qualification": "welp-run-qualification/1",
            "cache_regime": "cached_serving_measured_separately",
            "timing_boundary": "end_to_end_including_prompt_processing",
            "gpu_name": "Test GPU 9000",
            "hw_class": "DISCRETE_GPU",
        }, indent=1), encoding="utf-8")
        qual_sha = _sha256_file(directory / "run-qualification.json")
        (directory / "run-qualification-sidecar.json").write_text(json.dumps({
            "sidecar": "welp-measurement-qualification-sidecar/1",
            "fields": {
                "cache_regime": {
                    "value": "cached_serving_measured_separately",
                    "evidence": {"path": "run-qualification.json", "sha256": qual_sha,
                                 "json_pointer": "/cache_regime"}},
                "timing_boundary": {
                    "value": "end_to_end_including_prompt_processing",
                    "evidence": {"path": "run-qualification.json", "sha256": qual_sha,
                                 "json_pointer": "/timing_boundary"}},
                "hardware.gpu_name": {
                    "value": "Test GPU 9000",
                    "evidence": {"path": "run-qualification.json", "sha256": qual_sha,
                                 "json_pointer": "/gpu_name"}},
                "hardware.hw_class": {
                    "value": "DISCRETE_GPU",
                    "evidence": {"path": "run-qualification.json", "sha256": qual_sha,
                                 "json_pointer": "/hw_class"}},
            },
        }, indent=1), encoding="utf-8")
        return record

    def import_result_v0():
        directory = root / "result-v0"
        (directory / "transcript").mkdir(parents=True)
        (directory / "transcript" / "transcript.json").write_text("{}", encoding="utf-8")
        record = _synthetic_result(
            directory,
            transcript_sha=_sha256_file(directory / "transcript" / "transcript.json"))

        def result_expected(directory, record):
            return {
                "artifact_sha256": _sha256_file(directory / "llmgauge-result.json"),
                "model_artifact_sha256": "bb" * 32,
                "cache_regime": "cached_serving_measured_separately",
                "timing_boundary": "end_to_end_including_prompt_processing",
                "metric_units": {"generation_tps": "tok/s"},
                "model": {"model_id": "test/example-model-GGUF:Q6_K", "quant": "Q6_K"},
                "engine": {"backend": "llama.cpp"},
                "hardware": {"gpu_name": "Test GPU 9000", "hw_class": "DISCRETE_GPU"},
                "workload": {"suite_id": "test-practical-suite", "prompt_count": 1,
                             "context_length": 8192},
                "runtime": {"ctx_size": 8192, "max_tokens": 512, "temperature": 0.2,
                            "top_p": 0.95, "gpu_layers": 999,
                            "kv_offload": "requested_on", "kv_cache_type_k": "f16",
                            "kv_cache_type_v": "f16", "flash_attention": "on",
                            "seed": 42},
                "qualification_sidecar": {
                    "path": str(directory / "run-qualification-sidecar.json"),
                    "expected_sha256": _sha256_file(
                        directory / "run-qualification-sidecar.json"),
                },
            }

        result = import_llmgauge(directory, result_expected(directory, record))
        _expect_compatible("result.v0 bounded import", result)
        assert result["provenance"]["model_artifact_sha256"] == {
            "value": "bb" * 32, "verification": "model.provenance.sha256"}
        assert result["metrics"]["evidence_availability"]["raw_referenced_artifacts"] == AVAILABLE
        assert result["metrics"]["per_prompt"][0]["generation_tps"] == 80.6
        assert result["metrics"]["per_prompt"][0]["peak_vram_mib"] == UNAVAILABLE
        assert "raw/p1.txt" in result["provenance"]["raw_files"]

        full = result_expected(directory, record)
        full["repetition_structure"] = True
        _expect_reason("result.v0 repetition structure", import_llmgauge(directory, full),
                       "availability: repetition_structure")

        record["transcript"]["sha256"] = "1" * 64
        (directory / "llmgauge-result.json").write_text(json.dumps(record, indent=1),
                                                        encoding="utf-8")
        _expect_reason("transcript digest mismatch",
                       import_llmgauge(directory, result_expected(directory, record)),
                       "raw: transcript sha256")

        failed = _synthetic_result(directory / "result-failed2", status="failed")
        _expect_reason("failed run unavailable",
                       import_llmgauge(directory / "result-failed2",
                                       result_expected(directory / "result-failed2", failed)),
                       "availability: run.status")

        # model artifact identity mismatch against model.provenance.sha256
        _synthetic_result(directory / "result-model")
        full = result_expected(directory / "result-model", None)
        full["model_artifact_sha256"] = "ee" * 32
        _expect_reason("result model artifact sha mismatch",
                       import_llmgauge(directory / "result-model", full),
                       "axis: model_artifact_sha256")
    check("import: bounded llmgauge.result.v0 (full identity, raw hashes, transcript digest, availability)", import_result_v0)

    print()
    if fails:
        print(f"{len(fails)} selftest failure(s)")
        return 1
    print(f"selftest PASS ({MODULE_ID}, {CONTRACT})")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: measurement.py selftest | import SOURCE EXPECTED_JSON | "
              "summarize INPUT_JSON")
        return 0
    if argv[0] == "selftest":
        return selftest()
    if argv[0] == "import":
        return _cli_import(argv[1:])
    if argv[0] == "summarize":
        return _cli_summarize(argv[1:])
    print(f"unknown command {argv[0]!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
