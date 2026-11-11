"""Runtime Performance section — dedicated deployment-attributed measurement.

Purpose (SPEC §4.1.1/§4.12): answer "how efficiently does this particular
qualified model deployment process input and generate output under
documented conditions?" — speed, latency, throughput and resource
consumption for ONE qualified deployment, with honest comparisons between
compatible deployments when the relevant technical conditions genuinely
match. Performance is measurement, never quality scoring: nothing here
feeds a capability rate, classification or advancement decision.

The section is model-, runtime-, backend-, GPU/vendor- and host-agnostic.
It reuses the accepted M2 performance machinery VERBATIM rather than
duplicating it under new names: the two frozen workload identities
(`perf-short` / `perf-substantial`, streaming, repetitions=3,
cache_prompt disabled on the native llama.cpp contract, exact-answer
sanity oracle), the shared runner execution path (durable generation
intents, raw SSE + deterministic reconstruction, standardized timings,
repetitions evidence, fatal device stops), the accepted profile
attribution (one qualified deployment profile — no second profile
system), and the accepted M2 measurement rules (throughput rates come
ONLY from the serving stack's native envelope ``timings`` block, preserved
verbatim; UNKNOWN when the server does not report them; token counts
divided by wall-clock time are never presented as server throughput).

This module owns: the section inventory (the two reused workloads bound by
provenance digest), the independent-selectability gate (no capability
witness exists or is invented for measurements; a technically qualified
deployment and valid measurement conditions are required, capability
results are not), attempt validation through the shared offline replay,
the per-workload measurement summary with explicit metric provenance and
units, deployment-attributed reporting, and the corrected comparison
classification (SAME_DEPLOYMENT repeatability / MATCHED_RUNTIME with the
runtime identity as the recorded compared variable / DEPLOYMENT_STACK /
INSUFFICIENT_COMPARABILITY).

Fault attribution (SPEC §4.12): valid measured throughput is a deployment
performance result; slow-but-valid generation is a legitimate measured
performance; an exceeded generation ceiling is the accepted budget-limited
outcome; a WELP-side token/time counting defect fails offline replay
validation (evidence-integrity problem, never silently scored); runtime
metering that disagrees with the recorded usage is labeled an unresolved
measurement-validity finding, never silently reconciled; an unavailable
telemetry provider is an UNAVAILABLE metric, never an invented zero; a
GPU reset or allocation failure is the shared fatal infrastructure stop;
directly compared unmatched configurations are a scientific comparison
invalidity (DEPLOYMENT_STACK labeling, never averaged).
"""
import json
import statistics
from pathlib import Path
import signal

from . import baseline, coding, policy, preflight, reporting, runner, store

SECTION = 'runtime-performance'
METHODOLOGY = 'runtime-performance/1'
_ALLOWED_CONFIG_KEYS = frozenset()

_fail = coding._fail

#: Required serving measurements per repeat (the accepted M2 rule,
#: policy._performance_timing_gaps): native prompt/generation throughput,
#: positive total latency and positive token usage, plus streaming TTFT.
#: These decide MEASURED versus MEASURED_PARTIAL; they are never a
#: speed threshold and never a quality score.

#: Per-workload measurement classification (fixed before any authentic
#: output; SPEC §4.12):
#: MEASURED          — valid execution; every required field present for
#:                     every repeat (incl. native rates on a streaming unit)
#: MEASURED_PARTIAL  — valid execution; core measurements (usage, total
#:                     latency) present; some metrics UNAVAILABLE (reported
#:                     as unavailable, never zero)
#: MEASUREMENT_INVALID — executed but the runtime/interface produced no
#:                     usable measurement core (invalid responses, missing
#:                     usage/latency, metering unusable)
#: NOT_MEASURED      — no valid execution (budget ceiling, transport
#:                     failure, fatal device/host stop, sanity failure)


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def load_fixture():
    """The two accepted M2 performance workload identities, reused verbatim.

    No new workload, repetition count, cache rule or numeric threshold is
    introduced (SPEC §4.12); the fixture digest binds the reused identities
    into the section evidence. Returns (fixture, tasks_by_id).
    """
    tasks = baseline._performance_tasks()
    by_id = {}
    for task in tasks:
        by_id[task['id']] = task
    if sorted(by_id) != ['perf-short', 'perf-substantial']:
        _fail('runtime_performance.fixture', 'unexpected performance workload identities')
    for task in tasks:
        method = task.get('method') or {}
        if not method.get('streaming') or method.get('cache_prompt') is not False:
            _fail('runtime_performance.fixture', f"{task['id']}: changed measurement method")
        if task.get('repetitions') != baseline.PERFORMANCE_REPETITIONS:
            _fail('runtime_performance.fixture', f"{task['id']}: changed repetition schedule")
        if task.get('scorer') != 'response_sanity':
            _fail('runtime_performance.fixture', f"{task['id']}: changed sanity oracle")
        if task.get('category') != 'performance':
            _fail('runtime_performance.fixture', f"{task['id']}: changed category")
    fixture = {
        'section': SECTION,
        'methodology': METHODOLOGY,
        'source': {
            'fixture_id': baseline.FIXTURE_ID, 'version': baseline.FIXTURE_VERSION,
            'rule': ('performance workload identities reused verbatim from the accepted '
                     'M2 baseline inventory; the section introduces no new workload, '
                     'repetition schedule, cache rule or threshold')},
        'tasks': tasks,
    }
    return fixture, by_id


