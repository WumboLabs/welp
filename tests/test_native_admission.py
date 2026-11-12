"""Synthetic software regressions: native metadata attribution, no model inference.

Extended 2026-11-11 for user-authorized generic context-meter admission
(context-meter/1) and the required full-coverage precommitment:
- valid native llama.cpp admission (unchanged contract);
- qualified generic meters for a Strata-like engine AND a third runtime,
  verified against hashed ORIGINAL witness/geometry evidence files (never a
  JSON verdict alone), with retained-qualification offline checks plus fresh
  live admission (render/tokenize probe, native template identity, native
  context geometry);
- rejection of missing/fabricated evidence, wrong tokenizer/template identity
  and wrong context geometry;
- the explicit full requirement fails BEFORE the first scored request on any
  excluded identity or uncovered construction, while explicit partial
  precommitment stays possible without any approval workflow;
- historical compatibility: boolean capabilities and frozen profiles keep
  their exact recorded admission outcomes.
"""
import copy
import hashlib
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
from welp_next import baseline, policy, preflight, runner, scoring

TEMPLATE = 'NATIVE ENGINE CHAT TEMPLATE SOURCE v7'
CONTEXT_ANSWER = 'TR-8842-QX 412 388 TR-3319-WD 357'


def fake_render_prompt(template, controls, messages):
    """Deterministic model-native rendering; deliberately NOT a Qwen template
    and carrying no reasoning markup — admission must not force one."""
    rendered = ''.join(f"<{m.get('role')}>{m.get('content')}" for m in messages)
    return f'<template:{_sha_bytes(template.encode())[:8]}>{rendered}{controls}'


_TOKEN_WORD = __import__('re').compile(r"[A-Za-z0-9'-]+|[^A-Za-z0-9\s]")


def fake_tokenize_ids(content, add_special=True):
    """Deterministic word/punctuation-level ids (~1 token/word, the regime the
    pinned constructions are tuned in); unique per distinct token string."""
    ids = []
    for token in _TOKEN_WORD.findall(content or ''):
        ids.append(8 + int.from_bytes(
            hashlib.sha256(token.encode()).digest()[:4], 'big'))
    return ([7] if add_special else []) + ids


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


class NativeAdmission(unittest.TestCase):
    def setUp(self):
        self.work = support.make_workdir('native-admission')
        self.addCleanup(support.shutil.rmtree, self.work, True)
        self.profile = support.build_profile(self.work, 'http://127.0.0.1:18861', self.work/'campaign')
        p = self.profile
        p['runtime'].update(backend='HIP', engine={'name': 'llama.cpp', 'version': 'b11311-f7b384c1e',
                                                 'path': '/qualified/bin/llama-server', 'sha256': 'a'*64})
        command = '/qualified/bin/llama-server --jinja --reasoning on'
        p['runtime']['serve'].update(command=command, sha256=hashlib.sha256(command.encode()).hexdigest(),
                                     echo_path='/props', pid=123, model_id=p['model']['artifact']['path'])
        p['reasoning'] = {'arm': 'ON', 'controls': {'chat_template_kwargs': {'enable_thinking': True}}}
        p['profile_id'] = p['profile_id'].replace('-cuda-off-', '-hip-on-')
        template = (self.work/'chat-template.txt').read_text()
        self.observed = {
            'props': {'build_info': 'b11311-f7b384c1e', 'model_path': p['model']['artifact']['path'],
                      'chat_template': template, 'total_slots': 1,
                      'default_generation_settings': {'n_ctx': 8192,
                         'params': {'temperature': 0.20000000298023224, 'top_p': 0.949999988079071, 'seed': 42}}},
            'process': {'pid': 123, 'executable': '/qualified/bin/llama-server', 'executable_sha256': 'a'*64,
                        'argv': ['/qualified/bin/llama-server', '--jinja', '--reasoning', 'on'],
                        'listeners': [{'local_address': '0100007F:49AD', 'state': '0A'}],
                        'backend_libraries': ['/qualified/bin/libggml-hip.so.0.25.3']},
            'template_probe': {'request': {'messages': [{'role': 'user', 'content': 'WELP preflight template rendering only.'}],
                                          'chat_template_kwargs': {'enable_thinking': True}},
                               'response': {'prompt': '<|im_start|>assistant\n<think>\n'}}}
        self.observed['admission_version'] = policy.ADMISSION_VERSION
        self.observed['tokenizer_probe'] = {'tokens': [1, 2]}

    def test_float32_echo_tolerance_does_not_admit_sampler_or_seed_drift(self):
        self.assertEqual(policy.echo_defects(self.profile, self.observed), [])
        for key, changed in [('temperature', 0.2001), ('top_p', 0.9501), ('seed', 43), ('seed', 42.0)]:
            with self.subTest(key=key, changed=changed):
                observed = copy.deepcopy(self.observed)
                observed['props']['default_generation_settings']['params'][key] = changed
                with self.assertRaisesRegex(policy.CheckError, 'serve.native.sampling.'+key):
                    policy.validate_echo(self.profile, observed)

    def test_misattribution_and_reasoning_drift_are_rejected_offline(self):
        cases = [('props', 'model_path', '/other/model.gguf', 'model.identity'),
                 ('props', 'chat_template', 'different template', 'template.identity'),
                 ('props', 'default_generation_settings', {'n_ctx': 4096, 'params': {}}, 'context'),
                 ('template_probe', 'response', {'prompt': '<think>\n\n</think>\n\n'}, 'reasoning')]
        for section, key, changed, defect in cases:
            with self.subTest(defect=defect):
                observed = copy.deepcopy(self.observed)
                observed[section][key] = changed
                with self.assertRaisesRegex(policy.CheckError, 'serve.native.'+defect):
                    policy.validate_echo(self.profile, observed)

    def test_native_llama_route_admits_context_units_without_any_declaration(self):
        task = {'id': 'context-family-a-v2-3072-seed-42', 'requires': ['context_meter'],
                'category': 'context', 'context_checkpoint': 3072}
        self.assertEqual(policy.task_applicability(self.profile, task), (True, ''))
        # A declared meter is unnecessary and its absence is not a defect here.
        self.assertIsNone(policy.context_meter_declaration(self.profile))
        self.assertEqual(policy.meter_evidence_defects(self.profile), [])

    def test_supplied_backend_condition_is_not_an_admission_vocabulary(self):
        for backend in ('CPU', 'Metal', 'ROCm'):
            with self.subTest(backend=backend):
                profile = copy.deepcopy(self.profile)
                profile['runtime']['backend'] = backend
                policy.validate_profile(profile)
        for backend in ('', '   ', None, 7):
            with self.subTest(backend=backend):
                profile = copy.deepcopy(self.profile)
                profile['runtime']['backend'] = backend
                with self.assertRaisesRegex(policy.CheckError, 'runtime.backend'):
                    policy.validate_profile(profile)


