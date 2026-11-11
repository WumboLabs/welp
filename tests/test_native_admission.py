"""Synthetic software regressions: native metadata attribution, no model inference."""
import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
from welp_next import policy, preflight


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




if __name__ == '__main__':
    unittest.main()
