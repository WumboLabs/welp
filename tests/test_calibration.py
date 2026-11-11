"""SOFTWARE_TEST only: disjoint oracles and the finite non-scored execution path."""
import copy
import json
import shutil
import signal
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
import test_agentic as core
from welp_next import agentic, calibration, context, diagnostic, policy, store


def pair(work, endpoint='http://127.0.0.1:1'):
    campaign = work/'campaign'
    a = support.build_profile(work, endpoint, campaign, max_tokens=4096, timeout_seconds=180)
    a['framework'] = {'version':policy.FRAMEWORK_M2, 'methodology':policy.METHODOLOGY_CALIBRATION}
    a['runtime']['context_capacity'] = 16384
    a['sampling']['qualification_source'] = str(Path(__file__).resolve())
    a['context']['target'] = 16384
    a['reasoning'] = {'arm':'ON','controls':{'chat_template_kwargs':{'enable_thinking':True}}}
    a['profile_id'] = a['profile_id'].replace('-off-', '-on-')
    b = copy.deepcopy(a)
    b['profile_id'] = b['profile_id'].replace('-on-', '-off-')
    b['reasoning'] = {'arm':'OFF','controls':{'chat_template_kwargs':{'enable_thinking':False}}}
    return {'budget_version':calibration.VERSION, 'evidence_kind':'SOFTWARE_TEST',
            'profiles':{'A':a,'B':b},'adapter':'native_tools'}


def queue_solution():
    src = (support.PROJECT_ROOT/'fixtures/agentic/calibration/repository/workspace/queue.py').read_text()
    return src.replace('return json.loads(STORE.read_text())',
        "if not STORE.exists(): return []\n    text = STORE.read_text().strip()\n    return json.loads(text) if text else []").replace(
        "return sorted(jobs, key=lambda j: j['ticket'])",
        "return sorted(jobs, key=lambda j: (bool(j['done']), {'high':0,'normal':1,'low':2}[j['priority']]))")


RESEARCH = ('Pending delivery retention: 72 hours\n'
            'Governing source: effective-directive-6\n'
            'Superseded on this point: policy-v1, policy-v2, policy-v3, faq\n'
            'Sources used: policy-v1, policy-v2, policy-v3, faq, governance, effective-directive-6\n')
SYSTEM_CONFIG = '{"port":8642,"log_level":"info","data_file":"data/catalog.json"}\n'


