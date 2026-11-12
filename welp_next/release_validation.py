"""WELP lean release validator (SPEC §11, §8 REWRITE row).

One terminal validator sharing the SAME enforcement predicates as the
producer and CLI — single-authority rule (§8.1). It never re-derives a
scientific rule: manifest verification is `reporting.verify_manifest`,
attempt-outcome reconstruction is `runner.replay_attempt`, section
lifecycle state comes from the section modules' own status functions,
and activation gating is `policy.campaign_activation`. Legacy bundles
are not a validation target.

- `validate_campaign(campaign_root)`: every finalized section's manifest
  is verified hash-by-hash; every runner-backed attempt's outcome is
  reconstructed from original bytes; methodology pins and publication-
  disposition summaries are checked for presence (not invented).
- `release_readiness(campaign_roots)`: aggregates campaigns against the
  §11 readiness requirements — distinct finalized campaigns with a
  finalized Model baseline and at least one exercised advancement gate.

Fail-closed: missing or inconsistent evidence fails the check; valid
negative outcomes remain admissible results; no live inference server is
ever contacted.
"""
import json
from pathlib import Path

from . import policy, reporting, runner, store

RUNNER_BACKED = ('baseline', 'coding', 'advanced-reasoning', 'advanced-long-context',
                 'advanced-tool-use', 'helicopterbench', 'runtime-performance')
ADVANCEMENT_SECTIONS = ('coding', 'advanced-reasoning', 'advanced-long-context',
                        'advanced-tool-use', 'helicopterbench',
                        'runtime-performance')


def _read(path):
    return json.loads(Path(path).read_bytes())


def validate_section(campaign_root, section):
    target = Path(campaign_root) / 'sections' / section
    if not target.exists():
        return {'section': section, 'present': False, 'verified': False,
                'state': 'NOT_RUN'}
    if not (target / 'manifest.json').exists():
        return {'section': section, 'present': True, 'verified': False,
                'state': 'NOT_FINALIZED'}
    reporting.verify_manifest(target)          # shared predicate; raises on tamper
    result = {'section': section, 'present': True, 'verified': True,
              'manifest': 'VERIFIED'}
    run_json = target / 'run.json'
    if run_json.exists():
        config = _read(run_json)
        result['methodology'] = config.get('methodology')
        result['profile_id'] = (config.get('profile') or {}).get('profile_id')
        result['profile_revision'] = config.get('profile_revision')
        if 'gate' in config:
            result['advancement_gate'] = config['gate']
        reference = (config.get('profile') or {}).get('deployment', {}).get('reuse_baseline')
        if reference and section in ('coding', 'advanced-reasoning',
                                      'advanced-long-context', 'advanced-tool-use'):
            from .coding import _advancement_gate
            gate_name = {'advanced-reasoning': 'reasoning',
                         'advanced-long-context': 'long-context',
                         'advanced-tool-use': 'tool-use'}.get(section, section)
            if _advancement_gate(config['profile'], gate_name) != config.get('gate'):
                raise policy.CheckError('validation: reused-baseline gate mismatch')
            result['baseline_reference'] = reference
    if section in RUNNER_BACKED:
        _, units = store.inventory(target)
        config = _read(run_json)
        replay_failures = []
        for uid, rows in units.items():
            resolved = policy.resolved_attempt(rows)
            if resolved is None:
                replay_failures.append(f'{uid}: no resolved attempt')
                continue
            task = None
            fixture_file = target / 'fixture.json'
            if fixture_file.exists():
                fixture = _read(fixture_file)
                if section == 'helicopterbench':
                    from . import helicopterbench
                    # Version-specific pinned fixture: frozen /1-/2 fixture
                    # for the accepted /2 methodology, v3 fixture for the
                    # prospective /3 methodology (original /1 /2 evidence
                    # and reconstruction unaffected).
                    pinned, tasks = helicopterbench.load_fixture(
                        config.get('methodology'))
                    if policy.digest(fixture) != policy.digest(pinned):
                        raise policy.CheckError('validation.helicopterbench: changed fixture')
                    task = tasks.get(uid)
                for candidate in fixture.get('tasks', []):
                    if candidate.get('id') == uid:
                        task = candidate
            if task is None:
                replay_failures.append(f'{uid}: pinned task missing from fixture')
                continue
            try:
                conditions = store.read_json(Path(resolved['path']) / 'conditions.json')
                recorded = policy.recorded_profile(config, conditions)
                policy.validate_echo(recorded, conditions['preflight']['echo'])
                score, fatal = runner.replay_attempt(recorded, task, resolved['path'])
                if fatal != conditions.get('fatal_device_condition'):
                    replay_failures.append(f'{uid}: false fatal attribution')
                elif score['outcome'] != resolved['outcome']:
                    replay_failures.append(f'{uid}: outcome reconstruction mismatch')
            except policy.CheckError as exc:
                replay_failures.append(f'{uid}: {exc}')
        result['units_replayed'] = len(units)
        result['replay_failures'] = replay_failures
        result['verified'] = not replay_failures
    if section == 'helicopterbench' \
            and result.get('methodology') in ('helicopterbench/2',
                                              'helicopterbench/3'):
        # Version-specific offline score reconstruction: the frozen /2
        # scorer for accepted /2 campaigns, the native 100-point /3 scorer
        # for prospective /3 campaigns. /1 evidence is never rescored.
        # /3 reconstructs ONLY an actually gameplay-scored completed
        # submission: a truncated reply can carry an extractable artifact
        # SHA with gameplay_scored=False — that is evidence, never a score.
        extraction = _read(target / 'extraction.json')
        if result['methodology'] == 'helicopterbench/2':
            from .scorers import helicopterbench as heli
            reconstructable = extraction.get('artifact_sha256') is not None
        else:
            from .scorers import helicopterbench_v3 as heli
            reconstructable = (extraction.get('artifact_sha256') is not None
                               and extraction.get('gameplay_scored') is True)
        if reconstructable:
            recorded_score = _read(target / 'heli-score.json')
            verification = _read(target / 'heli-verification.json')
            expected = heli.rubric_score(verification)
            if any(recorded_score.get(key) != expected.get(key)
                   for key in ('final_score', 'mechanical_points', 'mechanical_max', 'class', 'categories')):
                result['replay_failures'].append('helicopterbench: objective score reconstruction mismatch')
                result['verified'] = False
    if section == 'helicopterbench' \
            and result.get('methodology') == 'helicopterbench/3':
        # Exact v3 human-playtesting sidecar: verify its binding against the
        # finalized evidence and expose the reconciliation gate. The sidecar
        # lives outside the section manifest and never alters it.
        from . import heli_review
        review = heli_review.status(campaign_root)
        result['human_review'] = {
            key: review[key] for key in ('state', 'reconciled', 'reviewer',
                                         'earned_points', 'final_points',
                                         'max', 'answered', 'total_items',
                                         'unresolved_items', 'open_disputes',
                                         'reconciled_disputes',
                                         'stale_reconciliations',
                                         'review_sha256',
                                         'reconciliation_sha256',
                                         'human_review_sha256')}
        if review['review_sha256'] is not None:
            try:
                heli_review.binding(campaign_root)  # exact binding check
                review_summary = heli_review.safe_summary(campaign_root)
                result['human_review']['artifact_sha256'] = \
                    review_summary['artifact_sha256']
            except policy.CheckError as exc:
                result['replay_failures'].append(f'helicopterbench: {exc}')
                result['verified'] = False
    return result


