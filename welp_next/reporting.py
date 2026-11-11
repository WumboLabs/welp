"""Offline evidence validation and independent section finalization."""
import json
from pathlib import Path

from . import policy, preflight, store
from .runner import assess_response, request_body, software_identity, status


def model_summary(section):
    """Independently derived M2 coverage, with effective reviews separated."""
    from . import observation, review
    config, units = store.inventory(section)
    fixture = store.read_json(Path(section) / 'fixture.json')
    effective = review.effective_scores(section, fixture, units)
    resolved = {uid: [dict(score, finalized=True)] if score else []
                for uid, score in effective.items()}
    coverage = policy.baseline_coverage(fixture, resolved, config['profile'])
    performance = []
    vram_samples = []
    host_samples = []
    for task in fixture['tasks']:
        score = effective.get(task['id'])
        if not score or score.get('execution') != 'VALID':
            continue
        path = Path(section) / 'evidence' / task['id'] / score['attempt_id']
        conditions = store.read_json(path / 'conditions.json')
        memory = {}
        for name in observation.NAMES:
            snapshot = observation.read_snapshot(config['profile'], path, name)
            if snapshot is not None:
                memory[name] = snapshot
                host = snapshot.get('observations', {}).get('host', {}).get('mem_available_bytes')
                if isinstance(host, int):
                    host_samples.append(host)
                value = observation.device_memory(config['profile'], snapshot)
                if value is not None:
                    vram_samples.append(value)
        if task.get('repetitions', 1) > 1:
            from .runner import attempt_exchanges
            samples = attempt_exchanges(path, 'repeat')
        else:
            samples = [{'index': 1, 'prefix': '', 'conditions': conditions}]
        for sample in samples:
            observed = sample['conditions']
            performance.append({'unit_id': task['id'], 'sample': sample['index'],
                                'category': task['category'],
                                'profile_id': config['profile']['profile_id'],
                                'elapsed_seconds': observed['elapsed_seconds'],
                                'timings': observed.get('timings') or {},
                                'memory_evidence': [str(path / name) for name in memory],
                                'evidence': str(path / (sample['prefix'] + 'conditions.json'))})
    return {'coverage': coverage, 'effective_scores': effective,
            'performance': performance, 'classification': None,
            'memory': {'sampled_vram_used_max_bytes': max(vram_samples) if vram_samples else 'UNKNOWN',
                       'sampled_host_available_min_bytes': min(host_samples) if host_samples else 'UNKNOWN'},
            'classification_reason': 'Readiness and advancement thresholds are not calibrated',
            'technical_context_capacity': config['profile']['runtime']['context_capacity']}


