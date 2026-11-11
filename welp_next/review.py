"""Qualified, blinded, append-only subjective review; never alters observations.

One independent evaluator, one additional evaluator only for ambiguity. The
rubric and qualification corpus are extracted scientific assets. Review imports
are evidence, not instructions, and cannot change budgets or mechanical scores.

Reviewer-facing preparation projects each pending packet to an anonymous
transport (opaque ``review_id``, no unit/attempt binding, no campaign/profile/
model/deployment or transport-path metadata, no prior score/verdict fields)
while preserving task, answer, rubric and completion semantics verbatim. The
binding private attribution map stays operator-side; identifying input fails
closed for operator review; historical packet hashes, ``pending_packets`` and
``unit_id``-bound imports are unchanged.
"""
from pathlib import Path
import json

from . import policy, store

ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION = ROOT / 'fixtures/review/qualitative-qualification.json'
RUBRIC = 'welp-review-rubric-0.2.0-draft'
DISPOSITIONS = ('PASS', 'FAIL', 'NOT_EVALUABLE')
# Reviewer-facing projection: exactly these canonical packet keys are safe to
# show a blinded reviewer. The private binding and every transport-identifying
# or prior-score field stay operator-side.
REVIEWER_PACKET_KEYS = ('review_dimension', 'allowed_dispositions', 'rubric_contract',
                        'completion_state', 'mechanical_task_outcome',
                        'outgoing_messages', 'visible_answer', 'observed_actions')
# Metadata key names that identify unit/attempt/campaign/profile/model/
# deployment or transport provenance. Any occurrence near a reviewer surface
# fails closed for operator review.
IDENTITY_KEYS = frozenset((
    'artifact', 'artifacts', 'attempt', 'attempt_id', 'binding', 'campaign',
    'campaign_id', 'campaign_root', 'deployment', 'endpoint', 'evidence_path',
    'host', 'hostname', 'model', 'model_id', 'model_identity', 'path',
    'pathname', 'paths', 'profile', 'profile_id', 'profile_revision',
    'provider', 'root', 'section', 'section_path', 'transport', 'unit',
    'model_key', 'family', 'vendor', 'filename', 'artifact_filename',
    'unit_id'))
# Scorer conclusions are never exported. These names additionally reject
# caller-supplied prior judgments in reviewer submissions; objective facts are
# selected explicitly by _mechanical_facts.
PRIOR_SCORE_KEYS = frozenset((
    '_facets', 'check_pass', 'decisive_pass', 'disposition', 'execution',
    'facets', 'finalized', 'judgment', 'judgments', 'limits', 'mechanical_pass',
    'outcome', 'pass', 'passed', 'prior', 'reason', 'review', 'reviewed',
    'score', 'scored', 'scoring', 'semantic', 'verdict'))
# Reviewer submissions may carry ``unit_id`` (historical binding) and
# ``disposition`` (the required verdict); everything else identity-bearing or
# prior-verdict is refused.
SUBMISSION_KEYS = ((IDENTITY_KEYS - {'unit_id'}) |
                   (PRIOR_SCORE_KEYS - {'disposition'}))
CONTENT_KEYS = frozenset(('outgoing_messages', 'visible_answer'))
REVIEW_CONTENT_KEYS = frozenset(('rationale', 'evidence'))
OPERATING_INSTRUCTION = (
    'Give the stateless reviewer ONLY the bytes of the transport file: anonymous '
    'review_id/packet_sha256 references with the task, visible answer, rubric and '
    'completion state - no filesystem paths or filenames, no campaign/model/'
    'profile metadata, no prior scores or verdicts. The private attribution map '
    'printed here stays operator-side and is never sent to the reviewer. Collect '
    'the returned package (schema_version 1, reviewer identity and qualification, '
    'reviews keyed by review_id + packet_sha256) and import it append-only with '
    '`report --reviews` or `python -m welp_next.review import`.')


def required(task, score):
    return (score.get('execution') == 'VALID' and
            score.get('completion') == 'COMPLETE' and
            score.get('scoring') == 'NOT_SCOREABLE' and
            (task.get('scorer') == 'rubric' or
             task.get('expected', {}).get('kind') == 'reviewed_safety_v1' or
             bool((score.get('record') or {}).get('review_required'))))


