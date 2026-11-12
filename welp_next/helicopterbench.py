"""HelicopterBench section — one-shot game development benchmark.

Purpose (SPEC §4.1.1/§4.11): one frozen prompt asks the model for a complete,
immediately playable HTML5 helicopter game in a single standalone file. The
first completed submission is the submission: no feedback, no repair, no
retries, no best-of selection. The submitted artifact is verified by EXECUTING
it inside a disposable isolated browser namespace and scoring the frozen
mechanical rubric from observed behavior. The frozen accepted default is
methodology helicopterbench/2 (90-point rubric, final score normalized from
the exact mechanical total); the owner-approved prospective methodology
helicopterbench/3 (selected explicitly via config/CLI) re-weights the SAME 14
behavioral checks into a NATIVE 100-point rubric (five categories of exactly
20; no normalization) and adds an independent, attributed human playtesting
review as a SEPARATE acceptance channel (``welp_next.heli_review``): it binds
the finalized artifact and automated evidence by SHA-256, never enters the
automated score and never alters finalized evidence. Resource exhaustion
takes the accepted budget disposition and is never classified as a completed
incorrect game.

The section reuses the shared runner (durable attempts, budget policy,
generation intents), evidence store, manifests and offline reporting. There
is no capability-witness gate: HelicopterBench is an independently selectable
specialist section and no accepted predictive witness exists for complete
game construction — one is not invented. Authentic (REAL_MODEL) dispatch
additionally requires a recorded method acceptance in the deployment profile
(the accepted budget numbers and the selected methodology's scientific
acceptance); SOFTWARE_TEST validation is exempt.

The submitted game is untrusted: verification executes it ONLY inside the
browser sandbox (`welp_next.browser_harness`), never on the host.
"""
import json
from pathlib import Path
import signal

from . import coding, policy, preflight, reporting, runner, store
from . import browser_harness as verify
from .scorers import helicopterbench as heli

SECTION = 'helicopterbench'
# Frozen accepted default: methodology helicopterbench/2 with the frozen
# v1.0.0 fixture and the frozen 90-point→normalized scorer. The prospective
# methodology helicopterbench/3 (true native 100-point rubric + independent
# human playtesting) is selected explicitly and prospectively; original /1
# and /2 evidence and reconstruction are unaffected.
DEFAULT_METHODOLOGY = heli.METHODOLOGY_VERSION
FIXTURE_RELPATH = 'fixtures/helicopterbench/advanced-tasks.json'
METHODOLOGIES = {
    heli.METHODOLOGY_VERSION: {
        'fixture': FIXTURE_RELPATH, 'fixture_version': '1.0.0'},
    'helicopterbench/3': {
        'fixture': 'fixtures/helicopterbench/v3-tasks.json',
        'fixture_version': '3.0.0'},
}
_ALLOWED_CONFIG_KEYS = frozenset({'methodology'})

_fail = coding._fail


def _generation_consumed(target, uid):
    """Methodology helicopterbench/3 grants ONE generation opportunity per
    unit: any durable generation intent (written before dispatch, in any
    attempt) consumes it. Unsent preparation never consumes it and stays
    retryable under the existing rules; /1 and /2 keep the accepted
    invalid-retry behavior unchanged."""
    evidence = Path(target) / 'evidence' / uid
    return evidence.exists() and any(evidence.glob('*/generation-*-intent.json'))


def _scorer(methodology):
    """Version-specific scorer module: the frozen /2 scorer is untouched; /3
    is a separate module with the native 100-point rubric."""
    if methodology == heli.METHODOLOGY_VERSION:
        return heli
    if methodology == 'helicopterbench/3':
        from .scorers import helicopterbench_v3 as heli_v3
        return heli_v3
    _fail('helicopterbench.methodology',
          f'unsupported methodology {methodology!r}')


