"""Advanced Coding section — gated Model-side specialist section.

Purpose (SPEC §4.1/§4.7): measure the ability to produce, debug, modify and
verify functioning software — distinct from the Agentic repository task, which
evaluates autonomous multi-step execution and decision-making. The section
reuses the accepted M2 coding machinery verbatim: sandbox-executed frozen
unittest oracles (`coding_sandbox` scorer + `sandbox` boundary), profile
task budgets (`policy.task_budget`; coding category override), decisive
format-failure rules, and attempt accounting. Attempts are committed under
the M2 methodology pin by `runner.execute`; this module owns the section
inventory (three frozen authored tasks in `fixtures/coding/advanced-tasks.json`,
frozen before any authentic evaluation), the advancement gate, and section
status/report/recovery.

Gate: the section runs only on a recorded `ADVANCE` decision for `coding`
(e.g. capability-witness/2) computed by `m3.decisions` from the campaign's
finalized baseline, or an explicit EXPLORATORY authorization — never on a
caller assertion. Weak baselines defer; they are never permanently
disqualified (SPEC §4.5).

Fault attribution stays with the existing outcome machinery: model failures
are FAIL, boundary unavailability is INVALID, transport deadline is
BUDGET-limited, device events are fatal safety stops.
"""
import json
from pathlib import Path
import signal

from . import m3, policy, preflight, reporting, runner, store

SECTION = 'coding'
METHODOLOGY = 'coding-advanced/1'
FIXTURE_RELPATH = 'fixtures/coding/advanced-tasks.json'
_ALLOWED_CONFIG_KEYS = frozenset()


def _fail(field, message):
    raise policy.CheckError(f'{field}: {message}', field=field)


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def load_tasks():
    fixture = json.loads((policy.PROJECT_ROOT / FIXTURE_RELPATH).read_text())
    if fixture.get('schema_version') != 1 or not fixture.get('tasks'):
        _fail('coding.fixture', 'unsupported fixture')
    tasks = {t['id']: t for t in fixture['tasks']}
    if len(tasks) != len(fixture['tasks']):
        _fail('coding.fixture', 'duplicate task identities')
    return fixture, tasks


def _advancement_gate(profile, section='coding'):
    """Recorded advancement decision for a Model-side advanced section:
    ADVANCE, or EXPLORATORY with its operator attribution. The decision is
    computed from the campaign's finalized baseline — held in the campaign
    itself or, when the profile records `deployment.reuse_baseline`, in the
    referenced campaign by manifest-bound attribution (verified in place,
    never copied; same guarantees as the scored route's baseline reuse).
    Everything else blocks before any dispatch."""
    campaign = Path(profile['campaign_root'])
    reference = (profile.get('deployment') or {}).get('reuse_baseline')
    # Recorded HUMAN_DIRECTED/EXPLORATORY authorization for this section
    # (operator attribution from the authorizing handoff). It never fabricates
    # an ADVANCE: the standard eligibility decision is computed unchanged and
    # preserved alongside the EXPLORATORY selection.
    recorded_exploratory = (profile.get('deployment') or {}).get('exploratory_authorization')
    exploratory_inputs = ({section: dict(recorded_exploratory)}
                          if isinstance(recorded_exploratory, dict) else None)
    if reference is not None:
        missing = [key for key in ('campaign_root', 'section_manifest_sha256')
                   if not reference.get(key)]
        if missing:
            _fail('coding.baseline', 'recorded reuse attribution requires ' + str(missing))
        baseline_section = Path(reference['campaign_root']) / 'sections' / 'baseline'
        if policy.file_sha(baseline_section / 'manifest.json') != reference['section_manifest_sha256']:
            _fail('coding.baseline', 'recorded manifest identity mismatch')
        config, model = reporting.finalized_model_evidence(baseline_section)
        if not policy.compatible_profiles(config['profile'], profile):
            _fail('coding.baseline', 'incompatible scientific configuration')
        evidence = {'profile_id': config['profile']['profile_id'],
                    'profile_revision': config['profile_revision'],
                    'evidence_kind': config['profile']['evidence_kind'],
                    'manifest_sha256': reference['section_manifest_sha256'],
                    'methodology': config['profile']['framework']['methodology'],
                    'fixture_sha256': config['fixture_sha256'],
                    'task_categories': {task['id']: task['category'] for task in
                                        store.read_json(baseline_section / 'fixture.json')['tasks']},
                    'effective_scores': model['effective_scores'],
                    'coverage': model['coverage']}
        from . import advancement
        bound = advancement.bound_decisions(evidence, exploratory=exploratory_inputs)
        decision = bound['result']['decisions'][section]
        standard = decision['decision']
        reason = decision['reason']
        authorization = decision.get('exploratory_authorization')
        standard_eligibility = decision.get('standard_eligibility')
    else:
        value = m3.decisions(campaign, {'exploratory': exploratory_inputs} if exploratory_inputs else None)
        decision = value['decisions']['result']['decisions'][section]
        standard = decision['decision']
        reason = decision['reason']
        authorization = decision.get('exploratory_authorization')
        standard_eligibility = decision.get('standard_eligibility')
    if standard == 'ADVANCE':
        return {'decision': 'ADVANCE', 'reason': reason, 'exploratory': None}
    if standard == 'EXPLORATORY':
        if not authorization or not authorization.get('operator') \
                or not authorization.get('authorization'):
            _fail('coding.advancement', 'EXPLORATORY decision lacks recorded operator attribution')
        return {'decision': 'EXPLORATORY', 'reason': reason,
                'exploratory': authorization, 'standard_decision': standard,
                'standard_eligibility': standard_eligibility}
    raise policy.CheckError(
        f'{section}.advancement: {standard}; this section requires a recorded '
        'ADVANCE decision (capability evidence) or EXPLORATORY authorization — '
        'weak baselines defer and are never permanently disqualified')