def packet(section, task, score):
    path = Path(section) / 'evidence' / task['id'] / score['attempt_id']
    request = store.read_json(path / 'request.json')
    response = json.loads((path / 'response.raw').read_bytes())
    answer = response['choices'][0]['message'].get('content') or ''
    record = score.get('record') or {}
    return {'review_dimension': task.get('rubric', task.get('safety_policy',
                task.get('check', {}).get('rubric', 'Correctness against the task and supplied evidence'))),
            'allowed_dispositions': list(DISPOSITIONS), 'rubric_contract': RUBRIC,
            'completion_state': score['completion'],
            'mechanical_task_outcome': record,
            'outgoing_messages': request['messages'], 'visible_answer': answer,
            'observed_actions': [],
            'binding': {'unit_id': task['id'], 'attempt_id': score['attempt_id'],
                        'request_sha256': policy.file_sha(path / 'request.json'),
                        'response_sha256': policy.file_sha(path / 'response.raw')}}


def _verdict(verdict, answer):
    if verdict.get('disposition') not in DISPOSITIONS:
        raise policy.CheckError('review.disposition: expected PASS/FAIL/NOT_EVALUABLE')
    if not isinstance(verdict.get('rationale'), str) or not verdict['rationale'].strip():
        raise policy.CheckError('review.rationale: deciding rubric clause required')
    quotes = verdict.get('evidence')
    if not isinstance(quotes, list) or (answer and not quotes):
        raise policy.CheckError('review.evidence: exact supporting quotations required')
    if any(not isinstance(q, str) or not q or q not in answer for q in quotes):
        raise policy.CheckError('review.evidence: quotation absent from visible answer')


def validate_reviewer(reviewer):
    if not isinstance(reviewer, dict) or not reviewer.get('id'):
        raise policy.CheckError('review.evaluator: identity required')
    if (reviewer.get('independent_of_execution') is not True or
            reviewer.get('model_identity_blinded') is not True or
            not reviewer.get('provenance')):
        raise policy.CheckError('review.independence: qualified independent blinded evaluator required')
    qualification = reviewer.get('qualification', {})
    if qualification.get('fixture_sha256') != policy.file_sha(QUALIFICATION):
        raise policy.CheckError('review.qualification: wrong fixture identity')
    fixture = store.read_json(QUALIFICATION)
    cases = {c['id']: c for c in fixture['cases']}
    answers = qualification.get('answers')
    if (not isinstance(answers, list) or len(answers) != len(cases) or
            {a.get('case_id') for a in answers} != set(cases)):
        raise policy.CheckError('review.qualification: every fixed case required exactly once')
    for answer in answers:
        case = cases[answer['case_id']]
        _verdict(answer, case['visible_answer'])
        if answer['disposition'] != case['expected_disposition']:
            raise policy.CheckError('review.qualification: nonconformant ' + case['id'])


def pending_packets(section):
    config, units = store.inventory(section)
    fixture = store.read_json(Path(section) / 'fixture.json')
    packets = []
    for task in fixture['tasks']:
        score = policy.resolved_attempt(units.get(task['id'], []))
        if score and required(task, score):
            target = packet(section, task, score)
            packets.append({'unit_id': task['id'], 'packet_sha256': policy.digest(target),
                            'packet': target})
    return packets


def reference(packet_sha256):
    """Opaque anonymous reviewer reference for one exact pending packet."""
    return policy.digest({'welp-review-reference': packet_sha256})


def _mechanical_facts(value):
    """Only objective observations; never prior scorer conclusions or reasons."""
    keys = ('word_count', 'word_limit', 'truncated', 'finish_reason_retained')
    return {key: value[key] for key in keys if key in value}


