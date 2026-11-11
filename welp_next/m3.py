"""Offline M3 section integration; accepted Model methodology is unchanged.

This module owns Agentic section progression/evidence, not scientific capability
thresholds (advancement.decide) or task execution/scoring (agentic).
"""
import json
from pathlib import Path
import signal

from . import policy, preflight, reporting, runner, store

SECTIONS = ('agentic-readiness', 'agentic')
METHODOLOGY = policy.METHODOLOGY_AGENTIC_PRELIVE
PROPOSED_METHODOLOGY = policy.METHODOLOGY_AGENTIC_PROPOSED
TASKS = {'agentic-readiness': ('qualification',),
         'agentic': ('repository', 'system', 'research')}

# Operator-accepted scientific definitions; authentic execution remains inactive.
# Historical offline configurations retain their explicit original limits.
STANDARD_BUDGET_VERSION = 'agentic-budget/1'
STANDARD_SCIENTIFIC_METHODOLOGY = 'agentic/3'
STANDARD_VECTORS = {
    'qualification': (16, 8192, 3072, 300, 15),
    'repository': (40, 32768, 4096, 1200, 45),
    'system': (36, 16384, 3072, 900, 60),
    'research': (32, 24576, 4096, 900, 20),
}


def standard_config(section):
    """Software exercise of accepted limits, never scientific execution authority."""
    from . import agentic
    if section not in TASKS:
        raise policy.CheckError('agentic.section: unsupported section')
    return {
        'evidence_kind': 'SOFTWARE_TEST', 'adapter': 'native_tools',
        'checker_version': 3, 'budget_version': STANDARD_BUDGET_VERSION,
        'limits': {
            name: dict(zip(agentic.LIMIT_KEYS, STANDARD_VECTORS[name]),
                       evidence_kind='SOFTWARE_TEST',
                       source='agentic-budget/1; operator acceptance 2026-10-25; SOFTWARE_TEST exercise only')
            for name in TASKS[section]},
    }


def inventory(campaign, section):
    """Fixed section identities are authority, never a mutable unit list."""
    target = section_path(campaign, section)
    config = store.read_json(target / 'run.json')
    fixtures = store.read_json(target / 'fixture.json')
    profile = store.read_json(target / 'profile.json')
    if (config.get('unit_ids') != list(TASKS[section])
            or set(fixtures) != set(TASKS[section])
            or config.get('section') != section
            or config.get('methodology') not in (METHODOLOGY, PROPOSED_METHODOLOGY, policy.METHODOLOGY_AGENTIC)):
        raise policy.CheckError('validation.agentic.inventory: fixed task identities changed')
    if config.get('profile') != profile or config.get('profile_revision') != policy.digest(profile):
        raise policy.CheckError('validation.agentic.profile: changed snapshot')
    if (policy.digest(fixtures) != config.get('fixture_sha256')
            or fixtures != _config(config['agentic_config'], section,
                version={policy.METHODOLOGY_AGENTIC: 1, METHODOLOGY: 2, PROPOSED_METHODOLOGY: 3}[config['methodology']])):
        raise policy.CheckError('validation.agentic.fixture: changed fixed fixture')
    return store.inventory(target)


def section_path(campaign, section):
    if section not in SECTIONS:
        raise policy.CheckError('agentic.section: unsupported section')
    return Path(campaign) / 'sections' / section


def baseline_evidence(campaign, profile=None):
    section = store.section_path(campaign)
    config, model = reporting.finalized_model_evidence(section)
    if profile is not None and not policy.compatible_profiles(config['profile'], profile):
        raise policy.CheckError('progression.profile: baseline uses a different qualified profile')
    summary = runner.status(campaign)
    if summary['state'] not in ('COMPLETED', 'COMPLETED_PARTIAL'):
        raise policy.CheckError('progression.baseline: baseline is not finalized')
    return {'profile_id': config['profile']['profile_id'],
            'profile_revision': config['profile_revision'],
            'evidence_kind': config['profile']['evidence_kind'],
            'manifest_sha256': policy.file_sha(section / 'manifest.json'),
            'methodology': config['profile']['framework']['methodology'],
            'fixture_sha256': config['fixture_sha256'],
            'task_categories': {task['id']: task['category'] for task in
                store.read_json(section / 'fixture.json')['tasks']},
            'effective_scores': model['effective_scores'],
            'coverage': model['coverage']}


