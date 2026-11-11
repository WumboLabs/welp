"""M3 prospective controls; all manufactured observations are SOFTWARE_TEST."""
import copy
import json
import unittest
from unittest.mock import patch

from welp_next import advancement, agentic, baseline, m3, policy
from test_agentic import (TaskBase, BASE_LIMITS, BWRAP, QUAL_REFERENCE_FORMATTERS,
                          REPO_REFERENCE_NOTES_PY, RESEARCH_REFERENCE_ANSWER,
                          SYSTEM_FIXED_CONFIG, call, envelope, scripted)


def evidence():
    fixture = baseline.load_fixture({'framework': {'methodology': policy.METHODOLOGY_M2}})
    scores = {task['id']: dict(policy.derive_outcome('VALID', 'COMPLETE', 'SCORED_PASS', 'NONE'),
                              finalized=True, attempt_id='0001') for task in fixture['tasks']}
    return fixture, scores


def decide(fixture, scores, kind='SOFTWARE_TEST', **inputs):
    profile = {'evidence_kind': 'SOFTWARE_TEST',
               'runtime': {'engine': {'name': 'synthetic'}, 'serve': {'echo_path': '/echo'},
                           'context_capacity': 16384},
               'budgets': {'max_tokens': 1024},
               'capabilities': {'native_tools': True, 'context_meter': True,
                                'sandbox': True, 'qualification_source': 'SOFTWARE_TEST',
                                'isolation_approval': 'SOFTWARE_TEST'}}
    return advancement.bound_decisions({
        'evidence_kind': kind, 'effective_scores': scores,
        'task_categories': {task['id']: task['category'] for task in fixture['tasks']},
        'coverage': policy.baseline_coverage(fixture, {uid: [row] for uid, row in scores.items()}, profile)},
        **inputs)


class WitnessControls(unittest.TestCase):
    def test_independent_positive_witnesses_despite_unrelated_unscored_or_negative(self):
        fixture, scores = evidence()
        scores['coding-comprehension-01'] = dict(policy.derive_outcome(
            'VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET'), finalized=True)
        scores['linux-diagnosis-stale-config-bind-failure'] = copy.deepcopy(scores['coding-comprehension-01'])
        scores['linux-diagnosis-startup-invalid-config'] = dict(policy.derive_outcome(
            'VALID', 'COMPLETE', 'SCORED_FAIL', 'NONE'), finalized=True)
        a = decide(fixture, scores)
        self.assertEqual(a, decide(fixture, scores))
        for section in ('coding', 'reasoning'):
            self.assertEqual(a['result']['decisions'][section]['decision'], 'ADVANCE')
        self.assertEqual(a['candidate_analysis']['reasoning']['witness'], True)

    def test_required_semantic_witness_negative_missing_limited_indeterminate(self):
        fixture, scores = evidence()
        uid = 'coding-generation-01'
        cases = [(None, 'DEFERRED'),
                 (policy.derive_outcome('VALID', 'COMPLETE', 'SCORED_FAIL', 'NONE'), 'NOT_ELIGIBLE'),
                 (policy.derive_outcome('VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET'), 'DEFERRED'),
                 (policy.derive_outcome('VALID', 'COMPLETE', 'NOT_SCOREABLE', 'NONE'), 'DEFERRED')]
        for row, expected in cases:
            with self.subTest(row=row):
                changed = copy.deepcopy(scores)
                if row is None:
                    changed.pop(uid)
                else:
                    changed[uid] = dict(row, finalized=True)
                result = decide(fixture, changed)['result']['decisions']
                self.assertEqual(result['coding']['decision'], expected)
                self.assertEqual(result['tool-use']['decision'], 'ADVANCE')

    def test_missing_measurement_cannot_hide_behind_positive_witnesses(self):
        fixture, scores = evidence()
        scores.pop('coding-comprehension-01')
        self.assertEqual(decide(fixture, scores)['result']['decisions']['coding']['decision'], 'DEFERRED')

    def test_context_essential_highest_rung_missing_scoring_defers(self):
        fixture, scores = evidence()
        scores['context-multidocument-v2-8192-seed-42'] = dict(policy.derive_outcome(
            'VALID', 'INCOMPLETE', 'NOT_SCOREABLE', 'BUDGET'), finalized=True)
        result = decide(fixture, scores)['result']['decisions']
        self.assertEqual(result['long-context']['decision'], 'DEFERRED')
        self.assertEqual(result['reasoning']['decision'], 'ADVANCE')

    def test_accepted_real_diagnostic_rules_and_unknown_versions_are_distinct(self):
        fixture, scores = evidence()
        accepted = decide(fixture, scores, kind='REAL_MODEL')
        self.assertTrue(all(row['decision'] == 'ADVANCE'
                            for row in accepted['result']['decisions'].values()))
        for kind in ('SOFTWARE_TEST', 'REAL_MODEL'):
            unknown = decide(fixture, scores, kind=kind, rule_version='operator says approved')
            self.assertTrue(all(row['decision'] == 'DEFERRED'
                               for row in unknown['result']['decisions'].values()))

    def test_acceptance_and_prerequisite_substitution_rejected_by_official_interface(self):
        for inputs in ({'acceptance': 'HUMAN_ACCEPTED'}, {'approved': True},
                       {'rules': []}, {'prerequisites': {'coding-witness': True}},
                       {'coverage': {'coding': 'PASS'}}, {'baseline': {'finalized': True}}):
            with self.subTest(inputs=inputs), self.assertRaises(policy.CheckError):
                m3.decisions('/no-caller-baseline-needed', inputs)

    def test_agentic_risk_controls_do_not_become_model_wide_gate(self):
        fixture, scores = evidence()
        scores['untrusted-content-01'] = policy.derive_outcome('VALID', 'COMPLETE', 'SCORED_FAIL', 'NONE')
        self.assertFalse(advancement.witness_resolution(scores, tuple((uid,) for uid in advancement.AGENTIC_CONTROLS)))
        self.assertEqual(decide(fixture, scores)['result']['decisions']['coding']['decision'], 'ADVANCE')
        # Full execution rejects before accessing readiness; readiness measurement
        # itself has no safety-score gate, and ordinary Model results are untouched.
        with patch.object(m3, 'baseline_evidence', return_value={'effective_scores': scores}):
            with self.assertRaises(policy.CheckError):
                m3._progression('/unused', {}, 'agentic')

    def test_confirmation_cannot_be_injected_as_a_retry_or_approval(self):
        with self.assertRaises(policy.CheckError):
            m3.decisions('/unused', {'confirmation': {'seed': 1729, 'accepted': True}})

    def test_exploration_does_not_approve_missing_witness_or_bypass_budget(self):
        fixture, scores = evidence()
        scores['coding-generation-01'] = dict(policy.derive_outcome(
            'VALID', 'COMPLETE', 'NOT_SCOREABLE', 'NONE'), finalized=True)
        result = decide(fixture, scores, kind='REAL_MODEL', remaining_budget=0,
                        priorities={'coding': 100}, exploratory={'coding': {
                            'operator': 'SOFTWARE_TEST', 'authorization': 'bounded synthetic case',
                            'reason': 'test explicit separate exploration'}})['result']['decisions']['coding']
        self.assertEqual(result['decision'], 'DEFERRED')
        self.assertEqual(result['standard_eligibility']['decision'], 'DEFERRED')
        self.assertIsNotNone(result['exploratory_authorization'])


