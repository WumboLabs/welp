"""HelicopterBench /3 independent human playtesting review (SPEC §4.11,
methodology helicopterbench/3, owner-approved prospective 2026-11-11).

A SEPARATE acceptance channel next to the frozen automated 14-check verifier:
it never enters, averages with or overwrites the automated score in
``heli-score.json``. The operating agent never invents human answers and
never produces a model self-score — answers only ever arrive from an
attributed human reviewer through ``import``.

Store (outside the immutable section manifest; never mutates finalized
game/scoring evidence under ``sections/helicopterbench/``):

    <campaign>/human-review/helicopterbench/
        review.json                     operative review (publish-if-absent)
        superseded/review-<sha256>.json preserved prior review revisions
        reconciliation.jsonl            append-only reconciliation records
        sessions/<UTC>/checklist.html   prepared local review surfaces

Exact-game binding: every review binds, by SHA-256, the finalized artifact
bytes and the automated evidence set (submission.html, heli-verification.json,
heli-score.json, manifest.json) plus the extraction artifact digest. Import
refuses any binding that does not match the current finalized section, so a
review can never be attached to different or altered game/automation bytes.

Answers are per-checklist-item Yes (full item points) / No (zero) / explicitly
unresolved; a missing item is unanswered. ``earned_points`` is a RUNNING total
and never a final score until every item is answered and every dispute is
reconciled (state ``FINALIZED``). Material disagreements (the reviewer's
explicit answer contradicting an explicit automated verdict, or reviewer-
declared disputes) are resolved ONLY by explicit append-only reconciliation
records carrying evidence, rationale and the attributed reviewer; automated
results are never averaged or overwritten. A review may be superseded only
while NOT finalized, explicitly (``supersedes`` digest), by the SAME
reviewer id, with the prior revision preserved verbatim under ``superseded/``.

Play surfaces: ``prepare`` writes the checklist-only safe default — the
trusted surface never executes the game (an ordinary-browser double-click is
safe; CSP/sandbox cannot block WebRTC STUN/TURN). ``play`` launches the
entire trusted checklist + exact game inside a disposable bubblewrap
NETWORK namespace (``--unshare-all``; no external interface exists, so no
STUN/TURN/fetch route out), read-only runtime — the ENABLED review surface
is written to an ANONYMOUS memfd and supplied through bubblewrap's native
``--ro-bind-data`` descriptor interface (never a named host file; SIGKILL-safe)
— only the session-local review-export
directory and a fresh browser-private profile writable, narrow
Wayland-socket display only (no unsafe X11 fallback; the host socket is
resolved separately from possibly-absolute ``WAYLAND_DISPLAY`` and bound at
a fixed namespace-local name), GPU disabled, hard host-side timeout, named
fail-closed refusals for missing bwrap/browser/Wayland, and an explicit
bounded-diagnostic failure on any nonzero browser exit. No server, no
service. The independent mechanical verifier remains the existing bubblewrap
CDP sandbox (``welp_next.browser_harness``) and is never altered by this
review.
"""
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from . import policy, store
from . import browser_harness
from .scorers import helicopterbench_v3 as rubric

SECTION = 'helicopterbench'
METHODOLOGY = rubric.METHODOLOGY_VERSION
REVIEW_SCHEMA = 'welp-heli-review/1'
RECONCILIATION_SCHEMA = 'welp-heli-reconciliation/1'
BINDING_SCHEMA = 'welp-heli-binding/1'
SAFE_SUMMARY_SCHEMA = 'welp-heli-review-safe-summary/1'
RESOLUTIONS = ('automated_stands', 'reviewer_stands')

# Files of the finalized automated evidence bound into every review.
BOUND_FILES = ('submission.html', 'heli-verification.json', 'heli-score.json',
               'manifest.json')

# The human checklist mirrors the frozen /3 rubric one-to-one (same 14 items,
# same categories, same points; single weight authority: the /3 rubric), so a
# reviewer's independent play assessment localizes disagreements exactly.
# The human checklist asks the EXACT 14 owner-approved questions, verbatim,
# in rubric order. Numeric/mechanical clarification lives in the recorded-
# evidence supplements panel, never in the question text.
PROMPTS = {
    'no_runtime_exceptions': 'Does the game start without crashing?',
    'canvas_present': 'Does the game display its playing area?',
    'animation_liveliness': 'Does the game visibly animate?',
    'input_causes_ascent': 'Does holding the control make the helicopter rise?',
    'gravity_causes_descent': 'Does releasing the control make it descend?',
    'controls_state_numeric': 'Does the helicopter respond consistently to input?',
    'obstacles_present': 'Do obstacles appear?',
    'obstacles_advance': 'Do obstacles move toward the helicopter?',
    'collision_produces_game_over': 'Can hitting an obstacle end the game?',
    'score_accrues': 'Does the score increase during gameplay?',
    'game_over_visible_text': 'Does a game-over message or screen appear?',
    'restart_resets': 'Can the player restart after losing?',
    'difficulty_increases': 'Does the game become harder over time?',
    'speed_increases': 'Does the game speed up as play progresses?',
}

# Recorded mechanical evidence panels that may supplement (never replace) the
# reviewer's judgment for numeric-state items.
SUPPLEMENTS = {
    'no_runtime_exceptions': ['load_exceptions'],
    'animation_liveliness': ['liveliness_frame_bytes'],
    'input_causes_ascent': ['hold_trajectory'],
    'gravity_causes_descent': ['gravity_samples'],
    'controls_state_numeric': ['gravity_samples', 'hold_trajectory'],
    'obstacles_advance': ['obstacle_x_samples'],
    'collision_produces_game_over': ['game_over_new_visible_text',
                                     'game_over_text_sample'],
    'score_accrues': ['score_samples'],
    'game_over_visible_text': ['game_over_new_visible_text'],
    'restart_resets': ['post_restart_state'],
    'difficulty_increases': ['difficulty_samples'],
    'speed_increases': ['speed_samples'],
}

CHECK_ITEMS = [(category, check, points)
               for category, spec in rubric.RUBRIC.items()
               for check, points in spec['subchecks'].items()]
CHECKLIST_MAX = sum(points for _, _, points in CHECK_ITEMS)

ANSWER_VALUES = (True, False, 'unresolved')
REVIEW_KEYS = frozenset(('schema', 'methodology', 'binding', 'reviewer',
                         'played', 'answers', 'notes', 'disputes', 'at',
                         'supersedes'))


def store_base(campaign):
    return Path(campaign) / 'human-review' / SECTION


def section_dir(campaign):
    return Path(campaign) / 'sections' / SECTION


def _has_submission(section):
    """True only when a real COMPLETED submission was gameplay-scored:
    extraction bound a digest AND the generation outcome was a valid
    completed submission (PASS). Extractable bytes inside a truncated
    (finish=length) reply were never a submission; budget-limited, empty and
    artifact-deficient generations submit nothing. There is no game to play
    in those cases: human gameplay review is NOT_APPLICABLE — no invented
    answers, no invented play claim, no invented score."""
    extraction_path = Path(section) / 'extraction.json'
    score_path = Path(section) / 'heli-score.json'
    if not extraction_path.exists() or not score_path.exists():
        return False
    extraction = store.read_json(extraction_path)
    score = store.read_json(score_path)
    # A TECHNICAL_INVALID environment failure on a real submitted game still
    # leaves a playable exact game: the gate applies (score may be None).
    return (extraction.get('artifact_sha256') is not None
            and extraction.get('gameplay_scored') is True
            and score.get('generation_outcome') == 'PASS')


def _require_finalized_v3(campaign):
    section = section_dir(campaign)
    if not (section / 'manifest.json').exists():
        raise policy.CheckError(
            'heli-review: helicopterbench section is not finalized; '
            'finalize the automated record first')
    from . import reporting
    reporting.verify_manifest(section)
    methodology = store.read_json(section / 'run.json').get('methodology')
    if methodology != METHODOLOGY:
        raise policy.CheckError(
            f'heli-review: human playtesting is a {METHODOLOGY} component; '
            f'the section methodology is {methodology!r}')
    return section


