"""SOFTWARE_TEST observations only; no SSH, NVIDIA access or real inference."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
from welp_next import advancement, diagnostic, policy, preflight, remote, runner, store

BIN = '/data/ai/llama.cpp-sm120/970b51ce7c9ba5fff0726c5e9994f1c2f0e4eedc/bin'


def fixture(work):
    p = support.build_profile(work, 'http://127.0.0.1:18974', work / 'diagnostic', max_tokens=128)
    p['framework'] = {'version': policy.FRAMEWORK_M2, 'methodology': policy.METHODOLOGY_DIAGNOSTIC}
    p['evidence_kind'] = 'TECHNICAL_DIAGNOSTIC'
    p['profile_id'] = p['profile_id'].replace('-cuda-off-', '-cuda-on-')
    p['reasoning'] = {'arm': 'ON', 'controls': {'chat_template_kwargs': {'enable_thinking': True}}}
    p['sampling']['qualification_source'] = str(work / 'qualification.json')
    store.put_json(work / 'qualification.json', {'evidence_kind': 'SOFTWARE_TEST', 'not_model_science': True})
    p['qualification'] = {'path': str(work / 'qualification.json'), 'sha256': policy.file_sha(work / 'qualification.json')}
    p['runtime']['engine'] = {'name': 'llama.cpp', 'version': 'b11827-test', 'path': BIN + '/llama-server', 'sha256': 'a' * 64}
    command = BIN + '/llama-server --jinja --reasoning on'
    p['runtime']['serve'].update(command=command, sha256=hashlib.sha256(command.encode()).hexdigest(),
                                 echo_path='/props', pid=123, model_id='synthetic-echo')
    p['hardware']['device'] = {'name': 'NVIDIA GeForce RTX 5070', 'pci_id': '0000:0a:00.0', 'driver_version': '595.91.07'}
    stat = {'dev': 1, 'ino': 2, 'size': 100, 'mtime_ns': 3, 'ctime_ns': 4}
    libs = {BIN + '/libggml-cuda.so.0.27.0': 'b' * 64, BIN + '/libllama-server-impl.so': 'c' * 64}
    d = {'mode': 'ssh-local-forward', 'execution_host': 'execution-host', 'inference_host': 'inference-host',
         'remote_uid': 1000, 'model_path': '/models/active/Qwen3.5-9B-Q4_K_M.gguf',
         'boot_id_sha256': 'd' * 64, 'ssh_sha256': 'e' * 64, 'server_start_ticks': '456',
         'tunnel': {'pid': 321, 'start_ticks': '654'}, 'library_sha256': libs, 'model_stat': stat}
    p['deployment'] = d
    proc = {'pid': 123, 'uid': 1000, 'start_ticks': '456', 'executable': BIN + '/llama-server',
            'executable_sha256': 'a' * 64, 'argv': command.split(),
            'listeners': [{'local_address': '0100007F:1F98', 'state': '0A'}],
            'backend_libraries': list(libs), 'library_sha256': libs,
            'cuda_visible_device_pci': '0000:0a:00.0', 'ptx_jit_disabled': True}
    props = {'build_info': 'b11827-test', 'model_path': d['model_path'], 'model_alias': 'synthetic-echo',
             'chat_template': (work / 'chat-template.txt').read_text(), 'total_slots': 1,
             'default_generation_settings': {'n_ctx': 8192, 'params': {'temperature': .2, 'top_p': .95, 'seed': 42}}}
    observation = {'execution_host': 'execution-host', 'collector': 'authenticated-ssh/1',
                   'nonce': 'f' * 48, 'requested_at': 100., 'received_at': 101.,
                   'tunnel': {'pid': 321, 'uid': 1000, 'start_ticks': '654', 'executable': '/usr/bin/ssh',
                              'executable_sha256': 'e' * 64, 'argv': policy.forward_argv(d),
                              'listeners': [{'local_address': '0100007F:4A1E', 'state': '0A'}]},
                   'remote': {'hostname': 'inference-host', 'uid': 1000, 'boot_id_sha256': 'd' * 64,
                              'nonce': 'f' * 48, 'observed_at': 100.5, 'process': proc, 'props': props,
                              'model': {'path': d['model_path'], 'mapped': True, 'stat': stat,
                                        'sha256': p['model']['artifact']['sha256']},
                              'devices': [{**p['hardware']['device'], 'power_limit_w': 200.,
                                           'enforced_power_limit_w': 200., 'temperature_c': 40,
                                           'vram_free_bytes': 4 << 30}],
                              'compute_processes': [{'pid': 123, 'pci_id': '0000:0a:00.0'}],
                              'host': {'mem_available_bytes': 10 << 30}, 'kernel': []}}
    echo = {'props': copy.deepcopy(props), 'process': copy.deepcopy(proc), 'deployment': observation,
            'template_probe': {'request': {'messages': [{'role': 'user', 'content': 'WELP preflight template rendering only.'}],
                                           **p['reasoning']['controls']}, 'response': {'prompt': '<think>\n'}}}
    return p, echo


class RemoteDiagnostic(unittest.TestCase):
    def setUp(self):
        self.work = support.make_workdir('remote-diagnostic')
        self.addCleanup(support.shutil.rmtree, self.work, True)
        self.profile, self.echo = fixture(self.work)





    def test_diagnostic_cannot_select_model_baseline_or_manufacture_advancement(self):
        with self.assertRaises(policy.CheckError):
            runner.plan(self.profile)
        with self.assertRaisesRegex(policy.CheckError, 'advancement.evidence_kind'):
            advancement.decide({'status': 'SOFTWARE_TEST', 'categories': {}}, evidence_kind='TECHNICAL_DIAGNOSTIC')
        for kind in ('REAL_MODEL', 'SOFTWARE_TEST'):
            p = copy.deepcopy(self.profile)
            p['evidence_kind'] = kind
            with self.assertRaisesRegex(policy.CheckError, 'evidence_kind'):
                policy.validate_profile(p)


    def envelope(self, content='', finish='stop', calls=None, n=2):
        message = {'role': 'assistant', 'content': content, 'reasoning_content': 'SOFTWARE_TEST thought'}
        if calls:
            message['tool_calls'] = calls
        return {'model': 'synthetic-echo', 'system_fingerprint': 'b11827-test',
                'choices': [{'message': message, 'finish_reason': finish}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': n, 'total_tokens': 10+n},
                'timings': {'predicted_n': n}, '__verbose': {'tokens_predicted': n, 'tokens': list(range(n))}}

    def call(self, ident, path):
        return {'id': ident, 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': path})}}

    def run_synthetic(self):
        packets = [self.envelope('READY'), self.envelope('', 'length', n=1),
                   self.envelope('', 'tool_calls', [self.call('original-missing-id', 'missing.txt')]),
                   self.envelope('', 'tool_calls', [self.call('original-recovery-id', 'receipt.txt')]),
                   self.envelope('qualified-native-tool')]
        requests = []
        def exchange(profile, body, timeout):
            requests.append(copy.deepcopy(body))
            envelope = packets.pop(0)
            return {'started_at': 'SOFTWARE_TEST', 'raw': policy.canonical(envelope), 'status': 200,
                    'headers': {}, 'error': None, 'timed_out': False, 'streaming': False,
                    'first_byte_seconds': .01, 'ttft_seconds': None, 'latency_seconds': .02}
        admission = {'ok': True, 'echo': self.echo}
        with patch.object(preflight, 'online', return_value=admission), \
             patch.object(context := diagnostic.context, 'token_client', return_value=(lambda messages: '<think>\n', lambda text: [1, 2])), \
             patch.object(runner, '_http_exchange', side_effect=exchange):
            result = diagnostic.run(self.profile)
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(len(requests), 5)
        return requests

    def test_original_native_tool_ids_feedback_limits_and_offline_recovery(self):
        requests = self.run_synthetic()
        self.assertEqual(requests[1]['max_tokens'], 1)
        self.assertEqual(requests[3]['messages'][-1]['tool_call_id'], 'original-missing-id')
        self.assertFalse(json.loads(requests[3]['messages'][-1]['content'])['ok'])
        self.assertEqual(requests[4]['messages'][-1]['tool_call_id'], 'original-recovery-id')
        with patch.object(runner, '_http_exchange', side_effect=AssertionError('no generation during report/finalized resume')):
            report = diagnostic.report(self.profile['campaign_root'])
            self.assertTrue(report['technical_checks_pass'])
            self.assertFalse(report['scientific_credit'])
            self.assertEqual(report['units']['length-exhaustion']['reason'], 'BUDGET_LIMITED')
            self.assertEqual(diagnostic.report(self.profile['campaign_root']), report)
            self.assertEqual(diagnostic.resume(self.profile['campaign_root'])['state'], 'COMPLETED')

    def test_rehashed_forged_feedback_id_cannot_survive_offline_reconstruction(self):
        self.run_synthetic()
        section = diagnostic.section_path(self.profile['campaign_root'])
        path = section / 'evidence/native-tool-feedback/0001'
        req = path / 'exchange-0003-request.json'
        body = store.read_json(req)
        body['messages'][-1]['tool_call_id'] = 'forged-feedback-id'
        req.write_bytes(policy.canonical(body))
        attempt_path = path / 'attempt.json'
        attempt = store.read_json(attempt_path)
        attempt['files'][req.name] = policy.file_sha(req)
        attempt_path.write_bytes(policy.canonical(attempt))
        with self.assertRaisesRegex(policy.CheckError, 'diagnostic.request'):
            diagnostic.report(self.profile['campaign_root'])

    def test_accounting_identity_and_length_failures_never_become_semantic_failures(self):
        for mutate in ('accounting', 'model', 'length'):
            body = diagnostic._body(self.profile, 'natural-completion', diagnostic._messages()['natural-completion'])
            env = self.envelope('READY')
            if mutate == 'accounting':
                env['usage']['completion_tokens'] = 999
            elif mutate == 'model':
                env['model'] = 'different-model'
            else:
                env = self.envelope('', 'length', n=128)
            rows = [{'body': body, 'raw': policy.canonical(env), 'conditions': {'http_status': 200}}]
            result = diagnostic._evaluate(self.profile, 'natural-completion', rows)
            self.assertEqual(result['outcome'], 'NOT_EVALUABLE' if mutate == 'length' else 'INVALID')


    def test_interrupted_report_publication_resumes_without_reexecution_or_rewrite(self):
        self.run_synthetic()
        original = store.put
        def interrupted(path, value):
            if Path(path).name == 'SECTION-REPORT.md':
                raise OSError('SOFTWARE_TEST interrupted publication')
            return original(path, value)
        with patch.object(store, 'put', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'interrupted publication'):
                diagnostic.report(self.profile['campaign_root'])
        with patch.object(runner, '_http_exchange', side_effect=AssertionError('offline report only')):
            receipt = diagnostic.report(self.profile['campaign_root'])
            self.assertTrue(receipt['technical_checks_pass'])
            self.assertEqual(diagnostic.report(self.profile['campaign_root']), receipt)


if __name__ == '__main__':
    unittest.main()
