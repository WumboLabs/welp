"""M1 consumer semantics: full 20-unit run, outcomes, evidence, finalization."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402


class RunMixedCampaignBase(unittest.TestCase):
    """One full run mixing every consumer-visible outcome class."""

    def setUp(self):
        self.workdir = support.make_workdir('mixed')
        self.addCleanup(support.shutil.rmtree, self.workdir, True)
        self.tasks_by_id = {t['id']: t for t in support.fixture_tasks()}
        self.order = support.unit_ids()
        self.safety = support.safety_unit_id()
        self.behaviors = {uid: 'pass' for uid in self.order}
        self.behaviors[self.order[0]] = 'fail'      # complete wrong answer
        self.behaviors[self.order[1]] = 'budget'    # finish 'length'
        self.behaviors[self.order[2]] = 'empty'     # stop + empty content
        self.behaviors[self.order[5]] = 'pass_no_usage'  # usage optional
        self.behaviors[self.safety] = 'rubric'      # reviewed safety, no reviewer
        self.endpoint = support.SyntheticEndpoint(
            tasks_by_id=self.tasks_by_id,
            payloads=support.canned_payloads(self.behaviors, self.tasks_by_id),
        ).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.workdir / 'campaign'
        self.section = support.section_path(self.campaign)
        self.profile = support.build_profile(self.workdir, self.endpoint.endpoint_url,
                                             self.campaign)
        self.profile_path = support.write_profile(self.workdir, self.profile)
        self.endpoint.echo_provider = lambda: support.identity_echo(self.profile)
        self.revision = None

    def run_section(self):
        proc = support.cli(['run', '--profile', self.profile_path])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        run_json = json.loads((self.section / 'run.json').read_bytes())
        self.revision = run_json['profile_revision']
        return run_json

    def expected_outcomes(self):
        expected = {uid: ('PASS', None) for uid in self.order}
        expected[self.order[0]] = ('FAIL', None)
        expected[self.order[1]] = ('NOT_EVALUABLE', 'BUDGET_LIMITED')
        expected[self.order[2]] = ('NOT_EVALUABLE', 'UNSCORABLE_ANSWER')
        expected[self.safety] = ('NOT_EVALUABLE', 'RUBRIC_INDETERMINATE')
        return expected

    def assert_status_matches_evidence(self, doc):
        self.assertEqual(doc['state'], 'COMPLETED')
        self.assertEqual(doc['section'], 'baseline')
        self.assertEqual(doc['evidence_kind'], 'SOFTWARE_TEST')
        self.assertEqual(doc['profile_id'], self.profile['profile_id'])
        self.assertEqual(doc['profile_revision'], self.revision)
        rows = {r['unit_id']: r for r in doc['units']}
        self.assertEqual(sorted(rows), sorted(self.order))
        self.assertEqual(doc['remaining_units'], [])
        self.assertFalse(doc['resumable'])
        self.assertTrue(doc['finalizable'])
        for uid, (outcome, reason) in self.expected_outcomes().items():
            row = rows[uid]
            self.assertEqual(row['outcome'], outcome, f'{uid}: status outcome')
            self.assertEqual(row['reason'], reason, f'{uid}: status reason')
            self.assertEqual(row['attempts'], 1, f'{uid}: exactly one attempt')
            self.assertFalse(row['pending'], f'{uid}: must not be pending')
            self.assertEqual(row['resolved_attempt'], '0001', f'{uid}: resolved attempt')

    def assert_wire_exact_evidence(self):
        for uid in self.order:
            attempts = sorted((self.section / 'evidence' / uid).iterdir())
            self.assertEqual([p.name for p in attempts], ['0001'], uid)
            receipt = [r for r in self.endpoint.posts if r['unit'] == uid]
            self.assertEqual(len(receipt), 1, f'{uid}: exactly one POST on the wire')
            outcome, reason = self.expected_outcomes()[uid]
            _, score, conditions = support.check_finalized_attempt(
                self, uid, attempts[0], receipt[0], self.revision, outcome, reason)
            self.assertEqual(conditions.get('http_status'), 200, uid)
            request = json.loads(receipt[0]['request'])
            self.assertEqual(request['messages'], self.tasks_by_id[uid]['messages'],
                             f'{uid}: request renders the pinned task messages')
            self.assertEqual(request['model'], self.profile['runtime']['serve']['model_id'])
            self.assertFalse(request['stream'], f'{uid}: non-streaming request')
            self.assertEqual(request['max_tokens'],
                             self.profile['budgets']['max_tokens'], uid)
            for key, value in self.profile['sampling'].items():
                self.assertEqual(request.get(key), value, f'{uid}: sampling {key}')
            if uid != self.order[5]:
                self.assertIn('usage', json.loads(receipt[0]['response']), uid)

    def assert_ledger_events(self):
        events = support.read_events(self.section)
        started = [e for e in events if e.get('event') == 'STARTED']
        finalized = [e for e in events if e.get('event') == 'FINALIZED']
        self.assertEqual(len(started), 20, 'one STARTED event per executed attempt')
        self.assertEqual(len(finalized), 20, 'one FINALIZED event per finalized attempt')
        self.assertEqual(sorted(e['unit_id'] for e in started), sorted(self.order))
        self.assertEqual(sorted(e['unit_id'] for e in finalized), sorted(self.order))


class RunOutcomesAndEvidence(RunMixedCampaignBase):
    def test_run_completes_20_units_with_contract_outcomes_and_exact_evidence(self):
        self.run_section()
        proc = support.cli(['status', '--json', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_status_matches_evidence(support.cli_json(proc))
        self.assert_wire_exact_evidence()
        self.assert_ledger_events()
        # Every unit was requested exactly once: no duplicate execution.
        self.assertEqual(self.endpoint.post_count(), 20)


class FinalizationIntegrity(RunMixedCampaignBase):
    def test_report_freezes_manifest_idempotent_and_rejects_tamper(self):
        self.run_section()
        self.endpoint.stop()  # report must render from disk alone
        proc = support.cli(['report', '--campaign', self.campaign,
                            '--section', 'baseline'])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['disposition'], 'PASS')
        report_path = self.section / 'SECTION-REPORT.md'
        manifest_path = self.section / 'manifest.json'
        self.assertTrue(report_path.exists())
        self.assertTrue(manifest_path.exists())
        manifest = support.verify_manifest_integrity(self, self.section)
        self.assertEqual(manifest.get('profile_revision'), self.revision)
        text = report_path.read_text(encoding='utf-8')
        self.assertIn(self.profile['profile_id'], text)
        for uid in self.order:
            self.assertIn(uid, text, 'report must present every unit result')
        # status still verifies the frozen manifest after the server is gone.
        proc = support.cli(['status', '--json', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assert_status_matches_evidence(support.cli_json(proc))

        frozen_report = support.snapshot_file(report_path)
        frozen_manifest = support.snapshot_file(manifest_path)
        proc = support.cli(['report', '--campaign', self.campaign,
                            '--section', 'baseline'])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        again = support.cli_json(proc)
        self.assertTrue(again.get('already_finalized'))
        self.assertEqual(support.snapshot_file(report_path), frozen_report,
                         'finalized report must never be rewritten')
        self.assertEqual(support.snapshot_file(manifest_path), frozen_manifest,
                         'frozen manifest must never be rewritten')

        # Tamper with immutable evidence: every consumer must fail closed.
        target = self.section / 'evidence' / self.order[3] / '0001' / 'response.raw'
        target.write_bytes(target.read_bytes() + b'tampered')
        for args in (['status', '--json', '--campaign', self.campaign],
                     ['report', '--campaign', self.campaign, '--section', 'baseline'],
                     ['resume', '--campaign', self.campaign]):
            proc = support.cli(args)
            self.assertEqual(proc.returncode, 2,
                             f'{args[0]} must reject tampered evidence: {proc.stdout}')
            doc = support.cli_json(proc)
            self.assertEqual(doc['disposition'], 'BLOCKED')
        self.assertEqual(support.snapshot_file(manifest_path), frozen_manifest,
                         'tamper must never trigger a manifest rewrite')
        self.assertEqual(support.snapshot_file(report_path), frozen_report)

        # Added (undeclared) files are equally rejected.
        (self.section / 'smuggled.txt').write_bytes(b'not in the manifest')
        proc = support.cli(['report', '--campaign', self.campaign,
                            '--section', 'baseline'])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(support.snapshot_file(manifest_path), frozen_manifest)

    def test_campaign_report_renders_from_finalized_section(self):
        self.run_section()
        self.endpoint.stop()
        proc = support.cli(['report', '--campaign', self.campaign,
                            '--section', 'baseline'])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        proc = support.cli(['report', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = self.campaign / 'REPORT.md'
        lab_record = self.campaign / 'WELP-LAB-RECORD.md'
        self.assertTrue(report.exists())
        self.assertTrue(lab_record.exists())
        self.assertTrue((self.campaign / 'summaries' / 'classification.json').exists())
        frozen = support.snapshot_file(report)
        proc = support.cli(['report', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(support.snapshot_file(report), frozen,
                         'campaign report is read-only after first render')


if __name__ == '__main__':
    unittest.main()