def binding(campaign):
    """Exact binding of one finalized section: game bytes + automated
    evidence set + extraction digest + manifest profile revision."""
    section = _require_finalized_v3(campaign)
    extraction = store.read_json(section / 'extraction.json')
    manifest = store.read_json(section / 'manifest.json')
    return {'schema': BINDING_SCHEMA, 'section': SECTION,
            'campaign': Path(campaign).resolve().name,
            'methodology': METHODOLOGY,
            'profile_revision': manifest.get('profile_revision'),
            'artifact_sha256': extraction.get('artifact_sha256'),
            'automation_sha256': {name: policy.file_sha(section / name)
                                  for name in BOUND_FILES}}


def _verify_binding(campaign, claimed):
    expected = binding(campaign)
    if claimed != expected:
        differing = sorted(
            key for key in set(expected) | set(claimed or {})
            if (claimed or {}).get(key) != expected.get(key))
        raise policy.CheckError(
            'heli-review.binding: review does not bind the finalized '
            f'automation/game/manifest exactly (mismatched: {differing})')
    return expected


def _revalidate_review(campaign, review):
    """ONE shared reconstruction predicate (import, status, safe_summary):
    structure validation AND exact re-binding of the stored review against
    the current finalized automation/game/manifest. A stored review whose
    binding no longer matches can never produce a gate state."""
    _validate_review(review)
    _verify_binding(campaign, review.get('binding'))
    return review


def _check_values(value, where):
    if not isinstance(value, dict):
        raise policy.CheckError(f'heli-review.{where}: must be an object')
    for key, answer in value.items():
        if key not in PROMPTS:
            raise policy.CheckError(
                f'heli-review.{where}: unknown checklist item {key!r}')
        if answer is not True and answer is not False \
                and answer != 'unresolved':
            raise policy.CheckError(
                f'heli-review.{where}: {key} must be true (Yes), false (No) '
                "or 'unresolved'")


def _validate_reviewer(reviewer, where):
    """Shared attributed-HUMAN-reviewer predicate (import and every
    reconstruction). Id is stripped and required; model/agent roles are
    refused — agent answers are never accepted under any label."""
    if not isinstance(reviewer, dict) or 'id' not in reviewer:
        raise policy.CheckError(
            f'heli-review.{where}: reviewer must carry a non-empty "id" '
            '(attributed reviewer; anonymous or agent-authored answers are '
            'refused)')
    extra = set(reviewer) - {'id', 'role'}
    if extra:
        raise policy.CheckError(
            f'heli-review.{where}.reviewer: unexpected keys {sorted(extra)}')
    rid = reviewer.get('id')
    if not isinstance(rid, str) or not rid.strip():
        raise policy.CheckError(
            f'heli-review.{where}: reviewer id must be a non-empty string')
    reviewer['id'] = rid.strip()
    role = reviewer.get('role')
    if role is not None:
        if not isinstance(role, str) or not role.strip():
            raise policy.CheckError(
                f'heli-review.{where}: reviewer role must be a non-empty '
                'string when present')
        stripped = role.strip()
        lowered = stripped.lower()
        if 'model' in lowered or 'agent' in lowered:
            raise policy.CheckError(
                f'heli-review.{where}: reviewer role {stripped!r} is refused '
                '(model/agent roles can never review); answers must come '
                'from an attributed human reviewer')
        reviewer['role'] = stripped
    return reviewer


def _validate_review(candidate):
    """Fail-closed validation of a saved reviewer file (never inferred,
    never auto-corrected). Shared by import and every reconstruction."""
    unknown = set(candidate) - REVIEW_KEYS
    if unknown:
        raise policy.CheckError(
            f'heli-review.review: unexpected keys {sorted(unknown)}')
    if candidate.get('schema') != REVIEW_SCHEMA:
        raise policy.CheckError(
            f'heli-review.review: schema must be {REVIEW_SCHEMA!r}')
    if candidate.get('methodology') != METHODOLOGY:
        raise policy.CheckError(
            f'heli-review.review: methodology must be {METHODOLOGY!r}')
    _validate_reviewer(candidate.get('reviewer'), 'review')
    if candidate.get('played') is not True:
        raise policy.CheckError(
            'heli-review.review: "played" must be true; a review without '
            'play of the exact bound game is refused')
    _check_values(candidate.get('answers'), 'answers')
    notes = candidate.get('notes')
    if notes is not None:
        if not isinstance(notes, dict):
            raise policy.CheckError('heli-review.notes: must be an object')
        for key, note in notes.items():
            if key not in PROMPTS:
                raise policy.CheckError(
                    f'heli-review.notes: unknown checklist item {key!r}')
            if not isinstance(note, str):
                raise policy.CheckError(
                    f'heli-review.notes: {key} must be a string')
    disputes = candidate.get('disputes')
    if disputes is not None:
        if not isinstance(disputes, list):
            raise policy.CheckError('heli-review.disputes: must be a list')
        for dispute in disputes:
            if not isinstance(dispute, dict):
                raise policy.CheckError('heli-review.disputes: entries must '
                                        'be objects')
            if dispute.get('check') not in PROMPTS:
                raise policy.CheckError(
                    'heli-review.disputes: check must be a checklist item')
            for field in ('claim', 'evidence'):
                if not isinstance(dispute.get(field), str) \
                        or not dispute.get(field).strip():
                    raise policy.CheckError(
                        f'heli-review.disputes: {field} must be a non-empty '
                        'string')
            unexpected = set(dispute) - {'check', 'claim', 'evidence'}
            if unexpected:
                raise policy.CheckError(
                    'heli-review.disputes: unexpected keys '
                    f'{sorted(unexpected)}')
    if 'at' in candidate and not isinstance(candidate.get('at'), str):
        raise policy.CheckError('heli-review.review: "at" must be a string')
    if 'supersedes' in candidate and (
            not isinstance(candidate.get('supersedes'), str)
            or len(candidate['supersedes']) != 64):
        raise policy.CheckError(
            'heli-review.review: "supersedes" must be the 64-hex SHA-256 of '
            'the prior review')
    return candidate


def _read_json_file(path):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise policy.CheckError(f'heli-review.{path}: {exc}') from exc


def operative_review_path(campaign):
    return store_base(campaign) / 'review.json'


def _operative_review_bytes(campaign):
    path = operative_review_path(campaign)
    if not path.exists():
        return None, None
    data = path.read_bytes()
    return data, _file_sha256(data)


