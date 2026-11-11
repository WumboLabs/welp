"""CPU-only SOFTWARE_TEST protocol observations. No SSH or GPU is contacted."""
import copy
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import signal
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
import test_agentic as core
import test_calibration as calibration_tests
import test_remote_diagnostic as diagnostic_tests
from welp_next import agentic, calibration, diagnostic, policy, store


class NativeEndpoint:
    """Small native-protocol peer for the existing diagnostic CLI, not inference."""
    def __init__(self):
        self.profile = None
        self.requests = []
        self.mode = 'normal'
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def reply(self, value):
                raw = policy.canonical(value)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                p = owner.profile
                model = 'wrong-model' if owner.mode == 'wrong-model' else p['runtime']['serve']['model_id']
                if self.path == '/models':
                    return self.reply({'data':[{'id':model}]})
                template = Path(p['model']['tokenizer_chat_template']['path']).read_text()
                if owner.mode == 'wrong-template': template += 'changed'
                self.reply({'model_alias':model, 'model_path':'/operator/current/model.gguf',
                    'chat_template':template, 'build_info':'ordinary-updated-build',
                    'default_generation_settings':{'n_ctx':p['runtime']['context_capacity'],
                                                   'params':policy.sampling_settings(p)}})
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/apply-template':
                    on = body.get('chat_template_kwargs', {}).get('enable_thinking')
                    return self.reply({'prompt':json.dumps(body) + ('<think>\n' if on else '<think>\n\n</think>\n\n')})
                if self.path == '/tokenize': return self.reply({'tokens':[1,2,3]})
                owner.requests.append(copy.deepcopy(body))
                content, finish, calls = 'READY', 'stop', None
                if body['max_tokens'] == 1:
                    content, finish = '', 'length'
                elif body.get('tools'):
                    tool_messages = [m for m in body['messages'] if m['role'] == 'tool']
                    if len(tool_messages) < 2:
                        path = 'missing.txt' if not tool_messages else 'receipt.txt'
                        name = 'unsupported_interface' if owner.mode == 'unsupported-tools' else 'read_file'
                        calls = [{'id':'original-'+str(len(tool_messages)), 'type':'function',
                                  'function':{'name':name,'arguments':json.dumps({'path':path})}}]
                        content, finish = '', 'tool_calls'
                    else: content = 'qualified-native-tool'
                message = {'role':'assistant','content':content,'reasoning_content':'SOFTWARE_TEST reasoning'}
                if calls: message['tool_calls'] = calls
                self.reply({'model':body['model'], 'system_fingerprint':'ordinary-updated-build',
                    'choices':[{'message':message,'finish_reason':finish}],
                    'usage':{'prompt_tokens':3,'completion_tokens':1,'total_tokens':4},
                    'timings':{'predicted_n':1},'__verbose':{'tokens_predicted':1,'tokens':[42],'truncated':False}})
        self.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()


