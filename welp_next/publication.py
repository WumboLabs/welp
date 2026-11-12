"""Offline public-safe export for the existing WumboLabs registry/site consumer.

No network or evidence mutation. Ordinary exports retain visibility. A separately
recorded, evidence-bound HUMAN_ACCEPTED review admits routine public-safe closeout.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from . import policy, release_validation, reporting, store

DISPOSITIONS = {'WEBSITE_READY', 'WEBSITE_BLOCKED', 'NOT_FOR_PUBLICATION', 'WEBSITE_PUBLISHED'}
FACETS = ('outcome', 'reason', 'execution', 'completion', 'scoring', 'limits')


def public_safe(value):
    """Reject private attribution instead of trying to redact arbitrary bytes."""
    if isinstance(value, dict):
        for item in value.values():
            public_safe(item)
    elif isinstance(value, list):
        for item in value:
            public_safe(item)
    elif isinstance(value, str) and re.search(
            r'/home/|/data/|/mnt/|/tmp/|\.ssh/|https?://(?:127\.|localhost)|'
            r'GPU-[0-9a-f-]{20,}|(?:api[_-]?key|password|bearer)\s*[:=]', value, re.I):
        raise policy.CheckError('publication.public_safety: private value requires operator review')


def _unit_rows(config, units, resolved):
    """Public outcome rows, including identities without an effective score.

    Applicability comes from the frozen inventory, not current runtime support.
    No missing or excluded identity acquires a numeric score.
    """
    excluded = config.get('excluded_units') or {}
    rows = []
    for uid in sorted(set(config['unit_ids']) | set(excluded) | set(resolved)):
        result = resolved.get(uid)
        attempts = units.get(uid, [])
        original = policy.resolved_attempt(attempts)
        reason = excluded.get(uid)
        applicable = uid not in excluded
        applicability = ('APPLICABLE' if applicable else
                         'INTEGRATION_BLOCKED' if reason.startswith('INTEGRATION_BLOCKED:')
                         else 'UNSUPPORTED' if reason.startswith('UNSUPPORTED:')
                         else 'EXCLUDED')
        facets = ({k: result.get(k) for k in FACETS} if result is not None else
                  {**policy.derive_outcome('NOT_RUN', 'NOT_APPLICABLE',
                                          'NOT_APPLICABLE', 'NONE'),
                   'reason': reason or 'No finalized measurement'})
        attempted = any(
            any(Path(attempt['path']).glob('generation-*-intent.json'))
            or ((Path(attempt['path']) / 'response.raw').exists()
                and not (Path(attempt['path']) / 'trial-boundary.json').exists())
            for attempt in attempts)
        impact = ('EXCLUDED_NO_MEASUREMENT' if not applicable else
                  'NO_FINALIZED_MEASUREMENT' if result is None else
                  'INVALID_MEASUREMENT' if result.get('execution') != 'VALID' else
                  'VALID_UNSCORED_MEASUREMENT' if result.get('scoring') not in
                  ('SCORED_PASS', 'SCORED_FAIL') else 'MEASURED_AND_SCORED')
        rows.append({'unit_id': uid, **facets,
                     'technical_applicability': applicability,
                     'exclusion_reason': reason, 'coverage_impact': impact,
                     'attempted': attempted, 'recorded_attempts': len(attempts),
                     'original_outcome': original.get('outcome') if original else None,
                     'original_result': ({k: original.get(k) for k in FACETS}
                                         if original else None)})
    return rows


def export_campaign(campaign):
    campaign = Path(campaign)
    validated = release_validation.validate_campaign(campaign)
    if not validated['sections'] or not validated['all_finalized_sections_verified']:
        raise policy.CheckError('publication.validation: every section must be finalized and replay-verified')
    visibility = store.read_json(campaign / 'summaries/website-publication.json')
    disposition = visibility.get('disposition')
    if disposition not in DISPOSITIONS:
        raise policy.CheckError('publication.disposition: existing public visibility disposition required')
    sections = []
    profiles = {}
    for record in validated['sections']:
        section = campaign / 'sections' / record['section']
        config, units = store.inventory(section)
        profile = config['profile']
        profiles[profile['profile_id']] = profile
        model = None
        if section.name == 'baseline':
            _, model = reporting.finalized_model_evidence(section)
            resolved = model['effective_scores']
        else:
            resolved = {uid: policy.resolved_attempt(attempts) for uid, attempts in units.items()}
        rows = _unit_rows(config, units, resolved)
        item = {'section': section.name, 'profile_id': profile['profile_id'],
                'profile_revision': config['profile_revision'],
                'methodology': config.get('methodology') or profile['framework']['methodology'],
                'evidence_kind': profile['evidence_kind'], 'units': rows,
                'manifest_sha256': policy.file_sha(section / 'manifest.json'),
                'report_sha256': policy.file_sha(section / 'SECTION-REPORT.md')}
        if config.get('gate'):
            item['advancement'] = {k: config['gate'].get(k) for k in ('decision',)}
        if model is not None:
            item['coverage'] = model['coverage']
            item['performance_observations'] = [
                {k: row[k] for k in ('unit_id', 'sample', 'elapsed_seconds', 'timings')}
                for row in model['performance'] if row['category'] == 'performance']
            item['memory'] = model['memory']
        path = section / 'heli-score.json'
        if path.exists():
            item['objective_benchmark'] = store.read_json(path)
        if item['methodology'] == 'helicopterbench/3':
            from . import heli_review
            item['human_benchmark_review'] = heli_review.safe_summary(campaign)
        if section.name == 'runtime-performance':
            observations = []
            for uid, result in resolved.items():
                if result is None:
                    continue
                path = Path(result['path'])
                for sample in sorted(path.glob('*conditions.json')):
                    conditions = store.read_json(sample)
                    observations.append({'unit_id': uid, 'timings': conditions.get('timings')})
            item['performance_observations'] = observations
        sections.append(item)
    first = next(iter(profiles.values()))
    artifact = first['model']['artifact']
    classification = store.read_json(campaign / 'summaries/classification.json').get('classification')
    identity = {'model_id': first['model']['model_key'], 'profile_id': first['profile_id'],
                'event_id': campaign.name, 'event_type': 'welp-recharacterization',
                'event_date': first['profile_id'][-10:]}
    evidence = visibility.get('canonical_evidence') or {
        'state': 'PENDING_HUMAN_GATE', 'proposed_repo': 'WumboLabs/evaluations'}
    evidence = {k: v for k, v in evidence.items()
                if k in ('state', 'repo', 'proposed_repo', 'commit', 'path', 'url')}
    if disposition == 'WEBSITE_PUBLISHED' and evidence.get('state') != 'PUBLISHED':
        raise policy.CheckError('publication.citation: published disposition lacks immutable evidence')
    if evidence.get('state') == 'PUBLISHED':
        commit = evidence.get('commit', '')
        path = evidence.get('path', '')
        if (evidence.get('repo') != 'WumboLabs/evaluations'
                or not re.fullmatch(r'[0-9a-f]{40}', commit)
                or not re.fullmatch(r'[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*', path)
                or any(part in ('.', '..') for part in path.split('/'))):
            raise policy.CheckError('publication.citation: exact central commit and safe path required')
    elif evidence.get('state') != 'PENDING_HUMAN_GATE' or any(k in evidence for k in ('commit', 'path', 'url')):
        raise policy.CheckError('publication.citation: pending evidence cannot invent a public citation')
    result = {
        'schema': 'wumbolabs-labs-publication/1', 'campaign': campaign.name,
        'identity': identity, 'publication_date': identity['event_date'],
        'website_record_slug': 'eval-' + campaign.name,
        'disposition': disposition,
        'reason': visibility.get('reason') or 'Existing campaign visibility retained; export does not authorize publication.',
        'model': {'display_name': identity['model_id']},
        'artifact': {'tested': identity['model_id'], 'precision': artifact.get('quantization', 'UNKNOWN'),
                     'format': artifact['format'], 'revision': artifact['revision'], 'sha256': artifact['sha256']},
        'runtime': {'engine': first['runtime']['engine']['name'],
                    'version': first['runtime']['engine']['version'], 'backend': first['runtime']['backend']},
        'hardware': {'gpu': first.get('hardware', {}).get('device', {}).get('name', 'UNKNOWN')},
        'welp': {'outcome': 'Finalized independent section findings',
                 'classification': classification or 'NOT_ASSIGNED', 'snapshot': first['framework']['methodology']},
        'context': {'practical_default_tokens': first['context']['target'], 'envelope_complete': False,
                    'native_maximum_disposition': 'NOT_CLAIMED'},
        'quality': {'constrained_result': 'See configuration-specific section findings; no composite model score.',
                    'capability_highlights': [s['section'] + ': ' + str(len(s['units'])) + ' recorded identities' for s in sections],
                    'key_guardrails': ['Model and Agentic findings are independent.',
                                       'Performance is deployment-attributed, never model-quality credit.',
                                       'Missing metrics remain unknown; boundary memory samples are not true peaks.']},
        'localmaxxing': {'status': 'BLOCKED', 'note': 'No submission or service-state claim is made by this export.'},
        'canonical_evidence': evidence, 'welp_sections': sections,
        'profile_conditions': [{
            'profile_id': p['profile_id'], 'artifact_sha256': p['model']['artifact']['sha256'],
            'framework': p['framework'], 'runtime': {'engine': p['runtime']['engine']['name'],
                'version': p['runtime']['engine']['version'], 'backend': p['runtime']['backend']},
            'context_capacity': p['runtime']['context_capacity'], 'reasoning': p['reasoning'],
            'sampling': {k: v for k, v in p['sampling'].items() if k != 'qualification_source'},
            'template_sha256': p['model']['tokenizer_chat_template']['sha256']}
            for p in profiles.values()],
        'public_summary': 'Finalized configuration-specific WELP sections with original negative and limited outcomes retained. No composite model score, public release or operational activation is implied.'}
    public_safe(result)
    return result


def accepted_export(export, acceptance, review_source):
    """Apply an operator-recorded scientific decision, never an approval flag.

    The operator must obtain the actual human decision before recording it.
    The private decision source and exact reviewed manifests/visibility are bound
    by hashes; the public receipt contains neither private source bytes nor names.
    This does not authenticate a reviewer or replace scientific review.
    """
    def require(condition, message):
        if not condition:
            raise policy.CheckError('publication.acceptance: ' + message)

    require(acceptance.get('schema') == 'welp-scientific-acceptance/1',
            'recognized review receipt required')
    require(acceptance.get('decision') == 'HUMAN_ACCEPTED',
            'unresolved scientific review')
    require(acceptance.get('campaign_id') == export['campaign'],
            'review belongs to another campaign')
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}', acceptance.get('reviewed_at', '')),
            'review date required')
    require(isinstance(acceptance.get('basis'), str) and acceptance['basis'].strip(),
            'scientific acceptance basis required')
    require(acceptance.get('review_source_sha256') == policy.file_sha(review_source),
            'original human decision source mismatch')
    sections = export.get('welp_sections') or []
    require(sections and all(s.get('evidence_kind') == 'REAL_MODEL' for s in sections),
            'only actual model findings can enter public scientific closeout')
    manifests = {s['section']: s['manifest_sha256'] for s in sections}
    require(acceptance.get('section_manifests') == manifests,
            'review does not cover the exact finalized sections')
    require(all(not any(u.get(k) == 'INVALID' for k in ('outcome', 'execution'))
                for s in sections for u in s['units']),
            'unresolved technical INVALID coverage requires correction')
    human_review_sha = None
    for section in sections:
        if section.get('methodology') != 'helicopterbench/3':
            continue
        human = section.get('human_benchmark_review')
        if isinstance(human, dict) and human.get('state') == 'NOT_APPLICABLE_NO_SUBMISSION':
            objective = section.get('objective_benchmark') or {}
            require(human.get('artifact_sha256') is None
                    and objective.get('final_score') is None
                    and objective.get('mechanical_points') is None
                    and objective.get('categories') is None,
                    'no-submission disposition cannot conceal a scored game')
            continue
        require(isinstance(human, dict) and human.get('state') == 'FINALIZED',
                'HelicopterBench /3 requires a completed attributed human review')
        require(human.get('unresolved_items') == []
                and human.get('open_disputes') == [],
                'HelicopterBench /3 material questions/disagreements remain unresolved')
        require(type(human.get('final_points')) is int and 0 <= human['final_points'] <= 100,
                'HelicopterBench /3 human score is not finalized')
        human_review_sha = human.get('human_review_sha256')
        require(isinstance(human_review_sha, str)
                and re.fullmatch(r'[0-9a-f]{64}', human_review_sha),
                'HelicopterBench /3 exact human-review identity required')
        require(acceptance.get('helicopterbench_human_review_sha256') == human_review_sha,
                'acceptance does not bind the exact reconciled human review')
    # Existing explicit privacy/scope holds cannot disappear through acceptance.
    require(export['disposition'] != 'WEBSITE_BLOCKED',
            'resolve the exceptional website hold before closeout')
    require(export['disposition'] != 'NOT_FOR_PUBLICATION' or export.get('reason') ==
            'Existing campaign visibility retained; export does not authorize publication.',
            'an explicit nonpublication hold needs separate correction')
    public_safe(export)
    receipt = {k: acceptance[k] for k in (
        'schema', 'decision', 'campaign_id', 'reviewed_at', 'basis',
        'review_source_sha256', 'section_manifests')}
    if human_review_sha is not None:
        receipt['helicopterbench_human_review_sha256'] = human_review_sha
    public_safe(receipt)
    result = dict(export, disposition='WEBSITE_READY',
                  scientific_acceptance=receipt,
                  reason='HUMAN_ACCEPTED scientific review; routine public-safe publication is standing-authorized.')
    return result


def attach_gameplay(campaign, export, descriptor):
    """Verify event-specific captured bytes; never generate substitute footage."""
    identity = export['identity']
    section = next((s for s in export['welp_sections']
                    if s['section'] == 'helicopterbench'), None)
    if section is None:
        raise policy.CheckError('publication.media: no HelicopterBench section')
    extraction = store.read_json(Path(campaign) / 'sections/helicopterbench/extraction.json')
    expected = {
        'event_id': identity['event_id'], 'profile_id': section['profile_id'],
        'methodology': section['methodology'],
        'game_sha256': extraction['artifact_sha256'],
        'model_artifact_sha256': export['artifact']['sha256']}
    if any(descriptor.get(k) != v for k, v in expected.items()):
        raise policy.CheckError('publication.media: event/profile/artifact attribution mismatch')
    video = Path(descriptor['video_path'])
    if policy.file_sha(video) != descriptor.get('sha256'):
        raise policy.CheckError('publication.media: captured video checksum mismatch')
    try:
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_streams', '-show_format',
            '-of', 'json', str(video)], timeout=30))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise policy.CheckError('publication.media: MP4 format verification failed') from exc
    stream = next((s for s in probe['streams'] if s.get('codec_type') == 'video'), {})
    if (stream.get('codec_name') != 'h264'
            or 'mp4' not in probe['format']['format_name'].split(',')
            or float(probe['format'].get('duration', 0)) <= 0):
        raise policy.CheckError('publication.media: positive-duration H.264 MP4 required')
    media = dict(expected, sha256=descriptor['sha256'],
                 url=f"/media/evaluations/{identity['event_id']}/gameplay.mp4",
                 duration_seconds=float(probe['format']['duration']),
                 width=stream['width'], height=stream['height'],
                 label='Actual independently executed gameplay from the evaluated generated artifact.')
    public_safe(media)
    return dict(export, gameplay_media=media)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--acceptance', type=Path,
                        help='external evidence-bound HUMAN_ACCEPTED review receipt')
    parser.add_argument('--review-source', type=Path,
                        help='private original human decision source (hashed, never exported)')
    parser.add_argument('--gameplay-media', type=Path,
                        help='event-bound captured MP4 descriptor; requires ffprobe')
    parser.add_argument('--gameplay-unavailable-reason',
                        help='why genuine footage is unavailable; never substitute a demonstration')
    args = parser.parse_args(argv)
    if args.destination.resolve().is_relative_to(args.campaign.resolve()):
        raise policy.CheckError('publication.destination: export must not mutate its scientific source')
    value = export_campaign(args.campaign)
    if bool(args.acceptance) != bool(args.review_source):
        raise policy.CheckError('publication.acceptance: receipt and decision source are both required')
    if args.acceptance:
        value = accepted_export(value, store.read_json(args.acceptance), args.review_source)
    if args.gameplay_media and args.gameplay_unavailable_reason:
        raise policy.CheckError('publication.media: captured footage and unavailable reason are exclusive')
    if args.gameplay_media:
        value = attach_gameplay(args.campaign, value, store.read_json(args.gameplay_media))
    elif args.gameplay_unavailable_reason:
        public_safe(args.gameplay_unavailable_reason)
        value['gameplay_unavailable_reason'] = args.gameplay_unavailable_reason
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with args.destination.open('xb') as target:
        target.write(policy.canonical(value) + b'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