def _config(config):
    """HelicopterBench caller keys: only the prospective methodology
    selection; tasks, prompt, budgets and the extraction contract stay
    frozen section identities."""
    if config is None:
        return {'methodology': DEFAULT_METHODOLOGY}
    if not isinstance(config, dict) or set(config) - _ALLOWED_CONFIG_KEYS:
        _fail('helicopterbench.config',
              'only {"methodology": "helicopterbench/3"} is caller-'
              'selectable; tasks, budgets and scoring are frozen section '
              'identities')
    return {'methodology': config.get('methodology') or DEFAULT_METHODOLOGY}


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def load_fixture(methodology=None):
    """Version-specific frozen fixture. The default (None) is the frozen
    accepted /2 fixture; helicopterbench/3 selects fixtures/helicopterbench/
    v3-tasks.json (same verbatim task, same extraction contract)."""
    methodology = methodology or DEFAULT_METHODOLOGY
    spec = METHODOLOGIES.get(methodology)
    if spec is None and methodology == 'helicopterbench/1':
        # Preserved /1 campaigns reconstruct offline against the UNCHANGED
        # historic fixture. This never enables /1 dispatch or rescore
        # (plan/_scorer refuse /1; the objective reconstruction only runs
        # for /2 and /3).
        spec = METHODOLOGIES[DEFAULT_METHODOLOGY]
    if spec is None:
        _fail('helicopterbench.methodology',
              f'unsupported methodology {methodology!r}')
    fixture = json.loads((policy.PROJECT_ROOT / spec['fixture']).read_text())
    task = fixture.get('task')
    if fixture.get('version') != spec['fixture_version'] or not task:
        _fail('helicopterbench.fixture', 'unsupported fixture')
    if methodology == 'helicopterbench/3' \
            and fixture.get('methodology') != methodology:
        _fail('helicopterbench.fixture', 'fixture/methodology mismatch')
    task = {**task,
            'messages': [{'role': 'user', 'content': task['user_task']}]}
    return fixture, {'helicopterbench-01': task}


def plan(profile, config=None):
    policy.validate_profile(profile)
    config = _config(config)
    methodology = config['methodology']
    _scorer(methodology)  # the methodology must be wired before planning
    fixture, tasks = load_fixture(methodology)
    # Authorization gate before environment checks: REAL_MODEL dispatch
    # requires the recorded method acceptance for the selected methodology;
    # SOFTWARE_TEST is exempt.
    if profile.get('evidence_kind') == 'REAL_MODEL' and not (
            profile.get('deployment') or {}).get('method_acceptance'):
        _fail('helicopterbench.acceptance',
              'REAL_MODEL dispatch requires the recorded scientific-method '
              f'acceptance: the {methodology} methodology must be '
              'accepted before real-model dispatch')
    checks = preflight.offline(profile)
    return {'section': SECTION, 'methodology': methodology,
            'evidence_kind': profile['evidence_kind'],
            'profile_revision': policy.digest(profile),
            'unit_ids': list(tasks), 'fixture_sha256': policy.digest(fixture),
            'gate': {'decision': 'ADVANCE', 'reason':
                     'independently selectable specialist section; no '
                     'capability-witness gate exists for one-shot game '
                     'construction and none is invented (SPEC §4.11)'},
            'preflight': checks, 'config': config}


def _identity(profile, fixture, tasks, planned):
    return {'profile': profile, 'profile_revision': policy.digest(profile),
            'methodology': planned['methodology'], 'section': SECTION,
            'unit_ids': list(tasks), 'fixture_sha256': policy.digest(fixture),
            'software': runner.software_identity(),
            'admission_version': policy.ADMISSION_VERSION,
            'gate': planned['gate']}


