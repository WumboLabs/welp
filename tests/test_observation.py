"""Optional collector through real inference/evidence/replay; no GPU workloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import support
from test_runtime_performance import stream_frames
from welp_next import observation, policy, reporting, runner, store
from welp_next import runtime_performance as perf


COLLECT = """import json,sys,time
r=json.load(sys.stdin)
print(json.dumps({'request_id':r['request_id'],'scope':'device-wide',
'source':{'collector':'synthetic-device-fixture','observed_epoch':time.time()},
'observations':{'devices':[{'pci_id':r['pci_id'],
'vram_used_bytes':1048576 if r['phase']=='before' else 2097152}],
'compute_processes':[{'pid':999,'reported_memory_bytes':777}]}}))
"""


class AttemptObservation(unittest.TestCase):
    def run_performance(self, command=None, configure=True, timeout=2):
        work = support.make_workdir('attempt-observation')
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        campaign = work / 'campaign'
        campaign.mkdir()
        profile = support.build_profile(work, 'http://127.0.0.1:1/v1', campaign)
        profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                'methodology': policy.METHODOLOGY_M2}
        profile['sampling']['qualification_source'] = str(Path(__file__))
        if configure:
            profile['deployment'] = {'observation': {
                'command': command or [sys.executable, '-c', COLLECT],
                'timeout_seconds': timeout}}
        _, tasks = perf.load_fixture()
        server = support.SyntheticEndpoint(tasks_by_id=tasks,
            payloads={uid: (200, stream_frames()) for uid in tasks},
            echo_provider=lambda: {**support.identity_echo(profile),
                                   'sampling': policy.sampling_settings(profile)})
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            perf.run(profile)
        finally:
            server.stop()
        return campaign, profile, tasks

    def test_attempt_samples_drive_coverage_reporting_and_offline_replay(self):
        campaign, profile, tasks = self.run_performance()
        section = campaign / 'sections/runtime-performance'
        _, units = store.inventory(section)
        for uid, rows in units.items():
            score = policy.resolved_attempt(rows)
            self.assertEqual(score['outcome'], 'PASS')
            path = Path(score['path'])
            before = observation.read_snapshot(profile, path, 'gpu-before.json')
            after = observation.read_snapshot(profile, path, 'gpu-after.json')
            self.assertEqual(before['binding']['unit_id'], uid)
            self.assertEqual(after['binding']['attempt_id'], '0001')
            self.assertEqual(observation.device_memory(profile, before), 1048576)
            self.assertEqual(observation.device_memory(profile, after), 2097152)
            self.assertEqual(policy.performance_gaps(score, profile, tasks[uid]), [])
            rebuilt, fatal = runner.replay_attempt(profile, tasks[uid], path)
            self.assertEqual(rebuilt['outcome'], 'PASS')
            self.assertFalse(fatal)
        perf.report_section(campaign)
        reporting.verify_manifest(section)
        summary = store.read_json(section / 'performance-summary.json')
        for row in summary['workloads'].values():
            memory = row['memory']
            self.assertEqual(memory['sampled_max_bytes'], 2097152)
            self.assertEqual(memory['scope'], 'device-wide')
            self.assertEqual(memory['process_attributed_bytes'], 'UNAVAILABLE')
            self.assertEqual(memory['true_peak_bytes'], 'UNAVAILABLE')
            self.assertEqual(memory['sample_count'], 2)
            self.assertEqual(memory['delta_bytes'], 1048576)

    def test_absent_collector_does_not_invent_memory(self):
        campaign, profile, tasks = self.run_performance(configure=False)
        path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
        self.assertFalse((path / 'gpu-before.json').exists())
        self.assertEqual(perf._memory_observations(profile, path)['before'], 'UNAVAILABLE')
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, tasks['perf-short']),
                         ['memory_consumption'])

    def test_failed_collector_preserves_answers_and_scoring(self):
        campaign, profile, tasks = self.run_performance(command=[sys.executable, '-c', 'raise SystemExit(7)'])
        path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
        self.assertEqual(store.read_json(path / 'gpu-before.json')['status'], 'UNAVAILABLE')
        rebuilt, fatal = runner.replay_attempt(profile, tasks['perf-short'], path)
        self.assertEqual(rebuilt['outcome'], 'PASS')
        self.assertFalse(fatal)
        self.assertEqual(store.read_json(path / 'repetitions.json')['repeats'][0]['envelope']
                         ['choices'][0]['message']['content'], '42')
        self.assertFalse(perf._memory_observations(profile, path)['available'])

    def test_collector_timeout_and_stale_response_remain_unavailable(self):
        for command, timeout in (
                ([sys.executable, '-c', 'import time; time.sleep(2)'], .05),
                ([sys.executable, '-c', COLLECT.replace("r['request_id']", "'old-request'")], 2)):
            with self.subTest(command=command):
                campaign, profile, tasks = self.run_performance(command=command, timeout=timeout)
                path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
                self.assertEqual(store.read_json(path / 'gpu-before.json')['status'], 'UNAVAILABLE')
                self.assertEqual(runner.replay_attempt(profile, tasks['perf-short'], path)[0]['outcome'], 'PASS')
                error = store.read_json(path / 'gpu-before.json')['error']
                self.assertIn('TimeoutExpired' if timeout == .05 else 'ValueError', error)

    def test_observed_zero_is_not_missing_memory(self):
        command = [sys.executable, '-c', COLLECT.replace(
            "1048576 if r['phase']=='before' else 2097152", '0')]
        campaign, profile, tasks = self.run_performance(command=command)
        path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, tasks['perf-short']), [])
        memory = perf._memory_observations(profile, path)
        self.assertTrue(memory['available'])
        self.assertEqual(memory['sampled_max_bytes'], 0)
    def test_malformed_collector_output_does_not_break_model_evidence(self):
        for output in ('[]', '{"observations": {"devices": "not-a-list"}}', 'not json'):
            with self.subTest(output=output):
                campaign, profile, tasks = self.run_performance(
                    command=[sys.executable, '-c', f'print({output!r})'])
                path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
                snapshot = observation.read_snapshot(profile, path, 'gpu-after.json')
                self.assertEqual(snapshot['status'], 'UNAVAILABLE')
                self.assertEqual(runner.replay_attempt(profile, tasks['perf-short'], path)[0]['outcome'], 'PASS')


    def test_snapshots_cannot_be_copied_between_units_or_attempts(self):
        campaign, profile, tasks = self.run_performance()
        evidence = campaign / 'sections/runtime-performance/evidence'
        first = evidence / 'perf-short/0001'
        second = evidence / 'perf-substantial/0001'
        (second / 'gpu-before.json').write_bytes((first / 'gpu-before.json').read_bytes())
        with self.assertRaisesRegex(policy.CheckError, 'observation.binding'):
            runner.replay_attempt(profile, tasks['perf-substantial'], second)
        retry = evidence / 'perf-short/0002'
        shutil.copytree(first, retry)
        with self.assertRaisesRegex(policy.CheckError, 'observation.binding'):
            observation.read_snapshot(profile, retry, 'gpu-before.json')

    def test_out_of_window_snapshot_fails_offline_validation(self):
        campaign, profile, tasks = self.run_performance()
        path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
        snapshot = store.read_json(path / 'gpu-after.json')
        snapshot['started_epoch'] += 100
        snapshot['ended_epoch'] += 100
        (path / 'gpu-after.json').write_text(json.dumps(snapshot))
        with self.assertRaisesRegex(policy.CheckError, 'observation.window'):
            runner.replay_attempt(profile, tasks['perf-short'], path)

    def test_unbound_and_foreign_device_samples_cannot_supply_coverage(self):
        campaign, profile, tasks = self.run_performance()
        path = campaign / 'sections/runtime-performance/evidence/perf-short/0001'
        for name in observation.NAMES:
            snapshot = store.read_json(path / name)
            snapshot['observations']['devices'][0]['pci_id'] = '0000:99:00.0'
            (path / name).write_text(json.dumps(snapshot))
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, tasks['perf-short']),
                         ['memory_consumption'])
        self.assertFalse(perf._memory_observations(profile, path)['available'])
        (path / 'gpu-before.json').write_text(json.dumps({'observations': {
            'devices': [{'pci_id': profile['hardware']['device']['pci_id'], 'vram_used_bytes': 123}]}}))
        with self.assertRaisesRegex(policy.CheckError, 'observation.binding'):
            observation.read_snapshot(profile, path, 'gpu-before.json')

    def test_nvidia_adapter_reports_device_total_not_sum_of_processes(self):
        from welp_next.observe_nvidia import COLLECTOR
        work = support.make_workdir('nvidia-collector')
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        binary = work / 'nvidia-smi'
        binary.write_text(f'#!{sys.executable}\nimport sys\n'
            "print('00000000:04:00.0, fake-primary, 100\\n00000000:99:00.0, fake-other, 200' "
            "if '--query-gpu=' in ' '.join(sys.argv) else "
            "'999, fake-primary, 77\\n1000, fake-other, 88')\n")
        binary.chmod(0o700)
        result = subprocess.run([sys.executable, '-c', COLLECTOR],
            input=json.dumps({'request_id': 'current', 'pci_id': '0000:04:00.0'}),
            capture_output=True, text=True, check=True,
            env={**os.environ, 'PATH': str(work) + os.pathsep + os.environ['PATH']})
        measured = json.loads(result.stdout)
        self.assertEqual(measured['observations']['devices'],
                         [{'pci_id': '0000:04:00.0', 'vram_used_bytes': 100 * 1024 * 1024}])
        self.assertEqual(measured['observations']['compute_processes'][0]['reported_memory_bytes'],
                         77 * 1024 * 1024)
        self.assertEqual(measured['scope'], 'device-wide')
        self.assertIn('not model-specific', measured['source']['process_attribution'])


if __name__ == '__main__':
    unittest.main()
