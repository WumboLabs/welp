"""CPU-only SOFTWARE_TEST regressions for the authentic-calibration defects.

Real disposable files, HTTP client, bubblewrap loop and owned local processes;
no GPU, inference server, SSH connection or real-model observations.
"""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support
import test_agentic as core
import test_calibration as existing
import test_remote_diagnostic as remote_tests
from welp_next import agentic, calibration, context, policy, preflight, remote, runner, store


class RootFilesystem(unittest.TestCase):
    def setUp(self):
        self.work = core.workdir('root-filesystem')
        self.addCleanup(shutil.rmtree, self.work, True)
        self.workspace = self.work/'workspace'
        self.workspace.mkdir()
        (self.workspace/'child').mkdir()
        (self.workspace/'ordinary.txt').write_text('ordinary SOFTWARE_TEST content')
        (self.workspace/'child'/'nested.txt').write_text('nested')
        self.sandbox = SimpleNamespace(workspace=self.workspace)

    def call(self, tool, path, **kwargs):
        return agentic._execute_tool({'tool':tool,'args':dict(path=path,**kwargs)},self.sandbox)

    def test_supported_root_spellings_list_the_authorized_root(self):
        for spelling in ('.','./','/workspace','/workspace/','/workspace/.'):
            with self.subTest(path=spelling):
                self.assertEqual(self.call('list_dir',spelling),
                                 {'ok':True,'entries':['child/','ordinary.txt']})

    def test_child_listing_and_ordinary_read_still_work(self):
        self.assertEqual(self.call('list_dir','child')['entries'],['child/nested.txt'])
        self.assertEqual(self.call('read_file','/workspace/ordinary.txt')['content'],
                         'ordinary SOFTWARE_TEST content')

    def test_empty_root_and_directory_are_not_file_operations(self):
        original=(self.workspace/'ordinary.txt').read_bytes()
        for spelling in ('',' ','/workspace','.','child'):
            with self.subTest(path=spelling):
                self.assertFalse(self.call('read_file',spelling)['ok'])
                self.assertFalse(self.call('write_file',spelling,content='not allowed')['ok'])
        self.assertTrue(self.workspace.is_dir())
        self.assertEqual((self.workspace/'ordinary.txt').read_bytes(),original)
        self.assertFalse(self.call('list_dir','')['ok'])

    def test_traversal_absolute_and_symlink_components_never_escape(self):
        secret=self.work/'outside.txt';secret.write_text('outside sentinel')
        (self.workspace/'leaf-link').symlink_to(secret)
        (self.workspace/'ancestor-link').symlink_to(self.work,target_is_directory=True)
        for path in ('../outside.txt','child/../../outside.txt','/etc/passwd',
                     '/workspace/../outside.txt','leaf-link','ancestor-link/outside.txt'):
            with self.subTest(path=path):
                self.assertFalse(self.call('read_file',path)['ok'])
                self.assertFalse(self.call('write_file',path,content='overwrite')['ok'])
        self.assertFalse(self.call('list_dir','ancestor-link')['ok'])
        self.assertEqual(secret.read_text(),'outside sentinel')
        linked=self.work/'linked-root';linked.symlink_to(self.workspace,target_is_directory=True)
        self.sandbox.workspace=linked
        self.assertFalse(self.call('list_dir','/workspace')['ok'])

    def test_special_files_and_leaf_swap_are_no_follow_and_nonblocking(self):
        fifo=self.workspace/'pipe';os.mkfifo(fifo)
        for tool,args in (('read_file',{}),('write_file',{'content':'x'}),('list_dir',{})):
            self.assertFalse(self.call(tool,'pipe',**args)['ok'])
        outside=self.work/'outside.txt';outside.write_text('protected sentinel')
        original=agentic._resolve_under
        def swap(root,rel):
            target=original(root,rel)
            if rel=='ordinary.txt':
                target.unlink();target.symlink_to(outside)
            return target
        with patch.object(agentic,'_resolve_under',side_effect=swap):
            self.assertFalse(self.call('read_file','ordinary.txt')['ok'])
        self.assertEqual(outside.read_text(),'protected sentinel')

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_original_root_failure_then_inspect_repair_verify_finish(self):
        fixture=agentic.load_fixture('qualification')
        calls=[('list_dir',{'path':'/workspace'}),('list_dir',{'path':'.'}),
               ('read_file',{'path':'formatters.py'}),
               ('read_file',{'path':'tests/test_greet.py'}),
               ('write_file',{'path':'formatters.py','content':core.QUAL_REFERENCE_FORMATTERS}),
               ('run',{'command':'./run_tests.sh'}),('finish',{'report':'Tests pass.'})]
        path=self.work/'attempt'
        result=agentic.execute(fixture,core.BASE_LIMITS,'text_json',
            core.scripted([core.envelope(core.call(t,a)) for t,a in calls]),path)
        self.assertEqual(result['outcome'],'PASS',result.get('evaluation'))
        transcript=json.loads((path/'agentic-transcript.json').read_text())['transcript']
        observed=[v['observation'] for v in transcript if v['role']=='observation']
        self.assertTrue(all(v['ok'] for v in observed))
        self.assertIn('tests/',observed[0]['entries'])
        self.assertIn('missing the bold function',observed[2]['content'])
        self.assertTrue(next(c['pass'] for c in result['evaluation']['checks'] if c['id']=='no_forbidden_edits'))
        self.assertEqual(agentic.replay(path,fixture,core.BASE_LIMITS,'text_json')['outcome'],'PASS')