def _file_sha256(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def review_digest(campaign):
    """Exact content digests of the human-review sidecar for acceptance
    binding: review_sha256, reconciliation_sha256 and the combined
    human_review_sha256 (canonical digest over both). Any swapped or new
    review, or any reconciliation change, breaks a digest recorded elsewhere."""
    review_bytes, review_sha = _operative_review_bytes(campaign)
    rec_path = store_base(campaign) / 'reconciliation.jsonl'
    rec_sha = _file_sha256(rec_path.read_bytes()) if rec_path.exists() else None
    combined = None if review_sha is None else policy.digest(
        {'review': review_sha, 'reconciliation': rec_sha})
    return {'review_sha256': review_sha,
            'reconciliation_sha256': rec_sha,
            'human_review_sha256': combined}


def _validate_reconciliation_entry(entry, where):
    """Shared reconciliation-row predicate (append and every read): schema,
    checklist item, allowed resolution, non-empty attributed HUMAN reviewer,
    evidence and rationale. Malformed or unattributed rows never count as
    resolved disputes."""
    unknown = set(entry) - {'schema', 'check', 'resolution', 'evidence',
                            'rationale', 'reviewer', 'at', 'review_sha256'}
    if unknown:
        raise policy.CheckError(
            f'heli-review.{where}: unexpected keys {sorted(unknown)}')
    if entry.get('schema') != RECONCILIATION_SCHEMA:
        raise policy.CheckError(
            f'heli-review.{where}: schema must be {RECONCILIATION_SCHEMA!r}')
    if entry.get('check') not in PROMPTS:
        raise policy.CheckError(
            f'heli-review.{where}: check must be a checklist item')
    if entry.get('resolution') not in RESOLUTIONS:
        raise policy.CheckError(
            f'heli-review.{where}: resolution must be one of '
            f'{list(RESOLUTIONS)}')
    for field in ('evidence', 'rationale'):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            raise policy.CheckError(
                f'heli-review.{where}: {field} must be a non-empty string '
                '(explicit reconciliation; never implicit)')
    _validate_reviewer(entry.get('reviewer'), where)
    if entry.get('at') is not None and not isinstance(entry.get('at'), str):
        raise policy.CheckError(
            f'heli-review.{where}: "at" must be a string')
    digest = entry.get('review_sha256')
    if digest is not None and (not isinstance(digest, str)
                               or len(digest) != 64):
        raise policy.CheckError(
            f'heli-review.{where}: review_sha256 must be a 64-hex digest')
    return entry


def _reconciliation_entries(campaign):
    path = store_base(campaign) / 'reconciliation.jsonl'
    if not path.exists():
        return []
    entries = []
    for index, line in enumerate(path.read_bytes().splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise policy.CheckError(
                f'heli-review.reconciliation: malformed entry #{index + 1}: '
                f'{exc}') from exc
        # Revalidate EVERY stored row on read: a modified sidecar can never
        # turn malformed or unattributed rows into resolved disputes.
        entries.append(_validate_reconciliation_entry(
            entry, f'reconciliation#{index + 1}'))
    return entries


def _automated_verdicts(campaign):
    section = section_dir(campaign)
    score_path = section / 'heli-score.json'
    if not score_path.exists():
        return {}
    verdicts = {}
    categories = store.read_json(score_path).get('categories') or {}
    if not isinstance(categories, dict):
        return verdicts
    for category in categories.values():
        subchecks = (category or {}).get('subchecks') or {}
        if not isinstance(subchecks, dict):
            continue
        for check, detail in subchecks.items():
            verdicts[check] = (detail or {}).get('pass')
    return verdicts


def status(campaign):
    """Operator-facing human-review state (the reconciliation gate)."""
    campaign = Path(campaign)
    section = section_dir(campaign)
    run_methodology = None
    if (section / 'run.json').exists():
        run_methodology = store.read_json(section / 'run.json').get('methodology')
    base = {
        'applicable': run_methodology == METHODOLOGY,
        'section_finalized': (section / 'manifest.json').exists(),
        'methodology': run_methodology,
        'state': 'NOT_IMPORTED', 'reconciled': False,
        'max': CHECKLIST_MAX, 'total_items': len(CHECK_ITEMS),
        'answered': 0, 'earned_points': None, 'final_points': None,
        'reviewer': None, 'unresolved_items': [], 'open_disputes': [],
        'reconciled_disputes': 0, 'stale_reconciliations': 0,
        'review_sha256': None, 'reconciliation_sha256': None,
        'human_review_sha256': None,
        'reviewer_identity_note': 'full identity, notes, dispute claims and '
                                  'rationales stay in the private original '
                                  'review; use safe_summary for a public-safe '
                                  'projection',
    }
    if run_methodology != METHODOLOGY:
        return base
    if not _has_submission(section):
        base['state'] = 'NOT_APPLICABLE_NO_SUBMISSION'
        base['reason'] = ('no valid completed submission was gameplay-scored '
                          '(budget-limited, empty, artifact-deficient or '
                          'non-completed generation): there is no game to '
                          'play and no human gameplay score; nothing is '
                          'invented')
        return base
    base.update(review_digest(campaign))
    review_bytes, review_sha = _operative_review_bytes(campaign)
    if review_bytes is None:
        return base
    review = _revalidate_review(
        campaign, _read_json_file(operative_review_path(campaign)))
    answers = review.get('answers') or {}
    verdicts = _automated_verdicts(campaign) \
        if base['section_finalized'] else {}
    explicit = [check for _category, check, _points in CHECK_ITEMS
                if answers.get(check) is True or answers.get(check) is False]
    unresolved = sorted(
        check for _category, check, _points in CHECK_ITEMS
        if answers.get(check) is not True and answers.get(check) is not False)
    earned = sum(points for _category, check, points in CHECK_ITEMS
                 if answers.get(check) is True)
    open_disputes = {d['check'] for d in (review.get('disputes') or [])}
    for check, answer in answers.items():
        verdict = verdicts.get(check)
        if answer is True and verdict is False:
            open_disputes.add(check)     # reviewer: works; automation: fails
        elif answer is False and verdict is True:
            open_disputes.add(check)     # reviewer: broken; automation: passes
    reconciled = {}
    for entry in _reconciliation_entries(campaign):
        if entry.get('review_sha256') == review_sha:
            reconciled[entry['check']] = entry.get('resolution')
        else:
            base['stale_reconciliations'] += 1
    remaining = sorted(open_disputes - set(reconciled))
    if unresolved:
        state = 'UNRESOLVED'
    elif remaining:
        state = 'DISPUTED'
    else:
        state = 'FINALIZED'
    base.update({'state': state, 'reconciled': state == 'FINALIZED',
                 'answered': len(explicit),
                 'earned_points': earned,
                 'final_points': earned if state == 'FINALIZED' else None,
                 'reviewer': (review.get('reviewer') or {}).get('id'),
                 'unresolved_items': unresolved,
                 'open_disputes': remaining,
                 'reconciled_disputes': len(reconciled)})
    return base


def safe_summary(campaign):
    """Public-safe projection for publication exports: exact game/automation
    binding digests, answers, points, review/reconciliation state and
    unresolved IDs. No reviewer identity, no raw notes, no dispute prose, no
    host paths. Human answers are projected verbatim — never inferred."""
    campaign = Path(campaign)
    base = status(campaign)
    if not base['applicable']:
        return {'schema': SAFE_SUMMARY_SCHEMA, 'methodology': base['methodology'],
                'applicable': False,
                'note': 'human playtesting applies to methodology '
                        f'{METHODOLOGY} only'}
    if base['state'] == 'NOT_APPLICABLE_NO_SUBMISSION':
        # Verified no-submission/no-gameplay-score disposition: no binding
        # reads (the files do not exist), no answers, no invented score.
        return {'schema': SAFE_SUMMARY_SCHEMA, 'methodology': METHODOLOGY,
                'applicable': True, 'state': base['state'],
                'reason': base.get('reason'), 'reconciled': False,
                'answered': 0, 'total_items': base['total_items'],
                'max': base['max'], 'earned_points': None,
                'final_points': None, 'answers': {},
                'unresolved_items': [], 'open_disputes': [],
                'reconciliations': {}, 'stale_reconciliations': 0,
                'review_sha256': None, 'reconciliation_sha256': None,
                'human_review_sha256': None,
                'reviewer_identity': 'OMITTED (private original review)',
                'notes': 'OMITTED (private original review)',
                'acceptance_gate': {
                    'required_for_official': False, 'pass': True,
                    'reason': 'verified no-submission/no-gameplay-score '
                              'disposition is exempt from gameplay review'}}
    review_bytes, review_sha = _operative_review_bytes(campaign)
    answers = {}
    if review_bytes is not None:
        raw = (_revalidate_review(
            campaign,
            _read_json_file(operative_review_path(campaign))).get('answers')
            or {})
        for _category, check, _points in CHECK_ITEMS:
            value = raw.get(check)
            answers[check] = value if value in (True, False, 'unresolved') \
                else 'unanswered'
    reconciliations = {}
    if review_sha is not None:
        for entry in _reconciliation_entries(campaign):
            if entry.get('review_sha256') == review_sha:
                reconciliations[entry['check']] = entry.get('resolution')
    bound = binding(campaign)
    return {'schema': SAFE_SUMMARY_SCHEMA, 'methodology': METHODOLOGY,
            'applicable': True,
            'artifact_sha256': bound['artifact_sha256'],
            'game_sha256': bound['artifact_sha256'],
            'automation_sha256': bound['automation_sha256'],
            'review_sha256': base.get('review_sha256'),
            'reconciliation_sha256': base.get('reconciliation_sha256'),
            'human_review_sha256': base.get('human_review_sha256'),
            'state': base['state'], 'reconciled': base['reconciled'],
            'answered': base['answered'], 'total_items': base['total_items'],
            'max': base['max'], 'earned_points': base['earned_points'],
            'final_points': base['final_points'],
            'answers': answers,
            'unresolved_items': base['unresolved_items'],
            'open_disputes': base['open_disputes'],
            'reconciliations': reconciliations,
            'stale_reconciliations': base['stale_reconciliations'],
            'reviewer_identity': 'OMITTED (private original review)',
            'notes': 'OMITTED (private original review)',
            'acceptance_gate': {'required_for_official': True,
                                'pass': base['state'] == 'FINALIZED',
                                'reason': 'finalized and fully reconciled'
                                if base['state'] == 'FINALIZED'
                                else f"human review is {base['state']}"}}


# --------------------------------------------------------------------------
# Review surface (prepare): one self-contained local HTML checklist


def _safe_json_blob(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) \
        .replace('<', '\\u003c').replace('\u2028', '\\u2028') \
        .replace('\u2029', '\\u2029')


def _review_context(campaign, *, mount_enabled=False):
    section = section_dir(campaign)
    verification = store.read_json(section / 'heli-verification.json') \
        if (section / 'heli-verification.json').exists() else {}
    score = store.read_json(section / 'heli-score.json') \
        if (section / 'heli-score.json').exists() else {}
    evidence = {key: value for key, value in (verification.get('evidence') or {}).items()
                if key != 'review_screenshots_b64'}
    # Draft round-trip: an imported NOT-finalized review is loaded back
    # verbatim (the reviewer's own answers/notes/attribution plus the exact
    # supersedes digest) so the human can finish it in the UI without
    # hand-editing JSON. Nothing is invented: absent answers stay absent.
    draft = None
    review_bytes, review_sha = _operative_review_bytes(campaign)
    if review_bytes is not None:
        review = _revalidate_review(
            campaign, _read_json_file(operative_review_path(campaign)))
        if status(campaign)['state'] == 'FINALIZED':
            raise policy.CheckError(
                'heli-review.prepare: the imported review is FINALIZED and '
                'immutable; no new review surface is needed')
        reviewer = review.get('reviewer') or {}
        draft = {'supersedes': review_sha,
                 'reviewer': {'id': reviewer.get('id'),
                              'role': reviewer.get('role')},
                 'answers': dict(review.get('answers') or {}),
                 'notes': dict(review.get('notes') or {}),
                 # Explicit reviewer-declared disputes are preserved verbatim
                 # through the draft round-trip; they are never dropped.
                 'disputes': [dict(dispute)
                              for dispute in (review.get('disputes') or [])]}
    return {'binding': binding(campaign),
            'draft': draft,
            'mount_enabled': bool(mount_enabled),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'automated': {
                'class': score.get('class'),
                'final_score': score.get('final_score'),
                'mechanical_points': score.get('mechanical_points'),
                'mechanical_max': score.get('mechanical_max'),
                'generation_outcome': score.get('generation_outcome'),
                'checks': verification.get('checks') or {},
                'categories': score.get('categories') or {},
            },
            'evidence': evidence,
            'checklist': [
                {'check': check, 'category': category, 'points': points,
                 'prompt': PROMPTS[check],
                 'supplements': SUPPLEMENTS.get(check, [])}
                for category, check, points in CHECK_ITEMS]}


def prepare(campaign):
    """Write one self-contained local review surface (checklist + the exact
    SHA-verified game embedded in a sandboxed opaque-origin iframe)."""
    section = _require_finalized_v3(campaign)
    if not _has_submission(section):
        raise policy.CheckError(
            'heli-review.prepare: NOT_APPLICABLE_NO_SUBMISSION — no valid '
            'completed submission was gameplay-scored (budget-limited, '
            'empty, artifact-deficient or non-completed generation); there '
            'is no game to play and no review surface to prepare')
    context = _review_context(campaign, mount_enabled=False)
    game_text = _game_text(campaign)
    session = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    directory = store_base(campaign) / 'sessions' / f'{session}-{uuid.uuid4().hex[:8]}'
    path = directory / 'checklist.html'
    if path.exists():
        raise policy.CheckError(
            f'heli-review.prepare: session surface {path} already exists')
    store.put(path, _checklist_html(context, game_text).encode('utf-8'))
    return {'disposition': 'PREPARED', 'checklist': str(path),
            'binding': context['binding'],
            'draft_loaded': context['draft'] is not None,
            'instruction':
                'This surface is the trusted CHECKLIST FRONT only: open it '
                'in an ordinary browser to read the binding, safety boundary '
                'and the recorded automated evidence — it NEVER executes the '
                'game. For actual play run the network-isolated session: '
                f'welp heli-review --campaign {Path(campaign)} play  '
                '(inside that namespace the enabled transient copy of this '
                'checklist embeds the same exact game; play there, answer '
                'every item (Yes/No/unresolved), export the review JSON, '
                'then: welp heli-review --campaign '
                f'{Path(campaign)} import --review <saved.json>'
                + (' An imported unfinished review was loaded verbatim '
                   '(answers, notes, reviewer id, disputes, supersedes '
                   'digest); the played box must be re-checked after '
                   'playing again.'
                   if context['draft'] is not None else '')}


def _game_text(campaign):
    """The exact submitted bytes, decoded WITHOUT newline translation (a
    read_text would normalize CRLF and spuriously break the SHA-256
    binding)."""
    game_path = section_dir(campaign) / 'submission.html'
    game_bytes = game_path.read_bytes()
    try:
        return game_bytes.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise policy.CheckError(
            'heli-review: submission bytes are not UTF-8 text '
            f'({exc}); the exact-byte binding cannot be embedded') from exc


def play(campaign, *, browser_binary=None, timeout_seconds=3600.0,
         headless=False):
    """Network-isolated human play session (the P1 route).

    CSP and the opaque-origin iframe sandbox do NOT block WebRTC
    STUN/TURN, so the trusted checklist + exact game are launched INSIDE a
    disposable bubblewrap namespace: --unshare-all leaves only a private
    loopback (no external interface exists — no STUN/TURN/fetch target of
    any kind). The runtime and the play surface are bound READ-ONLY; the
    only writable host binds are the session-local review-export directory
    and the fresh browser-private profile. Interactive display is a narrow
    Wayland socket bind only (no unsafe X11 fallback); GPU is disabled.
    Named fail-closed refusals for missing bwrap/browser/Wayland. No
    server, no service, no gameplay claims."""
    section = _require_finalized_v3(campaign)
    if not _has_submission(section):
        raise policy.CheckError(
            'heli-review.play: NOT_APPLICABLE_NO_SUBMISSION — no valid '
            'completed submission was gameplay-scored; there is no game to '
            'play')
    if shutil.which('bwrap') is None:
        raise policy.CheckError(
            'heli-review.play: bwrap not found; the network-isolated play '
            'session requires the installed bubblewrap tool')
    browser_binary = browser_binary or browser_harness.find_browser()
    if not browser_binary:
        raise policy.CheckError(
            'heli-review.play: no installed Chromium-family browser found '
            '(the isolated play session uses the deployed browser binary; '
            'none is downloaded or installed)')
    resolved = Path(shutil.which(browser_binary) or browser_binary)
    real = Path(os.path.realpath(resolved))
    wayland = None
    if not headless:
        # WAYLAND_DISPLAY may be a bare name (resolved under
        # XDG_RUNTIME_DIR) or an ABSOLUTE socket path — resolve the host
        # socket separately and bind it at a FIXED namespace-local name so
        # absolute names cannot break the bind.
        display = os.environ.get('WAYLAND_DISPLAY') or 'wayland-0'
        runtime_dir = os.environ.get('XDG_RUNTIME_DIR')
        host_socket = Path(display) if os.path.isabs(display) \
            else (Path(runtime_dir) / display if runtime_dir else None)
        if host_socket is None or not host_socket.exists():
            raise policy.CheckError(
                'heli-review.play: no Wayland display socket found '
                f'(WAYLAND_DISPLAY={display!r}, XDG_RUNTIME_DIR='
                f'{runtime_dir!r}); headed play requires a live Wayland '
                'session — there is no unsafe X11 fallback')
        wayland = (host_socket, 'wayland-0')
    context = _review_context(campaign, mount_enabled=True)
    session = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    directory = store_base(campaign) / 'sessions' / \
        f'{session}-{uuid.uuid4().hex[:8]}-play'
    export_dir = directory / 'review-export'
    profile_dir = directory / 'profile'
    export_dir.mkdir(parents=True, exist_ok=True)
    default_dir = profile_dir / 'Default'
    default_dir.mkdir(parents=True, exist_ok=True)
    # Seed the fresh browser profile so the exported review.json lands in
    # the only writable session directory (textarea copy is the fallback).
    (default_dir / 'Preferences').write_text(json.dumps(
        {'download': {'default_directory': '/work/review-export',
                      'prompt_for_download': False}}, sort_keys=True),
        encoding='utf-8')
    # The ENABLED play surface NEVER exists as a named host file (a
    # SIGKILLed launcher could otherwise leave it behind): it is written
    # into an anonymous memfd and supplied through bubblewrap's read-only
    # data-descriptor interface, never a host-visible path.
    payload = _checklist_html(context, _game_text(campaign)).encode('utf-8')
    play_fd = os.memfd_create('welp-heli-play-enabled-html')
    try:
        # write() in full (os.write alone may perform a partial write).
        with os.fdopen(play_fd, 'wb', closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.lseek(play_fd, 0, os.SEEK_SET)
        argv = _play_argv(str(real), play_fd, export_dir, profile_dir,
                          wayland=wayland, headless=headless)
        started = time.time()
        try:
            completed = subprocess.run(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=timeout_seconds,
                pass_fds=(play_fd,), env={'PATH': '/usr/bin'})
        except subprocess.TimeoutExpired:
            raise policy.CheckError(
                'heli-review.play: the play session exceeded its hard '
                f'{timeout_seconds}s wall-clock bound and was terminated '
                '(fail-closed)')
        if completed.returncode != 0:
            # Explicit bounded diagnostic (browser stderr tail); the session
            # stayed isolated and never recorded gameplay claims.
            tail = (completed.stderr or b'')[-400:].decode(
                'utf-8', 'replace').strip().replace('\n', ' | ')
            raise policy.CheckError(
                f'heli-review.play: the isolated browser exited nonzero '
                f'(exit {completed.returncode}). No gameplay claims were '
                f'recorded. Browser stderr tail: {tail or "<empty>"}')
    finally:
        # The memfd (and with it the enabled play surface) dies here and
        # with the launcher process — including SIGKILL; nothing named ever
        # existed on the host. The browser-private profile is discarded;
        # the reviewer export directory persists.
        os.close(play_fd)
        shutil.rmtree(profile_dir, ignore_errors=True)
    return {'disposition': 'PLAY_SESSION_CLOSED',
            'exit_code': completed.returncode,
            'elapsed_seconds': round(time.time() - started, 3),
            'review_export_dir': str(export_dir),
            'headless': headless,
            'network_isolation': 'bwrap --unshare-all: no external network '
                                 'interface exists in the namespace; '
                                 'WebRTC STUN/TURN and every other channel '
                                 'have no route out',
            'note': 'no gameplay claims are recorded by launching; the '
                    'reviewer records their review via heli-review import'}


def _play_argv(browser, play_fd, export_dir, profile_dir, *, wayland,
               headless):
    """Pure argv builder (SOFTWARE_TEST-verifiable) for the isolated play
    session: network namespace, read-only runtime, the enabled play surface
    bound read-only from an ANONYMOUS memfd (never a named host file),
    writable session export + fresh browser profile, and
    a narrow Wayland socket bound at a FIXED namespace-local name
    (``wayland`` = (host socket path, local display name)); headless skips
    the display; GPU disabled."""
    browser = Path(browser)
    # The /work tmpfs precedes its file bind. Use the native descriptor
    # interface: bubblewrap does not preserve arbitrary /proc/self/fd paths.
    argv = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
            '--clearenv',
            '--ro-bind', '/usr', '/usr',
            '--ro-bind-try', '/lib', '/lib',
            '--ro-bind-try', '/lib64', '/lib64',
            '--ro-bind-try', '/bin', '/bin',
            '--ro-bind-try', '/sbin', '/sbin',
            '--tmpfs', '/tmp',
            '--tmpfs', '/work',
            '--ro-bind-data', str(play_fd), '/work/play.html',
            '--proc', '/proc', '--dev', '/dev',
            '--ro-bind', '/etc/fonts', '/etc/fonts',
            '--ro-bind', str(browser.parent), str(browser.parent),
            '--bind', str(export_dir), '/work/review-export',
            '--bind', str(profile_dir), '/profile',
            '--chdir', '/work',
            '--setenv', 'PATH', '/usr/bin:/bin',
            '--setenv', 'HOME', '/tmp',
            '--setenv', 'TMPDIR', '/tmp',
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1']
    if wayland is not None:
        host_socket, local_display = wayland
        argv += ['--dir', '/xdg-run',
                 '--bind', str(host_socket), f'/xdg-run/{local_display}',
                 '--setenv', 'XDG_RUNTIME_DIR', '/xdg-run',
                 '--setenv', 'WAYLAND_DISPLAY', local_display]
    flags = ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
             '--disable-extensions', '--no-first-run',
             '--no-default-browser-check', '--disable-background-networking',
             '--host-resolver-rules=MAP * ~NOTFOUND',
             '--user-data-dir=/profile']
    if headless:
        flags = ['--headless=new'] + flags
    else:
        flags = ['--ozone-platform=wayland'] + flags
    argv += ['--', str(browser)] + flags + ['file:///work/play.html']
    return argv


def _checklist_html(context, game_text):
    checklist_json = _safe_json_blob(context)
    game_json = _safe_json_blob(game_text)
    return CHECKLIST_TEMPLATE.replace('__CHECKLIST_CONTEXT__', checklist_json) \
        .replace('__GAME_BYTES__', game_json)


CHECKLIST_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<!-- Enforced on THIS document and INHERITED by the srcdoc game document
     (local-scheme documents inherit the parent policy container): the game
     runs with no network, no nested frames, no object/embed and no
     form/base targets regardless of iframe csp-attribute support. The
     sandboxed iframe carries the same policy as an extra Chromium-side
     tightening. NOTE: the earlier "no child frame" observation was an
     OOPIF/Target.getTargets artifact (the about:srcdoc target EXISTS);
     strict frame-src/child-src 'none' is retained unless a real mounted
     game is ever actually blocked. -->
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; media-src 'none'; connect-src 'none'; frame-src 'none'; child-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>WELP HelicopterBench /3 — independent human playtest review</title>
<style>
:root { font-family: system-ui, sans-serif; }
body { margin: 0 auto; max-width: 1040px; padding: 16px; color: #17202a; }
h1 { font-size: 1.25rem; } h2 { font-size: 1.05rem; margin-top: 1.4rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
td, th { border: 1px solid #ccd1d9; padding: 4px 8px; text-align: left;
         word-break: break-all; }
.banner { padding: 10px; margin: 8px 0; border-radius: 4px;
          white-space: pre-wrap; }
.bad { background: #fde8e8; border: 1px solid #e08080; }
.good { background: #e8f8f0; border: 1px solid #6fcf97; }
.note { color: #5a6472; font-size: 0.82rem; }
.item { border: 1px solid #ccd1d9; border-radius: 4px; padding: 10px;
        margin: 8px 0; }
.item header { font-weight: 600; }
.item .points { float: right; color: #5a6472; font-weight: 400; }
supplement, .supplement { background: #f5f6fa; padding: 6px 8px;
        font-size: 0.8rem; margin-top: 6px; white-space: pre-wrap;
        word-break: break-all; }
label { margin-right: 12px; }
iframe { width: 100%; height: 560px; border: 2px solid #17202a;
         background: #fff; }
textarea { width: 100%; min-height: 120px; font-family: monospace;
           font-size: 0.78rem; }
button { padding: 6px 12px; }
input[type="text"] { width: 100%; box-sizing: border-box; }
fieldset { border: 1px solid #ccd1d9; margin: 8px 0; }
</style>
</head>
<body>
<h1>WELP HelicopterBench /3 — independent human playtesting</h1>
<p class="note">This is a local, self-contained review surface. It is NOT the
automated verifier: the official automated 14-check verification runs inside
the disposable bubblewrap namespace (welp_next.browser_harness) and is never
altered by this review. Your answers are attributed to you, are never
inferred by any agent, and are never merged into the automated score.</p>

<h2>1. Binding</h2>
<div id="binding-panel"></div>
<div id="mount-status"></div>
<div id="automated-panel" class="banner good"></div>

<h2>2. Safety boundary and explicit limitations</h2>
<p class="note">The embedded game is byte-verified against the finalized
binding and, only on an exact match, mounted into an
<code>&lt;iframe sandbox="allow-scripts"&gt;</code> with an opaque origin.
The parent policy inherited by the game document denies all network,
object/embed, form and ALL nested-frame targets (frame-src/child-src
'none'); the verified game itself is the single sandboxed opaque-origin
srcdoc iframe (actual rendered-surface proof: canvas visible, game
__STATE__ live, rendered game-over). There is no same-origin access, no
host filesystem, no CDP, no cookies/storage, no popups, no top navigation.
Because CSP and the sandbox cannot block every exfiltration channel (e.g.
WebRTC STUN/TURN), mounting is ENABLED only in the transient copy that
<code>welp heli-review --campaign &lt;campaign&gt; play</code> launches
inside the disposable network-isolated bubblewrap namespace (no external
interface at all; read-only runtime and review file; only the session
review-export directory and a fresh browser-private profile writable;
narrow Wayland socket display, no X11 fallback; GPU disabled; enabled play
copy removed after the session). A copy opened directly outside that
session is the checklist-only safe default and NEVER executes the game.
The mechanical verifier (the existing bubblewrap CDP sandbox) remains
authoritative and is never altered by this review.</p>

<h2>3. Play the exact game</h2>
<p class="note">Hold the mouse button to ascend; release for gravity; click
after game over to restart. Play enough of a run to judge every item below;
the recorded mechanical evidence (numeric state samples) may supplement your
judgment for numeric items — it never replaces your play.</p>
<iframe id="game-frame" sandbox="allow-scripts" referrerpolicy="no-referrer"
        csp="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; frame-src 'none'; child-src 'none'; connect-src 'none'; font-src 'none'; media-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'"></iframe>

<h2>4. Checklist — Yes earns the item points, No earns zero, unresolved
stays unresolved</h2>
<div id="score-panel" class="banner good"></div>
<div id="checklist-panel"></div>

<h2>5. Reviewer</h2>
<p><label>Reviewer id: <input type="text" id="reviewer-id"></label>
<label>Role: <input type="text" id="reviewer-role" placeholder="operator"></label></p>
<p><label><input type="checkbox" id="played-box"> I played this exact bound game in the sandbox above.</label></p>

<h2>6. Export review</h2>
<p><button id="export-button" disabled>Build review JSON</button>
<a id="download-link" style="display:none">download review.json</a></p>
<p class="note" id="export-note">Export unlocks once the game bytes verify,
you attribute yourself by id, and the played box is checked. Partial answers
are allowed; any unanswered or unresolved item keeps the review UNRESOLVED,
and every material disagreement with the automated record must later be
reconciled explicitly (evidence + rationale + reviewer) — nothing is averaged
or overwritten.</p>
<textarea id="export-area" readonly placeholder="review JSON appears here"></textarea>

<script type="application/json" id="welp-review-context">__CHECKLIST_CONTEXT__</script>
<script type="application/json" id="welp-game-bytes">__GAME_BYTES__</script>
<script>
'use strict';
var CONTEXT = JSON.parse(document.getElementById('welp-review-context').textContent);
var GAME_TEXT = JSON.parse(document.getElementById('welp-game-bytes').textContent);

// Exact-byte binding verification uses the standard WebCrypto API
// (crypto.subtle). Local file URLs are secure contexts in Chromium; if the
// API is unavailable the surface FAILS CLOSED with a named refusal and the
// game is never mounted — there is no hash fallback.
function el(tag, attrs, text) {
  var node = document.createElement(tag);
  for (var k in (attrs || {})) node.setAttribute(k, attrs[k]);
  if (text !== undefined) node.textContent = text;
  return node;
}

var VERIFIED = false;
// Verify, then mount — never mount on any mismatch or missing WebCrypto.
  var binding = CONTEXT.binding;
  var panel = document.getElementById('binding-panel');
  var table = el('table');
  [['campaign', binding.campaign], ['methodology', binding.methodology],
   ['profile_revision', binding.profile_revision],
   ['artifact (game) sha256', binding.artifact_sha256]]
   .forEach(function (row) {
     var tr = el('tr');
     tr.appendChild(el('th', null, row[0]));
     tr.appendChild(el('td', null, String(row[1])));
     table.appendChild(tr);
   });
  Object.keys(binding.automation_sha256).forEach(function (name) {
    var tr = el('tr');
    tr.appendChild(el('th', null, name + ' sha256'));
    tr.appendChild(el('td', null, binding.automation_sha256[name]));
    table.appendChild(tr);
  });
  panel.appendChild(table);

  var statusBox = document.getElementById('mount-status');
  function refuse(message) {
    statusBox.appendChild(el('div', {'class': 'banner bad'}, message));
    document.getElementById('export-button').disabled = true;
  }
  if (CONTEXT.mount_enabled !== true) {
    // Safe default (prepare): this surface is checklist-only and NEVER
    // executes the game — double-clicking it in an ordinary browser is
    // safe. The network-isolated play session supplies an enabled copy.
    refuse('CHECKLIST-ONLY SAFE DEFAULT: this surface does not execute the '
           + 'game (CSP and the opaque-origin sandbox cannot block every '
           + 'exfiltration channel, e.g. WebRTC). For actual play launch '
           + 'the network-isolated session: welp heli-review --campaign '
           + '<campaign> play');
    // Still show the binding for transparency, never mount.
  } else {
  (async function verifyAndMount() {
    try {
      if (!window.crypto || !window.crypto.subtle
          || typeof window.crypto.subtle.digest !== 'function') {
        refuse('NAMED REFUSAL: this context does not provide '
               + 'crypto.subtle (a secure context is required for local '
               + 'file review in Chromium). The exact-byte binding cannot '
               + 'be verified and the game is NOT mounted.');
        return;
      }
      var gameBytes = new TextEncoder().encode(GAME_TEXT);
      var digestBuffer = await window.crypto.subtle.digest('SHA-256', gameBytes);
      var digestHex = Array.from(new Uint8Array(digestBuffer))
        .map(function (byte) { return ('0' + byte.toString(16)).slice(-2); })
        .join('');
      if (digestHex !== binding.artifact_sha256) {
        refuse('BINDING FAILURE: embedded game bytes hash to ' + digestHex
               + ' but the finalized binding is '
               + binding.artifact_sha256 + '. The game is NOT mounted. Do '
               + 'not review; regenerate the review surface.');
        return;
      }
      VERIFIED = true;
      statusBox.appendChild(el('div', {'class': 'good banner'},
        'Game bytes verified: sha256 = ' + digestHex
        + ' — mounted in the sandboxed opaque-origin iframe below.'));
      document.getElementById('game-frame').srcdoc = GAME_TEXT;
      if (typeof refreshExport === 'function') refreshExport();
    } catch (error) {
      refuse('BINDING VERIFICATION ERROR (' + error
             + '): the game is NOT mounted.');
    }
  })();
  }

function fmt(value) {
  if (value === undefined || value === null) return '—';
  if (Array.isArray(value)) return JSON.stringify(value);
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
function verdictWord(v) {
  return v === true ? 'passed'
       : v === false ? 'failed (0 points)'
       : 'not measured by the automated run';
}
function answerWord(a) {
  return a === true ? 'Yes — it works'
       : a === false ? 'No — it does not work as asked'
       : 'Unresolved — could not be assessed';
}

// The ORIGINAL automated score, shown separately: this human review never
// replaces, merges or averages it.
document.getElementById('automated-panel').textContent =
  'Automated verification (separate official channel — this review never '
  + 'changes or averages it): class ' + fmt(CONTEXT.automated.class)
  + ', final score ' + fmt(CONTEXT.automated.final_score) + ' / '
  + fmt(CONTEXT.automated.mechanical_max || 100) + ' (mechanical '
  + fmt(CONTEXT.automated.mechanical_points) + ' / '
  + fmt(CONTEXT.automated.mechanical_max || 100)
  + '), generation outcome: ' + fmt(CONTEXT.automated.generation_outcome) + '.';

// Checklist UI
var answers = {}, notes = {}, disputes = {};
// Draft round-trip: an imported NOT-finalized review is loaded back into
// the surface verbatim (the reviewer's OWN answers/notes/attribution, plus
// the supersedes digest); initial reviews stay unanswered. Nothing is
// invented or defaulted — only prior human input is restored.
var DRAFT = CONTEXT.draft || null;
if (DRAFT) {
  answers = Object.assign({}, DRAFT.answers || {});
  notes = Object.assign({}, DRAFT.notes || {});
  (DRAFT.disputes || []).forEach(function (dispute) {
    if (dispute && dispute.check && dispute.claim && dispute.evidence) {
      disputes[dispute.check] = {check: dispute.check, claim: dispute.claim,
                                 evidence: dispute.evidence};
    }
  });
}
var listPanel = document.getElementById('checklist-panel');
var scorePanel = document.getElementById('score-panel');
function refreshScore() {
  var answered = 0, earned = 0, unresolved = [], disputesRaised = 0,
      contradictions = 0;
  CONTEXT.checklist.forEach(function (item) {
    var a = answers[item.check];
    if (a === true) { answered++; earned += item.points; }
    else if (a === false) { answered++; }
    else unresolved.push(item.check);
    if (disputes[item.check]) disputesRaised++;
    var v = CONTEXT.automated.checks[item.check];
    if ((a === true && v === false) || (a === false && v === true)) {
      contradictions++;
    }
  });
  var lines = ['Answered ' + answered + ' / ' + CONTEXT.checklist.length +
               ' — RUNNING earned points: ' + earned + ' / ' + 100 +
               (unresolved.length
                ? (' — unresolved items: ' + unresolved.join(', '))
                : ' — no unresolved items') +
               ' — disputes raised: ' + disputesRaised +
               ' — material disagreements with the automated record: '
               + contradictions];
  lines.push('RUNNING TOTAL, NOT A FINAL SCORE: it becomes final only when ' +
             'every item is answered Yes/No and every dispute is reconciled. ' +
             'The automated score shown above stays separate and unchanged.');
  scorePanel.textContent = lines.join('\n');
}
refreshScore();
CONTEXT.checklist.forEach(function (item) {
  var box = el('div', {'class': 'item'});
  var head = el('header');
  head.appendChild(el('span', {'class': 'points'},
    item.category + ' — ' + item.points + ' pts · automated verification: '
    + verdictWord(CONTEXT.automated.checks[item.check])));
  head.appendChild(document.createTextNode(item.prompt));
  box.appendChild(head);
  var comparison = el('div', {'class': 'supplement'});
  comparison.style.display = 'none';
  function updateComparison() {
    var a = answers[item.check];
    var v = CONTEXT.automated.checks[item.check];
    var contradicting = (a === true && v === false)
                     || (a === false && v === true);
    if (contradicting) {
      comparison.style.display = 'block';
      comparison.textContent =
        'You answered "' + answerWord(a) + '" while the automated '
        + 'verification ' + verdictWord(v) + ' for this same question. '
        + 'Exporting this review raises a MATERIAL DISAGREEMENT that must '
        + 'be reconciled explicitly (evidence, rationale, reviewer) — '
        + 'nothing is averaged or overwritten.';
    } else {
      comparison.style.display = 'none';
      comparison.textContent = '';
    }
  }
  var choices = el('div');
  [['yes', 'Yes (full points)'], ['no', 'No (zero)'],
   ['unresolved', 'Unresolved']].forEach(function (choice) {
    var label = el('label');
    var input = el('input', {'type': 'radio', 'name': 'answer-' + item.check});
    var draftAnswer = DRAFT && DRAFT.answers ? DRAFT.answers[item.check] : undefined;
    if ((draftAnswer === true && choice[0] === 'yes')
        || (draftAnswer === false && choice[0] === 'no')
        || (draftAnswer === 'unresolved' && choice[0] === 'unresolved')) {
      input.checked = true;
    }
    input.addEventListener('change', function () {
      if (choice[0] === 'yes') answers[item.check] = true;
      else if (choice[0] === 'no') answers[item.check] = false;
      else answers[item.check] = 'unresolved';
      refreshScore();
      updateComparison();
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(choice[1]));
    choices.appendChild(label);
  });
  box.appendChild(choices);
  box.appendChild(comparison);
  var noteInput = el('input', {'type': 'text',
                               'placeholder': 'optional note (kept private)'});
  noteInput.value = (DRAFT && DRAFT.notes && DRAFT.notes[item.check]) || '';
  noteInput.addEventListener('input', function () {
    if (noteInput.value) notes[item.check] = noteInput.value;
    else delete notes[item.check];
  });
  box.appendChild(noteInput);
  if (item.supplements.length) {
    var lines = ['Recorded mechanical evidence (supplements your judgment):'];
    item.supplements.forEach(function (key) {
      lines.push(key + ' = ' + fmt(CONTEXT.evidence[key]));
    });
    if (CONTEXT.automated.checks[item.check] !== undefined) {
      lines.push('automated verdict for this item: ' +
                 CONTEXT.automated.checks[item.check]);
    }
    box.appendChild(el('div', {'class': 'supplement'}, lines.join('\n')));
  }
  var disputeToggle = el('button', {'type': 'button'},
                         'Raise dispute (material disagreement)');
  var disputeFields = el('div');
  disputeFields.style.display = 'none';
  var claim = el('input', {'type': 'text', 'placeholder': 'claim'});
  var evidence = el('input', {'type': 'text', 'placeholder': 'evidence'});
  disputeToggle.addEventListener('click', function () {
    disputeFields.style.display =
      disputeFields.style.display === 'none' ? 'block' : 'none';
  });
  claim.addEventListener('input', syncDispute);
  evidence.addEventListener('input', syncDispute);
  // A dispute restored from the draft round-trip reopens its fields.
  var restored = disputes[item.check];
  if (restored) {
    disputeFields.style.display = 'block';
    claim.value = restored.claim;
    evidence.value = restored.evidence;
  }
  function syncDispute() {
    delete disputes[item.check];
    if (disputeFields.style.display !== 'none' && claim.value &&
        evidence.value) {
      disputes[item.check] = {check: item.check, claim: claim.value,
                              evidence: evidence.value};
    }
    refreshScore();
  }
  disputeFields.appendChild(claim);
  disputeFields.appendChild(evidence);
  box.appendChild(disputeToggle);
  box.appendChild(disputeFields);
  listPanel.appendChild(box);
});

var idInput = document.getElementById('reviewer-id');
var playedBox = document.getElementById('played-box');
var exportButton = document.getElementById('export-button');
if (DRAFT && DRAFT.reviewer) {
  idInput.value = DRAFT.reviewer.id || '';
  document.getElementById('reviewer-role').value = DRAFT.reviewer.role || '';
}
function refreshExport() {
  exportButton.disabled = !(VERIFIED && idInput.value.trim() && playedBox.checked);
}
idInput.addEventListener('input', refreshExport);
playedBox.addEventListener('change', refreshExport);
refreshExport();

exportButton.addEventListener('click', function () {
  var review = {
    schema: 'welp-heli-review/1',
    methodology: CONTEXT.binding.methodology,
    binding: CONTEXT.binding,
    reviewer: {id: idInput.value.trim()},
    played: playedBox.checked,
    answers: answers,
    notes: notes,
    disputes: Object.keys(disputes).map(function (k) { return disputes[k]; })
  };
  if (document.getElementById('reviewer-role').value.trim()) {
    review.reviewer.role = document.getElementById('reviewer-role').value.trim();
  }
  if (DRAFT && DRAFT.supersedes) {
    review.supersedes = DRAFT.supersedes;
  }
  var text = JSON.stringify(review, null, 2);
  var area = document.getElementById('export-area');
  area.value = text;
  var link = document.getElementById('download-link');
  link.href = URL.createObjectURL(new Blob([text], {'type': 'application/json'}));
  link.download = 'review.json';
  link.style.display = 'inline';
  link.textContent = 'download review.json';
});
</script>
</body>
</html>
'''


# --------------------------------------------------------------------------
# Import / reconcile


def import_review(campaign, review_path):
    """Validated publish of one saved reviewer file. Fail-closed on binding,
    schema, attribution and completeness inconsistencies; never mutates the
    finalized automated evidence."""
    section = _require_finalized_v3(campaign)
    candidate = _read_json_file(review_path)
    _revalidate_review(campaign, candidate)  # structure + exact re-binding
    path = operative_review_path(campaign)
    payload = candidate_bytes(candidate)
    with store.locked(campaign):
        # Re-read under the writer lock: supersession must preserve the
        # prior bytes BEFORE atomically replacing the operative draft.
        prior_bytes, prior_sha = _operative_review_bytes(campaign)
        superseded = None
        if prior_bytes is not None:
            prior = _validate_review(json.loads(prior_bytes))
            prior_state = status(campaign)['state']
            if prior_state == 'FINALIZED':
                raise policy.CheckError(
                    'heli-review.import: a FINALIZED review is immutable; a new '
                    'review under an accepted digest breaks acceptance binding '
                    'and is refused')
            if candidate.get('supersedes') != prior_sha:
                raise policy.CheckError(
                    'heli-review.import: an existing review is present; a '
                    'superseding review must carry supersedes = its exact '
                    f'SHA-256 ({prior_sha})')
            if (candidate.get('reviewer') or {}).get('id') != \
                    (prior.get('reviewer') or {}).get('id'):
                raise policy.CheckError(
                    'heli-review.import: supersession must carry the SAME '
                    'reviewer id as the superseded review')
            if _file_sha256(payload) == prior_sha:
                raise policy.CheckError(
                    'heli-review.import: this exact review is already imported')
            store.put(store_base(campaign) / 'superseded'
                      / f'review-{prior_sha}.json', prior_bytes)
            superseded = prior_sha
            # Atomic replace of the operative draft (prior already archived);
            # publish-if-absent cannot overwrite, so swap via rename.
            temp = path.with_name(f'.pending-review-{uuid.uuid4().hex}')
            with open(temp, 'xb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        else:
            store.put(path, payload)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return {'disposition': 'IMPORTED',
            'superseded': superseded,
            'review_sha256': review_sha_of(campaign),
            'state': status(campaign)['state'],
            'reviewer': (candidate.get('reviewer') or {}).get('id')}


def candidate_bytes(candidate):
    return json.dumps(candidate, ensure_ascii=False, sort_keys=True,
                      indent=1).encode('utf-8')


def review_sha_of(campaign):
    return review_digest(campaign)['review_sha256']


def reconcile(campaign, entry_path):
    """Append one explicit reconciliation record for an open dispute of the
    operative review. Evidence, rationale and reviewer are REQUIRED; the
    automated results and the review answers are never changed."""
    section = _require_finalized_v3(campaign)
    entry = _validate_reconciliation_entry(_read_json_file(entry_path),
                                           'reconcile')
    state = status(campaign)
    if state['state'] == 'NOT_IMPORTED':
        raise policy.CheckError(
            'heli-review.reconcile: no imported human review to reconcile')
    review_bytes, review_sha = _operative_review_bytes(campaign)
    if entry.get('review_sha256') not in (None, review_sha):
        raise policy.CheckError(
            'heli-review.reconcile: entry names a different review digest '
            f'({entry.get("review_sha256")}); the operative review is '
            f'{review_sha}')
    if entry['check'] not in state['open_disputes']:
        raise policy.CheckError(
            f'heli-review.reconcile: {entry["check"]} has no open dispute in '
            'the operative review; nothing to reconcile')
    if entry['check'] in [e.get('check') for e in _reconciliation_entries(campaign)
                          if e.get('review_sha256') == review_sha]:
        raise policy.CheckError(
            f'heli-review.reconcile: {entry["check"]} is already reconciled '
            'for the operative review')
    record = {'schema': RECONCILIATION_SCHEMA, 'check': entry['check'],
              'resolution': entry['resolution'], 'evidence': entry['evidence'],
              'rationale': entry['rationale'], 'reviewer': entry['reviewer'],
              'at': entry.get('at'), 'review_sha256': review_sha}
    path = store_base(campaign) / 'reconciliation.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    with open(path, 'ab') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True)
                     .encode('utf-8') + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    return {'disposition': 'RECONCILED', 'check': entry['check'],
            'resolution': entry['resolution'],
            'state': status(campaign)['state']}


def cli(args):
    campaign = args.campaign
    if args.action == 'status':
        return status(campaign)
    if args.action == 'prepare':
        return prepare(campaign)
    if args.action == 'play':
        return play(campaign, browser_binary=getattr(args, 'browser', None),
                    timeout_seconds=getattr(args, 'timeout', 3600.0),
                    headless=getattr(args, 'headless', False))
    if args.action == 'import':
        if not getattr(args, 'review', None):
            raise policy.CheckError('heli-review.import: --review required')
        return import_review(campaign, args.review)
    if args.action == 'reconcile':
        if not getattr(args, 'reconciliation', None):
            raise policy.CheckError(
                'heli-review.reconcile: --reconciliation required')
        return reconcile(campaign, args.reconciliation)
    raise policy.CheckError(f'heli-review: unknown action {args.action!r}')