def _config(config):
    if config is None:
        config = {}
    if not isinstance(config, dict) or set(config) - _ALLOWED_CONFIG_KEYS:
        _fail('coding.config', 'no caller-configurable keys; tasks, budgets, '
              'checkers and scoring are frozen section identities')
    return {}


def plan(profile, config=None):
    policy.validate_profile(profile)
    config = _config(config)
    fixture, tasks = load_tasks()
    checks = preflight.offline(profile)
    gate = _advancement_gate(profile)
    if 'sandbox' in {requirement for task in tasks.values()
                     for requirement in task.get('requires', [])} \
            and profile.get('capabilities', {}).get('sandbox') is not True:
        _fail('coding.sandbox', 'INTEGRATION_BLOCKED isolation not qualified')
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
        raise policy.CheckError(f'validation.coding.{uid}: changed budget attribution')
    replayed, fatal = runner.replay_attempt(profile, tasks[uid], path)
    if fatal != conditions.get('fatal_device_condition'):
        raise policy.CheckError(f'validation.coding.{uid}.safety: false fatal attribution')
    replayed.pop('replay', None)
    for key, value in replayed.items():
        if row.get(key) != value:
            raise policy.CheckError(f'validation.coding.{uid}.{key}: replay mismatch')


def run(profile, config=None):
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign)
    fixture, tasks = load_tasks()
    config = _config(config)
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if not policy.compatible_profiles(saved['profile'], profile):
            raise policy.CheckError('recovery.coding: changed finalized configuration')
        return status(campaign)
    planned = plan(profile, config)
    identity = _identity(profile, fixture, tasks, planned)
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['fixture_sha256'] != identity['fixture_sha256']):
                raise policy.CheckError('recovery.coding: changed scientific configuration')
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
    for uid, attempts in units.items():
        resolved = policy.resolved_attempt(attempts)
        rows.append({'unit_id': uid, 'attempts': len(attempts),
                     'resolved_attempt': resolved['attempt_id'] if resolved else None,
                     'outcome': resolved['outcome'] if resolved else 'NOT_RUN',
                     'reason': resolved.get('reason') if resolved else None,
                     'partial_progress': resolved.get('record', {}).get('tests_pass')
                     if resolved else None,
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
        raise policy.CheckError('recovery.coding: wrong campaign')
    if config['methodology'] != METHODOLOGY:
        raise policy.CheckError('recovery.coding: methodology mismatch')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.coding: wrong campaign')
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
            raise policy.CheckError('finalization.coding: pending work; resume first')
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
        text = ('# WELP — advanced coding\n\n'
                'Sandbox-executed frozen oracles decide; a no-code-block reply is '
                'a decisive format FAIL; unavailable isolation is INVALID, never '
                'a model failure; transport deadlines are budget-limited.\n\n'
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