def _reject_private(value, where, keys, *, content_keys=frozenset(), markers=()):
    """Fail closed on identity-bearing metadata near a reviewer surface.

    Exact key names in ``keys`` and absolute-path or marker-bearing string
    values outside ``content_keys`` raise CheckError for operator review.
    Original task/answer content under ``content_keys`` is never redacted or
    value-scanned."""
    def walk(node, content):
        if isinstance(node, dict):
            for key, item in node.items():
                name = key.lower() if isinstance(key, str) else ''
                if not content and name in keys:
                    raise policy.CheckError(f'{where}: refused metadata field '
                                            f'{key!r} requires operator review')
                walk(item, content or name in content_keys)
        elif isinstance(node, list):
            for item in node:
                walk(item, content)
        elif (isinstance(node, str) and not content and
              (node.startswith('/') or
               any(marker and marker.casefold() in node.casefold() for marker in markers))):
            raise policy.CheckError(f'{where}: refused identity-bearing path '
                                    'value requires operator review')
    walk(value, False)


def projection(target, *, markers=()):
    """Safe reviewer-facing copy of one pending packet: an anonymous
    reference plus exactly the safe canonical keys. Prior score/verdict
    metadata is withheld from the mechanical outcome; identity-bearing
    metadata fails closed. Task, answer, rubric and completion semantics are
    preserved verbatim."""
    packet = target['packet']
    record = packet['mechanical_task_outcome']
    # The frozen rubric contains task-language JSON selectors (for example
    # {"path": ["root_cause", "detail"]}), not deployment attribution.
    _reject_private(record, 'review.preparation', IDENTITY_KEYS,
                    content_keys=frozenset(('rubric',)), markers=markers)
    try:
        safe = {key: packet[key] for key in REVIEWER_PACKET_KEYS}
    except KeyError as exc:
        raise policy.CheckError('review.preparation: unexpected canonical '
                                f'packet shape ({exc.args[0]})') from exc
    safe['mechanical_task_outcome'] = _mechanical_facts(record)
    _reject_private(safe, 'review.preparation', IDENTITY_KEYS,
                    content_keys=CONTENT_KEYS | {'review_dimension'}, markers=markers)
    # Identifying original prose is not silently rewritten. Stop for operator
    # review; arbitrary natural-language anonymity remains an operating duty.
    def content_identity(value):
        if isinstance(value, str):
            return any(m and m.casefold() in value.casefold() for m in markers)
        if isinstance(value, dict):
            return any(content_identity(v) for v in value.values())
        if isinstance(value, list):
            return any(content_identity(v) for v in value)
        return False
    if any(content_identity(safe[key]) for key in CONTENT_KEYS | {'review_dimension'}):
        raise policy.CheckError('review.preparation: identifying original content requires operator review')
    return {'review_id': reference(target['packet_sha256']),
            'packet_sha256': target['packet_sha256'], **safe}


def _model_terms(section):
    """Known model-identity tokens from the section profile: model_key,
    family and vendor when supplied, and the artifact filename, stem and
    directory. Known tokens only — no universal identity detection."""
    try:
        model = (store.read_json(Path(section) / 'run.json').get('profile') or {}).get('model') or {}
    except policy.CheckError:
        model = {}
    terms = set()
    for key in ('model_key', 'family', 'vendor'):
        value = model.get(key)
        if isinstance(value, str) and value.strip():
            terms.add(value.strip())
    location = (model.get('artifact') or {}).get('path')
    if isinstance(location, str) and location.strip():
        artifact = Path(location.strip())
        terms.update({artifact.name, artifact.stem, artifact.parent.name})
    model_key = model.get('model_key')
    if isinstance(model_key, str) and '-' in model_key:
        terms.add(model_key.split('-', 1)[0])
    return {term for term in terms if term and len(term) >= 4}


def _identity_terms(section, targets):
    """Every known identity token a transport path must not carry: campaign
    name, unit/attempt ids and the profile model identity terms. Catches
    family-bearing ancestor paths (the 2026-11-09 incident class) even when
    the directory name is not the campaign name itself."""
    section = Path(section)
    terms = {section.parent.parent.name}
    for target in targets:
        terms.add(str(target['unit_id']))
        terms.add(str(target['packet']['binding']['attempt_id']))
    profile = store.read_json(section / 'run.json').get('profile') or {}
    for extra in (profile.get('deployment'), profile.get('qualification')):
        if isinstance(extra, dict):
            for key in ('family', 'vendor'):
                value = extra.get(key)
                if isinstance(value, str) and value.strip():
                    terms.add(value.strip())
    return terms | _model_terms(section)