def decisions(campaign, inputs=None, *, persist=False):
    from . import advancement
    if inputs is None:
        inputs = {}
    allowed = {'rule_version', 'priorities', 'remaining_budget', 'exploratory'}
    if not isinstance(inputs, dict) or set(inputs) - allowed:
        raise policy.CheckError('advancement.inputs: caller rules, acceptance and prerequisites are not authority')
    evidence = baseline_evidence(campaign)
    value = {'methodology': advancement.WITNESS_VERSION, 'baseline': evidence,
             'inputs': inputs,
             'decisions': advancement.bound_decisions(evidence, **inputs)}
    value['decision_sha256'] = policy.digest(value)
    if persist:
        with store.locked(campaign):
            path = Path(campaign) / 'decisions' / (value['decision_sha256'] + '.json')
            reporting.ensure_json(path, value)
        value = dict(value, evidence_path=str(path))
    return value


def _methodology(config):
    version = config.get('checker_version', 2)
    if type(version) is not int or version not in (2, 3):
        raise policy.CheckError('agentic.checker: only checker/2 or checker/3 software preparation')
    return PROPOSED_METHODOLOGY if version == 3 else METHODOLOGY


def _config(config, section, *, version=None):
    from . import agentic
    if not isinstance(config, dict) or config.get('evidence_kind') != 'SOFTWARE_TEST':
        raise policy.CheckError('agentic.calibration: authentic scored execution inactive; qualified context/profile and separate scored authorization required')
    if config.get('adapter') not in ('text_json', 'native_tools'):
        raise policy.CheckError('agentic.adapter: INTEGRATION_BLOCKED unsupported interface')
    selected = config.get('checker_version', version if version is not None else 2)
    if type(selected) is not int or selected not in (1, 2, 3) or (version is not None and selected != version):
        raise policy.CheckError('agentic.checker: incompatible recorded checker version')
    limits = config.get('limits')
    if not isinstance(limits, dict):
        raise policy.CheckError('agentic.limits: explicit per-task limits required; no universal turn default')
    if 'budget_version' in config:
        expected = standard_config(section)
        if (config['budget_version'] != STANDARD_BUDGET_VERSION or selected != 3
                or config['adapter'] != expected['adapter'] or limits != expected['limits']):
            raise policy.CheckError('agentic.standard: accepted task limits/checker/interface cannot be substituted')
    fixtures = {}
    for name in TASKS[section]:
        if name not in limits:
            raise policy.CheckError(f'agentic.limits.{name}: explicit SOFTWARE_TEST limits required')
        agentic.validate_limits(limits[name])
        fixtures[name] = agentic.load_fixture(name, version=selected)
    return fixtures


def _progression(campaign, profile, section, methodology=METHODOLOGY):
    baseline = baseline_evidence(campaign, profile)
    if section == 'agentic':
        ready = section_path(campaign, 'agentic-readiness')
        from . import advancement
        controls = advancement.witness_resolution(baseline['effective_scores'],
            tuple((uid,) for uid in advancement.AGENTIC_CONTROLS))
        if controls is not True:
            disposition = 'NOT_ELIGIBLE' if controls is False else 'DEFERRED'
            raise policy.CheckError('progression.controls: ' + disposition +
                                    '; required risk-specific baseline witnesses')
        reporting.verify_manifest(ready)
        cfg = store.read_json(ready / 'run.json')
        if not policy.compatible_profiles(cfg['profile'], profile):
            raise policy.CheckError('progression.readiness: different profile')
        if cfg['methodology'] != methodology:
            raise policy.CheckError('progression.readiness: matching prospective checker qualification required')
        from . import agentic
        _, units = inventory(campaign, 'agentic-readiness')
        fixtures = store.read_json(ready / 'fixture.json')
        row = policy.resolved_attempt(units.get('qualification', []))
        if row:
            _validate_attempt(cfg, fixtures, 'qualification', row)
        admission = agentic.readiness_admission(row or {})
        if not admission['admitted']:
            raise policy.CheckError('progression.readiness: NOT_ELIGIBLE; ' + admission['reason'])
        baseline['readiness_manifest_sha256'] = policy.file_sha(ready / 'manifest.json')
        baseline['admission'] = 'SOFTWARE_TEST_ONLY; not scientific Agentic qualification'
    return baseline


