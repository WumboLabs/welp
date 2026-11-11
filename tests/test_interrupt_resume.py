"""M1 consumer semantics: SIGINT handling, resume, no double credit, config pinning."""
import json
import signal
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402


class InterruptResumeBase(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('interrupt')
        self.addCleanup(support.shutil.rmtree, self.workdir, True)
        self.tasks_by_id = {t['id']: t for t in support.fixture_tasks()}
        self.order = support.unit_ids()
        self.endpoint = support.SyntheticEndpoint(tasks_by_id=self.tasks_by_id).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.workdir / 'campaign'
        self.section = support.section_path(self.campaign)
        self.profile = support.build_profile(self.workdir, self.endpoint.endpoint_url,
                                             self.campaign)
        self.profile_path = support.write_profile(self.workdir, self.profile)
        self.endpoint.echo_provider = lambda: support.identity_echo(self.profile)

    def configure(self, behaviors=None, delays=None):
        behaviors = behaviors or {uid: 'pass' for uid in self.order}
        behaviors[support.safety_unit_id()] = 'rubric'
        self.behaviors = behaviors
        self.endpoint.payloads = support.canned_payloads(behaviors, self.tasks_by_id)
        self.endpoint.delays = delays or {}
        return behaviors

    def run_until_sigint_after_third_request(self):
        """Start `run`, SIGINT once the third unit's request is in flight.

        Per the M1 runner contract the first SIGINT drains the in-flight
        bounded request, finalizes it, and stops before the next unit.
        """
        delayed = self.order[2]
        self.endpoint.delays = {delayed: 6.0}
        proc = support.popen_cli(['run', '--profile', self.profile_path])
        try:
            self.endpoint.wait_for(
                lambda: self.endpoint.post_count(delayed) >= 1, timeout=90,
                message=f'request for third unit {delayed} never reached the endpoint')
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=120)
        except Exception:
            proc.kill()
            proc.communicate()
            raise
        self.assertEqual(proc.returncode, 130,
                         f'SIGINT must exit 130; stdout={out} stderr={err}')
        return out

    def revision(self):
        return json.loads((self.section / 'run.json').read_bytes())['profile_revision']

    def evidence_tree(self):
        return {str(p.relative_to(self.section)): support.snapshot_file(p)
                for p in sorted(self.section.rglob('*')) if p.is_file()}

    def assert_first_k_finalized(self, k):
        proc = support.cli(['status', '--json', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['state'], 'INTERRUPTED')
        self.assertFalse(doc['finalizable'], 'INTERRUPTED renders no verdict')
        self.assertEqual(doc['remaining_units'], self.order[k:])
        rows = {r['unit_id']: r for r in doc['units']}
        for uid in self.order[:k]:
            row = rows[uid]
            self.assertEqual(row['attempts'], 1, f'{uid}: completed record kept')
            self.assertFalse(row['pending'], uid)
            self.assertEqual(row['outcome'], 'FAIL' if self.behaviors[uid] == 'fail' else 'PASS', uid)
        for uid in self.order[k:]:
            self.assertEqual(rows[uid]['attempts'], 0, f'{uid}: not yet executed')
            self.assertEqual(rows[uid]['outcome'], 'NOT_RUN', uid)
        return doc


class SigintDrainsInflightAndResumeCompletes(InterruptResumeBase):
    def test_sigint_after_third_request_then_resume_without_double_execution(self):
        behaviors = self.configure(
            behaviors={uid: 'pass' for uid in self.order} |
                      {self.order[0]: 'fail'})
        self.run_until_sigint_after_third_request()
        self.assert_first_k_finalized(3)
        # The in-flight unit was drained to a fully finalized attempt.
        receipt = [r for r in self.endpoint.posts if r['unit'] == self.order[2]][0]
        support.check_finalized_attempt(
            self, self.order[2], self.section / 'evidence' / self.order[2] / '0001',
            receipt, self.revision(), 'PASS', None)
        events = support.read_events(self.section)
        self.assertTrue(any(e.get('event') == 'INTERRUPTED' for e in events),
                        'the interruption must be recorded in the event ledger')
        self.assertEqual(self.endpoint.post_count(self.order[0]), 1,
                         'the FAIL unit was executed exactly once')

        proc = support.cli(['resume', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['state'], 'COMPLETED')
        self.assertEqual(doc['remaining_units'], [])
        rows = {r['unit_id']: r for r in doc['units']}
        for uid in self.order:
            row = rows[uid]
            self.assertEqual(row['attempts'], 1,
                             f'{uid}: no duplicate finalized attempt (no double credit)')
            self.assertEqual(row['resolved_attempt'], '0001', uid)
            expected = ('FAIL' if uid == self.order[0] else
                        'NOT_EVALUABLE' if uid == support.safety_unit_id() else 'PASS')
            self.assertEqual(row['outcome'], expected, uid)
            self.assertEqual(self.endpoint.post_count(uid), 1,
                             f'{uid}: executed exactly once across run+resume')
        events = support.read_events(self.section)
        started = [e for e in events if e.get('event') == 'STARTED']
        finalized = [e for e in events if e.get('event') == 'FINALIZED']
        self.assertEqual(len(started), 20, 'exactly one STARTED per unit overall')
        self.assertEqual(len(finalized), 20, 'exactly one FINALIZED per unit overall')
        self.assertTrue(any(e.get('event') == 'INTERRUPTED' for e in events),
                        'append-only ledger keeps the interruption record')

        self.endpoint.stop()  # report from disk alone
        proc = support.cli(['report', '--campaign', self.campaign,
                            '--section', 'baseline'])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(support.cli_json(proc)['disposition'], 'PASS')
        support.verify_manifest_integrity(self, self.section)


class ResumeRejectsAlteredConfiguration(InterruptResumeBase):
    def test_altered_profile_is_rejected_and_recovery_stays_pinned(self):
        self.configure()
        self.run_until_sigint_after_third_request()
        self.assert_first_k_finalized(3)
        frozen = self.evidence_tree()

        altered = dict(self.profile)
        altered['budgets'] = dict(self.profile['budgets'],
                                  max_tokens=self.profile['budgets']['max_tokens'] + 1)
        altered_path = support.write_profile(self.workdir, altered,
                                             name='profile-altered.json')
        proc = support.cli(['run', '--profile', altered_path])
        self.assertEqual(proc.returncode, 2,
                         f'altered configuration must be rejected: {proc.stdout}')
        doc = support.cli_json(proc)
        self.assertEqual(doc['disposition'], 'BLOCKED')
        self.assertTrue(any(n in doc['check'].lower()
                            for n in ('recovery', 'changed', 'profile_revision')),
                        f'check must name the recovery pin: {doc["check"]}')
        self.assertEqual(self.evidence_tree(), frozen,
                         'rejected run must not touch existing evidence')

        # Recovery still uses the pinned profile and completes cleanly.
        proc = support.cli(['resume', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['state'], 'COMPLETED')
        rows = {r['unit_id']: r for r in doc['units']}
        for uid in self.order:
            self.assertEqual(rows[uid]['attempts'], 1, uid)
            self.assertEqual(self.endpoint.post_count(uid), 1, uid)


if __name__ == '__main__':
    unittest.main()
