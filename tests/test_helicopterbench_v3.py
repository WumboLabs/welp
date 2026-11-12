"""HelicopterBench methodology /3: native 100-point rubric, version-specific
fixture/scorer selection, one-generation rule, and the independent human
playtesting channel (binding, unresolved/disputed states, reconciliation
gates, safe summary, manifests and offline reconstruction).

All submissions are SOFTWARE_TEST artifacts executed through the REAL section
path (and, where noted, the REAL isolated browser sandbox). No authentic
model evaluation is claimed and no human answers are invented: reviewer
files in these tests are synthetic attributed-test fixtures.
"""
import io
import json
import uuid
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from welp_next import helicopterbench, heli_review, policy, preflight, reporting, \
    release_validation, store
from welp_next import __main__ as cli
from welp_next.scorers import helicopterbench as heli
from welp_next.scorers import helicopterbench_v3 as heli_v3
import support

REFERENCE = Path(__file__).resolve().parent / 'artifacts' / 'helicopter-reference.html'


def payload(content, finish='stop'):
    return (200, support.canonical(support.envelope(content, finish)) + b'\n')


def _profile(workdir, campaign):
    profile = support.build_profile(workdir, 'http://127.0.0.1:1/v1', campaign)
    profile['framework'] = {'version': policy.FRAMEWORK_M2,
                            'methodology': policy.METHODOLOGY_M2}
    profile['sampling']['qualification_source'] = \
        str(Path(support.__file__).resolve())
    return profile


def run_v3(content=None, finish='stop', payloads=None):
    """One v3 SOFTWARE_TEST campaign through the REAL section path."""
    workdir = support.make_workdir('heli-v3')
    campaign = workdir / 'heli-campaign'
    campaign.mkdir()
    profile = _profile(workdir, campaign)
    _, tasks = helicopterbench.load_fixture('helicopterbench/3')
    if payloads is None:
        payloads = {'helicopterbench-01': payload(content or '', finish)}
    server = support.SyntheticEndpoint(
        tasks_by_id=tasks, payloads=payloads,
        echo_provider=lambda: {**support.identity_echo(profile),
                               'sampling': policy.sampling_settings(profile)})
    server.start()
    try:
        profile['runtime']['serve']['endpoint'] = server.endpoint_url
        helicopterbench.run(profile, {'methodology': 'helicopterbench/3'})
    finally:
        server.stop()
    return workdir, campaign, server


def section(campaign):
    return Path(campaign) / 'sections' / 'helicopterbench'


def reviewer_file(workdir, campaign, **overrides):
    """A synthetic attributed-HUMAN review fixture (never agent answers)."""
    review = {'schema': heli_review.REVIEW_SCHEMA,
              'methodology': heli_review.METHODOLOGY,
              'binding': heli_review.binding(campaign),
              'reviewer': {'id': 'operator-test', 'role': 'operator'},
              'played': True,
              'answers': {check: True for _, check, _ in heli_review.CHECK_ITEMS},
              'notes': {}, 'disputes': []}
    review.update(overrides)
    path = workdir / f'review-{uuid.uuid4().hex}.json'
    path.write_text(json.dumps(review, sort_keys=True), encoding='utf-8')
    return path


