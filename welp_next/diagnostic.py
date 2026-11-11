"""Non-scored remote deployment diagnostics using WELP execution/evidence primitives.

Three fixed protocol witnesses, not Model/Agentic evaluation tasks or calibration.
The only tool is the existing native read_file interface over two controlled
in-memory diagnostic paths. No frozen Agentic fixture or model code is executed.
"""
import json
from pathlib import Path
import signal

from . import agentic, context, policy, preflight, reporting, runner, store

UNIT_IDS = ('natural-completion', 'length-exhaustion', 'native-tool-feedback')
PROMPTS = {
    'natural-completion': 'Technical protocol diagnostic, not a capability test. Reply with exactly READY. Think briefly.',
    'length-exhaustion': 'Technical token-limit diagnostic. Count from one to twenty, one number per line.',
    'native-tool-feedback': ('Technical interface diagnostic, not Agentic readiness. First call read_file with path '
                             'missing.txt. Follow the resulting tool feedback to recover. After reading receipt.txt, '
                             'reply with exactly its content. Do not invent file content.'),
}
TOOL = next(t for t in agentic.TOOL_JSON_SCHEMAS if t['function']['name'] == 'read_file')


def section_path(campaign):
    return Path(campaign) / 'sections' / 'diagnostic'


def plan(profile):
    if not policy.is_diagnostic(profile):
        raise policy.CheckError('diagnostic.profile: disjoint technical-diagnostic profile required')
    checks = preflight.offline(profile)
    if profile['budgets']['max_tokens'] > 4096 or profile['budgets']['timeout_seconds'] > 180:
        raise policy.CheckError('diagnostic.budget: at most4096 tokens/180seconds per response')
    return {'scope': 'NON_SCORED_DEPLOYMENT_DIAGNOSTIC', 'scientific_credit': False,
            'evidence_kind': profile['evidence_kind'], 'profile_revision': policy.digest(profile),
            'unit_ids': list(UNIT_IDS), 'max_generation_requests': 5,
            'max_generated_tokens': 4 * profile['budgets']['max_tokens'] + 1,
            'preflight': checks}


def _body(profile, uid, messages):
    body = runner.request_body(profile, {'messages': messages})
    body['max_tokens'] = 1 if uid == 'length-exhaustion' else profile['budgets']['max_tokens']
    body['return_tokens'] = True
    if uid == 'native-tool-feedback':
        body.update(tools=[TOOL], tool_choice='auto')
    return body


def _feedback(call):
    """Same native parser as Agentic; no shell, files, permissions or API access."""
    parsed = agentic.parse_native_tool_call(call)
    if parsed['tool'] != 'read_file':
        raise agentic.ParseError('diagnostic permits read_file only')
    path = parsed['args']['path']
    if path == 'missing.txt':
        return {'ok': False, 'error': 'No such diagnostic file. Read receipt.txt instead.'}
    if path == 'receipt.txt':
        return {'ok': True, 'content': 'qualified-native-tool'}
    return {'ok': False, 'error': 'Diagnostic has only missing.txt and receipt.txt.'}


def _messages():
    return {uid: [{'role': 'user', 'content': PROMPTS[uid]}] for uid in UNIT_IDS}


def native_accounting(envelope, cap):
    """One native inclusive generated-token predicate, reused by calibration."""
    n = (envelope.get("usage") or {}).get("completion_tokens")
    verbose = envelope.get("__verbose") or {}
    return (type(n) is int and 0 < n <= cap
            and (envelope.get("timings") or {}).get("predicted_n") == n
            and verbose.get("tokens_predicted") == n
            and isinstance(verbose.get("tokens"), list) and len(verbose["tokens"]) == n)


