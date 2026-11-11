"""Capability-guided selection/reporting; advisory layer over accepted science.

All observations are manufactured SOFTWARE_TEST records; no inference, no
execution authorization and no scoring change is exercised or implied.
"""
import unittest

from welp_next import capability, policy
from test_prelive_controls import decide, evidence


def guidance(fixture, scores, **inputs):
    kind = inputs.pop('kind', 'SOFTWARE_TEST')
    advanced = decide(fixture, scores, kind=kind, **inputs)
    profile = {'evidence_kind': kind,
               'runtime': {'engine': {'name': 'synthetic'}, 'serve': {'echo_path': '/echo'},
                           'context_capacity': 16384},
               'budgets': {'max_tokens': 1024},
               'capabilities': {'native_tools': True, 'context_meter': True,
                                'sandbox': True, 'qualification_source': 'SOFTWARE_TEST',
                                'isolation_approval': 'SOFTWARE_TEST'}}
    envelope = {'methodology': advanced['rule_version'],
                'baseline': {'evidence_kind': kind,
                             'effective_scores': scores,
                             'task_categories': {task['id']: task['category']
                                                 for task in fixture['tasks']},
                             'coverage': policy.baseline_coverage(
                                 fixture, {uid: [row] for uid, row in scores.items()},
                                 profile)},
                'decisions': advanced}
    return capability.guidance(envelope)


class CapabilityGuidance(unittest.TestCase):
    def test_strong_evidence_recommends_advance_and_names_strengths(self):
        fixture, scores = evidence()
        env = guidance(fixture, scores)
        self.assertEqual(env['schema'], capability.SCHEMA)
        self.assertTrue(env['advisory_only'] and env['grants_no_execution_authority'])
        self.assertTrue(env['deferred_is_not_failed'] and env['unsupported_is_not_model_failure'])
        for section in ('coding', 'reasoning', 'long-context', 'tool-use'):
            cap = env['capabilities'][section]
            self.assertEqual(cap['applicability'], 'EVALUATED')
            self.assertIs(cap['witness'], True)
            self.assertEqual(cap['recommendation'], 'ADVANCE')
            self.assertEqual(cap['recommendation_kind'], 'EVIDENCE_GUIDED')
            self.assertFalse(cap['human_directed'])
            self.assertTrue(cap['strengths'])

    def test_weak_evidence_is_not_eligible_and_negatives_stay_visible(self):
        fixture, scores = evidence()
        scores['coding-generation-01'] = dict(policy.derive_outcome(
            'VALID', 'COMPLETE', 'SCORED_FAIL', 'NONE'), finalized=True)
        env = guidance(fixture, scores)
        cap = env['capabilities']['coding']
        self.assertEqual(cap['recommendation'], 'NOT_ELIGIBLE')
        self.assertIs(cap['witness'], False)
        self.assertIn('coding-generation-01', cap['weaknesses'])
        self.assertTrue(cap['strengths'])  # other valid passes remain visible
        self.assertGreater(env['baseline_negative_counts']['fail'], 0)

    def test_uncertain_evidence_defers_and_is_never_incompetence(self):
        fixture, scores = evidence()
        scores['coding-generation-01'] = dict(policy.derive_outcome(
            'VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET'), finalized=True)
        env = guidance(fixture, scores)
        cap = env['capabilities']['coding']
        self.assertEqual(cap['recommendation'], 'DEFERRED')
        self.assertIsNone(cap['witness'])
        self.assertIn('coding-generation-01', cap['uncertain'])
        self.assertNotIn('coding-generation-01', cap['weaknesses'])

    def test_missing_measurement_is_uncertain_not_negative(self):
        fixture, scores = evidence()
        scores.pop('reasoning-correctness-01')
        env = guidance(fixture, scores)
        cap = env['capabilities']['reasoning']
        self.assertIsNone(cap['witness'])
        self.assertEqual(cap['recommendation'], 'DEFERRED')
        self.assertIn('reasoning-correctness-01', cap['uncertain'])

    def test_human_directed_selection_preserves_standard_eligibility(self):
        fixture, scores = evidence()
        scores['coding-generation-01'] = dict(policy.derive_outcome(
            'VALID', 'COMPLETE', 'SCORED_FAIL', 'NONE'), finalized=True)
        env = guidance(fixture, scores, exploratory={
            'coding': {'operator': 'operator', 'authorization': 'assignment',
                       'reason': 'specialist interest despite weak baseline'}})
        cap = env['capabilities']['coding']
        self.assertEqual(cap['recommendation'], 'EXPLORATORY')
        self.assertEqual(cap['recommendation_kind'], 'HUMAN_DIRECTED')
        self.assertTrue(cap['human_directed'])
        self.assertEqual(cap['standard_eligibility']['decision'], 'NOT_ELIGIBLE')
        self.assertFalse(env['grants_no_execution_authority'] is False)

    def test_unsupported_category_is_reported_without_model_blame(self):
        fixture, scores = evidence()
        env = guidance(fixture, scores)
        text = capability.render(env)
        self.assertIn('unsupported interface is not a model-quality failure', text)
        self.assertIn('deferred capability is not a failed capability', text)

    def test_render_is_deterministic_and_counts_baseline_negatives(self):
        fixture, scores = evidence()
        scores['coding-generation-01'] = dict(policy.derive_outcome(
            'VALID', 'COMPLETE', 'SCORED_FAIL', 'NONE'), finalized=True)
        env = guidance(fixture, scores)
        self.assertEqual(capability.render(env), capability.render(env))
        self.assertIn('FAIL', capability.render(env))

    def test_guidance_rejects_non_decision_envelopes(self):
        for bad in ({}, {'decisions': {}}, {'methodology': 'x', 'baseline': {},
                                            'decisions': {'result': {}}}):
            with self.subTest(bad=bad):
                with self.assertRaises(policy.CheckError):
                    capability.guidance(bad)

    def test_render_rejects_wrong_schema(self):
        with self.assertRaises(policy.CheckError):
            capability.render({'schema': 'other'})

    def test_cli_helper_attaches_guidance_only_with_decisions(self):
        from welp_next import __main__ as cli_main
        fixture, scores = evidence()
        envelope = {'methodology': 'capability-witness/2', 'baseline': {},
                    'decisions': decide(fixture, scores)}
        attached = cli_main._with_guidance({'advancement': envelope})
        self.assertIn('capability_guidance', attached)
        untouched = cli_main._with_guidance({'state': 'COMPLETED'})
        self.assertNotIn('capability_guidance', untouched)


if __name__ == '__main__':
    unittest.main()
