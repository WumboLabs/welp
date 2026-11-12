"""Lean release validator (SPEC §11/§8 REWRITE row) and the campaign-bound
activation-record correction: shared predicates only, fail-closed,
honest negative outcomes, no live inference."""
import copy
import json
import unittest
from pathlib import Path

from welp_next import __main__ as cli
from welp_next import policy, release_validation
from welp_next import runtime_performance as perf
import support


def run_section(content='No game here, sorry.', label='release'):
    """Fast finalized section campaign (artifact-deficient: no sandbox run)."""
    workdir = support.make_workdir(f'release-{label}')
    campaign = workdir / f'{label}-campaign'
    campaign.mkdir()
    profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1', campaign)
    profile['framework'] = {'version': policy.FRAMEWORK_M2,
                            'methodology': policy.METHODOLOGY_M2}
    profile['sampling']['qualification_source'] = \
        str(Path(support.__file__).resolve())
    fixture, tasks = perf.load_fixture()
    server = support.SyntheticEndpoint(
        tasks_by_id=tasks,
        payloads={uid: (200, support.canonical(support.envelope(content, 'stop')) + b'\n')
                  for uid in tasks},
        echo_provider=lambda: {**support.identity_echo(profile),
                               'sampling': policy.sampling_settings(profile)})
    server.start()
    try:
        profile['runtime']['serve']['endpoint'] = server.endpoint_url
        perf.run(profile)
    finally:
        server.stop()
    perf.report_section(campaign)
    return campaign, profile


class ReleaseValidation(unittest.TestCase):
    def test_finalized_section_passes_with_replay(self):
        campaign, profile = run_section(label='pass')
        record = release_validation.validate_campaign(campaign)
        self.assertTrue(record['all_finalized_sections_verified'])
        result = record['sections'][0]
        self.assertEqual(result['section'], 'runtime-performance')
        self.assertTrue(result['verified'])
        self.assertEqual(result['units_replayed'], 2)
        self.assertEqual(result['replay_failures'], [])
        self.assertEqual(result['advancement_gate']['decision'], 'ADVANCE')
        # publication dispositions are a campaign-report concern: a
        # section-only campaign reports honestly that none were emitted
        self.assertIsNone(record['publication_disposition'])
        self.assertFalse(record['publication_disposition_emitted'])

    def test_tampered_evidence_fails_closed(self):
        campaign, _ = run_section(label='tamper')
        section = campaign / 'sections' / 'runtime-performance'
        score = section / 'evidence' / 'perf-short' / '0001' / 'score.json'
        score.write_bytes(score.read_bytes() + b'\n')  # one-byte material alteration
        with self.assertRaises(policy.CheckError):
            release_validation.validate_campaign(campaign)

    def test_invalid_outcomes_close_normally_without_credit(self):
        # artifact-deficient replies on sanity workloads are unusable
        # repeated responses: the accepted disposition is INVALID with a
        # bounded retry, both attempts closing INVALID — no scientific
        # credit, and the validator still admits them as verified records
        campaign, _ = run_section(label='negative')
        record = release_validation.validate_campaign(campaign)
        self.assertTrue(record['all_finalized_sections_verified'])
        status = perf.status(campaign)
        self.assertEqual(status['units'][0]['outcome'], 'INVALID')
        self.assertEqual(status['units'][1]['outcome'], 'INVALID')
        self.assertEqual(status['state'], 'COMPLETED_PARTIAL')

    def test_evaluation_detection_and_readiness_aggregation(self):
        # pure aggregation over validator records: a finalized, replay-
        # verified baseline with an exercised gate counts as one evaluation
        verified_baseline = {'section': 'baseline', 'present': True, 'verified': True,
                             'profile_id': 'p-1'}
        gated = {'section': 'runtime-performance', 'present': True, 'verified': True,
                 'profile_id': 'p-1', 'advancement_gate': {'decision': 'ADVANCE'}}
        entry = release_validation._evaluation_from_record(
            {'campaign': 'c1', 'sections': [verified_baseline, gated],
             'all_finalized_sections_verified': True})
        self.assertIsNotNone(entry)
        self.assertTrue(entry['advancement_decisions_exercised'])
        self.assertIsNone(release_validation._evaluation_from_record(
            {'campaign': 'c2', 'sections': [dict(verified_baseline, verified=False)],
             'all_finalized_sections_verified': False}))
        # a baseline without an exercised gate records the evaluation but
        # does not satisfy the exercised-gate requirement
        without_gate = release_validation._evaluation_from_record(
            {'campaign': 'c3', 'sections': [dict(verified_baseline),
                                            dict(gated, advancement_gate=None)],
             'all_finalized_sections_verified': True})
        self.assertIsNotNone(without_gate)
        self.assertFalse(without_gate['advancement_decisions_exercised'])
        from unittest.mock import patch
        baseline_only = {
            'campaign': 'c3', 'campaign_root': '/c3',
            'sections': [verified_baseline],
            'all_finalized_sections_verified': True}
        with patch.object(release_validation, 'validate_campaign',
                          return_value=baseline_only):
            readiness = release_validation.release_readiness(['/c3'] * 3)
        self.assertFalse(readiness['requirement_three_diverse_real_model_evaluations']['met'])
        specialist = {
            'campaign': 'specialist', 'campaign_root': '/specialist',
            'sections': [dict(gated, baseline_reference={'campaign_root': '/c3'})],
            'all_finalized_sections_verified': True}
        with patch.object(release_validation, 'validate_campaign',
                          side_effect=[baseline_only, specialist]):
            readiness = release_validation.release_readiness(['/c3', '/specialist'])
        self.assertEqual(readiness['distinct_evaluations_with_baseline_and_gate'], 1)

    def test_cli_validate_subcommand(self):
        campaign, _ = run_section(label='cli')
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(['validate', '--campaign', str(campaign), '--json'])
        self.assertEqual(code, 0)
        record = json.loads(buffer.getvalue())
        self.assertTrue(record['all_finalized_sections_verified'])


if __name__ == '__main__':
    unittest.main()