def _evaluate(profile, uid, exchanges):
    """Pure interpretation from original bytes, shared by execution and replay."""
    checks, observed = {}, []
    messages = _messages()[uid]
    failure, host, limited = None, False, False
    tool_events = []
    for index, row in enumerate(exchanges):
        body, raw, conditions = row['body'], row['raw'], row['conditions']
        if body != _body(profile, uid, messages):
            raise policy.CheckError('diagnostic.request: transcript, parameters or limits changed')
        if index and uid != 'native-tool-feedback':
            raise policy.CheckError('diagnostic.exchanges: unexpected additional generation')
        recon = runner.reconstruct_response(raw)
        envelope = recon['envelope'] or {}
        error = conditions.get('transport_error')
        host |= runner._fatal_condition(raw, error, envelope)
        if error or not 200 <= (conditions.get('http_status') or 0) < 300:
            if conditions.get('client_deadline_exhausted'):
                limited = True
            else:
                failure = 'TRANSPORT_OR_SERVING_FAILURE'
            break
        message = runner._assistant_message(envelope)
        choices = envelope.get('choices') or [{}]
        finish = choices[0].get('finish_reason')
        usage = envelope.get('usage') or {}
        verbose = envelope.get('__verbose') or {}
        n = usage.get('completion_tokens')
        accounting = native_accounting(envelope, body['max_tokens'])
        checks[f'exchange-{index+1}.native_accounting'] = accounting
        checks[f'exchange-{index+1}.model_identity'] = (
            envelope.get('model') == profile['runtime']['serve']['model_id'])
        if not accounting or not checks[f'exchange-{index+1}.model_identity']:
            failure = 'NATIVE_ACCOUNTING_OR_ATTRIBUTION_FAILURE'
            break
        if not message:
            failure = 'INVALID_RESPONSE_ENVELOPE'
            break
        observed.append({'finish_reason': finish, 'usage': usage, 'native_timings': envelope.get('timings'),
                         'generated_token_ids': verbose.get('tokens'),
                         'reasoning_content': message.get('reasoning_content'), 'content': message.get('content')})
        if finish == 'length':
            limited = True
            checks['explicit_length_limit'] = n == body['max_tokens']
            break
        calls = message.get('tool_calls') or []
        if uid == 'native-tool-feedback' and calls:
            if len(calls) != 1 or not isinstance(calls[0].get('id'), str) or not calls[0]['id']:
                failure = 'UNSUPPORTED_TOOL_ENVELOPE'
                break
            try:
                feedback = _feedback(calls[0])
            except agentic.ParseError as exc:
                failure = 'UNSUPPORTED_TOOL_ARGUMENTS: ' + str(exc)
                break
            tool_events.append({'call': calls[0], 'feedback': feedback})
            messages = messages + [message, {'role': 'tool', 'tool_call_id': calls[0]['id'],
                                             'content': json.dumps(feedback, sort_keys=True)}]
        else:
            checks['natural_completion'] = finish == 'stop'
            expected = 'qualified-native-tool' if uid == 'native-tool-feedback' else 'READY'
            checks['diagnostic_content'] = message.get('content', '').strip() == expected
            if index != len(exchanges) - 1:
                raise policy.CheckError('diagnostic.exchanges: generation after final answer')
    if uid == 'native-tool-feedback':
        checks['observed_tool_error_and_recovery'] = (
            len(tool_events) == 2 and tool_events[0]['feedback']['ok'] is False and
            tool_events[1]['feedback']['ok'] is True)
    if uid == 'length-exhaustion':
        checks['expected_length_exhaustion'] = bool(observed and observed[-1]['finish_reason'] == 'length')
    if host or failure:
        facets = policy.derive_outcome('INVALID', 'NOT_APPLICABLE', 'NOT_APPLICABLE', 'HOST' if host else 'NONE')
    elif limited:
        facets = policy.derive_outcome('VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET')
    else:
        facets = policy.derive_outcome('VALID', 'COMPLETE',
                                       'SCORED_PASS' if checks and all(checks.values()) else 'SCORED_FAIL', 'NONE')
    return {**facets, 'checks': checks, 'observed': observed, 'tool_events': tool_events,
            'integration_error': failure, 'scientific_credit': False,
            'diagnostic_checks_pass': bool(checks) and all(checks.values()),
            'fatal_device_condition': host}




def _commit(profile, uid, path, admission, result):
    store.put_json(path / 'conditions.json', {
        'profile': profile, 'profile_revision': policy.digest(profile), 'profile_id': profile['profile_id'],
        'evidence_kind': profile['evidence_kind'], 'preflight': admission,
        'request_limits': profile['budgets'], 'fatal_device_condition': result['fatal_device_condition']})
    result.update(unit_id=uid, attempt_id=path.name, profile_revision=policy.digest(profile),
                  profile_id=profile['profile_id'], evidence_kind=profile['evidence_kind'])
    store.finalize_attempt(path, result, methodology=policy.METHODOLOGY_DIAGNOSTIC)
    return result


