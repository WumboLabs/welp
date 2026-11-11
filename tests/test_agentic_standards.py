"""Accepted budget definitions; all execution here remains SOFTWARE_TEST."""
import copy
import json
import shutil
import unittest

import support
import test_agentic as core
from test_calibration import NativeSoftwareEndpoint
from welp_next import agentic, m3


class StandardBoundary(unittest.TestCase):
    def setUp(self):
        self.work = core.workdir('accepted-standard')
        self.addCleanup(shutil.rmtree, self.work, True)

    def test_cli_rejects_each_changed_scientific_limit_before_endpoint_or_baseline(self):
        peer = NativeSoftwareEndpoint()
        self.addCleanup(peer.close)
        profile = support.build_profile(self.work, peer.url, self.work/'campaign')
        peer.profile = profile
        path = self.work/'profile.json'
        path.write_text(json.dumps(profile))
        original = m3.standard_config('agentic-readiness')
        mutants = []
        for key in agentic.LIMIT_KEYS:
            mutant = copy.deepcopy(original)
            mutant['limits']['qualification'][key] += 1
            mutants.append(mutant)
        for key, value in (('budget_version', 'unaccepted/2'), ('checker_version', 2),
                           ('adapter', 'text_json')):
            mutant = copy.deepcopy(original)
            mutant[key] = value
            mutants.append(mutant)
        for mutant in mutants:
            with self.subTest(mutant=mutant):
                config = self.work/'config.json'
                config.write_text(json.dumps(mutant))
                result = support.cli(['plan', '--section', 'agentic-readiness',
                                      '--profile', path, '--agentic-config', config])
                self.assertEqual(result.returncode, 2)
                self.assertIn('agentic.standard', result.stdout+result.stderr)
        self.assertEqual(peer.calls, [])

    def test_cli_caller_approval_cannot_turn_standard_preparation_into_calibration(self):
        peer = NativeSoftwareEndpoint()
        self.addCleanup(peer.close)
        profile = support.build_profile(self.work, peer.url, self.work/'campaign')
        peer.profile = profile
        path = self.work/'profile.json'
        path.write_text(json.dumps(profile))
        config = m3.standard_config('agentic-readiness')
        config.update(evidence_kind='CALIBRATION', approved=True,
                      acceptance='HUMAN_ACCEPTED')
        config_path = self.work/'config.json'
        config_path.write_text(json.dumps(config))
        result = support.cli(['run', '--section', 'agentic-readiness', '--profile', path,
                              '--agentic-config', config_path])
        self.assertEqual(result.returncode, 2)
        self.assertIn('agentic.calibration', result.stdout+result.stderr)
        self.assertEqual(peer.calls, [])
        self.assertFalse((self.work/'campaign/sections/agentic-readiness/evidence').exists())


@unittest.skipUnless(core.BWRAP, 'bwrap required')
class StandardExecution(unittest.TestCase):
    def execute(self, name, exchange):
        section = 'agentic-readiness' if name == 'qualification' else 'agentic'
        config = m3.standard_config(section)
        fixture = m3._config(config, section)[name]
        path = core.workdir('standard-execution')
        self.addCleanup(shutil.rmtree, path, True)
        result = agentic.execute(fixture, config['limits'][name], 'native_tools',
                                 exchange, path)
        return result, path, fixture, config['limits'][name]

    def test_standard_readiness_repairs_verifies_and_reconstructs_without_credit(self):
        actions = [('list_dir', {'path': '/workspace'}),
                   ('write_file', {'path': 'formatters.py',
                                   'content': core.QUAL_REFERENCE_FORMATTERS}),
                   ('run', {'command': 'cd /workspace && ./run_tests.sh'}),
                   ('finish', {'report': 'Formatter repaired; verification passed.'})]
        replies = [core.envelope(tool_calls=[core.native_call(str(i), name, args)],
                                 finish_reason='tool_calls')
                   for i, (name, args) in enumerate(actions)]
        result, path, fixture, limits = self.execute('qualification', core.scripted(replies))
        self.assertEqual(result['outcome'], 'PASS')
        self.assertEqual(result['evidence']['kind'], 'SOFTWARE_TEST')
        self.assertEqual(agentic.replay(path, fixture, limits, 'native_tools')['evaluation'],
                         result['evaluation'])

    def test_each_standard_turn_ceiling_stops_an_unfinished_real_tool_loop(self):
        for name in agentic.FIXTURE_NAMES:
            with self.subTest(task=name):
                turns = m3.STANDARD_VECTORS[name][0]
                replies = [core.envelope(tool_calls=[core.native_call(str(i), 'list_dir',
                                                                      {'path': '.'})],
                                         finish_reason='tool_calls', completion_tokens=1)
                           for i in range(turns)]
                ledger = []
                result, _, _, _ = self.execute(name, core.scripted(replies, ledger))
                self.assertEqual(result['turns_used'], turns)
                self.assertEqual(len(ledger), turns)
                self.assertEqual(result['stop_reason'], 'TURN_LIMIT')
                self.assertEqual(result['outcome'], 'NOT_EVALUABLE')
                self.assertEqual(result['reason'], 'BUDGET_LIMITED')
                self.assertIsNone(result['final_report'])

    def test_total_completion_allowance_limits_the_final_request_and_stops_before_more_work(self):
        caps = []
        responses = [3072, 3072, 2048]
        def exchange(body, remaining):
            caps.append(body['max_tokens'])
            count = responses[len(caps)-1]
            env = core.envelope(tool_calls=[core.native_call(str(len(caps)), 'list_dir',
                                                             {'path': '/workspace'})],
                                finish_reason='tool_calls', completion_tokens=count)
            return {'raw': json.dumps(env).encode(), 'status': 200,
                    'error': None, 'timed_out': False}
        result, _, _, _ = self.execute('qualification', exchange)
        self.assertEqual(caps, [3072, 3072, 2048])
        self.assertEqual(result['total_completion_tokens'], 8192)
        self.assertEqual(result['stop_reason'], 'TOKEN_BUDGET_LIMIT')
        self.assertEqual(result['outcome'], 'NOT_EVALUABLE')
        self.assertEqual(result['reason'], 'BUDGET_LIMITED')
