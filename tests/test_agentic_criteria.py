"""Prospective checker/3 behavior; all responses and evidence are SOFTWARE_TEST."""
import copy
import json
import shutil
import unittest

from welp_next import agentic, agentic_checks_v3, m3, policy
from test_agentic import (BASE_LIMITS, BWRAP, QUAL_REFERENCE_FORMATTERS,
                          REPO_REFERENCE_NOTES_PY, RESEARCH_REFERENCE_ANSWER,
                          SYSTEM_FIXED_CONFIG, call, envelope, scripted, workdir)


@unittest.skipUnless(BWRAP, 'bwrap required')
class ProspectiveCriteria(unittest.TestCase):
    def execute(self, name, actions, *, calibration=False, version=3, limits=None):
        fixture = agentic.load_fixture(name, version=version, calibration=calibration)
        attempt = workdir('criteria-v3')
        self.addCleanup(shutil.rmtree, attempt, True)
        result = agentic.execute(fixture, limits or BASE_LIMITS, 'text_json',
                                 scripted([envelope(call(tool, args)) for tool, args in actions]), attempt)
        return result, attempt, fixture

    def repaired(self, command, tail=None):
        return self.execute('qualification', [
            ('write_file', {'path': 'formatters.py', 'content': QUAL_REFERENCE_FORMATTERS}),
            ('run', {'command': command}),
            *(tail or []),
            ('finish', {'report': 'Formatter repaired; verification attempted as recorded.'}),
        ])

    def check(self, result, name):
        return next(c['pass'] for c in result['evaluation']['checks'] if c['id'] == name)

    def test_required_script_equivalents_execute_and_reconstruct(self):
        for command in ('./run_tests.sh', 'cd /workspace && ./run_tests.sh',
                        '/bin/sh /workspace/run_tests.sh', 'cd /workspace && sh ./run_tests.sh'):
            with self.subTest(command=command):
                result, path, fixture = self.repaired(command)
                self.assertEqual(result['outcome'], 'PASS')
                self.assertTrue(self.check(result, 'required_verification_execution'))
                replay = agentic.replay(path, fixture, BASE_LIMITS, 'text_json')
                self.assertEqual(replay['evaluation'], result['evaluation'])

    def test_echo_wrong_workspace_unrelated_script_and_shell_suffixes_do_not_verify(self):
        for command in ('echo ./run_tests.sh', 'cd /tmp && /workspace/run_tests.sh',
                        'sh -c "echo ./run_tests.sh"', './run_tests.sh || true',
                        './run_tests.sh; echo done', './run_tests.sh > /dev/null',
                        'echo "$(./run_tests.sh)"'):
            with self.subTest(command=command):
                result, _, _ = self.repaired(command)
                self.assertEqual(result['outcome'], 'FAIL')
                self.assertTrue(self.check(result, 'acceptance'))
                self.assertFalse(self.check(result, 'required_verification_execution'))

    def test_success_prose_cannot_replace_actual_verification(self):
        result, _, _ = self.execute('qualification', [
            ('write_file', {'path': 'formatters.py', 'content': QUAL_REFERENCE_FORMATTERS}),
            ('finish', {'report': 'Tests passed.'}),
        ])
        self.assertTrue(self.check(result, 'acceptance'))
        self.assertFalse(self.check(result, 'required_verification_execution'))
        self.assertEqual(result['outcome'], 'FAIL')

    def test_failed_script_and_later_actions_do_not_verify_final_state(self):
        result, _, _ = self.execute('qualification', [
            ('run', {'command': './run_tests.sh'}), ('finish', {'report': 'Unable to repair.'})])
        self.assertFalse(self.check(result, 'required_verification_execution'))
        for tail in ([('write_file', {'path': 'extra.txt', 'content': 'late mutation'})],
                     [('run', {'command': 'ls /workspace'})]):
            result, _, _ = self.repaired('cd /workspace && ./run_tests.sh', tail)
            self.assertFalse(self.check(result, 'required_verification_execution'))
            self.assertEqual(result['outcome'], 'FAIL')

    def test_missing_failed_or_mismatched_execution_receipt_cannot_establish_verification(self):
        result, path, fixture = self.repaired('./run_tests.sh')
        trace = json.loads((path / 'agentic-transcript.json').read_text())['transcript']
        for mutation in ({'launched': False}, {'exit_code': 1}, {'timed_out': True},
                         {'snapshot_complete': False}, {'args': {'command': 'echo unrelated'}}):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(trace)
                obs = next(e['observation'] for e in changed if e.get('role') == 'observation'
                           and e['observation'].get('tool') == 'run')
                obs.update(mutation)
                self.assertFalse(agentic_checks_v3.verification(result, changed, './run_tests.sh'))

    def test_repository_functional_and_hidden_acceptance_are_not_weakened(self):
        result, _, _ = self.execute('repository', [
            ('write_file', {'path': 'notes.py', 'content': REPO_REFERENCE_NOTES_PY}),
            ('run', {'command': 'cd /workspace && ./run_tests.sh'}),
            ('finish', {'report': 'Visible verification succeeded.'}),
        ])
        self.assertEqual(result['outcome'], 'PASS')
        self.assertTrue(self.check(result, 'visible_tests_pass'))
        self.assertTrue(self.check(result, 'hidden_acceptance_pass'))

    def test_catalog_native_case_variants_pass_but_invalid_level_does_not(self):
        for level in ('info', 'INFO', 'InFo'):
            with self.subTest(level=level):
                config = json.dumps({'port': 8642, 'log_level': level, 'data_file': 'data/catalog.json'})
                result, _, fixture = self.execute('system', [
                    ('write_file', {'path': 'config/catalog.json', 'content': config}),
                    ('run', {'command': 'chmod 644 data/catalog.json'}),
                    ('run', {'command': 'cd /workspace && ./check.sh'}),
                    ('finish', {'report': 'Independent service verification completed.'}),
                ], calibration=True)
                self.assertEqual(result['outcome'], 'PASS')
                for check in ('config_log_level_valid', 'service_healthy', 'data_bytes_preserved',
                              'authorized_repair_boundary', 'required_verification_execution'):
                    self.assertTrue(self.check(result, check))
                changed = copy.deepcopy(result)
                changed['final_state']['files']['config/catalog.json']['content'] = config.replace(level, 'noisy')
                receipt = agentic_checks_v3.acceptance(result['evaluation']['acceptance'], changed,
                                                       agentic.AgenticFixture.coerce(fixture))
                self.assertFalse(next(c['pass'] for c in receipt['checks'] if c['id'] == 'config_log_level_valid'))

    def test_scored_quote_service_retains_its_actual_case_sensitive_contract(self):
        for level, expected in (('info', 'PASS'), ('INFO', 'FAIL')):
            with self.subTest(level=level):
                result, _, _ = self.execute('system', [
                    ('write_file', {'path': 'config/service.json',
                                    'content': SYSTEM_FIXED_CONFIG.replace('info', level)}),
                    ('run', {'command': 'chmod 644 data/quotes.json'}),
                    ('run', {'command': './check.sh'}),
                    ('finish', {'report': 'State and verification recorded.'}),
                ])
                self.assertEqual(result['outcome'], expected)
                self.assertEqual(self.check(result, 'config_log_level_valid'), level == 'info')
                self.assertEqual(self.check(result, 'service_healthy'), level == 'info')

    def test_research_required_governance_authority_and_source_exposure_still_bind(self):
        cases = [(RESEARCH_REFERENCE_ANSWER, True, 'PASS'),
                 (RESEARCH_REFERENCE_ANSWER.replace(', governance\n', '\n'), True, 'FAIL'),
                 (RESEARCH_REFERENCE_ANSWER.replace('Governing source: ops-bulletin-7',
                                                    'Governing source: manual-v3'), True, 'FAIL'),
                 (RESEARCH_REFERENCE_ANSWER, False, 'FAIL')]
        for answer, expose, expected in cases:
            with self.subTest(answer=answer, expose=expose):
                actions = [('run', {'command': 'cat sources/*.md'})] if expose else []
                actions += [('write_file', {'path': 'research-pack/answer.md', 'content': answer}),
                            ('finish', {'report': 'Artifact written; original checks determine acceptance.'})]
                result, _, _ = self.execute('research', actions)
                self.assertEqual(result['outcome'], expected)

    def test_verified_partial_repair_without_finish_is_not_completion(self):
        result, _, _ = self.execute('qualification', [
            ('write_file', {'path': 'formatters.py', 'content': QUAL_REFERENCE_FORMATTERS}),
            ('run', {'command': 'cd /workspace && ./run_tests.sh'}),
        ], limits=dict(BASE_LIMITS, max_turns=2))
        self.assertEqual(result['outcome'], 'NOT_EVALUABLE')
        self.assertEqual(result['reason'], 'BUDGET_LIMITED')
        self.assertTrue(result['evaluation']['partial_progress'])

    def test_historical_checker_keeps_literal_verification_and_cannot_be_relabelled(self):
        result, path, _ = self.execute('qualification', [
            ('write_file', {'path': 'formatters.py', 'content': QUAL_REFERENCE_FORMATTERS}),
            ('run', {'command': 'cd /workspace && ./run_tests.sh'}),
            ('finish', {'report': 'Repair verified.'}),
        ], version=2)
        self.assertEqual(result['outcome'], 'FAIL')
        with self.assertRaises(policy.CheckError):
            agentic.replay(path, agentic.load_fixture('qualification', version=3), BASE_LIMITS, 'text_json')


class ScientificExecutionBoundary(unittest.TestCase):
    def test_proposed_criteria_do_not_authorize_scored_model_execution(self):
        for kind in ('REAL_MODEL', 'CALIBRATION'):
            with self.subTest(kind=kind), self.assertRaises(policy.CheckError):
                m3._config({'evidence_kind': kind, 'adapter': 'native_tools',
                            'checker_version': 3, 'approved': True, 'limits': {}}, 'agentic-readiness')
        # 2026-11-06: REAL_MODEL limits are structurally valid; execution stays
        # blocked by the scored module's campaign gate without activation.
        from welp_next import scored
        limits = dict(BASE_LIMITS, evidence_kind='REAL_MODEL',
                      source='agentic-budget/1; campaign-gated scored route')
        agentic.validate_limits(limits)
        profile = {'campaign_id': 'unauthorized-campaign',
                   'campaign_root': '/tmp/no-such-activation-dir',
                   'evidence_kind': 'REAL_MODEL'}
        self.assertFalse(scored.authorized(profile))