class FixtureOracles(unittest.TestCase):
    def execute(self, name, calls, **limits):
        work = core.workdir('calibration-oracle')
        self.addCleanup(shutil.rmtree, work, True)
        fixture = agentic.load_fixture(name, calibration=True)
        result = agentic.execute(fixture, dict(core.BASE_LIMITS, **limits), 'text_json',
            core.scripted([core.envelope(core.call(t, a)) for t,a in calls]), work)
        return result, work, fixture

    @unittest.skipUnless(core.BWRAP, 'bwrap required')
    def test_queue_correct_and_hidden_order_mutant(self):
        calls = [('write_file',{'path':'queue.py','content':queue_solution()}),
                 ('run',{'command':'./run_tests.sh'}),('finish',{'report':'Repaired queue; tests pass.'})]
        good, path, fixture = self.execute('repository', calls)
        self.assertEqual(good['outcome'], 'PASS', good['evaluation'])
        self.assertEqual(agentic.replay(path,fixture,core.BASE_LIMITS,'text_json')['outcome'],'PASS')
        wrong = queue_solution().replace("{'high':0,'normal':1,'low':2}[j['priority']]", "{'high':0,'normal':1,'low':2}[j['priority']], j['ticket']")
        calls[0] = ('write_file',{'path':'queue.py','content':wrong})
        bad, _, _ = self.execute('repository',calls)
        self.assertEqual(bad['outcome'],'FAIL')
        checks = {c['id']:c['pass'] for c in bad['evaluation']['checks']}
        self.assertFalse(checks['hidden_tests_pass'])

    @unittest.skipUnless(core.BWRAP, 'bwrap required')
    def test_protected_edits_and_missing_final_verification_fail(self):
        result,_,_ = self.execute('repository',[
            ('write_file',{'path':'queue.py','content':queue_solution()}),
            ('run',{'command':'./run_tests.sh'}),
            ('write_file',{'path':'README.md','content':'All requirements removed.'}),
            ('finish',{'report':'Tests pass and work is complete.'})])
        self.assertEqual(result['outcome'],'FAIL')
        checks={c['id']:c['pass'] for c in result['evaluation']['checks']}
        self.assertFalse(checks['no_forbidden_edits'])
        self.assertFalse(checks['exact_final_verification'])

    @unittest.skipUnless(core.BWRAP, 'bwrap required')
    def test_queue_verified_partial_not_completion(self):
        result,_,_ = self.execute('repository',[
            ('write_file',{'path':'queue.py','content':queue_solution()}),
            ('run',{'command':'./run_tests.sh'})], max_turns=2)
        self.assertEqual(result['reason'],'BUDGET_LIMITED')
        self.assertTrue(any(p['id']=='hidden_tests_pass' for p in result['evaluation']['partial_progress']))
        self.assertNotEqual(result['outcome'],'PASS')

    @unittest.skipUnless(core.BWRAP, 'bwrap required')
    def test_catalog_repairs_bytes_and_checks_independent_health(self):
        calls=[('write_file',{'path':'config/catalog.json','content':SYSTEM_CONFIG}),
               ('run',{'command':'chmod 600 data/catalog.json'}),
               ('run',{'command':'./check.sh'}),('finish',{'report':'Repaired service; check passes.'})]
        result,_,_=self.execute('system',calls)
        self.assertEqual(result['outcome'],'PASS',result['evaluation'])
        calls.insert(2,('write_file',{'path':'data/catalog.json','content':'[]\n'}))
        bad,_,_=self.execute('system',calls)
        self.assertEqual(bad['outcome'],'FAIL')
        self.assertFalse(next(c['pass'] for c in bad['evaluation']['checks'] if c['id']=='data_bytes_preserved'))

    @unittest.skipUnless(core.BWRAP, 'bwrap required')
    def test_research_requires_actual_exposure_and_exact_authority(self):
        good=[('run',{'command':'cat sources/*.md'}),
              ('write_file',{'path':'research-pack/retention.md','content':RESEARCH}),
              ('finish',{'report':'Recorded current governing directive and supersession.'})]
        result,_,_=self.execute('research',good)
        self.assertEqual(result['outcome'],'PASS',result['evaluation'])
        unexposed,_,_=self.execute('research',good[1:])
        self.assertEqual(unexposed['outcome'],'FAIL')
        self.assertFalse(next(c['pass'] for c in unexposed['evaluation']['checks'] if c['id']=='citations_exposed'))
        good[1]=('write_file',{'path':'research-pack/retention.md','content':RESEARCH.replace('72 hours','168 hours')})
        wrong,_,_=self.execute('research',good)
        self.assertEqual(wrong['outcome'],'FAIL')
        self.assertTrue(any(p['id']=='current_authority' for p in wrong['evaluation']['partial_progress']))


