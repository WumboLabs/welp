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
#: - input_usage.{total_input_tokens, cache_n, native_prompt_n,
#:   uncached_native_prompt_tokens, native_cache_state}  [tokens, verbatim
#:   native counts plus the runtime's total input usage; prompt_n is the
#:   native prompt-interval count (the uncached portion under reuse),
#:   cache_n the independent reuse counter; the split scopes comparisons
#:   to compatible quantities, never reconciles them]
#: - native_tokens_per_second.prompt_interval_scope  [full_prompt only with
#:   native no-reuse evidence; uncached_native_interval under cache reuse;
#:   UNKNOWN otherwise — a cached-interval rate is never presented as a
#:   full-prompt processing rate]
#: - finish_reason, usage_source [verbatim]


def _finite_positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and value not in (float('inf'), float('-inf'))
            and value > 0)


#: Prospective input-token/cache interpretation, versioned and attributed
#: (SPEC §4.12 metering-consistency clarified 2026-11-11 after the
#: Qwen3.8-Flash-Next/Strata/R9700 campaign): the runtime's
#: ``usage.prompt_tokens`` is TOTAL input usage (cached plus uncached),
#: while the native ``prompt_n`` is the native prompt-interval count (the
#: tokens the native prompt phase processed — the uncached portion
#: whenever reuse happened) and ``cache_n`` is the independent reuse
#: counter; neither is a subset of the other. The compatible split check
#: is ``prompt_n + cache_n`` against the total input usage per the native
#: llama.cpp contract; cache is never subtracted twice. Native rates,
#: wall-clock numerators and metering findings compare only compatible
#: quantities: a native prompt rate or wall-clock prompt estimate over a
#: cached five-token interval is never presented as a full-prompt
#: processing rate, negative counters and unreconciled shapes produce no
#: derived rates, and missing evidence stays UNKNOWN/UNAVAILABLE — never
#: zero. Historical finalized evidence keeps its original accounting;
#: this attribution applies to summaries derived with it (finalized
#: sections are never re-derived).
TIMING_INTERPRETATION = {
    'version': 'native-input-cache-split/1',
    'rule': (
        'usage.prompt_tokens is total input usage (cached plus uncached); '
        'native prompt_n is the native prompt interval count (the uncached '
        'portion when reuse happened) and cache_n is the independent reuse '
        'counter, both verbatim. The compatible split check is prompt_n + '
        'cache_n against the total input usage per the native llama.cpp '
        'contract; cache is never subtracted twice. Native prompt rates and '
        'wall-clock prompt estimates are scoped to their compatible interval: '
        'full prompt only with native no-reuse evidence (cache_n == 0) '
        'without a contradicting total, the uncached/native interval under '
        'reconciled reuse, otherwise UNKNOWN. A cached-interval rate is '
        'never presented as a full-prompt rate; negative counters and '
        'unreconciled splits produce no derived rates; metering findings '
        'compare compatible quantities; missing evidence stays '
        'UNKNOWN/UNAVAILABLE, never zero. Historical finalized evidence '
        'retains its original accounting'),
}


