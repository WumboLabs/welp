"""Read-only AMD deployment adapter (installed ``amd-smi``), optional
boundary observer.

Not a safety admission tool and not a monitor. One invocation takes one
device-wide snapshot: it echoes the caller's nonce and reports the
declared device's whole-VRAM occupancy in the tool's documented native
unit, converted to bytes with the recorded factor. It never starts or
stops a GPU workload, never reads per-process memory, and never claims
an in-request peak; device attribution follows the caller's declared
pci_id only, and a foreign or absent device fails closed to unavailable
telemetry.

``amd-smi`` prints advisory text (for example card-node permission
notices) before its JSON document on stdout; the JSON suffix is parsed
explicitly. Observed shapes (amd-smi 26.2.0, read-only):

- ``amd-smi list --json``            → ``[{"gpu": 0, "bdf": "0000:03:00.0", ...}]``
- ``amd-smi metric -m --json -g BDF`` → ``{"gpu_data": [{"gpu": 0, "mem_usage":
  {"total_vram": {"value": 32624, "unit": "MB"}, "used_vram": {...}, ...}}]}``

Only the documented ``MB`` unit is accepted; anything else is refused
rather than guessed (fail closed). The runtime boundary contract is the
established JSON stdin/stdout interface shared with the NVIDIA adapter:
request ``{request_id, phase, pci_id}`` in, response
``{request_id, scope, source, observations}`` out, consumed by the
deployment-side observer command configured on the profile.
"""
import json
import socket
import subprocess
import sys
import time

AMD_SMI = 'amd-smi'
SUBPROCESS_TIMEOUT_SECONDS = 10
#: ``amd-smi metric --json`` documents memory as ``{'value': N, 'unit': 'MB'}``.
NATIVE_MEMORY_UNIT = 'MB'
#: Conversion applied to the documented native MB figure, verified on this
#: host against byte-counting authorities rather than assumed from the label:
#: ``amd-smi metric`` reported total_vram 32624 MB for the declared device
#: while the kernel sysfs counter ``mem_info_vram_total`` and
#: ``rocm-smi --showmeminfo vram --json`` both report 34,208,743,424 bytes,
#: and 32624 x 1048576 = 34,208,743,424 exactly — the tool's 'MB' is the
#: binary unit (whole-MB quantization, not a decimal megabyte). The native
#: value and unit are preserved beside the conversion in every observation.
BYTES_PER_NATIVE_UNIT = 1048576


def _json_document(text):
    """Parse the JSON document from output that may carry advisory text first."""
    for index, character in enumerate(text):
        if character not in '[{':
            continue
        try:
            return json.loads(text[index:])
        except ValueError:
            continue
    raise ValueError('amd-smi produced no JSON document (advisory-only output?)')


def _run(arguments):
    return subprocess.run([AMD_SMI, *arguments], capture_output=True, text=True,
                          timeout=SUBPROCESS_TIMEOUT_SECONDS, check=True)


def _byte_value(value):
    """A nonnegative native MB figure (integral) suitable for byte conversion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('amd-smi memory value is not a number')
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError('amd-smi memory value is not an integral MB figure')
        value = int(value)
    if value < 0:
        raise ValueError('amd-smi memory value is negative')
    return value


def _declared_gpu(pci_id):
    """Resolve the declared pci_id against the tool's own device inventory."""
    result = _run(['list', '--json'])
    document = _json_document(result.stdout)
    entries = document if isinstance(document, list) else []
    for entry in entries:
        if (isinstance(entry, dict) and isinstance(entry.get('bdf'), str)
                and entry['bdf'].lower() == pci_id.lower()):
            gpu_id = entry.get('gpu')
            if isinstance(gpu_id, bool) or not isinstance(gpu_id, int):
                raise ValueError('amd-smi list reports a malformed device id')
            return gpu_id
    raise ValueError(f'no amd-smi device with BDF {pci_id}')


def _metric_memory(pci_id):
    """(gpu_id, used_vram_block, total_vram_block) for the declared device."""
    result = _run(['metric', '-m', '--json', '-g', pci_id])
    document = _json_document(result.stdout)
    entries = document.get('gpu_data') if isinstance(document, dict) else None
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError('amd-smi metric did not return exactly one requested device')
    gpu_id = entries[0].get('gpu')
    if isinstance(gpu_id, bool) or not isinstance(gpu_id, int):
        raise ValueError('amd-smi metric reports a malformed device id')
    memory = entries[0].get('mem_usage')
    if not isinstance(memory, dict):
        raise ValueError('amd-smi metric reports no mem_usage block')
    used, total = memory.get('used_vram'), memory.get('total_vram')
    if (not isinstance(used, dict) or not isinstance(total, dict)
            or used.get('unit') != NATIVE_MEMORY_UNIT
            or total.get('unit') != NATIVE_MEMORY_UNIT):
        raise ValueError(f'unsupported amd-smi memory unit; the documented '
                         f'unit is {NATIVE_MEMORY_UNIT}')
    return gpu_id, used, total


def collect(pci_id):
    """One device-wide VRAM observation for the declared device; raises on any
    failure (absent/foreign device, unsupported unit, malformed output) so the
    boundary caller records unavailable telemetry — never a zero."""
    started = time.time()
    listed_gpu = _declared_gpu(pci_id)
    metric_gpu, used, total = _metric_memory(pci_id)
    if listed_gpu != metric_gpu:
        raise ValueError('amd-smi device identity disagreed between list and metric')
    return {
        'request_meta': {'gpu_id': metric_gpu, 'bdf': pci_id,
                         'sample_started_epoch': started,
                         'sample_ended_epoch': time.time()},
        'device': {
            'pci_id': pci_id,
            'vram_used_bytes': _byte_value(used.get('value')) * BYTES_PER_NATIVE_UNIT,
            'native_used_vram_mb': used.get('value'),
            'native_total_vram_mb': total.get('value'),
            'native_unit': NATIVE_MEMORY_UNIT,
        },
    }


def main():
    request = json.load(sys.stdin)
    pci_id = request.get('pci_id') if isinstance(request, dict) else None
    if not isinstance(pci_id, str) or not pci_id:
        raise ValueError('observation request requires the declared device pci_id')
    measured = collect(pci_id)
    print(json.dumps({
        'request_id': request.get('request_id'),
        'scope': 'device-wide',
        'source': {
            'collector': AMD_SMI,
            'subcommands': ['list --json', 'metric -m --json -g <bdf>'],
            'gpu_id': measured['request_meta']['gpu_id'],
            'bdf': pci_id,
            'host': socket.gethostname(),
            'sample_started_epoch': measured['request_meta']['sample_started_epoch'],
            'sample_ended_epoch': measured['request_meta']['sample_ended_epoch'],
            'memory_unit': 'amd-smi native MB figure converted to bytes '
                           f'({BYTES_PER_NATIVE_UNIT} bytes per reported MB unit); '
                           'native value and unit preserved on the device entry',
            'scope_note': 'device-wide VRAM occupancy; not a model-process '
                          'allocation and not an in-request peak; no per-process '
                          'memory is read',
        },
        'observations': {'devices': [measured['device']]},
    }))


if __name__ == '__main__':
    main()