def plan(profile, config=None):
    policy.validate_profile(profile)
    config = coding._config(config)
    fixture, tasks = load_fixture()
    for uid, task in tasks.items():
        applicable, reason = policy.task_applicability(profile, task)
        if not applicable:
            _fail('runtime_performance.applicability',
                  f'{uid}: {reason}')
    checks = preflight.offline(profile)
    return {'section': SECTION, 'methodology': METHODOLOGY,
            'evidence_kind': profile['evidence_kind'],
            'profile_revision': policy.digest(profile),
            'unit_ids': list(tasks), 'fixture_sha256': policy.digest(fixture),
            'gate': {'decision': 'ADVANCE', 'reason':
                     'independently selectable measurement section: requires a technically '
                     'qualified deployment and valid measurement conditions, never a '
                     'capability result; no capability-witness gate exists and none is '
                     'invented (SPEC §4.12)'},
            'preflight': checks, 'config': config}


def _identity(profile, fixture, tasks, planned):
    return {'profile': profile, 'profile_revision': policy.digest(profile),
            'methodology': METHODOLOGY, 'section': SECTION,
            'unit_ids': list(tasks), 'fixture_sha256': policy.digest(fixture),
            'software': runner.software_identity(),
            'admission_version': policy.ADMISSION_VERSION,
            'gate': planned['gate']}


def run(profile, config=None):
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign)
    fixture, tasks = load_fixture()
    config = coding._config(config)
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if not policy.compatible_profiles(saved['profile'], profile):
            raise policy.CheckError('recovery.runtime_performance: changed finalized configuration')
        return status(campaign)
    planned = plan(profile, config)
    identity = _identity(profile, fixture, tasks, planned)
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['fixture_sha256'] != identity['fixture_sha256']):
                raise policy.CheckError('recovery.runtime_performance: changed scientific configuration')
        else:
            for name, value in (('profile.json', profile),
                                ('fixture.json', fixture),
                                ('run.json', identity)):
                reporting.ensure_json(target / name, value)
        _, units = store.inventory(target)
        if not any(policy.unit_pending(rows) for rows in units.values()):
            return status(campaign)
        store.check_preparation(target)
        try:
            admission = preflight.online(profile)
        except policy.CheckError as exc:
            failure = dict(getattr(exc, 'evidence', {}))
            failure.update(ok=False, error=str(exc),
                           profile_revision=identity['profile_revision'])
            store.record_admission(target, failure)
            raise
        store.record_admission(target, admission)
        stop = False

        def interrupted(signum, frame):
            nonlocal stop
            if stop:
                raise KeyboardInterrupt
            stop = True

        previous = signal.signal(signal.SIGINT, interrupted)
        try:
            for uid, task in tasks.items():
                while not stop and policy.unit_pending(store.attempts(target, uid)):
                    path = store.new_attempt(target, uid, preparing=True)
                    store.append_event(target, {'event': 'PREPARING', 'unit_id': uid,
                                                'attempt_id': path.name,
                                                'at': runner.now()})
                    try:
                        fatal = runner.execute(profile, task, path,
                                               identity['profile_revision'], admission)
                    except KeyboardInterrupt:
                        stop = True
                        break
                    if fatal:
                        stop = True
                        break
                    store.append_event(target, {
                        'event': 'PREPARATION_FAILED' if store.preparation_only(path)
                        else 'FINALIZED', 'unit_id': uid, 'attempt_id': path.name,
                        'at': runner.now()})
                    if store.preparation_only(path):
                        stop = True
                        break
        finally:
            signal.signal(signal.SIGINT, previous)
            if stop:
                store.append_event(target, {'event': 'INTERRUPTED', 'at': runner.now()})
        return status(campaign)


