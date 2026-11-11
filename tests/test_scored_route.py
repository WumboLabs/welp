"""Campaign-gated scored-route controls; all manufactured data is offline.

No inference, no campaign activation and no live endpoint is exercised.
These tests pin: gate-off rejection, standard-configuration immutability,
cross-backend scientific compatibility per SPEC §3.2/§3.3, and scored
readiness admission semantics.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from welp_next import agentic, m3, policy, scored


def base_profile(backend='CUDA'):
    """Minimal valid REAL_MODEL M2 surface mirroring the accepted HIP profile."""
    return {
        'schema_version': 1,
        'framework': {'version': 'welp/1.0.0-alpha-m2', 'methodology': 'model-baseline/2'},
        'evidence_kind': 'REAL_MODEL',
        'profile_id': 'qwen35-9b-rtx5070-cuda-on-2026-11-06',
        'campaign_id': 'qwen35-9b-rtx5070-cuda-m3-scored-2026-11-06',
        'campaign_root': '/accepted/model-evaluations/'
                         'qwen35-9b/campaign-groups/qwen35-9b-rtx5070-cuda-m3-scored-2026-11-06',
        'model': {'model_key': 'qwen35-9b',
                  'artifact': {'format': 'GGUF', 'path': '/models/qwen.gguf',
                               'revision': 'r', 'sha256': 'a' * 64},
                  'tokenizer_chat_template': {'source': 'native /props', 'sha256': 'b' * 64}},
        'runtime': {'backend': backend, 'context_capacity': 16384,
                    'engine': {'name': 'llama.cpp', 'version': 'b11827',
                               'path': '/srv/llama-server', 'sha256': 'c' * 64},
                    'serve': {'endpoint': 'http://127.0.0.1:18974', 'model_id': '/models/qwen.gguf',
                              'echo_path': '/props'}},
        'context': {'target': 16384},
        'reasoning': {'arm': 'ON', 'controls': {'chat_template_kwargs': {'enable_thinking': True}}},
        'sampling': {'temperature': 1.0, 'top_p': 0.95, 'top_k': 20, 'min_p': 0.0,
                     'presence_penalty': 1.5, 'repeat_penalty': 1.0, 'seed': 42,
                     'qualification_source': '/qualified/wide16k.json'},
        'budgets': {'max_tokens': 4096, 'timeout_seconds': 180,
                    'qualification_source': '/qualified/wide16k.json',
                    'note': 'fixed before outputs'},
        'capabilities': {'native_tools': True, 'context_meter': True, 'sandbox': True,
                         'qualification_source': '/qualified/props.json',
                         'isolation_approval': '/qualified/isolation.json'},
        'deployment': {'reuse_baseline': {'campaign_root': '/accepted/m2',
                                          'section_manifest_sha256': 'd' * 64}},
    }


def hip_variant(profile):
    other = copy.deepcopy(profile)
    other['runtime']['backend'] = 'HIP'
    other['runtime']['engine'].update(version='b11311', path='/hip/llama-server',
                                      sha256='e' * 64)
    other['runtime']['serve']['endpoint'] = 'http://127.0.0.1:18862'
    other['profile_id'] = 'qwen35-9b-r9700-hip-on-2026-10-22'
    return other


def qualification_result(outcome='PASS'):
    return {'interrupted': None, 'calibration': None, 'task_class': 'qualification',
            'task_id': 'agentic-qualification-1-greet-mini-v3', 'outcome': outcome,
            'stop_reason': 'FINISHED' if outcome == 'PASS' else 'TURN_LIMIT',
            'evidence': {'kind': 'REAL_MODEL'}, 'non_scored': True,
            'scored_sample': False, 'checker_version': 3}


class ScoredGate(unittest.TestCase):
    def test_gate_is_inactive_by_default(self):
        profile = base_profile()
        # fail-closed without a campaign-bound activation record
        self.assertIsNone(policy.campaign_activation(
            profile['campaign_root'], profile['campaign_id'], policy.SCORED_METHODOLOGY))
        self.assertFalse(scored.authorized(profile))
        # a record for another campaign never authorizes this one
        import support
        workdir = support.make_workdir('scored-gate-inactive')
        other_campaign = workdir / 'other-campaign'
        support.write_activation(str(other_campaign), 'other-campaign',
                                 policy.SCORED_METHODOLOGY)
        profile['campaign_id'] = 'scored-gate-campaign'
        profile['campaign_root'] = str(other_campaign)
        self.assertFalse(scored.authorized(profile))

    def test_activation_record_authorizes_only_the_bound_campaign(self):
        import support
        workdir = support.make_workdir('scored-gate-active')
        profile = base_profile()
        profile['campaign_id'] = 'scored-gate-campaign'
        profile['campaign_root'] = str(workdir / 'scored-gate-campaign')
        support.write_activation(profile['campaign_root'], profile['campaign_id'],
                                 policy.SCORED_METHODOLOGY)
        self.assertTrue(scored.authorized(profile))
        record = scored.activation_record(profile)
        self.assertEqual(record['campaign'], 'scored-gate-campaign')
        self.assertEqual(record['methodology'], policy.SCORED_METHODOLOGY)
        # malformed shapes stay fail-closed
        (Path(profile['campaign_root']) / policy.ACTIVATION_FILENAME).write_text('{}')
        self.assertFalse(scored.authorized(profile))
        support.write_activation(profile['campaign_root'], profile['campaign_id'],
                                 'agentic-calibration/1')  # wrong methodology binding
        self.assertFalse(scored.authorized(profile))

    def test_plan_requires_activation_and_real_model(self):
        profile = base_profile()
        config = scored.standard_config('agentic-readiness', ())
        with self.assertRaises(policy.CheckError) as ctx:
            scored.plan(profile, 'agentic-readiness', config)
        self.assertIn('scored.authorization', str(ctx.exception))
        software = copy.deepcopy(profile)
        software['evidence_kind'] = 'SOFTWARE_TEST'
        import support
        workdir = support.make_workdir('scored-gate-evidence')
        software['campaign_id'] = 'scored-gate-evidence-campaign'
        software['campaign_root'] = str(workdir / 'scored-gate-evidence-campaign')
        support.write_activation(software['campaign_root'], software['campaign_id'],
                                 policy.SCORED_METHODOLOGY)
        with self.assertRaises(policy.CheckError) as ctx:
            scored.plan(software, 'agentic-readiness', config)
        self.assertIn('REAL_MODEL', str(ctx.exception))

    def test_standard_config_is_immutable_and_rejects_substitution(self):
        profile = base_profile()
        config = scored.standard_config('agentic-readiness', ())
        limits = config['limits']['qualification']
        self.assertEqual(limits['evidence_kind'], 'REAL_MODEL')
        self.assertEqual(tuple(limits[k] for k in agentic.LIMIT_KEYS),
                         m3.STANDARD_VECTORS['qualification'])
        agentic.validate_limits(limits)  # structural validation accepts gated kind
        import support
        workdir = support.make_workdir('scored-gate-limits')
        gated_profile = base_profile()
        gated_profile['campaign_id'] = 'scored-gate-limits-campaign'
        gated_profile['campaign_root'] = str(workdir / 'scored-gate-limits-campaign')
        support.write_activation(gated_profile['campaign_root'],
                                 gated_profile['campaign_id'],
                                 policy.SCORED_METHODOLOGY)
        self.assertTrue(scored.authorized(gated_profile))
        for mutation in (
                {**config, 'checker_version': 2},
                {**config, 'adapter': 'text_json'},
                {**config, 'budget_version': 'agentic-calibration/1'},
                {**config, 'limits': {**limits, 'max_turns': 17}},
                {**config, 'limits': {**limits, 'evidence_kind': 'SOFTWARE_TEST'}}):
            with self.subTest(mutation=list(mutation)):
                with self.assertRaises(policy.CheckError) as ctx:
                    scored._limits(mutation, 'agentic-readiness', ())
                self.assertIn('scored.config', str(ctx.exception))

    def test_limits_validator_still_blocks_oversized_real_model_response(self):
        limits = scored.standard_config('agentic-readiness', ())['limits']['qualification']
        with self.assertRaises(policy.CheckError):
            agentic.validate_limits({**limits, 'max_tokens': 4097})


class BackendCompatibility(unittest.TestCase):
    def test_identical_science_across_backends_is_compatible(self):
        cuda, hip = base_profile(), hip_variant(base_profile())
        self.assertTrue(policy.compatible_profiles(cuda, hip))

    def test_material_differences_remain_incompatible(self):
        cuda = base_profile()
        for mutate in (
                lambda p: p['sampling'].update(temperature=0.5),
                lambda p: p['model']['tokenizer_chat_template'].update(sha256='f' * 64),
                lambda p: p['reasoning']['controls'].update({'chat_template_kwargs': {}}),
                lambda p: p['runtime'].update(context_capacity=32768),
                lambda p: p.update(evidence_kind='SOFTWARE_TEST'),
                lambda p: p['budgets'].update(max_tokens=2048),
                lambda p: p['capabilities'].update(native_tools=False),
                lambda p: p['model']['artifact'].update(sha256='0' * 64)):
            other = copy.deepcopy(cuda)
            mutate(other)
            self.assertFalse(policy.compatible_profiles(cuda, other),
                             'material scientific change must stay incompatible')


class ScoredReadinessAdmission(unittest.TestCase):
    def test_readiness_gate_admits_only_real_model_checker3_pass(self):
        from welp_next import store
        good = qualification_result()
        self.assertTrue(good['outcome'] == 'PASS' and good['evidence']['kind'] == 'REAL_MODEL')
        for mutate, label in (
                (lambda r: r.update(outcome='FAIL'), 'fail'),
                (lambda r: r.update(evidence={'kind': 'SOFTWARE_TEST'}), 'synthetic'),
                (lambda r: r.update(non_scored=False), 'scored-fixture'),
                (lambda r: r.update(checker_version=2), 'checker2'),
                (lambda r: r.update(interrupted=True), 'interrupted')):
            row = copy.deepcopy(good)
            mutate(row)
            admitted = (row.get('interrupted') is None
                        and row.get('task_class') == 'qualification'
                        and row.get('outcome') == 'PASS'
                        and row.get('evidence', {}).get('kind') == 'REAL_MODEL'
                        and row.get('non_scored') is True
                        and row.get('scored_sample') is False
                        and row.get('checker_version') == 3)
            self.assertFalse(admitted, label)


if __name__ == '__main__':
    unittest.main()


class ReadinessReuse(unittest.TestCase):
    def test_reuse_readiness_attribution_requires_manifest_identity(self):
        import support
        profile = base_profile()
        workdir = support.make_workdir('scored-gate-reuse')
        profile['campaign_id'] = 'scored-gate-reuse-campaign'
        profile['campaign_root'] = str(workdir / 'scored-gate-reuse-campaign')
        support.write_activation(profile['campaign_root'], profile['campaign_id'],
                                 policy.SCORED_METHODOLOGY)
        profile['deployment']['reuse_readiness'] = {
            'campaign_root': '/accepted/scored-campaign',
            'section_manifest_sha256': '9' * 64}
        from welp_next import reporting
        with patch.object(policy, 'file_sha', return_value='mismatch'), \
                patch.object(reporting, 'verify_manifest'):
            with self.assertRaises(policy.CheckError) as ctx:
                scored._readiness_gate(profile['campaign_root'], profile)
        self.assertIn('recorded manifest identity mismatch', str(ctx.exception))