def _attempt(profile, uid, path, admission):
    rows, messages = [], _messages()[uid]
    store.put_json(path / 'started.json', {'unit_id': uid, 'profile_revision': policy.digest(profile),
                                         'started_at': runner.now()})
    # Metadata, not generation; preserve actual native rendering/token identities.
    render, tokenize = context.token_client(profile)
    prompt = render(messages)
    tokens = tokenize(prompt)
    store.put_json(path / 'native-context.json', {'messages': messages, 'rendered': prompt,
                   'tokens': tokens, 'prompt_tokens': len(tokens), 'context_capacity': profile['runtime']['context_capacity']})
    if len(tokens) + profile['budgets']['max_tokens'] > profile['runtime']['context_capacity']:
        raise policy.CheckError('diagnostic.context: prompt plus generation reserve does not fit')
    for index in range(1, 4 if uid == 'native-tool-feedback' else 2):
        body = _body(profile, uid, messages)
        prefix = f'exchange-{index:04d}-'
        store.put_json(path / (prefix + 'request.json'), body)  # BEFORE any network action
        if index == 1:
            store.put_json(path / 'request.json', body)
        store.generation_intent(path, body)
        exchange = runner._http_exchange(profile, body, profile['budgets']['timeout_seconds'])
        store.put(path / (prefix + 'response.raw'), exchange['raw'])
        if index == 1:
            store.put(path / 'response.raw', exchange['raw'])
        conditions = {k: v for k, v in exchange.items() if k != 'raw'}
        conditions['transport_error'] = conditions.pop('error')
        conditions['http_status'] = conditions.pop('status')
        conditions['client_deadline_exhausted'] = conditions.pop('timed_out')
        store.put_json(path / (prefix + 'conditions.json'), conditions)
        rows.append({'body': body, 'raw': exchange['raw'], 'conditions': conditions})
        result = _evaluate(profile, uid, rows)
        if result['outcome'] == 'INVALID' or result['limits'] == 'BUDGET':
            break
        envelope = runner.reconstruct_response(exchange['raw'])['envelope'] or {}
        message = runner._assistant_message(envelope)
        calls = message.get('tool_calls') if message else None
        if not calls:
            break
        if uid != 'native-tool-feedback' or len(calls) != 1:
            break
        try:
            feedback = _feedback(calls[0])
        except agentic.ParseError:
            break
        messages = messages + [message, {'role': 'tool', 'tool_call_id': calls[0]['id'],
                                         'content': json.dumps(feedback, sort_keys=True)}]
    return _commit(profile, uid, path, admission, result)


def run(profile):
    plan_value = plan(profile)
    section = section_path(profile['campaign_root'])
    with store.locked(profile['campaign_root']):
        if (section / 'manifest.json').exists():
            reporting.verify_manifest(section)
            return status(profile['campaign_root'])
        identity = {'profile': profile, 'profile_revision': policy.digest(profile),
                    'unit_ids': list(UNIT_IDS), 'software': runner.software_identity(),
                    'scope': plan_value['scope'], 'scientific_credit': False}
        identity['admission_version'] = policy.ADMISSION_VERSION
        if (section / 'run.json').exists():
            saved = store.read_json(section / 'run.json')
            if not policy.compatible_profiles(saved['profile'], profile):
                raise policy.CheckError('diagnostic.recovery: scientifically incompatible configuration')
        else:
            store.put_json(section / 'profile.json', profile)
            store.put_json(section / 'run.json', identity)
        store.check_preparation(section)
        try:
            admission = preflight.online(profile)
        except policy.CheckError as exc:
            store.record_admission(section, getattr(exc, 'evidence', {'ok': False, 'error': str(exc)}))
            raise
        store.record_admission(section, admission)
        _, units = store.inventory(section)
        if policy.safety_stopped(units):
            raise policy.CheckError('diagnostic.safety: previous fatal observation requires review')
        interrupted = False
        def stop(signum, frame):
            nonlocal interrupted
            interrupted = True
        previous = signal.signal(signal.SIGINT, stop)
        try:
            for uid in UNIT_IDS:
                if interrupted:
                    break
                if policy.unit_pending(units[uid]):
                    path = store.new_attempt(section, uid, preparing=True)
                    try:
                        result = _attempt(profile, uid, path, admission)
                    except (policy.CheckError, OSError) as exc:
                        if not store.preparation_only(path):
                            raise
                        store.put_json(path / 'setup-result.json',
                            {'classification':'PREPARATION_FAILURE','model_trial':False,'error':str(exc)})
                        break
                    if result['outcome'] == 'INVALID' or result['fatal_device_condition']:
                        break
        finally:
            signal.signal(signal.SIGINT, previous)
    return status(profile['campaign_root'])


