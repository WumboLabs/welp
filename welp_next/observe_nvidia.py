"""Read-only NVIDIA deployment adapter, optionally over existing SSH access.

Not a safety admission tool or a monitor. It takes one device-wide snapshot per
invocation, echoes the caller's nonce, and never starts/stops a GPU workload.
"""
import argparse
import json
import shlex
import subprocess
import sys


COLLECTOR = r'''
import csv, io, json, socket, subprocess, sys, time
request = json.load(sys.stdin)
def query(fields, kind='gpu'):
    result = subprocess.run(['nvidia-smi', '--query-' + kind + '=' + fields,
                             '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, check=True, timeout=5)
    return list(csv.reader(io.StringIO(result.stdout), skipinitialspace=True))
def pci(value):
    domain, bus, slot = value.lower().split(':')
    return f'{int(domain, 16):04x}:{bus}:{slot}'
started = time.time()
gpus = query('pci.bus_id,uuid,memory.used')
by_uuid = {row[1]: row[0] for row in gpus}
devices = [{'pci_id': request['pci_id'], 'vram_used_bytes': int(row[2]) * 1024 * 1024}
           for row in gpus if pci(row[0]) == pci(request['pci_id'])]
processes = []
process_error = None
try:
    for row in query('pid,gpu_uuid,used_gpu_memory', 'compute-apps'):
        if len(row) == 3 and row[1] in by_uuid:
            processes.append({'pid': int(row[0]), 'pci_id': pci(by_uuid[row[1]]),
                              'reported_memory_bytes': int(row[2]) * 1024 * 1024
                                  if row[2].isdigit() else None})
except (subprocess.SubprocessError, ValueError) as exc:
    process_error = str(exc)
print(json.dumps({'request_id': request['request_id'], 'scope': 'device-wide',
    'source': {'collector': 'nvidia-smi', 'host': socket.gethostname(),
               'sample_started_epoch': started, 'sample_ended_epoch': time.time(),
               'memory_unit': 'MiB converted to bytes',
               'process_query_limitation': process_error,
               'process_attribution': 'context only; not model-specific allocation'},
    'observations': {'devices': devices, 'compute_processes': processes}}))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', help='Existing trusted SSH alias; no configuration changes')
    args = parser.parse_args(argv)
    request = json.load(sys.stdin)
    if args.ssh_host:
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ConnectTimeout=5', '--', args.ssh_host,
                   shlex.join(['python3', '-c', COLLECTOR])]
    else:
        command = [sys.executable, '-c', COLLECTOR]
    result = subprocess.run(command, input=json.dumps(request), capture_output=True,
                            text=True, timeout=20, check=True)
    sys.stdout.write(result.stdout)


if __name__ == '__main__':
    main()
