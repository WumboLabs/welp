"""Advanced Reasoning section: gate, frozen inventory, execution, attribution.

All model observations are SOFTWARE_TEST against the synthetic thread-server;
no authentic model evaluation is claimed or exercised. Failure-attribution
tests pin: wrong answers are valid FAILs, empty answers are NOT_EVALUABLE,
transport deadlines are budget-limited (never model failures).
"""
import json
import unittest
from unittest.mock import patch

from welp_next import advanced_reasoning, policy
import support


def gate_envelope(decision, authorization=None):
    return {'decisions': {'result': {'decisions': {'reasoning': {
        'decision': decision, 'reason': 'recorded test decision',
        'exploratory_authorization': authorization}}}}}


def payload(content):
    return (200, support.canonical(support.envelope(content, 'stop')) + b'\n')


def make_profile(workdir, campaign, server_url=None):
    profile = support.build_profile(workdir, server_url or 'http://127.0.0.1:1/v1', campaign)
    profile['framework'] = {'version': policy.FRAMEWORK_M2,
                            'methodology': policy.METHODOLOGY_M2}
    profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                               'sandbox': True,
                               'qualification_source': 'SOFTWARE_TEST',
                               'isolation_approval': 'SOFTWARE_TEST'}
    profile['sampling']['qualification_source'] = \
        support.SUPPORT_PATH
    return profile


def echo_provider(profile):
    return {**support.identity_echo(profile),
            'sampling': policy.sampling_settings(profile)}


class GateAndInventory(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('reasoning-gate')
        self.campaign = self.workdir / 'reasoning-campaign'
        self.campaign.mkdir()
        self.profile = make_profile(self.workdir, self.campaign)

    def test_plan_requires_finalized_baseline(self):
        with self.assertRaises(policy.CheckError):
            advanced_reasoning.plan(self.profile)

    def test_gate_blocks_deferred_and_unattributed_exploratory(self):
        with patch('welp_next.m3.decisions', return_value=gate_envelope('DEFERRED')):
            with self.assertRaises(policy.CheckError) as ctx:
                advanced_reasoning.plan(self.profile)
            self.assertIn('reasoning.advancement: DEFERRED', str(ctx.exception))
        with patch('welp_next.m3.decisions', return_value=gate_envelope(
                'EXPLORATORY', authorization={})):
            with self.assertRaises(policy.CheckError) as ctx:
                advanced_reasoning.plan(self.profile)
            self.assertIn('attribution', str(ctx.exception))

    def test_advance_gate_plans_frozen_inventory(self):
        with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
            value = advanced_reasoning.plan(self.profile)
        self.assertEqual(value['section'], 'advanced-reasoning')
        self.assertEqual(value['methodology'], 'reasoning-advanced/1')
        self.assertEqual(value['unit_ids'], ['advanced-constraints-01',
                                             'advanced-evidence-01',
                                             'advanced-revision-01'])

    def test_caller_config_keys_are_rejected(self):
        with self.assertRaises(policy.CheckError):
            advanced_reasoning.plan(self.profile, {'thresholds': {'x': 1}})


class ExecutionAndAttribution(unittest.TestCase):
    def _run(self, behaviors):
        workdir = support.make_workdir('reasoning-exec')
        campaign = workdir / 'reasoning-campaign'
        campaign.mkdir()
        profile = make_profile(workdir, campaign)
        fixture, tasks = advanced_reasoning.load_tasks()
        payloads = {uid: payload(content) for uid, content in behaviors.items()}
        # The revision task is a two-turn conversation: the frozen initial
        # answer is 54; the scored final exchange serves the behavior value
        # (the correct 60, or a near-miss) after the followup condition change.
        payloads['advanced-revision-01'] = lambda index: payload(
            '54' if index == 1 else behaviors['advanced-revision-01'])
        server = support.SyntheticEndpoint(tasks_by_id=tasks, payloads=payloads,
                                           echo_provider=lambda: echo_provider(profile))
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                advanced_reasoning.run(profile)
            status = advanced_reasoning.status(campaign)
            report = None
            if status['state'] in ('COMPLETED', 'COMPLETED_PARTIAL'):
                with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                    report = advanced_reasoning.report_section(campaign)
            return status, report, campaign, tasks
        finally:
            server.stop()

    def test_correct_answers_pass_and_finalize(self):
        behaviors = {'advanced-constraints-01': 'Quinn',
                     'advanced-evidence-01': '24',
                     'advanced-revision-01': '60'}
        status, report, campaign, tasks = self._run(behaviors)
        self.assertEqual(status['state'], 'COMPLETED')
        outcomes = {u['unit_id']: u['outcome'] for u in status['units']}
        self.assertEqual(outcomes, {'advanced-constraints-01': 'PASS',
                                    'advanced-evidence-01': 'PASS',
                                    'advanced-revision-01': 'PASS'})
        self.assertEqual(report['disposition'], 'PASS')
        support.verify_manifest_integrity(self, campaign / 'sections' / 'advanced-reasoning')
        # The revision task's scored exchange is the final one (after the
        # followup): its frozen oracle must be the revised answer, and the
        # initial-turn answer must never satisfy it.
        section = campaign / 'sections' / 'advanced-reasoning'
        attempts = json.loads(
            (section / 'evidence/advanced-revision-01/0001/attempt.json').read_text())
        self.assertEqual(attempts['unit_id'], 'advanced-revision-01')
        raw = (section / 'evidence/advanced-revision-01/0001/response.raw').read_bytes()
        self.assertIn(b'60', raw)
        self.assertEqual(len(raw.split(b'\n')), 2)  # two genuine exchanges

    def test_wrong_answers_are_valid_fails_never_harness_errors(self):
        # Near-miss answers for each behavior: partial-constraint Thursday,
        # supersession-chain short-circuit (memo quota headroom), stale
        # initial-condition answer after the revision.
        behaviors = {'advanced-constraints-01': 'Priya',
                     'advanced-evidence-01': '16',
                     'advanced-revision-01': '54'}
        status, report, campaign, tasks = self._run(behaviors)
        self.assertEqual(status['state'], 'COMPLETED')
        for u in status['units']:
            self.assertEqual(u['outcome'], 'FAIL', u['unit_id'])
            self.assertIsNone(u['reason'], 'wrong answers are semantic FAILs, '
                                           'never budget/invalid classifications')

    def test_empty_answer_is_not_evaluable_not_fail(self):
        # Empty refusals are unscorable, never semantic FAILs; the existing
        # outcome machinery classifies them NOT_EVALUABLE/UNSCORABLE_ANSWER
        # (a truncated-with-partial-content reply would be BUDGET_LIMITED).
        status, report, campaign, tasks = self._run({
            'advanced-constraints-01': '',
            'advanced-evidence-01': '',
            'advanced-revision-01': ''})
        for u in status['units']:
            self.assertEqual(u['outcome'], 'NOT_EVALUABLE', u['unit_id'])
            self.assertEqual(u['reason'], 'UNSCORABLE_ANSWER')

    def test_offline_reconstruction_without_endpoint(self):
        behaviors = {'advanced-constraints-01': 'Quinn',
                     'advanced-evidence-01': '16',
                     'advanced-revision-01': '54'}
        status, report, campaign, tasks = self._run(behaviors)
        section = campaign / 'sections' / 'advanced-reasoning'
        self.assertTrue((section / 'manifest.json').exists())
        # Repeat finalization re-verifies the manifest without new inference.
        with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
            again = advanced_reasoning.report_section(campaign)
        self.assertTrue(again['already_finalized'])
        support.verify_manifest_integrity(self, section)


if __name__ == '__main__':
    unittest.main()
