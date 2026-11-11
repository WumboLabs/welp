"""M1 consumer semantics: offline plan, fail-closed profile validation, A6 selftest."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
from welp_next import scoring  # noqa: E402  (offline contract interfaces)


class PlanOffline(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('plan')
        self.addCleanup(support.shutil.rmtree, self.workdir, True)
        self.tasks_by_id = {t['id']: t for t in support.fixture_tasks()}
        self.endpoint = support.SyntheticEndpoint(tasks_by_id=self.tasks_by_id).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.workdir / 'campaign'
        self.profile = support.build_profile(self.workdir, self.endpoint.endpoint_url,
                                             self.campaign)
        self.profile_path = support.write_profile(self.workdir, self.profile)

    def test_plan_validates_offline_and_emits_20_units_without_any_request(self):
        proc = support.cli(['plan', '--json', '--profile', self.profile_path])
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        plan = support.cli_json(proc)
        self.assertEqual(plan['section'], 'baseline')
        self.assertEqual(plan['part'], 'reliability')
        self.assertEqual(plan['evidence_kind'], 'SOFTWARE_TEST')
        self.assertEqual(plan['profile_id'], self.profile['profile_id'])
        self.assertEqual(plan['profile_revision'], support.sha256_bytes(support.canonical(self.profile)))
        self.assertEqual(plan['unit_ids'], support.unit_ids())
        self.assertEqual(len(plan['unit_ids']), 20)
        # Offline plan never contacts the endpoint (no GET /models, no POST).
        self.assertEqual(self.endpoint.request_count(), 0)
        # Plan is a dry run: no campaign evidence is created.
        self.assertFalse((self.campaign / 'sections').exists())


    def test_scorer_selftest_demonstrates_facet_outcomes_offline(self):
        # M1 acceptance A6: PASS, FAIL, NOT_EVALUABLE/BUDGET_LIMITED, INVALID.
        result = scoring.selftest()
        self.assertTrue(result.get('pass'),
                        f"scorer selftest failures: {result.get('failures')}")


class InvalidProfilesFailClosed(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('invalid-profile')
        self.addCleanup(support.shutil.rmtree, self.workdir, True)
        self.tasks_by_id = {t['id']: t for t in support.fixture_tasks()}
        self.endpoint = support.SyntheticEndpoint(tasks_by_id=self.tasks_by_id).start()
        self.addCleanup(self.endpoint.stop)
        self.campaign = self.workdir / 'campaign'
        self.base = support.build_profile(self.workdir, self.endpoint.endpoint_url,
                                          self.campaign)

    def write_variant(self, name, profile, raw=None):
        if raw is not None:
            path = self.workdir / f'{name}.json'
            path.write_text(raw, encoding='utf-8')
            return path
        return support.write_profile(self.workdir, profile, name=f'{name}.json')

    def variants(self):
        bad_backend = json.loads(json.dumps(self.base))
        bad_backend['runtime']['backend'] = 'QUANTUM'
        sha_mismatch = json.loads(json.dumps(self.base))
        sha_mismatch['model']['artifact']['sha256'] = 'not-a-model-digest'
        bad_capacity = json.loads(json.dumps(self.base))
        bad_capacity['runtime']['context_capacity'] = 'unlimited'
        wrong_target = json.loads(json.dumps(self.base))
        wrong_target['context']['target'] = 999999
        # (name, profile-path, substrings any-of which must appear in the
        # named check; empty set = only require a nonempty check string)
        return [
            ('bad-backend', self.write_variant('bad-backend', bad_backend), {'backend'}),
            ('artifact-sha-mismatch', self.write_variant('artifact-sha-mismatch', sha_mismatch), {'sha', 'artifact'}),
            ('bad-context-capacity', self.write_variant('bad-context-capacity', bad_capacity), {'capacity'}),
            ('context-target-exceeds-capacity', self.write_variant('target-exceeds', wrong_target), {'capacity', 'target', 'context'}),
            ('malformed-json', self.write_variant('malformed', None, raw='{"schema_version": 1,'), set()),
        ]

    def test_plan_rejects_invalid_profiles_with_named_check_and_no_contact(self):
        for name, path, needles in self.variants():
            with self.subTest(variant=name):
                proc = support.cli(['plan', '--profile', path])
                self.assertEqual(proc.returncode, 2,
                                 f'{name}: expected BLOCKED exit 2, got '
                                 f'{proc.returncode}; stdout={proc.stdout}')
                doc = support.cli_json(proc)
                self.assertEqual(doc['disposition'], 'BLOCKED')
                self.assertIsInstance(doc.get('check'), str)
                self.assertTrue(doc['check'], f'{name}: named check expected')
                if needles:
                    self.assertTrue(any(n in doc['check'].lower() for n in needles),
                                    f'{name}: check does not name the field: '
                                    f'{doc["check"]}')
        # Fail-closed before any measurement: the live endpoint saw nothing.
        self.assertEqual(self.endpoint.request_count(), 0)

    def test_run_rejects_invalid_profile_before_campaign_evidence(self):
        name, path, _ = self.variants()[0]  # bad backend enum
        proc = support.cli(['run', '--profile', path])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertEqual(doc['disposition'], 'BLOCKED')
        self.assertFalse((self.campaign / 'sections').exists(),
                         'no section evidence may exist for a rejected profile')
        self.assertEqual(self.endpoint.request_count(), 0)


if __name__ == '__main__':
    unittest.main()