def status(campaign):
    target = section_path(campaign)
    if not (target / 'run.json').exists():
        return {'section': SECTION, 'state': 'NOT_RUN', 'units': [], 'finalized': False}
    config, units = store.inventory(target)
    rows = []
    for uid, attempts in units.items():
        resolved = policy.resolved_attempt(attempts)
        rows.append({'unit_id': uid, 'attempts': len(attempts),
                     'resolved_attempt': resolved['attempt_id'] if resolved else None,
                     'outcome': resolved['outcome'] if resolved else 'NOT_RUN',
                     'reason': resolved.get('reason') if resolved else None,
                     'pending': policy.unit_pending(attempts)})
    admissions = store.admission_records(target)
    blocked = bool(admissions) and admissions[-1].get('ok') is False
    return {'section': SECTION, 'state': policy.section_state(units, blocked=blocked),
            'profile_id': config['profile']['profile_id'],
            'evidence_kind': config['profile']['evidence_kind'],
            'methodology': config['methodology'], 'units': rows,
            'preparation_failures': store.preparation_failures(target),
            'remaining_units': [r['unit_id'] for r in rows if r['pending']],
            'finalized': (target / 'manifest.json').exists()}


def resume(campaign, profile=None):
    config = store.read_json(section_path(campaign) / 'run.json')
    if Path(config['profile']['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.runtime_performance: wrong campaign')
    if config['methodology'] != METHODOLOGY:
        raise policy.CheckError('recovery.runtime_performance: methodology mismatch')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.runtime_performance: wrong campaign')
    return run(profile)


# ---------------------------------------------------------------------------
# Measurement summary (original evidence only; replay validates first)

#: Metrics summarized per repeat, with explicit provenance and units:
#: - usage.{prompt_tokens, completion_tokens, total_tokens}  [tokens, native
#:   accounting verbatim; completion includes reasoning tokens where the
#:   runtime reports them, carried verbatim under completion_tokens_details]
#: - timings.tokens_per_second.{prompt, generation}  [tokens/s, NATIVE engine
#:   metering verbatim; UNKNOWN when unreported — never zero, never replaced]
#: - timings.observed_wall_clock.{prompt_per_second, generation_per_second}
#:   [tokens/s, DERIVED estimate: usage over observed wall-clock windows;
#:    clearly distinct from native rates and never presented as them]
#: - timings.ttft_seconds        [s, first GENERATED delta incl. reasoning]
#: - timings.first_byte_seconds  [s, first HTTP byte — distinct from TTFT]
#: - timings.latency_seconds     [s, total request completion]
#: - timings.cache_state         [native cache_n/prompt_n pair or UNKNOWN]
#: - finish_reason, usage_source [verbatim]


def _finite_positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and value not in (float('inf'), float('-inf'))
            and value > 0)


def _wall_clock_estimates(timings):
    """Honest wall-clock derivatives, never presented as native throughput.

    prompt window ≈ time to first generated delta (the prompt-processing
    span ends when generation starts); generation window ≈ total latency
    minus that span. UNKNOWN provenance stays UNKNOWN.
    """
    usage = timings.get('usage') or {}
    latency = timings.get('latency_seconds')
    ttft = timings.get('ttft_seconds')
    estimates = {'provenance': 'derived_wall_clock', 'prompt_per_second': 'UNKNOWN',
                 'generation_per_second': 'UNKNOWN'}
    prompt_tokens = usage.get('prompt_tokens')
    completion_tokens = usage.get('completion_tokens')
    if (_finite_positive(latency) and _finite_positive(ttft)
            and isinstance(prompt_tokens, int) and prompt_tokens > 0
            and 0 < ttft < latency):
        estimates['prompt_per_second'] = round(prompt_tokens / ttft, 3)
    if (_finite_positive(latency) and _finite_positive(ttft)
            and isinstance(completion_tokens, int) and completion_tokens > 0
            and 0 < ttft < latency):
        estimates['generation_per_second'] = round(
            completion_tokens / (latency - ttft), 3)
    return estimates


def _usage_record(timings):
    """Verbatim usage with the reasoning-token location surfaced.

    completion_tokens is the runtime's own accounting and includes
    reasoning tokens where the runtime generates and reports them; the
    detail block is never dropped or merged into the visible answer.
    """
    usage = timings.get('usage')
    if not isinstance(usage, dict):
        return {'usage': None, 'usage_source': timings.get('usage_source', 'UNAVAILABLE'),
                'reasoning_tokens': 'UNAVAILABLE'}
    details = usage.get('completion_tokens_details')
    reasoning = details.get('reasoning_tokens') if isinstance(details, dict) else None
    if reasoning is None:
        reasoning = usage.get('reasoning_tokens')
    return {'usage': usage, 'usage_source': timings.get('usage_source'),
            'reasoning_tokens': reasoning if isinstance(reasoning, int) else 'UNAVAILABLE'}


