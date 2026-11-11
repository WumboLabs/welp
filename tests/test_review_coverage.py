"""Consumer-visible review binding, ambiguity and mechanical/semantic boundaries."""
import copy
import tempfile
import unittest
from pathlib import Path

from welp_next import policy, review, store


class ReviewTest(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / 'tmp/m2-model-baseline/tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.section = Path(self.temp.name) / 'sections/baseline'
        self.task = {'id': 'subjective', 'scorer': 'rubric', 'category': 'reasoning',
                     'messages': [{'role': 'user', 'content': 'What is established?'}],
                     'rubric': 'Do not claim that absent health evidence establishes health.'}
        self.score = policy.derive_outcome('VALID', 'COMPLETE', 'NOT_SCOREABLE', 'NONE')
        self.score.update(unit_id='subjective', attempt_id='0001', profile_revision='a'*64,
                          record={'review_required': True, 'mechanical_pass': True})
        self.path = self.section / 'evidence/subjective/0001'
        store.put_json(self.section / 'fixture.json', {'tasks': [self.task]})
        store.put_json(self.section / 'run.json', {'unit_ids': ['subjective'],
                       'profile_revision': 'a'*64})
        store.put_json(self.path / 'request.json', {'messages': self.task['messages']})
        store.put_json(self.path / 'response.raw', {'choices': [{'message': {
                       'content': 'Present health is not established by the provided evidence.'}}]})
        store.put_json(self.path / 'conditions.json', {'profile_revision': 'a'*64,
                       'request_limits': {}, 'evidence_kind': 'SOFTWARE_TEST',
                       'preflight': {'echo': {}}})
        store.finalize_attempt(self.path, self.score)

    def package(self, disposition='PASS', reviewer_id='independent-software-fixture'):
        corpus = store.read_json(review.QUALIFICATION)
        qualification = {'fixture_sha256': policy.file_sha(review.QUALIFICATION),
            'answers': [{'case_id': c['id'], 'disposition': c['expected_disposition'],
                         'rationale': c['deciding_rule']['quote'],
                         'evidence': [c['visible_answer']] if c['visible_answer'] else []}
                        for c in corpus['cases']]}
        target = review.pending_packets(self.section)[0]
        return {'schema_version': 1, 'reviewer': {'id': reviewer_id,
                'independent_of_execution': True, 'model_identity_blinded': True,
                'provenance': 'SOFTWARE_TEST review-boundary fixture, not a live evaluator',
                'qualification': qualification},
                'reviews': [{'unit_id': 'subjective', 'packet_sha256': target['packet_sha256'],
                  'disposition': disposition, 'rationale': 'The visible answer explicitly denies established health.',
                  'evidence': ['health is not established']}]}

    def apply(self, package, name):
        path = Path(self.temp.name) / name
        store.put_json(path, package)
        review.import_reviews(self.section, path)

    def effective(self):
        fixture = store.read_json(self.section / 'fixture.json')
        _, units = store.inventory(self.section)
        return review.effective_scores(self.section, fixture, units)['subjective']

    def test_independent_review_preserves_original_and_binds_target(self):
        before = {p.name: policy.file_sha(p) for p in self.path.iterdir()}
        package = self.package()
        self.apply(package, 'review.json')
        self.assertEqual(self.effective()['outcome'], 'PASS')
        self.assertEqual(before, {p.name: policy.file_sha(p) for p in self.path.iterdir()})
        tampered = copy.deepcopy(package)
        tampered['reviews'][0]['packet_sha256'] = 'b'*64
        with self.assertRaisesRegex(policy.CheckError, 'binding'):
            self.apply(tampered, 'tampered.json')

    def test_false_quotation_and_unqualified_reviewer_rejected(self):
        package = self.package()
        package['reviews'][0]['evidence'] = ['The service is healthy.']
        with self.assertRaisesRegex(policy.CheckError, 'quotation'):
            self.apply(package, 'false-quote.json')
        package = self.package()
        package['reviewer']['qualification']['answers'][0]['disposition'] = 'FAIL'
        with self.assertRaisesRegex(policy.CheckError, 'qualification'):
            self.apply(package, 'unqualified.json')

    def test_bounded_ambiguity_requires_distinct_independent_reviewer(self):
        self.apply(self.package('NOT_EVALUABLE'), 'ambiguous.json')
        self.assertEqual(self.effective()['reason'], 'RUBRIC_INDETERMINATE')
        with self.assertRaisesRegex(policy.CheckError, 'distinct'):
            self.apply(self.package('PASS'), 'same-reviewer.json')
        self.apply(self.package('PASS', 'second-evaluator'), 'second.json')
        self.assertEqual(self.effective()['outcome'], 'PASS')
        with self.assertRaisesRegex(policy.CheckError, 'at most two'):
            self.apply(self.package('PASS', 'third-evaluator'), 'third.json')

    def test_unrequested_escalation_cannot_replace_unfavorable_result(self):
        self.apply(self.package('FAIL'), 'negative.json')
        with self.assertRaisesRegex(policy.CheckError, 'not ambiguous'):
            self.apply(self.package('PASS', 'another-evaluator'), 'reroll.json')
        self.assertEqual(self.effective()['outcome'], 'FAIL')

    def test_missing_review_is_not_positive_evidence(self):
        self.assertEqual(self.effective()['reason'], 'RUBRIC_INDETERMINATE')
        self.assertEqual(self.effective()['scoring'], 'NOT_SCOREABLE')

    def test_primary_and_bounded_escalation_import_together_before_finalization(self):
        self.apply([self.package('NOT_EVALUABLE'),
                    self.package('PASS', 'independent-escalation')], 'review-bundle.json')
        effective = self.effective()
        self.assertEqual(effective['outcome'], 'PASS')
        self.assertEqual(len(effective['review']['judgments']), 2)


class ReviewerPreparationTest(unittest.TestCase):
    """Anonymous reviewer-facing preparation: the transport carries no
    unit/campaign/profile/model/transport-path metadata and no prior
    score/verdict fields; the private attribution map binds anonymous
    outputs to exact pending packets; known identity tokens fail closed."""

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / 'tmp/m2-model-baseline/tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.scratch = scratch
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.transport = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.transport.cleanup)
        self.section = Path(self.temp.name) / 'sections/baseline'
        self.task = {'id': 'subjective', 'scorer': 'rubric', 'category': 'reasoning',
                     'messages': [{'role': 'user', 'content': 'What is established?'}],
                     'rubric': 'Do not claim that absent health evidence establishes health.'}
        self.answer = 'Present health is not established by the provided evidence.'
        self.path = self.section / 'evidence/subjective/0001'
        self.seed({'review_required': True, 'mechanical_pass': True})

    def seed(self, record):
        score = policy.derive_outcome('VALID', 'COMPLETE', 'NOT_SCOREABLE', 'NONE')
        score.update(unit_id='subjective', attempt_id='0001', profile_revision='a'*64,
                     record=record)
        store.put_json(self.section / 'fixture.json', {'tasks': [self.task]})
        store.put_json(self.section / 'run.json',
                       {'unit_ids': ['subjective'], 'profile_revision': 'a'*64})
        store.put_json(self.path / 'request.json', {'messages': self.task['messages']})
        store.put_json(self.path / 'response.raw',
                       {'choices': [{'message': {'content': self.answer}}]})
        store.put_json(self.path / 'conditions.json', {'profile_revision': 'a'*64,
                       'request_limits': {}, 'evidence_kind': 'SOFTWARE_TEST',
                       'preflight': {'echo': {}}})
        store.finalize_attempt(self.path, score)

    def add_profile(self, profile):
        """Attach a profile to the seeded section (run.json is append-only)."""
        config = store.read_json(self.section / 'run.json')
        config['profile'] = profile
        (self.section / 'run.json').unlink()
        store.put_json(self.section / 'run.json', config)

    def section_with(self, record):
        temp = tempfile.TemporaryDirectory(dir=self.scratch)
        self.addCleanup(temp.cleanup)
        section = Path(temp.name) / 'sections/baseline'
        score = policy.derive_outcome('VALID', 'COMPLETE', 'NOT_SCOREABLE', 'NONE')
        score.update(unit_id='subjective', attempt_id='0001', profile_revision='a'*64,
                     record=record)
        path = section / 'evidence/subjective/0001'
        store.put_json(section / 'fixture.json', {'tasks': [self.task]})
        store.put_json(section / 'run.json',
                       {'unit_ids': ['subjective'], 'profile_revision': 'a'*64})
        store.put_json(path / 'request.json', {'messages': self.task['messages']})
        store.put_json(path / 'response.raw',
                       {'choices': [{'message': {'content': self.answer}}]})
        store.put_json(path / 'conditions.json', {'profile_revision': 'a'*64,
                       'request_limits': {}, 'evidence_kind': 'SOFTWARE_TEST',
                       'preflight': {'echo': {}}})
        store.finalize_attempt(path, score)
        return section

    def reviewer(self):
        corpus = store.read_json(review.QUALIFICATION)
        return {'id': 'independent-software-fixture',
                'independent_of_execution': True, 'model_identity_blinded': True,
                'provenance': 'SOFTWARE_TEST review-boundary fixture, not a live evaluator',
                'qualification': {'fixture_sha256': policy.file_sha(review.QUALIFICATION),
                    'answers': [{'case_id': c['id'], 'disposition': c['expected_disposition'],
                                 'rationale': c['deciding_rule']['quote'],
                                 'evidence': [c['visible_answer']] if c['visible_answer'] else []}
                                for c in corpus['cases']]}}

    def judgment(self, **extra):
        target = review.pending_packets(self.section)[0]
        row = {'review_id': review.reference(target['packet_sha256']),
               'packet_sha256': target['packet_sha256'], 'disposition': 'PASS',
               'rationale': 'The visible answer explicitly denies established health.',
               'evidence': ['health is not established']}
        row.update(extra)
        return {'schema_version': 1, 'reviewer': self.reviewer(), 'reviews': [row]}

    def apply(self, package, name):
        path = Path(self.temp.name) / name
        store.put_json(path, package)
        review.import_reviews(self.section, path)

    def effective(self):
        fixture = store.read_json(self.section / 'fixture.json')
        _, units = store.inventory(self.section)
        return review.effective_scores(self.section, fixture, units)['subjective']

    def test_preparation_is_anonymous_and_attribution_binds_privately(self):
        targets = review.pending_packets(self.section)
        transport = review.prepare(self.section)
        self.assertEqual(set(transport), {'rubric_contract', 'packets'})
        self.assertEqual([set(t) for t in targets],
                         [{'unit_id', 'packet_sha256', 'packet'}])
        # Historical canonical packet shape and hashes are unchanged.
        packet = targets[0]['packet']
        self.assertEqual(set(packet), set(review.REVIEWER_PACKET_KEYS) | {'binding'})
        self.assertEqual(set(packet['binding']),
                         {'unit_id', 'attempt_id', 'request_sha256', 'response_sha256'})
        self.assertEqual(targets[0]['packet_sha256'], policy.digest(packet))
        safe = set(review.REVIEWER_PACKET_KEYS) | {'review_id', 'packet_sha256'}
        self.assertEqual(set(transport['packets'][0]), safe)
        text = policy.canonical(transport).decode()
        for fragment in ('"unit_id"', '"attempt_id"', '"binding"', '"outcome"',
                         '"reason"', '"disposition"', '"scoring"', '"semantic"',
                         '"mechanical_pass"', '"check_pass"', '"decisive_pass"',
                         '"_facets"', '"campaign"', '"model"', '"profile"',
                         'evidence/', str(self.section)):
            self.assertNotIn(fragment, text)
        self.assertNotIn('attribution', transport)
        row = review.attribution(self.section)[transport['packets'][0]['review_id']]
        self.assertEqual(row, {'unit_id': targets[0]['unit_id'],
                               'attempt_id': targets[0]['packet']['binding']['attempt_id'],
                               'packet_sha256': targets[0]['packet_sha256']})
        withheld = transport['packets'][0]['mechanical_task_outcome']
        self.assertNotIn('mechanical_pass', withheld)
        self.assertNotIn('review_required', withheld)

    def test_prior_score_metadata_is_withheld_but_facts_retained(self):
        record = {'review_required': True, 'mechanical_pass': True,
                  'check_pass': True, 'decisive_pass': True, 'semantic': 'PASS',
                  'pass': True, '_facets': ['VALID', 'COMPLETE', 'SCORED_PASS', 'NONE'],
                  'gates': {'exact_retrieval': True},
                  'review_evidence': {'mentions': True}, 'case_id': 'case-01',
                  'review_reason': 'RUBRIC_INDETERMINATE: detail prose requires review',
                  'word_count': 11, 'word_limit': 40}
        projection = review.prepare(self.section_with(record))['packets'][0]
        self.assertEqual(projection['mechanical_task_outcome'],
                         {'word_count': 11, 'word_limit': 40})
        self.assertEqual(projection['outgoing_messages'], self.task['messages'])
        self.assertEqual(projection['visible_answer'], self.answer)
        self.assertEqual(projection['completion_state'], 'COMPLETE')

    def test_known_identity_in_original_content_is_rejected_not_redacted(self):
        original = review.pending_packets(self.section)[0]
        for field, value in (
                ('visible_answer', 'I am GEMMA, a model by Google.'),
                ('outgoing_messages', [{'role': 'user', 'content': 'This run uses gEmMa.'}])):
            target = copy.deepcopy(original)
            target['packet'][field] = value
            before = copy.deepcopy(target)
            with self.assertRaisesRegex(policy.CheckError, 'identifying original content'):
                review.projection(target, markers=('gemma', 'Google'))
            self.assertEqual(target, before)

    def test_structured_rubric_selectors_export_without_private_attribution(self):
        rubric = {'boundary_constraints': [
            {'kind': 'sentence_count', 'path': ['root_cause', 'detail'],
             'min': 1, 'max': 2}]}
        self.task['rubric'] = rubric
        section = self.section_with({'review_required': True, 'rubric': rubric,
                                     'mechanical_pass': True})
        destination = Path(self.transport.name) / 'structured-review.json'
        review.export(section, destination)
        packet = store.read_json(destination)['packets'][0]
        self.assertEqual(packet['review_dimension'], rubric)
        self.assertEqual(packet['outgoing_messages'], self.task['messages'])
        self.assertEqual(packet['visible_answer'], self.answer)
        self.assertEqual(packet['mechanical_task_outcome'], {})
        self.assertNotIn('binding', packet)
        # Rubric prose still cannot disclose a known model identity.
        target = review.pending_packets(section)[0]
        target['packet']['review_dimension']['note'] = 'Uses GEMMA'
        with self.assertRaisesRegex(policy.CheckError, 'identifying original content'):
            review.projection(target, markers=('gemma',))

    def test_prepare_fails_closed_on_identity_bearing_metadata(self):
        for record in ({'review_required': True, 'campaign': 'campaign-gemma-4-12b'},
                       {'review_required': True,
                        'evidence_path': '/home/operator/campaign-gemma/evidence/subjective'},
                       {'review_required': True,
                        'note': '/home/operator/models-active/gemma/gemma.gguf'}):
            section = self.section_with(record)
            with self.assertRaisesRegex(policy.CheckError, 'review.preparation'):
                review.prepare(section)
            with self.assertRaisesRegex(policy.CheckError, 'operator review'):
                review.export(section, Path(self.transport.name) / 'review-packets.json')

    def test_export_refuses_incident_class_and_identity_bearing_paths(self):
        self.add_profile({'model': {
            'model_key': 'gemma-4-12b',
            'artifact': {'path': '/home/operator/models-active/gemma-4-12b/'
                                 'gemma-4-12b-it-UD-Q4_K_XL.gguf'}}})
        destination = Path(self.transport.name) / 'review-packets.json'
        result = review.export(self.section, destination)
        self.assertEqual(result['packets'], 1)
        self.assertEqual(result['transport'], str(destination))
        self.assertEqual(store.read_json(destination), review.prepare(self.section))
        self.assertNotIn('attribution', store.read_json(destination))
        self.assertTrue(result['instruction'].strip())
        self.assertEqual(result['attribution'][list(result['attribution'])[0]]['unit_id'],
                         'subjective')
        # The 2026-11-09 incident class: a family-bearing ancestor directory
        # that is not the campaign name itself.
        incident = Path(self.transport.name) / 'v1-gemma-fresh-authentic-2026-11-09' / 'review.json'
        with self.assertRaisesRegex(policy.CheckError, 'review.export.transport'):
            review.export(self.section, incident)
        campaign = self.section.parent.parent
        for candidate in (campaign / 'review-packets.json',
                          self.section / 'review-packets.json',
                          Path(self.transport.name) / 'review-subjective-0001.json'):
            with self.assertRaisesRegex(policy.CheckError, 'review.export.transport'):
                review.export(self.section, candidate)
        self.assertFalse(incident.exists())
        alias = Path(self.transport.name) / 'neutral-alias'
        alias.symlink_to(campaign, target_is_directory=True)
        with self.assertRaisesRegex(policy.CheckError, 'review.export.transport'):
            review.export(self.section, alias / 'review-packets.json')
        # Publish-if-absent: an existing transport is never rewritten.
        before = policy.file_sha(destination)
        with self.assertRaises(OSError):
            review.export(self.section, destination)
        self.assertEqual(policy.file_sha(destination), before)

    def test_anonymous_submission_binds_and_resolves_through_attribution(self):
        package = self.judgment()
        self.apply(package, 'review.json')
        self.assertEqual(self.effective()['outcome'], 'PASS')
        decision = self.effective()['review']['judgments'][0]
        target = review.pending_packets(self.section)[0]
        self.assertEqual(decision['review_id'], review.reference(target['packet_sha256']))
        self.assertEqual(review.attribution(self.section)[decision['review_id']]['unit_id'],
                         'subjective')
        tampered = copy.deepcopy(package)
        tampered['reviews'][0]['packet_sha256'] = 'b'*64
        with self.assertRaisesRegex(policy.CheckError, 'binding'):
            self.apply(tampered, 'tampered.json')
        with self.assertRaisesRegex(policy.CheckError, 'unknown or duplicate'):
            self.apply(self.judgment(review_id='0'*64), 'unknown.json')
        with self.assertRaisesRegex(policy.CheckError, 'review.reference'):
            self.apply(self.judgment(unit_id='subjective'), 'bound.json')
        self.assertEqual(len(list((self.section / 'reviews').glob('*.json'))), 1)

    def test_import_rejects_identity_and_prior_verdict_submission_fields(self):
        for index, extra in enumerate(({'evidence_path': str(self.path)},
                                       {'campaign': 'campaign-gemma-4-12b-fresh'},
                                       {'semantic': 'PASS'}, {'outcome': 'SCORED_PASS'},
                                       {'mechanical_pass': True})):
            with self.assertRaisesRegex(policy.CheckError, 'review.submission'):
                self.apply(self.judgment(**extra), f'rejected-{index}.json')
        self.assertFalse(list((self.section / 'reviews').glob('*.json')))


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.profile = {'framework': {'methodology': policy.METHODOLOGY_M2},
                        'runtime': {'context_capacity': 8192,
                                    'engine': {'name': 'software'},
                                    'serve': {'echo_path': '/echo'}},
                        'budgets': {'max_tokens': 1024},
                        'capabilities': {}}

    def row(self, scoring='SCORED_FAIL'):
        return dict(policy.derive_outcome('VALID', 'COMPLETE', scoring, 'NONE'), finalized=True)

    def test_negative_results_satisfy_measurement_not_missing_measurements(self):
        fixture = {'tasks': [{'id': 'logic', 'category': 'reasoning'},
                             {'id': 'code', 'category': 'coding'}]}
        result = policy.baseline_coverage(fixture, {'logic': [self.row()]}, self.profile)
        self.assertTrue(result['categories']['reasoning']['minimum_scoring_coverage_met'])
        self.assertEqual(result['categories']['reasoning']['fail'], 1)
        self.assertEqual(result['categories']['coding']['missing'], ['code'])
        self.assertEqual(result['status'], 'PARTIALLY_COMPLETE')

    def test_unsupported_interface_does_not_erase_independent_capability(self):
        fixture = {'tasks': [{'id': 'logic', 'category': 'reasoning'},
                             {'id': 'tool', 'category': 'tool_use', 'requires': ['native_tools']}]}
        result = policy.baseline_coverage(fixture, {'logic': [self.row()]}, self.profile)
        self.assertEqual(result['categories']['reasoning']['status'], 'COMPLETE')
        tool = result['categories']['tool_use']
        self.assertEqual(tool['status'], 'UNSUPPORTED_OR_NON_EVALUABLE')
        self.assertEqual(tool['measured'], 0)
        self.assertFalse(tool['minimum_measurement_coverage_met'])

    def test_budget_exhaustion_is_measured_but_never_scored(self):
        fixture = {'tasks': [{'id': 'logic', 'category': 'reasoning'}]}
        budget = dict(policy.derive_outcome('VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET'), finalized=True)
        result = policy.baseline_coverage(fixture, {'logic': [budget]}, self.profile)['categories']['reasoning']
        self.assertEqual((result['measured'], result['scored'], result['fail']), (1, 0, 0))
        self.assertTrue(result['minimum_measurement_coverage_met'])
        self.assertFalse(result['minimum_scoring_coverage_met'])

    def test_attempt_history_never_duplicates_scientific_credit(self):
        fixture = {'tasks': [{'id': 'logic', 'category': 'reasoning'}]}
        result = policy.baseline_coverage(fixture, {'logic': [self.row(), self.row()]}, self.profile)
        self.assertEqual(result['categories']['reasoning']['measured'], 1)
        self.assertEqual(result['categories']['reasoning']['scored'], 1)