# ---------------------------------------------------------------------------
# Generic qualified context meter (context-meter/1)


class MeterEndpoint:
    """Synthetic qualified meter: the two native metadata routes, an enforcing
    configuration echo with retained NATIVE props, and generation. Counts
    every request by route so tests can prove metadata-only phases."""

    def __init__(self, profile, *, template=TEMPLATE, capacity=None, broken_routes=()):
        self.profile = profile
        self.template = template
        self.capacity = capacity if capacity is not None else \
            profile['runtime']['context_capacity']
        self.broken_routes = set(broken_routes)
        self.counts = {}
        self.route_log = []
        self._lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        if self.httpd is None:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)
        self.httpd = None

    def url(self, path):
        return f'http://127.0.0.1:{self.port}/v1{path}'

    def _count(self, route):
        with self._lock:
            self.counts[route] = self.counts.get(route, 0) + 1
            self.route_log.append(route)

    def _send(self, handler, status, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Content-Length', str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def do_GET(self):
                path = self.path.rsplit('?', 1)[0]
                if path == '/v1/models':
                    outer._count('models')
                    return outer._send(self, 200, {'object': 'list', 'data': [
                        {'id': outer.profile['runtime']['serve']['model_id'], 'object': 'model'}]})
                if path == '/v1' + outer.profile['runtime']['serve']['echo_path']:
                    outer._count('echo')
                    return outer._send(self, 200, outer.configuration())
                outer._count('get:' + path)
                return outer._send(self, 404, {'error': 'not found'})

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}')
                if self.path == '/v1/apply-template':
                    outer._count('apply-template')
                    if 'apply-template' in outer.broken_routes:
                        return outer._send(self, 500, {'error': 'render unavailable'})
                    return outer._send(self, 200, {'prompt': outer.render(body)})
                if self.path == '/v1/tokenize':
                    outer._count('tokenize')
                    if 'tokenize' in outer.broken_routes:
                        return outer._send(self, 500, {'error': 'tokenize unavailable'})
                    return outer._send(self, 200, outer.tokenize(body))
                if self.path == '/v1/chat/completions':
                    outer._count('chat/completions')
                    if body.get('stream'):
                        frames = [
                            {'choices': [{'delta': {'role': 'assistant'}, 'index': 0}]},
                            {'choices': [{'delta': {'content': CONTEXT_ANSWER}, 'index': 0}]},
                            {'choices': [{'delta': {}, 'finish_reason': 'stop', 'index': 0}],
                             'usage': {'prompt_tokens': 10, 'completion_tokens': 8}},
                        ]
                        payload = b''.join(
                            b'data: ' + json.dumps(frame).encode() + b'\n\n'
                            for frame in frames) + b'data: [DONE]\n\n'
                        return outer._send(self, 200, payload)
                    return outer._send(self, 200, {
                        'choices': [{'message': {'role': 'assistant', 'content': CONTEXT_ANSWER},
                                     'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 10, 'completion_tokens': 8}})
                outer._count('post:' + self.path)
                return outer._send(self, 404, {'error': 'not found'})

        return Handler

    def render(self, body):
        controls = {k: v for k, v in body.items() if k in self.profile['reasoning']['controls']}
        messages = body.get('messages') or []
        return fake_render_prompt(self.template, controls, messages)

    def tokenize(self, body):
        return {'tokens': fake_tokenize_ids(body.get('content') or '',
                                            bool(body.get('add_special')))}

    def configuration(self):
        profile = self.profile
        return {
            'artifact_sha256': profile['model']['artifact']['sha256'],
            'engine': {'name': profile['runtime']['engine']['name'],
                       'version': profile['runtime']['engine']['version']},
            'sampling': policy.sampling_settings(profile),
            'reasoning': {'arm': profile['reasoning']['arm'],
                          'controls': profile['reasoning']['controls']},
            'context_capacity': self.capacity,
            'source': 'synthetic qualified meter; native props retained below',
            'native_props': {
                'model_alias': profile['runtime']['serve']['model_id'],
                'chat_template': self.template,
                'default_generation_settings': {'n_ctx': self.capacity, 'params': {}},
                'total_slots': 1,
            },
        }


class GenericMeterBase(unittest.TestCase):
    ENGINE = 'Strata'
    NATIVE_TOOLS = True

    def setUp(self):
        self.work = support.make_workdir(f"generic-meter-{self.ENGINE.lower()}")
        self.addCleanup(support.shutil.rmtree, self.work, True)
        self.campaign = (self.work / 'research/model-evaluations/synthetic-native/'
                         'campaign-groups/synthetic-meter-campaign')
        self.campaign.mkdir(parents=True)
        self.profile = self.build_real_profile(self.ENGINE)
        self.endpoint = MeterEndpoint(self.profile)
        self.addCleanup(self.endpoint.close)
        self.profile['runtime']['serve']['endpoint'] = self.endpoint.url('')
        self.write_evidence(self.ENGINE)
        self.apply_declaration()
        self.work_space = patch('welp_next.preflight.WORKSPACE_ROOT', Path(self.work))
        self.work_space.start()
        self.addCleanup(self.work_space.stop)

    # -- profile / evidence construction ------------------------------------

    def build_real_profile(self, engine, *, capacity=131072, requirement='full'):
        artifact = self.work / 'native-artifact.bin'
        artifact.write_bytes(b'native pack artifact\n')
        profile = {
            'schema_version': 1,
            'framework': {'version': policy.FRAMEWORK_M2, 'methodology': policy.METHODOLOGY_M2},
            'profile_id': f'synthetic-native-{engine.lower()}-meter-on-2026-11-11',
            'campaign_id': self.campaign.name,
            'campaign_root': str(self.campaign),
            'evidence_kind': 'REAL_MODEL',
            'model': {
                'model_key': 'synthetic-native',
                'artifact': {'path': str(artifact), 'format': 'native-pack', 'revision': 'r9',
                             'sha256': support.sha256_file(artifact)},
                'tokenizer_chat_template': {'source': 'engine native template',
                                            'sha256': _sha_bytes(TEMPLATE.encode())},
            },
            'runtime': {
                'engine': {'name': engine, 'version': '1.4.2'},
                'backend': 'ROCm',
                'context_capacity': capacity,
                'serve': {'endpoint': 'http://127.0.0.1:1/v1', 'model_id': 'synthetic-native-gsq',
                          'echo_path': '/meter-configuration'},
            },
            'hardware': {'device': {'name': 'synthetic-native-device', 'pci_id': '0000:09:00.0',
                                    'driver_version': 'synthetic-2.0'}},
            'reasoning': {'arm': 'ON', 'controls': {'reasoning_effort': 'low'}},
            'sampling': {'temperature': 1.0, 'top_p': 0.95, 'seed': 42,
                         'qualification_source': str(self.work / 'qualification.json')},
            'context': {'target': 16384},
            'budgets': {'max_tokens': 512, 'timeout_seconds': 60,
                        'qualification_source': str(self.work / 'budget-qualification.txt'),
                        'note': 'synthetic qualified budget; fixed before testing'},
        }
        return profile

    def _witness_messages(self, target_tokens):
        """Coherent user messages whose live render+tokenize (the same fake
        meter the endpoint serves) is EXACTLY ``target_tokens`` ids — so the
        retained usage count, the declared meter_tokens and the live replay
        count are one verified number, never an assertion."""
        controls = self.profile['reasoning']['controls']

        def total(n):
            prompt = fake_render_prompt(TEMPLATE, controls,
                                        [{'role': 'user', 'content': ' '.join(['w'] * n)}])
            return len(fake_tokenize_ids(prompt, True))

        n = max(1, target_tokens - (total(1) - 1))
        return [{'role': 'user', 'content': ' '.join(['w'] * n)}]

    def write_witness(self, name, meter_class, *, target_tokens, stream=False, tools=False):
        folder = self.work / 'native-witnesses' / name
        folder.mkdir(parents=True, exist_ok=True)
        request_path = folder / 'request.json'
        response_path = folder / 'response.raw'
        request = {'model': self.profile['runtime']['serve']['model_id'],
                   'max_tokens': 1024,
                   **policy.sampling_settings(self.profile),
                   'reasoning_effort': 'low', 'stream': stream,
                   'messages': self._witness_messages(target_tokens)}
        if tools:
            request['tools'] = [{'type': 'function', 'function': {
                'name': 'read_file',
                'parameters': {'type': 'object', 'properties': {}}}}]
        request_path.write_bytes(policy.canonical(request) + b'\n')
        usage = {'usage': {'prompt_tokens': target_tokens}}
        response = (b'data: ' + policy.canonical(usage) + b'\n\ndata: [DONE]\n\n'
                    if stream else policy.canonical(usage) + b'\n')
        response_path.write_bytes(response)
        return {'name': name, 'class': meter_class,
                'request': {'path': str(request_path), 'sha256': support.sha256_file(request_path)},
                'response': {'path': str(response_path), 'sha256': support.sha256_file(response_path)},
                'meter_tokens': target_tokens}

    def build_geometry_rows(self):
        """Real retained-qualification rows: run the pinned M2 constructions
        offline against the deterministic meter (patched token_client), so the
        declared geometry evidence carries full validate_preparation-grade
        records instead of asserted flags."""
        from welp_next import context as context_prep
        fixture = baseline.load_fixture(self.profile)
        controls = self.profile['reasoning']['controls']
        rows = []
        for task in fixture['tasks']:
            if 'context_meter' not in (task.get('requires') or []):
                continue
            with patch.object(context_prep, 'token_client', return_value=(
                    lambda messages: fake_render_prompt(TEMPLATE, controls, messages),
                    fake_tokenize_ids)):
                prepared, evidence = baseline.prepare_task(self.profile, task)
            rows.append({'unit_id': task['id'], 'prepared': prepared,
                         'evidence': evidence})
        return rows

    def write_evidence(self, engine):
        adapter = self.work / 'meter_adapter.py'
        adapter.write_text('# qualified task-local meter bridge\n')
        geometry_rows = self.build_geometry_rows()
        geometry_path = self.work / 'all-context-qualification.json'
        geometry_path.write_text(json.dumps(geometry_rows) + '\n')
        witnesses = [
            self.write_witness('completion-qualified', 'serialization', target_tokens=45),
            self.write_witness('literal-token-parity', 'literal_protection', target_tokens=67),
            self.write_witness('native-tool-feedback', 'tool_continuation',
                               target_tokens=301, stream=True, tools=True),
        ]
        self.adapter_ref = {'path': str(adapter), 'sha256': support.sha256_file(adapter)}
        self.geometry_ref = {'path': str(geometry_path), 'sha256': support.sha256_file(geometry_path)}
        witnesses = [w for w in witnesses
                     if self.NATIVE_TOOLS or w['class'] != 'tool_continuation']
        self.witnesses = witnesses

    def apply_declaration(self, *, requirement='full'):
        declaration = {'contract': policy.CONTEXT_METER_CONTRACT,
                       'adapter': dict(self.adapter_ref),
                       'geometry_evidence': dict(self.geometry_ref),
                       'witnesses': [dict(w) for w in self.witnesses]}
        capabilities = dict(self.profile.get('capabilities') or {})
        if self.NATIVE_TOOLS:
            capabilities['native_tools'] = True
        capabilities['context_meter'] = declaration
        capabilities['qualification_source'] = str(self.work / 'qualification.json')
        self.profile['capabilities'] = capabilities
        self.profile['coverage'] = {'requirement': requirement}
        policy.validate_profile(self.profile)


class QualifiedGenericMeterAdmits(GenericMeterBase):
    def test_strata_like_and_third_runtime_admit_with_hashed_original_evidence(self):
        # Retained qualification verified offline: hashed originals, witness
        # counts against original response usage, geometry gates, identity.
        self.assertEqual(policy.meter_evidence_defects(self.profile), [])
        task = {'id': 'context-family-a-v2-3072-seed-42', 'requires': ['context_meter'],
                'category': 'context', 'context_checkpoint': 3072}
        self.assertEqual(policy.task_applicability(self.profile, task), (True, ''))

    def test_fresh_online_admission_passes_and_echo_revalidates_offline(self):
        evidence = preflight.online(self.profile)
        self.assertTrue(evidence['ok'])
        self.assertEqual(evidence['checks'][-1]['name'], 'serve.protocol')
        self.assertEqual(evidence['checks'][-1]['status'], 'PASS')
        routes = self.endpoint.counts
        # 1 probe + 3 witness replays, each render+tokenize, plus the repeat.
        self.assertEqual(routes.get('apply-template'), 5)
        self.assertEqual(routes.get('tokenize'), 5)
        echo = evidence['echo']
        replay = echo['meter_probe']['witness_replay']
        self.assertEqual(len(replay), 3)
        declared = {w['name']: w for w in self.witnesses}
        for row in replay:
            witness = declared[row['name']]
            self.assertEqual(row['request_sha256'], witness['request']['sha256'])
            self.assertEqual(row['live_tokens'], witness['meter_tokens'])
            self.assertLess(len(row['tokenize_response']['tokens']), 10_000_000)
        policy.validate_echo(self.profile, echo)  # saved-echo offline revalidation

    def test_geometry_evidence_covers_exactly_the_required_units(self):
        fixture = baseline.load_fixture(self.profile)
        self.assertEqual(policy.geometry_coverage_defects(self.profile, fixture), [])
        required = [t['id'] for t in fixture['tasks']
                    if 'context_meter' in (t.get('requires') or [])]
        self.assertEqual(len(required), 8)


class ThirdRuntimeQualifiedMeterAdmits(QualifiedGenericMeterAdmits):
    """The same contract on a third, unrelated runtime: admission is generic,
    never an engine exception."""
    ENGINE = 'AcmeRuntimex'


class TextOnlyQualifiedMeter(GenericMeterBase):
    """A text-only qualified deployment (no native_tools declared) qualifies
    for the context inventory with serialization + literal_protection
    witnesses alone; the tool_continuation witness binds only to profiles
    that actually declare native tools."""
    NATIVE_TOOLS = False

    def test_text_only_meter_qualifies_for_context_inventory(self):
        self.assertEqual(policy.meter_evidence_defects(self.profile), [])
        self.assertNotIn('native_tools', self.profile['capabilities'])
        task = {'id': 'context-family-a-v2-8192-seed-42', 'requires': ['context_meter'],
                'category': 'context', 'context_checkpoint': 8192}
        self.assertEqual(policy.task_applicability(self.profile, task), (True, ''))
        evidence = preflight.online(self.profile)
        self.assertTrue(evidence['ok'])

    def test_native_tool_profiles_still_require_tool_continuation_witness(self):
        profile = copy.deepcopy(self.profile)
        profile['capabilities']['native_tools'] = True
        defects = policy.meter_evidence_defects(profile)
        self.assertIn('meter.witness.classes', defects)


class GenericMeterRejections(GenericMeterBase):
    def test_missing_and_fabricated_evidence_files_fail_closed_offline(self):
        Path(self.witnesses[0]['response']['path']).unlink()
        defects = policy.meter_evidence_defects(self.profile)
        self.assertIn('meter.witness[0].response.unreadable', defects)
        response_path = Path(self.witnesses[1]['response']['path'])
        response_path.write_bytes(response_path.read_bytes() + b'fabricated\n')
        defects = policy.meter_evidence_defects(self.profile)
        self.assertIn('meter.witness[1].response.sha256', defects)
        with self.assertRaisesRegex(policy.CheckError, 'context.meter.evidence'):
            preflight.offline(self.profile)

    def test_witness_count_disagreeing_with_original_usage_is_rejected(self):
        self.profile['capabilities']['context_meter']['witnesses'][0]['meter_tokens'] = 999
        defects = policy.meter_evidence_defects(self.profile)
        self.assertIn('meter.witness[0].parity', defects)

    def test_witness_request_drifting_from_the_qualified_contract_is_rejected(self):
        drifted = self.write_witness('native-tool-feedback', 'tool_continuation',
                                     target_tokens=301, stream=True, tools=True)
        # Same retained usage count; the REQUEST identity drifts.
        drifted_request = json.loads(Path(drifted['request']['path']).read_bytes())
        drifted_request.update({'model': 'other-model', 'temperature': 0.7,
                                'reasoning_effort': 'high'})
        Path(drifted['request']['path']).write_bytes(policy.canonical(drifted_request) + b'\n')
        drifted['request']['sha256'] = support.sha256_file(drifted['request']['path'])
        self.profile['capabilities']['context_meter']['witnesses'][2] = drifted
        defects = policy.meter_evidence_defects(self.profile)
        self.assertIn('meter.witness[2].request.model', defects)
        self.assertIn('meter.witness[2].request.sampling.temperature', defects)
        self.assertIn('meter.witness[2].request.control.reasoning_effort', defects)

    def test_wrong_native_template_identity_is_rejected_live_and_offline(self):
        # Offline saved-echo validation rejects the drift...
        evidence = self.saved_good_echo()
        evidence['configuration']['native_props']['chat_template'] = 'TAMPERED'
        with self.assertRaisesRegex(policy.CheckError, 'serve.meter.template.identity'):
            policy.validate_echo(self.profile, evidence)
        # ...and the live route rejects it fail-closed.
        self.endpoint.template = 'A DIFFERENT NATIVE TEMPLATE'
        with self.assertRaises(policy.CheckError) as caught:
            preflight.online(self.profile)
        checks = caught.exception.evidence['checks']
        self.assertIn('serve.meter.template.identity', checks[-1]['detail']['defects'])

    def test_wrong_native_context_geometry_is_rejected(self):
        self.endpoint.capacity = 4096
        with self.assertRaises(policy.CheckError) as caught:
            preflight.online(self.profile)
        checks = caught.exception.evidence['checks']
        self.assertIn('serve.meter.context.geometry', checks[-1]['detail']['defects'])

    def test_meter_routes_must_answer_live(self):
        self.endpoint.broken_routes.add('tokenize')
        with self.assertRaises(policy.CheckError) as caught:
            preflight.online(self.profile)
        names = [c['name'] for c in caught.exception.evidence['checks']]
        self.assertIn('endpoint.http', names)

    def test_geometry_gates_and_identity_are_verified_not_asserted(self):
        geometry_path = Path(self.geometry_ref['path'])
        rows = json.loads(geometry_path.read_text())
        rows[3]['evidence']['gates']['placement']['pass'] = False
        rows[3]['evidence']['measure_meta']['template_sha256'] = '0' * 64
        geometry_path.write_text(json.dumps(rows) + '\n')
        self.profile['capabilities']['context_meter']['geometry_evidence']['sha256'] = \
            support.sha256_file(geometry_path)
        defects = policy.meter_evidence_defects(self.profile)
        self.assertIn('meter.geometry[3].gates', defects)
        self.assertIn('meter.geometry[3].template_sha256', defects)

    def test_deep_geometry_revalidation_binds_each_record_to_its_pinned_task(self):
        fixture = baseline.load_fixture(self.profile)
        self.assertEqual(policy.geometry_coverage_defects(self.profile, fixture), [])
        geometry_path = Path(self.geometry_ref['path'])
        rows = json.loads(geometry_path.read_text())
        moved = rows[5]['prepared']['construction']
        moved['seed'] = 314159 if moved['seed'] == 42 else 42
        geometry_path.write_text(json.dumps(rows) + '\n')
        self.profile['capabilities']['context_meter']['geometry_evidence']['sha256'] = \
            support.sha256_file(geometry_path)
        defects = policy.geometry_coverage_defects(self.profile, fixture)
        self.assertTrue(any(d.startswith('meter.geometry.validation') for d in defects),
                        defects)

    def test_declared_meter_with_uncovered_geometry_blocks_full_dispatch(self):
        fixture = baseline.load_fixture(self.profile)
        geometry_path = Path(self.geometry_ref['path'])
        rows = json.loads(geometry_path.read_text())
        del rows[2]
        geometry_path.write_text(json.dumps(rows) + '\n')
        self.profile['capabilities']['context_meter']['geometry_evidence']['sha256'] = \
            support.sha256_file(geometry_path)
        with self.assertRaisesRegex(policy.CheckError, 'coverage.full'):
            runner._require_full_coverage(self.profile, fixture, {})

    def test_live_witness_replay_count_mismatch_is_rejected(self):
        echo = self.saved_good_echo()
        echo['meter_probe']['witness_replay'][1]['live_tokens'] = 999
        with self.assertRaisesRegex(policy.CheckError,
                                    'serve.meter.witness.replay.literal-token-parity'):
            policy.validate_echo(self.profile, echo)

    def test_missing_live_witness_replay_is_rejected(self):
        echo = self.saved_good_echo()
        del echo['meter_probe']['witness_replay']
        with self.assertRaisesRegex(policy.CheckError, 'serve.meter.witness.replay'):
            policy.validate_echo(self.profile, echo)

    def test_declaration_on_software_test_evidence_is_a_profile_defect(self):
        software = support.build_profile(self.work, 'http://127.0.0.1:1/v1', self.work / 'sw-campaign')
        software['capabilities'] = {'context_meter': {'contract': policy.CONTEXT_METER_CONTRACT}}
        with self.assertRaisesRegex(policy.CheckError, 'capabilities.context_meter'):
            policy.validate_profile(software)

    def saved_good_echo(self):
        evidence = preflight.online(self.profile)
        self.assertTrue(evidence['ok'])
        return copy.deepcopy(evidence['echo'])


class HistoricalAdmissionCompat(unittest.TestCase):
    def test_historical_boolean_capability_keeps_its_recorded_exclusion(self):
        # Exactly the recorded Strata-campaign shape: REAL_MODEL, engine not
        # llama.cpp, capabilities.context_meter is True — no declaration.
        work = support.make_workdir('historical-meter-bool')
        self.addCleanup(support.shutil.rmtree, work, True)
        profile = support.build_profile(work, 'http://127.0.0.1:1/v1', work / 'campaign')
        profile['evidence_kind'] = 'REAL_MODEL'
        profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                   'sandbox': True, 'qualification_source': 'retained'}
        task = {'id': 'context-multidocument-v2-8192-seed-42', 'requires': ['context_meter'],
                'category': 'context', 'context_checkpoint': 8192}
        self.assertEqual(policy.task_applicability(profile, task),
                         (False, 'INTEGRATION_BLOCKED: no rendered-token context meter'))
        self.assertEqual(policy.exclusion_cause(
            'INTEGRATION_BLOCKED: no rendered-token context meter'), 'integration')
        self.assertEqual(policy.exclusion_cause('UNSUPPORTED: checkpoint plus fixed '
                                                'generation reserve exceeds qualified capacity'),
                         'unsupported')

    def test_historical_software_test_boolean_stays_admitted(self):
        work = support.make_workdir('historical-meter-synthetic')
        self.addCleanup(support.shutil.rmtree, work, True)
        profile = support.build_profile(work, 'http://127.0.0.1:1/v1', work / 'campaign')
        profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                   'qualification_source': 'SOFTWARE_TEST'}
        task = {'id': 'context-family-a-v2-3072-seed-42', 'requires': ['context_meter'],
                'category': 'context', 'context_checkpoint': 3072}
        self.assertEqual(policy.task_applicability(profile, task), (True, ''))


# ---------------------------------------------------------------------------
# Required full-coverage precommitment before scored dispatch


class CoverageRequirementBase(unittest.TestCase):
    """SOFTWARE_TEST M2 campaigns confined to the project tmp tree."""

    def setUp(self):
        self.work = support.make_workdir('coverage-requirement')
        self.addCleanup(support.shutil.rmtree, self.work, True)
        self.tasks_by_id = {t['id']: t for t in scoring.load_fixture()['tasks']}
        self.endpoint = support.SyntheticEndpoint(tasks_by_id=self.tasks_by_id).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.work / 'campaign'
        self.profile = support.build_profile(self.work, self.endpoint.endpoint_url, self.campaign)
        self.profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                     'methodology': policy.METHODOLOGY_M2}
        self.profile['runtime']['context_capacity'] = 16384
        self.profile['context'] = {'target': 16384}
        self.profile['sampling']['qualification_source'] = str(Path(__file__).resolve())
        self.profile['capabilities'] = {'native_tools': True, 'sandbox': True,
                                        'isolation_approval': str(Path(__file__).resolve()),
                                        'qualification_source': 'SOFTWARE_TEST'}

    def write(self, name='profile.json'):
        return support.write_profile(self.work, self.profile, name=name)

    def section(self):
        return self.campaign / 'sections' / 'baseline'


class FullRequirementFailsBeforeAnyScoredRequest(CoverageRequirementBase):
    def test_blocked_plan_never_creates_run_identity_or_dispatches(self):
        self.profile['coverage'] = {'requirement': 'full'}
        path = self.write('profile-full.json')
        proc = support.cli(['run', '--profile', path])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['disposition'], 'BLOCKED')
        self.assertIn('coverage.full', doc['check'])
        self.assertIn('INTEGRATION_BLOCKED', doc['check'])
        self.assertEqual(self.endpoint.request_count(), 0)
        self.assertFalse((self.section() / 'run.json').exists())
        self.assertFalse((self.section() / 'evidence').exists())

    def test_native_llama_full_requirement_keeps_functional_path(self):
        # A valid native llama.cpp deployment is admitted by its own route;
        # the full requirement must not demand a generic declaration. Geometry
        # is proven fresh: all eight constructions pre-pass live before the
        # first scored generation (see FullRequirementPreparesBeforeDispatch).
        self.profile['coverage'] = {'requirement': 'full'}
        self.profile['runtime']['engine'] = {'name': 'llama.cpp', 'version': 'b1'}
        self.profile['runtime']['serve']['echo_path'] = '/props'
        self.profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                        'sandbox': True,
                                        'isolation_approval': str(Path(__file__).resolve()),
                                        'qualification_source': 'SOFTWARE_TEST'}
        policy.validate_profile(self.profile)
        fixture = baseline.load_fixture(self.profile)
        admitted, excluded = runner.m2_split(fixture, self.profile)
        self.assertEqual(len(admitted), 61)
        self.assertEqual(excluded, {})
        runner._require_full_coverage(self.profile, fixture, excluded)  # must not raise