def _repeat_measurement(timings, finish_reason):
    required = policy._performance_timing_gaps(timings or {})
    rates = (timings or {}).get('tokens_per_second') or {}
    record = {
        'required_field_gaps': required,
        'native_tokens_per_second': {'prompt': rates.get('prompt'),
                                     'generation': rates.get('generation'),
                                     'provenance': 'native_engine_timings',
                                     'unit': 'tokens_per_second'},
        'observed_wall_clock': _wall_clock_estimates(timings),
        'ttft_seconds': (timings or {}).get('ttft_seconds'),
        'first_byte_seconds': (timings or {}).get('first_byte_seconds'),
        'latency_seconds': (timings or {}).get('latency_seconds'),
        'cache_state': (timings or {}).get('cache_state'),
        'finish_reason': finish_reason or 'UNKNOWN',
        **_usage_record(timings),
    }
    return record


def _finish_reason(envelope):
    """Verbatim finish_reason from one reconstructed envelope."""
    choices = (envelope or {}).get('choices')
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish = choices[0].get('finish_reason')
        if isinstance(finish, str):
            return finish
    return 'UNKNOWN'


def _aggregate(repeats):
    """Min/median/max over the repeats for each finite numeric metric.

    Originals are always retained verbatim beside the summary; a metric
    with any UNKNOWN repeat stays UNKNOWN-level honest (aggregated only
    over the finite subset, with the covered count stated).
    """
    fields = {
        'native_tokens_per_second.prompt': lambda r: r['native_tokens_per_second']['prompt'],
        'native_tokens_per_second.generation': lambda r: r['native_tokens_per_second']['generation'],
        'observed_wall_clock.prompt_per_second': lambda r: r['observed_wall_clock']['prompt_per_second'],
        'observed_wall_clock.generation_per_second': lambda r: r['observed_wall_clock']['generation_per_second'],
        'ttft_seconds': lambda r: r['ttft_seconds'],
        'first_byte_seconds': lambda r: r['first_byte_seconds'],
        'latency_seconds': lambda r: r['latency_seconds'],
        'usage.prompt_tokens': lambda r: (r['usage'] or {}).get('prompt_tokens'),
        'usage.completion_tokens': lambda r: (r['usage'] or {}).get('completion_tokens'),
    }
    aggregation = {}
    for name, getter in fields.items():
        values = [v for v in (getter(r) for r in repeats) if _finite_positive(v)]
        if values:
            aggregation[name] = {'min': min(values),
                                 'median': statistics.median(values),
                                 'max': max(values), 'samples': len(values),
                                 'unit': 'tokens_per_second' if 'per_second' in name
                                 else ('tokens' if 'usage.' in name else 'seconds')}
    return aggregation


def _metering_consistency(repeats):
    """Native-vs-usage cross-check: never reconciled, only labeled.

    When the runtime reports native token counts (prompt_n/predicted_n)
    AND usage on the same repeat, disagreement is recorded as an unresolved
    measurement-validity finding attributed to the runtime/interface —
    never silently corrected by WELP.
    """
    findings = []
    for index, timing in enumerate(repeats, 1):
        native = timing.get('native_timings')
        usage = timing.get('usage') or {}
        if not isinstance(native, dict):
            continue
        for native_key, usage_key in (('prompt_n', 'prompt_tokens'),
                                      ('predicted_n', 'completion_tokens')):
            if (isinstance(native.get(native_key), int)
                    and isinstance(usage.get(usage_key), int)
                    and native[native_key] != usage[usage_key]):
                findings.append({
                    'repeat': index,
                    'finding': f'native {native_key}={native[native_key]} vs usage '
                               f'{usage_key}={usage[usage_key]}',
                    'attribution': 'runtime/interface metering disagreement; '
                                   'measurement validity unresolved',
                    'resolution': 'both observations preserved verbatim; never reconciled'})
    return findings


