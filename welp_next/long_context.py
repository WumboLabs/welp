"""Advanced Long Context section — gated Model-side specialist section.

Purpose (SPEC §4.1.1/§4.9): evaluate how accurately a model retrieves,
retains, reconciles and uses information distributed across lengthy inputs —
technical capacity, useful context and reasoning over context are distinct
concerns. The section reuses the accepted M2 scoring surface (`probe` scorer
with strict json_schema oracles including pinned semantic values; no keyword
grading; internal reasoning style/length never scored).

Inventory (frozen before any authentic evaluation; none has run):
`fixtures/long_context/advanced-tasks.json` — three authored tasks whose
lengthy contexts were constructed deterministically (seed 42) at authoring:
distributed retrieval with same-shape decoys at controlled depths,
supersession-chain synthesis across embedded documents, and long-span
retention with a late revision notice. Intended checkpoint sizes are
authoring targets (≈8K/≈8K/≈12K rendered-token classes); actual native token
counts are measured natively at authentic run and validated against the
qualified deployment's context capacity — an unsupported checkpoint is a
technical applicability outcome, never a model FAIL.

Gate: recorded `long-context` ADVANCE decision or attributed EXPLORATORY
authorization — computed from the campaign baseline (in-campaign or by
reuse attribution, identical guarantees to the coding/reasoning sections).
The M2-era context witness outcome (DEFERRED: highest Multi-Document
semantic result budget-limited) is a retained finding; it blocks standard
ADVANCE and never fabricates eligibility — HUMAN_DIRECTED/EXPLORATORY
remains available for explicitly authorized specialist testing.

Attempts are committed by `runner.execute` under the M2 methodology pin;
this module owns inventory, gate, status/resume/report (replay-based
finalization, manifest binding, idempotent report).
"""
import json
from pathlib import Path
import signal

from . import coding, context as context_prep, policy, preflight, reporting, runner, store

SECTION = 'advanced-long-context'
METHODOLOGY = 'long-context-advanced/1'
FIXTURE_RELPATH = 'fixtures/long_context/advanced-tasks.json'
_ALLOWED_CONFIG_KEYS = frozenset()

_fail = coding._fail


def _advancement_gate(profile):
    # Identical witness/reuse semantics as the coding gate; the recorded
    # decision read is the long-context one.
    return coding._advancement_gate(profile, section='long-context')


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def load_tasks():
    fixture = json.loads((policy.PROJECT_ROOT / FIXTURE_RELPATH).read_text())
    if fixture.get('schema_version') != 1 or not fixture.get('tasks'):
        _fail('long_context.fixture', 'unsupported fixture')
    tasks = {t['id']: t for t in fixture['tasks']}
    if len(tasks) != len(fixture['tasks']):
        _fail('long_context.fixture', 'duplicate task identities')
    return fixture, tasks


def _native_prompt_tokens(profile, task, admission):
    """Actual rendered prompt-token count via the qualified native metadata
    paths (/apply-template + /tokenize). Metadata only; never inference."""
    render, tokenize = context_prep.token_client(profile)
    prompt = render(task['messages'])
    ids = tokenize(prompt)
    return len(ids)


def _geometry_receipt(profile, task, prompt_tokens, feasible):
    return {'unit_id': task['id'], 'intended_checkpoint_tokens':
            task.get('intended_checkpoint_tokens'),
            'native_prompt_tokens': prompt_tokens,
            'completion_reserve_tokens': policy.task_budget(profile, task)['max_tokens'],
            'context_capacity_tokens': profile['runtime']['context_capacity'],
            'feasible': feasible,
            'disposition': ('TECHNICAL_INFEASIBLE_NOT_RUN' if not feasible
                            else 'ELIGIBLE')}


