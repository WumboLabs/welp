"""Optional AMD deployment adapter (observe_amd): advisory-tolerant amd-smi
JSON parsing, documented byte units with native figures preserved, source
attribution, fail-closed foreign/absent-device handling, and the shared
JSON stdin/stdout boundary contract. SOFTWARE_TEST only — no GPU work is
started, no per-process memory and no in-request peak is claimed."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from welp_next import observation, policy
from welp_next import observe_amd as amd
import support

ADVISORY = 'Permission needed to access required GPU device node(s):\n'

DEVICES = [
    {'gpu': 0, 'bdf': '0000:03:00.0',
     'uuid': 'cfff7551-0000-1000-80d6-c9601c85166d', 'kfd_id': 23334},
    {'gpu': 1, 'bdf': '0000:75:00.0',
     'uuid': '00ff13c0-0000-1000-8000-000000000000', 'kfd_id': 23335},
]

METRIC = {'gpu_data': [{'gpu': 0, 'mem_usage': {
    'total_vram': {'value': 32624, 'unit': 'MB'},
    'used_vram': {'value': 57, 'unit': 'MB'},
    'free_vram': {'value': 32567, 'unit': 'MB'}}}]}


def fake_amd_smi(work, metric_output):
    """An amd-smi stand-in on PATH: advisory text before the JSON document,
    exit 1 for an unknown device (the observed real tool behavior)."""
    binary = Path(work) / 'amd-smi'
    binary.write_text(
        f'#!{sys.executable}\n'
        'import json, sys\n'
        f'DEVICES = {DEVICES!r}\n'
        f'ADVISORY = {ADVISORY!r}\n'
        f'METRIC = {metric_output!r}\n'
        "args = sys.argv[1:]\n"
        "if 'list' in args:\n"
        "    print(ADVISORY + json.dumps(DEVICES))\n"
        "else:\n"
        "    bdf = args[args.index('-g') + 1]\n"
        "    if bdf not in {d['bdf'] for d in DEVICES}:\n"
        "        sys.stderr.write('device not found\\n')\n"
        "        raise SystemExit(1)\n"
        "    print(ADVISORY + json.dumps(METRIC))\n")
    binary.chmod(0o700)


def run_adapter(request, work, *, check=True):
    return subprocess.run(
        [sys.executable, '-m', 'welp_next.observe_amd'],
        input=json.dumps(request), capture_output=True, text=True, timeout=30,
        check=check, cwd=str(policy.PROJECT_ROOT),
        env={**os.environ, 'PATH': str(work) + os.pathsep + os.environ['PATH'],
             'PYTHONPATH': str(policy.PROJECT_ROOT)})


class JsonDocumentParsing(unittest.TestCase):
    def test_json_suffix_after_advisory_text(self):
        for prefix in (ADVISORY, '', 'warning lines\nmore warning\n'):
            document = amd._json_document(prefix + json.dumps(METRIC))
            self.assertEqual(document['gpu_data'][0]['mem_usage']['used_vram']['value'], 57)
        self.assertEqual(amd._json_document(ADVISORY + json.dumps(DEVICES)), DEVICES)

    def test_advisory_only_output_is_refused(self):
        with self.assertRaises(ValueError):
            amd._json_document(ADVISORY + 'no document follows\n')

    def test_byte_value_accepts_only_nonnegative_integral_figures(self):
        self.assertEqual(amd._byte_value(57), 57)
        self.assertEqual(amd._byte_value(59.0), 59)
        for bad in (True, None, '57', -1, 57.5):
            with self.assertRaises(ValueError):
                amd._byte_value(bad)


class ObserveAmdAdapter(unittest.TestCase):
    REQUEST = {'request_id': 'nonce-1', 'phase': 'before',
               'pci_id': '0000:03:00.0'}

    def setUp(self):
        self.work = support.make_workdir('observe-amd')
        fake_amd_smi(self.work, METRIC)

    def test_boundary_round_trip_with_documented_units_and_attribution(self):
        result = run_adapter(self.REQUEST, self.work)
        measured = json.loads(result.stdout)
        self.assertEqual(measured['request_id'], 'nonce-1')
        self.assertEqual(measured['scope'], 'device-wide')
        device = {'pci_id': '0000:03:00.0', 'vram_used_bytes': 57 * 1048576,
                  'native_used_vram_mb': 57, 'native_total_vram_mb': 32624,
                  'native_unit': 'MB'}
        self.assertEqual(measured['observations']['devices'], [device])
        # device-wide occupancy only: no process accounting, no peak claim
        self.assertNotIn('compute_processes', measured['observations'])
        self.assertEqual(sorted(measured['observations']),
                         ['devices'])
        self.assertEqual(sorted(device),
                         ['native_total_vram_mb', 'native_unit',
                          'native_used_vram_mb', 'pci_id', 'vram_used_bytes'])
        source = measured['source']
        self.assertEqual(source['collector'], 'amd-smi')
        self.assertEqual(source['bdf'], '0000:03:00.0')
        self.assertIn('memory_unit', source)
        self.assertIn('scope_note', source)
        self.assertTrue(source['sample_started_epoch'] <= source['sample_ended_epoch'])
        # the observation satisfies the established attribution contract
        self.assertTrue(observation._valid_devices(measured['observations']))
        self.assertEqual(observation.device_memory(
            {'hardware': {'device': {'pci_id': '0000:03:00.0'}}}, measured),
            57 * 1048576)
        # a foreign declared device is never attributed from this snapshot
        self.assertIsNone(observation.device_memory(
            {'hardware': {'device': {'pci_id': '0000:75:00.0'}}}, measured))
        self.assertIsNone(observation.device_memory(
            {'hardware': {'device': {'pci_id': '0000:99:00.0'}}}, measured))

    def test_foreign_or_absent_device_fails_closed(self):
        foreign = run_adapter({**self.REQUEST, 'pci_id': '0000:44:00.0'},
                              self.work, check=False)
        self.assertNotEqual(foreign.returncode, 0)
        self.assertEqual(foreign.stdout, '')
        self.assertIn('ValueError', foreign.stderr)

    def test_missing_declared_device_in_request_is_rejected(self):
        result = run_adapter({'request_id': 'nonce-2'}, self.work, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('declared device pci_id', result.stderr)

    def test_unsupported_memory_unit_is_refused_not_guessed(self):
        wrong_unit = json.loads(json.dumps(METRIC))
        block = wrong_unit['gpu_data'][0]['mem_usage']
        for entry in block.values():
            entry['unit'] = 'GB'
        fake_amd_smi(self.work, wrong_unit)
        result = run_adapter(self.REQUEST, self.work, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported amd-smi memory unit', result.stderr)

    def test_missing_memory_block_is_refused(self):
        fake_amd_smi(self.work, {'gpu_data': [{'gpu': 0}]})
        result = run_adapter(self.REQUEST, self.work, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('mem_usage', result.stderr)

    def test_advisory_only_stdout_is_refused(self):
        fake_amd_smi(self.work, 'total,used,free\n1,2,3')
        result = run_adapter(self.REQUEST, self.work, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no JSON document', result.stderr)

    def test_metric_device_id_disagreement_is_refused(self):
        # metric answers with a different gpu id than the list inventory:
        # the identity disagreement fails closed instead of attributing
        mismatched = json.loads(json.dumps(METRIC))
        mismatched['gpu_data'][0]['gpu'] = 7
        fake_amd_smi(self.work, mismatched)
        result = run_adapter(self.REQUEST, self.work, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('disagreed', result.stderr)

    def test_malformed_or_missing_device_id_is_refused(self):
        for metric_output in ({'gpu_data': [{'mem_usage': {
                'total_vram': {'value': 32624, 'unit': 'MB'},
                'used_vram': {'value': 57, 'unit': 'MB'}}}]},
                {'gpu_data': [{'gpu': 'zero', 'mem_usage': {
                    'total_vram': {'value': 32624, 'unit': 'MB'},
                    'used_vram': {'value': 57, 'unit': 'MB'}}}]}):
            fake_amd_smi(self.work, metric_output)
            result = run_adapter(self.REQUEST, self.work, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('malformed device id', result.stderr)


if __name__ == '__main__':
    unittest.main()