def _memory_observations(profile, path):
    """Deployment-attributed memory from the qualified deployment's observer.

    Snapshots are the established gpu-before/gpu-after contract written by
    the deployment-side observer while the attempt runs (hashed into the
    attempt at finalize). Device attribution matches the profile's declared
    pci_id; other devices are environment context, never attributed. When
    telemetry is unavailable the metric is UNAVAILABLE — never zero.
    """
    declared_pci = (profile.get('hardware') or {}).get('device', {}).get('pci_id')
    result = {'available': False, 'provenance': 'deployment_observer_snapshots',
              'declared_device_pci_id': declared_pci, 'before': 'UNAVAILABLE',
              'after': 'UNAVAILABLE', 'unit': 'bytes'}
    samples = {}
    boundary_samples = []
    from . import observation
    for name in observation.NAMES:
        snapshot = observation.read_snapshot(profile, path, name)
        value = observation.device_memory(profile, snapshot)
        if value is not None:
            samples[name] = value
            if snapshot.get('kind') == 'attempt_resource_observation':
                boundary_samples.append({'phase': snapshot['phase'], 'bytes': value,
                    'started_epoch': snapshot['started_epoch'],
                    'ended_epoch': snapshot['ended_epoch'], 'source': snapshot['source']})
    if 'gpu-before.json' in samples and 'gpu-after.json' in samples:
        result['available'] = True
        result['before'] = samples['gpu-before.json']
        result['after'] = samples['gpu-after.json']
        result['delta_bytes'] = samples['gpu-after.json'] - samples['gpu-before.json']
        result['note'] = ('device-wide VRAM observations around the workload; '
                          'peak-in-request telemetry is not available from this '
                          'observer contract and is not invented')
    elif samples:
        result['partial'] = sorted(samples)
        result['note'] = 'only one side of the workload window was observed'
    else:
        result['note'] = ('no deployment-observer memory telemetry for the declared '
                          'device; reported unavailable, never zero')
    if boundary_samples:
        result.update(scope='device-wide', sampling='before/after the complete attempt',
                      samples=boundary_samples, sample_count=len(boundary_samples),
                      sampled_max_bytes=max(s['bytes'] for s in boundary_samples),
                      true_peak_bytes='UNAVAILABLE', process_attributed_bytes='UNAVAILABLE')
    return result


def summarize_workload(profile, task, attempt_path, replayed_score):
    """One workload's measurement record from ORIGINAL evidence.

    ``replayed_score`` comes from runner.replay_attempt (offline, original
    bytes) so the outcome attribution is reconstruction-authoritative.
    """
    path = Path(attempt_path)
    conditions = store.read_json(path / 'conditions.json')
    repeats_path = path / 'repetitions.json'
    if (task.get('repetitions', 1) > 1) and repeats_path.exists():
        receipt = store.read_json(repeats_path)
        entries = receipt.get('repeats') or []
        timings = [entry['timings'] for entry in entries]
        finishes = [_finish_reason(entry.get('envelope')) for entry in entries]
    else:
        timings = [conditions.get('timings')]
        finishes = [_finish_reason(runner.reconstruct_response(
            (path / 'response.raw').read_bytes(),
            streaming=bool((conditions.get('timings') or {}).get('streaming')))['envelope'])]
    repeats = [_repeat_measurement(t, f) for t, f in zip(timings, finishes)]
    outcome = replayed_score.get('outcome')
    reason = replayed_score.get('reason')
    executed = replayed_score.get('execution') == 'VALID'
    complete_repeats = (len(repeats) == task.get('repetitions', 1)
                        and all(not r['required_field_gaps'] for r in repeats))
    core_present = all(
        (r['usage'] or {}).get('prompt_tokens') is not None
        and _finite_positive(r['latency_seconds']) for r in repeats)
    if executed and complete_repeats:
        classification = 'MEASURED'
    elif executed and core_present:
        classification = 'MEASURED_PARTIAL'
    elif executed:
        classification = 'MEASUREMENT_INVALID'
    else:
        classification = 'NOT_MEASURED'
    limitations = []
    for index, record in enumerate(repeats, 1):
        if record['native_tokens_per_second']['prompt'] == 'UNKNOWN':
            limitations.append(f'repeat-{index}: native prompt throughput unreported '
                               '(reported unavailable, never zero)')
        if record['native_tokens_per_second']['generation'] == 'UNKNOWN':
            limitations.append(f'repeat-{index}: native generation throughput unreported '
                               '(reported unavailable, never zero)')
        if record['ttft_seconds'] == 'UNKNOWN' and (conditions.get('timings') or {}).get('streaming'):
            limitations.append(f'repeat-{index}: time-to-first-token unobservable')
    memory = _memory_observations(profile, path)
    if not memory['available']:
        limitations.append('memory telemetry unavailable from the deployment observer '
                           '(reported unavailable, never zero)')
    return {'unit_id': task['id'], 'workload': task.get('workload'),
            'classification': classification, 'outcome': outcome, 'reason': reason,
            'repetitions_expected': task.get('repetitions', 1),
            'repeats': repeats, 'aggregation': _aggregate(repeats),
            'metering_consistency': _metering_consistency(timings),
            'memory': memory,
            'measurement_conditions': {
                'streaming': (conditions.get('timings') or {}).get('streaming'),
                'cache_condition': 'cache_prompt disabled on the native llama.cpp '
                                   'contract; native cache_n/prompt_n observed verbatim',
                'client_deadline_exhausted': conditions.get('client_deadline_exhausted'),
                'transport_error': conditions.get('transport_error'),
                'http_status': conditions.get('http_status')},
            'limitations': limitations}


