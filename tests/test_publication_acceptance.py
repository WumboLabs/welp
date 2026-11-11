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


if __name__ == '__main__':
    unittest.main()