def status(campaign):
    section = section_path(campaign)
    if not (section / 'run.json').exists():
        return {'section': 'diagnostic', 'state': 'NOT_RUN', 'scientific_credit': False}
    _, units = store.inventory(section)
    blocked = bool(store.admission_records(section) and not store.admission_records(section)[-1].get('ok'))
    return {'section': 'diagnostic', 'scientific_credit': False,
            'state': policy.section_state(units, interrupted=policy.safety_stopped(units), blocked=blocked),
            'preparation_failures': store.preparation_failures(section),
            'units': {uid: policy.resolved_attempt(rows) for uid, rows in units.items()}}


def resume(campaign, profile=None):
    profile = profile or store.read_json(section_path(campaign) / 'profile.json')
    if Path(profile['campaign_root']).resolve() != Path(campaign).resolve():
        raise policy.CheckError('recovery.campaign_root: wrong campaign')
    return run(profile)


def report(campaign):
    with store.locked(campaign):
        return _report(campaign)


def _report(campaign):
    section = section_path(campaign)
    if (section / 'manifest.json').exists():
        reporting.verify_manifest(section)
        return store.read_json(section / 'validation.json')
    config, units = store.inventory(section)
    profile = config['profile']
    if not policy.is_diagnostic(profile):
        raise policy.CheckError('diagnostic.validation: wrong methodology')
    if config['profile_revision'] != policy.digest(profile) or config['unit_ids'] != list(UNIT_IDS):
        raise policy.CheckError('diagnostic.validation: changed identity or inventory')
    state = status(campaign)['state']
    if state not in ('COMPLETED', 'COMPLETED_PARTIAL'):
        raise policy.CheckError('diagnostic.report: execution remains interrupted or blocked')
    reconstructed = {}
    for uid, attempts in units.items():
        resolved = policy.resolved_attempt(attempts)
        if not resolved:
            raise policy.CheckError('diagnostic.report: missing committed evidence')
        path = Path(resolved['path'])
        conditions = store.read_json(path / 'conditions.json')
        profile = policy.recorded_profile(config, conditions)
        policy.validate_echo(profile, conditions['preflight']['echo'])
        rows = []
        for p in sorted(path.glob('exchange-*-request.json')):
            prefix = p.name.removesuffix('request.json')
            rows.append({'body': store.read_json(p), 'raw': (path / (prefix + 'response.raw')).read_bytes(),
                         'conditions': store.read_json(path / (prefix + 'conditions.json'))})
        if not rows or len(rows) > (3 if uid == 'native-tool-feedback' else 1):
            raise policy.CheckError('diagnostic.validation: wrong exchange count')
        if (store.read_json(path / 'request.json') != rows[0]['body'] or
                (path / 'response.raw').read_bytes() != rows[0]['raw']):
            raise policy.CheckError('diagnostic.validation: original core exchange mismatch')
        result = _evaluate(profile, uid, rows)
        saved = store.read_json(path / 'score.json')
        if any(saved.get(k) != v for k, v in result.items()):
            raise policy.CheckError('diagnostic.validation: original bytes do not reproduce producer interpretation')
        reconstructed[uid] = result
    receipt = {'disposition': 'PASS', 'scope': 'NON_SCORED_DEPLOYMENT_DIAGNOSTIC',
               'evidence_kind': profile['evidence_kind'], 'scientific_credit': False,
               'profile_revision': config['profile_revision'], 'state': state,
               'technical_checks_pass': all(x['diagnostic_checks_pass'] for x in reconstructed.values()),
               'units': reconstructed}
    reporting.ensure_json(section / 'validation.json', receipt)
    text = '# WELP — non-scored deployment diagnostic\n\nNo Model/Agentic scientific credit.\n\n'
    text += '```json\n' + json.dumps(receipt, indent=2, sort_keys=True) + '\n```\n'
    report_path = section / 'SECTION-REPORT.md'
    if report_path.exists():
        if report_path.read_bytes() != text.encode():
            raise policy.CheckError('diagnostic.report: refusing changed existing report')
    else:
        store.put(report_path, text.encode())
    files = {str(p.relative_to(section)): policy.file_sha(p) for p in section.rglob('*') if p.is_file()}
    store.put_json(section / 'manifest.json', {'files': files})
    return receipt
