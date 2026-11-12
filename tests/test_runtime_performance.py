"""Runtime Performance section: reused M2 measurement machinery, summary
semantics, comparison classification, fault attribution, offline
reconstruction. SOFTWARE_TEST only — synthetic performance evidence stays
explicitly labeled SOFTWARE_TEST and never claims authentic measurement.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from welp_next import baseline, policy, runner, store
from welp_next import runtime_performance as perf
import support

USAGE = {'prompt_tokens': 16, 'completion_tokens': 7, 'total_tokens': 23,
         'completion_tokens_details': {'reasoning_tokens': 4}}
TIMINGS = {'prompt_per_second': 890.5, 'predicted_per_second': 74.25,
           'prompt_n': 16, 'predicted_n': 7, 'cache_n': 0}


def sse(frames):
    body = b''
    for frame in frames:
        body += b'data: ' + support.canonical(frame) + b'\n\n'
    return body + b'data: [DONE]\n\n'


def stream_frames(*, content='42', reasoning=None, usage=USAGE, timings=TIMINGS,
                  finish='stop'):
    frames = []
    if reasoning is not None:
        frames.append({'choices': [{'delta': {'reasoning_content': reasoning}}]})
    frames.append({'choices': [{'delta': {'content': content}}]})
    last = {'choices': [{'delta': {}, 'finish_reason': finish}]}
    if usage is not None:
        last['usage'] = usage
    if timings is not None:
        last['timings'] = timings
    frames.append(last)
    return sse(frames)


def gpu_snapshot(pci_bytes=1073741824, declared='0000:04:00.0', foreign='0000:99:00.0'):
    return {'observations': {'devices': [
        {'pci_id': declared, 'vram_used_bytes': pci_bytes},
        {'pci_id': foreign, 'vram_used_bytes': 4096}]}}


def timing_row(*, usage, cache_state, native_timings=None, native_rate=(812.8, 55.6),
               ttft=0.1364, latency=0.9642, first_byte=0.0101):
    """One recorded timings row in the standardized runner shape."""
    rates = {'prompt': 'UNKNOWN' if native_rate is None else native_rate[0],
             'generation': 'UNKNOWN' if native_rate is None else native_rate[1]}
    timings = {'streaming': True, 'ttft_seconds': ttft, 'first_byte_seconds': first_byte,
               'latency_seconds': latency, 'usage': usage,
               'usage_source': 'sse_usage_frame', 'tokens_per_second': rates,
               'cache_state': cache_state}
    if native_timings is not None:
        timings['native_timings'] = native_timings
    return timings


def variant_profile(profile, **overrides):
    """A materially different deployment variant for comparison tests."""
    variant = json.loads(json.dumps(profile))
    variant.update(overrides)
    return variant


class RuntimePerformance(unittest.TestCase):
    def _run(self, payloads, *, engine='synthetic-threadserver'):
        workdir = support.make_workdir('rt-perf')
        campaign = workdir / 'rt-campaign'
        campaign.mkdir()
        profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1', campaign)
        profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                'methodology': policy.METHODOLOGY_M2}
        profile['runtime']['engine']['name'] = engine
        profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())
        fixture, tasks = perf.load_fixture()
        server = support.SyntheticEndpoint(
            tasks_by_id=tasks, payloads=payloads,
            echo_provider=lambda: {**support.identity_echo(profile),
                                   'sampling': policy.sampling_settings(profile)})
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            perf.run(profile)
        finally:
            server.stop()
        return campaign, tasks, profile, server

    def _payloads(self, frames_for):
        return {uid: (200, frames_for(uid)) for uid in ('perf-short', 'perf-substantial')}

    # -- 1. reused frozen workload identities ------------------------------
    def test_fixture_reuses_m2_performance_identities_verbatim(self):
        fixture, tasks = perf.load_fixture()
        original = {t['id']: t for t in baseline._performance_tasks()}
        self.assertEqual(sorted(tasks), ['perf-short', 'perf-substantial'])
        self.assertEqual(tasks['perf-short'], original['perf-short'])
        self.assertEqual(tasks['perf-substantial'], original['perf-substantial'])
        self.assertEqual(fixture['source']['fixture_id'], baseline.FIXTURE_ID)
        self.assertEqual(tasks['perf-short']['repetitions'],
                         baseline.PERFORMANCE_REPETITIONS)
        self.assertEqual(tasks['perf-short']['method']['cache_prompt'], False)
        self.assertTrue(tasks['perf-short']['method']['streaming'])
        self.assertEqual(tasks['perf-short']['scorer'], 'response_sanity')
        with patch.object(baseline, '_performance_tasks') as tainted:
            changed = json.loads(json.dumps(original['perf-short']))
            changed['method']['streaming'] = False
            changed['repetitions'] = 1
            tainted.return_value = [changed, original['perf-substantial']]
            with self.assertRaises(policy.CheckError):
                perf.load_fixture()

    # -- 2/3/4/5/9/11: full path, accurate accounting, distinct provenance --
    def test_full_measurement_run(self):
        campaign, tasks, profile, server = self._run(
            self._payloads(lambda uid: stream_frames()))
        status = perf.status(campaign)
        self.assertEqual(status['state'], 'COMPLETED')
        section = campaign / 'sections' / 'runtime-performance'
        variant = json.loads(json.dumps(profile))
        variant['runtime']['engine']['version'] = '9.9.9'
        report = perf.report_section(campaign, compare_profile=variant)
        self.assertEqual(report['overall'], 'MEASURED')
        summary = store.read_json(section / 'performance-summary.json')
        self.assertTrue(summary['software_test'])
        self.assertEqual(summary['evidence_kind'], 'SOFTWARE_TEST')
        for uid, workload in summary['workloads'].items():
            self.assertEqual(workload['classification'], 'MEASURED')
            self.assertEqual(workload['outcome'], 'PASS')
            self.assertEqual(len(workload['repeats']), 3)
            for repeat in workload['repeats']:
                native = repeat['native_tokens_per_second']
                wall = repeat['observed_wall_clock']
                # native engine rates recorded verbatim, prompt/generation separate
                self.assertEqual(native['prompt'], TIMINGS['prompt_per_second'])
                self.assertEqual(native['generation'], TIMINGS['predicted_per_second'])
                self.assertNotEqual(native['prompt'], native['generation'])
                self.assertEqual(native['provenance'], 'native_engine_timings')
                # wall-clock derivatives present, labeled, distinct from native
                self.assertEqual(wall['provenance'], 'derived_wall_clock')
                self.assertIsInstance(wall['prompt_per_second'], float)
                self.assertIsInstance(wall['generation_per_second'], float)
                # first-byte vs TTFT vs total latency: distinct recorded metrics
                self.assertIsInstance(repeat['first_byte_seconds'], float)
                self.assertIsInstance(repeat['ttft_seconds'], float)
                self.assertIsInstance(repeat['latency_seconds'], float)
                self.assertLessEqual(repeat['first_byte_seconds'], repeat['ttft_seconds'])
                self.assertLessEqual(repeat['ttft_seconds'], repeat['latency_seconds'])
                # reasoning-inclusive completion accounting, usage from the SSE frame
                self.assertEqual(repeat['usage']['completion_tokens'], 7)
                self.assertEqual(repeat['reasoning_tokens'], 4)
                self.assertEqual(repeat['usage_source'], 'sse_usage_frame')
                self.assertEqual(repeat['finish_reason'], 'stop')
                self.assertEqual(repeat['cache_state'],
                                 {'cache_n': 0, 'prompt_n': 16})
                self.assertEqual(repeat['required_field_gaps'], [])
            aggregated = workload['aggregation']
            self.assertEqual(aggregated['latency_seconds']['samples'], 3)
            self.assertIn('median', aggregated['latency_seconds'])
            self.assertEqual(aggregated['usage.completion_tokens']['min'], 7)
            self.assertEqual(workload['memory']['available'], False)
            self.assertIn('never zero', ' '.join(workload['limitations']))
            self.assertEqual(workload['metering_consistency'], [])
        # native rates and wall-clock estimates must never be conflated in
        # the summary: the runner's wall-clock/usage division never appears
        # under the native provenance key
        short = summary['workloads']['perf-short']['repeats'][0]
        self.assertNotEqual(short['native_tokens_per_second']['generation'],
                            short['observed_wall_clock']['generation_per_second'])
        # attribution block carries the qualified deployment identity
        attribution = summary['profile_attribution']
        self.assertEqual(attribution['runtime']['engine_name'], 'synthetic-threadserver')
        self.assertEqual(attribution['hardware']['device']['pci_id'], '0000:04:00.0')
        self.assertEqual(attribution['model']['artifact_sha256'],
                         profile['model']['artifact']['sha256'])
        # comparison classification against a runtime-version variant: the
        # corrected semantics treat the runtime identity as the compared
        # variable (recorded, not required identical)
        comparison = summary['comparison']
        self.assertEqual(comparison['class'], 'MATCHED_RUNTIME')
        self.assertTrue(comparison['comparison_allowed'])
        self.assertEqual(comparison['runtime_under_comparison']['profile_b']['runtime.engine_version'],
                         '9.9.9')
        self.assertNotIn('runtime.engine_version', comparison['differing_fields'])
        self.assertEqual(comparison['matched_fields'], list(perf.MATERIAL_CONTROLS))
        # offline reconstruction + manifest integrity + idempotent finalization
        for uid, task in tasks.items():
            rows = store.inventory(section)[1][uid]
            replayed, fatal = runner.replay_attempt(profile, task,
                                                    Path(rows[0]['path']))
            self.assertFalse(fatal)
            self.assertEqual(replayed['outcome'], 'PASS')
        support.verify_manifest_integrity(self, section)
        before = (section / 'manifest.json').read_bytes()
        again = perf.report_section(campaign)
        self.assertTrue(again['already_finalized'])
        self.assertEqual((section / 'manifest.json').read_bytes(), before)

    # -- 7. missing/unavailable telemetry is honest ------------------------
    def test_missing_native_telemetry_is_unavailable_never_zero(self):
        campaign, _, profile, _ = self._run(
            self._payloads(lambda uid: stream_frames(timings=None, usage={
                k: v for k, v in USAGE.items() if k != 'completion_tokens_details'})))
        section = campaign / 'sections' / 'runtime-performance'
        report = perf.report_section(campaign)
        self.assertEqual(report['overall'], 'PARTIAL')
        summary = store.read_json(section / 'performance-summary.json')
        for workload in summary['workloads'].values():
            self.assertEqual(workload['classification'], 'MEASURED_PARTIAL')
            for repeat in workload['repeats']:
                self.assertEqual(repeat['native_tokens_per_second']['prompt'], 'UNKNOWN')
                self.assertEqual(repeat['native_tokens_per_second']['generation'], 'UNKNOWN')
                self.assertNotIn(0, (repeat['native_tokens_per_second']['prompt'],
                                     repeat['native_tokens_per_second']['generation']))
                self.assertEqual(repeat['reasoning_tokens'], 'UNAVAILABLE')
                self.assertEqual(repeat['required_field_gaps'],
                                 ['prompt_throughput', 'generation_throughput'])
                wall = repeat['observed_wall_clock']
                self.assertIsInstance(wall['generation_per_second'], float)
            self.assertTrue(any('unavailable, never zero' in line
                                for line in workload['limitations']))
            self.assertEqual(workload['memory']['available'], False)

    # -- D. memory attribution to the declared device ----------------------
    def test_memory_snapshots_attributed_to_declared_device(self):
        real_finalize = store.finalize_attempt

        def observer(path, score, methodology=None):
            store.put_json(path / 'gpu-before.json', gpu_snapshot(pci_bytes=1073741824))
            store.put_json(path / 'gpu-after.json', gpu_snapshot(pci_bytes=1174405120))
            return real_finalize(path, score, methodology=methodology)

        with patch.object(store, 'finalize_attempt', observer):
            campaign, _, _, _ = self._run(
                self._payloads(lambda uid: stream_frames()))
        section = campaign / 'sections' / 'runtime-performance'
        perf.report_section(campaign)
        summary = store.read_json(section / 'performance-summary.json')
        for workload in summary['workloads'].values():
            memory = workload['memory']
            self.assertTrue(memory['available'])
            self.assertEqual(memory['before'], 1073741824)
            self.assertEqual(memory['after'], 1174405120)
            self.assertEqual(memory['delta_bytes'], 100663296)
            self.assertEqual(memory['unit'], 'bytes')
            self.assertIn('device-wide', memory['note'])
            self.assertFalse(any('memory telemetry unavailable' in line
                                 for line in workload['limitations']))

    def test_foreign_device_telemetry_is_never_attributed(self):
        real_finalize = store.finalize_attempt

        def observer(path, score, methodology=None):
            foreign = {'observations': {'devices': [
                {'pci_id': '0000:99:00.0', 'vram_used_bytes': 8192}]}}
            store.put_json(path / 'gpu-before.json', foreign)
            store.put_json(path / 'gpu-after.json', foreign)
            return real_finalize(path, score, methodology=methodology)

        with patch.object(store, 'finalize_attempt', observer):
            campaign, _, _, _ = self._run(
                self._payloads(lambda uid: stream_frames()))
        section = campaign / 'sections' / 'runtime-performance'
        perf.report_section(campaign)
        summary = store.read_json(section / 'performance-summary.json')
        for workload in summary['workloads'].values():
            memory = workload['memory']
            self.assertFalse(memory['available'])
            self.assertEqual(memory['before'], 'UNAVAILABLE')
            self.assertIn('never zero', memory['note'])

    # -- 8/10. invalid runtime responses cannot claim performance ----------
    def test_invalid_runtime_response_never_yields_measurement(self):
        campaign, _, _, _ = self._run(self._payloads(
            lambda uid: b'not an envelope at all\n'))
        section = campaign / 'sections' / 'runtime-performance'
        status = perf.status(campaign)
        # invalid outcomes keep the section measured-only-in-part: the units
        # completed their attempt accounting with invalid measurements
        self.assertEqual(status['state'], 'COMPLETED_PARTIAL')
        report = perf.report_section(campaign)
        self.assertEqual(report['overall'], 'NOT_MEASURED')
        summary = store.read_json(section / 'performance-summary.json')
        for workload in summary['workloads'].values():
            self.assertEqual(workload['classification'], 'NOT_MEASURED')
            self.assertNotEqual(workload['outcome'], 'PASS')
            # no token/rate/usage figure may be aggregated for an invalid
            # measurement; only the exchange's observed wall-clock windows
            # remain, honestly recorded
            aggregated = workload['aggregation']
            self.assertEqual(sorted(aggregated), ['first_byte_seconds', 'latency_seconds'])
            # the invalid exchange's observations stay recorded, honestly
            # unknown — no token, rate or usage claim is manufactured
            for repeat in workload['repeats']:
                self.assertIsNone(repeat['usage'])
                self.assertEqual(repeat['usage_source'], 'UNAVAILABLE')
                self.assertEqual(repeat['native_tokens_per_second']['prompt'], 'UNKNOWN')
                self.assertEqual(repeat['observed_wall_clock']['generation_per_second'],
                                 'UNKNOWN')

    def test_sse_error_frame_is_fatal_infrastructure_stop(self):
        payloads = self._payloads(
            lambda uid: b'data: {"error":{"message":"HIP memory allocation failure"}}'
                        b'\n\ndata: [DONE]\n\n')
        campaign, _, _, _ = self._run(payloads)
        status = perf.status(campaign)
        # the shared fatal condition stops the section run: the first unit
        # carries the HOST invalid with its EXECUTION_FAILURE reason, the
        # second stays pending, and finalization is refused
        self.assertEqual(status['units'][0]['outcome'], 'INVALID')
        self.assertEqual(status['units'][0]['reason'], 'EXECUTION_FAILURE')
        self.assertTrue(status['remaining_units'])
        attempts = store.inventory(campaign / 'sections'
                                   / 'runtime-performance')[1]['perf-short']
        score = store.read_json(Path(attempts[0]['path']) / 'score.json')
        self.assertTrue(score['host'])
        with self.assertRaises(policy.CheckError):
            perf.report_section(campaign)
        self.assertFalse((campaign / 'sections' / 'runtime-performance'
                          / 'performance-summary.json').exists())

    # -- latency semantics on the shared runner ----------------------------
    def test_failed_stream_without_token_keeps_ttft_unknown(self):
        timing = runner._timings(
            {'streaming': True, 'ttft_seconds': None, 'first_byte_seconds': .01,
             'latency_seconds': .02}, None, 'UNAVAILABLE')
        self.assertEqual(timing['ttft_seconds'], 'UNKNOWN')
        self.assertEqual(timing['tokens_per_second'],
                         {'prompt': 'UNKNOWN', 'generation': 'UNKNOWN'})

    # -- 6. cache condition and native cache observation -------------------
    def test_cache_condition_per_native_contract(self):
        # The shared runner's pinned render: cache_prompt is disabled on the
        # native llama.cpp contract only; generic OpenAI-compatible endpoints
        # never receive the nonstandard key. Native cache observation
        # (cache_n/prompt_n) is recorded verbatim in the full-run test above.
        workdir = support.make_workdir('rt-perf-cache')
        profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1',
                                        workdir / 'cache-campaign')
        profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                'methodology': policy.METHODOLOGY_M2}
        profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())
        _, tasks = perf.load_fixture()
        profile['runtime']['engine']['name'] = 'llama.cpp'
        native = runner.request_body(profile, tasks['perf-short'])
        self.assertIs(native.get('cache_prompt'), False)
        self.assertTrue(native.get('stream'))
        self.assertEqual(native.get('stream_options'), {'include_usage': True})
        generic = runner.request_body(
            {**profile, 'runtime': {**profile['runtime'],
                                    'engine': {'name': 'other-engine', 'version': '1.0.0'}}},
            tasks['perf-short'])
        self.assertNotIn('cache_prompt', generic)

    def test_metering_disagreement_is_labeled_never_reconciled(self):
        campaign, _, _, _ = self._run(self._payloads(
            lambda uid: stream_frames(timings={**TIMINGS, 'predicted_n': 9})))
        section = campaign / 'sections' / 'runtime-performance'
        perf.report_section(campaign)
        summary = store.read_json(section / 'performance-summary.json')
        findings = summary['workloads']['perf-short']['metering_consistency']
        self.assertTrue(findings)
        self.assertEqual(findings[0]['repeat'], 1)
        self.assertIn('predicted_n=9', findings[0]['finding'])
        self.assertIn('runtime/interface', findings[0]['attribution'])
        self.assertIn('never reconciled', findings[0]['resolution'])
        # measurements stay recorded verbatim beside the finding
        self.assertEqual(summary['workloads']['perf-short']['classification'], 'MEASURED')

    # -- E. budget ceiling outcome ----------------------------------------
    def test_budget_ceiling_is_a_legitimate_metered_outcome(self):
        campaign, _, _, _ = self._run(self._payloads(
            lambda uid: stream_frames(content='42 but the answer continues', finish='length',
                                      usage={**USAGE, 'completion_tokens': 60})))
        section = campaign / 'sections' / 'runtime-performance'
        perf.report_section(campaign)
        summary = store.read_json(section / 'performance-summary.json')
        for workload in summary['workloads'].values():
            # the ceiling is carried as the accepted budget-limited outcome
            # while the metered observation itself stays valid
            self.assertEqual(workload['outcome'], 'NOT_EVALUABLE')
            self.assertEqual(workload['reason'], 'BUDGET_LIMITED')
            self.assertEqual(workload['classification'], 'MEASURED')
            for repeat in workload['repeats']:
                self.assertEqual(repeat['finish_reason'], 'length')
                self.assertIsNot(repeat['native_tokens_per_second']['generation'], 'UNKNOWN')

    # -- 7. comparison classification (corrected semantics) ----------------
    def _variant(self, profile, **overrides):
        variant = json.loads(json.dumps(profile))
        for dotted, value in overrides.items():
            if dotted in ('sampling', 'reasoning'):
                variant[dotted] = value
                continue
            group, _, key = dotted.rpartition('.')
            if group == 'runtime' and key.startswith('engine_'):
                variant['runtime']['engine'][key[len('engine_'):]] = value
            elif group == 'runtime':
                variant['runtime'][key] = value
            elif group == 'model':
                raw_key = {'artifact_sha256': 'sha256', 'artifact_format': 'format',
                           'artifact_revision': 'revision'}.get(key, key)
                variant['model']['artifact'][raw_key] = value
            elif group == 'hardware.device':
                variant['hardware']['device'][key] = value
            elif group == 'context':
                variant['runtime']['context_capacity'] = value
            else:
                raise AssertionError(f'unhandled override {dotted}')
        return variant

    def test_comparison_classification(self):
        _, _, profile, _ = self._run(
            self._payloads(lambda uid: stream_frames()))
        identical = json.loads(json.dumps(profile))
        same = perf.compare_profiles(profile, identical)
        # identical deployment: a repeatability comparison, not a runtime one
        self.assertEqual(same['class'], 'SAME_DEPLOYMENT')
        self.assertTrue(same['comparison_allowed'])
        for overrides, expected, field in (
                # a different qualified runtime with matched controls IS the
                # matched-runtime case: the runtime identity is the variable
                ({'runtime.engine_name': 'other-engine'}, 'MATCHED_RUNTIME', None),
                # a runtime version difference alone is also a matched-runtime
                # comparison — recorded, never required identical
                ({'runtime.engine_version': '9.9.9'}, 'MATCHED_RUNTIME', None),
                # material control differences are deployment-stack
                ({'runtime.backend': 'ROCm'}, 'DEPLOYMENT_STACK', 'runtime.backend'),
                ({'hardware.device.pci_id': '0000:05:00.0'},
                 'DEPLOYMENT_STACK', 'hardware.device.pci_id'),
                ({'model.artifact_sha256': 'deadbeef'},
                 'DEPLOYMENT_STACK', 'model.artifact_sha256'),
                ({'model.artifact_format': 'Q8_0'},
                 'DEPLOYMENT_STACK', 'model.artifact_format'),
                ({'context.capacity': 4096}, 'DEPLOYMENT_STACK', 'context.capacity'),
                ({'sampling': {'temperature': 0.7, 'top_p': 0.9, 'seed': 7}},
                 'DEPLOYMENT_STACK', 'sampling'),
                ({'reasoning': {'arm': 'ON', 'controls': {}}},
                 'DEPLOYMENT_STACK', 'reasoning')):
            result = perf.compare_profiles(profile, self._variant(profile, **overrides))
            self.assertEqual(result['class'], expected, field)
            self.assertEqual(result['comparison_allowed'],
                             expected in ('MATCHED_RUNTIME', 'SAME_DEPLOYMENT'), field)
            if field:
                self.assertIn(field, result['differing_fields'], field)
        # the compared variable is always recorded, never required identical
        matched = perf.compare_profiles(
            profile, self._variant(profile, **{'runtime.engine_name': 'other-engine'}))
        self.assertEqual(matched['class'], 'MATCHED_RUNTIME')
        self.assertEqual(matched['runtime_under_comparison']['profile_a']['runtime.engine_name'],
                         profile['runtime']['engine']['name'])
        self.assertEqual(matched['runtime_under_comparison']['profile_b']['runtime.engine_name'],
                         'other-engine')
        self.assertNotIn('runtime.engine_name', matched['differing_fields'])
        self.assertEqual(matched['matched_fields'], list(perf.MATERIAL_CONTROLS))
        # a matched-runtime comparison may not claim isolated runtime
        # causality when a material control also differs
        stacked = perf.compare_profiles(
            profile, self._variant(profile, **{'runtime.engine_name': 'other-engine',
                                               'runtime.backend': 'ROCm'}))
        self.assertEqual(stacked['class'], 'DEPLOYMENT_STACK')
        self.assertIn('runtime.backend', stacked['differing_fields'])

    def test_insufficient_comparability_when_essential_evidence_missing(self):
        _, _, profile, _ = self._run(
            self._payloads(lambda uid: stream_frames()))
        # missing artifact identity on either side: equivalence is never inferred
        no_artifact = json.loads(json.dumps(profile))
        no_artifact['model']['artifact']['sha256'] = None
        result = perf.compare_profiles(profile, no_artifact)
        self.assertEqual(result['class'], 'INSUFFICIENT_COMPARABILITY')
        self.assertFalse(result['comparison_allowed'])
        self.assertIn('model.artifact_sha256', result['unverifiable_fields'])
        # missing device identity
        no_device = json.loads(json.dumps(profile))
        no_device['hardware']['device']['pci_id'] = None
        result = perf.compare_profiles(profile, no_device)
        self.assertEqual(result['class'], 'INSUFFICIENT_COMPARABILITY')
        self.assertIn('hardware.device.pci_id', result['unverifiable_fields'])
        # missing runtime identity: the compared variable is not recordable
        no_engine = json.loads(json.dumps(profile))
        no_engine['runtime']['engine']['name'] = None
        result = perf.compare_profiles(profile, no_engine)
        self.assertEqual(result['class'], 'INSUFFICIENT_COMPARABILITY')
        self.assertIn('runtime.engine_name', result['unverifiable_fields'])

    # -- 12. existing M2 performance semantics unchanged -------------------
    def test_m2_performance_gap_semantics_unchanged(self):
        import shutil
        import tempfile
        base = Path(tempfile.mkdtemp(dir=policy.PROJECT_ROOT / 'tmp'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        profile = {'hardware': {'device': {'pci_id': '0000:04:00.0'}}}
        task = {'id': 'perf-short', 'repetitions': 3}
        good = {'tokens_per_second': {'prompt': 1.0, 'generation': 2.0},
                'latency_seconds': 1.0, 'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
                'streaming': True, 'ttft_seconds': 0.1}
        path = base / 'attempt'
        path.mkdir()
        (path / 'repetitions.json').write_text(json.dumps(
            {'repeats': [{'timings': good} for _ in range(3)]}))
        # memory snapshots absent: the accepted M2 rule records the gap
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, task),
                         ['memory_consumption'])
        (path / 'gpu-before.json').write_text(json.dumps(gpu_snapshot()))
        (path / 'gpu-after.json').write_text(json.dumps(gpu_snapshot()))
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, task), [])
        # accepted M2 rule: either side of the window observing the declared
        # device covers the memory requirement
        (path / 'gpu-after.json').unlink()
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, task), [])
        # snapshots for other devices only: the declared device stays unobserved
        foreign_only = {'observations': {'devices': [
            {'pci_id': '0000:99:00.0', 'vram_used_bytes': 8192}]}}
        (path / 'gpu-before.json').write_text(json.dumps(foreign_only))
        (path / 'gpu-after.json').write_text(json.dumps(foreign_only))
        self.assertEqual(policy.performance_gaps({'path': str(path)}, profile, task),
                         ['memory_consumption'])

    # -- 13. native input/cache interpretation (native-input-cache-split/1) -
    TOTAL_INPUT = {'prompt_tokens': 3659, 'completion_tokens': 47, 'total_tokens': 3706}

    def uncached_row(self):
        """Native no-reuse evidence: the interval IS the full prompt."""
        return timing_row(
            usage=self.TOTAL_INPUT,
            cache_state={'cache_n': 0, 'prompt_n': 3659},
            native_timings={'prompt_n': 3659, 'predicted_n': 47, 'cache_n': 0,
                            'prompt_per_second': 812.8, 'predicted_per_second': 55.6},
            native_rate=(812.8, 55.6))

    def cached_row(self):
        """The measured Strata shape: 5 uncached of 3,659 total input tokens."""
        return timing_row(
            usage=self.TOTAL_INPUT,
            cache_state={'cache_n': 3654, 'prompt_n': 5},
            native_timings={'prompt_n': 5, 'predicted_n': 47, 'cache_n': 3654,
                            'prompt_per_second': 43.9, 'predicted_per_second': 55.6},
            native_rate=(43.9, 55.6), ttft=0.0061, latency=0.8995)

    def test_uncached_full_prompt_counts_are_compatible(self):
        repeat = perf._repeat_measurement(self.uncached_row(), 'stop')
        split = repeat['input_usage']
        self.assertEqual(split['total_input_tokens'], 3659)
        self.assertEqual(split['cache_n'], 0)
        self.assertEqual(split['native_prompt_n'], 3659)
        self.assertEqual(split['uncached_native_prompt_tokens'], 3659)
        self.assertEqual(split['native_cache_state'], 'SPLIT')
        self.assertEqual(repeat['native_tokens_per_second']['prompt_interval_scope'],
                         'full_prompt')
        wall = repeat['observed_wall_clock']
        self.assertEqual(wall['prompt_per_second'], round(3659 / 0.1364, 3))
        self.assertEqual(wall['prompt_numerator_scope'], 'full_prompt')
        self.assertIsNone(wall['prompt_estimate_basis'])

    def test_cached_interval_is_never_a_full_prompt_rate(self):
        repeat = perf._repeat_measurement(self.cached_row(), 'stop')
        split = repeat['input_usage']
        # total input usage, uncached native count and cache reuse stay distinct
        self.assertEqual(split['total_input_tokens'], 3659)
        self.assertEqual(split['native_prompt_n'], 5)
        self.assertEqual(split['cache_n'], 3654)
        self.assertEqual(split['uncached_native_prompt_tokens'], 5)
        self.assertEqual(repeat['native_tokens_per_second']['prompt_interval_scope'],
                         'uncached_native_interval')
        wall = repeat['observed_wall_clock']
        # the estimate divides the five-token uncached interval by its window —
        # never the 3,659-token total over that window (a giant fake rate)
        self.assertEqual(wall['prompt_per_second'], round(5 / 0.0061, 3))
        self.assertEqual(wall['prompt_numerator_scope'], 'uncached_native_interval')
        self.assertLess(wall['prompt_per_second'], 3659 / 0.0061 / 2)
        self.assertIsNone(wall['prompt_estimate_basis'])

    def test_split_explained_prompt_difference_is_not_a_disagreement(self):
        # native prompt_n=5 + cache_n=3654 == usage 3659: compatible quantities,
        # both preserved verbatim, no manufactured finding
        self.assertEqual(perf._metering_consistency([self.cached_row()]), [])
        # an unexplained split is still a labeled finding, never reconciled
        mismatched = timing_row(
            usage=self.TOTAL_INPUT,
            cache_state={'cache_n': 100, 'prompt_n': 5},
            native_timings={'prompt_n': 5, 'predicted_n': 47, 'cache_n': 100},
            native_rate=None)
        findings = perf._metering_consistency([mismatched])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['quantity'], 'input_tokens_split')
        self.assertIn('prompt_n=5 + cache_n=100 != usage prompt_tokens=3659',
                      findings[0]['finding'])
        self.assertIn('never reconciled', findings[0]['resolution'])

    def test_cache_unobserved_withholds_prompt_estimate_never_fabricates(self):
        row = timing_row(usage=self.TOTAL_INPUT, cache_state='UNKNOWN',
                         native_timings=None, native_rate=None)
        repeat = perf._repeat_measurement(row, 'stop')
        split = repeat['input_usage']
        self.assertEqual(split['native_cache_state'], 'UNOBSERVED')
        self.assertEqual(split['uncached_native_prompt_tokens'], 'UNKNOWN')
        self.assertEqual(repeat['native_tokens_per_second']['prompt_interval_scope'],
                         'UNKNOWN')
        wall = repeat['observed_wall_clock']
        self.assertEqual(wall['prompt_per_second'], 'UNKNOWN')
        self.assertIn('not a compatible full-prompt numerator',
                      wall['prompt_estimate_basis'])
        # inclusive completion over its own window stays computable
        self.assertIsInstance(wall['generation_per_second'], float)

    def test_partial_evidence_and_negative_counters_fail_closed(self):
        prompt_only = timing_row(
            usage=self.TOTAL_INPUT,
            cache_state={'cache_n': None, 'prompt_n': 3659},
            native_timings={'prompt_n': 3659}, native_rate=None)
        repeat = perf._repeat_measurement(prompt_only, 'stop')
        self.assertEqual(repeat['input_usage']['native_cache_state'], 'PARTIAL')
        self.assertEqual(repeat['input_usage']['cache_n'], 'UNKNOWN')
        self.assertEqual(repeat['input_usage']['uncached_native_prompt_tokens'], 3659)
        self.assertEqual(repeat['native_tokens_per_second']['prompt_interval_scope'],
                         'native_prompt_interval')
        self.assertEqual(repeat['observed_wall_clock']['prompt_numerator_scope'],
                         'native_prompt_interval')
        negative = timing_row(
            usage=self.TOTAL_INPUT,
            cache_state={'cache_n': -1, 'prompt_n': 3659},
            native_timings={'prompt_n': 3659, 'cache_n': -1}, native_rate=None)
        repeat = perf._repeat_measurement(negative, 'stop')
        self.assertEqual(repeat['input_usage']['native_cache_state'], 'INCOHERENT')
        self.assertEqual(repeat['input_usage']['uncached_native_prompt_tokens'],
                         'UNKNOWN')
        self.assertEqual(repeat['native_tokens_per_second']['prompt_interval_scope'],
                         'UNKNOWN')
        wall = repeat['observed_wall_clock']
        self.assertEqual(wall['prompt_per_second'], 'UNKNOWN')
        self.assertIn('negative native counter', wall['prompt_estimate_basis'])
        findings = perf._metering_consistency([negative])
        self.assertEqual(findings[0]['quantity'], 'native_counters')
        self.assertIn('cache_n=-1', findings[0]['finding'])

    def test_unreconciled_split_withholds_derived_prompt_rates(self):
        # counters that do not reconcile with the runtime's total input
        # accounting (2 + 3654 != 3659): verbatim interval count retained,
        # but no derived prompt rate is manufactured from the disputed shape
        unreconciled = timing_row(
            usage=self.TOTAL_INPUT,
            cache_state={'cache_n': 3654, 'prompt_n': 2},
            native_timings={'prompt_n': 2, 'predicted_n': 47, 'cache_n': 3654},
            native_rate=None)
        repeat = perf._repeat_measurement(unreconciled, 'stop')
        self.assertEqual(repeat['input_usage']['native_cache_state'], 'SPLIT')
        self.assertEqual(repeat['input_usage']['uncached_native_prompt_tokens'], 2)
        self.assertEqual(repeat['native_tokens_per_second']['prompt_interval_scope'],
                         'native_prompt_interval')
        wall = repeat['observed_wall_clock']
        self.assertEqual(wall['prompt_per_second'], 'UNKNOWN')
        self.assertIn('does not reconcile', wall['prompt_estimate_basis'])
        findings = perf._metering_consistency([unreconciled])
        self.assertEqual(findings[0]['quantity'], 'input_tokens_split')
        self.assertIn('prompt_n=2 + cache_n=3654 != usage prompt_tokens=3659',
                      findings[0]['finding'])

    def test_missing_counters_stay_unavailable_never_zero(self):
        repeat = perf._repeat_measurement(
            timing_row(usage=None, cache_state='UNKNOWN',
                       native_timings=None, native_rate=None), 'stop')
        split = repeat['input_usage']
        self.assertEqual(split['total_input_tokens'], 'UNAVAILABLE')
        self.assertEqual(split['cache_n'], 'UNKNOWN')
        self.assertEqual(split['native_prompt_n'], 'UNKNOWN')
        self.assertEqual(split['uncached_native_prompt_tokens'], 'UNKNOWN')
        self.assertNotIn(0, split.values())
        wall = repeat['observed_wall_clock']
        self.assertEqual(wall['prompt_per_second'], 'UNKNOWN')
        self.assertEqual(wall['generation_per_second'], 'UNKNOWN')

    def test_reasoning_inclusive_usage_carried_and_scoped(self):
        usage = {**self.TOTAL_INPUT,
                 'completion_tokens_details': {'reasoning_tokens': 12}}
        repeat = perf._repeat_measurement(
            timing_row(usage=usage,
                       cache_state={'cache_n': 0, 'prompt_n': 3659},
                       native_timings={'prompt_n': 3659, 'predicted_n': 59,
                                       'cache_n': 0}), 'stop')
        # inclusive completion accounting verbatim; reasoning surfaced, not merged
        self.assertEqual(repeat['usage']['completion_tokens'], 47)
        self.assertEqual(repeat['reasoning_tokens'], 12)
        wall = repeat['observed_wall_clock']
        self.assertEqual(wall['completion_numerator_scope'], 'runtime_completion_tokens')
        self.assertIn('inclusive', wall['completion_tokens_note'])
        # predicted_n counts generated tokens including reasoning: 59 vs 47 is a
        # same-quantity disagreement, labeled never reconciled
        findings = perf._metering_consistency(
            [timing_row(usage=usage, cache_state={'cache_n': 0, 'prompt_n': 3659},
                        native_timings={'prompt_n': 3659, 'predicted_n': 59,
                                        'cache_n': 0})])
        self.assertEqual(findings[0]['quantity'], 'generated_tokens')
        self.assertIn('predicted_n=59', findings[0]['finding'])

    def test_reasoning_detail_absent_stays_unavailable(self):
        repeat = perf._repeat_measurement(
            timing_row(usage=dict(self.TOTAL_INPUT), cache_state='UNKNOWN',
                       native_timings=None, native_rate=None), 'stop')
        self.assertEqual(repeat['reasoning_tokens'], 'UNAVAILABLE')

    def test_mixed_prompt_intervals_aggregate_per_scope_only(self):
        repeats = [perf._repeat_measurement(self.cached_row(), 'stop') for _ in range(2)]
        repeats.append(perf._repeat_measurement(self.uncached_row(), 'stop'))
        aggregation = perf._aggregate(repeats)
        # the mixed-interval aggregates are suppressed entirely
        self.assertNotIn('native_tokens_per_second.prompt', aggregation)
        self.assertNotIn('observed_wall_clock.prompt_per_second', aggregation)
        by_scope = aggregation['native_tokens_per_second.prompt_by_scope']
        self.assertEqual(sorted(by_scope),
                         ['full_prompt', 'uncached_native_interval'])
        self.assertEqual(by_scope['uncached_native_interval']['samples'], 2)
        self.assertEqual(by_scope['uncached_native_interval']['min'], 43.9)
        self.assertEqual(by_scope['full_prompt']['samples'], 1)
        self.assertEqual(by_scope['full_prompt']['max'], 812.8)
        wall_by_scope = aggregation['observed_wall_clock.prompt_per_second_by_scope']
        self.assertEqual(sorted(wall_by_scope),
                         ['full_prompt', 'uncached_native_interval'])
        # uniform interval keeps the flat aggregate, now scoped
        uniform = perf._aggregate(
            [perf._repeat_measurement(self.cached_row(), 'stop')])
        flat = uniform['native_tokens_per_second.prompt']
        self.assertEqual(flat['scope'], 'uncached_native_interval')
        self.assertEqual(flat['samples'], 1)

    # -- CLI registration --------------------------------------------------
    def test_cli_section_registered(self):
        from welp_next import __main__ as cli
        parser = cli.parser()
        args = parser.parse_args(['plan', '--section', 'runtime-performance',
                                  '--profile', 'x.json'])
        self.assertEqual(args.section, 'runtime-performance')


if __name__ == '__main__':
    unittest.main()
