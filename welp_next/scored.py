"""Authentic scored M3 Agentic execution — campaign-gated prospective route.

The offline `m3` module stays SOFTWARE_TEST-only. This module owns the
prospective scored route accepted as `agentic/3` (checker/3, native tools,
`agentic-budget/1` standard vectors, REAL_MODEL evidence). Activation
mirrors the calibration precedent: a campaign-bound two-field source gate.
Without activation, every entry point fails closed; no caller argument can
enable execution. Model science prerequisites (SPEC §10.3B): finalized
compatible Model baseline (reused by recorded attribution, never copied),
risk-control witnesses, scored readiness on the same profile/adapter, and
the preselected specialist task.

Scientific conditions and outcomes semantics are those of m3/agentic;
nothing here relaxes budgets, checkers, isolation or attempt accounting.
"""
import json
from pathlib import Path
import signal

from . import advancement, m3, policy, preflight, reporting, runner, store

SCIENTIFIC_METHODOLOGY = policy.SCORED_METHODOLOGY

# Campaign-scoped authorization (corrected 2026-11-08): activation is a
# verified campaign-directory record (`policy.campaign_activation`,
# `campaign-activation.json` bound to campaign + methodology with operator
# attribution) — never a module source delta, which exposed concurrent
# importers to a temporarily authorized process. Fail-closed without the
# record; no caller argument can enable execution.

READINESS_UNITS = ('qualification',)
SPECIALIST_TASKS = ('system', 'research', 'repository')  # predeclared envelope-size ladder

_BASELINE_KEYS = ('campaign_root', 'section_manifest_sha256')


def authorized(profile) -> bool:
    record = policy.campaign_activation(profile.get('campaign_root'),
                                        profile.get('campaign_id'),
                                        SCIENTIFIC_METHODOLOGY)
    return bool(record and 'agentic-scored' in record['sections']
                and profile.get('evidence_kind') == 'REAL_MODEL')


def activation_record(profile):
    """The verified campaign activation record (None when inactive)."""
    return policy.campaign_activation(profile.get('campaign_root'),
                                      profile.get('campaign_id'),
                                      SCIENTIFIC_METHODOLOGY)


def standard_config(section, tasks):
    """Canonical accepted-vector REAL_MODEL configuration for the scored route."""
    from . import agentic
    names = READINESS_UNITS if section == 'agentic-readiness' else tuple(tasks)
    return {
        'evidence_kind': 'REAL_MODEL', 'adapter': 'native_tools',
        'checker_version': 3, 'budget_version': m3.STANDARD_BUDGET_VERSION,
        'limits': {
            name: dict(zip(agentic.LIMIT_KEYS, m3.STANDARD_VECTORS[name]),
                       evidence_kind='REAL_MODEL',
                       source=('agentic-budget/1; operator acceptance 2026-10-25; '
                               'campaign-gated authentic scored execution (agentic/3)'))
            for name in names},
    }


def _limits(config, section, tasks):
    from . import agentic
    expected = standard_config(section, tasks)
    if (not isinstance(config, dict)
            or config.get('evidence_kind') != 'REAL_MODEL'
            or config.get('adapter') != 'native_tools'
            or config.get('checker_version') != 3
            or config.get('budget_version') != m3.STANDARD_BUDGET_VERSION
            or config.get('limits') != expected['limits']):
        raise policy.CheckError(
            'scored.config: only the accepted unmodified standard configuration '
            '(agentic/3, checker/3, native tools, agentic-budget/1) is routable')
    fixtures = {}
    for name in expected['limits']:
        agentic.validate_limits(config['limits'][name])
        fixtures[name] = agentic.load_fixture(name, version=3)
    return fixtures


def _units(section, tasks):
    return READINESS_UNITS if section == 'agentic-readiness' else tuple(tasks)


def _baseline(profile):
    """Reused finalized Model baseline, verified in place at its accepted home.

    The reference campaign is recorded in the scored profile's deployment
    block; this never copies or rewrites accepted evidence.
    """
    reference = (profile.get('deployment') or {}).get('reuse_baseline') or {}
    missing = [key for key in _BASELINE_KEYS if not reference.get(key)]
    if missing:
        raise policy.CheckError('scored.baseline: recorded reuse attribution required '
                                + str(missing))
    campaign = Path(reference['campaign_root'])
    section = campaign / 'sections' / 'baseline'
    if policy.file_sha(section / 'manifest.json') != reference['section_manifest_sha256']:
        raise policy.CheckError('scored.baseline: recorded manifest identity mismatch')
    config, model = reporting.finalized_model_evidence(section)
    if not policy.compatible_profiles(config['profile'], profile):
        raise policy.CheckError('scored.baseline: incompatible scientific configuration')
    summary = runner.status(campaign)
    if summary['state'] not in ('COMPLETED', 'COMPLETED_PARTIAL'):
        raise policy.CheckError('scored.baseline: not finalized')
    return {'profile_id': config['profile']['profile_id'],
            'profile_revision': config['profile_revision'],
            'evidence_kind': config['profile']['evidence_kind'],
            'manifest_sha256': reference['section_manifest_sha256'],
            'reuse_campaign_root': str(campaign),
            'methodology': config['profile']['framework']['methodology'],
            'fixture_sha256': config['fixture_sha256'],
            'task_categories': {task['id']: task['category'] for task in
                store.read_json(section / 'fixture.json')['tasks']},
            'effective_scores': model['effective_scores'],
            'coverage': model['coverage']}