class FullRequirementPreparesBeforeDispatch(CoverageRequirementBase):
    def test_run_prepares_all_constructions_before_first_generation(self):
        self.profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                        'sandbox': True,
                                        'isolation_approval': str(Path(__file__).resolve()),
                                        'qualification_source': 'SOFTWARE_TEST'}
        self.profile['coverage'] = {'requirement': 'full'}
        meter = MeterEndpoint(self.profile)
        self.addCleanup(meter.close)
        self.endpoint.stop()  # all traffic now goes through the qualified meter
        self.profile['runtime']['serve']['endpoint'] = meter.url('')
        result = runner.run(self.profile)
        section = self.section()
        receipts = sorted((section / 'prepreparation' /
                           policy.digest(self.profile)).glob('*.json'))
        self.assertEqual(len(receipts), 8)
        # Ordering: construction metadata calls all precede the first scored
        # generation, and no construction runs after dispatch (receipt reuse).
        routes = meter.route_log
        self.assertIn('chat/completions', routes)
        first_generation = routes.index('chat/completions')
        self.assertEqual(set(routes[:first_generation]) - {'chat/completions'},
                         {'models', 'echo', 'apply-template', 'tokenize'})
        self.assertNotIn('apply-template', routes[first_generation:])
        self.assertNotIn('tokenize', routes[first_generation:])
        # Every context attempt reused its retained receipt verbatim.
        from welp_next import store
        for path in receipts:
            receipt = store.read_json(path)
            attempt = sorted((section / 'evidence' / receipt['unit_id']).iterdir())[0]
            saved = store.read_json(attempt / 'preparation.json')
            self.assertEqual(saved['prepared_task'], receipt['prepared_task'])
            self.assertEqual(saved['construction_evidence'], receipt['construction_evidence'])
        self.assertEqual(result['state'], 'COMPLETED')


