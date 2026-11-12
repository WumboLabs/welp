"""Evidence-bound scientific acceptance, independent of model score."""
import copy
import shutil
import unittest

from welp_next import policy, publication
import support


class ScientificAcceptance(unittest.TestCase):
    def setUp(self):
        self.work = support.make_workdir('publication-acceptance')
        self.addCleanup(lambda: shutil.rmtree(self.work))
        self.source = self.work / 'decision.txt'
        self.source.write_text('SOFTWARE_TEST human-decision source fixture; not a real acceptance.')
        self.export = {
            'campaign': 'synthetic-review-fixture',
            'disposition': 'NOT_FOR_PUBLICATION',
            'reason': 'Existing campaign visibility retained; export does not authorize publication.',
            'welp_sections': [{'section': 'coding', 'evidence_kind': 'REAL_MODEL',
                              'manifest_sha256': 'a' * 64,
                              'units': [{'outcome': 'FAIL', 'execution': 'COMPLETED'},
                                        {'outcome': 'NOT_EVALUABLE', 'reason': 'BUDGET_LIMITED'}]}]}
        self.receipt = {
            'schema': 'welp-scientific-acceptance/1', 'decision': 'HUMAN_ACCEPTED',
            'campaign_id': self.export['campaign'], 'reviewed_at': '2026-11-11',
            'basis': 'Synthetic decision used only for software validation.',
            'review_source_sha256': policy.file_sha(self.source),
            'section_manifests': {'coding': 'a' * 64}}

    def test_negative_and_budget_limited_findings_survive_acceptance(self):
        original = copy.deepcopy(self.export)
        result = publication.accepted_export(self.export, self.receipt, self.source)
        self.assertEqual(result['disposition'], 'WEBSITE_READY')
        self.assertEqual(result['welp_sections'], original['welp_sections'])
        self.assertEqual(self.export, original)
        self.assertEqual(result['scientific_acceptance']['section_manifests'], {'coding': 'a' * 64})

    def test_unaccepted_misattributed_or_changed_evidence_is_rejected(self):
        changes = [
            {'decision': 'PENDING_HUMAN_REVIEW'}, {'campaign_id': 'another-campaign'},
            {'section_manifests': {'coding': 'b' * 64}},
            {'section_manifests': {}}, {'review_source_sha256': '0' * 64}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(policy.CheckError):
                publication.accepted_export(self.export, dict(self.receipt, **change), self.source)
        self.source.write_text('Changed decision source')
        with self.assertRaises(policy.CheckError):
            publication.accepted_export(self.export, self.receipt, self.source)

    def test_invalid_coverage_and_explicit_holds_stop_publication(self):
        for update in ({'disposition': 'WEBSITE_BLOCKED'},
                       {'reason': 'Private content unresolved'}):
            with self.subTest(update=update), self.assertRaises(policy.CheckError):
                publication.accepted_export(dict(self.export, **update), self.receipt, self.source)
        invalid = copy.deepcopy(self.export)
        invalid['welp_sections'][0]['units'][0]['outcome'] = 'INVALID'
        with self.assertRaises(policy.CheckError):
            publication.accepted_export(invalid, self.receipt, self.source)

    def test_software_evidence_and_private_review_basis_cannot_publish(self):
        synthetic = copy.deepcopy(self.export)
        synthetic['welp_sections'][0]['evidence_kind'] = 'SOFTWARE_TEST'
        with self.assertRaises(policy.CheckError):
            publication.accepted_export(synthetic, self.receipt, self.source)
        receipt = dict(self.receipt, basis='Reviewer material at /home/private/review')
        with self.assertRaises(policy.CheckError):
            publication.accepted_export(self.export, receipt, self.source)

    def helicopter_v3(self):
        export = copy.deepcopy(self.export)
        section = export['welp_sections'][0]
        section.update(section='helicopterbench', methodology='helicopterbench/3',
                       objective_benchmark={'final_score': 25, 'mechanical_max': 100},
                       human_benchmark_review={
                           'state': 'FINALIZED', 'final_points': 86,
                           'human_review_sha256': 'c' * 64,
                           'unresolved_items': [], 'open_disputes': []})
        receipt = dict(self.receipt, section_manifests={'helicopterbench': 'a' * 64},
                       helicopterbench_human_review_sha256='c' * 64)
        return export, receipt

    def test_v3_acceptance_binds_human_review_without_replacing_automation(self):
        export, receipt = self.helicopter_v3()
        result = publication.accepted_export(export, receipt, self.source)
        section, = result['welp_sections']
        self.assertEqual(section['objective_benchmark']['final_score'], 25)
        self.assertEqual(section['human_benchmark_review']['final_points'], 86)
        self.assertEqual(result['scientific_acceptance']['helicopterbench_human_review_sha256'],
                         'c' * 64)
        self.assertEqual(export['disposition'], 'NOT_FOR_PUBLICATION')
        with self.assertRaisesRegex(policy.CheckError, 'exact reconciled human review'):
            publication.accepted_export(export, dict(receipt,
                helicopterbench_human_review_sha256='d' * 64), self.source)

    def test_v3_missing_unanswered_disputed_or_nonfinal_review_cannot_publish(self):
        for update in ({'state': 'DRAFT'}, {'final_points': None},
                       {'unresolved_items': ['input_causes_ascent']},
                       {'open_disputes': ['score_accrues']},
                       {'human_review_sha256': None}):
            export, receipt = self.helicopter_v3()
            export['welp_sections'][0]['human_benchmark_review'].update(update)
            with self.subTest(update=update), self.assertRaises(policy.CheckError):
                publication.accepted_export(export, receipt, self.source)
        export, receipt = self.helicopter_v3()
        del export['welp_sections'][0]['human_benchmark_review']
        with self.assertRaisesRegex(policy.CheckError, 'human review'):
            publication.accepted_export(export, receipt, self.source)

    def test_v3_no_submission_has_no_invented_human_or_gameplay_score(self):
        export, receipt = self.helicopter_v3()
        section = export['welp_sections'][0]
        section['objective_benchmark'] = {
            'final_score': None, 'mechanical_points': None, 'categories': None,
            'generation_outcome': 'NOT_EVALUABLE', 'generation_reason': 'BUDGET_LIMITED'}
        section['human_benchmark_review'] = {
            'state': 'NOT_APPLICABLE_NO_SUBMISSION', 'artifact_sha256': None,
            'final_points': None}
        receipt.pop('helicopterbench_human_review_sha256')
        accepted = publication.accepted_export(export, receipt, self.source)
        self.assertIsNone(accepted['welp_sections'][0]['objective_benchmark']['final_score'])
        self.assertIsNone(accepted['welp_sections'][0]['human_benchmark_review']['final_points'])
        self.assertNotIn('helicopterbench_human_review_sha256', accepted['scientific_acceptance'])
        section['human_benchmark_review']['artifact_sha256'] = 'd' * 64
        with self.assertRaisesRegex(policy.CheckError, 'conceal a scored game'):
            publication.accepted_export(export, receipt, self.source)

    def scoped_campaign(self):
        export, receipt = self.helicopter_v3()
        helicopter = export['welp_sections'][0]
        helicopter['human_benchmark_review'].update(
            state='DISPUTED', final_points=None, open_disputes=['score_accrues'])
        baseline = {
            'section': 'baseline', 'evidence_kind': 'REAL_MODEL',
            'manifest_sha256': 'b' * 64, 'coverage_requirement': 'full',
            'coverage': {'status': 'COMPLETE', 'categories': {
                'instruction_following': {'missing': [], 'excluded': {},
                                          'indeterminate': 0}}},
            'units': [{'unit_id': 'negative', 'outcome': 'FAIL', 'execution': 'VALID'}]}
        export['welp_sections'].append(baseline)
        receipt['section_manifests'] = {'baseline': 'b' * 64}
        receipt.pop('helicopterbench_human_review_sha256')
        receipt['excluded_sections'] = {'helicopterbench': {
            'manifest_sha256': 'a' * 64, 'status': 'DEFERRED_BY_OWNER',
            'reason': 'Owner defers the disputed experimental benchmark from this review.'}}
        return export, receipt

    def test_owner_deferred_dispute_does_not_gate_independent_findings(self):
        export, receipt = self.scoped_campaign()
        original = copy.deepcopy(export)
        result = publication.accepted_export(export, receipt, self.source)
        self.assertEqual(result['disposition'], 'WEBSITE_READY')
        self.assertEqual(result['acceptance_scope'], 'SELECTED_SECTIONS_ONLY')
        baseline, = result['welp_sections']
        self.assertEqual(baseline['units'][0]['outcome'], 'FAIL')
        excluded, = result['excluded_sections']
        self.assertEqual(excluded['section'], 'helicopterbench')
        self.assertFalse(excluded['accepted'])
        self.assertEqual(excluded['manifest_sha256'], 'a' * 64)
        self.assertNotIn('objective_benchmark', excluded)
        self.assertNotIn('human_benchmark_review', excluded)
        self.assertEqual(export, original)

    def test_scoped_review_cannot_silently_omit_or_invent_sections(self):
        for change in (
                {'excluded_sections': {}},
                {'section_manifests': {'invented': 'b' * 64}},
                {'section_manifests': {'baseline': 'c' * 64}},
                {'excluded_sections': {'helicopterbench': {
                    'manifest_sha256': 'c' * 64, 'status': 'DEFERRED_BY_OWNER',
                    'reason': 'Owner defers'}}},
                {'excluded_sections': {'helicopterbench': {
                    'manifest_sha256': 'a' * 64, 'status': 'NOT_RUN',
                    'reason': 'Owner defers'}}}):
            export, receipt = self.scoped_campaign()
            with self.subTest(change=change), self.assertRaises(policy.CheckError):
                publication.accepted_export(export, dict(receipt, **change), self.source)

    def test_mandatory_sections_cannot_be_dropped_to_hide_findings(self):
        for name in ('baseline', 'runtime-performance'):
            export, receipt = self.scoped_campaign()
            export['welp_sections'][0]['section'] = 'coding'
            export['welp_sections'][1]['section'] = name
            receipt['section_manifests'] = {'coding': 'a' * 64}
            receipt['excluded_sections'] = {name: {
                'manifest_sha256': 'b' * 64, 'status': 'DEFERRED_BY_OWNER',
                'reason': 'Hide an unwanted negative'}}
            with self.subTest(section=name), self.assertRaisesRegex(
                    policy.CheckError, 'mandatory'):
                publication.accepted_export(export, receipt, self.source)

    def test_incomplete_invalid_and_unresolved_baseline_still_block(self):
        for change in ({'missing': ['required-task']},
                       {'excluded': {'required-task': 'INTEGRATION_BLOCKED'}},
                       {'indeterminate': 1}):
            export, receipt = self.scoped_campaign()
            export['welp_sections'][1]['coverage']['categories']['instruction_following'].update(change)
            with self.subTest(change=change), self.assertRaises(policy.CheckError):
                publication.accepted_export(export, receipt, self.source)
        export, receipt = self.scoped_campaign()
        export['welp_sections'][1]['units'][0].update(outcome='INVALID', execution='INVALID')
        with self.assertRaisesRegex(policy.CheckError, 'INVALID'):
            publication.accepted_export(export, receipt, self.source)

    def test_scoped_review_preserves_budget_findings_and_publication_holds(self):
        export, receipt = self.scoped_campaign()
        baseline = export['welp_sections'][1]
        baseline['coverage']['status'] = 'COMPLETE_WITH_DOCUMENTED_LIMITATIONS'
        baseline['units'].append({'outcome': 'NOT_EVALUABLE', 'reason': 'BUDGET_LIMITED'})
        accepted = publication.accepted_export(export, receipt, self.source)
        self.assertEqual(accepted['welp_sections'][0]['units'][1]['reason'], 'BUDGET_LIMITED')
        for change in ({'disposition': 'WEBSITE_BLOCKED'}, {'reason': 'Explicit private hold'}):
            with self.subTest(change=change), self.assertRaises(policy.CheckError):
                publication.accepted_export(dict(export, **change), receipt, self.source)
        receipt['decision'] = 'PENDING_HUMAN_REVIEW'
        with self.assertRaisesRegex(policy.CheckError, 'unresolved scientific review'):
            publication.accepted_export(export, receipt, self.source)

    def test_exclusion_cannot_smuggle_private_content(self):
        export, receipt = self.scoped_campaign()
        receipt['excluded_sections']['helicopterbench']['reason'] = 'Decision at /home/private/review'
        with self.assertRaisesRegex(policy.CheckError, 'private'):
            publication.accepted_export(export, receipt, self.source)

if __name__ == '__main__':
    unittest.main()
