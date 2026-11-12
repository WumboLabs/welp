"""Advanced Coding section: gate, frozen inventory, execution, reconstruction.

All model observations in this module are SOFTWARE_TEST against the synthetic
thread-server and the real disposable bubblewrap boundary; no authentic model
evaluation is claimed or exercised.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from welp_next import coding, policy
import support

GOOD_CODE = {
    'advanced-module-01': (
        "```python\n"
        "def median(v):\n"
        "    v=sorted(v); n=len(v)\n"
        "    return v[n//2] if n%2 else (v[n//2-1]+v[n//2])/2\n\n"
        "def mode(v):\n"
        "    counts={}\n"
        "    for x in v: counts[x]=counts.get(x,0)+1\n"
        "    best=max(counts.values())\n"
        "    return min(k for k,c in counts.items() if c==best)\n\n"
        "def moving_average(v, window):\n"
        "    if window<1 or window>len(v): raise ValueError('window')\n"
        "    return [sum(v[i:i+window])/window for i in range(len(v)-window+1)]\n"
        "```\n"),
    'advanced-repair-supplied-01': (
        "```python\n"
        "def low_stock(items, threshold):\n"
        "    return sorted(name for name, row in items.items()\n"
        "                  if row['quantity'] < threshold)\n\n"
        "def total_value(items):\n"
        "    return sum(row['price'] * row['quantity'] for row in items.values())\n\n"
        "def apply_discount(items, percent):\n"
        "    import copy\n"
        "    out = copy.deepcopy(items)\n"
        "    for row in out.values():\n"
        "        row['price'] = row['price'] - row['price'] * percent / 100\n"
        "    return out\n"
        "```\n"),
}


def payload(content):
    return (200, support.canonical(support.envelope(content, 'stop')) + b'\n')


def gate_envelope(decision, authorization=None):
    return {'decisions': {'result': {'decisions': {'coding': {
        'decision': decision, 'reason': 'recorded test decision',
        'exploratory_authorization': authorization}}}}}


class GateAndConfig(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('coding-gate')
        self.campaign = self.workdir / 'coding-campaign'
        self.campaign.mkdir()
        self.profile = support.build_profile(self.workdir, 'http://127.0.0.1:1/v1',
                                             self.campaign)
        self.profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                        'sandbox': True,
                                        'qualification_source': 'SOFTWARE_TEST',
                                        'isolation_approval': 'SOFTWARE_TEST'}
        self.profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())

    def test_plan_requires_finalized_baseline_before_any_gate(self):
        with self.assertRaises(policy.CheckError):
            coding.plan(self.profile)

    def test_gate_blocks_deferred_and_unattributed_exploratory(self):
        with patch('welp_next.m3.decisions', return_value=gate_envelope('DEFERRED')):
            with self.assertRaises(policy.CheckError) as ctx:
                coding.plan(self.profile)
            self.assertIn('coding.advancement: DEFERRED', str(ctx.exception))
        with patch('welp_next.m3.decisions', return_value=gate_envelope(
                'EXPLORATORY', authorization={})):
            with self.assertRaises(policy.CheckError) as ctx:
                coding.plan(self.profile)
            self.assertIn('attribution', str(ctx.exception))

    def test_advance_gate_plans_frozen_inventory(self):
        with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
            value = coding.plan(self.profile)
        self.assertEqual(value['section'], 'coding')
        self.assertEqual(value['methodology'], 'coding-advanced/1')
        self.assertEqual(value['unit_ids'], ['advanced-module-01',
                                             'advanced-repair-supplied-01',
                                             'advanced-repair-multi-01'])
        self.assertEqual(value['gate']['decision'], 'ADVANCE')

    def test_caller_config_keys_are_rejected(self):
        with self.assertRaises(policy.CheckError):
            coding._config({'tasks': ['advanced-module-01']})
        self.assertEqual(coding._config(None), {})


class CodingSectionExecution(unittest.TestCase):
    def test_run_pass_fail_no_code_and_offline_reconstruction(self):
        workdir = support.make_workdir('coding-exec')
        campaign = workdir / 'coding-campaign'
        campaign.mkdir()
        profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1', campaign)
        profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                'methodology': policy.METHODOLOGY_M2}
        profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                   'sandbox': True,
                                   'qualification_source': 'SOFTWARE_TEST',
                                   'isolation_approval': 'SOFTWARE_TEST'}
        profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())
        fixture, tasks = coding.load_tasks()
        payloads = {uid: payload(content) for uid, content in {
            'advanced-module-01': GOOD_CODE['advanced-module-01'],
            'advanced-repair-supplied-01': GOOD_CODE['advanced-repair-supplied-01'],
            'advanced-repair-multi-01': 'I was unable to complete this task.',
        }.items()}
        server = support.SyntheticEndpoint(tasks_by_id=tasks, payloads=payloads,
                                           echo_provider=lambda: {**support.identity_echo(profile), 'sampling': policy.sampling_settings(profile)})
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                coding.run(profile)
            status = coding.status(campaign)
            self.assertEqual(status['state'], 'COMPLETED')
            outcomes = {u['unit_id']: u['outcome'] for u in status['units']}
            self.assertEqual(outcomes, {'advanced-module-01': 'PASS',
                                        'advanced-repair-supplied-01': 'PASS',
                                        'advanced-repair-multi-01': 'FAIL'})
            # Verified partial progress stays visible on the failing unit's
            # decisive no-code format failure? No: no admissible code means no
            # executed tests, so no partial milestone is claimed there.
            module_row = next(u for u in status['units']
                              if u['unit_id'] == 'advanced-module-01')
            self.assertTrue(module_row['partial_progress'])
            with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                report = coding.report_section(campaign)
            self.assertEqual(report['disposition'], 'PASS')
            self.assertEqual(report['state'], 'COMPLETED')
            support.verify_manifest_integrity(self, campaign / 'sections' / 'coding')
            # Repeat finalization is idempotent and re-verifies the manifest.
            with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                again = coding.report_section(campaign)
            self.assertTrue(again['already_finalized'])
        finally:
            server.stop()

    def test_wrong_implementation_is_a_valid_negative(self):
        workdir = support.make_workdir('coding-negative')
        campaign = workdir / 'coding-campaign'
        campaign.mkdir()
        profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1', campaign)
        profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                'methodology': policy.METHODOLOGY_M2}
        profile['capabilities'] = {'native_tools': True, 'context_meter': True,
                                   'sandbox': True,
                                   'qualification_source': 'SOFTWARE_TEST',
                                   'isolation_approval': 'SOFTWARE_TEST'}
        profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())
        fixture, tasks = coding.load_tasks()
        wrong = GOOD_CODE['advanced-module-01'].replace('window<1', 'window<0')
        payloads = {uid: payload(content) for uid, content in {
            'advanced-module-01': wrong,
            'advanced-repair-supplied-01': '',
            'advanced-repair-multi-01': 'I was unable to complete this task.',
        }.items()}
        server = support.SyntheticEndpoint(tasks_by_id=tasks, payloads=payloads,
                                           echo_provider=lambda: {**support.identity_echo(profile), 'sampling': policy.sampling_settings(profile)})
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            # The wrong implementation must be a FAIL with the sandbox verdict
            # recorded, never a harness error; the no-code units are decisive
            # format failures with no partial milestone claimed.
            with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                coding.run(profile)
            status = coding.status(campaign)
            outcomes = {u['unit_id']: u['outcome'] for u in status['units']}
            self.assertEqual(outcomes['advanced-module-01'], 'FAIL')
            section = campaign / 'sections' / 'coding'
            attempt = section / 'evidence/advanced-module-01/0001/score.json'
            score = json.loads(attempt.read_text())
            self.assertEqual(score['outcome'], 'FAIL')
            self.assertIs(score['record']['tests_pass'], False)
            # The raw sandbox receipt independently records the executed
            # unittest exit: failing tests give a nonzero exit, never a
            # harness error.
            executed = json.loads(
                (attempt.parent / 'sandbox-execution.json').read_text())
            self.assertTrue(executed['record']['executed'])
            self.assertNotEqual(executed['record']['exit_code'], 0)
        finally:
            server.stop()


if __name__ == '__main__':
    unittest.main()


class BaselineReuseGate(unittest.TestCase):
    def test_reuse_attribution_requires_manifest_identity(self):
        profile = support.build_profile(
            support.make_workdir('coding-reuse'), 'http://127.0.0.1:1/v1',
            support.make_workdir('coding-reuse-campaign'))
        profile['deployment'] = {'reuse_baseline': {
            'campaign_root': '/accepted/m2-campaign',
            'section_manifest_sha256': '7' * 64}}
        from welp_next import reporting
        with patch.object(policy, 'file_sha', return_value='mismatch'):
            with self.assertRaises(policy.CheckError) as ctx:
                coding._advancement_gate(profile)
        self.assertIn('recorded manifest identity mismatch', str(ctx.exception))