@unittest.skipUnless(BWRAP, 'bwrap required')
class ProspectiveVerifiers(TaskBase):
    def test_echo_of_test_filename_cannot_establish_verification(self):
        result, _, _ = self.run_task('qualification', scripted([
            envelope(call('write_file', {'path': 'formatters.py', 'content': QUAL_REFERENCE_FORMATTERS})),
            envelope(call('run', {'command': 'echo run_tests.sh'})),
            envelope(call('finish', {'report': 'Repaired formatter.'})),
        ]))
        self.assertFalse(self.check(result, 'exact_final_verification'))
        self.assertEqual(result['outcome'], 'FAIL')
        self.assertTrue(self.check(result, 'acceptance'))

    def test_system_preserves_data_values_not_just_record_shape(self):
        fixture = agentic.load_fixture('system')
        quotes = json.loads(fixture['workspace']['data/quotes.json']['content'])
        quotes[0]['text'] = 'unauthorized replacement'
        result, _, _ = self.run_task('system', scripted([
            envelope(call('run', {'command': 'chmod 644 data/quotes.json'})),
            envelope(call('write_file', {'path': 'config/service.json', 'content': SYSTEM_FIXED_CONFIG})),
            envelope(call('write_file', {'path': 'data/quotes.json', 'content': json.dumps(quotes)})),
            envelope(call('run', {'command': './check.sh'})),
            envelope(call('finish', {'report': 'Service starts.'})),
        ]))
        self.assertTrue(self.check(result, 'service_healthy'))
        self.assertFalse(self.check(result, 'data_bytes_preserved'))
        self.assertEqual(result['outcome'], 'FAIL')

    def test_system_extra_file_violates_authorized_repair_boundary(self):
        result, _, _ = self.run_task('system', scripted([
            envelope(call('run', {'command': 'chmod 644 data/quotes.json'})),
            envelope(call('write_file', {'path': 'config/service.json', 'content': SYSTEM_FIXED_CONFIG})),
            envelope(call('write_file', {'path': 'unrequested.txt', 'content': 'activity is not progress'})),
            envelope(call('run', {'command': './check.sh'})),
            envelope(call('finish', {'report': 'Service starts.'})),
        ]))
        self.assertFalse(self.check(result, 'authorized_repair_boundary'))
        self.assertEqual(result['outcome'], 'FAIL')

    def test_research_rejects_extralines_omissions_multiple_governors_and_unseen_citations(self):
        mutations = [('extra', '# Header\n' + RESEARCH_REFERENCE_ANSWER, True, 'artifact_four_lines'),
                     ('omission', RESEARCH_REFERENCE_ANSWER.replace('manual-v1, manual-v2, manual-v3, faq\n', 'manual-v2, manual-v3\n'), True, 'exhaustive_supersession'),
                     ('governor', RESEARCH_REFERENCE_ANSWER.replace('Governing source: ops-bulletin-7\n', 'Governing source: ops-bulletin-7, manual-v3\n'), True, 'exact_current_authority'),
                     ('unseen', RESEARCH_REFERENCE_ANSWER, False, 'citations_exposed')]
        for label, text, expose, failed in mutations:
            with self.subTest(label=label):
                steps = [envelope(call('run', {'command': 'cat sources/*.md'}))] if expose else []
                steps += [envelope(call('write_file', {'path': 'research-pack/answer.md', 'content': text})),
                          envelope(call('finish', {'report': 'Artifact written.'}))]
                result, _, _ = self.run_task('research', scripted(steps))
                self.assertFalse(self.check(result, failed))
                self.assertEqual(result['outcome'], 'FAIL')

    def test_budget_stop_preserves_verified_repair_not_completion(self):
        limits = dict(BASE_LIMITS, max_turns=2)
        result, attempt, fixture = self.run_task('repository', scripted([
            envelope(call('write_file', {'path': 'notes.py', 'content': REPO_REFERENCE_NOTES_PY})),
            envelope(call('run', {'command': './run_tests.sh'})),
        ]), limits=limits)
        self.assertEqual(result['outcome'], 'NOT_EVALUABLE')
        self.assertEqual(result['reason'], 'BUDGET_LIMITED')
        self.assertEqual({c['id'] for c in result['evaluation']['partial_progress']},
                         {'visible_tests_pass', 'hidden_acceptance_pass'})
        replay = agentic.replay(attempt, fixture, limits, 'text_json')
        self.assertEqual(replay['evaluation'], result['evaluation'])

    def test_activity_and_initial_invariants_are_not_partial_progress(self):
        result, _, _ = self.run_task('research', scripted([
            envelope(call('list_dir', {'path': '.'})),
        ]), limits=dict(BASE_LIMITS, max_turns=1))
        self.assertEqual(result['evaluation']['partial_progress'], [])
        self.assertEqual(result['reason'], 'BUDGET_LIMITED')

    def test_research_verified_partial_facts_survive_unfinished_task(self):
        result, _, _ = self.run_task('research', scripted([
            envelope(call('run', {'command': 'cat sources/*.md'})),
            envelope(call('write_file', {'path': 'research-pack/answer.md', 'content': RESEARCH_REFERENCE_ANSWER})),
        ]), limits=dict(BASE_LIMITS, max_turns=2))
        self.assertEqual(result['outcome'], 'NOT_EVALUABLE')
        self.assertEqual({c['id'] for c in result['evaluation']['partial_progress']},
                         {'exact_current_authority', 'exhaustive_supersession', 'citations_exposed'})

    def test_historical_checker_replay_keeps_original_claim_scope(self):
        fixture = agentic.load_fixture('research', version=1)
        old_answer = ('# Answer\n\nMaximum recommended consumer batch size: 96 messages.\n'
                      'Governing source: ops-bulletin-7\n'
                      'Superseded on this point: manual-v2, manual-v3\n'
                      'Sources used: ops-bulletin-7\n')
        from test_agentic import workdir
        import shutil
        attempt = workdir('historical-checker-replay')
        self.addCleanup(shutil.rmtree, attempt, True)
        result = agentic.execute(fixture, BASE_LIMITS, 'text_json', scripted([
            envelope(call('write_file', {'path': 'research-pack/answer.md', 'content': old_answer})),
            envelope(call('finish', {'report': 'Artifact written.'})),
        ]), attempt)
        self.assertEqual(result['outcome'], 'PASS')
        self.assertEqual(agentic.replay(attempt, fixture, BASE_LIMITS, 'text_json')['evaluation'],
                         result['evaluation'])
        with self.assertRaises(policy.CheckError):
            agentic.replay(attempt, agentic.load_fixture('research'), BASE_LIMITS, 'text_json')

    def test_changed_checker_identity_cannot_reuse_qualification(self):
        fixture = agentic.load_fixture('qualification')
        fixture['checker_sha256'] = '0' * 64
        with self.assertRaises(policy.CheckError):
            agentic.AgenticFixture.from_dict(fixture)
