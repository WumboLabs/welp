"""M1 consumer semantics: bounded INVALID retry, exhaustion gap, unrelated progress."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402


class BoundedRetryGap(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('gap')
        self.addCleanup(support.shutil.rmtree, self.workdir, True)
        self.tasks_by_id = {t['id']: t for t in support.fixture_tasks()}
        self.order = support.unit_ids()
        self.http500_unit = self.order[4]
        self.malformed_unit = self.order[9]
        behaviors = {uid: 'pass' for uid in self.order}
        behaviors[self.http500_unit] = 'http500'      # every attempt fails at HTTP
        behaviors[self.malformed_unit] = 'malformed'  # HTTP 200, unusable envelope
        self.endpoint = support.SyntheticEndpoint(
            tasks_by_id=self.tasks_by_id,
            payloads=support.canned_payloads(behaviors, self.tasks_by_id),
        ).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.workdir / 'campaign'
        self.section = support.section_path(self.campaign)
        self.profile = support.build_profile(self.workdir, self.endpoint.endpoint_url,
                                             self.campaign)
        self.profile_path = support.write_profile(self.workdir, self.profile)
        self.endpoint.echo_provider = lambda: support.identity_echo(self.profile)
        self.gap_units = (self.http500_unit, self.malformed_unit)

    def test_invalid_units_retry_bounded_then_gap_while_unrelated_proceed(self):
        proc = support.cli(['run', '--profile', self.profile_path])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        proc = support.cli(['status', '--json', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['state'], 'COMPLETED_PARTIAL')
        self.assertTrue(doc['finalizable'])
        self.assertEqual(doc['remaining_units'], [], 'exhausted gaps are not pending')
        rows = {r['unit_id']: r for r in doc['units']}
        self.assertEqual(len(rows), 20)
        for uid in self.gap_units:
            row = rows[uid]
            self.assertEqual(row['outcome'], 'INVALID', f'{uid}: harness gap outcome')
            self.assertEqual(row['reason'], 'EXECUTION_FAILURE', f'{uid}: gap reason')
            self.assertEqual(row['attempts'], 2, f'{uid}: bounded retry MAX_ATTEMPTS=2')
            self.assertFalse(row['pending'], uid)
        for uid in self.order:
            if uid not in self.gap_units:
                expected = 'NOT_EVALUABLE' if uid == support.safety_unit_id() else 'PASS'
                self.assertEqual(rows[uid]['outcome'], expected,
                                 f'{uid}: unrelated units proceed unblocked')
                self.assertEqual(rows[uid]['attempts'], 1, uid)

        # Evidence: exactly two finalized INVALID attempts per gap unit.
        for uid, status_code in ((self.http500_unit, 500), (self.malformed_unit, 200)):
            attempts = sorted((self.section / 'evidence' / uid).iterdir())
            self.assertEqual([p.name for p in attempts], ['0001', '0002'], uid)
            receipts = [r for r in self.endpoint.posts if r['unit'] == uid]
            self.assertEqual(len(receipts), 2, f'{uid}: exactly two wire attempts')
            for attempt_dir, receipt in zip(attempts, receipts):
                _, score, conditions = support.check_finalized_attempt(
                    self, uid, attempt_dir, receipt, self.revision_of(),
                    'INVALID', 'EXECUTION_FAILURE')
                self.assertEqual(conditions.get('http_status'), status_code, uid)
                if status_code == 500:
                    self.assertIn('500', conditions.get('transport_error') or '', uid)
            for name in ('0001', '0002'):
                body = (self.section / 'evidence' / uid / name / 'response.raw').read_bytes()
                self.assertTrue(body, f'{uid}/{name}: raw error body is retained')
        # Unrelated units were each requested exactly once, including units
        # scheduled after the failing ones.
        for uid in self.order:
            expected = 2 if uid in self.gap_units else 1
            self.assertEqual(self.endpoint.post_count(uid), expected,
                             f'{uid}: wire request count')

    def revision_of(self):
        return json.loads((self.section / 'run.json').read_bytes())['profile_revision']

    def test_report_records_gap_from_disk_and_resume_adds_nothing(self):
        proc = support.cli(['run', '--profile', self.profile_path])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        posts_before = self.endpoint.post_count()
        self.endpoint.stop()  # report and resume must work without the endpoint
        proc = support.cli(['report', '--campaign', self.campaign,
                            '--section', 'baseline'])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['disposition'], 'PASS')
        self.assertEqual(doc['state'], 'COMPLETED_PARTIAL')
        support.verify_manifest_integrity(self, self.section)
        attempts_before = self.count_attempts()
        proc = support.cli(['resume', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['state'], 'COMPLETED_PARTIAL',
                         'resume must not convert exhausted gaps into reruns')
        self.assertEqual(self.count_attempts(), attempts_before,
                         'resume must not add attempts once units are exhausted')
        self.assertEqual(self.endpoint.post_count(), posts_before,
                         'no further traffic after gap exhaustion')

    def count_attempts(self):
        return sum(1 for _ in (self.section / 'evidence').rglob('attempt.json'))


if __name__ == '__main__':
    unittest.main()