def plan(profile, section, config):
    policy.validate_profile(profile)
    if profile['evidence_kind'] != 'SOFTWARE_TEST':
        raise policy.CheckError('agentic.evidence_kind: offline development permits SOFTWARE_TEST only')
    fixtures = _config(config, section)
    checks = preflight.offline(profile)
    methodology = _methodology(config)
    progression = _progression(profile['campaign_root'], profile, section, methodology)
    if config['adapter'] == 'native_tools' and profile.get('capabilities', {}).get('native_tools') is not True:
        raise policy.CheckError('agentic.adapter: INTEGRATION_BLOCKED native tools not qualified')
    if section == 'agentic':
        ready = store.read_json(section_path(profile['campaign_root'], 'agentic-readiness') / 'run.json')
        if ready['agentic_config']['adapter'] != config['adapter']:
            raise policy.CheckError('progression.readiness: adapter differs from qualification')
    return {'section': section, 'methodology': methodology,
            'evidence_kind': 'SOFTWARE_TEST', 'profile_revision': policy.digest(profile),
            'unit_ids': list(fixtures), 'preflight': checks, 'progression': progression,
            'scientific_validation': 'NOT_TESTED', 'config': config,
            **({'accepted_standard': {
                'budget_version': STANDARD_BUDGET_VERSION,
                'scientific_methodology': STANDARD_SCIENTIFIC_METHODOLOGY,
                'checker_version': 3,
                'authentic_execution': 'INACTIVE; qualified context/profile and separate scored authorization required',
            }} if 'budget_version' in config else {})}


def _identity(profile, section, config, fixtures, progression):
    return {'profile': profile, 'profile_revision': policy.digest(profile),
            'methodology': _methodology(config), 'section': section,
            'agentic_config': config, 'unit_ids': list(fixtures),
            'fixture_sha256': policy.digest(fixtures), 'software': runner.software_identity(),
            'admission_version': policy.ADMISSION_VERSION,
            'progression': progression}


def run(profile, section, config):
    from . import agentic
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign, section)
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if not policy.compatible_profiles(saved['profile'], profile) or saved['agentic_config'] != config:
            raise policy.CheckError('recovery.agentic: changed finalized configuration')
        return status(campaign, section)
    planned = plan(profile, section, config)
    fixtures = _config(config, section)
    identity = _identity(profile, section, config, fixtures, planned['progression'])
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['agentic_config'] != config or saved['fixture_sha256'] != identity['fixture_sha256']):
                raise policy.CheckError('recovery.agentic: changed scientific configuration')
        else:
            for name, value in (('profile.json', profile), ('fixture.json', fixtures), ('run.json', identity)):
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
                        'evidence_kind': 'SOFTWARE_TEST', 'request_limits': limits,
                        'preflight': admission, 'methodology': identity['methodology']})
                    exchanges = []
                    def exchange(body, remaining_wall_seconds):
                        # Core owns messages/tools and per-turn budget. Profile owns
                        # serving identity, sampling and qualified reasoning controls.
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
                        break  # in-flight attempt retained, never committed as model evidence
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
    target = section_path(campaign, section)
    if not (target / 'run.json').exists():
        return {'section': section, 'state': 'NOT_RUN', 'units': [], 'finalized': False}
    config, units = inventory(campaign, section)
    rows = []
    for name, attempts in units.items():
        resolved = policy.resolved_attempt(attempts)
        rows.append({'unit_id': name, 'attempts': len(attempts),
                     'resolved_attempt': resolved['attempt_id'] if resolved else None,
                     'outcome': resolved['outcome'] if resolved else 'NOT_RUN',
                     'reason': resolved.get('reason') if resolved else None,
                     'partial_progress': resolved.get('evaluation', {}).get('partial_progress') if resolved else None,
                     'pending': policy.unit_pending(attempts)})
        if config['methodology'] == PROPOSED_METHODOLOGY:
            # Expose the existing independently observed requirements, not a
            # second score or a reinterpretation of historical summaries.
            rows[-1]['checks'] = [
                {key: check.get(key) for key in ('id', 'pass', 'detail')}
                for check in (resolved or {}).get('evaluation', {}).get('checks', [])]
    admissions = store.admission_records(target)
    blocked = bool(admissions) and admissions[-1].get('ok') is False
    return {'section': section, 'state': policy.section_state(units, blocked=blocked),
            'profile_id': config['profile']['profile_id'], 'evidence_kind': 'SOFTWARE_TEST',
            'scientific_validation': 'NOT_TESTED', 'units': rows,
            'preparation_failures': store.preparation_failures(target),
            'remaining_units': [r['unit_id'] for r in rows if r['pending']],
            'finalized': (target / 'manifest.json').exists()}