def _transport(targets, section):
    section = Path(section)
    campaign = section.parent.parent
    markers = (str(section), campaign.name, *_model_terms(section))
    return {'rubric_contract': RUBRIC,
            'packets': [projection(target, markers=markers) for target in targets]}


def prepare(section):
    """Reviewer transport payload for a section: anonymous packets only. The
    binding private attribution map (``attribution``) is never part of it."""
    return _transport(pending_packets(section), section)


def _map(targets):
    return {reference(target['packet_sha256']):
            {'unit_id': target['unit_id'],
             'attempt_id': target['packet']['binding']['attempt_id'],
             'packet_sha256': target['packet_sha256']}
            for target in targets}


def attribution(section):
    """Private operator mapping binding each anonymous review_id to the exact
    pending packet (unit, attempt, packet digest). Never part of reviewer
    transport or reviewer input."""
    return _map(pending_packets(section))


def export(section, destination):
    """Write the anonymous reviewer transport OUTSIDE the campaign and return
    the transport location, the binding private attribution map and the
    operating instruction. Refuses campaign-owned transport paths and
    identity-bearing path/filenames — the task-owned pathname leak class that
    disqualified a blinded review on 2026-11-09."""
    section = Path(section).resolve()
    supplied_destination = Path(destination)
    destination = supplied_destination.resolve()
    campaign = section.parent.parent
    for owned in (section, campaign):
        if destination.is_relative_to(owned) or owned.is_relative_to(destination):
            raise policy.CheckError('review.export.transport: reviewer transport '
                                    'must live outside the campaign evidence tree')
    targets = pending_packets(section)
    text = supplied_destination.as_posix().casefold() + '\n' + destination.as_posix().casefold()
    for term in _identity_terms(section, targets):
        if term.casefold() in text:
            raise policy.CheckError(
                'review.export.transport: identity-bearing transport path or '
                f'filename ({term!r}) requires operator review; deliver the '
                'transport bytes only, from a neutral path outside the campaign')
    payload = _transport(targets, section)
    store.put(destination, policy.canonical(payload) + b'\n')
    return {'transport': str(destination), 'packets': len(payload['packets']),
            'attribution': _map(targets), 'instruction': OPERATING_INSTRUCTION}


def _validated_packages(section, additional=None):
    section = Path(section)
    targets = {p['unit_id']: p for p in pending_packets(section)}
    references = {reference(t['packet_sha256']): t for t in targets.values()}
    packages = [store.read_json(p) for p in sorted((section / 'reviews').glob('*.json'))]
    if additional is not None and additional not in packages:
        packages.append(additional)
    judgments = {}
    for package in packages:
        if package.get('schema_version') != 1:
            raise policy.CheckError('review.schema_version: expected 1')
        for key in package:
            if isinstance(key, str) and key.lower() in SUBMISSION_KEYS:
                raise policy.CheckError('review.submission: identity-bearing '
                                        f'field {key!r} requires operator review')
        reviewer = package.get('reviewer')
        validate_reviewer(reviewer)
        rows = package.get('reviews')
        if not isinstance(rows, list) or not rows:
            raise policy.CheckError('review.reviews: nonempty judgment list required')
        seen = set()
        for judgment in rows:
            _reject_private(judgment, 'review.submission', SUBMISSION_KEYS,
                            content_keys=REVIEW_CONTENT_KEYS)
            review_id = judgment.get('review_id')
            if review_id is not None:
                if judgment.get('unit_id') is not None:
                    raise policy.CheckError('review.reference: anonymous '
                                            'submission carries a private unit binding')
                target = references.get(review_id) if isinstance(review_id, str) else None
                key = review_id
            else:
                # Historical binding: unit_id plus exact packet digest, unchanged.
                key = judgment.get('unit_id')
                target = targets.get(key)
            if key in seen or target is None:
                raise policy.CheckError('review.target: unknown or duplicate unit')
            seen.add(key)
            if judgment.get('packet_sha256') != target['packet_sha256']:
                raise policy.CheckError('review.binding: changed target packet')
            _verdict(judgment, target['packet']['visible_answer'])
            prior = judgments.setdefault(target['unit_id'], [])
            if prior:
                if len(prior) >= 2 or prior[0]['reviewer_id'] == reviewer['id']:
                    raise policy.CheckError('review.bound: at most two distinct independent evaluators')
                if prior[0]['disposition'] != 'NOT_EVALUABLE' and prior[0].get('disputed') is not True:
                    raise policy.CheckError('review.escalation: primary result is not ambiguous/disputed')
            prior.append({**judgment, 'reviewer_id': reviewer['id']})
    return judgments