def run(profile, config=None):
    campaign = Path(profile['campaign_root'])
    target = section_path(campaign)
    config = _config(config)
    fixture, tasks = load_fixture(config['methodology'])
    if (target / 'manifest.json').exists():
        reporting.verify_manifest(target)
        saved = store.read_json(target / 'run.json')
        if not policy.compatible_profiles(saved['profile'], profile):
            raise policy.CheckError('recovery.helicopterbench: changed finalized configuration')
        if saved.get('methodology') != config['methodology']:
            raise policy.CheckError('recovery.helicopterbench: changed finalized methodology')
        return status(campaign)
    planned = plan(profile, config)
    identity = _identity(profile, fixture, tasks, planned)
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['fixture_sha256'] != identity['fixture_sha256']
                    or saved.get('methodology') != identity['methodology']):
                raise policy.CheckError('recovery.helicopterbench: changed scientific configuration')
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
                while (not stop
                       and not (identity['methodology'] == 'helicopterbench/3'
                                and _generation_consumed(target, uid))
                       and policy.unit_pending(store.attempts(target, uid))):
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
                    if identity['methodology'] == 'helicopterbench/3' \
                            and _generation_consumed(target, uid):
                        # The durable generation intent exists: the single
                        # generation opportunity of methodology /3 is spent
                        # (a failed transport exchange after the intent is
                        # never issued twice by this section).
                        store.append_event(target, {
                            'event': 'GENERATION_CONSUMED', 'unit_id': uid,
                            'attempt_id': path.name, 'at': runner.now()})
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
    summary = {'section': SECTION, 'state': policy.section_state(units, blocked=blocked),
               'profile_id': config['profile']['profile_id'],
               'evidence_kind': config['profile']['evidence_kind'],
               'methodology': config['methodology'], 'units': rows,
               'preparation_failures': store.preparation_failures(target),
               'remaining_units': [r['unit_id'] for r in rows if r['pending']],
               'finalized': (target / 'manifest.json').exists()}
    if config['methodology'] == 'helicopterbench/3':
        # Exact v3 human-playtesting reconciliation gate (separate sidecar;
        # the automated record is never altered by it).
        from . import heli_review
        summary['human_review'] = heli_review.status(campaign)
    return summary