class LeanAdmissionCLI(unittest.TestCase):
    def setUp(self):
        self.work = support.make_workdir('lean-admission')
        self.addCleanup(shutil.rmtree, self.work, True)

    def diagnostic(self, backend='CUDA'):
        endpoint = NativeEndpoint(); self.addCleanup(endpoint.close)
        profile, _ = diagnostic_tests.fixture(self.work)
        profile['runtime']['serve']['endpoint'] = endpoint.url
        profile['runtime']['backend'] = backend
        endpoint.profile = profile
        return endpoint, profile

    def invoke(self, profile, *args):
        path = support.write_profile(self.work, profile)
        result = support.cli([*args, '--profile', path, '--json'])
        return result, support.cli_json(result)

    def test_package_updates_and_new_server_incarnation_do_not_invalidate_inference(self):
        endpoint, profile = self.diagnostic()
        # Owner-supplied historical metadata is intentionally stale. No executable
        # or host process is part of WELP's model-facing protocol admission.
        profile['deployment'].update(ssh_sha256='0'*64, boot_id_sha256='1'*64,
            library_sha256={'/ordinary/updated/library.so':'2'*64})
        profile['runtime']['engine'].update(version='historical-build',sha256='3'*64)
        profile['runtime']['serve']['pid'] = 99999999
        profile['environment'] = {'kernel':'new-kernel','ssh_version':'new-package'}
        result, state = self.invoke(profile, 'run', '--section', 'diagnostic')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(state['state'], 'COMPLETED')
        self.assertEqual(len(endpoint.requests), 5)
        target = diagnostic.section_path(profile['campaign_root'])
        recorded = store.read_json(target/'evidence/natural-completion/0001/conditions.json')
        self.assertEqual(recorded['profile']['environment'], profile['environment'])
        self.assertNotIn('process', recorded['preflight']['echo'])
        endpoint.close()
        report = support.cli(['report','--section','diagnostic','--campaign',profile['campaign_root'],'--json'])
        receipt = support.cli_json(report)
        self.assertTrue(receipt['technical_checks_pass'], report.stdout)
        self.assertFalse(receipt['scientific_credit'])
        self.assertEqual(receipt['units']['length-exhaustion']['reason'],'BUDGET_LIMITED')

    def test_local_hip_uses_the_same_scientific_protocol_without_os_audits(self):
        endpoint, profile = self.diagnostic('HIP')
        profile.pop('deployment'); profile.pop('qualification'); profile.pop('hardware')
        profile['runtime']['engine'].pop('path'); profile['runtime']['engine'].pop('sha256')
        profile['runtime']['serve'].pop('pid')
        result, state = self.invoke(profile, 'run', '--section','diagnostic')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(state['units']['native-tool-feedback']['outcome'],'PASS')
        self.assertEqual(endpoint.requests[-1]['messages'][-1]['tool_call_id'],'original-1')

    def test_wrong_model_and_template_block_before_any_generation(self):
        endpoint, profile = self.diagnostic()
        for mode in ('wrong-model','wrong-template'):
            endpoint.mode = mode
            result, state = self.invoke(profile,'run','--section','diagnostic')
            self.assertEqual(result.returncode,2,result.stdout)
            self.assertEqual(state['disposition'],'BLOCKED')
            self.assertEqual(endpoint.requests,[])
            self.assertEqual(store.attempts(diagnostic.section_path(profile['campaign_root']),'natural-completion'),[])

    def test_unsupported_native_tool_protocol_is_invalid_not_semantic_failure(self):
        endpoint, profile = self.diagnostic(); endpoint.mode = 'unsupported-tools'
        result, state = self.invoke(profile,'run','--section','diagnostic')
        self.assertEqual(result.returncode,130,result.stdout)
        row = state['units']['native-tool-feedback']
        self.assertEqual(row['outcome'],'INVALID')
        self.assertIn('UNSUPPORTED_TOOL_ARGUMENTS',row['integration_error'])
        self.assertFalse(row['scientific_credit'])

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_setup_failure_then_restarted_endpoint_uses_original_cell_without_extra_trial(self):
        endpoint = calibration_tests.NativeSoftwareEndpoint(); self.addCleanup(endpoint.close)
        config = calibration_tests.pair(self.work, 'http://127.0.0.1:1')
        profile = config['profiles']['A']; campaign = profile['campaign_root']
        config_path = self.work/'calibration.json'; config_path.write_bytes(policy.canonical(config))
        prepared,_ = self.invoke(profile,'run','--section','calibration','--calibration-config',config_path,'--prepare')
        self.assertEqual(prepared.returncode,130,prepared.stdout)
        failed, state = self.invoke(profile,'run','--section','calibration','--calibration-config',config_path)
        self.assertEqual(state['consumed_slots'],0,failed.stdout)
        self.assertEqual(state['next_cell']['slot'],1)
        self.assertEqual(len(state['preparation_failures']),1)
        failed_path = Path(state['preparation_failures'][0])
        self.assertFalse((failed_path/'score.json').exists())
        self.assertFalse((failed_path/'attempt.json').exists())
        self.assertEqual(store.read_json(failed_path/'setup-result.json')['classification'],'PREPARATION_FAILURE')
        target = calibration.section_path(campaign)
        events = support.read_events(target) if (target/'units.jsonl').exists() else []
        self.assertEqual([e for e in events if e['event']=='STARTED'], [])
        for p in config['profiles'].values():
            p['runtime']['serve']['endpoint'] = endpoint.url
            p['runtime']['engine']['version'] = 'ordinary-new-runtime-build'
            p['environment'] = {'os':'updated','ssh_sha256':'changed'}
        endpoint.profile = profile
        endpoint.readiness_script = [('list_dir',{'path':'/workspace'}),
            ('read_file',{'path':'formatters.py'}),
            ('write_file',{'path':'formatters.py','content':core.QUAL_REFERENCE_FORMATTERS}),
            ('run',{'command':'./run_tests.sh'}),('finish',{'report':'Tests pass.'})]
        result, state = self.invoke(profile,'resume','--section','calibration','--campaign',campaign)
        self.assertEqual(state['consumed_slots'],1,result.stdout+result.stderr)
        row = next(value for value in state['units'].values() if value)
        self.assertEqual(row['outcome'],'PASS',row)
        self.assertEqual(row['attempt_id'],'0002')
        self.assertFalse(row['scientific_credit'])
        self.assertEqual(len(endpoint.calls),5)
        self.assertTrue(json.loads(endpoint.calls[1]['messages'][-1]['content'])['ok'])
        target = calibration.section_path(campaign)
        starts = [e for e in support.read_events(target) if e['event']=='STARTED']
        self.assertEqual([(e['unit_id'],e['attempt_id']) for e in starts], [(row['unit_id'],'0002')])
        calibration._stop(target,'SOFTWARE_TEST_ONLY_STOP')
        endpoint.close()
        result = support.cli(['report','--section','calibration','--campaign',campaign,'--json'])
        receipt = support.cli_json(result)
        self.assertEqual(receipt['consumed_slots'],1,result.stdout)
        self.assertEqual(receipt['charged']['turns'],5)
        self.assertEqual(receipt['charged']['task_seconds'],180)
        again = support.cli(['report','--section','calibration','--campaign',campaign,'--json'])
        self.assertEqual(support.cli_json(again),receipt)
        (Path(row['path'])/'response.raw').write_bytes(b'tampered calibration evidence')
        rejected = support.cli(['report','--section','calibration','--campaign',campaign,'--json'])
        self.assertEqual(rejected.returncode,2,rejected.stdout)

    def test_repeated_unavailable_endpoint_setup_is_finite_without_model_trials(self):
        config = calibration_tests.pair(self.work)
        profile = config['profiles']['A']
        config_path = self.work/'calibration.json'; config_path.write_bytes(policy.canonical(config))
        self.invoke(profile,'run','--section','calibration','--calibration-config',config_path,'--prepare')
        for _ in range(3):
            _, state = self.invoke(profile,'run','--section','calibration','--calibration-config',config_path)
            self.assertEqual(state['consumed_slots'],0)
        fourth, blocked = self.invoke(profile,'run','--section','calibration','--calibration-config',config_path)
        self.assertEqual(fourth.returncode,2,fourth.stdout)
        self.assertIn('preparation.limit',blocked['check'])
        self.assertEqual(calibration.status(profile['campaign_root'])['consumed_slots'],0)

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_unconfirmed_generation_consumes_original_slot_and_cannot_be_replaced(self):
        endpoint = calibration_tests.NativeSoftwareEndpoint(); self.addCleanup(endpoint.close)
        config = calibration_tests.pair(self.work,endpoint.url)
        profile = config['profiles']['A']; endpoint.profile = profile; endpoint.generation_delay = 2
        config_path = self.work/'calibration.json'; config_path.write_bytes(policy.canonical(config))
        profile_path = support.write_profile(self.work,profile)
        self.invoke(profile,'run','--section','calibration','--calibration-config',config_path,'--prepare')
        child = support.popen_cli(['run','--profile',profile_path,'--section','calibration','--calibration-config',config_path,'--json'])
        try:
            until = time.monotonic()+10
            while not endpoint.calls and time.monotonic()<until: time.sleep(.01)
            self.assertEqual(len(endpoint.calls),1)
            child.send_signal(signal.SIGKILL); child.communicate(timeout=5)
        finally:
            if child.poll() is None: child.kill(); child.communicate(timeout=5)
        state = calibration.status(profile['campaign_root'])
        self.assertEqual(state['consumed_slots'],1)
        result,_ = self.invoke(profile,'resume','--section','calibration','--campaign',profile['campaign_root'])
        self.assertEqual(result.returncode,2,result.stdout)
        state = calibration.status(profile['campaign_root'])
        row = next(v for v in state['units'].values() if v)
        self.assertEqual(row['stop_reason'],'INTERRUPTED_SLOT_CONSUMED')
        self.assertEqual(state['next_cell']['configuration'],'B')
        self.assertEqual(len(endpoint.calls),1)
        self.assertEqual(calibration._charged(calibration.section_path(profile['campaign_root']),
            calibration._load(profile['campaign_root'])[1])['tokens'],2048)


if __name__ == '__main__': unittest.main()