def _attribution(profile):
    runtime = profile.get('runtime') or {}
    engine = runtime.get('engine') or {}
    model = profile.get('model') or {}
    artifact = model.get('artifact') or {}
    return {
        'profile_id': profile.get('profile_id'),
        'evidence_kind': profile.get('evidence_kind'),
        'model': {'model_key': model.get('model_key'),
                  'artifact_sha256': artifact.get('sha256'),
                  'artifact_format': artifact.get('format'),
                  'artifact_revision': artifact.get('revision'),
                  'quantization_note': 'precision/quantization is carried by the '
                                       'recorded artifact identity above'},
        'runtime': {'engine_name': engine.get('name'), 'engine_version': engine.get('version'),
                    'backend': runtime.get('backend'),
                    'serve_model_id': (runtime.get('serve') or {}).get('model_id')},
        'hardware': {'device': (profile.get('hardware') or {}).get('device'),
                     'note': 'single-device single-request measurement condition; '
                             'concurrency/batching beyond the pinned request shape is '
                             'recorded only when the qualified profile declares it'},
        'context': {'capacity': runtime.get('context_capacity')},
        'reasoning': profile.get('reasoning'),
        'sampling': profile.get('sampling'),
    }


#: Comparison semantics (SPEC §4.12, corrected 2026-11-08, before any
#: authentic generation):
#: - SAME_DEPLOYMENT: identical model artifact, runtime, backend, hardware
#:   and material configuration — repeatability within one deployment.
#: - MATCHED_RUNTIME: two DIFFERENT qualified runtime implementations or
#:   versions compared when every material control matches — the runtime
#:   identity/version IS the compared variable: recorded, never required to
#:   be identical.
#: - DEPLOYMENT_STACK: a material control differs (artifact/quantization,
#:   hardware, backend, ...) — informative, but not a controlled
#:   runtime-only comparison; deployments stay independent, never averaged.
#: - INSUFFICIENT_COMPARABILITY: an essential condition is missing or
#:   unverifiable — report the limitation, never infer equivalence.

#: Material controls that must match for a runtime-only comparison.
MATERIAL_CONTROLS = (
    'model.artifact_sha256', 'model.artifact_format', 'model.artifact_revision',
    'runtime.backend',
    'hardware.device.pci_id', 'hardware.device.name',
    'context.capacity', 'sampling', 'reasoning',
)
#: The compared variable: recorded on every comparison, never required to
#: be identical across the two deployments.
RUNTIME_VARIABLES = ('runtime.engine_name', 'runtime.engine_version')


def _control_value(attribution, dotted):
    if dotted in ('sampling', 'reasoning'):
        return attribution.get(dotted)
    group, _, key = dotted.rpartition('.')
    if group == 'model':
        return attribution['model'].get(key)
    if group == 'runtime':
        return attribution['runtime'].get(key)
    if group == 'hardware.device':
        return (attribution['hardware']['device'] or {}).get(key)
    if group == 'context':
        return attribution['context'].get(key)
    raise KeyError(dotted)