def resume(campaign, section, profile=None):
    config = store.read_json(section_path(campaign, section) / 'run.json')
    if Path(config['profile']['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.campaign_root: wrong campaign')
    if config['methodology'] not in (METHODOLOGY, PROPOSED_METHODOLOGY):
        raise policy.CheckError('recovery.methodology: historical Agentic execution is frozen')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.campaign_root: wrong campaign')
    return run(profile, section, config['agentic_config'])


def validate_wire(path, profile, fixture, limits, adapter):
    """Bind core reconstruction to the actual qualified HTTP requests."""
    expected = {'fixture': fixture, 'limits': limits, 'adapter': adapter}
    if store.read_json(path / 'request.json') != expected:
        raise policy.CheckError('validation.agentic.request: changed fixed inputs')
    conditions = store.read_json(path / 'conditions.json')
    if (conditions.get('profile_revision') != policy.digest(profile)
            or conditions.get('evidence_kind') != profile['evidence_kind']
            or conditions.get('request_limits') != limits):
        raise policy.CheckError('validation.agentic.conditions: changed attribution')
    core = sorted(path.glob('agentic-http-*-request.json'))
    wire = sorted(path.glob('http-*-request.json'))
    if len(core) != len(wire):
        raise policy.CheckError('validation.agentic.http: exchange count mismatch')
    originals = []
    for index, core_path in enumerate(core, 1):
        request = store.read_json(core_path)
        expected = {**request, 'model': profile['runtime']['serve']['model_id'],
                    'stream': False, **policy.sampling_settings(profile),
                    **profile['reasoning']['controls']}
        if store.read_json(path / f'http-{index:04d}-request.json') != expected:
            raise policy.CheckError('validation.agentic.http: qualified request mismatch')
        raw = (path / f'http-{index:04d}-response.raw').read_bytes()
        if (path / f'agentic-http-{index:04d}-response.raw').read_bytes() != raw:
            raise policy.CheckError('validation.agentic.http: original response mismatch')
        originals.append(raw)
    if (path / 'response.raw').read_bytes() != b'\n'.join(originals):
        raise policy.CheckError('validation.agentic.http: original response aggregate mismatch')


def _validate_attempt(config, fixtures, name, row):
    from . import agentic
    path = Path(row['path'])
    conditions = store.read_json(path / 'conditions.json')
    profile = policy.recorded_profile(config, conditions)
    policy.validate_echo(profile, conditions['preflight']['echo'])
    validate_wire(path, profile, fixtures[name],
        config['agentic_config']['limits'][name], config['agentic_config']['adapter'])
    replayed = agentic.replay(path, fixtures[name],
        config['agentic_config']['limits'][name], config['agentic_config']['adapter'])
    replayed.pop('replay', None)
    for key, value in replayed.items():
        if row.get(key) != value:
            raise policy.CheckError(f'validation.agentic.{name}.{key}: replay mismatch')


def report_section(campaign, section):
    from . import agentic
    target = section_path(campaign, section)
    with store.locked(campaign):
        if (target / 'manifest.json').exists():
            reporting.verify_manifest(target)
            return {'disposition': 'PASS', 'report': str(target / 'SECTION-REPORT.md'),
                    'already_finalized': True}
        config, units = inventory(campaign, section)
        fixtures = store.read_json(target / 'fixture.json')
        _progression(campaign, config['profile'], section, config['methodology'])
        summary = status(campaign, section)
        if summary['remaining_units']:
            raise policy.CheckError('finalization.agentic: pending work; resume first')
        for name, attempts in units.items():
            for row in attempts:
                if not row.get('finalized'):
                    continue
                _validate_attempt(config, fixtures, name, row)
        reporting.ensure_json(target / 'validation.json', {
            'disposition': 'PASS', 'methodology': config['methodology'],
            'evidence_kind': 'SOFTWARE_TEST', 'scientific_validation': 'NOT_TESTED'})
        reporting.ensure_json(target / 'summary.json', summary)
        text = (f'# WELP — {section}\n\nSOFTWARE_TEST only; synthetic responses, not model science.\n\n'
                'Readiness and full Agentic are independently finalized; neither changes Model findings.\n\n'
                'Qualification admission and all limits here are software-test inputs, not scientific thresholds.\n\n'
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
                'state': summary['state'], 'scientific_validation': 'NOT_TESTED'}


def finalized_sections(campaign):
    result = {}
    for section in SECTIONS:
        target = section_path(campaign, section)
        if (target / 'manifest.json').exists():
            reporting.verify_manifest(target)
            result[section] = status(campaign, section)
    return result
