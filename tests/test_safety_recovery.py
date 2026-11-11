"""Synthetic software-only admission, budget, and crash-boundary regressions."""
import copy
import json
import os
from pathlib import Path
import signal
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
from welp_next import policy, preflight, runner, store


class SafetyRecovery(unittest.TestCase):
    def setUp(self):
        self.work = support.make_workdir('safety')
        self.addCleanup(support.shutil.rmtree, self.work, True)
        self.tasks = {t['id']: t for t in support.fixture_tasks()}
        self.order = list(self.tasks)
        self.endpoint = support.SyntheticEndpoint(
            tasks_by_id=self.tasks,
            payloads=support.canned_payloads({u: 'pass' for u in self.order}, self.tasks)).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.work / 'campaign'
        self.profile = support.build_profile(self.work, self.endpoint.endpoint_url, self.campaign)
        self.endpoint.echo_provider = lambda: support.identity_echo(self.profile)


    def test_dead_endpoint_rejected_before_measurement(self):
        self.endpoint.stop()
        with self.assertRaisesRegex(policy.CheckError, 'endpoint.unreachable'):
            runner.run(self.profile)
        self.assertEqual(self.endpoint.post_count(), 0)
        self.assertEqual(runner.status(self.campaign)['state'], 'BLOCKED')

    def test_fatal_vulkan_error_survives_crash_before_stop_marker(self):
        first = self.order[0]
        self.endpoint.payloads[first] = (200, b'{"error":{"message":"VK_ERROR_OUT_OF_DEVICE_MEMORY"}}')
        original = store.put_json

        def crash_before_marker(path, value):
            if Path(path).name == 'safety-stop.json':
                raise OSError('simulated process loss before auxiliary stop marker')
            return original(path, value)

        with patch.object(store, 'put_json', side_effect=crash_before_marker):
            with self.assertRaisesRegex(OSError, 'simulated process loss'):
                runner.run(self.profile)
        section = store.section_path(self.campaign)
        self.assertFalse((section / 'safety-stop.json').exists())
        state = runner.status(self.campaign)
        self.assertEqual(state['state'], 'INTERRUPTED')
        self.assertFalse(state['resumable'])
        with self.assertRaisesRegex(policy.CheckError, 'safety.stop'):
            runner.run(self.profile)
        self.assertEqual(self.endpoint.post_count(), 1)
        row = state['units'][0]
        self.assertEqual((row['outcome'], row['attempts']), ('INVALID', 1))

    def test_client_deadline_is_not_semantic_failure_or_retry(self):
        self.profile['budgets']['timeout_seconds'] = 0.15
        self.endpoint.delays[self.order[0]] = 0.35
        result = runner.run(self.profile)
        first = result['units'][0]
        self.assertEqual((first['outcome'], first['reason']), ('NOT_EVALUABLE', 'BUDGET_LIMITED'))
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(self.endpoint.post_count(self.order[0]), 1)
        conditions = store.read_json(store.section_path(self.campaign) / 'evidence' /
                                     self.order[0] / first['resolved_attempt'] / 'conditions.json')
        self.assertTrue(conditions['client_deadline_exhausted'])
        self.assertEqual(conditions['request_limits']['timeout_seconds'], 0.15)

    def test_hard_kill_keeps_partial_attempt_and_completed_negatives(self):
        first, third = self.order[0], self.order[2]
        self.endpoint.payloads[first] = (200, support.canonical(support.envelope(support.fail_content(self.tasks[first]), 'stop')))
        self.endpoint.delays[third] = 1.0
        profile_path = support.write_profile(self.work, self.profile)
        process = support.popen_cli(['run', '--profile', profile_path, '--json'])
        try:
            self.endpoint.wait_for(lambda: self.endpoint.post_count(third) == 1, timeout=10)
            process.send_signal(signal.SIGKILL)
            process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        before = runner.status(self.campaign)
        self.assertEqual(before['state'], 'INTERRUPTED')
        self.assertEqual(before['remaining_units'], self.order[2:])
        completed = store.section_path(self.campaign) / 'evidence' / first / '0001' / 'response.raw'
        original_response = completed.read_bytes()
        self.endpoint.delays.clear()
        result = support.cli(['resume', '--campaign', self.campaign, '--json'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = support.cli_json(result)
        self.assertEqual(after['state'], 'COMPLETED')
        self.assertEqual(after['units'][0]['outcome'], 'FAIL')
        self.assertEqual(completed.read_bytes(), original_response)
        self.assertEqual(self.endpoint.post_count(first), 1)
        retried = store.attempts(store.section_path(self.campaign), third)
        self.assertEqual([r['finalized'] for r in retried], [False, True])
        self.assertEqual(self.endpoint.post_count(third), 2)  # network retry, not double credit

    def test_report_rechecks_observed_echo_not_just_hash_consistency(self):
        runner.run(self.profile)
        self.endpoint.stop()
        attempt = store.section_path(self.campaign) / 'evidence' / self.order[0] / '0001'
        conditions = store.read_json(attempt / 'conditions.json')
        conditions['preflight']['echo']['configuration']['artifact_sha256'] = 'f' * 64
        (attempt / 'conditions.json').write_bytes(policy.canonical(conditions))
        commit = store.read_json(attempt / 'attempt.json')
        commit['files']['conditions.json'] = policy.file_sha(attempt / 'conditions.json')
        (attempt / 'attempt.json').write_bytes(policy.canonical(commit))
        from welp_next import reporting
        with self.assertRaisesRegex(policy.CheckError, 'serve.echo.artifact_sha256'):
            reporting.report_section(self.campaign)



class EnforcementBoundaries(unittest.TestCase):

    def test_incomplete_answers_cannot_carry_correctness_verdicts(self):
        for scoring in ('SCORED_PASS', 'SCORED_FAIL'):
            with self.subTest(scoring=scoring), self.assertRaises(policy.CheckError):
                policy.derive_outcome('VALID', 'INCOMPLETE', scoring, 'BUDGET')

    def test_allocation_errors_stop_but_successful_answer_quotations_do_not(self):
        task = support.fixture_tasks()[0]
        for cause in ('VK_ERROR_OUT_OF_DEVICE_MEMORY', 'VK_ERROR_OUT_OF_HOST_MEMORY', 'HIP out of memory'):
            with self.subTest(cause=cause):
                score, fatal = runner.assess_response(task, json.dumps({'error': {'message': cause}}).encode())
                self.assertTrue(fatal)
                self.assertEqual((score['execution'], score['limits']), ('INVALID', 'HOST'))
        score, fatal = runner.assess_response(task, support.canonical(support.envelope('Historic CUDA OOM is unrelated.', 'stop')))
        self.assertFalse(fatal)
        self.assertEqual(score['execution'], 'VALID')

    def test_invalid_budget_and_request_overrides_fail_offline(self):
        work = support.make_workdir('profile-boundaries')
        self.addCleanup(support.shutil.rmtree, work, True)
        base = support.build_profile(work, 'http://127.0.0.1:1/v1', work / 'campaign')
        for field, value in [('timeout_seconds', float('nan')), ('timeout_seconds', float('inf'))]:
            altered = copy.deepcopy(base)
            altered['budgets'][field] = value
            with self.assertRaisesRegex(policy.CheckError, 'timeout_seconds'):
                preflight.offline(altered)
        for container in ('sampling', 'reasoning'):
            altered = copy.deepcopy(base)
            target = altered['sampling'] if container == 'sampling' else altered['reasoning']['controls']
            target['messages'] = []
            with self.assertRaisesRegex(policy.CheckError, 'messages'):
                preflight.offline(altered)
        altered = copy.deepcopy(base)
        altered['profile_id'] = base['profile_id'].replace('-off-', '-not-configurable-')
        altered['reasoning']['arm'] = 'ON'
        with self.assertRaisesRegex(policy.CheckError, 'profile_id'):
            preflight.offline(altered)
