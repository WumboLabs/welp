"""Advanced Long Context section: gate, geometry, execution, attribution.

All model observations are SOFTWARE_TEST against the synthetic thread-server;
no authentic model evaluation is claimed. Fault-attribution tests pin: decoy/
superseded/stale answers are valid FAILs, empty answers are NOT_EVALUABLE,
unsupported geometry blocks as technical applicability (never model FAIL),
and human-directed/EXPLORATORY preserves the standard eligibility result.
"""
import json
import unittest
from unittest.mock import patch

from welp_next import advancement, long_context, policy, reporting, store
import support


def gate_envelope(decision, authorization=None):
    return {'decisions': {'result': {'decisions': {'long-context': {
        'decision': decision, 'reason': 'recorded test decision',
        'exploratory_authorization': authorization}}}}}


def payload(content):
    return (200, support.canonical(support.envelope(content, 'stop')) + b'\n')


def make_profile(workdir, campaign, server_url=None, capacity=16384):
    profile = support.build_profile(workdir, server_url or 'http://127.0.0.1:1/v1', campaign)
    profile['framework'] = {'version': policy.FRAMEWORK_M2,
                            'methodology': policy.METHODOLOGY_M2}
    profile['runtime']['context_capacity'] = capacity
    profile['context'] = {'target': min(16384, capacity)}
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


CORRECT = {
    'advanced-lc-retrieval-01': '{"access_code":"TR-7741-KD","crates_2027":213,"contact_extension":"x-4471"}',
    'advanced-lc-synthesis-01': '{"effective_quota_gb":64,"maintenance_frequency":"monthly","superseded_document":"policy-v1"}',
    'advanced-lc-retention-01': '{"site_name":"Harborview","retention_days":90,"admin_contact":"a.ferrar@depot.example"}',
}
NEAR_MISS = {
    'advanced-lc-retrieval-01': '{"access_code":"TR-1188-QS","crates_2027":305,"contact_extension":"x-7710"}',
    'advanced-lc-synthesis-01': '{"effective_quota_gb":40,"maintenance_frequency":"weekly","superseded_document":"maintenance-v1"}',
    'advanced-lc-retention-01': '{"site_name":"Harborview","retention_days":30,"admin_contact":"a.ferrar@depot.example"}',
}