class Response(io.BytesIO):
    status=200
    headers={}
    def read1(self,n):return self.read(n)


class DeadlineControls(unittest.TestCase):
    def setUp(self):
        self.work=core.workdir('deadline-controls')
        self.addCleanup(shutil.rmtree,self.work,True)
        self.config=existing.pair(self.work)
        self.profile=self.config['profiles']['A']
        self.cell=calibration.inventory(self.config)[0][0]
        self.target=calibration.section_path(self.profile['campaign_root'])

    def clock(self,seconds):
        cell=copy.deepcopy(self.cell);cell['limits']['wall_seconds']=seconds
        clock=calibration.Clock(self.target,cell,time.time())
        self.addCleanup(clock.close)
        clock.phase('task')
        return clock

    def immediate(self,timeout=2):
        with patch.object(preflight,'open_request',return_value=Response(b'{"SOFTWARE_TEST":true}')):
            return runner._http_exchange(self.profile,{'stream':False},timeout)

    def test_immediate_http_preserves_and_eventually_enforces_outer_timer(self):
        clock=self.clock(.2)
        self.assertEqual(self.immediate()['status'],200)
        self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0],0)
        self.assertLessEqual(signal.getitimer(signal.ITIMER_REAL)[0],.2)
        with self.assertRaises(calibration.Deadline):time.sleep(.4)
        self.assertLessEqual(clock.deadline,time.monotonic())

    def test_http_exception_restores_enclosing_deadline(self):
        self.clock(.2)
        with patch.object(preflight,'open_request',side_effect=URLError('SOFTWARE_TEST unavailable')):
            result=runner._http_exchange(self.profile,{},2)
        self.assertIn('transport',result['error'])
        with self.assertRaises(calibration.Deadline):time.sleep(.4)

    def test_blocking_request_is_bounded_by_remaining_task_not_http_cap(self):
        clock=self.clock(.15)
        started=time.monotonic();allowances=[]
        def blocking(request,timeout):
            allowances.append(timeout);time.sleep(1)
            return Response(b'late')
        with patch.object(preflight,'open_request',side_effect=blocking):
            with self.assertRaises(calibration.Deadline):
                runner._http_exchange(self.profile,{},180)
        self.assertLess(time.monotonic()-started,.7)
        self.assertLessEqual(allowances[0],.15)
        self.assertLessEqual(clock.deadline,time.monotonic())

    def test_sequential_http_cannot_reset_original_180_second_deadline(self):
        now=[1000.0]
        with patch.object(time,'monotonic',side_effect=lambda:now[0]):
            clock=self.clock(180)
            original=clock.task_deadline
            for _ in range(3):
                now[0]+=50
                self.assertEqual(self.immediate()['status'],200)
                self.assertEqual(clock.task_deadline,original)
            self.assertEqual(original,1180)
            now[0]=1180
            with self.assertRaises(calibration.Deadline):clock.check()
            with self.assertRaises(calibration.Deadline):clock.phase('task')
            clock.close()

    def test_expiration_before_generation_sends_no_request_or_reservation(self):
        path=store.new_attempt(self.target,self.cell['id'])
        with patch.object(runner,'_http_exchange') as generated:
            with self.assertRaises(calibration.Deadline):
                calibration.exchange_turn(self.profile,{'max_tokens':2048},0,path,self.target,
                    {'cells':[self.cell]},time.time(),self.cell)
        generated.assert_not_called()
        self.assertFalse(list(path.glob('*reservation.json')))

    def test_native_metadata_consumes_the_same_task_window(self):
        now=[100.0]
        class Metadata(Response):
            def read(self,*args):
                now[0]=101.0
                return b'{"prompt":"late"}'
        with patch.object(time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(context.urllib.request,'urlopen',return_value=Metadata(b'')) as http:
            with self.assertRaises(TimeoutError):
                context._post_json(self.profile,'/apply-template',{},deadline=100.5)
        self.assertEqual(http.call_args.kwargs['timeout'],.5)

    def test_metadata_expiration_is_budget_not_semantic_or_harness_failure(self):
        path=store.new_attempt(self.target,self.cell['id'])
        now=[100.0]
        def metadata(*args,**kwargs):
            now[0]=101.0;raise TimeoutError('expired metadata')
        with patch.object(time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(context,'measure_native_request',side_effect=metadata), \
             patch.object(runner,'_http_exchange') as generated:
            with self.assertRaises(calibration.Deadline):
                calibration.exchange_turn(self.profile,{'max_tokens':2048},.5,path,self.target,
                    {'cells':[self.cell]},time.time(),self.cell)
        generated.assert_not_called()
        self.assertFalse(list(path.glob('*reservation.json')))

    def test_late_http_response_cannot_be_represented_as_in_budget(self):
        now=[100.0]
        class Late(Response):
            def read1(self,n):
                now[0]=102.0
                return super().read1(n)
        with patch.object(time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(preflight,'open_request',return_value=Late(b'original late bytes')):
            result=runner._http_exchange(self.profile,{},1)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['raw'],b'original late bytes')

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_actual_loop_bounds_native_metadata_and_generation_without_semantic_fail(self):
        for stage in ('metadata','generation'):
            with self.subTest(stage=stage):
                work=self.work/stage;work.mkdir()
                endpoint=existing.NativeSoftwareEndpoint();self.addCleanup(endpoint.close)
                config=existing.pair(work,endpoint.url);profile=config['profiles']['A']
                endpoint.profile=profile
                endpoint.metadata_delay=2 if stage=='metadata' else 0
                endpoint.generation_delay=2 if stage=='generation' else 0
                cell=copy.deepcopy(calibration.inventory(config)[0][0])
                cell['limits']['wall_seconds']=1
                clock=calibration.Clock(self.target,cell,time.time())
                path=work/'attempt';path.mkdir()
                def exchange(body,remaining):
                    return calibration.exchange_turn(profile,body,remaining,path,self.target,
                        {'cells':[cell]},time.time(),cell,clock=clock)
                started=time.monotonic()
                try:
                    result=agentic.execute(agentic.load_fixture('qualification'),
                        dict(core.BASE_LIMITS,wall_seconds=1,command_seconds=1),
                        'native_tools',exchange,path,phase=clock.phase)
                finally:clock.close()
                self.assertLess(time.monotonic()-started,2)
                self.assertEqual(result['reason'],'BUDGET_LIMITED')
                self.assertEqual(result['outcome'],'NOT_EVALUABLE')
                self.assertEqual(len(endpoint.calls),0 if stage=='metadata' else 1)
                self.assertEqual(agentic.replay(path,agentic.load_fixture('qualification'),
                    dict(core.BASE_LIMITS,wall_seconds=1,command_seconds=1),'native_tools')['outcome'],
                    'NOT_EVALUABLE')
                endpoint.close()

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_actual_tool_execution_cannot_outlive_task_or_start_another_turn(self):
        cell=copy.deepcopy(self.cell);cell['limits']['wall_seconds']=1
        clock=calibration.Clock(self.target,cell,time.time())
        path=self.work/'tool-attempt'
        ledger=[]
        exchange=core.scripted([core.envelope(core.call('run',{'command':'sleep 3'}))],ledger)
        limits=dict(core.BASE_LIMITS,wall_seconds=1,command_seconds=1)
        started=time.monotonic()
        try:
            result=agentic.execute(agentic.load_fixture('qualification'),limits,'text_json',
                exchange,path,phase=clock.phase)
        finally:clock.close()
        self.assertLess(time.monotonic()-started,2)
        self.assertEqual(result['reason'],'BUDGET_LIMITED')
        self.assertEqual(result['stop_reason'],'WALL_CLOCK_LIMIT')
        self.assertEqual(len(ledger),1)


class ObservationAndTeardown(unittest.TestCase):
    def setUp(self):
        self.work=core.workdir('observation-teardown')
        self.addCleanup(shutil.rmtree,self.work,True)
        self.remote_profile,self.echo=remote_tests.fixture(self.work)
        (self.work/'local').mkdir()
        self.config=existing.pair(self.work/'local')
        self.profile=self.config['profiles']['A']
        self.cell=calibration.inventory(self.config)[0][0]
        self.target=calibration.section_path(self.profile['campaign_root'])




    def child(self,code):
        proc=subprocess.Popen([sys.executable,'-B','-u','-c',code],stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,start_new_session=True)
        def cleanup():
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL)
            proc.communicate(timeout=3)
        self.addCleanup(cleanup)
        self.assertEqual(proc.stdout.readline().strip(),'OBSERVING')
        return proc,remote.process(proc.pid)

    def test_owned_runner_drains_pending_observation_before_server_teardown(self):
        proc,identity=self.child("import signal,time; signal.signal(signal.SIGINT,lambda *_:None); print('OBSERVING',flush=True); time.sleep(.25); print('DRAINED',flush=True)")
        receipt=remote.drain_owned_runner(proc,identity,2)
        self.assertTrue(receipt['quiescent']);self.assertFalse(receipt['forced'])
        self.assertIn('DRAINED',receipt['stdout'])
        self.assertIsNotNone(proc.poll())
        again=remote.drain_owned_runner(proc,identity,2)
        self.assertTrue(again['quiescent']);self.assertFalse(again['forced'])
        self.assertEqual(again['returncode'],receipt['returncode'])

    def test_teardown_timeout_only_quiesces_exact_owned_group(self):
        code="import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); print('OBSERVING',flush=True); time.sleep(30)"
        owned,identity=self.child(code);other,_=self.child(code)
        started=time.monotonic()
        receipt=remote.drain_owned_runner(owned,identity,.4)
        self.assertLess(time.monotonic()-started,1.5)
        self.assertTrue(receipt['forced']);self.assertTrue(receipt['quiescent'])
        self.assertEqual(receipt['failure_class'],'CONTROLLED_TEARDOWN_TIMEOUT')
        self.assertEqual(owned.returncode,-signal.SIGKILL)
        self.assertIsNone(other.poll())

    def test_changed_ownership_is_refused_without_signalling(self):
        owned,identity=self.child("import time; print('OBSERVING',flush=True); time.sleep(30)")
        identity['start_ticks']='wrong incarnation'
        with self.assertRaisesRegex(policy.CheckError,'ownership'):
            remote.drain_owned_runner(owned,identity,.2)
        self.assertIsNone(owned.poll())


class CalibrationRecovery(unittest.TestCase):
    def setUp(self):
        self.work=core.workdir('harness-calibration-recovery')
        self.addCleanup(shutil.rmtree,self.work,True)
        self.config=existing.pair(self.work)
        self.profile=self.config['profiles']['A']
        self.campaign=self.profile['campaign_root']

    def test_historical_true_switch_does_not_authorize_a_replacement(self):
        # The corrected campaign-bound activation record replaces the retired
        # module source-delta: a record binds ONE campaign and methodology.
        import support
        real=copy.deepcopy(self.config);real['evidence_kind']='CALIBRATION'
        support.write_activation(self.campaign, 'previous-approved-campaign',
                                 policy.METHODOLOGY_CALIBRATION,
                                 sections=('agentic-calibration',))
        with patch.object(preflight,'online') as admission, \
             patch.object(runner,'_http_exchange') as generation:
            with self.assertRaisesRegex(policy.CheckError,'NOT authorized'):
                calibration.run(self.profile,real,prepare=True)
        admission.assert_not_called();generation.assert_not_called()
        # a correctly bound record authorizes its own campaign only
        support.write_activation(self.campaign, self.profile['campaign_id'],
                                 policy.METHODOLOGY_CALIBRATION,
                                 sections=('agentic-calibration',))
        self.assertTrue(bool(policy.campaign_activation(
            self.campaign, self.profile['campaign_id'], policy.METHODOLOGY_CALIBRATION)))
        # no source-state mutation: the module carries no activation flags
        source = Path(calibration.__file__).read_text()
        self.assertNotIn('EXECUTION_AUTHORIZED', source)
        self.assertNotIn('AUTHORIZED_CAMPAIGN', source)

    def sealed_interruption(self):
        calibration.run(self.profile,self.config,prepare=True)
        target,saved=calibration._load(self.campaign)
        path=store.new_attempt(target,saved['cells'][0]['id'])
        calibration._interrupted(target,saved)
        calibration._stop(target,'SOFTWARE_TEST_STOP')
        report=calibration.report(self.campaign)
        return target,path,report

    def test_sealed_historical_attribution_survives_source_change_without_rescoring(self):
        target,path,report=self.sealed_interruption()
        before={str(p.relative_to(target)):policy.file_sha(p) for p in target.rglob('*') if p.is_file()}
        with patch.object(runner,'software_identity',return_value={'new-implementation':'f'*64}), \
             patch.object(agentic,'replay',side_effect=AssertionError('do not rescore history')):
            self.assertEqual(calibration.report(self.campaign),report)
            self.assertEqual(calibration.status(self.campaign)['consumed_slots'],1)
        after={str(p.relative_to(target)):policy.file_sha(p) for p in target.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(next(iter(report['results'].values()))['outcome'],'INVALID')

    def test_historical_source_tolerance_does_not_disable_tamper_detection(self):
        target,path,_=self.sealed_interruption()
        (path/'response.raw').write_bytes(b'tampered SOFTWARE_TEST raw evidence')
        with patch.object(runner,'software_identity',return_value={'new-implementation':'f'*64}):
            with self.assertRaisesRegex(policy.CheckError,'manifest.files'):
                calibration.report(self.campaign)

    def test_expired_original_preparation_is_not_revived_by_resume(self):
        calibration.run(self.profile,self.config,prepare=True)
        with patch.object(calibration.time,'time',return_value=time.time()+181):
            with self.assertRaisesRegex(policy.CheckError,'180second'):
                calibration.resume(self.campaign,self.profile)
        with self.assertRaisesRegex(policy.CheckError,'prior attribution'):
            calibration.resume(self.campaign,self.profile,prepare=True)
        self.assertEqual(calibration.status(self.campaign)['consumed_slots'],0)

    @unittest.skipUnless(core.BWRAP,'bwrap required')
    def test_native_http_calibration_loop_root_feedback_repair_and_offline_replay(self):
        endpoint=existing.NativeSoftwareEndpoint();self.addCleanup(endpoint.close)
        (self.work/'live-software').mkdir()
        config=existing.pair(self.work/'live-software',endpoint.url)
        profile=config['profiles']['A'];endpoint.profile=profile
        endpoint.readiness_script=[('list_dir',{'path':'/workspace'}),
            ('read_file',{'path':'formatters.py'}),
            ('write_file',{'path':'formatters.py','content':core.QUAL_REFERENCE_FORMATTERS}),
            ('run',{'command':'./run_tests.sh'}),('finish',{'report':'Tests pass.'})]
        calibration.run(profile,config,prepare=True)
        state=calibration.run(profile,config)
        unit=next(v for v in state['units'].values() if v)
        self.assertEqual(unit['outcome'],'PASS',unit.get('evaluation'))
        self.assertEqual(len(endpoint.calls),5)
        root_feedback=json.loads(endpoint.calls[1]['messages'][-1]['content'])
        self.assertTrue(root_feedback['ok']);self.assertIn('formatters.py',root_feedback['entries'])
        self.assertEqual(endpoint.calls[1]['messages'][-1]['tool_call_id'],'synthetic-1')
        target=calibration.section_path(profile['campaign_root'])
        path=Path(unit['path'])
        self.assertTrue(store.read_json(path/'quiescence.json')['observations_drained'])
        self.assertFalse(unit['scientific_credit'])
        self.assertEqual(unit['evidence_kind'],'SOFTWARE_TEST')
        self.assertFalse(agentic.readiness_admission(unit)['admitted'])
        calibration._stop(target,'SOFTWARE_TEST_BOUNDED_SMOKE')
        endpoint.close()
        receipt=calibration.report(profile['campaign_root'])
        manifest=policy.file_sha(target/'manifest.json')
        self.assertEqual(calibration.report(profile['campaign_root']),receipt)
        self.assertEqual(calibration.resume(profile['campaign_root'])['consumed_slots'],1)
        self.assertEqual(policy.file_sha(target/'manifest.json'),manifest)
        self.assertEqual(len(store.attempts(target,unit['unit_id'])),1)


if __name__=='__main__':unittest.main()
