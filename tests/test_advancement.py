"""Advancement decision science: rule-bound eligibility, unresolved-evidence
deferral, scheduling and exploratory boundaries (SPEC §4.2, §12).

Pure offline tests over the real ``policy.baseline_coverage`` producer: no
endpoint, no store, no fixture execution. Every deciding number in these
tests is an explicitly configured test rule — the module under test supplies
no official numeric defaults, and none asserted here is one.
"""
import copy
import json
import unittest

from welp_next import advancement, policy


def attempt(completion='COMPLETE', scoring='SCORED_PASS', limits='NONE'):
    """One finalized producer-shaped attempt row (§5.1 facets via policy)."""
    row = policy.derive_outcome('VALID', completion, scoring, limits)
    row['finalized'] = True
    return row


def producer_coverage(categories):
    """Real policy.baseline_coverage result over a synthetic inventory.

    ``categories`` maps category name to a list of attempt rows; a None entry
    leaves that identity unmeasured (missing evidence).
    """
    tasks, units = [], {}
    for category, specs in categories.items():
        for index, spec in enumerate(specs):
            uid = f'{category}-{index}'
            tasks.append({'id': uid, 'category': category, 'messages': []})
            if spec is not None:
                units[uid] = [spec]
    return policy.baseline_coverage({'tasks': tasks}, units, {})


def rule(rule_id='coding-rule', sections=('coding',), evidence_class='SOFTWARE_TEST',
         required=None, prerequisites=()):
    """A valid declarative test rule with explicit provenance bindings."""
    return {'rule_id': rule_id, 'sections': list(sections),
            'evidence_class': evidence_class,
            'source': 'worker test proposal (not an official threshold)',
            'acceptance': 'operator-accepted for this test only',
            'required_categories': required or {
                'coding': {'min_measured': 1, 'min_passes': 1}},
            'critical_prerequisites': list(prerequisites)}


def authorization(section='coding'):
    return {section: {'operator': 'test-operator',
                      'authorization': 'OP-TEST-2026-10-22',
                      'reason': 'bounded research question, not eligibility'}}


