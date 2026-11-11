"""Optional deployment snapshots; no accelerator code or quality scoring.

Two synchronous samples bracket the whole performance attempt, including repeats.
Collector absence/failure is unavailable telemetry, never a model outcome. Legacy
snapshots remain readable under their recorded, pre-binding interpretation.
"""
import json
import math
from pathlib import Path
import subprocess
import time
import uuid
from datetime import datetime

from . import policy, store


NAMES = ('gpu-before.json', 'gpu-after.json')


def _valid_devices(observations):
    if not isinstance(observations, dict):
        return False
    devices = observations.get('devices')
    return isinstance(devices, list) and all(
        isinstance(d, dict) and isinstance(d.get('pci_id'), str) and
        type(d.get('vram_used_bytes')) is int and d['vram_used_bytes'] >= 0
        for d in devices)


def capture(profile, task, path, phase):
    config = (profile.get('deployment') or {}).get('observation')
    if config is None or task.get('category') != 'performance':
        return
    path = Path(path)
    request = {'request_id': uuid.uuid4().hex, 'phase': phase,
               'pci_id': (profile.get('hardware') or {}).get('device', {}).get('pci_id')}
    snapshot = {'schema_version': 1, 'kind': 'attempt_resource_observation',
                'binding': {'unit_id': task['id'], 'attempt_id': path.name,
                            'profile_revision': policy.digest(profile)},
                'phase': phase, 'request_id': request['request_id'],
                'scope': 'device-wide', 'sampling': 'one synchronous boundary sample',
                'started_epoch': time.time(), 'status': 'UNAVAILABLE',
                'observations': {'devices': []}}
    try:
        if not request['pci_id']:
            raise ValueError('hardware.device.pci_id is required for memory attribution')
        command = config['command']
        timeout = config.get('timeout_seconds', 10)
        if (not isinstance(command, list) or not command or
                any(not isinstance(x, str) or not x for x in command) or
                type(timeout) not in (int, float) or not math.isfinite(timeout) or
                not 0 < timeout <= 30):
            raise ValueError('observation requires argv and a timeout in (0, 30] seconds')
        result = subprocess.run(command, input=json.dumps(request), capture_output=True,
                                text=True, timeout=timeout, check=True)
        observed = json.loads(result.stdout)
        if (not isinstance(observed, dict) or observed.get('request_id') != request['request_id'] or
                observed.get('scope') != 'device-wide' or not observed.get('source') or
                not _valid_devices(observed.get('observations'))):
            raise ValueError('collector requires matching request identity, device-wide scope, source and byte observations')
        snapshot.update(status='OBSERVED', observations=observed['observations'],
                        source=observed['source'])
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
        snapshot['error'] = f'{type(exc).__name__}: {exc}'[:2048]
    snapshot['ended_epoch'] = time.time()
    store.put_json(path / f'gpu-{phase}.json', snapshot)


def read_snapshot(profile, path, name):
    """One shared attribution check for consumers and offline reconstruction."""
    path = Path(path)
    try:
        snapshot = json.loads((path / name).read_bytes())
    except (OSError, ValueError):
        return None
    bound = isinstance(snapshot, dict) and snapshot.get('kind') == 'attempt_resource_observation'
    if not bound:
        # A new deployment may not substitute unbound historical/environment data.
        if (profile.get('deployment') or {}).get('observation') is not None:
            raise policy.CheckError('observation.binding: unbound snapshot on observed deployment')
        return snapshot if isinstance(snapshot, dict) else None
    expected = {'unit_id': path.parent.name, 'attempt_id': path.name,
                'profile_revision': policy.digest(profile)}
    start, end = snapshot.get('started_epoch'), snapshot.get('ended_epoch')
    if (snapshot.get('schema_version') != 1 or snapshot.get('binding') != expected or
            name != f"gpu-{snapshot.get('phase')}.json" or
            snapshot.get('phase') not in ('before', 'after') or
            not isinstance(snapshot.get('request_id'), str) or
            not snapshot['request_id'] or snapshot.get('scope') != 'device-wide' or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in (start, end)) or
            end < start):
        raise policy.CheckError('observation.binding: foreign attempt or malformed snapshot')
    started = store.read_json(path / 'started.json')['started_at']
    conditions = store.read_json(path / 'conditions.json')
    lower = datetime.fromisoformat(started).timestamp()
    upper = datetime.fromisoformat(conditions['ended_at']).timestamp()
    if start < lower or end > upper:
        raise policy.CheckError('observation.window: snapshot outside the attempt')
    intents = sorted(path.glob('generation-*-intent.json'))
    if snapshot['phase'] == 'before' and intents:
        if end > store.read_json(intents[0])['epoch']:
            raise policy.CheckError('observation.window: before snapshot after dispatch')
    if snapshot['phase'] == 'after':
        request_start = datetime.fromisoformat(conditions['started_at']).timestamp()
        elapsed = conditions.get('elapsed_seconds')
        if isinstance(elapsed, (int, float)) and start + .001 < request_start + elapsed:
            raise policy.CheckError('observation.window: after snapshot before response')
    if snapshot.get('status') == 'UNAVAILABLE':
        if snapshot.get('observations') != {'devices': []}:
            raise policy.CheckError('observation.unavailable: unexpected measured data')
    elif (snapshot.get('status') != 'OBSERVED' or not snapshot.get('source') or
          not _valid_devices(snapshot.get('observations'))):
        raise policy.CheckError('observation.schema: malformed observed snapshot')
    return snapshot


def device_memory(profile, snapshot):
    """Whole-device bytes only; never attribute this total to a model process."""
    pci = (profile.get('hardware') or {}).get('device', {}).get('pci_id')
    if not pci or not snapshot or snapshot.get('status') == 'UNAVAILABLE':
        return None
    for device in (snapshot.get('observations') or {}).get('devices', []):
        value = device.get('vram_used_bytes')
        if device.get('pci_id') == pci and type(value) is int and value >= 0:
            return value
    return None