class RubricWeights(unittest.TestCase):
    def test_native_100_points_fourteen_checks(self):
        self.assertEqual(heli_v3.METHODOLOGY_VERSION, 'helicopterbench/3')
        self.assertEqual(heli_v3.MECHANICAL_MAX, 100)
        self.assertEqual(sum(c['points'] for c in heli_v3.RUBRIC.values()), 100)
        self.assertEqual(sum(len(c['subchecks']) for c in heli_v3.RUBRIC.values()), 14)
        for category, spec in heli_v3.RUBRIC.items():
            self.assertEqual(spec['points'], 20, category)
            self.assertEqual(sum(spec['subchecks'].values()), 20, category)
        # The owner-approved ordered weights, verbatim per category.
        self.assertEqual([list(c['subchecks'].values()) for c in heli_v3.RUBRIC.values()],
                         [[8, 6, 6], [7, 7, 6], [7, 6, 7], [10, 5, 5], [10, 10]])

    def test_no_normalization_identity_final_score(self):
        self.assertEqual(heli_v3.normalize_score(0), 0.0)
        self.assertEqual(heli_v3.normalize_score(86), 86.0)
        self.assertEqual(heli_v3.normalize_score(100), 100.0)
        self.assertIsNone(heli_v3.normalize_score(None))

    def test_full_partial_and_environment_records(self):
        full = heli_v3.rubric_score({'checks': {
            key: True for category in heli_v3.RUBRIC.values()
            for key in category['subchecks']}})
        self.assertEqual(full['mechanical_points'], 100)
        self.assertEqual(full['final_score'], 100.0)
        self.assertEqual(full['class'], 'FUNCTIONAL_PLAYABLE')
        partial_record = {'checks': {
            key: True for category in heli_v3.RUBRIC.values()
            for key in category['subchecks']}}
        partial_record['checks']['score_accrues'] = False
        partial_record['checks']['speed_increases'] = False
        partial_record['checks']['restart_resets'] = False
        partial = heli_v3.rubric_score(partial_record)
        self.assertEqual(partial['mechanical_points'], 75)
        self.assertEqual(partial['final_score'], 75.0)
        self.assertEqual(partial['class'], 'PARTIAL')
        technical = heli_v3.rubric_score({'environment_error': 'browser missing'})
        self.assertEqual(technical['class'], 'TECHNICAL_INVALID')
        self.assertIsNone(technical['final_score'])
        self.assertIsNone(technical['mechanical_points'])

    def test_each_check_awards_exact_literal_weight(self):
        # Independent literal expected weights (owner-approved ordered list),
        # verified through the ACTUAL rubric_score with one-Yes records —
        # never derived from the scorer's own metadata.
        LITERAL = {
            'no_runtime_exceptions': 8, 'canvas_present': 6,
            'animation_liveliness': 6, 'input_causes_ascent': 7,
            'gravity_causes_descent': 7, 'controls_state_numeric': 6,
            'obstacles_present': 7, 'obstacles_advance': 6,
            'collision_produces_game_over': 7, 'score_accrues': 10,
            'game_over_visible_text': 5, 'restart_resets': 5,
            'difficulty_increases': 10, 'speed_increases': 10}
        self.assertEqual(len(LITERAL), 14)
        self.assertEqual(sum(LITERAL.values()), 100)
        for check, weight in LITERAL.items():
            scored = heli_v3.rubric_score({'checks': {check: True}})
            self.assertEqual(scored['mechanical_points'], weight, check)
            self.assertEqual(scored['final_score'], float(weight), check)
        # Every category reaches exactly 20 with its full set of Yes.
        categories = {}
        for category, spec in heli_v3.RUBRIC.items():
            scored = heli_v3.rubric_score(
                {'checks': {check: True for check in spec['subchecks']}})
            awarded = sum(detail['points'] for detail
                          in scored['categories'][category]['subchecks'].values())
            categories[category] = awarded
            self.assertEqual(awarded, 20, category)
            self.assertEqual(scored['categories'][category]['max'], 20, category)
        self.assertEqual(sum(categories.values()), 100)

    def test_frozen_v2_scorer_behavior_intact(self):
        self.assertEqual(heli.METHODOLOGY_VERSION, 'helicopterbench/2')
        self.assertEqual(heli.MECHANICAL_MAX, 90)
        self.assertEqual(sum(c['points'] for c in heli.RUBRIC.values()), 90)
        self.assertEqual(heli.normalize_score(67), 74.4)
        # The /2 check ORDER is preserved inside every /3 category; only the
        # weights of the last two categories changed.
        for category in heli.RUBRIC:
            self.assertEqual(list(heli.RUBRIC[category]['subchecks']),
                             list(heli_v3.RUBRIC[category]['subchecks']))


class VersionSelection(unittest.TestCase):
    def test_default_fixture_is_frozen_v1_for_accepted_methodology(self):
        fixture, tasks = helicopterbench.load_fixture()
        self.assertEqual(fixture['fixture_id'], 'welp-helicopterbench-1')
        self.assertEqual(fixture['version'], '1.0.0')
        self.assertEqual(list(tasks), ['helicopterbench-01'])

    def test_v3_fixture_selection(self):
        fixture, tasks = helicopterbench.load_fixture('helicopterbench/3')
        self.assertEqual(fixture['fixture_id'], 'welp-helicopterbench-3')
        self.assertEqual(fixture['version'], '3.0.0')
        self.assertEqual(fixture['methodology'], 'helicopterbench/3')
        self.assertEqual(list(tasks), ['helicopterbench-01'])
        frozen, _ = helicopterbench.load_fixture()
        # Same verbatim frozen prompt, scorer and one-shot rules.
        self.assertEqual(fixture['task']['user_task'], frozen['task']['user_task'])
        self.assertEqual(fixture['task']['scorer'], frozen['task']['scorer'])

    def test_config_selection_and_rejection(self):
        self.assertEqual(helicopterbench._config(None)['methodology'],
                         'helicopterbench/2')
        self.assertEqual(
            helicopterbench._config({'methodology': 'helicopterbench/3'})['methodology'],
            'helicopterbench/3')
        with self.assertRaises(policy.CheckError):
            helicopterbench._config({'tasks': []})
        with self.assertRaises(policy.CheckError):
            helicopterbench.load_fixture('helicopterbench/9')

    def test_preserved_v1_maps_to_unchanged_historic_fixture_only(self):
        # Preserved /1 campaigns reconstruct offline against the UNCHANGED
        # historic fixture; /1 dispatch/rescore is never enabled.
        historic, tasks_default = helicopterbench.load_fixture()
        mapped, tasks = helicopterbench.load_fixture('helicopterbench/1')
        self.assertEqual(mapped, historic)
        self.assertEqual(tasks, tasks_default)
        with self.assertRaises(policy.CheckError):
            helicopterbench._scorer('helicopterbench/1')
        workdir = support.make_workdir('heli-v3-one')
        campaign = workdir / 'heli-campaign'
        campaign.mkdir()
        with self.assertRaises(policy.CheckError):
            helicopterbench.plan(_profile(workdir, campaign),
                                 {'methodology': 'helicopterbench/1'})

    def test_plan_reports_selected_methodology(self):
        workdir = support.make_workdir('heli-v3-plan')
        campaign = workdir / 'heli-campaign'
        campaign.mkdir()
        profile = _profile(workdir, campaign)
        planned = helicopterbench.plan(profile)
        self.assertEqual(planned['methodology'], 'helicopterbench/2')
        planned_v3 = helicopterbench.plan(
            profile, {'methodology': 'helicopterbench/3'})
        self.assertEqual(planned_v3['methodology'], 'helicopterbench/3')
        fixture, _ = helicopterbench.load_fixture('helicopterbench/3')
        self.assertEqual(planned_v3['fixture_sha256'], policy.digest(fixture))

    def test_real_model_acceptance_message_names_methodology(self):
        workdir = support.make_workdir('heli-v3-gate')
        campaign = workdir / 'heli-campaign'
        campaign.mkdir()
        profile = _profile(workdir, campaign)
        profile['evidence_kind'] = 'REAL_MODEL'
        with self.assertRaises(policy.CheckError) as ctx:
            helicopterbench.plan(profile, {'methodology': 'helicopterbench/3'})
        self.assertIn('acceptance', str(ctx.exception))
        self.assertIn('helicopterbench/3', str(ctx.exception))


