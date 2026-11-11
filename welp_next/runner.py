"""One profile-parametrized OpenAI chat execution path.

M1 (``baseline-reliability-slice/1``) keeps the limited vertical slice:
non-streaming requests against the 20-task reliability fixture. M2
(``model-baseline/2``) extends the same runner with the pinned full-baseline
inventory: preparation evidence, native tool schemas driven only through the
frozen in-process simulator, actual multi-turn correction conversations,
dedicated streaming performance units (repeated, raw SSE + deterministic
reconstruction), standardized request timings, and pinned applicability
exclusions. Measurements never touch quality scoring; the scoring dispatch
stays in :mod:`welp_next.scoring`.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request
import uuid

from . import observation, policy, preflight, scoring, store


M1_PART = 'reliability'
M2_PART = 'baseline'
PARTS = (M1_PART, M2_PART)
M1_SCOPE = 'LIMITED_VERTICAL_SLICE'
M2_SCOPE = 'FULL_MODEL_BASELINE'
UNKNOWN = 'UNKNOWN'
MAX_TOOL_CALLS = 3


def now():
    return datetime.now(timezone.utc).isoformat()


def software_identity():
    """Readable implementation attribution, not a frozen Linux/source inventory."""
    return {'implementation': 'welp-lean-admission/1', 'framework': policy.FRAMEWORK_M2}


# ---------------------------------------------------------------------------
# Part / inventory resolution (the profile pin fixes the section inventory)


def resolve_part(profile, part=None):
    """Resolve ``--part`` against the profile's methodology pin.

    The default is profile-specific. A mismatching part is rejected instead of
    silently narrowing (or silently widening) the pinned inventory.
    """
    if policy.is_diagnostic(profile) or policy.is_calibration(profile):
        raise policy.CheckError('part: non-scored diagnostics/calibration cannot select Model execution')
    default = M2_PART if policy.is_m2(profile) else M1_PART
    if part is None or part == default:
        return part if part is not None else default
    if policy.is_m2(profile):
        raise policy.CheckError(
            'part: M2 pins the full baseline inventory; --part reliability would '
            'silently narrow it — run --part baseline or use an M1 profile')
    raise policy.CheckError(
        'part: M1 pins the reliability slice only; --part baseline requires a '
        f'{policy.METHODOLOGY_M2} (M2) profile')


def load_inventory(profile):
    """Full pinned fixture for the profile methodology (M1 loader unchanged)."""
    if policy.is_m2(profile):
        from . import baseline
        return baseline.load_fixture(profile), True
    return scoring.load_fixture(), False


def m2_split(fixture, profile):
    """Split the pinned inventory via policy.task_applicability (one authority).

    Returns (applicable tasks, excluded_units mapping uid -> reason). Excluded
    units are pinned in the run identity; they are never attempted and never
    silently dropped.
    """
    applicable, excluded = [], {}
    for task in fixture['tasks']:
        ok, reason = policy.task_applicability(profile, task)
        if ok:
            applicable.append(task)
        else:
            excluded[task['id']] = reason
    return applicable, excluded


def plan(profile, part=None):
    checks = preflight.offline(profile)
    resolved = resolve_part(profile, part)
    fixture, m2 = load_inventory(profile)
    plan_value = {'framework': profile['framework'], 'profile_id': profile['profile_id'],
                  'profile_revision': policy.digest(profile), 'evidence_kind': profile['evidence_kind'],
                  'section': 'baseline', 'part': resolved,
                  'scope': M2_SCOPE if m2 else M1_SCOPE,
                  'unit_ids': [t['id'] for t in fixture['tasks']],
                  'sampling': profile['sampling'], 'budgets': profile['budgets'], 'preflight': checks}
    if m2:
        applicable, excluded = m2_split(fixture, profile)
        policy.baseline_coverage(fixture, {}, profile)
        plan_value['inventory_ids'] = plan_value['unit_ids']
        plan_value['unit_ids'] = [task['id'] for task in applicable]
        plan_value['planned_units'] = [
            {'unit_id': t['id'], 'category': t.get('category'),
             'max_tokens': policy.task_budget(profile, t)['max_tokens'],
             'timeout_seconds': policy.task_budget(profile, t)['timeout_seconds']}
            for t in applicable]
        plan_value['excluded_units'] = [
            {'unit_id': uid, 'reason': reason} for uid, reason in sorted(excluded.items())]
    return plan_value


def initialize(profile, section, part=None):
    resolved = resolve_part(profile, part)
    fixture, m2 = load_inventory(profile)
    excluded = {}
    if m2:
        applicable, excluded = m2_split(fixture, profile)
        policy.baseline_coverage(fixture, {}, profile)
        unit_ids = [t['id'] for t in applicable]
    else:
        unit_ids = [t['id'] for t in fixture['tasks']]
    config = {'framework': profile['framework'], 'profile': profile,
              'profile_revision': policy.digest(profile),
              'fixture_sha256': policy.digest(fixture),
              'software': software_identity(), 'created_at': now(),
              'unit_ids': unit_ids, 'part': resolved,
              'scope': M2_SCOPE if m2 else M1_SCOPE}
    config['admission_version'] = policy.ADMISSION_VERSION
    if m2:
        config['excluded_units'] = excluded
    section.mkdir(parents=True, exist_ok=True)
    config_path = section / 'run.json'
    if config_path.exists():
        saved = store.read_json(config_path)
        default_part = M2_PART if policy.is_m2(profile) else M1_PART
        if not policy.compatible_profiles(saved['profile'], profile):
            raise policy.CheckError('recovery.profile: scientifically incompatible configuration')
        for key in ('framework', 'fixture_sha256', 'unit_ids', 'scope', 'excluded_units'):
            if saved.get(key) != config.get(key):
                raise policy.CheckError(f'recovery.{key}: changed; use a new authorized campaign, not resume')
        # Historical M1 run identity has no 'part'; it is the profile default.
        if saved.get('part', default_part) != config['part']:
            raise policy.CheckError('recovery.part: changed; use a new authorized campaign, not resume')
        return saved
    # An interruption during initialization is safely repeatable; snapshots are
    # published exclusively and checked before completing the initialization commit.
    if any(p.name not in ('fixture.json', 'profile.json') and not p.name.startswith('.pending-')
           for p in section.iterdir()):
        raise policy.CheckError('recovery.initialize: foreign evidence without run identity')
    for name, value in (('fixture.json', fixture), ('profile.json', profile)):
        path = section / name
        if path.exists():
            if store.read_json(path) != value:
                raise policy.CheckError(f'recovery.initialize: inconsistent {name}')
        else:
            store.put_json(path, value)
    store.put_json(section / 'run.json', config)
    return config


# ---------------------------------------------------------------------------
# Request rendering (prepared task in; native tools and streaming declared here)


def wants_streaming(profile, task):
    """Streaming is reserved for the dedicated fixed performance units."""
    if (task.get('method') or {}).get('streaming'):
        return True
    return policy.is_m2(profile) and task.get('category') == 'performance'


def _native_llama_cpp(profile):
    """The native llama.cpp serving stack: any profile whose declared runtime
    engine is llama.cpp speaks the llama.cpp server contract (cache_prompt is
    part of that server's completion endpoint regardless of the metadata
    echo path), so the declared measurement condition is profile-independent.
    Generic OpenAI-compatible endpoints (other engines) never receive
    nonstandard request keys."""
    return ((profile.get('runtime') or {}).get('engine') or {}).get('name') == 'llama.cpp'


def request_body(profile, task):
    budget = policy.task_budget(profile, task)
    body = {'model': profile['runtime']['serve']['model_id'], 'messages': task['messages'],
            'stream': False, 'max_tokens': budget['max_tokens'],
            **policy.sampling_settings(profile)}
    if task.get('tools'):
        body['tools'] = task['tools']
        if task.get('tool_choice') is not None:
            body['tool_choice'] = task['tool_choice']
    if wants_streaming(profile, task):
        body['stream'] = True
        body['stream_options'] = {'include_usage': True}
    if (task.get('method') or {}).get('cache_prompt') is False and _native_llama_cpp(profile):
        # Pinned per-request measurement condition for the fixed performance
        # units: the native llama.cpp server is told not to reuse cached
        # prompt state for THIS request, so prompt throughput is measured
        # over the full prompt. This is a fixed declared measurement
        # condition, never a runtime optimization or system cache flush.
        # Observed native cache_n/prompt_n stay verbatim (UNKNOWN when
        # absent) in the timings and are never labeled cold/warm.
        body['cache_prompt'] = False
    controls = profile['reasoning']['controls']
    return {**body, **controls}


# ---------------------------------------------------------------------------
# Scoring dispatch (M1 reliability scorer unchanged; M2 via the science module)


def _dispatch(task, response, *, timed_out=False, m2=False):
    return scoring.score_dispatch(task, response, timed_out=timed_out, m2=m2)


def _fatal_condition(raw, error, envelope=None):
    """The single fatal device/host stop decision over ORIGINAL bytes: a
    transport error or an error envelope whose text matches a fatal
    accelerator condition. Shared by the live loop, assess_response and
    offline replay, so an HTTP-200 SSE error frame stops exactly like a
    nonstream error envelope."""
    error_envelope = isinstance(envelope, dict) and 'error' in envelope
    return bool(error or error_envelope) and policy.fatal_device_error(
        bytes(raw).decode('utf-8', errors='replace') + '\n' + (error or ''))


def assess_response(task, raw, *, error=None, timed_out=False, m2=False, envelope=None):
    """Shared interpretation; final validation reconstructs these inputs from disk."""
    parsed = envelope
    parse_error = None
    if parsed is None:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError) as exc:
            parse_error = exc
    if _fatal_condition(raw, error, parsed):
        return scoring.invalid_score('fatal accelerator condition', host=True), True
    if timed_out:
        return _dispatch(task, {}, timed_out=True, m2=m2), False
    if error:
        return scoring.invalid_score(error), False
    try:
        if parsed is None:
            raise parse_error
        return _dispatch(task, parsed, m2=m2), False
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return scoring.invalid_score(f'malformed response/scorer: {exc}'), False


# ---------------------------------------------------------------------------
# Deterministic response reconstruction (execute and offline report share this)


def reconstruct_response(raw, streaming=False):
    """Pure decoder over ORIGINAL bytes; no I/O, no clocks, no profile.

    streaming=False: the raw body is one JSON envelope (or None when
    unparseable). streaming=True: raw is the SSE wire byte stream; the
    reconstructed envelope is assembled exactly like the OpenAI nonstream
    shape (content deltas joined; tool_call deltas assembled by index).
    """
    raw = bytes(raw)
    recon = {'streaming': bool(streaming), 'raw_sha256': hashlib.sha256(raw).hexdigest()}
    if not streaming:
        try:
            envelope = json.loads(raw)
        except (ValueError, TypeError):
            envelope = None
        finish = usage = native = None
        if isinstance(envelope, dict):
            choices = envelope.get('choices')
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                finish = choices[0].get('finish_reason')
            if isinstance(envelope.get('usage'), dict):
                usage = envelope['usage']
            if isinstance(envelope.get('timings'), dict):
                native = envelope['timings']
        recon.update(envelope=envelope, chunk_count=1 if envelope is not None else 0,
                     complete=envelope is not None, finish_reason=finish, usage=usage,
                     native_timings=native, has_content_delta=False,
                     has_reasoning_delta=False, has_tool_delta=False)
        return recon
    frames = []
    complete = False
    for line in raw.splitlines():
        if not line.startswith(b'data:'):
            continue
        payload = line[5:].strip()
        if payload == b'[DONE]':
            complete = True
            break
        try:
            frame = json.loads(payload)
        except ValueError:
            continue
        if isinstance(frame, dict):
            frames.append(frame)
    content = []
    reasoning_content = []
    reasoning = []
    tools = {}
    finish = None
    usage = None
    native = None
    model = None
    frame_error = None
    has_content = False
    has_reasoning = False
    has_tool = False
    for frame in frames:
        if frame.get('model'):
            model = frame['model']
        if 'error' in frame:
            # SSE error frames are error envelopes, never dropped: an
            # HTTP-200 accelerator/host failure must stop the attempt
            # immediately (via the shared fatal condition) and must survive
            # offline replay byte-for-byte.
            frame_error = frame['error']
        if isinstance(frame.get('usage'), dict):
            usage = frame['usage']
        if isinstance(frame.get('timings'), dict):
            native = frame['timings']  # native servers report timings on the last frame
        choices = frame.get('choices')
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        delta = choice.get('delta') if isinstance(choice.get('delta'), dict) else {}
        if isinstance(delta.get('content'), str) and delta['content']:
            content.append(delta['content'])
            has_content = True
        for field, parts in (('reasoning_content', reasoning_content),
                             ('reasoning', reasoning)):
            value = delta.get(field)
            if isinstance(value, str) and value:
                parts.append(value)
                has_reasoning = True
        for call in delta.get('tool_calls') or []:
            has_tool = True
            index = call.get('index') if isinstance(call.get('index'), int) else 0
            slot = tools.setdefault(index, {
                'id': None, 'type': 'function', 'function': {'name': '', 'arguments': ''}})
            if call.get('id'):
                slot['id'] = call['id']
            if call.get('type'):
                slot['type'] = call['type']
            function = call.get('function') or {}
            if function.get('name'):
                slot['function']['name'] = function['name']
            if isinstance(function.get('arguments'), str):
                slot['function']['arguments'] += function['arguments']
        if choice.get('finish_reason'):
            finish = choice['finish_reason']
    envelope = None
    if frames:
        message = {'role': 'assistant'}
        text = ''.join(content)
        if text or not tools:
            message['content'] = text
        if reasoning_content:
            message['reasoning_content'] = ''.join(reasoning_content)
        if reasoning:
            message['reasoning'] = ''.join(reasoning)
        if tools:
            message['tool_calls'] = [
                {'id': slot['id'], 'type': slot['type'], 'function': slot['function'],
                 'index': index}
                for index, slot in sorted(tools.items())]
        envelope = {'model': model,
                    'choices': [{'message': message, 'finish_reason': finish}],
                    'usage': usage if usage is not None else {}}
        if native is not None:
            envelope['timings'] = native
        if frame_error is not None:
            envelope['error'] = frame_error
    recon.update(envelope=envelope, chunk_count=len(frames), complete=complete,
                 finish_reason=finish, usage=usage, native_timings=native,
                 has_content_delta=has_content, has_reasoning_delta=has_reasoning,
                 has_tool_delta=has_tool)
    return recon


# ---------------------------------------------------------------------------
# One HTTP exchange with standardized timings (never mixed into scoring)


def _http_exchange(profile, body, timeout_seconds):
    started_at = now()
    started_clock = time.monotonic()
    streaming = bool(body.get('stream'))
    raw = bytearray()
    streamed = bytearray()
    status = None
    response_headers = {}
    timed_out = False
    error = None
    first_byte = None
    ttft = None
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    outer_deadline = started_clock + previous_timer[0] if previous_timer[0] else None
    deadline = started_clock + max(0.0, timeout_seconds)
    if outer_deadline is not None:
        deadline = min(deadline, outer_deadline)

    def deadline_expired(signum, frame):
        if outer_deadline is not None and time.monotonic() >= outer_deadline:
            if callable(previous_alarm):
                previous_alarm(signum, frame)
        raise TimeoutError('client wall-clock deadline exhausted')

    previous_alarm = signal.signal(signal.SIGALRM, deadline_expired)
    signal.setitimer(signal.ITIMER_REAL, max(1e-6, deadline - time.monotonic()))
    try:
        if time.monotonic() >= deadline:
            deadline_expired(signal.SIGALRM, None)
        request = Request(profile['runtime']['serve']['endpoint'].rstrip('/') + '/chat/completions',
                          data=policy.canonical(body) + b'\n',
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            response = preflight.open_request(request, max(1e-6, deadline - time.monotonic()))
        except HTTPError as exc:
            response = exc
            error = f'HTTP {exc.code}'
        with response:
            status = response.status
            response_headers = dict(response.headers.items())
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('client deadline exhausted')
                chunk = response.read1(65536)
                if not chunk:
                    break
                if first_byte is None:
                    first_byte = time.monotonic() - started_clock
                if streaming:
                    streamed.extend(chunk)
                    recon = reconstruct_response(bytes(streamed), streaming=True)
                    if ttft is None and (recon['has_content_delta']
                                         or recon['has_reasoning_delta']
                                         or recon['has_tool_delta']):
                        ttft = time.monotonic() - started_clock
                raw.extend(chunk)
        if time.monotonic() >= deadline:
            deadline_expired(signal.SIGALRM, None)
    except (TimeoutError, socket.timeout) as exc:
        timed_out = True
        error = f'client deadline: {exc}'
    except URLError as exc:
        timed_out = isinstance(exc.reason, TimeoutError)
        error = f'client deadline: {exc}' if timed_out else f'transport: {exc}'
    except OSError as exc:
        error = f'transport: {exc}'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        if outer_deadline is not None:
            remaining = outer_deadline - time.monotonic()
            if previous_timer[1] and remaining <= 0:
                remaining %= previous_timer[1]
            signal.setitimer(signal.ITIMER_REAL, max(0.0, remaining), previous_timer[1])
    return {'started_at': started_at, 'raw': bytes(raw), 'status': status,
            'headers': response_headers, 'error': error, 'timed_out': timed_out,
            'streaming': streaming, 'first_byte_seconds': first_byte, 'ttft_seconds': ttft,
            'latency_seconds': time.monotonic() - started_clock}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _timings(exchange, usage, usage_source, native_timings=None):
    """Standardized timings, strictly separated from scoring.

    Throughput rates come ONLY from the serving stack's native envelope
    ``timings`` block (``prompt_per_second``/``predicted_per_second``),
    preserved verbatim under ``native_timings``; they are UNKNOWN when the
    server does not report them. Token counts divided by wall-clock latency
    are never presented as server throughput. Cache observation is the
    native ``cache_n``/``prompt_n`` pair when actually reported, else
    UNKNOWN — repeating a request is never treated as proof of cache state.
    """
    native = native_timings if isinstance(native_timings, dict) else None

    def rate(field):
        value = native.get(field) if native else None
        return value if _is_number(value) else UNKNOWN

    cache_state = UNKNOWN
    if native is not None and ('cache_n' in native or 'prompt_n' in native):
        cache_state = {'cache_n': native.get('cache_n'), 'prompt_n': native.get('prompt_n')}
    return {'streaming': exchange['streaming'],
            'ttft_seconds': (exchange['ttft_seconds'] if exchange['streaming']
                             and exchange['ttft_seconds'] is not None else UNKNOWN),
            'first_byte_seconds': (exchange['first_byte_seconds']
                                   if exchange['first_byte_seconds'] is not None else UNKNOWN),
            'latency_seconds': exchange['latency_seconds'], 'usage': usage,
            'usage_source': usage_source,
            'tokens_per_second': {'prompt': rate('prompt_per_second'),
                                  'generation': rate('predicted_per_second')},
            'native_timings': native, 'cache_state': cache_state}


def _usage_source(exchange, usage):
    if exchange['streaming']:
        return 'sse_usage_frame' if usage else 'UNAVAILABLE'
    return 'envelope' if usage else 'UNAVAILABLE'


# ---------------------------------------------------------------------------
# Prepared-task helpers (M2)


def _followups(prepared):
    ups = []
    for item in prepared.get('followups') or []:
        if isinstance(item, str):
            item = {'role': 'user', 'content': item}
        if (not isinstance(item, dict) or item.get('role') != 'user'
                or not isinstance(item.get('content'), str)):
            raise policy.CheckError(
                f"unit {prepared.get('id')}: followups must be user messages")
        ups.append({'role': 'user', 'content': item['content']})
    return ups


def _repetitions(prepared):
    value = prepared.get('repetitions', 1)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise policy.CheckError(
            f"unit {prepared.get('id')}: repetitions must be an integer >= 1")
    return value


def _reject_preloaded_answers(prepared):
    """A prior model turn is always the attempt's ACTUAL recorded response;
    preparation may never preload an assistant message as if the model said it."""
    for message in prepared.get('messages') or []:
        if isinstance(message, dict) and message.get('role') == 'assistant':
            raise policy.CheckError(
                f"unit {prepared.get('id')}: prepared messages preload an assistant "
                'turn; multi-turn correction must use the actual recorded model turn')


def _assistant_message(envelope):
    """Verbatim assistant message dict from one response envelope, or None."""
    if not isinstance(envelope, dict):
        return None
    choices = envelope.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get('message')
    if not isinstance(message, dict) or message.get('role') != 'assistant':
        return None
    return message


def _message_tool_calls(message):
    calls = message.get('tool_calls')
    return calls if isinstance(calls, list) and calls else []


def _tool_content(result):
    """Exact tool-message content shown to the model; offline replay derives
    identical bytes from the recorded result."""
    return json.dumps(result, sort_keys=True, separators=(',', ':'))


def _tool_executor(prepared=None):
    """The task's frozen simulator entry point: the dotted path declared in
    ``simulator.executor`` (hash-bound fixture content; recovery tasks declare
    the pinned recovery simulator), or the pinned recovery simulator when no
    path is declared. A declared path outside the pinned science modules, or
    an unavailable entry point, resolves to None — an integration defect,
    never model evidence."""
    declared = ((prepared or {}).get('simulator') or {}).get('executor')
    if not declared:
        try:
            from .scorers.realwork import execute_tool
        except ImportError:
            return None
        return execute_tool
    module_name, _, attribute = str(declared).rpartition('.')
    if not module_name.startswith('welp_next.scorers.'):
        return None
    try:
        import importlib
        return getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError):
        return None


def _parse_tool_call(call):
    """The ONE tool-call derivation, used identically by the live loop and
    offline replay: (function name, parsed arguments) from the raw assistant
    call. Unparseable argument payloads pass through unchanged so the
    executor classifies them."""
    function = (call.get('function') or {}) if isinstance(call, dict) else {}
    name = function.get('name')
    raw_arguments = function.get('arguments')
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except ValueError:
        arguments = raw_arguments  # the executor classifies malformed payloads
    return name, arguments


def _tool_bound(prepared):
    """The frozen per-attempt simulator call bound (never above
    MAX_TOOL_CALLS); enforced per call inside every returned batch."""
    value = prepared.get('max_calls', MAX_TOOL_CALLS)
    if not isinstance(value, int) or isinstance(value, bool):
        value = MAX_TOOL_CALLS
    return min(value, MAX_TOOL_CALLS)


def _run_tool(execute_tool_fn, call, state):
    """Advance the frozen simulator by one model call with THREADED state.

    Returns (result, arguments, name, new_state). ``result`` None means the
    executor itself failed to advance (integration defect -> INVALID).
    Executor error results (malformed arguments, unknown tool, transient
    failure) are genuine task behavior: they are shown to the model verbatim
    and judged by the scorer, never converted to infrastructure INVALID.
    """
    name, arguments = _parse_tool_call(call)
    try:
        result, state = execute_tool_fn({'tool': name, 'arguments': arguments}, state)
        return result, arguments, name, state
    except Exception:
        return None, arguments, name, state


def _sandbox_record(prepared, envelope, budget):
    """Sandbox execution for sandbox-requiring tasks. Frozen contract:
    welp_next.sandbox.execute_probe(check, submission_text, *, timeout_seconds);
    the submission is the FULL final assistant message content and extraction
    happens inside the sandbox module, so offline replay re-derives identical
    extraction bytes purely. Returns (record, submission_sha256|None). The
    record is durable observed executor evidence (sandbox-execution.json);
    it never re-executes during report replay. An unavailable boundary is an
    explicit available:false record (INVALID/EXECUTION_FAILURE in scoring),
    never a model FAIL and never a synthesized verdict."""
    message = _assistant_message(envelope)
    submission = message.get('content') if message else None
    sha = (hashlib.sha256(submission.encode('utf-8')).hexdigest()
           if isinstance(submission, str) and submission.strip() else None)
    if sha is None:
        return {'available': False, 'executed': False,
                'reason': 'no model submission to execute'}, None
    try:
        from . import sandbox
    except ImportError:
        return {'available': False, 'executed': False,
                'reason': 'sandbox module unavailable'}, sha
    try:
        return sandbox.execute_probe(prepared.get('check') or {}, submission,
                                     timeout_seconds=budget['timeout_seconds']), sha
    except Exception as exc:
        return {'available': False, 'executed': False,
                'reason': f'sandbox execution failed: {exc}'}, sha


# ---------------------------------------------------------------------------
# Attempt execution


def _repeat_summary(conditions, index, kind):
    """One per-exchange summary derived ONLY from the recorded conditions.

    The live loop and offline replay build the identical summary from the
    same conditions record, so the science's ``repeat_conditions`` extras
    aggregate every prior timeout/transport flag without producer/replay
    divergence."""
    timings = conditions.get('timings') or {}
    return {'exchange': index, 'kind': kind,
            'latency_seconds': conditions.get('elapsed_seconds'),
            'ttft_seconds': timings.get('ttft_seconds'), 'usage': timings.get('usage'),
            'tokens_per_second': timings.get('tokens_per_second'),
            'http_status': conditions.get('http_status'),
            'transport_error': conditions.get('transport_error'),
            'client_deadline_exhausted': conditions.get('client_deadline_exhausted'),
            'cache_state': timings.get('cache_state')}




def _prepare_failure(profile, task, path, revision, admission, budget, exc):
    """Preserve bounded setup failure without inventing a model observation."""
    reason = f'preparation unavailable: {exc}'
    store.put_json(path / 'preparation.json', {
        'unit_id': task['id'], 'attempt_id': path.name, 'profile_revision': revision,
        'prepared_task': task,
        'construction_evidence': {'prepared': False, 'reason': reason},
        'prepared_sha256': policy.digest(task)})
    store.put_json(path / 'request.json', request_body(profile, task))
    store.put(path / 'response.raw', b'')
    conditions = {'started_at': now(), 'ended_at': now(), 'elapsed_seconds': None,
                  'profile': profile, 'profile_id': profile['profile_id'], 'profile_revision': revision,
                  'evidence_kind': profile['evidence_kind'], 'preflight': admission,
                  'request_limits': budget, 'request_sent': False,
                  'preparation_error': reason, 'http_status': None, 'http_headers': {},
                  'transport_error': None, 'client_deadline_exhausted': False,
                  'fatal_device_condition': False, 'timings': None}
    store.put_json(path / 'conditions.json', conditions)
    score = scoring.invalid_score(reason)
    score.update(unit_id=task['id'], attempt_id=path.name, profile_revision=revision,
                 profile_id=profile['profile_id'], evidence_kind=profile['evidence_kind'])
    store.finalize_attempt(path, score, methodology=policy.METHODOLOGY_M2)
    return False


def execute(profile, task, path, revision, admission):
    m2 = policy.is_m2(profile)
    started = now()
    budget = policy.task_budget(profile, task)
    store.put_json(path / 'started.json', {'started_at': started, 'unit_id': task['id'],
                   'attempt_id': path.name, 'profile_revision': revision})
    prepared, evidence = task, None
    followups, repetitions, tools, streaming = [], 1, False, False
    if m2:
        try:
            from . import baseline
            prepared, evidence = baseline.prepare_task(profile, task)
            baseline.validate_preparation(profile, task, prepared, evidence)
            _reject_preloaded_answers(prepared)
            followups = _followups(prepared)
            repetitions = _repetitions(prepared)
            tools = bool(prepared.get('tools'))
            streaming = wants_streaming(profile, prepared)
            if streaming and followups:
                raise policy.CheckError(
                    f"unit {task['id']}: streaming with followups is not a supported unit shape")
            if tools and (followups or repetitions > 1 or streaming):
                raise policy.CheckError(
                    f"unit {task['id']}: the tool simulator loop is single-shot and non-streaming")
            if repetitions > 1 and followups:
                raise policy.CheckError(
                    f"unit {task['id']}: repetitions with followups is not a supported unit shape")
        except Exception as exc:  # bounded INVALID with the named reason; no POST
            return _prepare_failure(profile, task, path, revision, admission, budget, exc)
        # Saved BEFORE the request so the scored context is reconstructable
        # even if the machine dies mid-request.
        store.put_json(path / 'preparation.json', {
            'unit_id': task['id'], 'attempt_id': path.name, 'profile_revision': revision,
            'prepared_task': prepared, 'construction_evidence': evidence,
            'prepared_sha256': policy.digest(prepared)})
    tool_bound = _tool_bound(prepared)
    executor = _tool_executor(prepared) if tools else None
    executor_state = None
    phase = 'repeat' if repetitions > 1 else 'turn'
    messages = list(prepared['messages'])
    attempt_started = now()
    exchange_summaries = []
    repeat_records = []
    tool_events = []
    tool_failure = None
    protocol_error = None
    budget_exhausted = False
    unexecuted_requests = []
    calls_used = 0
    step = 0
    final = None
    observation.capture(profile, task, path, 'before')
    while True:
        step += 1
        body = request_body(profile, {**prepared, 'messages': messages})
        store.generation_intent(path, body)
        exchange = _http_exchange(profile, body, budget['timeout_seconds'])
        recon = reconstruct_response(exchange['raw'], streaming=exchange['streaming'])
        envelope = recon['envelope']
        usage = recon['usage']
        timings = _timings(exchange, usage, _usage_source(exchange, usage),
                           recon.get('native_timings'))
        turn_conditions = {
            'started_at': exchange['started_at'], 'ended_at': now(),
            'elapsed_seconds': exchange['latency_seconds'],
            'unit_id': task['id'], 'attempt_id': path.name, 'exchange': step,
            'http_status': exchange['status'], 'transport_error': exchange['error'],
            'client_deadline_exhausted': exchange['timed_out'], 'timings': timings}
        assistant = _assistant_message(envelope)
        if followups:
            more = step <= len(followups) and assistant is not None
        elif repetitions > 1:
            more = step < repetitions
        elif tools:
            asked = assistant is not None and bool(_message_tool_calls(assistant))
            if asked and executor is None:
                tool_failure = ('frozen tool simulator unavailable: '
                                'scorers.realwork.execute_tool missing')
            more = bool(asked and executor is not None and calls_used < tool_bound)
        else:
            more = False
        fatal_stop = _fatal_condition(exchange['raw'], exchange['error'], envelope)
        if fatal_stop:
            # An immediate fatal device/host condition (HTTP error text or an
            # HTTP-200 error envelope, including a preserved SSE error frame)
            # ends the attempt before any later repeat or followup; the
            # finalized HOST invalid plus the section safety stop persist it.
            more = False
        if repetitions > 1:
            repeat_records.append({'repeat': step, 'envelope': envelope,
                                   'raw_sha256': recon['raw_sha256'], 'timings': timings})
        if tools and assistant is not None and executor is not None and not fatal_stop:
            # Advance the frozen simulator BEFORE any evidence file is named:
            # an executor defect, a native-protocol violation, or the frozen
            # call bound terminates the attempt HERE, and a terminal exchange
            # must be committed under the root names with its exact original
            # bytes — never only under a turn-NN prefix.
            batch = _message_tool_calls(assistant)
            messages = messages + [assistant]
            executed = 0
            for call in batch:
                call_id = call.get('id') if isinstance(call, dict) else None
                if not isinstance(call, dict) or not isinstance(call_id, str) or not call_id:
                    # The model broke the native protocol: a valid task
                    # failure (the scorer judges the incomplete transcript),
                    # not INVALID.
                    protocol_error = 'tool_call missing native id'
                    break
                if calls_used >= tool_bound:
                    # The frozen bound is enforced PER CALL inside each
                    # returned batch: excess requested calls are retained as
                    # requested-but-never-executed evidence and no simulator
                    # action is ever fabricated for them.
                    budget_exhausted = True
                    break
                result, arguments, name, executor_state = _run_tool(executor, call, executor_state)
                if result is None:
                    tool_failure = 'frozen tool simulator unavailable or failed to advance'
                    break
                message = {'role': 'tool', 'tool_call_id': call_id,
                           'content': _tool_content(result)}
                tool_events.append({'tool': name, 'arguments': arguments,
                                    'result': result, 'tool_call_id': call_id,
                                    'message': message})
                messages.append(message)
                calls_used += 1
                executed += 1
            unexecuted_requests = [
                {'tool_call_id': (call.get('id') if isinstance(call, dict) else None),
                 'tool': _parse_tool_call(call)[0]} for call in batch[executed:]]
            if protocol_error or budget_exhausted or tool_failure:
                more = False
        prefix = f'{phase}-{step:02d}-' if more else ''
        store.put_json(path / (prefix + 'request.json'), body)
        # SIGINT intentionally leaves an uncommitted attempt, never a fabricated response.
        store.put(path / (prefix + 'response.raw'), exchange['raw'])
        if exchange['streaming']:
            store.put_json(path / (prefix + 'reconstruction.json'), recon)
        if more:
            # Auxiliary per-exchange conditions only; the final exchange's
            # richer record is the attempt-level conditions.json written once,
            # after scoring, below.
            store.put_json(path / (prefix + 'conditions.json'), turn_conditions)
        exchange_summaries.append(_repeat_summary(turn_conditions, step, phase))
        if not more:
            final = (body, exchange, recon, timings, usage)
            break
        # Advance the actual conversation for the next exchange.
        if followups:
            messages = messages + [assistant, followups[step - 1]]
        elif repetitions > 1:
            pass  # identical rendered request; a genuinely independent response

    body, exchange, recon, timings, usage = final
    observation.capture(profile, task, path, 'after')
    scored = recon['envelope']
    if m2 and tools:
        scored = {**(scored if isinstance(scored, dict) else {}),
                  'tool_events': [{'tool': event['tool'], 'arguments': event['arguments'],
                                   'result': event['result']} for event in tool_events]}
        receipt = {'unit_id': task['id'], 'attempt_id': path.name,
                   'profile_revision': revision, 'events': tool_events}
        if protocol_error:
            receipt['protocol_error'] = protocol_error
        if budget_exhausted:
            receipt['budget_exhausted'] = True
        if unexecuted_requests:
            receipt['unexecuted_requests'] = unexecuted_requests
        store.put_json(path / 'tool-events.json', receipt)
    if m2 and 'sandbox' in (prepared.get('requires') or []):
        record, submission_sha = _sandbox_record(prepared, recon['envelope'], budget)
        scored = {**(scored if isinstance(scored, dict) else {}), 'sandbox_execution': record}
        store.put_json(path / 'sandbox-execution.json', {
            'unit_id': task['id'], 'attempt_id': path.name, 'profile_revision': revision,
            'check': prepared.get('check') or {}, 'submission_sha256': submission_sha,
            'record': record})
    if m2 and repetitions > 1:
        scored = {**(scored if isinstance(scored, dict) else {}),
                  'repeats': [record['envelope'] for record in repeat_records],
                  'repeat_conditions': exchange_summaries}
        store.put_json(path / 'repetitions.json', {
            'unit_id': task['id'], 'attempt_id': path.name, 'profile_revision': revision,
            'repetitions': repetitions, 'repeats': repeat_records})
    conditions = {'started_at': exchange['started_at'], 'ended_at': now(),
                  'elapsed_seconds': exchange['latency_seconds'],
                  'profile': profile, 'profile_id': profile['profile_id'], 'profile_revision': revision,
                  'evidence_kind': profile['evidence_kind'],
                  'preflight': admission, 'request_limits': budget,
                  'http_status': exchange['status'], 'http_headers': exchange['headers'],
                  'transport_error': exchange['error'], 'client_deadline_exhausted': exchange['timed_out'],
                  'fatal_device_condition': False, 'timings': timings}
    if tool_failure:
        # Genuine simulator integration defect: INVALID, never a model outcome.
        conditions['tool_integration_error'] = f'tool simulator: {tool_failure}'
        score = scoring.invalid_score(conditions['tool_integration_error'])
        fatal = False
    else:
        score, fatal = assess_response(task, exchange['raw'], error=exchange['error'],
                                       timed_out=exchange['timed_out'], m2=m2, envelope=scored)
    conditions['fatal_device_condition'] = fatal
    if m2:
        conditions['attempt_started_at'] = attempt_started
        if step > 1:
            conditions['exchanges'] = exchange_summaries
    store.put_json(path / 'conditions.json', conditions)
    score.update(unit_id=task['id'], attempt_id=path.name, profile_revision=revision,
                 profile_id=profile['profile_id'], evidence_kind=profile['evidence_kind'])
    store.finalize_attempt(path, score, methodology=policy.METHODOLOGY_M2 if m2 else None)
    return fatal


# ---------------------------------------------------------------------------
# Offline replay (report authority: original bytes only, never score.json)


def _read_raw(path):
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise policy.CheckError(f'replay.evidence.{Path(path).name}: {exc}') from exc


def attempt_exchanges(path, phase):
    """Ordered per-exchange ORIGINAL evidence for one attempt.

    Non-final exchanges live under ``<phase>-NN-`` prefixes; the final
    exchange is stored under the root file names (a single-exchange attempt
    has root files only). Any missing auxiliary raises."""
    path = Path(path)
    numbers = []
    index = 1
    while (path / f'{phase}-{index:02d}-request.json').exists():
        numbers.append((index, False))
        index += 1
    numbers.append((index, True))
    exchanges = []
    for number, final in numbers:
        prefix = '' if final else f'{phase}-{number:02d}-'
        exchanges.append({'index': number, 'final': final, 'prefix': prefix,
                          'request': store.read_json(path / (prefix + 'request.json')),
                          'raw': _read_raw(path / (prefix + 'response.raw')),
                          'conditions': store.read_json(path / (prefix + 'conditions.json'))})
    return exchanges


def conversation_messages(prepared, envelopes):
    """Pure expected request message chains for a followups conversation.

    Chain 1 is the prepared messages; every later chain appends the ACTUAL
    assistant turn reconstructed from the previous exchange's original bytes
    followed by the pinned user followup. Prepared assistant turns are
    rejected upstream; an exchange that produced no assistant turn cannot
    continue the conversation."""
    followups = _followups(prepared)
    chains = []
    messages = [dict(message) for message in prepared['messages']]
    for index, envelope in enumerate(envelopes):
        chains.append([dict(message) for message in messages])
        if index == len(envelopes) - 1:
            break
        assistant = _assistant_message(envelope)
        if assistant is None:
            raise policy.CheckError(
                f"unit {prepared.get('id')}: exchange {index + 1} has no actual "
                'assistant turn to continue the conversation from')
        messages = messages + [assistant, followups[index]]
    return chains


def _validate_tool_events(profile, task, prepared, exchanges, recons, receipt):
    """Replay the frozen simulator over the calls the RAW assistant messages
    actually requested and verify the record against the ACTUAL conversation
    chain.

    Every event carries exactly tool/arguments/result/tool_call_id/message;
    the tool name and parsed arguments are DERIVED from each raw
    assistant.function call with the live parser (_parse_tool_call) and must
    equal the event, and each recorded result must equal a threaded-state
    executor replay of those derived values — a receipt can never credit a
    call the model never requested. Each tool message must be exactly what
    entered the following request; every non-final exchange's requested
    calls are covered in order; every exchange's request must equal the full
    pinned render request_body(profile, prepared-with-chain). Requested
    calls left unexecuted at the terminal exchange must match the receipt's
    retained excess-request evidence (bound exhaustion or native protocol
    violation), never a fabricated action. Returns the plain
    {tool, arguments, result} list the scoring dispatch consumes. A missing
    simulator is a validation failure (CheckError), never a pass."""
    execute_tool = _tool_executor(prepared)
    if execute_tool is None:
        raise policy.CheckError(
            f'replay.tools: the frozen simulator for {task["id"]} is unavailable')
    events = receipt.get('events')
    if not isinstance(events, list):
        raise policy.CheckError(f'replay.tools: events of {task["id"]} missing')
    if len(events) > MAX_TOOL_CALLS:
        raise policy.CheckError(f'replay.tools: {task["id"]} exceeds the frozen call bound')
    protocol_error = receipt.get('protocol_error')
    if protocol_error is not None and not (isinstance(protocol_error, str) and protocol_error):
        raise policy.CheckError(f'replay.tools: protocol_error of {task["id"]} malformed')
    budget_exhausted = receipt.get('budget_exhausted')
    if budget_exhausted is not None and budget_exhausted is not True:
        raise policy.CheckError(f'replay.tools: budget_exhausted of {task["id"]} malformed')
    excess = receipt.get('unexecuted_requests')
    if excess is not None and not isinstance(excess, list):
        raise policy.CheckError(f'replay.tools: unexecuted_requests of {task["id"]} malformed')
    messages = [dict(message) for message in prepared['messages']]
    state = None
    replayed = []
    index = 0
    final_calls = []
    for exchange, recon in zip(exchanges, recons):
        if exchange['request'].get('messages') != messages:
            raise policy.CheckError(
                f'replay.conversation: tool exchange {exchange["index"]} of {task["id"]} '
                'does not follow the actual recorded chain')
        if exchange['request'] != request_body(profile, {**prepared, 'messages': messages}):
            raise policy.CheckError(
                f'replay.request: tool exchange {exchange["index"]} of {task["id"]} does not '
                'match the pinned profile/task render '
                '(model/max_tokens/sampling/reasoning/tools/stream)')
        assistant = _assistant_message(recon['envelope'])
        calls = _message_tool_calls(assistant) if assistant is not None else []
        if exchange['final']:
            final_calls = calls
            break
        if assistant is None:
            raise policy.CheckError(
                f'replay.tools: exchange {exchange["index"]} of {task["id"]} '
                'has no assistant turn')
        messages = messages + [assistant]
        for call in calls:
            if index >= len(events):
                raise policy.CheckError(
                    f'replay.tools: requested call without a recorded event in {task["id"]}')
            event = events[index]
            call_id = call.get('id') if isinstance(call, dict) else None
            name, arguments = _parse_tool_call(call)
            if (not isinstance(event, dict)
                    or set(event) != {'tool', 'arguments', 'result', 'tool_call_id', 'message'}
                    or event.get('tool_call_id') != call_id
                    or event.get('tool') != name
                    or event.get('arguments') != arguments
                    or event.get('message') != {'role': 'tool', 'tool_call_id': call_id,
                                                'content': _tool_content(event.get('result'))}):
                raise policy.CheckError(
                    f'replay.tools: event {index} of {task["id"]} is not the executor '
                    'response to the raw recorded function call')
            result, state = execute_tool({'tool': name, 'arguments': arguments}, state)
            if result != event['result']:
                raise policy.CheckError(
                    f'replay.tools: recorded result {index} of {task["id"]} does not '
                    'match the frozen executor')
            messages.append(event['message'])
            replayed.append({'tool': name, 'arguments': arguments, 'result': event['result']})
            index += 1
    # Events attributed to the terminal exchange: the batch the producer was
    # advancing when the attempt ended. Everything beyond them was requested
    # but never executed, and must be exactly the retained excess evidence.
    executed_final = len(events) - index
    tail = final_calls[executed_final:] if 0 <= executed_final <= len(final_calls) else None
    if tail is None or index > len(events):
        raise policy.CheckError(
            f'replay.tools: {task["id"]} records events outside the recorded chain')
    if tail:
        if protocol_error is None and budget_exhausted is not True:
            raise policy.CheckError(
                f'replay.tools: {task["id"]} ends with requested calls but no retained '
                'terminal evidence')
        if not isinstance(excess, list) or len(excess) != len(tail):
            raise policy.CheckError(
                f'replay.tools: unexecuted requests of {task["id"]} do not match the raw calls')
        for call, entry in zip(tail, excess):
            call_id = call.get('id') if isinstance(call, dict) else None
            if (not isinstance(entry, dict) or entry.get('tool_call_id') != call_id
                    or entry.get('tool') != _parse_tool_call(call)[0]):
                raise policy.CheckError(
                    f'replay.tools: unexecuted request binding of {task["id"]} mismatched')
        if protocol_error is not None:
            first_id = tail[0].get('id') if isinstance(tail[0], dict) else None
            if isinstance(first_id, str) and first_id:
                raise policy.CheckError(
                    f'replay.tools: protocol_error of {task["id"]} without a malformed raw call')
        if budget_exhausted is True and len(events) != _tool_bound(prepared):
            raise policy.CheckError(
                f'replay.tools: budget_exhausted of {task["id"]} without the frozen bound reached')
    else:
        if protocol_error is not None or budget_exhausted is True:
            raise policy.CheckError(
                f'replay.tools: terminal evidence of {task["id"]} without unexecuted calls')
        if excess:
            raise policy.CheckError(
                f'replay.tools: unexecuted requests of {task["id"]} without requested calls')
    return replayed


def _validate_sandbox_record(prepared, recon, saved):
    """Validate the saved sandbox executor record against the ORIGINAL final
    response. Never re-executes anything: the recorded executor output is the
    trusted observation; only pure identities (check block, submission digest,
    deterministic extraction, verdict usability) are re-derived here."""
    from . import sandbox
    if saved.get('check') != (prepared.get('check') or {}):
        raise policy.CheckError('replay.sandbox: check identity mismatch')
    record = saved.get('record')
    if not isinstance(record, dict):
        raise policy.CheckError('replay.sandbox: executor record missing')
    message = _assistant_message(recon['envelope'])
    submission = message.get('content') if message else None
    expected_sha = (hashlib.sha256(submission.encode('utf-8')).hexdigest()
                    if isinstance(submission, str) and submission.strip() else None)
    if saved.get('submission_sha256') != expected_sha:
        raise policy.CheckError('replay.sandbox: submission digest mismatch')
    if record.get('extracted') is not None:
        if record['extracted'] != sandbox.extract_code(submission or ''):
            raise policy.CheckError('replay.sandbox: extraction identity mismatch')
    if record.get('executed') and sandbox.tests_pass(record) is None:
        raise policy.CheckError('replay.sandbox: executed record without a usable verdict')
    return record


def replay_attempt(profile, task, path):
    """Reconstruct one committed attempt's score from ORIGINAL evidence only.

    Reads preparation.json, per-exchange request/response.raw/conditions,
    reconstruction.json, repetitions.json, tool-events.json and
    sandbox-execution.json — never score.json or any producer outcome claim.
    Verifies the pinned streaming/transport attribution, observed timings
    against the raw native timing/usage (a measured TTFT stays within its
    exchange; UNKNOWN stays UNKNOWN), every exchange's FULL pinned request
    render, the multi-turn conversation (root follows the actual prior
    answers and followups), every repeat against its original
    bytes/timings, the threaded frozen simulator replay bound to the raw
    function calls, and the sandbox executor record identities; then re-runs
    the shared scoring dispatch. A shortened attempt is accepted only when
    its final exchange terminates the conversation the way the live loop
    does (fatal transport/envelope condition, or — for followups — no usable
    assistant turn). Returns (score, fatal); raises policy.CheckError on any
    missing or inconsistent auxiliary, so a missing auxiliary fails
    validation."""
    path = Path(path)
    m2 = policy.is_m2(profile)
    revision = policy.digest(profile)
    if m2:
        conditions = store.read_json(path / 'conditions.json')
        for name in observation.NAMES:
            observation.read_snapshot(profile, path, name)
        before_path = path / 'gpu-before.json'
        after_path = path / 'gpu-after.json'
        before_fatal = before_path.exists() and store.read_json(before_path).get('fatal')
        after_fatal = after_path.exists() and store.read_json(after_path).get('fatal')
        if conditions.get('preparation_error'):
            return scoring.invalid_score(conditions['preparation_error'], host=bool(before_fatal)), bool(before_fatal)
        if after_fatal:
            return scoring.invalid_score('post-request accelerator safety failure', host=True), True
        if conditions.get('tool_integration_error'):
            return scoring.invalid_score(conditions['tool_integration_error']), False
        saved = store.read_json(path / 'preparation.json')
        prepared = saved.get('prepared_task')
        if (not isinstance(prepared, dict) or saved.get('unit_id') != task['id']
                or saved.get('attempt_id') != path.name
                or saved.get('profile_revision') != revision
                or saved.get('prepared_sha256') != policy.digest(prepared)):
            raise policy.CheckError('replay.preparation: identity mismatch')
    else:
        prepared = task
    followups = _followups(prepared) if m2 else []
    repetitions = _repetitions(prepared) if m2 else 1
    tools = bool(prepared.get('tools')) if m2 else False
    sandbox_required = m2 and 'sandbox' in (prepared.get('requires') or [])
    streaming = m2 and wants_streaming(profile, prepared)
    if tools and (followups or repetitions > 1):
        raise policy.CheckError(
            f"unit {task['id']}: unsupported prepared shape (tools with followups/repeats)")
    if not tools:
        expected_count = repetitions if repetitions > 1 else len(followups) + 1
    else:
        expected_count = None  # the frozen protocol decides the exchange count
    phase = 'repeat' if repetitions > 1 else 'turn'
    exchanges = attempt_exchanges(path, phase)
    binding = {'unit_id': task['id'], 'attempt_id': path.name, 'profile_revision': revision}

    def check_binding(saved, label):
        if not isinstance(saved, dict) or any(saved.get(k) != v for k, v in binding.items()):
            raise policy.CheckError(f'replay.{label}: identity mismatch')

    recons = []
    for exchange in exchanges:
        if bool(exchange['request'].get('stream')) != streaming:
            raise policy.CheckError(
                f'replay.streaming: exchange {exchange["index"]} of {task["id"]} does '
                'not match the pinned streaming decision')
        timings = exchange['conditions'].get('timings')
        if not isinstance(timings, dict) or bool(timings.get('streaming')) != streaming:
            raise policy.CheckError(
                f'replay.timings: exchange {exchange["index"]} of {task["id"]} '
                'misattributes the transport mode')
        recon = reconstruct_response(exchange['raw'], streaming=streaming)
        if streaming:
            if store.read_json(path / (exchange['prefix'] + 'reconstruction.json')) != recon:
                raise policy.CheckError(
                    f'replay.reconstruction: exchange {exchange["index"]} of {task["id"]} '
                    'differs from the original SSE bytes')
        # The standardized timings record must be exactly what the ORIGINAL
        # bytes plus the client's wall-clock observations produce: everything
        # byte-derived (usage, usage source, native timings, throughput
        # rates, cache state) is recomputed here from the raw response;
        # wall-clock numbers are carried through and bounded — a measured
        # TTFT must be an actual streaming observation inside the exchange,
        # and UNKNOWN stays UNKNOWN (never zero, never rejected).
        rebuilt = _timings(
            {'streaming': streaming,
             'ttft_seconds': timings.get('ttft_seconds'),
             'first_byte_seconds': timings.get('first_byte_seconds'),
             'latency_seconds': timings.get('latency_seconds')},
            recon['usage'], _usage_source({'streaming': streaming}, recon['usage']),
            recon.get('native_timings'))
        if timings != rebuilt:
            raise policy.CheckError(
                f'replay.timings: exchange {exchange["index"]} of {task["id"]} does '
                'not match the original bytes/usage')
        latency = timings.get('latency_seconds')
        if not _is_number(latency) or latency < 0:
            raise policy.CheckError(
                f'replay.timings: exchange {exchange["index"]} of {task["id"]} has an '
                'unusable latency observation')
        first_byte = timings.get('first_byte_seconds')
        if first_byte != UNKNOWN and (
                not _is_number(first_byte) or first_byte < 0 or first_byte > latency):
            raise policy.CheckError(
                f'replay.timings: exchange {exchange["index"]} of {task["id"]} has a '
                'first-byte observation outside the exchange')
        ttft = timings.get('ttft_seconds')
        if ttft != UNKNOWN and (
                not _is_number(ttft) or ttft < 0 or ttft > latency
                or (_is_number(first_byte) and ttft < first_byte)):
            raise policy.CheckError(
                f'replay.timings: exchange {exchange["index"]} of {task["id"]} has a '
                'TTFT observation outside the exchange')
        recons.append(recon)

    root = exchanges[-1]
    scored = recons[-1]['envelope']
    extras = {}
    if expected_count is not None and len(exchanges) != expected_count:
        # A legitimately shortened attempt ends on an exchange the live loop
        # itself could not continue: a fatal transport/envelope condition is
        # the only early stop for repeats; followups also stop when the
        # exchange produced no usable assistant turn. A first-turn HTTP 500
        # or deadline therefore replays as the recorded budget/invalid
        # outcome instead of failing every later report, while a
        # success-path attempt is still held to the pinned exchange count.
        stopped = _fatal_condition(root['raw'], root['conditions'].get('transport_error'),
                                   scored)
        legitimate = stopped or (bool(followups) and _assistant_message(scored) is None)
        if len(exchanges) > expected_count or not legitimate:
            raise policy.CheckError(
                f'replay.exchanges: unit {task["id"]} expected {expected_count} '
                f'exchanges, found {len(exchanges)} without a terminating exchange')
    if not tools:
        if followups:
            chains = conversation_messages(prepared, [recon['envelope'] for recon in recons])
        else:
            chains = [[dict(message) for message in prepared['messages']]
                      for _ in exchanges]
        for exchange, chain in zip(exchanges, chains):
            if exchange['request'].get('messages') != chain:
                raise policy.CheckError(
                    f'replay.conversation: exchange {exchange["index"]} of {task["id"]} '
                    'does not follow the actual prior answers and pinned followups')
            # EVERY actual exchange must equal the FULL pinned render, not
            # only its messages: model, max_tokens, samplers, reasoning
            # controls, native tool schemas and the stream decision are all
            # attributed to the pinned profile/task.
            if exchange['request'] != request_body(profile, {**prepared, 'messages': chain}):
                raise policy.CheckError(
                    f'replay.request: exchange {exchange["index"]} of {task["id"]} does not '
                    'match the pinned profile/task render '
                    '(model/max_tokens/sampling/reasoning/tools/stream)')
    if repetitions > 1:
        saved = store.read_json(path / 'repetitions.json')
        check_binding(saved, 'repetitions')
        repeats = saved.get('repeats')
        if (saved.get('repetitions') != repetitions or not isinstance(repeats, list)
                or len(repeats) != len(exchanges)):
            raise policy.CheckError(f'replay.repetitions: binding of {task["id"]} invalid')
        for exchange, recon, record in zip(exchanges, recons, repeats):
            expected = {'repeat': exchange['index'], 'envelope': recon['envelope'],
                        'raw_sha256': recon['raw_sha256'],
                        'timings': exchange['conditions']['timings']}
            if record != expected:
                raise policy.CheckError(
                    f'replay.repetitions: repeat {exchange["index"]} of {task["id"]} '
                    'differs from the original bytes/conditions')
        if any(exchange['request'] != root['request'] for exchange in exchanges[:-1]):
            raise policy.CheckError(
                f'replay.repetitions: repeated requests of {task["id"]} are not '
                'identical renders')
        extras['repeats'] = [record['envelope'] for record in repeats]
        extras['repeat_conditions'] = [_repeat_summary(exchange['conditions'],
                                                       exchange['index'], phase)
                                       for exchange in exchanges]
    if tools:
        receipt = store.read_json(path / 'tool-events.json')
        check_binding(receipt, 'tools')
        extras['tool_events'] = _validate_tool_events(profile, task, prepared,
                                                      exchanges, recons, receipt)
    if sandbox_required:
        saved = store.read_json(path / 'sandbox-execution.json')
        check_binding(saved, 'sandbox')
        extras['sandbox_execution'] = _validate_sandbox_record(prepared, recons[-1], saved)
    if extras:
        scored = {**(scored if isinstance(scored, dict) else {}), **extras}
    score, fatal = assess_response(
        task, root['raw'], error=root['conditions'].get('transport_error'),
        timed_out=bool(root['conditions'].get('client_deadline_exhausted')),
        m2=m2, envelope=scored)
    return score, fatal


# ---------------------------------------------------------------------------
# Section driver


def run(profile, part=None):
    policy.validate_profile(profile)
    resolved = resolve_part(profile, part)
    campaign = Path(profile['campaign_root'])
    section = store.section_path(campaign)
    if not (section / 'manifest.json').exists():
        plan(profile, resolved)  # reject bad routing/identity before creating even the writer lock
    with store.locked(campaign):
        if (section / 'manifest.json').exists():
            from .reporting import verify_manifest
            verify_manifest(section)
            saved = store.read_json(section / 'run.json')
            if not policy.compatible_profiles(saved['profile'], profile):
                raise policy.CheckError('recovery.profile_revision: finalized run uses another profile')
            return status(campaign)
        config = initialize(profile, section, resolved)
        _, units = store.inventory(section)
        if (section / 'safety-stop.json').exists() or policy.safety_stopped(units):
            raise policy.CheckError('safety.stop: no automatic retry; human safety review required')
        pending = [uid for uid, rows in units.items() if policy.unit_pending(rows)]
        if not pending:
            return status(campaign)
        store.check_preparation(section)
        try:
            admission = preflight.online(profile)
        except policy.CheckError as exc:
            failure = dict(getattr(exc, 'evidence', {}))
            failure.update(ok=False, error=str(exc), profile_revision=config['profile_revision'])
            store.record_admission(section, failure)
            raise
        store.record_admission(section, admission)
        preflight_dir = campaign / 'profile'
        revision = policy.digest(profile)
        profile_file = preflight_dir / (revision + '.json')
        if not profile_file.exists():
            store.put_json(profile_file, profile)
        store.put_json(preflight_dir / ('preflight-' + uuid.uuid4().hex + '.json'), admission)
        tasks = {t['id']: t for t in store.read_json(section / 'fixture.json')['tasks']}
        interruption = None
        stop_requested = False

        def interrupt(signum, frame):
            nonlocal stop_requested
            if stop_requested:
                raise KeyboardInterrupt
            stop_requested = True

        previous_handler = signal.signal(signal.SIGINT, interrupt)
        try:
            for uid in pending:
                # Retry only INVALID, never valid FAIL or valid budget-limited output.
                while policy.unit_pending(store.attempts(section, uid)):
                    if stop_requested:
                        interruption = 'SIGINT'
                        break
                    path = store.new_attempt(section, uid, preparing=True)
                    store.append_event(section, {'event': 'PREPARING', 'unit_id': uid,
                                      'attempt_id': path.name, 'at': now()})
                    fatal = execute(profile, tasks[uid], path, revision, admission)
                    setup_failed = store.preparation_only(path)
                    store.append_event(section, {'event': 'PREPARATION_FAILED' if setup_failed else 'FINALIZED',
                                      'unit_id': uid, 'attempt_id': path.name, 'at': now()})
                    if setup_failed:
                        interruption = 'preparation failure; no model trial consumed'
                        break
                    if fatal:
                        store.put_json(section / 'safety-stop.json',
                                       {'unit_id': uid, 'attempt_id': path.name, 'at': now()})
                        interruption = 'fatal accelerator condition'
                        break
                if interruption:
                    break
        except KeyboardInterrupt:
            interruption = 'SIGINT'
        finally:
            signal.signal(signal.SIGINT, previous_handler)
            if stop_requested and not interruption:
                interruption = 'SIGINT'
            if interruption:
                store.append_event(section, {'event': 'INTERRUPTED', 'reason': interruption, 'at': now()})
        result = status(campaign)
        if interruption:
            result['interruption'] = interruption
        return result


def _review_kind(score):
    """Review-demanding resolved units (parent reporting owns effective rows)."""
    record = score.get('record')
    if isinstance(record, dict):
        kind = record.get('review_required') or record.get('review_kind')
        if isinstance(kind, str) and kind:
            return kind
    if score.get('completion') == 'COMPLETE' and score.get('scoring') == 'NOT_SCOREABLE':
        return 'reviewed_safety_v1'
    return None


def _review_outstanding(judgments):
    """True while the bounded review history still owes a decision: no
    judgment yet, or a single ambiguous/disputed primary with the one
    allowed escalation still outstanding. A decided (PASS/FAIL) or
    bound-exhausted (two independent judgments) history is final and never
    pending; the scientific disposition itself stays in review.effective_scores."""
    if not isinstance(judgments, list):
        return True
    if len(judgments) >= 2:
        return False
    if not judgments:
        return True
    first = judgments[0] if isinstance(judgments[0], dict) else {}
    return (first.get('disposition') == 'NOT_EVALUABLE'
            or first.get('disputed') is True)


def status(campaign):
    section = store.section_path(campaign)
    if not (section / 'run.json').exists():
        return {'campaign': str(campaign), 'section': 'baseline', 'state': 'NOT_RUN',
                'units': [], 'remaining_units': [], 'finalizable': False}
    config, units = store.inventory(section)
    m2 = policy.is_m2(config['profile'])
    effective = {}
    if m2:
        from . import review
        effective = review.effective_scores(section, store.read_json(section / 'fixture.json'),
                                            units)
    records = []
    pending_reviews = []
    for uid, rows in units.items():
        resolved = policy.resolved_attempt(rows)
        record = {'unit_id': uid, 'profile_id': config['profile']['profile_id'],
                  'outcome': resolved['outcome'] if resolved else 'NOT_RUN',
                  'reason': resolved.get('reason') if resolved else 'not yet finalized',
                  'resolved_attempt': resolved['attempt_id'] if resolved else None,
                  'attempts': len(rows), 'pending': policy.unit_pending(rows)}
        if resolved is not None:
            kind = _review_kind(resolved)
            if m2:
                score = effective.get(uid)
                review_info = score.get('review') if isinstance(score, dict) else None
                if isinstance(review_info, dict):
                    # The M2 outcome is the effective review result; the
                    # original unreviewed outcome is retained alongside,
                    # never overwritten.
                    record['outcome'] = score.get('outcome', record['outcome'])
                    record['reason'] = score.get('reason', record['reason'])
                    record['original_outcome'] = review_info.get('original_outcome',
                                                                 record['outcome'])
                    judgments = review_info.get('judgments')
                    if kind and _review_outstanding(judgments):
                        pending_reviews.append({'unit_id': uid,
                                                'attempt_id': resolved['attempt_id'],
                                                'kind': kind})
                elif kind:
                    pending_reviews.append({'unit_id': uid,
                                            'attempt_id': resolved['attempt_id'],
                                            'kind': kind})
            elif kind:
                pending_reviews.append({'unit_id': uid, 'attempt_id': resolved['attempt_id'],
                                        'kind': kind})
        records.append(record)
    excluded = [{'unit_id': uid, 'profile_id': config['profile']['profile_id'],
                 'outcome': 'NOT_RUN', 'reason': reason, 'resolved_attempt': None,
                 'attempts': 0, 'pending': False, 'applicability_excluded': True}
                for uid, reason in sorted((config.get('excluded_units') or {}).items())]
    stopped = (section / 'safety-stop.json').exists() or policy.safety_stopped(units)
    admissions = store.admission_records(section)
    if config.get('admission_version') != policy.ADMISSION_VERSION and any(
            row.get('profile_revision') != config['profile_revision'] for row in admissions):
        raise policy.CheckError('evidence.admission: mixed profile revision')
    blocked = bool(admissions) and admissions[-1].get('ok') is False
    state = policy.section_state(units, interrupted=stopped, blocked=blocked)
    remaining = [row['unit_id'] for row in records if row['pending']]
    return {'campaign': str(campaign), 'section': 'baseline',
            'part': config.get('part', M1_PART), 'scope': config.get('scope', M1_SCOPE),
            'evidence_kind': config['profile']['evidence_kind'],
            'profile_id': config['profile']['profile_id'], 'profile_revision': config['profile_revision'],
            'state': state, 'units': records, 'excluded_units': excluded,
            'pending_reviews': pending_reviews, 'remaining_units': remaining,
            'preparation_failures': store.preparation_failures(section),
            'resumable': bool(remaining) and not stopped,
            'finalizable': state in ('COMPLETED', 'COMPLETED_PARTIAL'),
            'finalized': (section / 'manifest.json').exists()}