def compare_profiles(profile_a, profile_b):
    """Classify a two-deployment comparison from recorded attribution only.

    Material controls (artifact identity, backend, hardware device, context
    geometry, sampling, reasoning) must match for a runtime-only
    comparison; the runtime engine name/version is the compared variable —
    recorded, never required to be identical. A missing essential value is
    INSUFFICIENT_COMPARABILITY (limitation reported, equivalence never
    inferred).
    """
    a, b = _attribution(profile_a), _attribution(profile_b)
    matched, differing, unverifiable = [], {}, []
    for field in MATERIAL_CONTROLS:
        va, vb = _control_value(a, field), _control_value(b, field)
        if va is None or vb is None:
            unverifiable.append(field)
        elif va == vb:
            matched.append(field)
        else:
            differing[field] = [va, vb]
    runtime_record = {
        'profile_a': {field: _control_value(a, field) for field in RUNTIME_VARIABLES},
        'profile_b': {field: _control_value(b, field) for field in RUNTIME_VARIABLES},
        'provenance': 'compared variable: recorded, never required identical'}
    for field in RUNTIME_VARIABLES:
        if _control_value(a, field) is None or _control_value(b, field) is None:
            unverifiable.append(field)
    if unverifiable:
        classification = 'INSUFFICIENT_COMPARABILITY'
    elif differing:
        classification = 'DEPLOYMENT_STACK'
    elif all(_control_value(a, f) == _control_value(b, f) for f in RUNTIME_VARIABLES):
        classification = 'SAME_DEPLOYMENT'
    else:
        classification = 'MATCHED_RUNTIME'
    return {'class': classification,
            'runtime_under_comparison': runtime_record,
            'matched_fields': matched, 'differing_fields': differing,
            'unverifiable_fields': unverifiable,
            'comparison_allowed': classification in ('MATCHED_RUNTIME', 'SAME_DEPLOYMENT'),
            'rule': ('SAME_DEPLOYMENT: identical deployment, repeatability comparison. '
                     'MATCHED_RUNTIME: different qualified runtimes/versions under matched '
                     'material controls (same model artifact identity, backend, hardware '
                     'device, context geometry, sampling and reasoning) — the runtime '
                     'identity is the compared variable, recorded but never required '
                     'identical. DEPLOYMENT_STACK: a material control differs — '
                     'deployments are reported independently and never averaged. '
                     'INSUFFICIENT_COMPARABILITY: an essential condition is missing or '
                     'unverifiable — report the limitation, never infer equivalence')}


def _validate_attempt(config, tasks, uid, row):
    path = Path(row['path'])
    conditions = store.read_json(path / 'conditions.json')
    profile = policy.recorded_profile(config, conditions)
    policy.validate_echo(profile, conditions['preflight']['echo'])
    if conditions.get('request_limits') != policy.task_budget(profile, tasks[uid]):
        raise policy.CheckError(
            f'validation.runtime_performance.{uid}: changed budget attribution')
    replayed, fatal = runner.replay_attempt(profile, tasks[uid], path)
    if fatal != conditions.get('fatal_device_condition'):
        raise policy.CheckError(
            f'validation.runtime_performance.{uid}.safety: false fatal attribution')
    return replayed