def plan(profile, config=None):
    policy.validate_profile(profile)
    config = coding._config(config)
    fixture, tasks = load_tasks()
    checks = preflight.offline(profile)
    gate = _advancement_gate(profile)
    for uid, task in tasks.items():
        needed = task['intended_checkpoint_tokens'] + profile['budgets']['max_tokens']
        capacity = profile['runtime']['context_capacity']
        if needed > capacity:
            _fail('long_context.geometry',
                  f'{uid}: intended checkpoint {task["intended_checkpoint_tokens"]} '
                  f'tokens plus completion reserve {profile["budgets"]["max_tokens"]} '
                  f'exceeds the qualified context capacity {capacity} — technical '
                  'applicability limit, not a model outcome')
    return {'section': SECTION, 'methodology': METHODOLOGY,
            'evidence_kind': profile['evidence_kind'],
            'profile_revision': policy.digest(profile),
            'unit_ids': list(tasks), 'fixture_sha256': policy.digest(fixture),
            'gate': gate, 'preflight': checks, 'config': config}


def _identity(profile, fixture, tasks, planned):
    return {'profile': profile, 'profile_revision': policy.digest(profile),
            'methodology': METHODOLOGY, 'section': SECTION,
            'unit_ids': list(tasks), 'fixture_sha256': policy.digest(fixture),
            'software': runner.software_identity(),
            'admission_version': policy.ADMISSION_VERSION,
            'gate': planned['gate']}


def _validate_attempt(config, tasks, uid, row):
    path = Path(row['path'])
    conditions = store.read_json(path / 'conditions.json')
    profile = policy.recorded_profile(config, conditions)
    policy.validate_echo(profile, conditions['preflight']['echo'])
    if conditions.get('request_limits') != policy.task_budget(profile, tasks[uid]):
        raise policy.CheckError(f'validation.long_context.{uid}: changed budget attribution')
    replayed, fatal = runner.replay_attempt(profile, tasks[uid], path)
    if fatal != conditions.get('fatal_device_condition'):
        raise policy.CheckError(f'validation.long_context.{uid}.safety: false fatal attribution')
    replayed.pop('replay', None)
    for key, value in replayed.items():
        if row.get(key) != value:
            raise policy.CheckError(f'validation.long_context.{uid}.{key}: replay mismatch')


def run(profile, config=None):
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign)
    fixture, tasks = load_tasks()
    config = coding._config(config)
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if not policy.compatible_profiles(saved['profile'], profile):
            raise policy.CheckError('recovery.long_context: changed finalized configuration')
        return status(campaign)
    planned = plan(profile, config)
    identity = _identity(profile, fixture, tasks, planned)
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['fixture_sha256'] != identity['fixture_sha256']):
                raise policy.CheckError('recovery.long_context: changed scientific configuration')
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
                # Native geometry admission before dispatch (SPEC §4.9):
                # metadata-only measurement of the actual rendered prompt; an
                # infeasible task is a technical NOT_RUN that never dispatches
                # scored inference and never blocks independent eligible tasks.
                prompt_tokens = _native_prompt_tokens(profile, task, admission)
                reserve = policy.task_budget(profile, task)['max_tokens']
                capacity = profile['runtime']['context_capacity']
                feasible = prompt_tokens + reserve <= capacity
                receipt = _geometry_receipt(profile, task, prompt_tokens, feasible)
                store.put_json(target / f'geometry-{uid}.json', receipt)
                store.append_event(target, {
                    'event': 'FEASIBLE' if feasible else 'GEOMETRY_INFEASIBLE',
                    'unit_id': uid, 'native_prompt_tokens': prompt_tokens,
                    'at': runner.now()})
                if not feasible:
                    store.append_event(target, {
                        'event': 'TECHNICAL_NOT_RUN', 'unit_id': uid,
                        'at': runner.now()})
                    continue
                while not stop and policy.unit_pending(store.attempts(target, uid)):
                    path = store.new_attempt(target, uid, preparing=True)
                    store.append_event(target, {'event': 'PREPARING', 'unit_id': uid,
                                               'attempt_id': path.name, 'at': runner.now()})
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
    technical_not_run = {}
    events_path = target / 'units.jsonl'
    if events_path.exists():
        for line in events_path.read_text().splitlines():
            event = json.loads(line)
            if event.get('event') == 'GEOMETRY_INFEASIBLE':
                technical_not_run[event['unit_id']] = event.get('native_prompt_tokens')
    for uid, attempts in units.items():
        if uid in technical_not_run and not attempts:
            rows.append({'unit_id': uid, 'attempts': 0, 'resolved_attempt': None,
                         'outcome': 'NOT_RUN',
                         'reason': 'TECHNICAL_INFEASIBLE: native rendered prompt '
                                   f'({technical_not_run[uid]} tokens) plus the accepted '
                                   'completion reserve exceeds the qualified context capacity',
                         'pending': False})
            continue
        resolved = policy.resolved_attempt(attempts)
        rows.append({'unit_id': uid, 'attempts': len(attempts),
                     'resolved_attempt': resolved['attempt_id'] if resolved else None,
                     'outcome': resolved['outcome'] if resolved else 'NOT_RUN',
                     'reason': resolved.get('reason') if resolved else None,
                     'pending': policy.unit_pending(attempts)})
    admissions = store.admission_records(target)
    blocked = bool(admissions) and admissions[-1].get('ok') is False
    # Units resolved as technical NOT_RUN (recorded native geometry
    # infeasibility, no attempts) are not pending work: they are honest
    # coverage gaps, so partial execution is COMPLETED_PARTIAL rather than
    # INTERRUPTED. Fatal/interrupted/blocked states still dominate.
    state_units = {uid: rows for uid, rows in units.items()
                   if not (uid in technical_not_run and not rows)}
    state = policy.section_state(state_units, blocked=blocked)
    if state == 'COMPLETED' and technical_not_run:
        state = 'COMPLETED_PARTIAL'
    return {'section': SECTION, 'state': state,
            'technical_not_run': sorted(technical_not_run),
            'profile_id': config['profile']['profile_id'],
            'evidence_kind': config['profile']['evidence_kind'],
            'methodology': config['methodology'], 'units': rows,
            'preparation_failures': store.preparation_failures(target),
            'remaining_units': [r['unit_id'] for r in rows if r['pending']],
            'finalized': (target / 'manifest.json').exists()}