def model_text(summary, config, model):
    profile = config['profile']
    coverage = model['coverage']
    lines = ['# WELP — standardized Model baseline', '',
             f"Evidence class: **{summary['evidence_kind']}**.",
             f"Profile: `{summary['profile_id']}`; revision `{summary['profile_revision']}`.",
             f"Framework/methodology: `{profile['framework']}`.",
             f"Execution: **{summary['state']}**; scientific coverage: **{coverage['status']}**.",
             'Validation: PASS — reconstruction from original evidence, without a serving endpoint.', '',
             '## Capability coverage', '',
             '| Category | Status | Applicable | Measured | Scored | PASS | FAIL | Missing | Excluded |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for category, row in coverage['categories'].items():
        quality = category != 'performance'
        lines.append(f"| {category} | {row['status']} | {row['applicable']} | {row['measured']} | "
                     f"{row['scored'] if quality else '—'} | {row['pass'] if quality else '—'} | "
                     f"{row['fail'] if quality else '—'} | {len(row['missing'])} | {len(row['excluded'])} |")
    lines += ['', coverage['rule'] + '.', 'Negative scored answers count as evidence, not execution failures.',
              'Measurement coverage and correctness-scoring coverage are independent; an unscored answer is not positive evidence.', '',
              '## Findings and original evidence', '',
              '| Unit | Category | Outcome | Reason | Review | Evidence |',
              '|---|---|---|---|---|---|']
    fixture = store.read_json(Path(summary['campaign']) / 'sections/baseline/fixture.json')
    for task in fixture['tasks']:
        uid = task['id']
        score = model['effective_scores'].get(uid)
        applicable, reason = policy.task_applicability(profile, task)
        if not applicable:
            lines.append(f"| {uid} | {task['category']} | NOT_RUN | {reason} | — | fixture.json |")
        elif score:
            evidence = f"evidence/{uid}/{score['attempt_id']}/"
            reviewed = 'independent' if score.get('review', {}).get('judgments') else 'deterministic/unreviewed'
            lines.append(f"| {uid} | {task['category']} | {score['outcome']} | {score.get('reason') or '—'} | "
                         f"{reviewed} | [{score['attempt_id']}]({evidence}) |")
        else:
            lines.append(f"| {uid} | {task['category']} | NOT_RUN | missing measurement | — | — |")
    lines += ['', '## Practical context', '',
              f"Technical configured capacity: **{model['technical_context_capacity']} tokens**. This is not a semantic-usefulness claim.",
              'Controlled Context and Multi-Document checkpoints retain separate task/seed results, measured rendered-token occupancy and fact/document placement.',
              'Only completed scored checkpoints demonstrate semantic usefulness; configured capacity, missing checkpoints and resource exhaustion never do.',
              'No native/extension maximum or advanced long-context characterization is claimed.', '',
              '## Inference performance — separate from capability scoring', '',
              '| Unit | Response seconds | TTFT seconds | Prompt tokens/s | Generation tokens/s | Evidence |',
              '|---|---:|---|---|---|---|']
    for row in model['performance']:
        if row['category'] not in ('performance', 'context'):
            continue
        timing = row['timings']
        rates = timing.get('tokens_per_second', {})
        lines.append(f"| {row['unit_id']} / sample {row['sample']} | {row['elapsed_seconds']:.6f} | "
                     f"{timing.get('ttft_seconds', 'UNKNOWN')} | {rates.get('prompt', 'UNKNOWN')} | "
                     f"{rates.get('generation', 'UNKNOWN')} | {row['evidence']} |")
    lines += ['', 'Native timing/usage fields, raw streaming observations and sampled memory snapshots are retained per attempt.',
              f"Sampled maximum device VRAM used: {model['memory']['sampled_vram_used_max_bytes']} bytes; "
              f"sampled minimum host memory available: {model['memory']['sampled_host_available_min_bytes']} bytes.",
              'UNKNOWN means unmeasured, never zero. TTFT is a client-observed first generated content/reasoning/tool delta, not total latency.',
              'Context/cache state and token counts remain attached to each workload; no cross-workload average or performance-derived quality score.', '',
              '## Limits and interpretation', '',
              '- Baseline probes are bounded diagnostics, not exhaustive capability certification or a cross-model ranking.',
              '- Qualification-specific native/default reasoning and sampler settings are preserved; one profile/arm is reported independently.',
              '- Budgets, non-evaluable tasks, excluded interfaces, invalid attempts and unresolved reviews remain visible.',
              '- One qualified independent reviewer is used for subjective tasks; one extra independent review is allowed only for ambiguity/dispute.',
              '- No readiness or advancement classification: consequential thresholds remain uncalibrated.',
              '- Basic tool use is not Agentic readiness. Agentic: NOT_TESTED, never a negative Model input.',
              '- Publication, runtime optimization, advanced sections and legacy cutover are outside M2.', '',
              '## Coverage detail', '', '```json',
              json.dumps(coverage, indent=2, sort_keys=True), '```', '',
              '## Qualified deployment', '', '```json',
              json.dumps(profile, indent=2, sort_keys=True), '```', '']
    return '\n'.join(lines)

def verify_manifest(section):
    section = Path(section)
    manifest = store.read_json(section / 'manifest.json')
    actual = {str(p.relative_to(section)): policy.file_sha(p)
              for p in section.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    if manifest.get('files') != actual:
        raise policy.CheckError('manifest.files: missing, added or altered evidence/report')
    return manifest


def validate_prepared_request(profile, task, path, request):
    from . import baseline
    saved = store.read_json(path / 'preparation.json')
    prepared = saved.get('prepared_task')
    if (saved.get('unit_id') != task['id'] or
            saved.get('attempt_id') != path.name or
            saved.get('profile_revision') != policy.digest(profile) or
            not isinstance(prepared, dict) or
            saved.get('prepared_sha256') != policy.digest(prepared)):
        raise policy.CheckError('validation.preparation: identity mismatch')
    conditions = store.read_json(path / 'conditions.json')
    if not conditions.get('preparation_error'):
        baseline.validate_preparation(profile, task, prepared, saved.get('construction_evidence'))
    # runner.replay_attempt derives the actual conversation and repetitions
    # from original bytes, never from producer score claims.
    if not task.get('followups') and not task.get('tools'):
        if request != request_body(profile, prepared):
            raise policy.CheckError('validation.request: changed prepared request')


def validate(section):
    """Validate execution under the recorded implementation."""
    return _validate(section, recorded_finalized=False)


def finalized_model_evidence(section):
    """Reuse finalized M2 science after additive framework changes.

    The sealed prior validation remains attribution to its recorded software.
    Reconstruct original requests, responses, scores and reviews using the
    unchanged M2 predicates; never trust the cached coverage or caller claims.
    This does not authorize execution/resumption under different software.
    """
    section = Path(section)
    verify_manifest(section)
    config = store.read_json(section / 'run.json')
    receipt = store.read_json(section / 'validation.json')
    if (not policy.is_m2(config['profile'])
            or receipt.get('disposition') != 'PASS'
            or receipt.get('evidence_kind') != config['profile']['evidence_kind']):
        raise policy.CheckError('advancement.baseline: finalized validated M2 required')
    reconstructed = _validate(section, recorded_finalized=True)
    if reconstructed != receipt:
        raise policy.CheckError('advancement.baseline: validation receipt does not reproduce')
    model = model_summary(section)
    if model != store.read_json(section / 'model-summary.json'):
        raise policy.CheckError('advancement.baseline: cached scientific summary does not reproduce')
    return config, model


def _validate(section, *, recorded_finalized):
    """Reconstruct scorer inputs from original bytes, not producer claims."""
    section = Path(section)
    config, units = store.inventory(section)
    profile = store.read_json(section / 'profile.json')
    policy.validate_profile(profile)
    fixture = store.read_json(section / 'fixture.json')
    if config['profile'] != profile or policy.digest(profile) != config['profile_revision']:
        raise policy.CheckError('validation.profile: snapshot/revision mismatch')
    if policy.digest(fixture) != config['fixture_sha256']:
        raise policy.CheckError('validation.fixture: changed')
    tasks = {t['id']: t for t in fixture['tasks']}
    if policy.is_m2(profile):
        from . import baseline
        if fixture != baseline.load_fixture(profile):
            raise policy.CheckError('validation.fixture: differs from pinned M2 inventory')
        expected_ids = [uid for uid, task in tasks.items() if policy.task_applicability(profile, task)[0]]
        excluded = {uid: policy.task_applicability(profile, task)[1]
                    for uid, task in tasks.items() if uid not in expected_ids}
        if expected_ids != config['unit_ids'] or excluded != config.get('excluded_units'):
            raise policy.CheckError('validation.plan: changed applicable M2 inventory')
    elif list(tasks) != config['unit_ids'] or len(tasks) != 20:
        raise policy.CheckError('validation.plan: expected exact 20-unit fixture')
    checked = []
    for uid, rows in units.items():
        valid_seen = False
        for row in rows:
            if not row.get('finalized'):
                continue
            if valid_seen:
                raise policy.CheckError(f'validation.duplicate: attempt after valid measurement {uid}')
            path = Path(row['path'])
            conditions = store.read_json(path / 'conditions.json')
            attempt_profile = policy.recorded_profile(config, conditions)
            request = store.read_json(path / 'request.json')
            if policy.is_m2(attempt_profile):
                validate_prepared_request(attempt_profile, tasks[uid], path, request)
            elif request != request_body(attempt_profile, tasks[uid]):
                raise policy.CheckError(f'validation.request: differs from pinned task/config {uid}')
            # The raw request file is exactly the bytes sent on the wire.
            if (path / 'request.json').read_bytes() != policy.canonical(request) + b'\n':
                raise policy.CheckError(f'validation.request_bytes: {uid}')
            conditions = store.read_json(path / 'conditions.json')
            if (conditions['request_limits'] != policy.task_budget(attempt_profile, tasks[uid]) or
                    conditions['evidence_kind'] != attempt_profile['evidence_kind']):
                raise policy.CheckError(f'validation.conditions: mismatched attribution {uid}')
            policy.validate_echo(attempt_profile, conditions['preflight']['echo'])
            raw = (path / 'response.raw').read_bytes()
            if policy.is_m2(profile):
                from .runner import replay_attempt
                expected, fatal = replay_attempt(attempt_profile, tasks[uid], path)
            else:
                expected, fatal = assess_response(
                    tasks[uid], raw, error=conditions.get('transport_error'),
                    timed_out=conditions.get('client_deadline_exhausted', False))
            if fatal != conditions.get('fatal_device_condition'):
                raise policy.CheckError(f'validation.safety: false fatal-condition attribution {uid}')
            scientific = {k: v for k, v in row.items() if k not in
                          ('unit_id', 'attempt_id', 'profile_revision', 'profile_id',
                           'evidence_kind', 'finalized', 'path')}
            if scientific != expected:
                raise policy.CheckError(f'validation.scoring: does not reproduce {uid}/{path.name}')
            valid_seen = row['execution'] == 'VALID'
            checked.append(f'{uid}/{path.name}')
    summary = status(section.parents[1])
    if not summary['finalizable']:
        raise policy.CheckError('validation.section: INTERRUPTED; resume before finalization')
    return {'disposition': 'PASS', 'basis': 'independent offline reconstruction',
            'evidence_kind': profile['evidence_kind'], 'scope': config['scope'],
            'checked_attempts': checked, 'state': summary['state'],
            'resolved_attempts': {r['unit_id']: r['resolved_attempt'] for r in summary['units']}}


def section_text(summary, config):
    profile = config['profile']
    lines = ['# WELP — limited Model evaluation vertical slice', '',
             '**Not a full WELP baseline or model readiness verdict.**', '',
             f"Evidence class: {summary['evidence_kind']}. " +
             ('Synthetic software validation; not real-model measurements.'
              if summary['evidence_kind'] == 'SOFTWARE_TEST' else 'Real-model measurement evidence.'), '',
             f"Profile: `{summary['profile_id']}`", f"Revision: `{summary['profile_revision']}`",
             f"Framework/methodology: `{profile['framework']}`", '',
             f"Section: baseline / reliability; state: **{summary['state']}**",
             'Validation: PASS — independent reconstruction from original evidence.',
             f"Evidence: `{summary['campaign']}/sections/baseline/`", '',
             '## Scientific results', '',
             '| Profile | Unit | Outcome | Reason | Resolved attempt | Attempts |',
             '|---|---|---|---|---|---|']
    for row in summary['units']:
        lines.append(f"| {row['profile_id']} | {row['unit_id']} | {row['outcome']} | "
                     f"{row['reason'] or '—'} | {row['resolved_attempt'] or '—'} | {row['attempts']} |")
    lines += ['', '## Configuration and conditions (not quality inputs)', '',
              '```json', json.dumps(profile, indent=2, ensure_ascii=False, sort_keys=True), '```', '',
              'Exact request limits, server echoes, timestamps, finish reasons, usage and latency',
              'are retained in each attempt. Latency/throughput are never quality-score inputs.', '',
              '## Limitations and gaps', '',
              '- Exactly 20 tasks, seed 42, one predeclared budget condition; not the legacy',
              '  paired-lane/two-seed reliability study and not the full Model baseline.',
              '- The git safety task requires a qualified independent semantic review. Without',
              '  it, the answer is retained as NOT_EVALUABLE/RUBRIC_INDETERMINATE, not FAIL.',
              '- Valid incorrect answers and budget-limited answers are findings, not framework failures.',
              '- INVALID measurements (if present) are bounded execution gaps, never model-quality failures.',
              '- In-flight uncommitted attempts remain provenance, not scientific credit.',
              '- Model classification not assigned from this limited slice. Agentic: NOT_TESTED.',
              '- Advancement, publication, runtime comparisons and campaign closeout are out of scope.', '']
    return '\n'.join(lines)


def ensure_json(path, value):
    if path.exists():
        if store.read_json(path) != value:
            raise policy.CheckError(f'finalization.existing: refusing rewrite {path}')
    else:
        store.put_json(path, value)


def report_section(campaign, reviews=None):
    section = store.section_path(campaign)
    with store.locked(campaign):
        if (section / 'manifest.json').exists():
            if reviews is not None:
                raise policy.CheckError('review.finalized: cannot import into immutable finalized section')
            verify_manifest(section)
            return {'disposition': 'PASS', 'report': str(section / 'SECTION-REPORT.md'),
                    'manifest': str(section / 'manifest.json'), 'already_finalized': True}
        if reviews is not None:
            from . import review
            review.import_reviews(section, reviews)
        result = validate(section)
        config, _ = store.inventory(section)
        summary = status(campaign)
        if policy.is_m2(config['profile']):
            model = model_summary(section)
            ensure_json(section / 'model-summary.json', model)
            text = model_text(summary, config, model).encode()
        else:
            text = section_text(summary, config).encode()
        report = section / 'SECTION-REPORT.md'
        if report.exists():
            if report.read_bytes() != text:
                raise policy.CheckError('finalization.report: refusing rewrite')
        else:
            store.put(report, text)
        ensure_json(section / 'validation.json', result)
        files = {str(p.relative_to(section)): policy.file_sha(p)
                 for p in section.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        store.put_json(section / 'manifest.json', {'schema_version': 1,
                       'profile_revision': config['profile_revision'], 'files': files})
        verify_manifest(section)
        return {'disposition': 'PASS', 'report': str(report),
                'manifest': str(section / 'manifest.json'), 'state': summary['state']}


def _report_independent_sections(campaign):
    """Render finalized standalone sections without fabricating a baseline."""
    sections = sorted(p for p in (campaign / 'sections').iterdir() if p.is_dir())
    if not sections:
        raise policy.CheckError('campaign.report: no sections')
    rows = []
    texts = []
    for section in sections:
        verify_manifest(section)
        config = store.read_json(section / 'run.json')
        profile = config['profile']
        rows.append({'section': section.name, 'profile_id': profile['profile_id'],
                     'evidence_kind': profile['evidence_kind'],
                     'methodology': config.get('methodology'),
                     'report': f'sections/{section.name}/SECTION-REPORT.md'})
        texts.append((section / 'SECTION-REPORT.md').read_text())
    text = '# WELP — independent sections\n\nNo baseline result is assigned by this campaign.\n\n'
    text += '\n\n'.join(texts)
    companion = '# WELP lab record\n\n' + json.dumps(rows, indent=2, sort_keys=True) + '\n'
    for name, body in [('REPORT.md', text), ('WELP-LAB-RECORD.md', companion)]:
        path = campaign / name
        if path.exists() and path.read_text() != body:
            raise policy.CheckError(f'campaign.report: refusing rewrite {name}')
        if not path.exists():
            store.put(path, body.encode())
    values = {
        'classification.json': {'classification': None, 'disposition': 'INDEPENDENT_SECTIONS_ONLY'},
        'section-dispositions.json': {'sections': rows, 'baseline': 'NOT_RUN'},
        'localmaxxing.json': {'disposition': 'NOT_APPLICABLE_INDEPENDENT_SECTIONS'},
        'website-publication.json': {'disposition': 'NOT_FOR_PUBLICATION'}}
    for name, value in values.items():
        ensure_json(campaign / 'summaries' / name, value)
    return {'disposition': 'PASS', 'report': str(campaign / 'REPORT.md'),
            'scope': 'INDEPENDENT_SECTIONS', 'sections': rows}


def report_campaign(campaign):
    campaign = Path(campaign)
    section = store.section_path(campaign)
    with store.locked(campaign):
        if not section.exists():
            return _report_independent_sections(campaign)
        verify_manifest(section)
        summary = status(campaign)
        config, _ = store.inventory(section)
        text = ('# WELP — limited Model vertical slice\n\n'
                f"Evidence class: {summary['evidence_kind']}.\n\n"
                'Model: baseline/reliability slice only; no full baseline or classification.\n'
                'Agentic: NOT_TESTED (independent; not a negative Model input).\n\n'
                f"Finalized section: [SECTION-REPORT.md](sections/baseline/SECTION-REPORT.md)\n\n"
                f"State: {summary['state']}; validation PASS.\n")
        m2 = policy.is_m2(config['profile'])
        if m2:
            text = (section / 'SECTION-REPORT.md').read_text().replace(
                '](evidence/', '](sections/baseline/evidence/')
        from . import m3
        agentic_sections = m3.finalized_sections(campaign)
        if agentic_sections:
            text += ('\n## Independent Agentic software validation\n\n'
                     'SOFTWARE_TEST only; not authentic Agentic model science. '
                     'Model findings above are unchanged; the historical baseline '
                     'NOT_TESTED statement describes that section in isolation.\n\n')
            for name, result in agentic_sections.items():
                text += (f"- {name}: {result['state']}; "
                         f"[independent report](sections/{name}/SECTION-REPORT.md).\n")
            text += '\nScientific Agentic qualification and task budgets: pending calibration and real-model validation.\n'
        companion = ('# WELP lab record\n\n'
                     f"Profile: `{summary['profile_id']}`.\n\n"
                     f"Evidence class: {summary['evidence_kind']}; execution: {summary['state']}.\n\n"
                     'Primary model findings: [REPORT.md](REPORT.md).\n\n'
                     'Validated baseline: [SECTION-REPORT.md](sections/baseline/SECTION-REPORT.md).\n'
                     if m2 else '# WELP lab record\n\n' + text.split('\n', 2)[2])
        for name, body in [('REPORT.md', text), ('WELP-LAB-RECORD.md', companion)]:
            path = campaign / name
            if path.exists():
                if path.read_text() != body:
                    raise policy.CheckError(f'campaign.report: refusing rewrite {name}')
            else:
                store.put(path, body.encode())
        summaries = campaign / 'summaries'
        values = {'classification.json': {'classification': None,
                  'disposition': 'NOT_ASSIGNED_LIMITED_SLICE', 'profile_id': summary['profile_id']},
                  'section-dispositions.json': {'Model': summary['state'], 'Agentic': 'NOT_TESTED'},
                  'localmaxxing.json': {'disposition': 'NOT_APPLICABLE_M1'},
                  'website-publication.json': {'disposition': 'NOT_APPLICABLE_M1'}}
        if m2:
            model = store.read_json(section / 'model-summary.json')
            values['classification.json']['disposition'] = 'NOT_ASSIGNED_UNCALIBRATED'
            values['section-dispositions.json']['Model_coverage'] = model['coverage']['status']
            values['localmaxxing.json']['disposition'] = 'NOT_APPLICABLE_M2_DEVELOPMENT'
            values['website-publication.json']['disposition'] = 'NOT_FOR_PUBLICATION'
        if agentic_sections:
            values['section-dispositions.json']['Agentic'] = {
                name: {'execution': result['state'], 'evidence_kind': 'SOFTWARE_TEST',
                       'scientific_validation': 'NOT_TESTED'}
                for name, result in agentic_sections.items()}
        for name, value in values.items():
            ensure_json(summaries / name, value)
        return {'disposition': 'PASS', 'report': str(campaign / 'REPORT.md'),
                'evidence_kind': config['profile']['evidence_kind'], 'scope': config['scope']}