class OneGenerationRule(unittest.TestCase):
    def test_invalid_transport_after_intent_never_retries(self):
        # The durable generation intent is written before dispatch; a failed
        # transport exchange after it must never be issued a second time
        # (methodology /3 one-generation opportunity).
        payloads = {'helicopterbench-01': (
            500, support.canonical({'error': {'message': 'upstream exploded',
                                              'type': 'server_error'}}) + b'\n')}
        workdir, campaign, server = run_v3(payloads=payloads)
        self.assertEqual(server.post_count('helicopterbench-01'), 1)
        target = section(campaign)
        self.assertEqual(
            len(store.attempts(target, 'helicopterbench-01')), 1)
        events = [json.loads(line)['event']
                  for line in (target / 'units.jsonl').read_bytes().splitlines()]
        self.assertIn('GENERATION_CONSUMED', events)
        status = helicopterbench.status(campaign)
        self.assertEqual(status['state'], 'INTERRUPTED')
        self.assertEqual(status['remaining_units'], ['helicopterbench-01'])
        # A resumed run must not issue the consumed second generation: no
        # new attempt is created even though the unit still counts as
        # pending under the generic invalid-retry bound.
        before = len(store.attempts(target, 'helicopterbench-01'))
        with self.assertRaises(policy.CheckError):
            helicopterbench.resume(campaign)  # reuses the frozen /3 method
        self.assertEqual(
            len(store.attempts(target, 'helicopterbench-01')), before)

    def test_truncated_reply_never_gameplay_scored(self):
        # finish=length is never a completed submission even when the reply
        # contains an extractable fenced block: evidence only, no
        # submission.html, no verification, no score, no human review gate.
        content = ("```html\n<!DOCTYPE html>\n<html><body>partial game "
                   "</body></html>\n```\nand further explanatory text that "
                   "got cut off mid-sent")
        workdir, campaign, _server = run_v3(content, finish='length')
        target = section(campaign)
        status = helicopterbench.status(campaign)
        self.assertEqual(status['units'][0]['outcome'], 'NOT_EVALUABLE')
        report = helicopterbench.report_section(campaign)
        extraction = store.read_json(target / 'extraction.json')
        self.assertIsNotNone(extraction['decision'])
        self.assertFalse(extraction['gameplay_scored'])
        self.assertEqual(extraction['generation_outcome'], 'NOT_EVALUABLE')
        self.assertFalse((target / 'submission.html').exists())
        verification = store.read_json(target / 'heli-verification.json')
        self.assertEqual(verification['verdict'], 'NOT_A_COMPLETED_SUBMISSION')
        score = store.read_json(target / 'heli-score.json')
        self.assertIsNone(score['score'])
        self.assertEqual(score['generation_outcome'], 'NOT_EVALUABLE')
        review = status['human_review']
        self.assertEqual(review['state'], 'NOT_APPLICABLE_NO_SUBMISSION')
        with self.assertRaises(policy.CheckError) as ctx:
            heli_review.prepare(campaign)
        self.assertIn('NOT_APPLICABLE_NO_SUBMISSION', str(ctx.exception))
        safe = heli_review.safe_summary(campaign)
        self.assertEqual(safe['state'], 'NOT_APPLICABLE_NO_SUBMISSION')
        self.assertTrue(safe['acceptance_gate']['pass'])
        self.assertFalse(safe['acceptance_gate']['required_for_official'])
        # Release validation and the export projection stay green: an
        # extractable artifact SHA inside a non-completed reply is never a
        # reconstruction target (no false score mismatch).
        record = release_validation.validate_campaign(campaign)
        self.assertTrue(record['all_finalized_sections_verified'])
        review_block = record['sections'][0]['human_review']
        self.assertEqual(review_block['state'], 'NOT_APPLICABLE_NO_SUBMISSION')
        self.assertIsNone(review_block['human_review_sha256'])
        self.assertIsNone(safe['human_review_sha256'])
        reporting.report_campaign(campaign)


