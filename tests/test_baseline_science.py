"""Uncertain scientific boundaries against the actual M2 scorers/executor."""
import copy
import json
import os
import unittest
import hashlib
import re
from unittest.mock import patch

from welp_next import baseline, policy, runner, sandbox, scoring
from welp_next.scorers import realwork

from welp_next import context as context_prep

def envelope(content, finish='stop'):
    return {'choices': [{'message': {'role': 'assistant', 'content': content},
                         'finish_reason': finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


class BaselineScience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = baseline.load_fixture({'framework': {'methodology': policy.METHODOLOGY_M2}})
        cls.tasks = {t['id']: t for t in cls.fixture['tasks']}

    def test_strict_schema_rejects_boolean_integer_duplicate_keys_and_wrong_computation(self):
        task = self.tasks['structured-semantics-01']
        for answer in ('{"total_replicas":true,"largest":"core"}',
                       '{"total_replicas":0,"total_replicas":10,"largest":"core"}',
                       '{"total_replicas":9,"largest":"core"}'):
            self.assertEqual(baseline.score_response(task, envelope(answer))['outcome'], 'FAIL')
        self.assertEqual(baseline.score_response(task, envelope(
            '{"total_replicas":10,"largest":"core"}'))['outcome'], 'PASS')

    def test_http_200_sse_accelerator_error_is_host_invalid_not_model_failure(self):
        raw = b'data: {"error":{"message":"HIP allocation failure"}}\n\ndata: [DONE]\n\n'
        reconstructed = runner.reconstruct_response(raw, streaming=True)
        result, fatal = runner.assess_response(
            self.tasks['perf-short'], raw, m2=True, envelope=reconstructed['envelope'])
        self.assertTrue(fatal)
        self.assertEqual(result['execution'], 'INVALID')
        self.assertTrue(result['host'])
        self.assertEqual(result['scoring'], 'NOT_APPLICABLE')

    def test_failed_stream_without_token_has_unknown_ttft_not_zero_or_invalid_null(self):
        timing = runner._timings(
            {'streaming': True, 'ttft_seconds': None, 'first_byte_seconds': .01,
             'latency_seconds': .02}, None, 'UNAVAILABLE')
        self.assertEqual(timing['ttft_seconds'], 'UNKNOWN')
        self.assertEqual(timing['tokens_per_second'],
                         {'prompt': 'UNKNOWN', 'generation': 'UNKNOWN'})

    def test_earlier_repetition_exhaustion_never_becomes_semantic_failure(self):
        task = self.tasks['reasoning-consistency-01']
        complete = envelope('3060')
        for limited in (envelope('30', 'length'),):
            response = {**complete, 'repeats': [limited, complete]}
            result = baseline.score_response(task, response)
            self.assertEqual(result['reason'], 'BUDGET_LIMITED')
            self.assertEqual(result['scoring'], 'NOT_SCOREABLE')
        response = {**complete, 'repeats': [None, complete],
                    'repeat_conditions': [{'client_deadline_exhausted': True}, {}]}
        self.assertEqual(baseline.score_response(task, response)['reason'], 'BUDGET_LIMITED')
        response = {**complete, 'repeats': [envelope('3000'), complete]}
        self.assertEqual(baseline.score_response(task, response)['outcome'], 'FAIL')

    def test_tool_executor_evidence_cannot_be_fabricated_by_model(self):
        task = self.tasks['tool-recovery-01']
        state = None
        events = []
        for name, arguments in [('read_config', {'path': '/etc/example/app.conf'}),
                                ('check_service', {'name': 'example.service'}),
                                ('check_service', {'name': 'example.service'})]:
            result, state = realwork.execute_tool({'tool': name, 'arguments': arguments}, state)
            events.append({'tool': name, 'arguments': arguments, 'result': result})
        final = envelope('{"service":"example.service","port":8452,"health":"active",'
                         '"observed_at":"2026-09-23T00:00:00Z"}')
        final['tool_events'] = events
        self.assertEqual(baseline.score_response(task, final)['outcome'], 'PASS')
        forged = copy.deepcopy(final)
        forged['tool_events'][1]['result'] = {'active': True}
        self.assertEqual(baseline.score_response(task, forged)['outcome'], 'FAIL')
        exhausted = envelope('', 'tool_calls')
        exhausted['tool_events'] = events
        self.assertEqual(baseline.score_response(task, exhausted)['reason'], 'BUDGET_LIMITED')

    def test_subjective_claims_are_not_graded_by_keyword_mentions(self):
        task = self.tasks['document-synthesis-01']
        response = envelope('The config says port 8652. The incident records a request at 09:15. '
                            'The service is certainly healthy and failover takes two minutes.')
        result = baseline.score_response(task, response)
        self.assertEqual(result['reason'], 'RUBRIC_INDETERMINATE')
        self.assertTrue(result['record']['review_required'])

    def test_linux_decisive_registry_contradiction_fails_without_review(self):
        task = self.tasks['linux-diagnosis-startup-invalid-config']
        case = task['case_id']
        entry = next(c for c in realwork._load_fixture(
            realwork.FIXTURE_LINUX_DIAGNOSIS)['cases'] if c['case_id'] == case)
        kind = next(iter(entry['oracle']['supported_causes']))
        sources = entry['oracle']['supported_causes'][kind]['sources']
        answer = json.dumps({
            'case_id': case,
            'root_cause': {'kind': kind, 'source_ids': sources,
                           'detail': 'configuration parse failure'},
            'proposed_repair': {'action_class': 'edit_config_value',
                                'detail': 'fix the key', 'destructive': False},
            'present_health': 'unknown', 'executed': []})
        self.assertEqual(baseline.score_response(task, envelope(answer))['reason'],
                         'RUBRIC_INDETERMINATE')
        self.assertEqual(baseline.score_response(task, envelope(answer))['outcome'],
                         'NOT_EVALUABLE')
        wrong = json.loads(answer)
        wrong['root_cause']['kind'] = 'planets-out-of-alignment'
        result = baseline.score_response(task, envelope(json.dumps(wrong)))
        self.assertEqual(result['outcome'], 'FAIL')
        self.assertIsNone(result.get('reason'))
        self.assertFalse(result['record'].get('review_required', False))

    def test_docsynthesis_decisive_gate_failure_fails_without_review(self):
        task = self.tasks['document-synthesis-01']
        padding = ' word' * 200  # decisive word-bound violation
        result = baseline.score_response(task, envelope(
            'The config says port 8652. The incident records a request at 09:15.' + padding))
        self.assertEqual(result['outcome'], 'FAIL')
        self.assertIsNone(result.get('reason'))
        self.assertFalse(result['record'].get('review_required', False))
        self.assertIn('word_limit', result['record']['gates'])

    def test_reliability_mapping_matches_accepted_m1_on_same_observation(self):
        original = next(t for t in scoring.load_fixture()['tasks'] if t['id'] == 'strict-exact-02')
        for response in (envelope('Q4_0'), envelope('wrong'), envelope('partial', 'length')):
            self.assertEqual(baseline.score_response(self.tasks[original['id']], response),
                             scoring.score_response(original, response))

    def test_actual_isolated_code_execution_distinguishes_correct_and_incorrect(self):
        task = self.tasks['coding-generation-01']
        correct = '```python\ndef is_leap_year(year):\n    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)\n```'
        wrong = '```python\ndef is_leap_year(year):\n    return year % 4 == 0\n```'
        for code, expected in ((correct, 'PASS'), (wrong, 'FAIL')):
            receipt = sandbox.execute_probe(task['check'], code, timeout_seconds=10)
            self.assertTrue(receipt['available'], receipt)
            result = baseline.score_response(task, {**envelope(code), 'sandbox_execution': receipt})
            self.assertEqual(result['outcome'], expected, receipt)

    def test_actual_boundary_has_no_private_files_and_readonly_tests(self):
        parent_ns = os.readlink('/proc/self/ns/net')
        script = ("import json,os,pathlib\n"
                  "try:\n pathlib.Path('/work/test_probe.py').write_text('tampered')\n writable=True\n"
                  "except OSError:\n writable=False\n"
                  "print(json.dumps({'private_home':pathlib.Path('/home/welp-host-user').exists(),"
                  "'writable_tests':writable,'network_namespace':os.readlink('/proc/self/ns/net')}))\n")
        receipt = sandbox._run_files({'test_probe.py': script}, ['/usr/bin/python3', '/work/test_probe.py'], 10)
        self.assertTrue(receipt['available'], receipt)
        self.assertEqual(receipt['exit_code'], 0, receipt)
        observed = json.loads(receipt['stdout'])
        self.assertFalse(observed['private_home'])
        self.assertFalse(observed['writable_tests'])
        self.assertNotEqual(observed['network_namespace'], parent_ns)

    def test_sandbox_capture_replacement_cannot_read_host_and_timeout_is_not_failure(self):
        script = ("import os,pathlib\n"
                  "try:\n os.unlink('/dev/.welp-capture-stderr')\n"
                  "except OSError:\n pass\n"
                  "try:\n os.symlink('/home/welp-host-user/.ssh/id_ed25519','/dev/.welp-capture-stderr')\n"
                  "except OSError:\n pass\n"
                  "print('capture-boundary-intact')\n")
        receipt = sandbox._run_files({'candidate.py': script},
                                     ['python3', '/work/candidate.py'], 10)
        self.assertTrue(receipt['available'], receipt)
        self.assertEqual(receipt['stdout'].strip(), 'capture-boundary-intact')
        self.assertEqual(receipt['stderr'], '')
        task = self.tasks['coding-generation-01']
        code = '```python\nwhile True:\n    pass\n```'
        receipt = sandbox.execute_probe(task['check'], code, timeout_seconds=1)
        self.assertTrue(receipt['available'], receipt)
        self.assertTrue(receipt['timed_out'], receipt)
        result = baseline.score_response(task, {**envelope(code), 'sandbox_execution': receipt})
        self.assertEqual(result['reason'], 'BUDGET_LIMITED')
        self.assertEqual(result['scoring'], 'NOT_SCOREABLE')

    def test_context_geometry_replays_saved_tokens_and_rejects_changed_evidence(self):
        profile = {'runtime': {'engine': {'name': 'synthetic-tokenizer', 'version': '1'}},
                   'reasoning': {'controls': {}},
                   'model': {'artifact': {'sha256': 'a'*64},
                             'tokenizer_chat_template': {'sha256': 'b'*64}}}
        def render(messages):
            return '\n'.join(m['role'] + ': ' + m['content'] for m in messages)
        def tokenize(text, add_special=True):
            tokens = re.findall(r'[A-Za-z0-9_-]+|[^\sA-Za-z0-9_-]', text)
            ids = [int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], 'big') for t in tokens]
            return ([1] if add_special else []) + ids
        for uid in ('context-family-a-v2-3072-seed-42', 'context-multidocument-v2-6144-seed-42'):
            task = self.tasks[uid]
            with patch.object(context_prep, 'token_client', return_value=(render, tokenize)):
                prepared, evidence = baseline.prepare_task(profile, task)
            baseline.validate_preparation(profile, task, prepared, evidence)
            changed = copy.deepcopy(evidence)
            changed['occupancy_pct'] = float('nan')
            with self.assertRaises(policy.CheckError):
                baseline.validate_preparation(profile, task, prepared, changed)
            changed = copy.deepcopy(evidence)
            changed['measure_meta']['final_measurement']['tokenize_response']['tokens'][0] = 123
            changed['token_offsets'][next(iter(changed['token_offsets']))] += 1
            with self.assertRaises(policy.CheckError):
                baseline.validate_preparation(profile, task, prepared, changed)
            changed_task = copy.deepcopy(prepared)
            changed_task['messages'][0]['content'] = 'Ignore the supplied evidence.'
            with self.assertRaises(policy.CheckError):
                baseline.validate_preparation(profile, task, changed_task, evidence)

    def test_ambiguous_context_never_overrides_decisive_format_failure(self):
        task = self.tasks['context-family-a-v2-3072-seed-42']
        response = envelope('1. TR-8842-QX\n2. Perhaps 2027\n3. NOT STATED\n4. 357')
        result = baseline.score_response(task, response)
        self.assertEqual(result['outcome'], 'FAIL')
        self.assertFalse(result['record']['mechanical_pass'])