class AdvancementTest(unittest.TestCase):

    def decide(self, coverage, *args, **kwargs):
        return advancement.decide(coverage, *args, **kwargs)

    # --------------------------------------------------------------- shape

    def test_no_rules_defers_every_section_with_calibration_reason(self):
        coverage = producer_coverage({'coding': [attempt()]})
        envelope = self.decide(coverage, evidence_kind='SOFTWARE_TEST')
        self.assertEqual(set(envelope), {'schema', 'evidence_kind', 'inputs',
                                         'decisions'})
        self.assertEqual(sorted(envelope['decisions']),
                         ['coding', 'long-context', 'reasoning', 'tool-use'])
        for section, decision in envelope['decisions'].items():
            self.assertEqual(decision['decision'], 'DEFERRED')
            self.assertIn('§12.1', decision['reason'])
            self.assertIn('not calibrated', decision['reason'])
            self.assertIn('no threshold is invented', decision['reason'])
            self.assertEqual(decision['rules'], [])
        self.assertNotIn('coding', json.dumps(envelope['inputs']))

    def test_decisions_use_existing_vocabulary_only_and_stay_json_compatible(self):
        coverage = producer_coverage({'coding': [attempt()]})
        envelope = self.decide(coverage, [rule()], evidence_kind='SOFTWARE_TEST')
        vocabulary = {'ADVANCE', 'NOT_ELIGIBLE', 'DEFERRED', 'NOT_APPLICABLE',
                      'EXPLORATORY', 'INTEGRATION_BLOCKED'}
        for decision in envelope['decisions'].values():
            self.assertIn(decision['decision'], vocabulary)
            self.assertIn(decision['standard_eligibility']['decision'],
                          vocabulary)
            self.assertEqual(set(decision), {
                'section', 'decision', 'reason', 'evidence_kind',
                'standard_eligibility', 'exploratory_authorization', 'rules',
                'evidence_citations', 'scheduling'})
        encoded = json.dumps(envelope)  # native JSON types only
        self.assertNotIn('NaN', encoded)

        def walk(value):
            if isinstance(value, dict):
                for key in value:
                    self.assertNotIn('percent', key.lower())
                    walk(value[key])
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(envelope)

    # ------------------------------------------------- eligibility science

    def test_configured_adequate_evidence_qualifies(self):
        coverage = producer_coverage({
            'coding': [attempt(), attempt(scoring='SCORED_FAIL'), attempt()],
            'reasoning': [attempt()]})
        envelope = self.decide(coverage, [rule(required={
            'coding': {'min_measured': 3, 'min_scored': 3, 'min_passes': 2}}),
        ], evidence_kind='SOFTWARE_TEST')
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'ADVANCE')
        self.assertIn('coding-rule', coding['reason'])
        self.assertTrue(all(entry['matched'] for entry in coding['rules']))
        citation = coding['evidence_citations'][0]
        self.assertEqual(citation['category'], 'coding')
        self.assertEqual((citation['measured'], citation['scored'],
                          citation['pass'], citation['fail'], citation['missing']),
                         (3, 3, 2, 1, []))
        # Per-capability independence: no cross-credit, no spurious verdicts.
        for section in ('reasoning', 'long-context', 'tool-use'):
            self.assertEqual(envelope['decisions'][section]['decision'],
                             'DEFERRED')

    def test_insufficient_evidence_cannot_qualify_and_defers_unresolved(self):
        coverage = producer_coverage({
            'coding': [attempt(), attempt(scoring='SCORED_FAIL'), None]})
        envelope = self.decide(coverage, [rule(required={
            'coding': {'min_measured': 3, 'min_scored': 2, 'min_passes': 1}}),
        ], evidence_kind='SOFTWARE_TEST')
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'DEFERRED')
        self.assertIn('coding-2', coding['reason'])
        self.assertIn('unmeasured identities', coding['reason'])

    def test_definitive_negative_is_not_eligible_with_valid_negatives_cited(self):
        coverage = producer_coverage({
            'coding': [attempt(scoring='SCORED_FAIL'),
                       attempt(scoring='SCORED_FAIL'),
                       attempt(scoring='SCORED_FAIL')]})
        envelope = self.decide(coverage, [rule(required={
            'coding': {'min_passes': 1}})], evidence_kind='SOFTWARE_TEST')
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'NOT_ELIGIBLE')
        self.assertIn('pass 0 against required 1', coding['reason'])
        citation = coding['evidence_citations'][0]
        self.assertEqual((citation['measured'], citation['fail'],
                          citation['missing']), (3, 3, []))

    def test_weak_unrelated_category_is_isolated(self):
        coverage = producer_coverage({
            'coding': [attempt(), attempt()],
            'reasoning': [attempt(scoring='SCORED_FAIL'), None]})
        envelope = self.decide(coverage, [
            rule(rule_id='coding-only', required={
                'coding': {'min_measured': 2, 'min_passes': 2}}),
            rule(rule_id='reasoning-only', sections=('reasoning',), required={
                'reasoning': {'min_passes': 1}}),
        ], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(envelope['decisions']['coding']['decision'], 'ADVANCE')
        self.assertEqual(envelope['decisions']['reasoning']['decision'],
                         'DEFERRED')
        self.assertEqual(
            [entry['rule_id'] for entry in
             envelope['decisions']['coding']['rules']], ['coding-only'])
        self.assertNotIn('reasoning',
                         json.dumps(envelope['decisions']['coding']
                                    ['evidence_citations']))

    def test_budget_exhaustion_defers_without_semantic_failure(self):
        coverage = producer_coverage({
            'coding': [attempt(), attempt()],
            'tool_use': [attempt(), attempt()]})
        rules = [rule(rule_id='coding-rule'),
                 rule(rule_id='tool-rule', sections=('tool-use',), required={
                     'tool_use': {'min_passes': 2}})]
        envelope = self.decide(coverage, rules, evidence_kind='SOFTWARE_TEST',
                               remaining_budget=1)
        self.assertEqual(envelope['decisions']['coding']['decision'], 'ADVANCE')
        tool = envelope['decisions']['tool-use']
        self.assertEqual(tool['decision'], 'DEFERRED')
        self.assertIn('postponed', tool['reason'])
        self.assertIn('budget', tool['reason'])
        self.assertNotIn('NOT_ELIGIBLE', tool['reason'])
        self.assertEqual(tool['standard_eligibility']['decision'], 'ADVANCE')
        self.assertEqual(envelope['decisions']['reasoning']['decision'],
                         'DEFERRED')
        zero = self.decide(coverage, rules, evidence_kind='SOFTWARE_TEST',
                           remaining_budget=0)
        for section in ('coding', 'tool-use'):
            self.assertEqual(zero['decisions'][section]['decision'], 'DEFERRED')
            self.assertIn(zero['decisions'][section]['scheduling']
                          ['scheduled_position'], (1, 2))
        failing = self.decide(coverage, [rule(required={'coding':
                                                        {'min_passes': 99}})],
                              evidence_kind='SOFTWARE_TEST', remaining_budget=0)
        self.assertEqual(failing['decisions']['coding']['decision'],
                         'NOT_ELIGIBLE')

    def test_priority_orders_scheduling_and_never_bypasses_eligibility(self):
        coverage = producer_coverage({
            'coding': [attempt()],
            'tool_use': [attempt(), attempt()]})
        rules = [rule(rule_id='coding-rule'),
                 rule(rule_id='tool-rule', sections=('tool-use',), required={
                     'tool_use': {'min_passes': 2}})]
        first = self.decide(coverage, rules, evidence_kind='SOFTWARE_TEST',
                            priorities={'tool-use': 5}, remaining_budget=1)
        self.assertEqual(first['decisions']['tool-use']['decision'], 'ADVANCE')
        self.assertEqual(first['decisions']['coding']['decision'], 'DEFERRED')
        self.assertEqual(first['decisions']['tool-use']['scheduling']
                         ['scheduled_position'], 1)
        second = self.decide(coverage, rules, evidence_kind='SOFTWARE_TEST',
                             priorities={'coding': 1}, remaining_budget=1)
        self.assertEqual(second['decisions']['coding']['decision'], 'ADVANCE')
        ineligible = producer_coverage({'reasoning': [
            attempt(scoring='SCORED_FAIL')]})
        bypass = self.decide(ineligible, [rule(rule_id='reasoning-rule',
                                               sections=('reasoning',),
                                               required={
                                                   'reasoning':
                                                       {'min_passes': 1}})],
                             evidence_kind='SOFTWARE_TEST',
                             priorities={'reasoning': 100})
        self.assertEqual(bypass['decisions']['reasoning']['decision'],
                         'NOT_ELIGIBLE')

    def test_deterministic_for_content_equal_inputs_and_non_mutating(self):
        coverage = producer_coverage({'coding': [attempt(), attempt()]})
        first_rule = rule()
        reordered = {'required_categories': {'coding': {'min_passes': 1,
                                                        'min_measured': 1}},
                     'acceptance': first_rule['acceptance'],
                     'source': first_rule['source'],
                     'evidence_class': 'SOFTWARE_TEST',
                     'sections': ['coding'],
                     'rule_id': 'coding-rule'}
        frozen_coverage = copy.deepcopy(coverage)
        frozen_rule = copy.deepcopy(first_rule)
        one = self.decide(coverage, [first_rule], evidence_kind='SOFTWARE_TEST')
        two = self.decide(coverage, [reordered], evidence_kind='SOFTWARE_TEST')
        three = self.decide(coverage, [first_rule], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(policy.canonical(one), policy.canonical(two))
        self.assertEqual(policy.canonical(one), policy.canonical(three))
        self.assertEqual(coverage, frozen_coverage)
        self.assertEqual(first_rule, frozen_rule)

    # -------------------------------------------------- evidence-class binding

    def test_external_rules_and_acceptance_cannot_admit_real_model_evidence(self):
        coverage = producer_coverage({'coding': [attempt(), attempt()]})
        for evidence_class in ('SOFTWARE_TEST', 'REAL_MODEL'):
            supplied = rule(evidence_class=evidence_class, prerequisites=('accepted',))
            supplied['acceptance'] = 'HUMAN_ACCEPTED'
            decision = self.decide(coverage, [supplied], evidence_kind='REAL_MODEL',
                                   prerequisites={'accepted': True})
            self.assertEqual(decision['decisions']['coding']['decision'], 'DEFERRED')
        real_rule = self.decide(coverage, [rule(evidence_class='REAL_MODEL')],
                                evidence_kind='SOFTWARE_TEST')
        self.assertEqual(real_rule['decisions']['coding']['decision'],
                         'NOT_ELIGIBLE')
        self.assertIn('binding mismatch',
                      real_rule['decisions']['coding']['reason'])

    # ------------------------------------------------------------ exploratory

    def test_exploratory_requires_attributed_authorization(self):
        coverage = producer_coverage({'coding': [attempt()]})
        envelope = self.decide(coverage, evidence_kind='SOFTWARE_TEST',
                               exploratory=authorization())
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'EXPLORATORY')
        self.assertEqual(coding['exploratory_authorization'], {
            'operator': 'test-operator',
            'authorization': 'OP-TEST-2026-10-22',
            'reason': 'bounded research question, not eligibility'})
        self.assertIn('test-operator', coding['reason'])
        self.assertIn('OP-TEST-2026-10-22', coding['reason'])
        self.assertIn('not eligibility', coding['reason'])
        self.assertEqual(coding['standard_eligibility']['decision'], 'DEFERRED')
        for section in ('reasoning', 'long-context', 'tool-use'):
            other = envelope['decisions'][section]
            self.assertEqual(other['decision'], 'DEFERRED')
            self.assertIsNone(other['exploratory_authorization'])
        self.assertEqual(envelope['inputs']['exploratory'],
                         authorization())
        for bad in (['coding'], {'coding': {'operator': 'x',
                                            'authorization': 'y'}},
                    {'agentic-readiness': authorization()['coding']},
                    {'coding': {'operator': '', 'authorization': 'y',
                                'reason': 'z'}}):
            with self.assertRaises(policy.CheckError):
                self.decide(coverage, evidence_kind='SOFTWARE_TEST',
                            exploratory=bad)

    def test_exploratory_preserves_scientific_failure_in_record(self):
        coverage = producer_coverage({'coding': [
            attempt(scoring='SCORED_FAIL')]})
        envelope = self.decide(coverage, [rule(required={
            'coding': {'min_passes': 1}})], evidence_kind='SOFTWARE_TEST',
            exploratory=authorization())
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'EXPLORATORY')
        standard = coding['standard_eligibility']
        self.assertEqual(standard['decision'], 'NOT_ELIGIBLE')
        self.assertIn('pass 0 against required 1', standard['reason'])

    # ---------------------------------------------------------- prerequisites

    def test_unresolved_prerequisite_defers_and_false_decides_not_eligible(self):
        coverage = producer_coverage({'coding': [attempt(), attempt()]})
        configured = [rule(required={'coding': {'min_passes': 2}},
                           prerequisites=('qualified_reviewer',))]
        unresolved = self.decide(coverage, configured,
                                 evidence_kind='SOFTWARE_TEST')
        self.assertEqual(unresolved['decisions']['coding']['decision'],
                         'DEFERRED')
        self.assertIn('qualified_reviewer', unresolved['decisions']['coding']
                      ['reason'])
        resolved = self.decide(coverage, configured,
                               evidence_kind='SOFTWARE_TEST',
                               prerequisites={'qualified_reviewer': {
                                   'resolved': False,
                                   'detail': 'reviewer declined the binding'}})
        coding = resolved['decisions']['coding']
        self.assertEqual(coding['decision'], 'NOT_ELIGIBLE')
        self.assertIn('reviewer declined the binding', coding['reason'])
        admitted = self.decide(coverage, configured,
                               evidence_kind='SOFTWARE_TEST',
                               prerequisites={'qualified_reviewer': True})
        self.assertEqual(admitted['decisions']['coding']['decision'],
                         'ADVANCE')
        self.assertTrue(admitted['decisions']['coding']['rules'][0]
                        ['prerequisites'][0]['resolved'])

    # ---------------------------------------------- measurement vs semantics

    def test_sufficiency_among_present_evidence_qualifies_despite_missing(self):
        coverage = producer_coverage({'coding': [attempt(), attempt(), None]})
        envelope = self.decide(coverage, [rule(required={
            'coding': {'min_passes': 2}})], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(envelope['decisions']['coding']['decision'], 'ADVANCE')
        conservative = self.decide(coverage, [rule(required={
            'coding': {'min_passes': 2, 'require_complete_measurement':
                       True}})], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(conservative['decisions']['coding']['decision'],
                         'DEFERRED')
        self.assertIn('missing unit identities',
                      conservative['decisions']['coding']['reason'])

    def test_budget_limited_and_indeterminate_remain_findings_not_failures(self):
        coverage = producer_coverage({'coding': [
            attempt(),
            attempt(completion='INCOMPLETE', scoring='NOT_SCOREABLE',
                    limits='BUDGET'),
            attempt(scoring='NOT_SCOREABLE')]})
        envelope = self.decide(coverage, [rule(required={
            'coding': {'min_passes': 2}})], evidence_kind='SOFTWARE_TEST')
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'DEFERRED')
        citation = coding['evidence_citations'][0]
        self.assertEqual((citation['measured'], citation['scored'],
                          citation['budget_limited'], citation['indeterminate'],
                          citation['missing']), (3, 1, 1, 1, []))
        self.assertIn('unscored', coding['reason'])
        bounded = self.decide(coverage, [rule(required={
            'coding': {'min_passes': 4}})], evidence_kind='SOFTWARE_TEST')
        coding = bounded['decisions']['coding']
        self.assertEqual(coding['decision'], 'NOT_ELIGIBLE')
        self.assertIn('retained findings, not semantic failures',
                      coding['reason'])
        self.assertIn('at most 3 passes achievable', coding['reason'])

    def test_absent_category_defers_and_never_counts_as_success(self):
        coverage = producer_coverage({'coding': [attempt()]})
        envelope = self.decide(coverage, [rule(rule_id='context-rule',
                                               sections=('long-context',),
                                               required={
                                                   'context':
                                                       {'min_measured': 1}})],
                              evidence_kind='SOFTWARE_TEST')
        decision = envelope['decisions']['long-context']
        self.assertEqual(decision['decision'], 'DEFERRED')
        self.assertIn('absent from coverage', decision['reason'])

    def test_unsupported_capability_is_not_applicable_with_citations(self):
        fixture = {'tasks': [{'id': 'tool-0', 'category': 'tool_use',
                              'messages': [], 'requires': ['native_tools']}]}
        coverage = policy.baseline_coverage(fixture, {}, {})
        envelope = self.decide(coverage, [rule(rule_id='tool-rule',
                                               sections=('tool-use',),
                                               required={
                                                   'tool_use':
                                                       {'min_measured': 1}})],
                              evidence_kind='SOFTWARE_TEST')
        decision = envelope['decisions']['tool-use']
        self.assertEqual(decision['decision'], 'NOT_APPLICABLE')
        self.assertIn('no applicable measurements', decision['reason'])
        citation = decision['evidence_citations'][0]
        self.assertEqual(citation['applicable'], 0)
        self.assertIn('native tool interface', citation['excluded'][0]['reason'])

    def test_pass_rate_never_treats_undefined_or_future_evidence_as_success(self):
        coverage = producer_coverage({'coding': [
            attempt(completion='INCOMPLETE', scoring='NOT_SCOREABLE',
                    limits='BUDGET'),
            attempt(completion='INCOMPLETE', scoring='NOT_SCOREABLE',
                    limits='BUDGET')]})
        undefined = self.decide(coverage, [rule(required={
            'coding': {'min_pass_rate': 0.5}})], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(undefined['decisions']['coding']['decision'],
                         'DEFERRED')
        scored = producer_coverage({'coding': [
            attempt(), attempt(scoring='SCORED_FAIL'),
            attempt(scoring='SCORED_FAIL'), attempt(scoring='SCORED_FAIL')]})
        definitive = self.decide(scored, [rule(required={
            'coding': {'min_pass_rate': 0.5}})], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(definitive['decisions']['coding']['decision'],
                         'NOT_ELIGIBLE')
        self.assertIn('could not exceed', definitive['decisions']['coding']
                      ['reason'])
        met = self.decide(producer_coverage({'coding': [
            attempt(), attempt(), attempt(), attempt(scoring='SCORED_FAIL')]}),
            [rule(required={'coding': {'min_pass_rate': 0.5}})],
            evidence_kind='SOFTWARE_TEST')
        self.assertEqual(met['decisions']['coding']['decision'], 'ADVANCE')

    def test_multiple_rules_alternative_satisfaction_is_cited(self):
        coverage = producer_coverage({'coding': [attempt()]})
        envelope = self.decide(coverage, [
            rule(rule_id='a-unreachable', required={'coding': {'min_passes': 9}}),
            rule(rule_id='b-satisfied', required={'coding': {'min_passes': 1}}),
        ], evidence_kind='SOFTWARE_TEST')
        coding = envelope['decisions']['coding']
        self.assertEqual(coding['decision'], 'ADVANCE')
        self.assertEqual([entry['rule_id'] for entry in coding['rules']],
                         ['a-unreachable', 'b-satisfied'])
        self.assertEqual([entry['matched'] for entry in coding['rules']],
                         [False, True])
        self.assertIn('b-satisfied', coding['reason'])

    def test_decimal_rate_boundary_is_inclusive(self):
        coverage = producer_coverage({'coding': [
            attempt(), attempt(), attempt(), attempt(), attempt(scoring='SCORED_FAIL')]})
        result = self.decide(coverage, [rule(required={
            'coding': {'min_pass_rate': 0.8}})], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(result['decisions']['coding']['decision'], 'ADVANCE')

    def test_unresolved_alternative_prevents_definitive_rejection(self):
        coverage = producer_coverage({'coding': [attempt(), None]})
        result = self.decide(coverage, [
            rule(rule_id='impossible', required={'coding': {'min_passes': 9}}),
            rule(rule_id='unresolved', required={'coding': {'min_passes': 2}}),
        ], evidence_kind='SOFTWARE_TEST')
        self.assertEqual(result['decisions']['coding']['decision'], 'DEFERRED')

    def test_false_coverage_constraint_is_rejected_not_inverted(self):
        for name in ('require_complete_measurement', 'require_complete_scoring'):
            with self.subTest(name=name), self.assertRaises(policy.CheckError):
                self.decide(producer_coverage({'coding': [attempt()]}),
                    [rule(required={'coding': {name: False}})],
                    evidence_kind='SOFTWARE_TEST')

    # ------------------------------------------------------------ fail-closed

    def test_rule_and_input_misuse_fails_closed(self):
        coverage = producer_coverage({'coding': [attempt()]})
        good = rule()
        bad_rules = [
            ('rule not an object', 'coding-rule'),
            ('rules not a list', dict(good)),
            ('unknown rule key', [dict(good, extra=1)]),
            ('missing acceptance', [{k: v for k, v in good.items()
                                     if k != 'acceptance'}]),
            ('empty source', [dict(good, source='  ')]),
            ('unknown section', [dict(good, sections=['agentic'])]),
            ('empty sections', [dict(good, sections=[])]),
            ('duplicate rule id', [good, dict(good)]),
            ('bad evidence class', [dict(good, evidence_class='SIMULATION')]),
            ('empty required categories', [dict(good, required_categories={})]),
            ('unknown criterion key', [dict(good, required_categories={
                'coding': {'min_passes': 1, 'min_average': 0.5}})]),
            ('zero min_passes', [dict(good, required_categories={
                'coding': {'min_passes': 0}})]),
            ('zero pass rate', [dict(good, required_categories={
                'coding': {'min_pass_rate': 0}})]),
            ('pass rate above one', [dict(good, required_categories={
                'coding': {'min_pass_rate': 1.5}})]),
            ('string pass rate', [dict(good, required_categories={
                'coding': {'min_pass_rate': '0.5'}})]),
            ('boolean count', [dict(good, required_categories={
                'coding': {'min_measured': True}})]),
            ('empty prerequisite name', [dict(good,
                                              critical_prerequisites=[''])]),
        ]
        for label, bad in bad_rules:
            with self.subTest(label=label):
                with self.assertRaises(policy.CheckError):
                    self.decide(coverage, bad, evidence_kind='SOFTWARE_TEST')
        bad_params = [
            ('unknown priority section', dict(priorities={'agentic': 1})),
            ('boolean priority', dict(priorities={'coding': True})),
            ('negative budget', dict(remaining_budget=-1)),
            ('boolean budget', dict(remaining_budget=True)),
            ('string budget', dict(remaining_budget='2')),
            ('unknown prerequisite section value',
                dict(prerequisites={'reviewer': 'maybe'})),
            ('bad prerequisite record',
                dict(prerequisites={'reviewer': {'resolved': 1}})),
            ('unknown prerequisite key',
                dict(prerequisites={'reviewer': {'resolved': True,
                                                 'proof': 'x'}})),
        ]
        for label, kwargs in bad_params:
            with self.subTest(label=label):
                with self.assertRaises(policy.CheckError):
                    self.decide(coverage, [good], evidence_kind='SOFTWARE_TEST',
                                **kwargs)
        with self.assertRaises(policy.CheckError):
            self.decide(coverage, [good], evidence_kind='SIMULATION')
        with self.assertRaises(TypeError):  # evidence_kind is required
            self.decide(coverage, [good])

    def test_malformed_coverage_fails_closed(self):
        good_row = {'planned': 1, 'applicable': 1, 'measured': 1, 'scored': 1,
                    'pass': 1, 'fail': 0, 'budget_limited': 0,
                    'indeterminate': 0, 'excluded': {}, 'missing': [],
                    'unscored': [], 'status': 'COMPLETE',
                    'minimum_measurement_coverage_met': True,
                    'minimum_scoring_coverage_met': True}
        cases = [
            ('not a dict', None),
            ('missing categories', {'status': 'COMPLETE'}),
            ('categories not a mapping', {'status': 'COMPLETE',
                                          'categories': []}),
            ('inconsistent scoring', {'status': 'COMPLETE', 'categories': {
                'coding': dict(good_row, **{'pass': 0})}}),
            ('counting absent evidence as measured', {'status': 'COMPLETE',
                'categories': {'coding': dict(good_row, measured=2)}}),
            ('invalid status', {'status': 'COMPLETE', 'categories': {
                'coding': dict(good_row, status='MOSTLY_FINE')}}),
            ('claiming coverage with missing units', {'status': 'COMPLETE',
                'categories': {'coding': dict(good_row,
                                minimum_measurement_coverage_met=False)}}),
            ('scored performance', {'status': 'COMPLETE', 'categories': {
                'performance': dict(good_row)}}),
        ]
        for label, coverage in cases:
            with self.subTest(label=label):
                with self.assertRaises(policy.CheckError):
                    self.decide(coverage, evidence_kind='SOFTWARE_TEST')


if __name__ == '__main__':
    unittest.main()
