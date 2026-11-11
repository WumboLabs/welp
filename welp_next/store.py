"""Append-only attempt files; all progress is reconstructed from committed evidence."""
import contextlib
import fcntl
import json
import os
import time
from pathlib import Path
import uuid

from . import policy


def read_json(path):
    try:
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise policy.CheckError(f"evidence.{path}: {exc}") from exc


def put(path, data):
    """Durable publish-if-absent; never replace an original observation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.pending-' + uuid.uuid4().hex)
    try:
        with temp.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def put_json(path, value):
    put(path, policy.canonical(value) + b'\n')


@contextlib.contextmanager
def locked(campaign):
    campaign = Path(campaign)
    campaign.mkdir(parents=True, exist_ok=True)
    with (campaign / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise policy.CheckError('campaign.lock: another writer is active') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def append_event(section, event):
    line = policy.canonical(event) + b'\n'
    with (Path(section) / 'units.jsonl').open('ab', buffering=0) as stream:
        stream.write(line)
        os.fsync(stream.fileno())


def attempts(section, unit_id):
    root = Path(section) / 'evidence' / unit_id
    rows = []
    if not root.exists():
        return rows
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith('.'):
            continue
        if preparation_only(path):
            continue
        if not (path / 'attempt.json').exists():
            conditions = read_json(path / 'conditions.json') if (path / 'conditions.json').exists() else {}
            rows.append({'attempt_id': path.name, 'unit_id': unit_id,
                         'finalized': False, 'path': str(path),
                         'fatal_device_condition': conditions.get('fatal_device_condition', False)})
            continue
        if not policy.evidence_complete(path):
            raise policy.CheckError(f'evidence.complete: corrupt finalized attempt {path}')
        row = read_json(path / 'score.json')
        row.update(finalized=True, path=str(path))
        if row.get('unit_id') != unit_id or row.get('attempt_id') != path.name:
            raise policy.CheckError(f'evidence.identity: {path}')
        rows.append(row)
    return rows


def inventory(section):
    config = read_json(Path(section) / 'run.json')
    result = {uid: attempts(section, uid) for uid in config['unit_ids']}
    for rows in result.values():
        for row in rows:
            if row.get('finalized'):
                conditions = read_json(Path(row['path']) / 'conditions.json')
                if config.get('admission_version') == policy.ADMISSION_VERSION:
                    policy.recorded_profile(config, conditions)
                elif row.get('profile_revision') != config['profile_revision']:
                    raise policy.CheckError('evidence.profile_revision: mixed configuration')
    return config, result


def new_attempt(section, unit_id, *, preparing=False):
    root = Path(section) / 'evidence' / unit_id
    root.mkdir(parents=True, exist_ok=True)
    children = sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit())
    if preparing:
        failures = [p for p in children if preparation_only(p)]
        if len(failures) >= 3:
            raise policy.CheckError('preparation.limit: three setup failures; review before further setup')
        # The 180-second window bounds the CURRENT setup-retry streak.
        # Rapid retries within the window are bounded exactly as before
        # (allowed while the streak is young, never extended past it). A
        # streak that has EXPIRED (the latest preparation-only failure is
        # itself older than the window) means the environment changed since
        # the last failure: one fresh setup attempt starts a new streak.
        # The former rule measured the first failure forever, permanently
        # locking legitimate resume-after-environment-repair. Corrected
        # 2026-11-09 (gemma-4-12b campaign: a transient warmup connection
        # reset during context construction permanently blocked the unit's
        # setup window).
        if failures:
            first_epoch = read_json(failures[0] / 'trial-boundary.json')['epoch']
            latest_epoch = read_json(failures[-1] / 'trial-boundary.json')['epoch']
            now = time.time()
            streak_active = now - latest_epoch <= 180
            streak_expired = now - first_epoch > 180
            if streak_active and streak_expired:
                raise policy.CheckError(
                    'preparation.deadline: an active setup-retry streak has exceeded '
                    'the original 180-second setup window; environment review required')
    number = max((int(p.name) for p in children), default=0) + 1
    path = root / f'{number:04d}'
    path.mkdir()
    if preparing:
        put_json(path / 'trial-boundary.json', {'accounting': policy.ATTEMPT_ACCOUNTING, 'epoch': time.time()})
    return path


def preparation_only(path):
    """Only prospective directories have this boundary; historical counts stand."""
    path = Path(path)
    return ((path / 'trial-boundary.json').exists() and not (path / 'attempt.json').exists()
            and not any(path.glob('generation-*-intent.json')))


def generation_intent(path, request):
    """Durable BEFORE possible dispatch. Unknown sends remain original trials."""
    path = Path(path)
    number = len(list(path.glob('generation-*-intent.json'))) + 1
    put_json(path / f'generation-{number:04d}-intent.json',
             {'request': request, 'epoch': time.time(), 'accounting': policy.ATTEMPT_ACCOUNTING})
    if number == 1 and path.parent.parent.name == 'evidence':
        append_event(path.parents[2], {'event':'STARTED','unit_id':path.parent.name,
            'attempt_id':path.name,'at':time.time(),'accounting':policy.ATTEMPT_ACCOUNTING})


def preparation_failures(section):
    return [str(p.parent) for p in sorted((Path(section) / 'evidence').glob('*/*/trial-boundary.json'))
            if preparation_only(p.parent)]


def check_preparation(section):
    """Bound consecutive endpoint setup failures without consuming model trials."""
    failures = []
    for row in reversed(admission_records(section)):
        if row.get('ok') is not False:
            break
        failures.append(row)
    if len(failures) >= 3:
        raise policy.CheckError('preparation.limit: three failed admissions; environment review required')


def finalize_attempt(path, score, methodology=None):
    """Commit an attempt. ``methodology=None`` keeps the historical M1 core-4
    commitment exactly; a methodology pin commits EVERY file present in the
    attempt directory except attempt.json itself (all auxiliary evidence is
    hash-bound: preparation, per-exchange, reconstruction, repetitions, GPU
    snapshots). Missing/extra auxiliary files invalidate the attempt."""
    if preparation_only(path):
        put_json(Path(path) / 'setup-result.json',
                 {'classification': 'PREPARATION_FAILURE', 'model_trial': False,
                  'error': score.get('stop_reason', score.get('cause', score.get('reason'))),
                  'profile_revision': score['profile_revision']})
        return False
    if methodology is None and (Path(path) / 'trial-boundary.json').exists():
        methodology = policy.METHODOLOGY
    put_json(path / 'score.json', score)
    if methodology is None:
        files = {name: policy.file_sha(path / name) for name in
                 ('request.json', 'response.raw', 'conditions.json', 'score.json')}
    else:
        files = {p.name: policy.file_sha(p) for p in sorted(path.iterdir())
                 if p.is_file() and p.name != 'attempt.json'}
    record = {'finalized': True, 'unit_id': score['unit_id'],
              'attempt_id': score['attempt_id'], 'profile_revision': score['profile_revision'],
              'files': files}
    if methodology is not None:
        record['methodology'] = methodology
    put_json(path / 'attempt.json', record)
    if not policy.evidence_complete(path):
        raise policy.CheckError(f'evidence.complete: producer failed {path}')


def section_path(campaign):
    return Path(campaign) / 'sections' / 'baseline'


def admission_records(section):
    root = Path(section) / 'admission'
    return [read_json(path) for path in sorted(root.glob('*.json'))]


def record_admission(section, value):
    root = Path(section) / 'admission'
    number = max((int(p.stem) for p in root.glob('*.json')), default=0) + 1
    put_json(root / f'{number:04d}.json', value)