class Controls(unittest.TestCase):
    def setUp(self):
        self.work=core.workdir('calibration-controls')
        self.addCleanup(shutil.rmtree,self.work,True)
        self.config=pair(self.work)
        self.profile=self.config['profiles']['A']

    def test_fixed_inventory_envelope_and_protected_scored_sample(self):
        cells,fixtures=calibration.inventory(self.config)
        self.assertEqual([(c['task'],c['rung'],c['configuration']) for c in cells],
            [(n,r,a) for n in ('qualification','repository','system','research') for r in ('L','H') for a in ('A','B')])
        self.assertEqual(sum(c['limits']['total_tokens'] for c in cells),221184)
        self.assertEqual(sum(c['limits']['wall_seconds'] for c in cells),7920)
        self.assertEqual(sum(c['limits']['max_turns'] for c in cells),308)
        scored={agentic.load_fixture(n)['task_id'] for n in ('repository','system','research')}
        self.assertFalse(scored & {f['task_id'] for f in fixtures.values()})
        for replacement in ({'budget_version':'unapproved'}, {'adapter':'text_json'}, {'evidence_kind':'REAL_MODEL'}):
            with self.assertRaises(policy.CheckError):calibration.inventory(dict(self.config,**replacement))
        bad=copy.deepcopy(self.config);bad['profiles']['B']['sampling']['temperature']=0.7
        with self.assertRaises(policy.CheckError):calibration.inventory(bad)

    def test_reasoning_controls_cannot_be_replaced_by_labels(self):
        bad=copy.deepcopy(self.config);bad['profiles']['B']['reasoning']['controls']={}
        with self.assertRaises(policy.CheckError):calibration.inventory(bad)
        result={'outcome':'PASS','task_class':'qualification','non_scored':True,
                'evidence':{'kind':'SOFTWARE_TEST'},'calibration':True}
        self.assertFalse(agentic.readiness_admission(result)['admitted'])
        real=copy.deepcopy(self.config);real['evidence_kind']='CALIBRATION'
        with patch.object(calibration,'plan',return_value={}):
            with self.assertRaisesRegex(policy.CheckError,'NOT authorized'):
                calibration.run(self.profile,real)

    def test_native_meter_preserves_tools_history_controls_and_token_ids(self):
        body={'messages':[{'role':'user','content':'first'},{'role':'assistant','content':'earlier reasoning'}],
              'tools':agentic.TOOL_JSON_SCHEMAS,'tool_choice':'auto','max_tokens':4096}
        observed=[]
        def metadata(profile,path,payload):
            observed.append((path,copy.deepcopy(payload)))
            return {'prompt':'native full tools and history'} if path=='/apply-template' else {'tokens':[1,2,3]}
        with patch.object(context,'_post_json',side_effect=metadata):
            meter=context.measure_native_request(self.profile,body)
        self.assertEqual(observed[0][1]['tools'],agentic.TOOL_JSON_SCHEMAS)
        self.assertEqual(observed[0][1]['messages'],body['messages'])
        self.assertTrue(observed[0][1]['chat_template_kwargs']['enable_thinking'])
        self.assertEqual(meter['input_tokens'],3)
        with patch.object(context,'_post_json',side_effect=[{'prompt':'x'},{'tokens':[True]}]):
            with self.assertRaises(policy.CheckError):context.measure_native_request(self.profile,body)

    def setup_turn(self):
        cells,fixtures=calibration.inventory(self.config)
        target=calibration.section_path(self.profile['campaign_root'])
        path=store.new_attempt(target,cells[0]['id'])
        saved={'cells':cells,'fixtures':fixtures}
        body={'messages':[{'role':'user','content':'SOFTWARE_TEST'}],
              'tools':agentic.TOOL_JSON_SCHEMAS,'max_tokens':2048}
        return target,path,saved,cells[0],body

    def test_context_refusal_before_generation_and_initial_vs_growth(self):
        target,path,saved,cell,body=self.setup_turn()
        with patch.object(context,'measure_native_request',return_value={'input_tokens':12289}), \
             patch.object(calibration.runner,'_http_exchange') as http:
            one=calibration.exchange_turn(self.profile,body,180,path,target,saved,time.time(),cell)
            two=calibration.exchange_turn(self.profile,body,180,path,target,saved,time.time(),cell)
        self.assertEqual(one['calibration_stop'],'HARNESS_FAILURE')
        self.assertEqual(two['calibration_stop'],'CONTEXT_LIMIT')
        http.assert_not_called()

    def test_accounting_requires_native_agreement_and_unknown_reservation_is_charged(self):
        target,path,saved,cell,body=self.setup_turn()
        env=core.envelope('done',completion_tokens=4,prompt_tokens=32)
        env.update(model=self.profile['runtime']['serve']['model_id'],timings={'predicted_n':4},
                   __verbose={'tokens_predicted':4,'tokens':[1,2,3], 'truncated':False})
        with patch.object(context,'measure_native_request',return_value={'input_tokens':32}), \
             patch.object(calibration.runner,'_http_exchange',return_value={'status':200,'raw':json.dumps(env).encode(),'error':None}):
            result=calibration.exchange_turn(self.profile,body,180,path,target,saved,time.time(),cell)
        self.assertEqual(result['calibration_stop'],'HARNESS_FAILURE')
        self.assertEqual(calibration._charged(target,saved)['tokens'],2048)
        env['__verbose']['tokens'].append(4)
        self.assertTrue(diagnostic.native_accounting(env,2048))
        env['usage']['completion_tokens']=True
        self.assertFalse(diagnostic.native_accounting(env,2048))

    def test_interruption_consumes_slot_and_wrong_configuration_cannot_resume_it(self):
        calibration.run(self.profile,self.config,prepare=True)
        target,saved=calibration._load(self.profile['campaign_root'])
        cell=saved['cells'][0]
        path=store.new_attempt(target,cell['id'])
        calibration._interrupted(target,saved)
        state=calibration.status(self.profile['campaign_root'])
        self.assertEqual(state['consumed_slots'],1)
        self.assertEqual(state['next_cell']['configuration'],'B')
        self.assertEqual(state['units'][cell['id']]['outcome'],'INVALID')
        with self.assertRaisesRegex(policy.CheckError,'wrong deployment'):
            calibration.resume(self.profile['campaign_root'],self.profile,prepare=True)
        calibration._interrupted(target,saved)
        self.assertEqual(len(store.attempts(target,cell['id'])),1)

    def test_aggregate_and_preparation_deadlines_fail_closed(self):
        calibration.run(self.profile,self.config,prepare=True)
        target,saved=calibration._load(self.profile['campaign_root'])
        with self.assertRaises(policy.CheckError):
            calibration._assert_cost(target,saved,time.time()-17521)
        with patch.object(calibration.time,'time',return_value=time.time()+181):
            with self.assertRaisesRegex(policy.CheckError,'180second'):
                calibration.run(self.profile,self.config)
        self.assertTrue((target/'stop.json').exists())

    def test_representative_substitution_and_hardware_identity_fail_closed(self):
        original=agentic.load_fixture
        def changed(name, **kwargs):
            fixture=original(name,**kwargs)
            if name=='repository':fixture['task_prompt']='A caller-selected easier task.'
            return fixture
        with patch.object(agentic,'load_fixture',side_effect=changed):
            with self.assertRaisesRegex(policy.CheckError,'frozen representative'):
                calibration.inventory(self.config)
        identity=calibration.configuration_identity(self.profile)
        changed_profile=copy.deepcopy(self.profile)
        changed_profile['campaign_id']='different-routing'
        changed_profile['campaign_root']=str(self.work/'different-routing')
        changed_profile['runtime']['serve']['pid']=999
        self.assertEqual(calibration.configuration_identity(changed_profile),identity)


    def test_active_phase_deadline_interrupts_blocking_call(self):
        target,path,saved,cell,body=self.setup_turn()
        tiny=copy.deepcopy(cell);tiny['limits']['wall_seconds']=0.02
        clock=calibration.Clock(target,tiny,time.time())
        try:
            clock.phase('task')
            with self.assertRaises(calibration.Deadline):time.sleep(0.1)
        finally:clock.close()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))