class ReferenceEndToEnd(unittest.TestCase):
    def _finalize(self):
        content = "```html\n" + REFERENCE.read_text() + "\n```"
        workdir, campaign, _server = run_v3(content)
        report = helicopterbench.report_section(campaign)
        return workdir, campaign, report

    def test_reference_game_scores_native_100(self):
        workdir, campaign, report = self._finalize()
        target = section(campaign)
        self.assertEqual(report['verification_class'], 'FUNCTIONAL_PLAYABLE')
        self.assertEqual(report['mechanical_points'], 100)
        self.assertEqual(report['final_score'], 100.0)
        score = store.read_json(target / 'heli-score.json')
        self.assertEqual(score['methodology'], 'helicopterbench/3')
        self.assertEqual(score['mechanical_max'], 100)
        self.assertEqual(score['score'], 100.0)
        self.assertTrue(score['human_review_required'])
        extraction = store.read_json(target / 'extraction.json')
        self.assertTrue(extraction['gameplay_scored'])
        # The exact v3 human-review gate is exposed on section status.
        status = helicopterbench.status(campaign)
        self.assertEqual(status['human_review']['state'], 'NOT_IMPORTED')
        self.assertFalse(status['human_review']['reconciled'])
        # Offline reconstruction and campaign reporting stay green.
        support.verify_manifest_integrity(self, target)
        record = release_validation.validate_campaign(campaign)
        self.assertTrue(record['all_finalized_sections_verified'])
        self.assertEqual(record['sections'][0]['human_review']['state'],
                         'NOT_IMPORTED')
        # Idempotent finalization.
        again = helicopterbench.report_section(campaign)
        self.assertTrue(again['already_finalized'])

    def test_forged_v3_score_fails_release_reconstruction(self):
        workdir, campaign, _report = self._finalize()
        target = section(campaign)
        score = store.read_json(target / 'heli-score.json')
        score['final_score'] = score['score'] = 0.0
        (target / 'heli-score.json').write_text(json.dumps(score))
        manifest = store.read_json(target / 'manifest.json')
        manifest['files']['heli-score.json'] = policy.file_sha(target / 'heli-score.json')
        (target / 'manifest.json').write_text(json.dumps(manifest))
        record = release_validation.validate_campaign(campaign)
        self.assertFalse(record['all_finalized_sections_verified'])
        self.assertIn('objective score reconstruction mismatch',
                      record['sections'][0]['replay_failures'][0])


def _surface_context(prepared):
    """Parse the review context the prepared surface ACTUALLY embeds (not
    its source wording)."""
    html = Path(prepared['checklist']).read_text(encoding='utf-8')
    marker = '<script type="application/json" id="welp-review-context">'
    blob = html.split(marker, 1)[1].split('</script>', 1)[0]
    return json.loads(blob)