def validate_campaign(campaign_root):
    campaign_root = Path(campaign_root)
    sections = sorted(p.name for p in (campaign_root / 'sections').iterdir()
                      if p.is_dir()) if (campaign_root / 'sections').exists() else []
    results = [validate_section(campaign_root, name) for name in sections]
    summaries = campaign_root / 'summaries'
    publication = None
    publication_file = summaries / 'website-publication.json'
    if publication_file.exists():
        try:
            publication = _read(publication_file).get('disposition')
        except ValueError:
            publication = 'MALFORMED'
    return {'campaign': campaign_root.name, 'campaign_root': str(campaign_root),
            'sections': results,
            'all_finalized_sections_verified': all(r.get('verified') is True
                                                   for r in results if r['present']),
            'publication_disposition': publication,
            'publication_disposition_emitted': publication is not None}


def _evaluation_from_record(record):
    by_name = {r['section']: r for r in record['sections']}
    baseline = by_name.get('baseline')
    gates = [r['advancement_gate'] for r in record['sections']
             if r['section'] in ADVANCEMENT_SECTIONS and r.get('advancement_gate')]
    if not (baseline and baseline.get('verified')):
        return None
    return {
        'campaign': record['campaign'],
        'profile_ids': sorted({r.get('profile_id') for r in record['sections']
                               if r.get('profile_id')}),
        'finalized_baseline': True,
        'advancement_decisions_exercised': bool(gates),
        'gate_decisions': gates,
        'verified': record['all_finalized_sections_verified']}


def release_readiness(campaign_roots):
    """Aggregate §11 readiness over finalized campaigns (no inference)."""
    campaigns = [validate_campaign(root) for root in campaign_roots]
    evaluations = []
    for record in campaigns:
        entry = _evaluation_from_record(record)
        if entry is None:
            continue
        for source in campaigns:
            if not source['all_finalized_sections_verified']:
                continue
            for section in source['sections']:
                reference = section.get('baseline_reference', {})
                if (reference.get('campaign_root') == record['campaign_root']
                        and section.get('verified') and section.get('advancement_gate')):
                    entry['gate_decisions'].append(section['advancement_gate'])
                    entry['advancement_decisions_exercised'] = True
        evaluations.append(entry)
    eligible = [e for e in evaluations if e['verified']
                and e['advancement_decisions_exercised']]
    distinct_profiles = sorted({pid for e in evaluations for pid in e['profile_ids']})
    return {
        'validated_campaigns': campaigns,
        'evaluations': evaluations,
        'distinct_evaluations_with_baseline_and_gate': len(eligible),
        'requirement_three_diverse_real_model_evaluations': {
            'required': '>= 3', 'currently_verified': len(eligible),
            'met': len(eligible) >= 3,
            'note': ('counting replay-verified baselines with verified exercised gates; '
                     'diversity (model family/architecture/deployment) and the final '
                     'multi-model acceptance remain human scientific decisions')},
        'distinct_profile_ids': distinct_profiles,
        'rule': ('fail-closed aggregation over the shared predicates only; no new '
                 'scientific rules are defined here (single-authority, SPEC §8.1)')}