class GeometryAndGate(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('lc-gate')
        self.campaign = self.workdir / 'lc-campaign'
        self.campaign.mkdir()
        self.profile = make_profile(self.workdir, self.campaign)

    def test_geometry_gate_blocks_unsupported_checkpoint(self):
        small = make_profile(self.workdir, self.campaign, capacity=8192)
        # The 12288-token retention checkpoint plus reserve cannot fit 8192:
        # a technical applicability limit, never a model outcome.
        with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
            with self.assertRaises(policy.CheckError) as ctx:
                long_context.plan(small)
        self.assertIn('long_context.geometry', str(ctx.exception))
        self.assertIn('technical', str(ctx.exception).lower() or 'applicability')

    def test_gate_blocks_deferred_context_witness(self):
        # The accepted M2 context witness is DEFERRED: it must block standard
        # advancement and never fabricate eligibility.
        with patch('welp_next.m3.decisions', return_value=gate_envelope('DEFERRED')):
            with self.assertRaises(policy.CheckError) as ctx:
                long_context.plan(self.profile)
            self.assertIn('long-context.advancement: DEFERRED', str(ctx.exception))

    def test_exploratory_requires_attribution_and_advance_plans(self):
        with patch('welp_next.m3.decisions', return_value=gate_envelope(
                'EXPLORATORY', authorization={})):
            with self.assertRaises(policy.CheckError) as ctx:
                long_context.plan(self.profile)
            self.assertIn('attribution', str(ctx.exception))
        with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
            value = long_context.plan(self.profile)
        self.assertEqual(value['unit_ids'], ['advanced-lc-retrieval-01',
                                             'advanced-lc-synthesis-01',
                                             'advanced-lc-retention-01'])
        self.assertEqual(value['gate']['decision'], 'ADVANCE')

    def test_exploratory_with_attribution_plans_and_preserves_standard(self):
        profile = self.profile
        profile['deployment'] = {'exploratory_authorization': {
            'operator': 'operator', 'authorization': 'handoff 2026-11-06',
            'reason': 'authorized specialist testing despite DEFERRED witness'}}
        with patch('welp_next.m3.decisions', return_value=gate_envelope(
                'EXPLORATORY', authorization=profile['deployment']['exploratory_authorization'])):
            value = long_context.plan(profile)
        self.assertEqual(value['gate']['decision'], 'EXPLORATORY')
        self.assertIsNotNone(value['gate']['exploratory'])
        self.assertEqual(value['gate']['standard_decision'], 'EXPLORATORY')

    def test_reuse_exploratory_passes_recorded_authorization_to_witness(self):
        # The real mechanism path: the recorded operator authorization is
        # passed into the evidence-bound witness computation for THIS section
        # only, and the unchanged standard eligibility (DEFERRED) is preserved
        # in the gate result rather than fabricated as ADVANCE.
        profile = self.profile
        authorization = {'operator': 'operator (handoff 2026-11-06)',
                         'authorization': 'HUMAN_DIRECTED/EXPLORATORY for the bounded '
                                          'advanced long-context inventory',
                         'reason': 'controlled reference-model verification of the section'}
        profile['deployment'] = {
            'reuse_baseline': {'campaign_root': '/accepted/m2-campaign',
                               'section_manifest_sha256': 'a' * 64},
            'exploratory_authorization': authorization}
        captured = {}
        config = {'profile': {'profile_id': 'p1', 'evidence_kind': 'MODEL_MEASURED',
                              'framework': {'methodology': policy.METHODOLOGY_M2}},
                  'profile_revision': 1, 'fixture_sha256': 'f' * 64}
        model = {'effective_scores': {}, 'coverage': {}}

        def spy(evidence, **kwargs):
            captured['exploratory'] = kwargs.get('exploratory')
            return {'result': {'decisions': {'long-context': {
                'decision': 'EXPLORATORY', 'reason': 'recorded human-directed selection',
                'exploratory_authorization': authorization,
                'standard_eligibility': {'decision': 'DEFERRED',
                                         'reason': 'context witness budget-limited'}}}}}

        with patch.object(policy, 'file_sha', return_value='a' * 64), \
             patch.object(policy, 'compatible_profiles', return_value=True), \
             patch.object(reporting, 'finalized_model_evidence',
                          return_value=(config, model)), \
             patch.object(store, 'read_json', return_value={'tasks': [
                 {'id': 'context-a', 'category': 'context'}]}), \
             patch.object(advancement, 'bound_decisions', spy):
            gate = long_context._advancement_gate(profile)
        self.assertEqual(captured['exploratory'], {'long-context': authorization})
        self.assertEqual(gate['decision'], 'EXPLORATORY')
        self.assertEqual(gate['standard_eligibility']['decision'], 'DEFERRED')
        self.assertEqual(gate['exploratory']['operator'], authorization['operator'])


class ConstructionDeterminism(unittest.TestCase):
    def test_fixture_contexts_are_deterministic_and_placement_frozen(self):
        fixture, tasks = long_context.load_tasks()
        for task in fixture['tasks']:
            self.assertGreater(task['context_words'], 5000)
            self.assertLess(task['context_chars'], 100000)
            content = task['messages'][0]['content']
            self.assertEqual(content.count('\n\n'), 1)
            self.assertTrue(content.rstrip().endswith('only the JSON object.'))
        # Every record depth is preserved in the frozen metadata.
        t1 = fixture['tasks'][0]['record_depths']
        self.assertEqual(sorted(t1.values()), [0.03, 0.22, 0.41, 0.58, 0.79, 0.96])


class ExecutionAndAttribution(unittest.TestCase):
    def _run(self, behaviors, capacity=16384, measure=None):
        workdir = support.make_workdir('lc-exec')
        campaign = workdir / 'lc-campaign'
        campaign.mkdir()
        profile = make_profile(workdir, campaign, capacity=capacity)
        fixture, tasks = long_context.load_tasks()
        payloads = {uid: payload(content) for uid, content in behaviors.items()}
        server = support.SyntheticEndpoint(tasks_by_id=tasks, payloads=payloads,
                                           echo_provider=lambda: echo_provider(profile))
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            measure = measure or (lambda profile, task, admission: 100)
            with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')), \
                 patch.object(long_context, '_native_prompt_tokens', measure):
                long_context.run(profile)
            status = long_context.status(campaign)
            report = None
            if status['state'] in ('COMPLETED', 'COMPLETED_PARTIAL'):
                with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
                    report = long_context.report_section(campaign)
            return status, report, campaign, tasks
        finally:
            server.stop()

    def test_correct_answers_pass_and_finalize(self):
        status, report, campaign, tasks = self._run(CORRECT)
        self.assertEqual(status['state'], 'COMPLETED')
        outcomes = {u['unit_id']: u['outcome'] for u in status['units']}
        self.assertEqual(outcomes, {'advanced-lc-retrieval-01': 'PASS',
                                    'advanced-lc-synthesis-01': 'PASS',
                                    'advanced-lc-retention-01': 'PASS'})
        self.assertEqual(report['disposition'], 'PASS')
        support.verify_manifest_integrity(self, campaign / 'sections' / 'advanced-long-context')

    def test_decoy_superseded_stale_answers_are_valid_fails(self):
        status, report, campaign, tasks = self._run(NEAR_MISS)
        self.assertEqual(status['state'], 'COMPLETED')
        for u in status['units']:
            self.assertEqual(u['outcome'], 'FAIL', u['unit_id'])
            self.assertIsNone(u['reason'])

    def test_empty_answers_are_unscorable_never_model_fails(self):
        behaviors = {uid: '' for uid in CORRECT}
        status, report, campaign, tasks = self._run(behaviors)
        for u in status['units']:
            self.assertEqual(u['outcome'], 'NOT_EVALUABLE')
            self.assertEqual(u['reason'], 'UNSCORABLE_ANSWER')

    def test_infeasible_geometry_is_technical_not_run_and_others_execute(self):
        # Native measurement says the retention prompt (13000 tokens) plus the
        # 4096-token reserve exceeds the 16384 capacity: a technical NOT_RUN
        # that never dispatches scored inference, while independent eligible
        # tasks execute normally (partial coverage, honestly reported).
        def measure(profile, task, admission):
            # 15900 + the 512-token test reserve exceeds the 16384 capacity,
            # while the other two prompts (100) fit comfortably.
            return 15900 if task['id'] == 'advanced-lc-retention-01' else 100
        status, report, campaign, tasks = self._run(CORRECT, measure=measure)
        self.assertEqual(status['state'], 'COMPLETED_PARTIAL')
        rows = {u['unit_id']: u for u in status['units']}
        self.assertEqual(rows['advanced-lc-retention-01']['outcome'], 'NOT_RUN')
        self.assertIn('TECHNICAL_INFEASIBLE', rows['advanced-lc-retention-01']['reason'])
        self.assertEqual(rows['advanced-lc-retention-01']['attempts'], 0)
        self.assertFalse(rows['advanced-lc-retention-01']['pending'])
        self.assertEqual(rows['advanced-lc-retrieval-01']['outcome'], 'PASS')
        self.assertEqual(rows['advanced-lc-synthesis-01']['outcome'], 'PASS')
        self.assertEqual(status['remaining_units'], [])
        section = campaign / 'sections' / 'advanced-long-context'
        receipt = store.read_json(section / 'geometry-advanced-lc-retention-01.json')
        self.assertFalse(receipt['feasible'])
        self.assertEqual(receipt['disposition'], 'TECHNICAL_INFEASIBLE_NOT_RUN')

    def test_idempotent_finalization_without_new_inference(self):
        status, report, campaign, tasks = self._run(CORRECT)
        section = campaign / 'sections' / 'advanced-long-context'
        manifest_before = (section / 'manifest.json').read_bytes()
        with patch('welp_next.m3.decisions', return_value=gate_envelope('ADVANCE')):
            again = long_context.report_section(campaign)
        self.assertTrue(again['already_finalized'])
        self.assertTrue(again['already_finalized'])
        self.assertEqual((section / 'manifest.json').read_bytes(), manifest_before)


if __name__ == '__main__':
    unittest.main()