class HumanReviewChannel(unittest.TestCase):
    def setUp(self):
        content = "```html\n" + REFERENCE.read_text() + "\n```"
        self.workdir, self.campaign, _server = run_v3(content)
        self.target = section(self.campaign)
        self.report = helicopterbench.report_section(self.campaign)
        self._evidence_before = {
            str(p.relative_to(self.target)): policy.file_sha(p)
            for p in self.target.rglob('*') if p.is_file()}

    def _assert_automation_untouched(self):
        after = {str(p.relative_to(self.target)): policy.file_sha(p)
                 for p in self.target.rglob('*') if p.is_file()}
        self.assertEqual(after, self._evidence_before)

    def test_checklist_surface_binds_exact_bytes(self):
        prepared = heli_review.prepare(self.campaign)
        html = Path(prepared['checklist']).read_text(encoding='utf-8')
        # Safe boundary, enforced policy, hash refusal, running display.
        self.assertIn('sandbox="allow-scripts"', html)
        self.assertNotIn('allow-same-origin', html)
        self.assertNotIn('allow-top-navigation', html)
        self.assertIn("default-src 'none'", html)
        self.assertIn("http-equiv=\"Content-Security-Policy\"", html)
        self.assertIn('crypto.subtle.digest', html)
        self.assertIn('digestHex !== binding.artifact_sha256', html)
        self.assertIn('NOT mounted', html)
        self.assertIn('RUNNING earned points', html)
        self.assertIn('RUNNING TOTAL, NOT A FINAL SCORE', html)
        self.assertIn('Automated verification (separate official channel', html)
        self.assertIn('MATERIAL DISAGREEMENT', html)
        # The embedded game bytes round-trip EXACTLY to the bound digest
        # (CRLF-safe: bytes are embedded, not newline-normalized text).
        marker = '<script type="application/json" id="welp-game-bytes">'
        blob = html.split(marker, 1)[1].split('</script>', 1)[0]
        game_text = json.loads(blob)
        import hashlib
        digest = hashlib.sha256(game_text.encode('utf-8')).hexdigest()
        self.assertEqual(digest,
                         store.read_json(self.target / 'extraction.json')['artifact_sha256'])
        self.assertEqual(game_text.encode('utf-8'),
                         (self.target / 'submission.html').read_bytes())

    def test_draft_round_trip_restores_human_input(self):
        # Initial surface: unanswered (no draft state embedded, never
        # default No).
        fresh = heli_review.prepare(self.campaign)
        self.assertFalse(fresh['draft_loaded'])
        self.assertIsNone(_surface_context(fresh)['draft'])
        # An imported NOT-finalized review is embedded verbatim into a
        # fresh surface: the reviewer's OWN answers/notes/attribution plus
        # the exact supersedes digest — finishable in the UI without
        # hand-editing JSON.
        partial = {check: True for _, check, _ in heli_review.CHECK_ITEMS}
        del partial['speed_increases']
        first = heli_review.import_review(
            self.campaign, reviewer_file(
                self.workdir, self.campaign, answers=partial,
                notes={'score_accrues': 'score rose steadily'},
                reviewer={'id': 'operator-test', 'role': 'operator'}))
        self.assertEqual(first['state'], 'UNRESOLVED')
        digests = heli_review.review_digest(self.campaign)
        prepared = heli_review.prepare(self.campaign)
        self.assertTrue(prepared['draft_loaded'])
        context = _surface_context(prepared)
        self.assertEqual(context['draft']['supersedes'],
                         digests['review_sha256'])
        self.assertEqual(context['draft']['answers'], partial)
        self.assertEqual(context['draft']['notes'],
                         {'score_accrues': 'score rose steadily'})
        self.assertEqual(context['draft']['reviewer'],
                         {'id': 'operator-test', 'role': 'operator'})
        self.assertEqual(context['draft']['disputes'], [])
        # A FINALIZED review is immutable: no new surface at all.
        heli_review.import_review(
            self.campaign,
            reviewer_file(self.workdir, self.campaign,
                          supersedes=digests['review_sha256'],
                          answers={check: True for _, check, _
                                   in heli_review.CHECK_ITEMS}))
        self.assertEqual(
            helicopterbench.status(self.campaign)['human_review']['state'],
            'FINALIZED')
        with self.assertRaises(policy.CheckError) as ctx:
            heli_review.prepare(self.campaign)
        self.assertIn('FINALIZED and immutable', str(ctx.exception))

    def test_play_route_named_refusals(self):
        # Observable fail-closed behavior of the play route.
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ('WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR')}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(policy.CheckError) as ctx:
                heli_review.play(self.campaign)
        self.assertIn('Wayland', str(ctx.exception))
        self.assertIn('X11', str(ctx.exception))
        with patch.object(heli_review.shutil, 'which', return_value=None):
            with self.assertRaises(policy.CheckError) as ctx:
                heli_review.play(self.campaign, headless=True)
        self.assertIn('bwrap', str(ctx.exception))

    def test_dispute_survives_reprepare_and_reimport(self):
        # A reviewer-declared dispute is explicit human input: the draft
        # round trip must preserve it across reprepare and supersession.
        dispute = {'check': 'restart_resets',
                   'claim': 'first click after game over did nothing',
                   'evidence': 'reproduced twice with visible dead state'}
        heli_review.import_review(
            self.campaign,
            reviewer_file(self.workdir, self.campaign, disputes=[dispute]))
        state = helicopterbench.status(self.campaign)['human_review']
        self.assertEqual(state['state'], 'DISPUTED')
        self.assertEqual(state['open_disputes'], ['restart_resets'])
        digests = heli_review.review_digest(self.campaign)
        prepared = heli_review.prepare(self.campaign)
        context = _surface_context(prepared)
        self.assertEqual(context['draft']['disputes'], [dispute])
        self.assertEqual(context['draft']['supersedes'],
                         digests['review_sha256'])
        # The superseding review carries the same dispute; it stays open.
        supersedes = reviewer_file(
            self.workdir, self.campaign,
            supersedes=digests['review_sha256'], disputes=[dispute])
        heli_review.import_review(self.campaign, supersedes)
        state = helicopterbench.status(self.campaign)['human_review']
        self.assertEqual(state['state'], 'DISPUTED')
        self.assertEqual(state['open_disputes'], ['restart_resets'])
        entry = {'schema': heli_review.RECONCILIATION_SCHEMA,
                 'check': 'restart_resets', 'resolution': 'reviewer_stands',
                 'evidence': 'two reproduced dead clicks',
                 'rationale': 'recorded observation stands over the '
                              'automated pass',
                 'reviewer': {'id': 'operator-test'},
                 'at': '2026-11-11T00:00:00Z'}
        path = self.workdir / 'reconcile-dispute.json'
        path.write_text(json.dumps(entry))
        result = heli_review.reconcile(self.campaign, path)
        self.assertEqual(result['state'], 'FINALIZED')

    def test_full_yes_review_finalizes_with_earned_100(self):
        path = reviewer_file(self.workdir, self.campaign)
        result = heli_review.import_review(self.campaign, path)
        self.assertEqual(result['state'], 'FINALIZED')
        review = helicopterbench.status(self.campaign)['human_review']
        self.assertTrue(review['reconciled'])
        self.assertEqual(review['earned_points'], 100)
        self.assertEqual(review['final_points'], 100)
        self.assertEqual(review['reviewer'], 'operator-test')
        self._assert_automation_untouched()
        # Public-safe projection: no identity, no notes, no paths, exact
        # digests; parent consumes it directly.
        safe = heli_review.safe_summary(self.campaign)
        self.assertEqual(safe['state'], 'FINALIZED')
        self.assertEqual(safe['final_points'], 100)
        self.assertEqual(safe['unresolved_items'], [])
        self.assertEqual(safe['open_disputes'], [])
        self.assertIsNone(safe.get('reviewer'))
        self.assertNotIn('operator-test', json.dumps(safe))
        digests = heli_review.review_digest(self.campaign)
        self.assertEqual(safe['human_review_sha256'],
                         digests['human_review_sha256'])
        self.assertEqual(
            safe['human_review_sha256'],
            policy.digest({'review': digests['review_sha256'],
                           'reconciliation': digests['reconciliation_sha256']}))
        self.assertEqual(safe['artifact_sha256'],
                         store.read_json(self.target / 'extraction.json')['artifact_sha256'])
        self.assertTrue(safe['acceptance_gate']['pass'])

    def test_unanswered_review_stays_unresolved_then_supersedes(self):
        partial = {check: True for _, check, _ in heli_review.CHECK_ITEMS}
        del partial['canvas_present']      # 6 points
        del partial['no_runtime_exceptions']  # 8 points
        first = heli_review.import_review(
            self.campaign, reviewer_file(self.workdir, self.campaign,
                                         answers=partial))
        self.assertEqual(first['state'], 'UNRESOLVED')
        review = helicopterbench.status(self.campaign)['human_review']
        self.assertEqual(review['earned_points'], 86)   # running only
        self.assertIsNone(review['final_points'])
        self.assertEqual(sorted(review['unresolved_items']),
                         ['canvas_present', 'no_runtime_exceptions'])
        digests = heli_review.review_digest(self.campaign)
        # A second import must be an EXPLICIT same-reviewer supersession.
        with self.assertRaises(policy.CheckError):
            heli_review.import_review(
                self.campaign,
                reviewer_file(self.workdir, self.campaign,
                              answers={check: True for _, check, _
                                       in heli_review.CHECK_ITEMS}))
        with self.assertRaises(policy.CheckError):
            heli_review.import_review(
                self.campaign,
                reviewer_file(self.workdir, self.campaign,
                              supersedes=digests['review_sha256'],
                              reviewer={'id': 'someone-else'},
                              answers={check: True for _, check, _
                                       in heli_review.CHECK_ITEMS}))
        second = heli_review.import_review(
            self.campaign,
            reviewer_file(self.workdir, self.campaign,
                          supersedes=digests['review_sha256'],
                          answers={check: True for _, check, _
                                   in heli_review.CHECK_ITEMS}))
        self.assertEqual(second['state'], 'FINALIZED')
        superseded_dir = heli_review.store_base(self.campaign) / 'superseded'
        self.assertTrue(any(superseded_dir.iterdir()))
        self._assert_automation_untouched()

    def test_dispute_requires_explicit_reconciliation(self):
        answers = {check: True for _, check, _ in heli_review.CHECK_ITEMS}
        answers['score_accrues'] = False  # contradicts the automated True
        heli_review.import_review(
            self.campaign, reviewer_file(self.workdir, self.campaign,
                                         answers=answers))
        review = helicopterbench.status(self.campaign)['human_review']
        self.assertEqual(review['state'], 'DISPUTED')
        self.assertEqual(review['open_disputes'], ['score_accrues'])
        self.assertIsNone(review['final_points'])
        score_sha_before = policy.file_sha(self.target / 'heli-score.json')
        # Reconciliation is explicit and complete: evidence, rationale and
        # the attributed reviewer; model roles are refused.
        for bad in ({'evidence': 'seen', 'rationale': ''},
                    {'evidence': '', 'rationale': 'because'},
                    {'reviewer': {'id': 'operator-test', 'role': 'model'}}):
            entry = {'schema': heli_review.RECONCILIATION_SCHEMA,
                     'check': 'score_accrues',
                     'resolution': 'reviewer_stands',
                     'evidence': bad.get('evidence', 'played five runs'),
                     'rationale': bad.get('rationale', 'score visibly rose'),
                     'reviewer': bad.get('reviewer',
                                         {'id': 'operator-test'}),
                     'at': '2026-11-11T00:00:00Z'}
            for key, value in bad.items():
                entry[key] = value
            path = self.workdir / f'reconcile-bad-{uuid.uuid4().hex}.json'
            path.write_text(json.dumps(entry))
            with self.assertRaises(policy.CheckError):
                heli_review.reconcile(self.campaign, path)
        good = {'schema': heli_review.RECONCILIATION_SCHEMA,
                'check': 'score_accrues', 'resolution': 'reviewer_stands',
                'evidence': 'played five full runs; the numeric score readout '
                            'increased continuously while flying',
                'rationale': 'the automated miss contradicts directly '
                             'observed behavior; the reviewer observation '
                             'stands and is recorded explicitly',
                'reviewer': {'id': 'operator-test'},
                'at': '2026-11-11T00:00:00Z'}
        path = self.workdir / 'reconcile-good.json'
        path.write_text(json.dumps(good))
        result = heli_review.reconcile(self.campaign, path)
        self.assertEqual(result['state'], 'FINALIZED')
        # Automated evidence byte-identical: reconciliation never overwrites.
        self.assertEqual(policy.file_sha(self.target / 'heli-score.json'),
                         score_sha_before)
        safe = heli_review.safe_summary(self.campaign)
        self.assertEqual(safe['reconciliations'],
                         {'score_accrues': 'reviewer_stands'})
        self.assertTrue(safe['acceptance_gate']['pass'])
        self._assert_automation_untouched()

    def test_tampered_or_foreign_sidecars_fail_closed(self):
        # Import refuses any binding that is not the exact finalized one.
        binding = heli_review.binding(self.campaign)
        broken = dict(binding)
        broken['artifact_sha256'] = '0' * 64
        with self.assertRaises(policy.CheckError) as ctx:
            heli_review.import_review(
                self.campaign,
                reviewer_file(self.workdir, self.campaign, binding=broken))
        self.assertIn('binding', str(ctx.exception))
        # v2 sections have no human-review channel at all.
        heli_review.import_review(
            self.campaign, reviewer_file(self.workdir, self.campaign))
        operative = heli_review.operative_review_path(self.campaign)
        review = json.loads(operative.read_text())
        review['binding']['artifact_sha256'] = '1' * 64
        operative.write_text(json.dumps(review, sort_keys=True))
        with self.assertRaises(policy.CheckError):
            helicopterbench.status(self.campaign)
        # A malformed/unattributed reconciliation row can never become a
        # resolved dispute: read-time revalidation fails closed.
        row = {'schema': heli_review.RECONCILIATION_SCHEMA,
               'check': 'restart_resets', 'resolution': 'reviewer_stands',
               'evidence': '', 'rationale': '', 'reviewer': {},
               'review_sha256': '0' * 64}
        with open(heli_review.store_base(self.campaign)
                  / 'reconciliation.jsonl', 'ab') as stream:
            stream.write(json.dumps(row).encode() + b'\n')
        with self.assertRaises(policy.CheckError):
            helicopterbench.status(self.campaign)