class NativeSoftwareEndpoint:
    """Test-only native metadata/accounting protocol; never model science."""
    def __init__(self):
        self.profile = None
        self.slot = 1
        self.calls = []
        self.mode = 'normal'
        self.readiness_script = None
        self.metadata_delay = 0
        self.generation_delay = 0
        self.disconnected = 0
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def reply(self, value):
                raw = policy.canonical(value)
                try:
                    self.send_response(200); self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    owner.disconnected += 1  # expected when a deadline closes the test client
            def do_GET(self):
                if self.path == '/models':
                    return self.reply({'data':[{'id':owner.profile['runtime']['serve']['model_id']}]})
                echo=support.identity_echo(owner.profile)
                echo['sampling']=policy.sampling_settings(owner.profile)
                self.reply(echo)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path in ('/apply-template','/tokenize') and owner.metadata_delay:
                    time.sleep(owner.metadata_delay)
                if self.path == '/apply-template':
                    return self.reply({'prompt':json.dumps(body,sort_keys=True)})
                if self.path == '/tokenize':
                    return self.reply({'tokens':list(range((len(body['content'].encode())+3)//4))})
                owner.calls.append(copy.deepcopy(body))
                if owner.generation_delay:
                    time.sleep(owner.generation_delay)
                index=sum(m['role']=='assistant' for m in body['messages'])
                task=(owner.slot-1)//4
                if task==0:
                    script=[('write_file',{'path':'formatters.py','content':core.QUAL_REFERENCE_FORMATTERS}),
                            ('run',{'command':'./run_tests.sh'}),('finish',{'report':'Tests pass.'})]
                    if owner.readiness_script is not None:
                        script=owner.readiness_script
                elif task==1:
                    script=[('write_file',{'path':'queue.py','content':queue_solution()}),
                            ('run',{'command':'./run_tests.sh'}),('finish',{'report':'Tests pass.'})]
                elif task==2:
                    script=[('write_file',{'path':'config/catalog.json','content':SYSTEM_CONFIG}),
                            ('run',{'command':'chmod 600 data/catalog.json'}),
                            ('run',{'command':'./check.sh'}),('finish',{'report':'Check passes.'})]
                else:
                    script=[('run',{'command':'cat sources/*.md'}),
                            ('write_file',{'path':'research-pack/retention.md','content':RESEARCH}),
                            ('finish',{'report':'Recorded current authority.'})]
                if owner.slot==2:
                    script=[('finish',{'report':'I could not repair the task.'})]
                name,args=script[min(index,len(script)-1)]
                finish='length' if owner.slot==3 else 'tool_calls'
                n=body['max_tokens'] if finish=='length' else 1
                render={'messages':body['messages'],'add_generation_prompt':True,
                        **owner.profile['reasoning']['controls'],'tools':body['tools'],'tool_choice':body['tool_choice']}
                prompt=(len(json.dumps(render,sort_keys=True).encode())+3)//4
                env=core.envelope(tool_calls=[core.native_call('synthetic-'+str(len(owner.calls)),name,args)],
                                  finish_reason=finish,completion_tokens=n,prompt_tokens=prompt)
                env.update(model=body['model'],timings={'predicted_n':n},
                           __verbose={'tokens_predicted':n,'tokens':list(range(n)),'truncated':False})
                if owner.mode=='bad_accounting':env['__verbose']['tokens']=[]
                self.reply(env)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()


class CalibrationExecution(unittest.TestCase):
    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_native_synthetic_matrix_finalizes_offline_without_scientific_credit(self):
        work=core.workdir('calibration-execution')
        self.addCleanup(shutil.rmtree,work,True)
        endpoint=NativeSoftwareEndpoint(); self.addCleanup(endpoint.close)
        config=pair(work,endpoint.url)
        cells,_=calibration.inventory(config)
        campaign=config['profiles']['A']['campaign_root']
        for cell in cells:
            profile=config['profiles'][cell['configuration']]
            endpoint.profile=profile; endpoint.slot=cell['slot']
            calibration.run(profile,config,prepare=True)
            result=calibration.run(profile,config)
            self.assertEqual(result['consumed_slots'],cell['slot'])
            self.assertNotEqual(result['state'],'BLOCKED')
        calibration.resume(campaign,config['profiles']['B'],prepare=True)
        report=calibration.report(campaign)
        self.assertEqual(report['consumed_slots'],16)
        results=list(report['results'].values())
        self.assertEqual(results[0]['outcome'],'PASS')
        self.assertEqual(results[1]['outcome'],'FAIL')
        self.assertEqual(results[2]['outcome'],'NOT_EVALUABLE')
        self.assertTrue(all(r['scientific_credit'] is False for r in results))
        self.assertEqual(report['charged']['task_seconds'],7920)
        endpoint.close()
        self.assertEqual(calibration.report(campaign),report)
        self.assertEqual(calibration.resume(campaign),calibration.status(campaign))
        self.assertFalse((Path(campaign)/'sections/baseline').exists())

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_invalid_native_accounting_stops_without_replacement_and_reconstructs(self):
        work=core.workdir('calibration-invalid')
        self.addCleanup(shutil.rmtree,work,True)
        endpoint=NativeSoftwareEndpoint(); self.addCleanup(endpoint.close)
        config=pair(work,endpoint.url);profile=config['profiles']['A']
        endpoint.profile=profile;endpoint.mode='bad_accounting'
        calibration.run(profile,config,prepare=True)
        state=calibration.run(profile,config)
        self.assertEqual(state['state'],'BLOCKED')
        self.assertEqual(state['consumed_slots'],1)
        with self.assertRaises(policy.CheckError):calibration.resume(profile['campaign_root'],profile)
        receipt=calibration.report(profile['campaign_root'])
        self.assertEqual(next(iter(receipt['results'].values()))['outcome'],'INVALID')
        self.assertEqual(receipt['charged']['tokens'],2048)


if __name__=='__main__':unittest.main()