class CompatibleProfileUpdateResumesFullBaseline(CoverageRequirementBase):
    """A compatible incidental profile change (serving port/transport) must
    not permanently block a full-coverage baseline: valid units are never
    rerun, old-revision construction receipts are preserved, and ALL required
    geometry is re-admitted live under the new revision before the first
    remaining scored generation."""

    def test_interruption_then_compatible_update_resumes_without_reruns(self):
        import signal as signal_module
        self.profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                        'sandbox': True,
                                        'isolation_approval': str(Path(__file__).resolve()),
                                        'qualification_source': 'SOFTWARE_TEST'}
        self.profile['coverage'] = {'requirement': 'full'}
        meter1 = MeterEndpoint(self.profile)
        self.addCleanup(meter1.close)
        self.endpoint.stop()
        self.profile['runtime']['serve']['endpoint'] = meter1.url('')
        profile_a = self.write('profile-a.json')
        proc = support.popen_cli(['run', '--profile', profile_a])
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and \
                    meter1.counts.get('chat/completions', 0) < 3:
                time.sleep(0.05)
            self.assertGreaterEqual(meter1.counts.get('chat/completions', 0), 3)
        finally:
            proc.send_signal(signal_module.SIGINT)
            proc.wait(timeout=180)
        section = self.section()
        interrupted = runner.status(self.campaign)
        self.assertEqual(interrupted['state'], 'INTERRUPTED')
        finalized_before = {row['unit_id'] for row in interrupted['units']
                            if row['outcome'] in ('PASS', 'FAIL') and not row['pending']}
        self.assertTrue(finalized_before)
        old_revision = policy.digest(self.profile)
        self.assertEqual(len(list((section / 'prepreparation' / old_revision).glob('*.json'))), 8)

        # Compatible incidental update: NEW serving port + transport identity
        # (recorded conditions, not scientific identities) -> new revision.
        meter1.close()
        meter2 = MeterEndpoint(self.profile)
        self.addCleanup(meter2.close)
        self.profile['runtime']['serve']['endpoint'] = meter2.url('')
        command = f'meter-serve --endpoint {self.profile["runtime"]["serve"]["endpoint"]}'
        self.profile['runtime']['serve']['command'] = command
        self.profile['runtime']['serve']['sha256'] = support.sha256_bytes(command.encode())
        new_revision = policy.digest(self.profile)
        self.assertNotEqual(new_revision, old_revision)

        result = runner.run(self.profile)
        self.assertEqual(result['state'], 'COMPLETED')
        # Valid units were never rerun: one finalized attempt each, unchanged.
        for uid in finalized_before:
            attempts = sorted((section / 'evidence' / uid).iterdir())
            self.assertEqual(len(attempts), 1, f'{uid} was rerun')
        # Old receipts preserved; current revision rebuilt under its own key.
        self.assertEqual(len(list((section / 'prepreparation' / old_revision).glob('*.json'))), 8)
        self.assertEqual(len(list((section / 'prepreparation' / new_revision).glob('*.json'))), 8)
        # All required geometry was admitted live on the NEW deployment before
        # the first remaining scored generation, and no construction ran after
        # dispatch (receipt reuse).
        routes = meter2.route_log
        self.assertIn('chat/completions', routes)
        first_generation = routes.index('chat/completions')
        self.assertEqual(set(routes[:first_generation]) - {'chat/completions'},
                         {'models', 'echo', 'apply-template', 'tokenize'})
        self.assertNotIn('apply-template', routes[first_generation:])
        self.assertNotIn('tokenize', routes[first_generation:])


