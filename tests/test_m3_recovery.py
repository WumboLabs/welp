"""A mutable run index cannot discard required Agentic tasks or create completion."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from welp_next import agentic, m3, policy, store


class FixedInventory(unittest.TestCase):
    def test_dropped_or_added_tasks_cannot_finalize_or_report_completion(self):
        scratch = Path(__file__).resolve().parents[1] / 'tmp/m3-advancement-agentic/tests'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            campaign = Path(temporary)
            section = m3.section_path(campaign, 'agentic')
            fixtures = {name: agentic.load_fixture(name) for name in m3.TASKS['agentic']}
            profile = {'evidence_kind': 'SOFTWARE_TEST', 'profile_id': 'software-inventory'}
            limits = {'evidence_kind': 'SOFTWARE_TEST', 'source': 'SOFTWARE_TEST fixed inventory regression',
                      'max_turns': 2, 'total_tokens': 200, 'max_tokens': 100,
                      'wall_seconds': 5, 'command_seconds': 1}
            config = {'section': 'agentic', 'methodology': m3.METHODOLOGY,
                      'profile': profile, 'profile_revision': policy.digest(profile),
                      'unit_ids': list(m3.TASKS['agentic']), 'fixture_sha256': policy.digest(fixtures),
                      'agentic_config': {'evidence_kind': 'SOFTWARE_TEST', 'adapter': 'text_json',
                                        'limits': {name: limits for name in fixtures}}}
            for name, value in [('run.json', config), ('profile.json', profile), ('fixture.json', fixtures)]:
                store.put_json(section / name, value)
            initial = m3.status(campaign, 'agentic')
            self.assertEqual(initial['state'], 'INTERRUPTED')
            self.assertEqual(set(initial['remaining_units']), set(m3.TASKS['agentic']))
            for identities in ([], ['repository'], ['repository', 'system', 'research', 'extra']):
                with self.subTest(identities=identities):
                    changed = copy.deepcopy(config)
                    changed['unit_ids'] = identities
                    (section / 'run.json').write_text(json.dumps(changed))
                    with self.assertRaises(policy.CheckError):
                        m3.status(campaign, 'agentic')
                    with self.assertRaises(policy.CheckError):
                        m3.report_section(campaign, 'agentic')