class CliSurface(unittest.TestCase):
    def test_resume_of_finalized_v3_section_reuses_frozen_method(self):
        # A finalized SOFTWARE_TEST v3 section resumes without reselecting
        # the methodology; no new attempt is created after finalization.
        content = "```html\n" + REFERENCE.read_text() + "\n```"
        workdir, campaign, _server = run_v3(content)
        helicopterbench.report_section(campaign)
        target = section(campaign)
        before = len(store.attempts(target, 'helicopterbench-01'))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(['resume', '--section', 'helicopterbench',
                             '--campaign', str(campaign), '--json'])
        self.assertEqual(code, 0)
        value = json.loads(buffer.getvalue())
        self.assertEqual(value['methodology'], 'helicopterbench/3')
        self.assertEqual(value['finalized'], True)
        self.assertEqual(len(store.attempts(target, 'helicopterbench-01')),
                         before)
        # An explicit conflicting methodology on resume must fail closed.
        with self.assertRaises(policy.CheckError) as conflict:
            helicopterbench.resume(
                campaign, None, {'methodology': 'helicopterbench/2'})
        self.assertIn('methodology mismatch', str(conflict.exception))

    def test_methodology_flag_scope_guard(self):
        with redirect_stdout(io.StringIO()) as output:
            code = cli.main(['plan', '--section', 'baseline',
                             '--profile', 'unused.json',
                             '--methodology', 'helicopterbench/3', '--json'])
        self.assertEqual(code, 2)
        self.assertIn('methodology.scope', output.getvalue())

    def test_heli_review_cli_flow(self):
        content = "```html\n" + REFERENCE.read_text() + "\n```"
        workdir, campaign, _server = run_v3(content)
        helicopterbench.report_section(campaign)
        def call(args):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main(args)
            return code, json.loads(buffer.getvalue())
        code, value = call(['heli-review', '--campaign', str(campaign),
                            'status', '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(value['state'], 'NOT_IMPORTED')
        code, prepared = call(['heli-review', '--campaign', str(campaign),
                               'prepare', '--json'])
        self.assertEqual(code, 0)
        self.assertTrue(Path(prepared['checklist']).exists())
        path = reviewer_file(workdir, campaign)
        code, imported = call(['heli-review', '--campaign', str(campaign),
                               'import', '--review', str(path), '--json'])
        self.assertEqual(code, 0)
        self.assertEqual(imported['state'], 'FINALIZED')
        code, value = call(['heli-review', '--campaign', str(campaign),
                            'status'])
        self.assertEqual(value['state'], 'FINALIZED')
        self.assertTrue(value['reconciled'])

    def test_plan_cli_selects_v3_methodology(self):
        workdir = support.make_workdir('heli-v3-cli-plan')
        campaign = workdir / 'heli-campaign'
        campaign.mkdir()
        profile_path = support.write_profile(workdir, _profile(workdir, campaign))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(['plan', '--section', 'helicopterbench',
                             '--profile', str(profile_path),
                             '--methodology', 'helicopterbench/3', '--json'])
        self.assertEqual(code, 0)
        planned = json.loads(buffer.getvalue())
        self.assertEqual(planned['methodology'], 'helicopterbench/3')
        fixture, _ = helicopterbench.load_fixture('helicopterbench/3')
        self.assertEqual(planned['fixture_sha256'], policy.digest(fixture))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli.main(['plan', '--section', 'helicopterbench',
                      '--profile', str(profile_path), '--json'])
        self.assertEqual(json.loads(buffer.getvalue())['methodology'],
                         'helicopterbench/2')


class HistoricalCompatibility(unittest.TestCase):
    def test_v1_v2_artifacts_and_reconstruction_unchanged(self):
        # The frozen /1 /2 fixture file is untouched and stays the DEFAULT
        # for accepted campaigns (no rescoring of /1 /2 evidence).
        frozen, _ = helicopterbench.load_fixture()
        self.assertEqual(frozen['fixture_id'], 'welp-helicopterbench-1')
        self.assertEqual(frozen['version'], '1.0.0')
        # A /2 verification record reconstructs identically through the
        # frozen scorer (the /3 module never rewrites /2 evidence).
        record = {'checks': {'no_runtime_exceptions': True, 'canvas_present': True,
                             'animation_liveliness': True, 'score_accrues': True,
                             'input_causes_ascent': True, 'gravity_causes_descent': True,
                             'controls_state_numeric': True,
                             'collision_produces_game_over': True,
                             'restart_resets': False, 'obstacles_present': True,
                             'obstacles_advance': True, 'game_over_visible_text': False,
                             'difficulty_increases': False, 'speed_increases': False}}
        self.assertEqual(heli.rubric_score(record)['mechanical_points'], 67)
        self.assertEqual(heli.rubric_score(record)['final_score'], 74.4)
        # The same record under /3: 20+20+20 launch/controls/obstacles plus
        # score_accrues 10; restart/game-over-text/difficulty/speed all
        # failed — exactly 70, identity-normalized.
        self.assertEqual(heli_v3.rubric_score(record)['mechanical_points'], 70)
        self.assertEqual(heli_v3.rubric_score(record)['final_score'], 70.0)

    def test_preserved_v1_campaign_validates_under_offline_mapping(self):
        # When the accepted /1 campaign evidence is reachable, release
        # validation must still pass with the recorded helicopterbench/1
        # methodology mapped to the unchanged historic fixture (no /1
        # dispatch/rescore enabled).
        campaign_root = (preflight.WORKSPACE_ROOT / 'research/model-evaluations'
                         / 'qwen35-9b/campaign-groups'
                         / 'qwen35-9b-rtx5070-cuda-helicopterbench-2026-11-07')
        if not (campaign_root / 'sections/helicopterbench/manifest.json').exists():
            self.skipTest('authentic /1 campaign evidence not reachable')
        result = release_validation.validate_section(campaign_root,
                                                     'helicopterbench')
        self.assertTrue(result['verified'], result)
        self.assertEqual(result['methodology'], 'helicopterbench/1')


if __name__ == '__main__':
    unittest.main()