def _count(value):
    """A verbatim integer counter, else None. Never coerced, never zeroed."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _cache_interpretation(cache_state, usage):
    """Compatible-quantity reading of the verbatim input/cache observation.

    Native counter semantics (llama.cpp contract, read runtime-
    independently): ``prompt_n`` is the native prompt-interval count — the
    tokens the native prompt phase processed, i.e. the uncached portion
    whenever reuse happened — and ``cache_n`` is the independent reuse
    counter; neither is a subset of the other, so the cache is never
    subtracted from the interval count. States: UNOBSERVED (no native
    counts reported), PARTIAL (exactly one reported), SPLIT (both
    nonnegative counters reported), INCOHERENT (a negative counter — no
    derived rates). Interval scope: full_prompt requires no-reuse evidence
    (cache_n == 0) with no contradicting total; reconciled reuse
    (prompt_n + cache_n == total, or no total reported) scopes the interval
    to the uncached portion; an unreconciled total leaves the interval
    coverage unresolved (native_prompt_interval, no derived prompt rates).
    The total input usage is never substituted for an interval count or
    vice versa.
    """
    pair = cache_state if isinstance(cache_state, dict) else {}
    cache_n = _count(pair.get('cache_n'))
    prompt_n = _count(pair.get('prompt_n'))
    total = _count(usage.get('prompt_tokens')) if isinstance(usage, dict) else None
    if cache_n is None and prompt_n is None:
        state, scope, uncached = 'UNOBSERVED', 'UNKNOWN', None
    elif min(value for value in (cache_n, prompt_n) if value is not None) < 0:
        state, scope, uncached = 'INCOHERENT', 'UNKNOWN', None
    elif prompt_n is None:
        # cache_n without prompt_n: no interval count to divide by
        state, scope, uncached = 'PARTIAL', 'UNKNOWN', None
    elif cache_n is None:
        # prompt_n alone: the native interval count; whether it covered the
        # full prompt is not established without reuse evidence
        state, scope, uncached = 'PARTIAL', 'native_prompt_interval', prompt_n
    elif cache_n == 0 and (total is None or total == prompt_n):
        state, scope, uncached = 'SPLIT', 'full_prompt', prompt_n
    elif cache_n > 0 and (total is None or total == prompt_n + cache_n):
        state, scope, uncached = 'SPLIT', 'uncached_native_interval', prompt_n
    else:
        # both counters reported but they do not reconcile with the runtime's
        # total input accounting: interval count stays verbatim, coverage
        # unresolved, no derived prompt rates
        state, scope, uncached = 'SPLIT', 'native_prompt_interval', prompt_n
    return {'total_input_tokens': total if total is not None else 'UNAVAILABLE',
            'cache_n': cache_n if cache_n is not None else 'UNKNOWN',
            'native_prompt_n': prompt_n if prompt_n is not None else 'UNKNOWN',
            'uncached_native_prompt_tokens':
                uncached if uncached is not None else 'UNKNOWN',
            'native_cache_state': state,
            'interval_scope': scope}


def _wall_clock_estimates(timings):
    """Honest wall-clock derivatives, never presented as native throughput.

    prompt window ≈ time to first generated delta (the prompt-processing
    span ends when generation starts); generation window ≈ total latency
    minus that span. Each estimate divides only a numerator compatible
    with its window (TIMING_INTERPRETATION): the prompt estimate uses the
    total input usage only with native no-reuse evidence (cache_n == 0),
    otherwise the native interval count, and stays UNKNOWN when the cache
    state is unobserved, partial, incoherent (negative counter) or an
    unreconciled split — total usage over a TTFT that covered only a
    cached five-token remainder would be a giant fabricated full-prompt
    rate, and disputed counter shapes produce no derived rates. UNKNOWN
    provenance stays UNKNOWN.
    """
    usage = timings.get('usage') or {}
    latency = timings.get('latency_seconds')
    ttft = timings.get('ttft_seconds')
    interp = _cache_interpretation(timings.get('cache_state'), usage)
    estimates = {'provenance': 'derived_wall_clock', 'unit': 'tokens_per_second',
                 'prompt_per_second': 'UNKNOWN',
                 'prompt_numerator_scope': interp['interval_scope'],
                 'prompt_estimate_basis': None,
                 'completion_numerator_scope': 'runtime_completion_tokens',
                 'completion_tokens_note': (
                     "usage.completion_tokens is the runtime's own inclusive "
                     'completion accounting (reasoning tokens included where '
                     'the runtime reports them)'),
                 'generation_per_second': 'UNKNOWN'}
    window_ok = _finite_positive(latency) and _finite_positive(ttft) and 0 < ttft < latency
    numerator = None
    if not window_ok:
        estimates['prompt_estimate_basis'] = (
            'wall-clock prompt window unavailable (a positive TTFT below the '
            'total latency is required)')
    elif interp['interval_scope'] == 'full_prompt':
        numerator = (_count(interp['total_input_tokens'])
                     or _count(interp['uncached_native_prompt_tokens']))
        if not numerator:
            estimates['prompt_estimate_basis'] = (
                'native interval reports no processed prompt tokens')
    elif interp['interval_scope'] == 'uncached_native_interval':
        numerator = _count(interp['uncached_native_prompt_tokens'])
        if not numerator:
            estimates['prompt_estimate_basis'] = (
                'no uncached prompt tokens processed in the window (fully '
                'served from cache)')
    elif (interp['interval_scope'] == 'native_prompt_interval'
            and interp['native_cache_state'] == 'PARTIAL'):
        # one-sided evidence with no known contradiction: the interval count
        # over its own native window stays a compatible division
        numerator = _count(interp['uncached_native_prompt_tokens'])
        if not numerator:
            estimates['prompt_estimate_basis'] = (
                'native interval reports no processed prompt tokens')
    elif interp['native_cache_state'] == 'UNOBSERVED':
        estimates['prompt_estimate_basis'] = (
            'native cache evidence unreported; total input usage over TTFT is '
            'not a compatible full-prompt numerator when cache reuse is possible')
    elif interp['native_cache_state'] == 'PARTIAL':
        estimates['prompt_estimate_basis'] = (
            'native prompt_n unreported; no compatible prompt numerator')
    elif interp['native_cache_state'] == 'INCOHERENT':
        estimates['prompt_estimate_basis'] = (
            'negative native counter; no derived rate is produced')
    else:
        estimates['prompt_estimate_basis'] = (
            'native interval count does not reconcile with the runtime total '
            'input accounting; no derived prompt rate is produced')
    if numerator:
        estimates['prompt_per_second'] = round(numerator / ttft, 3)
        estimates['prompt_numerator_scope'] = interp['interval_scope']
    completion_tokens = usage.get('completion_tokens')
    if (window_ok and _count(completion_tokens) and completion_tokens > 0):
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
    interp = _cache_interpretation((timings or {}).get('cache_state'),
                                   (timings or {}).get('usage') or {})
    record = {
        'required_field_gaps': required,
        'native_tokens_per_second': {'prompt': rates.get('prompt'),
                                     'generation': rates.get('generation'),
                                     'provenance': 'native_engine_timings',
                                     'unit': 'tokens_per_second',
                                     'prompt_interval_scope': interp['interval_scope'],
                                     'prompt_interval_note': (
                                         'native prompt metering covers only this '
                                         'interval; a cache-reuse interval rate is '
                                         'never a full-prompt processing rate')},
        'observed_wall_clock': _wall_clock_estimates(timings),
        'input_usage': {
            'total_input_tokens': interp['total_input_tokens'],
            'cache_n': interp['cache_n'],
            'native_prompt_n': interp['native_prompt_n'],
            'uncached_native_prompt_tokens': interp['uncached_native_prompt_tokens'],
            'native_cache_state': interp['native_cache_state'],
            'provenance': (
                "usage.prompt_tokens is the runtime's total input usage (cached "
                'plus uncached); native prompt_n/cache_n verbatim; the split '
                'scopes comparisons to compatible quantities, never reconciles')},
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


def _scope_aggregate(repeats, value_getter, scope_getter):
    """Min/median/max within one compatible scope at a time."""
    grouped = {}
    for repeat in repeats:
        value = value_getter(repeat)
        if _finite_positive(value):
            grouped.setdefault(scope_getter(repeat), []).append(value)
    return {scope: {'min': min(values), 'median': statistics.median(values),
                    'max': max(values), 'samples': len(values),
                    'unit': 'tokens_per_second'}
            for scope, values in sorted(grouped.items())}


def _aggregate(repeats):
    """Min/median/max over the repeats for each finite numeric metric.

    Originals are always retained verbatim beside the summary; a metric
    with any UNKNOWN repeat stays UNKNOWN-level honest (aggregated only
    over the finite subset, with the covered count stated). Prompt
    throughput is additionally aggregated only within one compatible
    prompt interval scope: when repeats span intervals (cached-reuse
    intervals beside full prompts) the mixed aggregate is suppressed and
    only the per-scope aggregates remain — a five-token cached-interval
    rate is never medianed into a full-prompt figure.
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
    for key, getter in (
            ('native_tokens_per_second.prompt',
             lambda r: (r['native_tokens_per_second']['prompt'],
                        r['native_tokens_per_second'].get('prompt_interval_scope',
                                                          'UNKNOWN'))),
            ('observed_wall_clock.prompt_per_second',
             lambda r: (r['observed_wall_clock']['prompt_per_second'],
                        r['observed_wall_clock'].get('prompt_numerator_scope',
                                                     'UNKNOWN')))):
        scoped = _scope_aggregate(repeats, lambda r, g=getter: g(r)[0],
                                  lambda r, g=getter: g(r)[1])
        if not scoped:
            continue
        aggregation[key + '_by_scope'] = scoped
        if len(scoped) > 1:
            # distinct prompt intervals are not one comparable quantity
            aggregation.pop(key, None)
        elif key in aggregation:
            aggregation[key]['scope'] = next(iter(scoped))
    return aggregation