class PartialPrecommitmentAllowed(CoverageRequirementBase):
    def test_explicit_partial_pins_exclusions_without_any_approval_workflow(self):
        self.profile['coverage'] = {'requirement': 'partial'}
        section = self.section()
        config = runner.initialize(self.profile, section)
        self.assertEqual(len(config['excluded_units']), 8)
        for uid, reason in config['excluded_units'].items():
            self.assertTrue(reason.startswith('INTEGRATION_BLOCKED'), f'{uid}: {reason}')

    def test_real_model_dispatch_requires_explicit_coverage_precommitment(self):
        # NEW REAL_MODEL baseline dispatch fails closed without the explicit
        # full/partial precommitment; the omitted default is reserved for
        # historical and software-test profiles.
        self.profile['evidence_kind'] = 'REAL_MODEL'
        section = self.section()
        with self.assertRaisesRegex(policy.CheckError, 'coverage.requirement'):
            runner.initialize(self.profile, section)
        self.assertFalse((section / 'run.json').exists())
        self.profile['coverage'] = {'requirement': 'partial'}
        config = runner.initialize(self.profile, section)
        self.assertEqual(len(config['excluded_units']), 8)

    def test_full_to_partial_recovery_is_never_waived(self):
        # Coverage precommitment is bound into scientific compatibility: a
        # full-requirement campaign cannot be resumed as partial (or back).
        self.profile['coverage'] = {'requirement': 'full'}
        self.profile['capabilities']['context_meter'] = True  # synthetic: admitted
        section = self.section()
        runner.initialize(self.profile, section)
        self.profile['coverage'] = {'requirement': 'partial'}
        with self.assertRaisesRegex(policy.CheckError, 'recovery.profile'):
            runner.initialize(self.profile, section)

    def test_scientific_configuration_binds_normalized_requirement(self):
        full = copy.deepcopy(self.profile)
        full['coverage'] = {'requirement': 'full'}
        partial = copy.deepcopy(self.profile)
        partial['coverage'] = {'requirement': 'partial'}
        legacy_absent = copy.deepcopy(self.profile)
        legacy_absent.pop('coverage', None)
        self.assertFalse(policy.compatible_profiles(full, partial))
        self.assertTrue(policy.compatible_profiles(legacy_absent, partial))
        self.assertTrue(policy.compatible_profiles(partial, legacy_absent))

    def test_plan_reports_required_admitted_excluded_with_precise_causes(self):
        planned = runner.plan(self.profile, part='baseline')
        coverage = planned['coverage']
        self.assertEqual(coverage['requirement'], 'partial')
        self.assertFalse(coverage['explicit'])
        self.assertEqual(len(coverage['required_units']), 61)
        self.assertEqual(len(coverage['admitted_units']), 53)
        self.assertEqual(len(coverage['excluded_units']), 8)
        self.assertFalse(coverage['plan_complete'])
        for row in coverage['excluded_units']:
            self.assertEqual(row['cause'], 'integration')
            self.assertEqual(row['reason'],
                             'INTEGRATION_BLOCKED: no rendered-token context meter')

    def test_full_requirement_plan_flags_unsatisfied_precommitment(self):
        self.profile['coverage'] = {'requirement': 'full'}
        planned = runner.plan(self.profile, part='baseline')
        coverage = planned['coverage']
        self.assertEqual(coverage['requirement'], 'full')
        self.assertTrue(coverage['explicit'])
        self.assertFalse(coverage['required_baseline_satisfied'])
        self.assertTrue(all(row['cause'] == 'integration' for row in coverage['excluded_units']))


if __name__ == '__main__':
    unittest.main()