def report_section(campaign, compare_profile=None):
    target = section_path(campaign)
    with store.locked(campaign):
        if (target / 'manifest.json').exists():
            reporting.verify_manifest(target)
            return {'disposition': 'PASS', 'report': str(target / 'SECTION-REPORT.md'),
                    'already_finalized': True}
        config, units = store.inventory(target)
        fixture, tasks = load_fixture()
        profile = config['profile']
        plan(profile)
        summary = status(campaign)
        if summary['remaining_units']:
            raise policy.CheckError(
                'finalization.runtime_performance: pending work; resume first')
        workloads = {}
        for uid, task in tasks.items():
            rows = units.get(uid) or []
            resolved = policy.resolved_attempt(rows)
            if resolved is None:
                workloads[uid] = {'unit_id': uid, 'classification': 'NOT_MEASURED',
                                  'outcome': 'NOT_RUN',
                                  'reason': 'no attempt reached finalization'}
                continue
            replayed = _validate_attempt(config, tasks, uid, resolved)
            workloads[uid] = summarize_workload(profile, task, resolved['path'], replayed)
        comparison = None
        if compare_profile is not None:
            comparison = {'compare_profile_id': compare_profile.get('profile_id'),
                          **compare_profiles(profile, compare_profile)}
        evidence_kind = profile['evidence_kind']
        overall = 'MEASURED' if all(
            w.get('classification') == 'MEASURED' for w in workloads.values()) else \
            ('NOT_MEASURED' if all(w.get('classification') == 'NOT_MEASURED'
                                   for w in workloads.values()) else 'PARTIAL')
        summary_record = {
            'section': SECTION, 'methodology': METHODOLOGY,
            'evidence_kind': evidence_kind,
            'software_test': evidence_kind == 'SOFTWARE_TEST',
            'profile_attribution': _attribution(profile),
            'overall': overall, 'workloads': workloads,
            'comparison': comparison,
            'comparison_rule': compare_profiles(profile, profile)['rule'],
            'note': ('performance measurements are deployment-attributed observations, '
                     'never quality scores and never cross-model rankings'),
        }
        reporting.ensure_json(target / 'performance-summary.json', summary_record)
        summary['overall'] = overall
        lines = ['# WELP — Runtime Performance',
                 '',
                 'Deployment-attributed measurement of inference speed, latency,',
                 'throughput and resource consumption for ONE qualified deployment.',
                 'Measurements are never quality scores; workloads are the accepted M2',
                 'performance identities reused verbatim. Synthetic evidence is labeled',
                 f'SOFTWARE_TEST (this campaign: {evidence_kind}).',
                 '',
                 f'Overall: **{overall}**.',
                 '',
                 '## Workload measurements', '']
        for uid, workload in workloads.items():
            lines.append(f"### {uid} ({workload.get('workload')}) — "
                         f"{workload.get('classification')}")
            lines.append('')
            for index, repeat in enumerate(workload.get('repeats') or [], 1):
                native = repeat['native_tokens_per_second']
                wall = repeat['observed_wall_clock']
                usage = repeat['usage'] or {}
                lines.append(
                    f"- repeat {index}: native {native['prompt']}/{native['generation']} tok/s "
                    f"(engine metering) | wall-clock estimate "
                    f"{wall['prompt_per_second']}/{wall['generation_per_second']} tok/s "
                    f"(derived, distinct) | TTFT {repeat['ttft_seconds']} s, first byte "
                    f"{repeat['first_byte_seconds']} s, total {repeat['latency_seconds']} s | "
                    f"usage {usage.get('prompt_tokens')}+{usage.get('completion_tokens')} tok "
                    f"(reasoning {repeat['reasoning_tokens']}) | finish "
                    f"{repeat['finish_reason']} | cache {repeat['cache_state']}")
            lines.append('')
            lines.append('Aggregated over finite samples: ' + json.dumps(
                workload.get('aggregation'), sort_keys=True))
            lines.append('')
            memory = workload.get('memory') or {}
            lines.append(f"Memory ({memory.get('declared_device_pci_id')}): "
                         f"{'observed ' + str(memory.get('before')) + ' -> ' + str(memory.get('after')) + ' bytes (device-wide, workload window)' if memory.get('available') else 'UNAVAILABLE'}")
            for limitation in workload.get('limitations') or []:
                lines.append(f'- limitation: {limitation}')
            for finding in workload.get('metering_consistency') or []:
                lines.append(f"- metering finding (repeat {finding['repeat']}): "
                             f"{finding['finding']} — {finding['attribution']}")
            lines.append('')
        lines.append('## Profile attribution')
        lines.append('')
        lines.append('```json')
        lines.append(json.dumps(summary_record['profile_attribution'],
                                indent=2, sort_keys=True))
        lines.append('```')
        lines.append('')
        lines.append('## Comparison eligibility')
        lines.append('')
        if comparison:
            lines.append(f"Provided comparison profile "
                         f"`{comparison['compare_profile_id']}`: **{comparison['class']}**. "
                         + {
                             'MATCHED_RUNTIME':
                                 'Material controls match; the runtime identity is the '
                                 'compared variable (recorded, not required identical) — '
                                 'controlled runtime comparison permitted.',
                             'SAME_DEPLOYMENT':
                                 'Identical deployment: a repeatability comparison within '
                                 'one deployment.',
                             'DEPLOYMENT_STACK':
                                 'Material conditions differ: a deployment-stack '
                                 'comparison — deployments are reported independently '
                                 'and never averaged.',
                             'INSUFFICIENT_COMPARABILITY':
                                 'An essential comparison condition is missing or '
                                 'unverifiable — the limitation is reported; no '
                                 'equivalence is inferred.',
                         }[comparison['class']])
            lines.append('')
            lines.append('```json')
            lines.append(json.dumps(comparison, indent=2, sort_keys=True))
            lines.append('```')
        else:
            lines.append(compare_profiles(profile, profile)['rule'])
        lines.append('')
        text = '\n'.join(lines) + '\n'
        report = target / 'SECTION-REPORT.md'
        if report.exists():
            if report.read_text() != text:
                raise policy.CheckError('finalization.report: refusing rewrite')
        else:
            store.put(report, text.encode())
        files = {str(p.relative_to(target)): policy.file_sha(p)
                 for p in target.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        store.put_json(target / 'manifest.json',
                       {'schema_version': 1, 'files': files,
                        'profile_revision': config['profile_revision']})
        reporting.verify_manifest(target)
        return {'disposition': 'PASS', 'report': str(report),
                'state': summary['state'], 'overall': overall}
