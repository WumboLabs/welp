"""Advanced Reasoning section — gated Model-side specialist section.

Purpose (SPEC §4.1.1/§4.8): deeper evaluation of observable multi-step
reasoning — multi-constraint satisfaction, grounded multi-evidence derivation
with supersession, and revised-condition updating — scored deterministically
on the final observable answer. The section deliberately does NOT score
internal reasoning style, length, or exposed chain-of-thought: a long trace
is not evidence of quality and a short correct answer is never penalized.

Reuse, not novelty: tasks use the accepted M2 `probe` scorer (exact-token
checks on the scored exchange, including one `followups` conversation scored
on the final exchange — the established multi-turn mechanism). Budgets are
the profile's fixed reasoning budget (`policy.task_budget`; no invented
section ceiling). Attempts are committed by `runner.execute` under the M2
methodology pin; this module owns the frozen inventory (three authored tasks
in `fixtures/reasoning/advanced-tasks.json`, frozen before any authentic
evaluation), the advancement gate (including reuse-by-reference baseline
attribution, same guarantees as the coding section), and section
status/resume/report.

Gate: the section runs only on a recorded `ADVANCE` decision for `reasoning`
(e.g. capability-witness/2) or explicit EXPLORATORY authorization — never on
a caller assertion. Weak/uncertain baselines defer; deferral never
permanently disqualifies.
"""
import json
from pathlib import Path
import signal

from . import coding, policy, preflight, reporting, runner, store

SECTION = 'advanced-reasoning'
METHODOLOGY = 'reasoning-advanced/1'
FIXTURE_RELPATH = 'fixtures/reasoning/advanced-tasks.json'
_ALLOWED_CONFIG_KEYS = frozenset()

_fail = coding._fail


def _advancement_gate(profile):
    # Identical witness/reuse semantics as the coding section's gate; the
    # recorded decision read is the reasoning one.
    return coding._advancement_gate(profile, section='reasoning')


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def load_tasks():
    fixture = json.loads((policy.PROJECT_ROOT / FIXTURE_RELPATH).read_text())
    if fixture.get('schema_version') != 1 or not fixture.get('tasks'):
        _fail('reasoning.fixture', 'unsupported fixture')
    tasks = {t['id']: t for t in fixture['tasks']}
    if len(tasks) != len(fixture['tasks']):
        _fail('reasoning.fixture', 'duplicate task identities')
    return fixture, tasks


def plan(profile, config=None):
    policy.validate_profile(profile)
    config = coding._config(config)
    fixture, tasks = load_tasks()
    checks = preflight.offline(profile)
    gate = _advancement_gate(profile)
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
        raise policy.CheckError(f'validation.reasoning.{uid}: changed budget attribution')
    replayed, fatal = runner.replay_attempt(profile, tasks[uid], path)
    if fatal != conditions.get('fatal_device_condition'):
        raise policy.CheckError(f'validation.reasoning.{uid}.safety: false fatal attribution')
    replayed.pop('replay', None)
    for key, value in replayed.items():
        if row.get(key) != value:
            raise policy.CheckError(f'validation.reasoning.{uid}.{key}: replay mismatch')


def run(profile, config=None):
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign)
    fixture, tasks = load_tasks()
    config = coding._config(config)
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if not policy.compatible_profiles(saved['profile'], profile):
            raise policy.CheckError('recovery.reasoning: changed finalized configuration')
        return status(campaign)
    planned = plan(profile, config)
    identity = _identity(profile, fixture, tasks, planned)
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['fixture_sha256'] != identity['fixture_sha256']):
                raise policy.CheckError('recovery.reasoning: changed scientific configuration')
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
        raise policy.CheckError('recovery.reasoning: wrong campaign')
    if config['methodology'] != METHODOLOGY:
        raise policy.CheckError('recovery.reasoning: methodology mismatch')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.reasoning: wrong campaign')
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
            raise policy.CheckError('finalization.reasoning: pending work; resume first')
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
        text = ('# WELP — advanced reasoning\n\n'
                'Deterministic exact-answer oracles decide on the scored '
                'exchange; internal reasoning style, length and exposed '
                'chain-of-thought are never scored; empty or off-format answers '
                'are unscorable, transport deadlines are budget-limited, and '
                'device events are fatal safety stops.\n\n'
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