def _section_path(campaign, section):
    if section not in ('agentic-readiness', 'agentic'):
        raise policy.CheckError('scored.section: unsupported section')
    return Path(campaign) / 'sections' / section


def _readiness_gate(campaign, profile):
    """Scored readiness admission plus risk-control witnesses (SPEC §10.3B).

    Readiness is resolved in the campaign itself, or — when the profile
    records `deployment.reuse_readiness` — in the referenced campaign by
    manifest-bound attribution (same mechanism and guarantees as baseline
    reuse: verified in place, never copied, never re-executed for credit).
    """
    from . import agentic
    baseline = _baseline(profile)
    controls = advancement.witness_resolution(baseline['effective_scores'],
        tuple((uid,) for uid in advancement.AGENTIC_CONTROLS))
    if controls is not True:
        disposition = 'NOT_ELIGIBLE' if controls is False else 'DEFERRED'
        raise policy.CheckError('scored.controls: ' + disposition +
                                '; required risk-specific baseline witnesses')
    reference = (profile.get('deployment') or {}).get('reuse_readiness')
    if reference is not None:
        missing = [key for key in ('campaign_root', 'section_manifest_sha256')
                   if not reference.get(key)]
        if missing:
            raise policy.CheckError('scored.readiness: recorded reuse attribution '
                                    'requires ' + str(missing))
        ready = Path(reference['campaign_root']) / 'sections' / 'agentic-readiness'
        if policy.file_sha(ready / 'manifest.json') != reference['section_manifest_sha256']:
            raise policy.CheckError('scored.readiness: recorded manifest identity mismatch')
    else:
        ready = _section_path(campaign, 'agentic-readiness')
    reporting.verify_manifest(ready)
    cfg = store.read_json(ready / 'run.json')
    if not policy.compatible_profiles(cfg['profile'], profile):
        raise policy.CheckError('scored.readiness: different profile')
    if cfg['methodology'] != SCIENTIFIC_METHODOLOGY:
        raise policy.CheckError('scored.readiness: checker/3 qualification required')
    _, units = store.inventory(ready)
    fixtures = store.read_json(ready / 'fixture.json')
    if cfg['agentic_config'].get('checker_version') != 3 or \
            fixtures.get('qualification', {}).get('checker_version') != 3:
        raise policy.CheckError('scored.readiness: checker/3 qualification required')
    row = policy.resolved_attempt(units.get('qualification', []))
    if row:
        _validate_attempt(cfg, fixtures, 'qualification', row)
    result = row or {}
    admitted = (result.get('interrupted') is None
                and result.get('task_class') == 'qualification'
                and result.get('outcome') == 'PASS'
                and result.get('evidence', {}).get('kind') == 'REAL_MODEL'
                and result.get('non_scored') is True
                and result.get('scored_sample') is False)
    if not admitted:
        raise policy.CheckError('scored.readiness: NOT_ELIGIBLE; qualification '
                                f"outcome {result.get('outcome')!r} "
                                f"(stop_reason {result.get('stop_reason')!r}) "
                                'does not admit scored readiness')
    baseline['readiness_manifest_sha256'] = reference['section_manifest_sha256'] \
        if reference is not None else policy.file_sha(ready / 'manifest.json')
    baseline['scored_readiness_admission'] = {
        'task_id': result.get('task_id'), 'admitted': True,
        'outcome': 'PASS', 'evidence_kind': 'REAL_MODEL',
        'reused_from': reference.get('campaign_root') if reference is not None else None}
    return baseline


def _identity(profile, section, config, fixtures, progression):
    return {'profile': profile, 'profile_revision': policy.digest(profile),
            'methodology': SCIENTIFIC_METHODOLOGY, 'section': section,
            'scored': True, 'agentic_config': config, 'unit_ids': list(fixtures),
            'fixture_sha256': policy.digest(fixtures), 'software': runner.software_identity(),
            'admission_version': policy.ADMISSION_VERSION,
            'progression': progression}


