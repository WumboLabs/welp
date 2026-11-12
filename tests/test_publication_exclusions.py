"""Excluded/missing evidence remains distinct from a scored model failure."""
import copy
import shutil
import unittest

from welp_next import policy, publication
import support


class PublicationExclusions(unittest.TestCase):
    def setUp(self):
        self.work = support.make_workdir('publication-exclusions')
        self.addCleanup(lambda: shutil.rmtree(self.work))

    def attempt(self, uid, facets, *, dispatched=True):
        path = self.work / uid / '0001'
        path.mkdir(parents=True)
        (path / 'trial-boundary.json').write_text('{}')
        if dispatched:
            (path / 'generation-0001-intent.json').write_text('{}')
        return dict(policy.derive_outcome(*facets), finalized=True, path=str(path),
                    attempt_id='0001', unit_id=uid)

    def test_exclusions_and_missing_identity_never_become_zero_or_fail(self):
        reason = 'INTEGRATION_BLOCKED: native tokenizer evidence unavailable'
        config = {'unit_ids': ['missing'], 'excluded_units': {
            'context': reason, 'tool': 'UNSUPPORTED: no native tool surface'}}
        rows = {r['unit_id']: r for r in publication._unit_rows(
            config, {'missing': []}, {'context': None, 'tool': None, 'missing': None})}
        self.assertEqual(set(rows), {'missing', 'context', 'tool'})
        for row in rows.values():
            self.assertEqual(row['outcome'], 'NOT_RUN')
            self.assertEqual(row['execution'], 'NOT_RUN')
            self.assertEqual(row['scoring'], 'NOT_APPLICABLE')
            self.assertIsNone(row['original_outcome'])
            self.assertFalse(row['attempted'])
            self.assertNotIn('score', row)
        self.assertEqual(rows['context']['exclusion_reason'], reason)
        self.assertEqual(rows['context']['technical_applicability'], 'INTEGRATION_BLOCKED')
        self.assertEqual(rows['tool']['technical_applicability'], 'UNSUPPORTED')
        self.assertEqual(rows['missing']['technical_applicability'], 'APPLICABLE')
        self.assertEqual(rows['context']['coverage_impact'], 'EXCLUDED_NO_MEASUREMENT')
        self.assertEqual(rows['missing']['coverage_impact'], 'NO_FINALIZED_MEASUREMENT')

    def test_attempted_budget_limit_and_reviewed_original_are_preserved(self):
        limited = self.attempt('limited', ('VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET'))
        original = self.attempt('reviewed', ('VALID', 'COMPLETE', 'NOT_SCOREABLE', 'NONE'))
        reviewed = dict(original, **policy.derive_outcome('VALID', 'COMPLETE', 'SCORED_PASS', 'NONE'))
        units = {'limited': [limited], 'reviewed': [original]}
        before = copy.deepcopy(units)
        rows = {r['unit_id']: r for r in publication._unit_rows(
            {'unit_ids': list(units)}, units, {'limited': limited, 'reviewed': reviewed})}
        self.assertEqual(rows['limited']['reason'], 'BUDGET_LIMITED')
        self.assertEqual(rows['limited']['coverage_impact'], 'VALID_UNSCORED_MEASUREMENT')
        self.assertTrue(rows['limited']['attempted'])
        self.assertEqual(rows['reviewed']['outcome'], 'PASS')
        self.assertEqual(rows['reviewed']['original_outcome'], 'NOT_EVALUABLE')
        self.assertEqual(rows['reviewed']['original_result']['scoring'], 'NOT_SCOREABLE')
        self.assertEqual(units, before)

    def test_unsent_preparation_failure_is_not_an_attempted_model_answer(self):
        original = self.attempt('setup', ('INVALID', 'NOT_APPLICABLE', 'NOT_APPLICABLE', 'NONE'),
                                dispatched=False)
        row, = publication._unit_rows({'unit_ids': ['setup']}, {'setup': [original]},
                                      {'setup': original})
        self.assertFalse(row['attempted'])
        self.assertEqual(row['recorded_attempts'], 1)
        self.assertEqual(row['original_outcome'], 'INVALID')
        self.assertEqual(row['coverage_impact'], 'INVALID_MEASUREMENT')

    def test_configured_capacity_does_not_become_a_practical_context_claim(self):
        from test_release_validation import run_section
        campaign, profile = run_section(label='context-export')
        self.addCleanup(lambda: shutil.rmtree(campaign.parent))
        from welp_next import reporting
        reporting.report_campaign(campaign)
        export = publication.export_campaign(campaign)
        self.assertIsNone(export['context']['practical_default_tokens'])
        self.assertFalse(export['context']['envelope_complete'])
        self.assertEqual(export['context']['configured_capacity_tokens'],
                         profile['runtime']['context_capacity'])


if __name__ == '__main__':
    unittest.main()