def resume(campaign, profile=None, config=None):
    run_config = store.read_json(section_path(campaign) / 'run.json')
    if Path(run_config['profile']['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.helicopterbench: wrong campaign')
    if run_config['methodology'] not in METHODOLOGIES:
        raise policy.CheckError('recovery.helicopterbench: methodology mismatch')
    if config is None:
        # No explicit selection: reuse the FROZEN run methodology so an
        # operator never has to reselect the score method to resume; there
        # is no silent migration. /1 /2 behavior is unchanged.
        selection = {'methodology': run_config['methodology']}
    else:
        selection = _config(config)
        if selection['methodology'] != run_config['methodology']:
            raise policy.CheckError(
                'recovery.helicopterbench: methodology mismatch')
    profile = profile or run_config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.helicopterbench: wrong campaign')
    return run(profile, selection)


def report_section(campaign, *, browser_binary=None, work_root=None,
                   verification_timeout=150.0):
    target = section_path(campaign)
    with store.locked(campaign):
        if (target / 'manifest.json').exists():
            reporting.verify_manifest(target)
            return {'disposition': 'PASS', 'report': str(target / 'SECTION-REPORT.md'),
                    'already_finalized': True}
        config, units = store.inventory(target)
        methodology = config['methodology']
        scorer = _scorer(methodology)
        fixture, _tasks = load_fixture(methodology)
        policy.digest(fixture)  # the pinned fixture must stay loadable
        profile = config['profile']
        plan(profile, {'methodology': methodology})
        summary = status(campaign)
        if summary['remaining_units']:
            raise policy.CheckError('finalization.helicopterbench: pending work; resume first')
        attempt_rows = next(iter(units.values()))
        if methodology == 'helicopterbench/3':
            # /3 resolves the attempt explicitly (one-generation rule).
            resolved = policy.resolved_attempt(attempt_rows)
            if resolved is None:
                raise policy.CheckError(
                    'finalization.helicopterbench: no resolved attempt')
        else:
            resolved = attempt_rows[0]
        path = Path(resolved['path'])
        envelope = json.loads((path / 'response.raw').read_bytes())
        content = ((envelope.get('choices') or [{}])[0].get('message') or {}).get('content')
        artifact, decision = scorer.extract_artifact(content)
        # Only a valid COMPLETED submission may be gameplay-scored. A
        # budget-limited, empty or otherwise non-completed reply is never a
        # submission: extractable bytes inside a truncated reply (e.g. a
        # fenced block cut off by finish=length) are recorded as evidence
        # but are never verified, never scored, never bound as a game.
        gameplay_scoreable = (methodology != 'helicopterbench/3'
                              or resolved['outcome'] == 'PASS')
        extraction = {'attempt_id': resolved['attempt_id'], 'decision': decision,
                      'artifact_sha256': scorer.sha256_hex(artifact) if artifact else None,
                      'artifact_bytes': len(artifact) if artifact else 0,
                      'generation_outcome': resolved['outcome'],
                      'gameplay_scored': False}
        verification = {'verdict': 'NO_ARTIFACT',
                        'note': 'no extractable artifact; browser verification not run'}
        rubric = {'mechanical_points': None, 'mechanical_max': scorer.MECHANICAL_MAX,
                  'final_score': None, 'class': 'NONFUNCTIONAL',
                  'note': 'nothing submitted to verify'}
        if artifact is not None and gameplay_scoreable:
            (target / 'submission.html').write_bytes(artifact)
            verification_root = work_root or (policy.PROJECT_ROOT / 'tmp'
                                              / 'helicopterbench-verification')
            verification_root.mkdir(parents=True, exist_ok=True)
            verification = verify.verify_game(
                artifact, browser_binary=browser_binary or verify.find_browser(),
                work_root=verification_root,
                timeout_seconds=verification_timeout)
            verification['artifact_sha256'] = extraction['artifact_sha256']
            rubric = scorer.rubric_score(verification)
            extraction['gameplay_scored'] = True
        elif artifact is not None:
            verification = {'verdict': 'NOT_A_COMPLETED_SUBMISSION',
                            'generation_outcome': resolved['outcome'],
                            'artifact_sha256': extraction['artifact_sha256'],
                            'note': 'extractable bytes were never a completed '
                                    'submission; never gameplay-scored '
                                    '(methodology /3 one-generation rule)'}
            rubric = {'mechanical_points': None, 'mechanical_max': scorer.MECHANICAL_MAX,
                      'final_score': None, 'class': 'NONFUNCTIONAL',
                      'note': 'no valid completed submission; nothing '
                              'gameplay-scored'}
        reporting.ensure_json(target / 'extraction.json', extraction)
        rubric_class = rubric.get('class')
        reporting.ensure_json(target / 'heli-verification.json', verification)
        final_score = rubric.get('final_score')
        score_record = {
            # Official WELP score: the objective result of the exact
            # mechanical total under the section methodology. Raw mechanical
            # points and category evidence stay visible.
            'score': final_score,
            'final_score': final_score,
            'methodology': methodology,
            'mechanical_points': rubric.get('mechanical_points'),
            'mechanical_max': rubric.get('mechanical_max', scorer.MECHANICAL_MAX),
            'class': rubric_class,
            'categories': rubric.get('categories'),
            'generation_outcome': resolved['outcome'],
            'generation_reason': resolved.get('reason')}
        if methodology == 'helicopterbench/3':
            # Human playtesting is a separate acceptance channel tracked in
            # the campaign human-review sidecar; it never alters this record.
            score_record['human_review_required'] = True
        reporting.ensure_json(target / 'heli-score.json', score_record)
        summary['verification_class'] = rubric_class
        summary['mechanical_points'] = rubric.get('mechanical_points')
        summary['final_score'] = final_score
        text = ('# WELP — HelicopterBench\n\n'
                'One-shot artifact benchmark (methodology ' + methodology +
                '): the first completed submission is '
                'the submission. Behavior is verified by executing the artifact '
                'inside an isolated browser namespace; the mechanical rubric '
                'scores observed behavior, never source code. ')
        if methodology == 'helicopterbench/3':
            text += ('The rubric is natively 100-point (no normalization); the '
                     'final score is the exact earned mechanical total. An '
                     'independent, attributed human playtesting review is '
                     'recorded separately in the campaign human-review '
                     'sidecar, binds these exact evidence files by SHA-256 '
                     'and never alters this automated record.\n\n')
        else:
            text += ('The final score '
                     'is the objective normalized 100-point result of the exact '
                     'mechanical total; no manual visual review is required. '
                     'Resource exhaustion is never a completed incorrect game.\n\n')
        text += ('Generation: ' + resolved['outcome'] +
                 (f" ({resolved.get('reason')})" if resolved.get('reason') else '') + '. '
                 f'Verification class: {rubric_class}. '
                 f"Final score: {final_score if final_score is not None else 'none'}/100 "
                 f"(mechanical {rubric.get('mechanical_points')} / "
                 f"{rubric.get('mechanical_max', scorer.MECHANICAL_MAX)}).\n\n"
                 '```json\n' + json.dumps(summary, indent=2, sort_keys=True) + '\n```\n')
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
                'state': summary['state'], 'verification_class': rubric_class,
                'mechanical_points': rubric.get('mechanical_points'),
                'final_score': final_score}