def resume(campaign, profile=None):
    config = store.read_json(section_path(campaign) / 'run.json')
    if Path(config['profile']['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.long_context: wrong campaign')
    if config['methodology'] != METHODOLOGY:
        raise policy.CheckError('recovery.long_context: methodology mismatch')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.long_context: wrong campaign')
    return run(profile)


def report_section(campaign):
    target = section_path(campaign)
    with store.locked(campaign):
        if (target / 'manifest.json').exists():
            reporting.verify_manifest(target)
            return {'disposition': 'PASS', 'report': str(target / 'SECTION-REPORT.md'),
                    'already_finalized': True}
        config, units = store.inventory(target)
        fixture, tasks = load_tasks()
        profile = config['profile']
        plan(profile)
        summary = status(campaign)
        if summary['remaining_units']:
            raise policy.CheckError('finalization.long_context: pending work; resume first')
        for uid, attempts in units.items():
            for row in attempts:
                if not row.get('finalized'):
                    continue
                _validate_attempt(config, tasks, uid, row)
        reporting.ensure_json(target / 'validation.json', {
            'disposition': 'PASS', 'methodology': METHODOLOGY,
            'evidence_kind': profile['evidence_kind'],
            'scientific_validation': 'EXECUTED'})
        reporting.ensure_json(target / 'summary.json', summary)
        text = ('# WELP — advanced long context\n\n'
                'Strict json_schema oracles with pinned values decide; decoy, '
                'superseded and stale values are decisive FAILs; unsupported '
                'geometry is a technical applicability limit, never a model '
                'failure; transport deadlines are budget-limited.\n\n'
                f'Execution: {summary["state"]}. Independent offline reconstruction: PASS.\n\n'
                '```json\n' + json.dumps(summary, indent=2, sort_keys=True) + '\n```\n')
        report = target / 'SECTION-REPORT.md'
        if report.exists():
            if report.read_text() != text:
                raise policy.CheckError('finalization.report: refusing rewrite')
        else:
            store.put(report, text.encode())
        files = {str(p.relative_to(target)): policy.file_sha(p)
                 for p in target.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        store.put_json(target / 'manifest.json', {'schema_version': 1, 'files': files,
                                                'profile_revision': config['profile_revision']})
        reporting.verify_manifest(target)
        return {'disposition': 'PASS', 'report': str(target / 'SECTION-REPORT.md'),
                'state': summary['state'], 'scientific_validation': 'EXECUTED'}
