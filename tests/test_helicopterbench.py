"""HelicopterBench section: submission semantics, sandboxed behavioral
verification, rubric, one-shot integrity, fault attribution, reconstruction.

All submissions are SOFTWARE_TEST artifacts (the reference-correct game and
known-defective variants) executed through the REAL section path and the
REAL isolated browser sandbox. No authentic model evaluation is claimed.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from welp_next import baseline, helicopterbench, policy, preflight, runner, store
from welp_next.scorers import helicopterbench as heli
import support

REFERENCE = Path(__file__).resolve().parent / 'artifacts' / 'helicopter-reference.html'


def payload(content, finish='stop'):
    return (200, support.canonical(support.envelope(content, finish)) + b'\n')


class Extraction(unittest.TestCase):
    def test_fenced_block_wins_and_is_verbatim(self):
        content = "Here is the game:\n```html\n<!DOCTYPE html><html><body></body></html>\n```\n"
        artifact, decision = heli.extract_artifact(content)
        self.assertEqual(decision['method'], 'fenced_html_block')
        self.assertTrue(artifact.startswith(b'<!DOCTYPE html>'))
        self.assertIn(b'</html>', artifact)

    def test_whole_reply_html_accepted(self):
        content = "<!DOCTYPE html>\n<html>\n<body><canvas></canvas></body>\n</html>"
        artifact, decision = heli.extract_artifact(content)
        self.assertEqual(decision['method'], 'whole_reply')

    def test_no_artifact_is_deficiency_not_crash(self):
        artifact, decision = heli.extract_artifact(
            "I could not finish the game, here is my plan instead.")
        self.assertIsNone(artifact)
        self.assertEqual(decision['method'], 'none')

    def test_extraction_is_deterministic(self):
        content = REFERENCE.read_text()
        first, _ = heli.extract_artifact(content)
        second, _ = heli.extract_artifact(content)
        self.assertEqual(first, second)


class SubmissionSemantics(unittest.TestCase):
    def setUp(self):
        self.task = helicopterbench.load_fixture()[1]['helicopterbench-01']

    def test_completed_artifact_is_valid_submission(self):
        content = "```html\n" + REFERENCE.read_text() + "\n```"
        result = baseline.score_response(self.task, support.envelope(content, 'stop'))
        self.assertEqual(result['outcome'], 'PASS')
        self.assertEqual(result['record']['extraction']['method'], 'fenced_html_block')

    def test_completed_without_artifact_is_valid_fail(self):
        result = baseline.score_response(
            self.task, support.envelope('Sorry, here is a design sketch instead.', 'stop'))
        self.assertEqual(result['outcome'], 'FAIL')
        self.assertEqual(result['record']['extraction']['method'], 'none')

    def test_budget_exhaustion_is_never_an_incorrect_game(self):
        result = baseline.score_response(self.task, support.envelope('', 'length'))
        self.assertEqual(result['reason'], 'BUDGET_LIMITED')

    def test_empty_completion_is_unscorable(self):
        result = baseline.score_response(self.task, support.envelope('', 'stop'))
        self.assertEqual(result['outcome'], 'NOT_EVALUABLE')


class MethodAcceptanceGate(unittest.TestCase):
    def setUp(self):
        # The seam under test is the recorded-acceptance gate; environment
        # preflight (campaign routing, endpoint admission) is out of scope.
        patcher = patch.object(preflight, 'offline', return_value={'ok': True})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.workdir = support.make_workdir('heli-gate')
        self.campaign = self.workdir / 'heli-campaign'
        self.campaign.mkdir()
        self.profile = support.build_profile(self.workdir, 'http://127.0.0.1:1/v1',
                                             self.campaign)
        self.profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                     'methodology': policy.METHODOLOGY_M2}
        self.profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())

    def test_real_model_requires_recorded_acceptance(self):
        profile = self.profile
        profile['evidence_kind'] = 'REAL_MODEL'
        with self.assertRaises(policy.CheckError) as ctx:
            helicopterbench.plan(profile)
        self.assertIn('acceptance', str(ctx.exception))
        profile['deployment'] = {'method_acceptance': {
            'operator': 'operator', 'date': 'pending', 'reference': 'SPEC 4.11'}}
        planned = helicopterbench.plan(profile)
        self.assertEqual(planned['unit_ids'], ['helicopterbench-01'])

    def test_software_test_is_exempt(self):
        planned = helicopterbench.plan(self.profile)
        self.assertIn('no capability-witness gate', planned['gate']['reason'])


class Rubric(unittest.TestCase):
    def test_reference_record_scores_full_mechanical(self):
        record_path = (Path(__file__).resolve().parents[1]
                       / 'tmp/helicopterbench-development-2026-11-07'
                       / 'reference-verification.json')
        if not record_path.exists():
            self.skipTest('reference verification record not yet produced')
        record = json.loads(record_path.read_text())
        rubric = heli.rubric_score(record)
        self.assertEqual(rubric['mechanical_points'], 90)
        self.assertEqual(rubric['final_score'], 100.0)
        self.assertEqual(rubric['class'], 'FUNCTIONAL_PLAYABLE')

    def test_environment_error_is_technical_never_model_fail(self):
        rubric = heli.rubric_score({'environment_error': 'browser missing'})
        self.assertEqual(rubric['class'], 'TECHNICAL_INVALID')
        self.assertIsNone(rubric['mechanical_points'])
        self.assertIsNone(rubric['final_score'])

    def test_partial_record_receives_partial_credit(self):
        record = {'checks': {'no_runtime_exceptions': True, 'canvas_present': True,
                             'animation_liveliness': True, 'score_accrues': True,
                             'input_causes_ascent': True, 'gravity_causes_descent': True,
                             'controls_state_numeric': True,
                             'collision_produces_game_over': True,
                             'restart_resets': False, 'obstacles_present': True,
                             'obstacles_advance': True, 'game_over_visible_text': False,
                             'difficulty_increases': False, 'speed_increases': False}}
        rubric = heli.rubric_score(record)
        self.assertEqual(rubric['class'], 'PARTIAL')
        # 20+20+19+7+0 = 67 mechanical; restart/game-over/difficulty subchecks fail
        self.assertEqual(rubric['mechanical_points'], 67)
        # Objective normalization from the exact mechanical total.
        self.assertEqual(rubric['final_score'], 74.4)

    def test_v2_objective_score_semantics(self):
        # Methodology helicopterbench/2: the same 14 mechanical subchecks and
        # 90-point weights; the 10-point review-only visual category is
        # retired; the single final score normalizes the exact mechanical
        # total (never per-category rounding); no manual review field exists.
        self.assertEqual(sum(c['points'] for c in heli.RUBRIC.values()), 90)
        self.assertEqual(sum(len(c['subchecks']) for c in heli.RUBRIC.values()), 14)
        self.assertNotIn('visual_quality_playability', heli.RUBRIC)
        self.assertEqual(heli.METHODOLOGY_VERSION, 'helicopterbench/2')
        self.assertEqual(heli.normalize_score(90), 100.0)
        self.assertEqual(heli.normalize_score(0), 0.0)
        self.assertEqual(heli.normalize_score(67), 74.4)
        self.assertEqual(heli.normalize_score(None), None)
        rubric = heli.rubric_score({'checks': {'no_runtime_exceptions': True}})
        for key in ('review_required', 'review_points_pending',
                    'review_categories', 'visual_quality_playability'):
            self.assertNotIn(key, rubric)
            self.assertNotIn(key, rubric['categories'])
        # Final score and mechanical points are always mutually consistent.
        self.assertEqual(rubric['final_score'],
                         heli.normalize_score(rubric['mechanical_points']))

    def test_v1_campaign_record_is_preserved_and_never_rescored(self):
        # The accepted 2026-11-07 authentic campaign (mechanical 34/90, visual
        # review PENDING) is immutable evidence: its verification record
        # reconstructs the same raw 34/PARTIAL under v2, and the normalized
        # 37.8 exists only as an illustrative conversion — never an official
        # retroactive v2 score (read-only use of frozen evidence).
        record_path = (preflight.WORKSPACE_ROOT / 'research/model-evaluations'
                       / 'qwen35-9b/campaign-groups'
                       / 'qwen35-9b-rtx5070-cuda-helicopterbench-2026-11-07'
                       / 'sections/helicopterbench/heli-verification.json')
        if not record_path.exists():
            self.skipTest('authentic campaign evidence not reachable')
        record = json.loads(record_path.read_text())
        rubric = heli.rubric_score(record)
        self.assertEqual(rubric['mechanical_points'], 34)
        self.assertEqual(rubric['final_score'], 37.8)  # illustrative only
        self.assertEqual(rubric['class'], 'PARTIAL')


class SectionEndToEnd(unittest.TestCase):
    def _run(self, content, finish='stop'):
        workdir = support.make_workdir('heli-exec')
        campaign = workdir / 'heli-campaign'
        campaign.mkdir()
        profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1', campaign)
        profile['framework'] = {'version': policy.FRAMEWORK_M2,
                                'methodology': policy.METHODOLOGY_M2}
        profile['sampling']['qualification_source'] = \
            str(Path(support.__file__).resolve())
        fixture, tasks = helicopterbench.load_fixture()
        server = support.SyntheticEndpoint(
            tasks_by_id=tasks, payloads={'helicopterbench-01': payload(content, finish)},
            echo_provider=lambda: {**support.identity_echo(profile),
                                   'sampling': policy.sampling_settings(profile)})
        server.start()
        try:
            profile['runtime']['serve']['endpoint'] = server.endpoint_url
            helicopterbench.run(profile)
        finally:
            server.stop()
        return campaign, tasks, profile

    def test_reference_game_passes_full_verification(self):
        content = "```html\n" + REFERENCE.read_text() + "\n```"
        campaign, tasks, profile = self._run(content)
        status = helicopterbench.status(campaign)
        self.assertEqual(status['state'], 'COMPLETED')
        self.assertEqual(status['units'][0]['outcome'], 'PASS')
        section = campaign / 'sections' / 'helicopterbench'
        report = helicopterbench.report_section(campaign)
        self.assertEqual(report['verification_class'], 'FUNCTIONAL_PLAYABLE')
        self.assertEqual(report['mechanical_points'], 90)
        # The v2 final score is the objective normalized 100-point result; a
        # complete valid score exists without any manual visual review.
        self.assertEqual(report['final_score'], 100.0)
        submission = (section / 'submission.html').read_bytes()
        self.assertIn(b'__HELICOPTER_STATE__', submission)
        score = store.read_json(section / 'heli-score.json')
        self.assertEqual(score['score'], 100.0)
        self.assertEqual(score['methodology'], 'helicopterbench/2')
        self.assertEqual(score['mechanical_points'], 90)
        for key in ('review_required', 'review_points_pending'):
            self.assertNotIn(key, score)
        report_text = (section / 'SECTION-REPORT.md').read_text()
        self.assertIn('Final score: 100.0/100', report_text)
        self.assertNotIn('review-only', report_text)
        support.verify_manifest_integrity(self, section)
        # One-shot integrity: exactly one resolved attempt.
        config, units = store.inventory(section)
        self.assertEqual(len(units['helicopterbench-01']), 1)
        # Idempotent finalization without new inference.
        before = (section / 'manifest.json').read_bytes()
        again = helicopterbench.report_section(campaign)
        self.assertTrue(again['already_finalized'])
        self.assertEqual((section / 'manifest.json').read_bytes(), before)
        # A standalone specialist must report without inventing a baseline,
        # and its singular frozen fixture must replay through the release CLI.
        from welp_next import reporting, release_validation
        from welp_next import __main__ as cli
        reporting.report_campaign(campaign)
        dispositions = store.read_json(campaign / 'summaries/section-dispositions.json')
        self.assertEqual(dispositions['baseline'], 'NOT_RUN')
        self.assertEqual(dispositions['sections'][0]['section'], 'helicopterbench')
        record = release_validation.validate_campaign(campaign)
        self.assertTrue(record['all_finalized_sections_verified'])
        self.assertEqual(record['sections'][0]['units_replayed'], 1)
        # Rehashing a forged derived score cannot hide a semantic mismatch.
        from contextlib import redirect_stdout
        import io
        score['final_score'] = score['score'] = 0.0
        (section / 'heli-score.json').write_text(json.dumps(score))
        manifest = store.read_json(section / 'manifest.json')
        manifest['files']['heli-score.json'] = policy.file_sha(section / 'heli-score.json')
        (section / 'manifest.json').write_text(json.dumps(manifest))
        with redirect_stdout(io.StringIO()) as output:
            code = cli.main(['validate', '--campaign', str(campaign), '--json'])
        self.assertEqual(code, 2)
        failure = json.loads(output.getvalue())['sections'][0]
        self.assertIn('objective score reconstruction mismatch',
                      failure['replay_failures'][0])

    def test_alternative_game_over_wording_earns_visible_indication(self):
        # Corrected v2 game-over check: the overlay says "SYSTEM FAILURE /
        # Collision Detected — click to reboot sequence" — outside the
        # retired v1 token set ("game over"/"crash") that mis-scored the
        # authentic 2026-11-07 campaign. The v2 check measures the NEW
        # rendered text appearing exactly with the demonstrated game-over
        # transition, so legitimate alternative wording earns the 4 points.
        campaign, _, _ = self._run(self._artifact('heli-alt-gameover-wording.html'))
        section = campaign / 'sections' / 'helicopterbench'
        report = helicopterbench.report_section(campaign)
        verification = store.read_json(section / 'heli-verification.json')
        checks = verification['checks']
        self.assertTrue(checks['game_over_visible_text'])
        new_lines = ' '.join(verification['evidence']['game_over_new_visible_text'])
        self.assertIn('system failure', new_lines)
        self.assertEqual(report['verification_class'], 'FUNCTIONAL_PLAYABLE')
        self.assertEqual(report['mechanical_points'], 90)
        self.assertEqual(report['final_score'], 100.0)

    def test_unrelated_hidden_and_telemetry_only_text_earn_no_credit(self):
        # Corrected v2 game-over check guards: a functional game-over STATE
        # with (1) an unrelated banner visible before AND after the crash,
        # (2) a hidden display:none "GAME OVER" div, and (3) accurate
        # gameOver telemetry but no rendered change — none of these may earn
        # the visible-indication check; exactly the 4 points are lost.
        campaign, _, _ = self._run(self._artifact('heli-unrelated-text.html'))
        section = campaign / 'sections' / 'helicopterbench'
        report = helicopterbench.report_section(campaign)
        verification = store.read_json(section / 'heli-verification.json')
        checks = verification['checks']
        self.assertTrue(checks['state_contract_present'])
        self.assertTrue(checks['collision_produces_game_over'])
        self.assertTrue(checks['restart_resets'])
        self.assertFalse(checks['game_over_visible_text'])
        self.assertEqual(verification['evidence']['game_over_new_visible_text'], [])
        score = store.read_json(section / 'heli-score.json')
        failed = [name for category in score['categories'].values()
                  for name, detail in category['subchecks'].items()
                  if detail['pass'] is False]
        self.assertEqual(failed, ['game_over_visible_text'])
        self.assertEqual(report['mechanical_points'], 86)
        self.assertEqual(report['final_score'], 95.6)

    def test_budget_limited_generation_never_reaches_verification(self):
        campaign, _, _ = self._run('<!DOCTYPE html>\n<html><body>partial ga', finish='length')
        section = campaign / 'sections' / 'helicopterbench'
        status = helicopterbench.status(campaign)
        # Accepted vocabulary: outcome NOT_EVALUABLE carrying reason
        # BUDGET_LIMITED (never a completed incorrect game).
        self.assertEqual(status['units'][0]['outcome'], 'NOT_EVALUABLE')
        self.assertEqual(status['units'][0]['reason'], 'BUDGET_LIMITED')
        report = helicopterbench.report_section(campaign)
        self.assertEqual(report['verification_class'], 'NONFUNCTIONAL')
        self.assertIsNone(report['mechanical_points'])
        self.assertIsNone(report['final_score'])
        score = store.read_json(section / 'heli-score.json')
        self.assertIsNone(score['score'])
        self.assertEqual(score['generation_outcome'], 'NOT_EVALUABLE')
        self.assertEqual(score['generation_reason'], 'BUDGET_LIMITED')

    def test_artifact_deficient_submission_fails_with_record(self):
        campaign, _, _ = self._run('No game here, sorry.')
        section = campaign / 'sections' / 'helicopterbench'
        status = helicopterbench.status(campaign)
        self.assertEqual(status['units'][0]['outcome'], 'FAIL')
        report = helicopterbench.report_section(campaign)
        self.assertEqual(report['verification_class'], 'NONFUNCTIONAL')
        self.assertIsNone(report['final_score'])
        extraction = store.read_json(section / 'extraction.json')
        self.assertEqual(extraction['decision']['method'], 'none')

    def _artifact(self, name):
        return '```html\n' + (Path(__file__).resolve().parent / 'artifacts' / name).read_text() + '\n```'

    def test_missing_instrumentation_keeps_demonstrated_launch_credit(self):
        # Admission check A.2: a visibly working game without the frozen
        # state contract. Contract-dependent mechanics must stay UNEVALUABLE
        # (never reported as broken); contract-independent launch/render
        # evidence is still credited, so the classification is PARTIAL.
        campaign, _, _ = self._run(self._artifact('heli-no-instrumentation.html'))
        section = campaign / 'sections' / 'helicopterbench'
        report = helicopterbench.report_section(campaign)
        verification = store.read_json(section / 'heli-verification.json')
        checks = verification['checks']
        self.assertFalse(checks['state_contract_present'])
        self.assertTrue(checks['canvas_present'])
        self.assertTrue(checks['no_runtime_exceptions'])
        self.assertTrue(checks['animation_liveliness'])
        for key in ('input_causes_ascent', 'gravity_causes_descent', 'score_accrues',
                    'obstacles_present', 'obstacles_advance', 'collision_produces_game_over',
                    'restart_resets', 'game_over_visible_text', 'difficulty_increases',
                    'speed_increases', 'controls_state_numeric'):
            self.assertNotIn(key, checks)
        self.assertEqual(report['verification_class'], 'PARTIAL')
        self.assertEqual(report['mechanical_points'], 20)
        # Missing instrumentation never fabricates gameplay failures: the
        # objective v2 score covers only demonstrated launch/render evidence.
        self.assertEqual(report['final_score'], 22.2)
        score = store.read_json(section / 'heli-score.json')
        self.assertNotIn('review_required', score)
        for category in ('controls_and_physics', 'obstacles_and_collision',
                         'score_failure_restart', 'course_and_difficulty'):
            for detail in score['categories'][category]['subchecks'].values():
                self.assertIsNone(detail['pass'])
                self.assertTrue(detail['unevaluable'])
        launch = score['categories']['launch_and_rendering']['subchecks']
        self.assertEqual({k: v['pass'] for k, v in launch.items()},
                         {'no_runtime_exceptions': True, 'canvas_present': True,
                          'animation_liveliness': True})

    def test_telemetry_without_rendering_never_counts_functional(self):
        # Admission check A.3: a game whose state contract advances while the
        # rendered surface is static. Telemetry-only progression must not
        # establish functioning gameplay: the rendering observation fails and
        # FUNCTIONAL_PLAYABLE is withheld, with the contradiction recorded.
        campaign, _, _ = self._run(self._artifact('heli-state-render-mismatch.html'))
        section = campaign / 'sections' / 'helicopterbench'
        report = helicopterbench.report_section(campaign)
        verification = store.read_json(section / 'heli-verification.json')
        checks = verification['checks']
        self.assertFalse(checks['animation_liveliness'])
        self.assertTrue(checks['obstacles_advance'])
        self.assertTrue(checks['score_accrues'])
        self.assertNotEqual(report['verification_class'], 'FUNCTIONAL_PLAYABLE')
        self.assertEqual(report['verification_class'], 'PARTIAL')
        self.assertLess(report['mechanical_points'], 90)
        # The objective v2 score stays mathematically consistent with the
        # earned mechanical points even for a partially functional artifact.
        self.assertEqual(report['final_score'],
                         heli.normalize_score(report['mechanical_points']))
        score = store.read_json(section / 'heli-score.json')
        self.assertFalse(
            score['categories']['launch_and_rendering']['subchecks']['animation_liveliness']['pass'])
        self.assertTrue(
            score['categories']['obstacles_and_collision']['subchecks']['obstacles_advance']['pass'])


if __name__ == '__main__':
    unittest.main()