def import_reviews(section, path):
    section = Path(section)
    if (section / 'manifest.json').exists():
        raise policy.CheckError('review.finalized: append errata or use a new run, never rewrite')
    payload = store.read_json(path)
    packages = payload if isinstance(payload, list) else [payload]
    if not packages or len(packages) > 2:
        raise policy.CheckError('review.import: one primary package and at most one escalation package')
    for package in packages:
        _validated_packages(section, package)
        existing = sorted((section / 'reviews').glob('*.json'))
        if any(store.read_json(p) == package for p in existing):
            continue
        destination = section / 'reviews' / (f'{len(existing) + 1:04d}-' + policy.digest(package) + '.json')
        store.put_json(destination, package)


def effective_scores(section, fixture, units):
    judgments = _validated_packages(section) if (Path(section) / 'reviews').exists() else {}
    result = {}
    for task in fixture['tasks']:
        uid = task['id']
        score = policy.resolved_attempt(units.get(uid, []))
        if score is None:
            result[uid] = None
            continue
        effective = dict(score)
        if required(task, score):
            decisions = judgments.get(uid, [])
            disposition = 'NOT_EVALUABLE'
            if decisions:
                first = decisions[0]['disposition']
                disposition = first
                if len(decisions) == 2:
                    second = decisions[1]['disposition']
                    disposition = second if first == 'NOT_EVALUABLE' or first == second else 'NOT_EVALUABLE'
                elif decisions[0].get('disputed') is True:
                    disposition = 'NOT_EVALUABLE'
            # Mechanical task constraints remain necessary, not semantic judgments.
            mechanical = (score.get('record') or {}).get('mechanical_pass', True)
            if disposition == 'PASS' and mechanical is False:
                disposition = 'FAIL'
            facets = policy.derive_outcome('VALID', 'COMPLETE',
                {'PASS': 'SCORED_PASS', 'FAIL': 'SCORED_FAIL',
                 'NOT_EVALUABLE': 'NOT_SCOREABLE'}[disposition], 'NONE')
            effective.update(facets)
            effective['review'] = {'disposition': disposition, 'judgments': decisions,
                                   'original_outcome': score['outcome']}
        result[uid] = effective
    return result


def _main(argv=None):
    """Module-level operating helper: anonymous transport export and
    append-only review import. The parent CLI stays in __main__.py."""
    import argparse
    parser = argparse.ArgumentParser(
        prog='python -m welp_next.review',
        description='Blinded reviewer-packet preparation: anonymous transport '
                    'export with a private attribution map, append-only import.')
    commands = parser.add_subparsers(dest='command', required=True)
    writer = commands.add_parser(
        'export', help='write the anonymous reviewer transport outside the campaign; '
                       'print the bound private attribution map and operating instruction')
    writer.add_argument('section')
    writer.add_argument('destination', type=Path)
    reader = commands.add_parser(
        'import', help='validate and append a returned reviewer package')
    reader.add_argument('section')
    reader.add_argument('path', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'export':
        print(json.dumps(export(args.section, args.destination),
                         ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    import_reviews(args.section, args.path)
    stored = len(sorted((Path(args.section) / 'reviews').glob('*.json')))
    print(json.dumps({'imported': str(args.path), 'packages': stored}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