def plan(profile, section, config):
    policy.validate_profile(profile)
    if profile.get('evidence_kind') != 'REAL_MODEL':
        raise policy.CheckError('scored.evidence_kind: the scored route is REAL_MODEL only')
    if not authorized(profile):
        raise policy.CheckError('scored.authorization: campaign is NOT authorized for '
                                'authentic scored execution')
    tasks = config.get('tasks') or ()
    fixtures = _limits(config, section, tasks)
    checks = preflight.offline(profile)
    if config['adapter'] == 'native_tools' and \
            profile.get('capabilities', {}).get('native_tools') is not True:
        raise policy.CheckError('scored.adapter: INTEGRATION_BLOCKED native tools not qualified')
    progression = ({} if section == 'agentic-readiness'
                   else _readiness_gate(profile['campaign_root'], profile))
    if section == 'agentic-readiness':
        progression = _baseline(profile)
        progression['stage'] = 'pre-readiness baseline attribution'
    return {'section': section, 'methodology': SCIENTIFIC_METHODOLOGY,
            'evidence_kind': 'REAL_MODEL', 'scored': True,
            'profile_revision': policy.digest(profile),
            'unit_ids': list(fixtures), 'preflight': checks, 'progression': progression,
            'scientific_validation': 'PENDING', 'config': config,
            'accepted_standard': {
                'budget_version': m3.STANDARD_BUDGET_VERSION,
                'scientific_methodology': SCIENTIFIC_METHODOLOGY,
                'checker_version': 3,
                'campaign_authorization': activation_record(profile)}}


def run(profile, section, config):
    from . import agentic
    campaign = Path(profile['campaign_root'])
    target = _section_path(campaign, section)
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if (not policy.compatible_profiles(saved['profile'], profile)
                or saved['agentic_config'] != config):
            raise policy.CheckError('recovery.scored: changed finalized configuration')
        return status(campaign, section)
    planned = plan(profile, section, config)
    fixtures = _limits(config, section, config.get('tasks') or ())
    identity = _identity(profile, section, config, fixtures, planned['progression'])
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['agentic_config'] != config
                    or saved['fixture_sha256'] != identity['fixture_sha256']):
                raise policy.CheckError('recovery.scored: changed scientific configuration')
        else:
            for name, value in (('profile.json', profile), ('fixture.json', fixtures),
                                ('run.json', identity)):
                reporting.ensure_json(target / name, value)
        _, units = store.inventory(target)
        if not any(policy.unit_pending(rows) for rows in units.values()):
            return status(campaign, section)
        store.check_preparation(target)
        try:
            admission = preflight.online(profile)
        except policy.CheckError as exc:
            failure = dict(getattr(exc, 'evidence', {}))
            failure.update(ok=False, error=str(exc), profile_revision=identity['profile_revision'])
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
            for name, fixture in fixtures.items():
                while not stop and policy.unit_pending(store.attempts(target, name)):
                    path = store.new_attempt(target, name, preparing=True)
                    store.append_event(target, {'event': 'PREPARING', 'unit_id': name,
                                               'attempt_id': path.name, 'at': runner.now()})
                    limits = config['limits'][name]
                    store.put_json(path / 'request.json', {'fixture': fixture, 'limits': limits,
                                                          'adapter': config['adapter']})
                    store.put_json(path / 'conditions.json', {
                        'profile': profile, 'profile_revision': policy.digest(profile),
                        'evidence_kind': 'REAL_MODEL', 'request_limits': limits,
                        'preflight': admission, 'methodology': identity['methodology']})
                    exchanges = []
                    def exchange(body, remaining_wall_seconds):
                        request = {**body, 'model': profile['runtime']['serve']['model_id'],
                                   'stream': False, **policy.sampling_settings(profile),
                                   **profile['reasoning']['controls']}
                        index = len(exchanges) + 1
                        store.put_json(path / f'http-{index:04d}-request.json', request)
                        store.generation_intent(path, request)
                        observed = runner._http_exchange(profile, request,
                            min(remaining_wall_seconds, profile['budgets']['timeout_seconds']))
                        raw = observed.pop('raw')
                        store.put(path / f'http-{index:04d}-response.raw', raw)
                        store.put_json(path / f'http-{index:04d}-conditions.json', observed)
                        exchanges.append(raw)
                        return {**observed, 'raw': raw}
                    try:
                        result = agentic.execute(fixture, limits, config['adapter'], exchange,
                                                 path, stop_requested=lambda: stop)
                    except KeyboardInterrupt:
                        stop = True
                        break
                    if stop or result.get('interrupted'):
                        stop = True
                        break
                    store.put(path / 'response.raw', b'\n'.join(exchanges))
                    score = dict(result, unit_id=name, attempt_id=path.name,
                                 profile_revision=policy.digest(profile))
                    store.finalize_attempt(path, score, methodology=identity['methodology'])
                    store.append_event(target, {'event': 'PREPARATION_FAILED' if store.preparation_only(path) else 'FINALIZED',
                                               'unit_id': name, 'attempt_id': path.name, 'at': runner.now()})
                    if store.preparation_only(path):
                        stop = True
                        break
        finally:
            signal.signal(signal.SIGINT, previous)
            if stop:
                store.append_event(target, {'event': 'INTERRUPTED', 'at': runner.now()})
        return status(campaign, section)


