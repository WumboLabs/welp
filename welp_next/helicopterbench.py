"""HelicopterBench section — one-shot game development benchmark.

Purpose (SPEC §4.1.1/§4.11): one frozen prompt asks the model for a complete,
immediately playable HTML5 helicopter game in a single standalone file. The
first completed submission is the submission: no feedback, no repair, no
retries, no best-of selection. The submitted artifact is verified by EXECUTING
it inside a disposable isolated browser namespace and scoring the frozen
mechanical rubric (90 points) from observed behavior; the final score is the
objective normalized 100-point result of the exact mechanical total
(``mechanical_points / 90 * 100``, one decimal) — no manual visual review
step exists (methodology helicopterbench/2; the retired 10-point review-only
visual category of methodology /1 remains a preserved historical method).
Resource exhaustion takes the accepted budget disposition and is
never classified as a completed incorrect game.

The section reuses the shared runner (durable attempts, budget policy,
generation intents), evidence store, manifests and offline reporting. There
is no capability-witness gate: HelicopterBench is an independently selectable
specialist section and no accepted predictive witness exists for complete
game construction — one is not invented. Authentic (REAL_MODEL) dispatch
additionally requires a recorded method acceptance in the deployment profile
(the proposed budget numbers are pending human scientific acceptance);
SOFTWARE_TEST validation is exempt.

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
METHODOLOGY = heli.METHODOLOGY_VERSION
FIXTURE_RELPATH = 'fixtures/helicopterbench/advanced-tasks.json'
_ALLOWED_CONFIG_KEYS = frozenset()

_fail = coding._fail


def section_path(campaign):
    return Path(campaign) / 'sections' / SECTION


def load_fixture():
    fixture = json.loads((policy.PROJECT_ROOT / FIXTURE_RELPATH).read_text())
    task = fixture.get('task')
    if fixture.get('version') != '1.0.0' or not task:
        _fail('helicopterbench.fixture', 'unsupported fixture')
    task = {**task,
            'messages': [{'role': 'user', 'content': task['user_task']}]}
    return fixture, {'helicopterbench-01': task}


def plan(profile, config=None):
    policy.validate_profile(profile)
    config = coding._config(config)
    fixture, tasks = load_fixture()
    # Authorization gate before environment checks: REAL_MODEL dispatch
    # requires the recorded method acceptance (the objective-score v2
    # methodology); SOFTWARE_TEST is exempt.
    if profile.get('evidence_kind') == 'REAL_MODEL' and not (
            profile.get('deployment') or {}).get('method_acceptance'):
        _fail('helicopterbench.acceptance',
              'REAL_MODEL dispatch requires the recorded scientific-method '
              'acceptance (deployment.method_acceptance): the '
              'helicopterbench/2 objective-score methodology must be '
              'accepted before real-model dispatch')
    checks = preflight.offline(profile)
    return {'section': SECTION, 'methodology': METHODOLOGY,
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
            raise policy.CheckError('recovery.helicopterbench: changed finalized configuration')
        return status(campaign)
    planned = plan(profile, config)
    identity = _identity(profile, fixture, tasks, planned)
    with store.locked(campaign):
        if (target / 'run.json').exists():
            saved = store.read_json(target / 'run.json')
            if (not policy.compatible_profiles(saved['profile'], profile)
                    or saved['fixture_sha256'] != identity['fixture_sha256']):
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
        raise policy.CheckError('recovery.helicopterbench: wrong campaign')
    if config['methodology'] != METHODOLOGY:
        raise policy.CheckError('recovery.helicopterbench: methodology mismatch')
    profile = profile or config['profile']
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.helicopterbench: wrong campaign')
    return run(profile)


def report_section(campaign, *, browser_binary=None, work_root=None,
                   verification_timeout=150.0):
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
            raise policy.CheckError('finalization.helicopterbench: pending work; resume first')
        resolved = next(iter(units.values()))[0]
        path = Path(resolved['path'])
        envelope = json.loads((path / 'response.raw').read_bytes())
        content = ((envelope.get('choices') or [{}])[0].get('message') or {}).get('content')
        artifact, decision = heli.extract_artifact(content)
        extraction = {'attempt_id': resolved['attempt_id'], 'decision': decision,
                      'artifact_sha256': heli.sha256_hex(artifact) if artifact else None,
                      'artifact_bytes': len(artifact) if artifact else 0}
        reporting.ensure_json(target / 'extraction.json', extraction)
        verification = {'verdict': 'NO_ARTIFACT',
                        'note': 'no extractable artifact; browser verification not run'}
        rubric = {'mechanical_points': None, 'mechanical_max': heli.MECHANICAL_MAX,
                  'final_score': None, 'class': 'NONFUNCTIONAL',
                  'note': 'nothing submitted to verify'}
        if artifact is not None:
            (target / 'submission.html').write_bytes(artifact)
            verification_root = work_root or (policy.PROJECT_ROOT / 'tmp'
                                              / 'helicopterbench-verification')
            verification_root.mkdir(parents=True, exist_ok=True)
            verification = verify.verify_game(
                artifact, browser_binary=browser_binary or verify.find_browser(),
                work_root=verification_root,
                timeout_seconds=verification_timeout)
            verification['artifact_sha256'] = extraction['artifact_sha256']
            rubric = heli.rubric_score(verification)
        rubric_class = rubric.get('class')
        reporting.ensure_json(target / 'heli-verification.json', verification)
        final_score = rubric.get('final_score')
        reporting.ensure_json(target / 'heli-score.json', {
            # Official WELP score: the objective normalized 100-point result
            # of the exact mechanical total (methodology helicopterbench/2).
            # Raw mechanical points and category evidence stay visible.
            'score': final_score,
            'final_score': final_score,
            'methodology': METHODOLOGY,
            'mechanical_points': rubric.get('mechanical_points'),
            'mechanical_max': rubric.get('mechanical_max', heli.MECHANICAL_MAX),
            'class': rubric_class,
            'categories': rubric.get('categories'),
            'generation_outcome': resolved['outcome'],
            'generation_reason': resolved.get('reason')})
        summary['verification_class'] = rubric_class
        summary['mechanical_points'] = rubric.get('mechanical_points')
        summary['final_score'] = final_score
        text = ('# WELP — HelicopterBench\n\n'
                'One-shot artifact benchmark (methodology ' + METHODOLOGY +
                '): the first completed submission is '
                'the submission. Behavior is verified by executing the artifact '
                'inside an isolated browser namespace; the mechanical rubric '
                'scores observed behavior, never source code. The final score '
                'is the objective normalized 100-point result of the exact '
                'mechanical total; no manual visual review is required. '
                'Resource exhaustion is never a completed incorrect game.\n\n'
                'Generation: ' + resolved['outcome'] +
                (f" ({resolved.get('reason')})" if resolved.get('reason') else '') + '. '
                f'Verification class: {rubric_class}. '
                f"Final score: {final_score if final_score is not None else 'none'}/100 "
                f"(mechanical {rubric.get('mechanical_points')} / "
                f"{rubric.get('mechanical_max', heli.MECHANICAL_MAX)}).\n\n"
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
