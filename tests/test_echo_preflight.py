"""M1 consumer semantics: exact echo contract enforcement before any measurement."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402


class EchoDisagreement(unittest.TestCase):
    def setUp(self):
        self.workdir = support.make_workdir('echo')
        self.addCleanup(support.shutil.rmtree, self.workdir, True)
        self.tasks_by_id = {t['id']: t for t in support.fixture_tasks()}
        self.campaign = self.workdir / 'campaign'
        self.section = support.section_path(self.campaign)
        # The endpoint echo is created after the profile exists; use a mutable
        # provider that resolves once the profile is built in the test body.
        self.echo_override = None
        self.endpoint = support.SyntheticEndpoint(
            tasks_by_id=self.tasks_by_id,
            echo_provider=lambda: (self.echo_override if self.echo_override
                                   else support.identity_echo(self.profile)),
        )
        self.endpoint.start()
        self.addCleanup(self.endpoint.stop)
        self.profile = support.build_profile(self.workdir, self.endpoint.endpoint_url,
                                             self.campaign)
        self.profile_path = support.write_profile(self.workdir, self.profile)

    def test_artifact_sha_disagreement_fails_closed_before_any_post(self):
        disagreeing = support.identity_echo(self.profile)
        disagreeing['artifact_sha256'] = 'f' * 64
        self.echo_override = disagreeing
        proc = support.cli(['run', '--profile', self.profile_path])
        self.assertEqual(proc.returncode, 2,
                         f'echo disagreement must fail closed: {proc.stdout}')
        doc = support.cli_json(proc)
        self.assertEqual(doc['disposition'], 'BLOCKED')
        self.assertTrue(doc.get('check'), 'a named check must be reported')
        # The preflight exchange happened, but no measurement request did.
        self.assertGreaterEqual(len(self.endpoint.gets), 1,
                                'preflight must consult the endpoint echo')
        self.assertEqual(self.endpoint.post_count(), 0,
                         'zero measurement POSTs on echo disagreement')
        self.assertFalse((self.section / 'evidence').exists(),
                         'no unit evidence may exist before echo agreement')
        proc = support.cli(['status', '--json', '--campaign', self.campaign])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = support.cli_json(proc)
        self.assertFalse(doc['finalizable'], 'no verdict without valid measurements')
        for row in doc['units']:
            self.assertEqual(row['outcome'], 'NOT_RUN', row)
            self.assertTrue(row['pending'], row)
            self.assertEqual(row['attempts'], 0, row)


if __name__ == '__main__':
    unittest.main()