def _metering_consistency(repeats):
    """Native-vs-usage cross-check over compatible quantities only.

    Generated tokens (native predicted_n vs usage completion_tokens) are
    the same quantity: disagreement is recorded as an unresolved
    measurement-validity finding attributed to the runtime/interface —
    never silently corrected by WELP. Input tokens are compared only
    compatibly (TIMING_INTERPRETATION): per the native llama.cpp contract
    the check is prompt_n + cache_n (interval count plus independent reuse
    counter) against the TOTAL input usage — the cache is never subtracted
    from the interval count; with cache_n unreported, a bare prompt_n
    difference against total input is labeled with the quantity caveat.
    A reconciled split is not a finding (compatible quantities, both
    preserved verbatim). A negative native counter is itself a finding and
    produces no derived rates anywhere.
    """
    findings = []
    for index, timing in enumerate(repeats, 1):
        native = timing.get('native_timings')
        usage = timing.get('usage') or {}
        if not isinstance(native, dict):
            continue
        predicted_n = _count(native.get('predicted_n'))
        completion = _count(usage.get('completion_tokens'))
        if predicted_n is not None and completion is not None and predicted_n != completion:
            findings.append({
                'repeat': index,
                'quantity': 'generated_tokens',
                'finding': f'native predicted_n={predicted_n} vs usage '
                           f'completion_tokens={completion}',
                'attribution': 'runtime/interface metering disagreement; '
                               'measurement validity unresolved',
                'resolution': 'both observations preserved verbatim; never reconciled'})
        prompt_n = _count(native.get('prompt_n'))
        cache_n = _count(native.get('cache_n'))
        total = _count(usage.get('prompt_tokens'))
        negatives = [f'{name}={value}' for name, value in
                     (('prompt_n', prompt_n), ('cache_n', cache_n))
                     if value is not None and value < 0]
        if negatives:
            findings.append({
                'repeat': index,
                'quantity': 'native_counters',
                'finding': f'negative native counter {", ".join(negatives)}; '
                           'no derived rate is produced',
                'attribution': 'runtime/interface metering defect; '
                               'measurement validity unresolved',
                'resolution': 'observations preserved verbatim; never reconciled'})
        elif prompt_n is not None and total is not None and prompt_n + (cache_n or 0) != total:
            if cache_n is not None:
                finding = (f'native prompt_n={prompt_n} + cache_n={cache_n} != usage '
                           f'prompt_tokens={total}')
                quantity = 'input_tokens_split'
            else:
                finding = (f'native prompt_n={prompt_n} vs usage prompt_tokens={total} '
                           '(cache_n unreported; total-input and interval counts may '
                           'be different quantities)')
                quantity = 'input_tokens'
            findings.append({
                'repeat': index,
                'quantity': quantity,
                'finding': finding,
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
    scopes = sorted({repeat['native_tokens_per_second']['prompt_interval_scope']
                     for repeat in repeats})
    if 'uncached_native_interval' in scopes or 'native_prompt_interval' in scopes:
        limitations.append('native prompt throughput on these repeats meters the native '
                           'prompt interval; full-prompt processing coverage is established '
                           'only by native no-reuse evidence (cache_n == 0)')
    if len([scope for scope in scopes if scope != 'UNKNOWN']) > 1:
        limitations.append('prompt throughput spans distinct prompt intervals across '
                           'repeats; aggregation is per-scope and the mixed aggregate '
                           'is suppressed')
    for index, record in enumerate(repeats, 1):
        if record['native_tokens_per_second']['prompt'] == 'UNKNOWN':
            limitations.append(f'repeat-{index}: native prompt throughput unreported '
                               '(reported unavailable, never zero)')
        if record['native_tokens_per_second']['generation'] == 'UNKNOWN':
            limitations.append(f'repeat-{index}: native generation throughput unreported '
                               '(reported unavailable, never zero)')
        wall = record['observed_wall_clock']
        if wall['prompt_per_second'] == 'UNKNOWN' and wall.get('prompt_estimate_basis'):
            limitations.append(f"repeat-{index}: wall-clock prompt estimate withheld — "
                               f"{wall['prompt_estimate_basis']}")
        if record['ttft_seconds'] == 'UNKNOWN' and (conditions.get('timings') or {}).get('streaming'):
            limitations.append(f'repeat-{index}: time-to-first-token unobservable')
    memory = _memory_observations(profile, path)
    if not memory['available']:
        limitations.append('memory telemetry unavailable from the deployment observer '
                           '(reported unavailable, never zero)')
    return {'unit_id': task['id'], 'workload': task.get('workload'),
            'classification': classification, 'outcome': outcome, 'reason': reason,
            'timing_interpretation': {
                'version': TIMING_INTERPRETATION['version'],
                'attribution': (
                    'summary-derivation lens only: usage, native counts, rates and '
                    'wall clocks above are the attempt evidence verbatim; the split/'
                    'scoping fields are derived at summary time under this version and '
                    'never rewritten into the attempt record')},
            'repetitions_expected': task.get('repetitions', 1),
            'repeats': repeats, 'aggregation': _aggregate(repeats),
            'metering_consistency': _metering_consistency(timings),
            'memory': memory,
            'measurement_conditions': {
                'streaming': (conditions.get('timings') or {}).get('streaming'),
                'cache_condition': 'cache_prompt disabled on the native llama.cpp '
                                   'contract; native cache_n/prompt_n observed verbatim',
                'timing_interpretation_version': TIMING_INTERPRETATION['version'],
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
            'timing_interpretation': TIMING_INTERPRETATION,
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
                split = repeat.get('input_usage') or {}
                lines.append(
                    f"- repeat {index}: native {native['prompt']}/{native['generation']} tok/s "
                    f"(engine metering, prompt interval {native.get('prompt_interval_scope', 'UNKNOWN')}) | "
                    f"wall-clock estimate "
                    f"{wall['prompt_per_second']}/{wall['generation_per_second']} tok/s "
                    f"(derived, distinct; prompt numerator scope "
                    f"{wall.get('prompt_numerator_scope', 'UNKNOWN')}) | TTFT {repeat['ttft_seconds']} s, first byte "
                    f"{repeat['first_byte_seconds']} s, total {repeat['latency_seconds']} s | "
                    f"usage {usage.get('prompt_tokens')}+{usage.get('completion_tokens')} tok "
                    f"(reasoning {repeat['reasoning_tokens']}; input split: "
                    f"{split.get('total_input_tokens', 'UNAVAILABLE')} total, "
                    f"{split.get('uncached_native_prompt_tokens', 'UNKNOWN')} uncached native, "
                    f"cache_n {split.get('cache_n', 'UNKNOWN')}) | finish "
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