def status(campaign, section):
    target = _section_path(campaign, section)
    if not (target / 'run.json').exists():
        return {'section': section, 'state': 'NOT_RUN', 'units': [], 'finalized': False,
                'scored': True}
    config, units = store.inventory(target)
    rows = []
    for name, attempts in units.items():
        resolved = policy.resolved_attempt(attempts)
        rows.append({'unit_id': name, 'attempts': len(attempts),
                     'resolved_attempt': resolved['attempt_id'] if resolved else None,
                     'outcome': resolved['outcome'] if resolved else 'NOT_RUN',
                     'reason': resolved.get('reason') if resolved else None,
                     'partial_progress': resolved.get('evaluation', {}).get('partial_progress') if resolved else None,
                     'pending': policy.unit_pending(attempts),
                     'checks': [
                         {key: check.get(key) for key in ('id', 'pass', 'detail')}
                         for check in (resolved or {}).get('evaluation', {}).get('checks', [])]})
    admissions = store.admission_records(target)
    blocked = bool(admissions) and admissions[-1].get('ok') is False
    return {'section': section, 'state': policy.section_state(units, blocked=blocked),
            'profile_id': config['profile']['profile_id'], 'scored': True,
            'evidence_kind': 'REAL_MODEL', 'methodology': SCIENTIFIC_METHODOLOGY,
            'units': rows,
            'preparation_failures': store.preparation_failures(target),
            'remaining_units': [r['unit_id'] for r in rows if r['pending']],
            'finalized': (target / 'manifest.json').exists()}


def resume(campaign, section, profile=None):
    config = store.read_json(_section_path(campaign, section) / 'run.json')
    if Path(config['profile']['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.scored: wrong campaign')
    if config['methodology'] != SCIENTIFIC_METHODOLOGY:
        raise policy.CheckError('recovery.scored: methodology mismatch')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.scored: wrong campaign')
    return run(profile, section, config['agentic_config'])


def _validate_attempt(config, fixtures, name, row):
    from . import agentic
    path = Path(row['path'])
    conditions = store.read_json(path / 'conditions.json')
    profile = policy.recorded_profile(config, conditions)
    policy.validate_echo(profile, conditions['preflight']['echo'])
    m3.validate_wire(path, profile, fixtures[name],
        config['agentic_config']['limits'][name], config['agentic_config']['adapter'])
    replayed = agentic.replay(path, fixtures[name],
        config['agentic_config']['limits'][name], config['agentic_config']['adapter'])
    replayed.pop('replay', None)
    for key, value in replayed.items():
        if row.get(key) != value:
            raise policy.CheckError(f'validation.scored.{name}.{key}: replay mismatch')


def report_section(campaign, section):
    from . import agentic
    target = _section_path(campaign, section)
    with store.locked(campaign):
        if (target / 'manifest.json').exists():
            reporting.verify_manifest(target)
            return {'disposition': 'PASS', 'report': str(target / 'SECTION-REPORT.md'),
                    'already_finalized': True}
        config, units = store.inventory(target)
        fixtures = store.read_json(target / 'fixture.json')
        if not authorized(config['profile']):
            raise policy.CheckError('scored.authorization: campaign gate is inactive; '
                                    'finalization requires the recorded campaign activation')
        if section == 'agentic':
            progression = _readiness_gate(campaign, config['profile'])
        else:
            progression = _baseline(config['profile'])
        summary = status(campaign, section)
        if summary['remaining_units']:
            raise policy.CheckError('finalization.scored: pending work; resume first')
        for name, attempts in units.items():
            for row in attempts:
                if not row.get('finalized'):
                    continue
                _validate_attempt(config, fixtures, name, row)
        reporting.ensure_json(target / 'validation.json', {
            'disposition': 'PASS', 'methodology': SCIENTIFIC_METHODOLOGY,
            'evidence_kind': 'REAL_MODEL', 'scored': True,
            'scientific_validation': 'EXECUTED'})
        reporting.ensure_json(target / 'summary.json', summary)
        text = (f'# WELP — scored {section} (agentic/3)\n\n'
                'Authentic REAL_MODEL scored execution under the campaign-gated '
                'route; independent offline reconstruction: PASS.\n\n'
                f'Execution: {summary["state"]}.\n\n'
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
